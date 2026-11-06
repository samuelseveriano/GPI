"""Product Research — pesquisa de um produto específico pelo nome (pt/en), em DUAS camadas:

1. **Dados locais**: SQLite, cache, catálogo, inteligência e histórico já existentes.
2. **Consultas direcionadas** (`targeted.py`): as fontes externas autorizadas que aceitam pesquisa por produto são
   consultadas quando faltam evidências ou quando a atualização é pedida. Um produto ausente do banco local pode ser
   investigado do zero; se nenhuma fonte estiver disponível, o dossiê lista os impedimentos concretos.

Rápida × completa (mesma infraestrutura):
* **Rápida** — cache primeiro (validade 7 dias), poucas fontes do mercado principal, avaliação preliminar.
* **Completa** — reaproveita a rápida (cache de até 1 dia), consulta fontes adicionais e os mercados de comparação,
  executa as análises estatísticas elegíveis e produz o dossiê aprofundado.

Progresso ≠ sucesso: cada etapa termina com um estado explícito (com dados, sem dados, ignorada por configuração, não
autorizada, indisponível, falhou, cancelada). O dossiê mostra separadamente o PROGRESSO do processamento e a COBERTURA
da investigação; sem evidência útil, o resultado é "Processamento concluído — dados insuficientes para análise comercial"."""
from __future__ import annotations

import json
import threading
import traceback
from datetime import date, timedelta

import numpy as np

from . import importx as IX
from . import marketplace as MK
from . import naming as NM
from . import store as S
from . import suppliers as SP
from . import targeted as TG

STEPS = [("entender", "Entender o produto (Product Understanding)"), ("catalogo", "Localizar no catálogo e na inteligência local"),
         ("coleta", "Consultas direcionadas nas fontes autorizadas"), ("demanda", "Demanda e pesquisa"),
         ("marketplaces", "Anúncios e preços"), ("semelhantes", "Produtos semelhantes"), ("fornecedores", "Fornecedores candidatos"),
         ("importacao", "NCM, regulatório e riscos"), ("qualidade", "Qualidade dos dados"), ("previsoes", "Tendências e previsões"),
         ("evidencias", "Registrar evidências"), ("decisao", "Classificar a decisão")]
QUICK_SKIP = {"previsoes"}
STEP_STATES = ["concluída com dados", "concluída sem dados", "ignorada por configuração", "não autorizada", "indisponível", "falhou",
               "cancelada"]
ENDED = set(STEP_STATES)
INSUFFICIENT = "Processamento concluído — dados insuficientes para análise comercial."
GOALS = ["importar para revenda", "avaliar demanda", "comparar mercados", "encontrar fornecedores", "monitorar"]
_running: dict[int, threading.Thread] = {}


def _period(params: dict, today: date) -> tuple[str, str]:
    if params.get("inicio") and params.get("fim"):
        return str(params["inicio"])[:10], str(params["fim"])[:10]
    m = int(params.get("periodo_meses") or 12)
    m = m if m in (3, 6, 12, 24) else 12
    return (today - timedelta(days=round(m * 30.44))).isoformat(), today.isoformat()


def create(db, query: str, params: dict) -> int:
    S.ensure(db)
    q = (query or "").strip()[:200]
    if len(q) < 2:
        raise ValueError("informe o nome do produto")
    steps = [{"id": k, "nome": n, "estado": "pendente"} for k, n in STEPS]
    cur = db.execute("INSERT INTO research_jobs (kind, query, params, status, steps, created_at) VALUES ('produto', ?, ?, 'na fila', ?, ?)",
                     (q, json.dumps(params, ensure_ascii=False), json.dumps(steps, ensure_ascii=False), S.now()))
    return cur.lastrowid


def progress(steps: list[dict]) -> dict:
    ended = [s for s in steps if s["estado"] in ENDED]
    by = {k: sum(1 for s in steps if s["estado"] == k) for k in STEP_STATES}
    return {"encerradas": len(ended), "concluidas": len(ended), "total": len(steps),
            "pct": round(100 * len(ended) / len(steps)) if steps else 0, "por_estado": {k: v for k, v in by.items() if v},
            "nota": "Progresso do processamento (etapas encerradas ÷ previstas). Não indica sucesso da análise — veja a cobertura."}


def get(db, rid: int) -> dict | None:
    S.ensure(db)
    r = db.query("SELECT * FROM research_jobs WHERE id = ?", (rid,))
    if not r:
        return None
    j = r[0]
    j["params"] = json.loads(j["params"] or "{}")
    j["steps"] = json.loads(j["steps"] or "[]")
    j["result"] = json.loads(j["result"]) if j["result"] else None
    j["progresso"] = progress(j["steps"])
    j["cobertura"] = (j["result"] or {}).get("cobertura")
    return j


def history(db, limit: int = 200) -> list[dict]:
    S.ensure(db)
    rows = db.query("SELECT id, kind, query, params, status, product_id, created_at, finished_at, saved, result FROM research_jobs ORDER BY id DESC LIMIT ?",
                    (limit,))
    for r in rows:
        r["params"] = json.loads(r["params"] or "{}")
        res = json.loads(r.pop("result") or "null") or {}
        r["nome_comercial"] = ((res.get("abas") or {}).get("visao_geral") or {}).get("produto")
        r["decisao"] = (res.get("decisao") or {}).get("cor")
        r["cobertura"] = (res.get("cobertura") or {}).get("fontes_com_evidencia")
        r["conclusiva"] = bool(res.get("conclusiva"))
    return rows


def cancel(db, rid: int) -> dict:
    S.ensure(db)
    db.execute("UPDATE research_jobs SET status = 'cancelando' WHERE id = ? AND finished_at IS NULL", (rid,))
    return {"ok": True}


def start(db, rid: int, ctx: dict) -> None:
    t = threading.Thread(target=run, args=(db, rid, ctx), daemon=True, name=f"gpi-pesquisa-{rid}")
    _running[rid] = t
    t.start()


def run(db, rid: int, ctx: dict) -> dict:
    """ctx: payload_fn, stages_fn, ncm, today, cfg e sync_ctx_fn (contexto dos conectores para as consultas direcionadas)."""
    j = get(db, rid)
    steps = j["steps"]
    params = j["params"]
    today = ctx["today"]
    deep = params.get("profundidade", "rapida") == "completa"
    out = {"consulta": j["query"], "parametros": params, "abas": {}, "modo": "completa" if deep else "rapida"}
    st = {"u": None, "p": None, "stage": None, "pid": None, "terms": None, "collected": [], "direct": {}}

    def cancelled():
        r = db.query("SELECT status FROM research_jobs WHERE id = ?", (rid,))
        return bool(r) and r[0]["status"] == "cancelando"

    def mark(i, estado, detalhe=None):
        steps[i]["estado"] = estado
        if detalhe:
            steps[i]["detalhe"] = detalhe
        db.execute("UPDATE research_jobs SET steps = ?, status = CASE WHEN status = 'cancelando' THEN status ELSE 'executando' END WHERE id = ?",
                   (json.dumps(steps, ensure_ascii=False), rid))

    funcs = {"entender": _s_understand, "catalogo": _s_catalog, "coleta": _s_collect, "demanda": _s_demand, "marketplaces": _s_markets,
             "semelhantes": _s_similar, "fornecedores": _s_suppliers, "importacao": _s_import, "qualidade": _s_quality,
             "previsoes": _s_forecast, "evidencias": _s_evidence, "decisao": _s_decision}
    failed = 0
    was_cancelled = False
    for i, (k, _) in enumerate(STEPS):
        if was_cancelled or cancelled():
            was_cancelled = True
            mark(i, "cancelada", "pesquisa cancelada pelo usuário")
            continue
        if k in QUICK_SKIP and not deep:
            mark(i, "ignorada por configuração", "pesquisa rápida (a completa inclui tendências e previsões)")
            continue
        mark(i, "executando")
        try:
            r = funcs[k](db, ctx, params, out, st, rid, today, cancelled)
            estado, det = r if isinstance(r, tuple) else ("concluída com dados", r)
            mark(i, estado, det)
        except Exception as e:  # noqa: BLE001
            failed += 1
            mark(i, "falhou", f"{type(e).__name__}: {str(e)[:200]}")
            out.setdefault("erros", []).append({"etapa": k, "erro": type(e).__name__, "detalhe": traceback.format_exc(limit=2)[-600:]})
    if "decisao" not in out:
        out["decisao"] = IX.classify_decision(None, None)
    ncom = ((out.get("coberturas") or {}).get("comercial") or {}).get("n", 0)
    out["conclusiva"] = bool(ncom) and out["decisao"]["cor"] != "CINZA"
    out["mensagem_final"] = (INSUFFICIENT if not ncom or out["decisao"]["cor"] == "CINZA"
                             else "Processamento concluído — evidências suficientes para uma avaliação " +
                             ("preliminar." if out["decisao"]["cor"] == "AMARELO" else "comercial."))
    out["resultado"] = summary(db, rid, out)
    status = ("cancelada" if was_cancelled else "concluída com falhas" if failed else
              "concluída — dados insuficientes" if not out["conclusiva"] else "concluída")
    db.execute("UPDATE research_jobs SET status = ?, result = ?, product_id = ?, finished_at = ?, steps = ? WHERE id = ?",
               (status, json.dumps(out, ensure_ascii=False, default=str), st["pid"], S.now(), json.dumps(steps, ensure_ascii=False), rid))
    _running.pop(rid, None)
    return out


def summary(db, rid, out) -> dict:
    """Bloco 'Resultado': classificação executiva, confiança, evidências, limitações e próximas ações objetivas
    (cada fonte ausente vira um botão para a integração correspondente)."""
    cov = out.get("coberturas") or {}
    dec = out.get("decisao") or {}
    ov = (out.get("abas") or {}).get("visao_geral") or {}
    lim, acts = [], []
    for r in out.get("fontes") or []:
        if r.get("tipo") != "consulta direcionada":
            continue
        if r["estado"] == "não autorizada":
            acts.append({"texto": f"{r['fonte']} não conectado — abrir Central de Integrações", "link": r.get("central") or "#integracoes"})
        elif r["estado"] in ("limite de requisições", "bloqueada pela rede", "indisponível", "falhou"):
            lim.append(f"{r['fonte']} ({r['mercado']}): {r.get('motivo') or r['estado']}")
    for k, v in ((out.get("mercados") or {}).get("cobertura") or {}).items():
        if v.get("mensagem") and k != "GLOBAL":
            lim.append(f"{k}: {v['mensagem']}")
    for f in ((ov.get("estagio_direto") or {}).get("faltando") or []):
        acts.append({"texto": f"Obter {f}", "link": None})
    if (cov.get("comercial") or {}).get("n", 0) == 0:
        lim.append("Sem evidência comercial: a classificação permanece CINZA (imagens, notícias e fornecedores não comprovam demanda).")
    seen, uniq = set(), []
    for a in acts:
        if a["texto"] not in seen:
            seen.add(a["texto"])
            uniq.append(a)
    n_ev = db.query("SELECT COUNT(*) AS n FROM research_evidence WHERE research_id = ?", (rid,))[0]["n"]
    return {"classificacao": dec.get("cor"), "significado": dec.get("significado"), "confianca": (cov.get("confianca") or {}),
            "evidencias": n_ev, "limitacoes": lim, "proximas_acoes": uniq[:10]}


def _with_data(n, det):
    return ("concluída com dados" if n else "concluída sem dados", det)


# ------------------------------------------------------------------------------------------------- etapas
def _s_understand(db, ctx, params, out, st, rid, today, cancelled):
    from ..intel import understanding as U
    u = U.understand(out["consulta"], params.get("idioma") or None)
    st["u"] = u
    out["abas"]["visao_geral"] = {"entendimento": {k: u.get(k) for k in ("principal", "produto_id", "estado", "nivel_rotulo", "taxonomia",
                                                                         "atributos", "contexto", "motivos")}}
    ok = u.get("estado") == "confirmada"
    return ("concluída com dados" if ok else "concluída sem dados",
            f"{u.get('estado')}: {NM.name_of(db, u.get('produto_id')) or 'produto não identificado'}")


def _s_catalog(db, ctx, params, out, st, rid, today, cancelled):
    from ..products.catalog import Catalog
    u = st["u"]
    payload = ctx["payload_fn"]()
    prods = payload.get("produtos") or {}
    cat = Catalog(db, ctx.get("cfg") or {})
    m = cat.match(out["consulta"])
    cands = [x for x in ((m or {}).get("variante"), (m or {}).get("familia"), u.get("produto_id"), u.get("principal")) if x]
    pid = next((c for c in cands if c in prods), None) or next(iter(cands), None)
    created = False
    if not m and u.get("estado") == "confirmada" and u.get("produto_id"):
        # produto ausente do catálogo: registro canônico só com identificação CONFIRMADA pelo Product Understanding
        got = cat.observe(out["consulta"], "pesquisa_usuario", params.get("mercado"), "compra", strong=True, lang=params.get("idioma"))
        created = bool(got)
        pid = got or pid
    st["pid"] = pid
    st["p"] = prods.get(pid) if pid else None
    stages = ctx["stages_fn"]()
    item = next((x for x in stages["itens"] if x["produto_id"] == pid), None)
    st["stage"] = item["estagio_evidencia"] if item else None
    d = NM.describe(db, pid, u)
    st["terms"] = {"pt": d["traducoes"].get("pt") or out["consulta"], "en": d["traducoes"].get("en") or out["consulta"]}
    ov = out["abas"]["visao_geral"]
    ov.update({"identificacao": d, "produto_id": pid, "produto": d["nome_comercial"] or out["consulta"], "no_catalogo": bool(m) or created,
               "registro_criado": created, "na_inteligencia": st["p"] is not None, "situacao": (st["p"] or {}).get("situacao"),
               "estagio": item["estagio"] if item else 0,
               "nome_estagio": item["nome_estagio"] if item else ("Identificado" if pid else "Não identificado"),
               "proximas_acoes": item["proximas_acoes"] if item else [], "indicadores": IX.indicators(st["p"], today.isoformat()),
               "investigar_url": f"#dossie/{pid}" if st["p"] else None, "termos_consulta": st["terms"]})
    local_n = len((st["p"] or {}).get("evidencias") or [])
    st["local_n"] = local_n
    det = ("na inteligência local" if st["p"] else "registro canônico criado (identificação confirmada)" if created
           else "no catálogo, sem evidências locais" if pid else "fora do catálogo — será investigado nas fontes externas")
    return _with_data(local_n, det)


def _markets(params):
    markets = [params.get("mercado") or "BR", *[m for m in (params.get("comparacao") or []) if m]][:6]
    return list(dict.fromkeys(str(m).upper() for m in markets))


NOT_PLANNED = ("ignorada (modo rápido)", "não cobre o mercado")
FAILED = ("indisponível", "falhou", "não autorizada", "limite de requisições", "bloqueada pela rede")


def _s_collect(db, ctx, params, out, st, rid, today, cancelled):
    mode = "completa" if params.get("profundidade") == "completa" else "rapida"
    markets = _markets(params)
    force = bool(params.get("atualizar"))
    need = force or mode == "completa" or not st.get("local_n")
    cov = TG.market_coverage(mode, markets)
    out["mercados"] = {"principal": markets[0], "comparativos": markets[1:], "cobertura": cov,
                       "comparacao_ativa": mode == "completa" and len(markets) > 1}
    st["main_market"] = markets[0]
    if not ctx.get("sync_ctx_fn"):
        st["collected"] = []
        out["coleta"] = {"realizada": False, "motivo": "conectores indisponíveis neste contexto"}
        return "indisponível", "contexto de conectores indisponível"
    if not need:
        st["collected"] = [{"id": sid, **TG._base(sid, m, role), "estado": "ignorada (modo rápido)", "consulta_realizada": False, "registros": 0,
                            "motivo": "evidências locais suficientes para a avaliação rápida; use 'Atualizar fontes' para consultar",
                            "acao": "marcar 'Atualizar fontes' ou usar a pesquisa completa"} for sid, m, role in TG.plan(mode, markets)]
        out["coleta"] = {"realizada": False, "motivo": "pesquisa rápida com evidências locais (cache)"}
        return "ignorada por configuração", "evidências locais disponíveis; consulta externa não necessária na rápida"
    res = TG.collect(db, ctx["sync_ctx_fn"], st["terms"]["pt"], st["terms"]["en"], st["pid"], markets, mode, force, rid, cancelled)
    st["collected"] = res
    useful = [r for r in res if r["estado"] in TG.USEFUL and r["registros"]]
    planned = [r for r in res if r["estado"] not in NOT_PLANNED]
    out["coleta"] = {"realizada": True, "modo": mode, "mercados": markets, "atualizacao_forcada": force, "resultados": res,
                     "invalidados": TG.invalidate(db, res, st.get("pid"))}
    if not any(r["papel"] == "principal" for r in planned):
        return "indisponível", f"{markets[0]}: {TG.NO_COVERAGE}"
    det = f"{len(useful)} fonte(s) com dados de {len(planned)} consulta(s) prevista(s)"
    if useful:
        return "concluída com dados", det
    if planned and all(r["estado"] == "não autorizada" for r in planned):
        return "não autorizada", "nenhuma fonte direcionada autorizada: " + "; ".join(sorted({r["fonte"] for r in planned}))
    if planned and all(r["estado"] in FAILED for r in planned):
        return "indisponível", det
    return "concluída sem dados", det


def _terms_q(st, out):
    t = st.get("terms") or {}
    return [x for x in {t.get("pt"), t.get("en"), out["consulta"]} if x]


def _volume_series(db, terms, pid, since):
    """Séries mensais de volume de fontes AUTORIZADAS (Keyword Planner / Bing), por fonte e mercado."""
    from ..products import nlp
    norms = [nlp._norm(t) for t in terms]
    rows = db.query("SELECT source, country, term, ref_date, value FROM search_observations WHERE source IN ('google_ads_kp', 'msads_kp') "
                    "AND ref_date >= ? AND (product_id = ? OR LOWER(term) IN (%s)) ORDER BY ref_date" % ",".join("?" * len(norms)),
                    (since[:7] + "-01", pid or "§", *norms))
    by = {}
    for r in rows:
        by.setdefault((r["source"], r["country"]), {}).setdefault(r["ref_date"][:7], []).append(r["value"])
    return {k: sorted((m, float(np.mean(v))) for m, v in d.items()) for k, d in by.items()}


def _s_demand(db, ctx, params, out, st, rid, today, cancelled):
    from ..analytics.classification import trend_test
    since, until = _period(params, today)
    markets = _markets(params)
    evs = [e for e in (st["p"] or {}).get("evidencias") or []]
    kw = MK.keywords(db, st["terms"]["pt"] if st.get("terms") else out["consulta"])
    vols = _volume_series(db, _terms_q(st, out), st["pid"], since)
    series = []
    for (src, cc), pts in vols.items():
        y = [v for _, v in pts]
        tt = trend_test(np.asarray(y)) if len(y) >= 6 else None
        series.append({"fonte": src, "mercado": cc, "meses": len(pts), "ultimo": pts[-1][1] if pts else None, "inicio": pts[0][0] if pts else None,
                       "fim": pts[-1][0] if pts else None, "tendencia": {k: tt.get(k) for k in ("direcao", "p_valor", "significativa")} if tt else None,
                       "pontos": pts, "papel": "principal" if cc == markets[0] else ("comparativo" if cc in markets else "fora da seleção")})
    series = [x for x in series if x["papel"] != "fora da seleção"]
    st["direct"]["volume"] = [x for x in series if x["papel"] == "principal"]        # decisão = mercado principal
    st["direct"]["volume_all"] = series
    news = db.query("SELECT ref_date, value FROM search_observations WHERE source = 'gdelt' AND term IN (%s) AND ref_date >= ? ORDER BY ref_date"
                    % ",".join("?" * len(_terms_q(st, out))), (*_terms_q(st, out), since[:7] + "-01"))
    rows = []
    for i, m in enumerate(markets):
        mrows = [r for r in kw["observadas"] if r["mercado"] in (m, f"GLOBAL:{params.get('idioma') or 'pt'}") and r["ultimo"] >= since[:len(r["ultimo"])]]
        rows.append({"mercado": m, "termos_observados": len(mrows), "com_volume": sum(1 for r in mrows if r["classe"] == "com volume verificado"),
                     "com_historico": sum(1 for r in mrows if r["classe"] == "com histórico"), "exemplos": mrows[:8],
                     "volume": [s for s in series if s["mercado"] == m], "papel": "principal" if i == 0 else "comparativo"})
    out["abas"]["demanda"] = {"periodo": [since, until], "mercados": rows, "volume_autorizado": series,
                              "comparacao_mercados": params.get("profundidade") == "completa" and len(markets) > 1,
                              "noticias_gdelt": {"meses": len(news), "artigos": sum(n["value"] for n in news), "mercado": "GLOBAL",
                                                 "nota": "Atenção pública na imprensa, cobertura GLOBAL — NÃO é demanda e não é atribuída ao Brasil."} if news else None,
                              "evidencias_inteligencia": [{k: e.get(k) for k in ("fonte_nome", "tipo_rotulo", "indicador", "mercado", "periodo",
                                                                                  "observacoes_n", "nao_e")} for e in evs],
                              "traducoes": kw["traducoes"], "palavras_geradas": kw["geradas"][:20], "legenda": kw["legenda"], "aviso": kw["aviso"],
                              "vazio": None if (evs or series or any(r["termos_observados"] for r in rows)) else
                              "Sem observações de pesquisa para este produto no período (veja 'Fontes e cobertura')."}
    return _with_data(len(evs) + len(series), f"{len(evs)} evidência(s) locais; {len(series)} série(s) de volume autorizado")


def _s_markets(db, ctx, params, out, st, rid, today, cancelled):
    pid = st["pid"]
    terms = _terms_q(st, out)
    markets = _markets(params)
    mode = "completa" if params.get("profundidade") == "completa" else "rapida"
    src_of = lambda m: [k for k, v in MK.SOURCE_MARKET.items() if v == m]  # noqa: E731
    per_market = {}
    for i, m in enumerate(markets if mode == "completa" else markets[:1]):
        srcs = src_of(m)
        ls = MK.listing_stats(db, pid, 30, today, terms, srcs) if srcs else None
        ls90 = MK.listing_stats(db, pid, 90, today, terms, srcs) if srcs else None
        per_market[m] = {"papel": "principal" if i == 0 else "comparativo", "fontes": srcs, "ultimos_30_dias": ls, "ultimos_90_dias": ls90,
                         "mensagem": None if srcs else "Nenhum marketplace com consulta direcionada para este mercado."}
    main = per_market[markets[0]]
    ls, ls90 = main["ultimos_30_dias"], main["ultimos_90_dias"]
    recent = db.query("SELECT source, item_id, title, brand, price, currency, seller, MAX(day) AS dia, MIN(day) AS primeiro, COUNT(DISTINCT day) AS dias, url "
                      "FROM market_listings WHERE product_id = ? OR product_id LIKE ? OR query IN (%s) GROUP BY source, item_id ORDER BY dia DESC LIMIT 60"
                      % ",".join("?" * len(terms)), (pid or "§", (pid or "§") + ":%", *terms))
    from . import listing_match as LM
    for r in recent:
        r["correspondencia"] = LM.classify(r["title"], pid)
        r["mercado"] = MK.SOURCE_MARKET.get(r["source"], "—")
        r["papel"] = "principal" if r["mercado"] == markets[0] else "comparativo"
    main_items = [r for r in recent if r["papel"] == "principal"]
    # SÓ o mercado principal e SÓ anúncios do produto/variante compatível entram na decisão (cabos/acessórios ficam fora)
    st["direct"]["listings"] = (ls or ls90 or {}).get("anuncios_elegiveis") if pid else 0
    st["direct"]["listings"] = st["direct"]["listings"] or 0
    st["direct"]["listing_sources"] = (ls or ls90 or {}).get("fontes", [])
    st["direct"]["price_history"] = sum(1 for r in main_items if r["dias"] >= 2 and r["correspondencia"]["elegivel"])
    out["abas"]["marketplaces"] = {"mercado_principal": markets[0], "ultimos_30_dias": ls, "ultimos_90_dias": ls90, "por_mercado": per_market,
                                   "anuncios": recent[:40], "competicao": MK.competition(ls),
                                   "historico_precos": {"anuncios_com_2_ou_mais_coletas": st["direct"]["price_history"],
                                                        "nota": "histórico só com observações reais (dias sem coleta não são preenchidos)"},
                                   "nao_disponivel": ["vendas", "receita", "unidades vendidas"],
                                   "vazio": None if ls or ls90 else (main["mensagem"] or "Nenhum anúncio no mercado principal (veja 'Fontes e cobertura')."),
                                   "aviso": MK.AUTH_NOTE + " Preço anunciado ≠ preço de venda; quantidade de anúncios não é demanda. "
                                            "Anúncios de mercados comparativos não são atribuídos ao mercado principal."}
    out["abas"]["marketplaces"]["indicadores_comerciais"] = commercial_indicators(db, pid)
    return _with_data(st["direct"]["listings"], f"{(ls or ls90 or {}).get('anuncios', 0)} anúncio(s) no mercado principal ({markets[0]}), "
                                                f"{st['direct']['listings']} elegível(is) para comparação")


def _s_similar(db, ctx, params, out, st, rid, today, cancelled):
    pid = st["pid"]
    if not pid:
        out["abas"]["semelhantes"] = {"grupos": {}, "itens": [], "vazio": "Produto não identificado — sem base para comparação."}
        return "concluída sem dados", "produto não identificado"
    res = similar_products(db, pid, st["u"], ctx["payload_fn"]().get("produtos") or {}, today, deep=params.get("profundidade") == "completa")
    out["abas"]["semelhantes"] = res
    return _with_data(len(res["itens"]), f"{len(res['itens'])} produto(s) em {sum(1 for v in res['grupos'].values() if v)} grupo(s)")


def commercial_indicators(db, pid) -> dict:
    """Indicadores comerciais do produto (oferta observada por mercado, já filtrada) e a linha correspondente do
    Opportunity Engine — atualizados pela própria coleta (targeted.invalidate → refresh_commercial)."""
    if not pid:
        return {"itens": [], "oportunidade": None, "vazio": "Produto não identificado."}
    comp = TG._load(db, "competition")
    items = [x for x in (comp or {}).get("itens", []) if x.get("product_id") == pid]
    opp3 = TG._load(db, "opportunity3")
    if comp is None or opp3 is None or (not items and db.query("SELECT 1 FROM market_listings WHERE product_id = ? LIMIT 1", (pid,))):
        opp3 = TG.refresh_commercial(db, {pid}).get("opportunity3") or opp3
        items = [x for x in (TG._load(db, "competition") or {}).get("itens", []) if x.get("product_id") == pid]
    opp = next((r for r in (opp3 or {}).get("produtos", []) if r.get("product_id") == pid), None)
    lim = ["Anúncios são oferta observada: não são vendas, demanda comprovada nem participação de mercado."]
    if items and all((x.get("dias_observados") or 0) < 2 for x in items):
        lim.append("Coleta única: nenhuma tendência ou crescimento é atribuído.")
    if any(x.get("mercado") != "BR" for x in items):
        lim.append("Oferta fora do Brasil (ex.: eBay/EUA) é contexto: não altera indicadores do mercado brasileiro.")
    if opp and not opp.get("elegivel_para_decisao"):
        lim.append("Índice de oportunidade parcial — não elegível para decisão (evidência insuficiente).")
    return {"itens": items, "oportunidade": opp and {k: opp.get(k) for k in ("prioridade", "indice", "indice_parcial", "elegivel_para_decisao",
                                                                             "explicacao", "tipos_de_evidencia", "oferta_observada", "riscos",
                                                                             "proximos_passos")},
            "limitacoes": lim, "vazio": None if items else "Sem anúncios elegíveis deste produto."}


SIM_CLASSES = ["Possível mesmo produto", "Variante da mesma família", "Produto tecnicamente semelhante", "Produto da mesma categoria",
               "Similaridade visual", "Correspondência não confirmada"]


def similar_products(db, pid, u, payload_products, today, deep=False) -> dict:
    """Classifica cada produto relacionado. Mesma categoria NÃO é equivalência; semelhança visual NÃO é mesmo fabricante."""
    from ..intel import understanding as U
    fam_id = pid.split(":")[0]
    me = db.query("SELECT product_id, family, category, parent_id FROM catalog_products WHERE product_id IN (?, ?) ORDER BY (product_id = ?) DESC",
                  (pid, fam_id, pid))
    head = (me[0]["family"] if me else None) or fam_id.split("+")[0]
    cat = me[0]["category"] if me else None
    rows = db.query("SELECT product_id, name_pt, name_en, level, parent_id, family, category FROM catalog_products WHERE product_id != ? AND "
                    "(parent_id = ? OR product_id = ? OR family = ? OR category = ?) LIMIT 400", (pid, fam_id, fam_id, head, cat or "§"))
    items = []
    for r in rows:
        if r["product_id"] == fam_id or r["parent_id"] == fam_id:
            cls, why = (SIM_CLASSES[1], "mesma família no catálogo; variante diferente" if r["parent_id"] == fam_id
                        else "família da variante pesquisada (variante não especificada)")
        elif r["family"] == head:
            cls, why = SIM_CLASSES[2], f"mesmo tipo de produto ({head}) com qualificadores/tecnologia diferentes"
        else:
            cls, why = SIM_CLASSES[3], f"mesma categoria ({r['category']}) — NÃO é equivalente"
        items.append(_sim_item(db, r["product_id"], cls, why, payload_products, today))
    # possível mesmo produto: aliases/variantes no catálogo cujo texto é entendido como o MESMO produto
    # (exclui a família e as variantes-irmãs: essas já são "Variante da mesma família")
    kin = {r["product_id"] for r in rows if r["product_id"] == fam_id or r["parent_id"] == fam_id} | {fam_id}
    for a in db.query("SELECT DISTINCT product_id, alias FROM product_aliases WHERE product_id != ? AND product_id LIKE ? LIMIT 100", (pid, fam_id + "%")):
        if a["product_id"] in kin or a["product_id"].split(":")[0] == fam_id:
            continue
        uu = U.understand(a["alias"], None, target=pid)
        if uu.get("relacao_alvo") == "corresponde" and uu.get("estado") == "confirmada":
            items = [i for i in items if i["produto_id"] != a["product_id"]]
            items.append(_sim_item(db, a["product_id"], SIM_CLASSES[0], f"alias '{a['alias']}' entendido como o mesmo produto", payload_products, today))
        elif (uu.get("estado") == "ambigua" or uu.get("relacao_alvo") == "ambigua") and not any(i["produto_id"] == a["product_id"] for i in items):
            items.append(_sim_item(db, a["product_id"], SIM_CLASSES[5], f"alias '{a['alias']}' com identificação ambígua", payload_products, today))
    # similaridade visual: imagens do catálogo deste produto × imagens de outros produtos (hashes locais)
    vis = visual_neighbors(db, pid) if deep else []
    for v in vis:
        items.append(_sim_item(db, v["product_id"], SIM_CLASSES[4], f"{v['classe']} (similaridade {v['similaridade']:.2f}) — "
                               "semelhança visual não comprova o mesmo fabricante", payload_products, today))
    seen, uniq = set(), []
    order = {c: i for i, c in enumerate(SIM_CLASSES)}
    for i in sorted(items, key=lambda x: (order[x["classe"]], -(x["opportunity_score"] or -1))):
        k = (i["produto_id"], i["classe"])
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    groups = {c: [i for i in uniq if i["classe"] == c][:15] for c in SIM_CLASSES}
    return {"grupos": groups, "itens": [i for c in SIM_CLASSES for i in groups[c]], "classes": SIM_CLASSES,
            "avisos": ["Produtos da mesma categoria não são equivalentes.", "Semelhança visual não comprova o mesmo fabricante.",
                       "Similaridade visual só é calculada na pesquisa completa e depende do catálogo visual."]}


def _sim_item(db, p2, cls, why, payload_products, today):
    p = payload_products.get(p2)
    return {"produto_id": p2, "nome": NM.name_of(db, p2) or p2, "classe": cls, "relacao": cls, "motivo": why, "situacao": (p or {}).get("situacao"),
            "opportunity_score": ((p or {}).get("indices") or {}).get("opportunity_score"),
            "anuncios_30d": (MK.listing_stats(db, p2, 30, today) or {}).get("anuncios")}


def visual_neighbors(db, pid) -> list[dict]:
    from . import visual as V
    mine = db.query("SELECT * FROM product_images WHERE product_id = ? OR product_id LIKE ?", (pid, pid.split(":")[0] + ":%"))
    if not mine:
        return []
    others = db.query("SELECT * FROM product_images WHERE product_id IS NOT NULL AND product_id != ? AND product_id NOT LIKE ?",
                      (pid, pid.split(":")[0] + ":%"))
    best = {}
    for a in mine:
        qa = {**a, "color": json.loads(a["color"] or "[]")}
        for b in others:
            cls, sim, _ = V.classify(qa, {**b, "color": json.loads(b["color"] or "[]")}, False)
            if cls in V.CLASSES[:5] and sim > best.get(b["product_id"], {}).get("similaridade", 0):
                best[b["product_id"]] = {"product_id": b["product_id"], "classe": cls, "similaridade": sim}
    return sorted(best.values(), key=lambda x: -x["similaridade"])[:10]


def _s_suppliers(db, ctx, params, out, st, rid, today, cancelled):
    fam = (st["pid"] or "").split(":")[0] or None
    d = SP.discover(db, st["terms"]["pt"] if st.get("terms") else out["consulta"], family=fam, product_id=st["pid"], limit=30,
                    extra_terms=[st["terms"]["en"]] if st.get("terms") else None)
    d["produto"] = NM.name_of(db, st["pid"]) or out["consulta"]
    out["abas"]["fornecedores"] = d
    return _with_data(len(d["candidatos"]), f"{len(d['candidatos'])} candidato(s)")


def _s_import(db, ctx, params, out, st, rid, today, cancelled):
    cat = db.query("SELECT ncm_hint FROM catalog_products WHERE product_id = ?", ((st["pid"] or "").split(":")[0],)) if st["pid"] else []
    text = st["terms"]["pt"] if st.get("terms") else out["consulta"]
    ncm = IX.ncm_block(db, ctx.get("ncm"), text, (cat[0]["ncm_hint"] if cat else None))
    reg = IX.regulatory_block(db, text)
    ls = (out["abas"].get("marketplaces") or {}).get("ultimos_30_dias")
    st["ncm_state"] = {"candidatas": len(ncm["candidatas"]), "series": len(ncm["estatisticas_agregadas"])}
    out["abas"]["importacao"] = {"ncm": ncm, "regulatorio": reg, "riscos": IX.risks(st["u"], reg, ncm, ls),
                                 "cenarios_salvos": IX.list_scenarios(db, st["pid"]) if st["pid"] else [],
                                 "simulador": {"campos": IX.FIELDS, "obrigatorios": IX.REQUIRED}}
    n = len(ncm["candidatas"]) + reg.get("registros_encontrados", 0)
    return _with_data(n, f"{len(ncm['candidatas'])} NCM candidata(s); {reg.get('registros_encontrados', 0)} registro(s) regulatório(s)")


def _s_quality(db, ctx, params, out, st, rid, today, cancelled):
    from ..intel.semantics import origin_of
    p = st["p"] or {}
    evs = p.get("evidencias") or []
    origins = {}
    for e in evs:
        o = origin_of(e.get("fonte") or "", e.get("camada") or "observado", e.get("metrica") or "")
        origins[o] = origins.get(o, 0) + 1
    try:
        from ..intel import understanding as U
        U.ensure(db)
        fam = (st["pid"] or "§").split(":")[0]
        pend = db.query("SELECT COUNT(*) AS n FROM association_review WHERE decisao IS NULL AND (sugestao = ? OR sugestao LIKE ?)",
                        (st["pid"] or "§", fam + "%"))
    except Exception:  # noqa: BLE001
        pend = [{"n": None}]
    visual_n = db.query("SELECT COUNT(*) AS n FROM product_images")[0]["n"]
    diag = TG.diagnostics(db, st.get("collected") or [], {"n": len(evs)}, st.get("ncm_state") or {}, visual_n)
    cov = TG.coverage(diag)
    out["fontes"] = diag
    out["cobertura"] = cov
    out["coberturas"] = coverage_by_type(db, out, st, diag)
    out["cobertura"]["confianca"] = out["coberturas"]["confianca"]
    ind = IX.indicators(st["p"], today.isoformat())
    out["abas"]["qualidade"] = {"evidence_coverage": ind["evidence_coverage"], "frescor": ind["data_freshness"], "origens": origins,
                                "identificacao": (st["u"] or {}).get("estado"), "associacoes_em_revisao": pend[0]["n"],
                                "cobertura_investigacao": cov, "coberturas": out["coberturas"], "fontes": sorted({e.get("fonte_nome") or e.get("fonte") for e in evs} | set(cov["fontes"])),
                                "regras": ["Dados DEMONSTRATIVOS/SIMULADOS nunca entram como evidência comercial.",
                                           "Identificação não confirmada impede recomendação (VERDE).",
                                           "Notícias e vídeos são contexto de atenção pública, não demanda.",
                                           "Ausência de dado não é evidência negativa."]}
    c = out["coberturas"]
    return _with_data(c["comercial"]["n"], f"comercial: {c['comercial']['nivel']} · contextual: {c['contextual']['nivel']} · "
                                           f"técnica: {c['tecnica']['nivel']} · confiança: {c['confianca']['nivel']}")


def _level(n, good):
    return "nenhuma" if not n else ("boa" if n >= good else "parcial")


def coverage_by_type(db, out, st, diag) -> dict:
    """Três coberturas que NÃO se misturam:
    * comercial — volume autorizado, histórico de procura, anúncios e histórico de preços do mercado principal, evidências
      comerciais locais (anúncios ≠ vendas);
    * contextual — notícias, vídeos, imagens, produtos relacionados e categoria (enriquecem, não comprovam intenção de compra);
    * técnica — identificação, família/variante, especificações, fornecedores candidatos, NCM e registros regulatórios.
    A classificação comercial (cor) continua dependendo apenas de evidências elegíveis."""
    from ..intel.semantics import COMMERCIAL, DEMAND, SEARCH
    ab = out["abas"]
    com = []
    for v in st["direct"].get("volume") or []:
        com.append({"indicador": "volume de buscas autorizado", "fonte": v["fonte"], "mercado": v["mercado"], "registros": v["meses"],
                    "detalhe": f"{v['meses']} mês(es)" + (f", tendência {v['tendencia']['direcao']}" if v.get("tendencia") else "")})
    for v in [x for x in st["direct"].get("volume_all") or [] if x.get("papel") == "comparativo"]:
        com.append({"indicador": "volume de buscas autorizado (mercado comparativo)", "fonte": v["fonte"], "mercado": v["mercado"],
                    "registros": v["meses"], "detalhe": "não entra na decisão do mercado principal", "comparativo": True})
    if st["direct"].get("listings"):
        com.append({"indicador": "anúncios e preços anunciados (oferta observada, não vendas)", "fonte": ", ".join(st["direct"].get("listing_sources") or []),
                    "mercado": st.get("main_market"), "registros": st["direct"]["listings"], "detalhe": "não é quantidade de vendas"})
    if st["direct"].get("price_history"):
        com.append({"indicador": "histórico de preços", "fonte": "anúncios coletados", "mercado": st.get("main_market"),
                    "registros": st["direct"]["price_history"], "detalhe": "anúncios com ≥ 2 coletas"})
    for e in (st["p"] or {}).get("evidencias") or []:
        if e.get("tipo") in (COMMERCIAL, DEMAND, SEARCH):
            com.append({"indicador": e.get("indicador") or e.get("metrica"), "fonte": e.get("fonte_nome") or e.get("fonte"), "mercado": e.get("mercado"),
                        "registros": e.get("observacoes_n"), "detalhe": "histórico local (sincronizações anteriores)"})
    ctx_items = []
    for c in st.get("collected") or []:
        if c["estado"] in TG.USEFUL and c["registros"] and c["capacidade"] in ("news_mentions", "product_search"):
            ctx_items.append({"indicador": c["indicador"], "fonte": c["fonte"], "mercado": c["mercado"], "registros": c["registros"]})
    imgs = db.query("SELECT COUNT(*) AS n FROM product_images WHERE product_id = ? OR product_id LIKE ?", (st["pid"] or "§", (st["pid"] or "§").split(":")[0] + "%"))[0]["n"]
    if imgs:
        ctx_items.append({"indicador": "imagens do produto no catálogo visual", "fonte": "catálogo local", "mercado": "—", "registros": imgs})
    rel = len((ab.get("semelhantes") or {}).get("itens") or [])
    if rel:
        ctx_items.append({"indicador": "produtos relacionados", "fonte": "catálogo", "mercado": "—", "registros": rel})
    cat = ((ab.get("visao_geral") or {}).get("identificacao") or {}).get("familia") or {}
    if cat.get("categoria"):
        ctx_items.append({"indicador": "categoria", "fonte": "catálogo", "mercado": "—", "registros": 1, "detalhe": cat["categoria"]})
    u = st.get("u") or {}
    idf = (ab.get("visao_geral") or {}).get("identificacao") or {}
    tec = []
    if u.get("estado") == "confirmada":
        tec.append({"indicador": "identificação técnica confirmada", "fonte": "Product Understanding", "registros": 1, "detalhe": u.get("nivel_rotulo")})
    if idf.get("familia"):
        tec.append({"indicador": "família", "fonte": "catálogo", "registros": 1, "detalhe": idf["familia"]["nome"]})
    if idf.get("variante"):
        tec.append({"indicador": "variante", "fonte": "catálogo", "registros": 1, "detalhe": idf["variante"]["rotulo"]})
    specs = {k: v for k, v in (u.get("atributos") or {}).items() if v}
    if specs:
        tec.append({"indicador": "especificações explícitas", "fonte": "texto da consulta", "registros": len(specs), "detalhe": ", ".join(specs)})
    sup = (ab.get("fornecedores") or {}).get("candidatos") or []
    if sup:
        tec.append({"indicador": "fornecedores candidatos", "fonte": "cadastro/embarques/registros", "registros": len(sup), "detalhe": "candidatos, não confirmados"})
    imp = ab.get("importacao") or {}
    if (imp.get("ncm") or {}).get("candidatas"):
        tec.append({"indicador": "NCM candidata", "fonte": "tabela NCM", "registros": len(imp["ncm"]["candidatas"]), "detalhe": "não é classificação fiscal"})
    if (imp.get("regulatorio") or {}).get("registros_encontrados"):
        tec.append({"indicador": "registros regulatórios", "fonte": "Anatel/Inmetro", "registros": imp["regulatorio"]["registros_encontrados"]})
    main_com = [x for x in com if not x.get("comparativo")]
    srcs = {x["fonte"] for x in main_com}
    ident = u.get("estado") == "confirmada"
    if main_com and ident and len(srcs) >= 2:
        conf, why = "alta", "evidência comercial de ≥ 2 fontes no mercado principal e identificação confirmada"
    elif main_com and ident:
        conf, why = "média", "evidência comercial de uma fonte no mercado principal"
    elif main_com:
        conf, why = "baixa", "há evidência comercial, mas a identificação do produto não está confirmada"
    elif ctx_items or tec:
        conf, why = "baixa", "somente evidências contextuais e/ou técnicas — não comprovam demanda"
    else:
        conf, why = "insuficiente", "nenhuma evidência"
    return {"comercial": {"nivel": _level(len(main_com), 2), "n": len(main_com), "itens": com,
                          "nota": "volume autorizado, procura, anúncios/preços do mercado principal; anúncios não são vendas"},
            "contextual": {"nivel": _level(len(ctx_items), 2), "n": len(ctx_items), "itens": ctx_items,
                           "nota": "notícias, vídeos, imagens, relacionados e categoria — enriquecem, não comprovam intenção de compra"},
            "tecnica": {"nivel": _level(len(tec), 4), "n": len(tec), "itens": tec, "nota": "identificação, especificações, fornecedores, NCM, regulatório"},
            "confianca": {"nivel": conf, "motivo": why}}


def _s_forecast(db, ctx, params, out, st, rid, today, cancelled):
    if not st["pid"] and not st["direct"].get("volume"):
        out["abas"]["previsoes"] = {"series": [], "vazio": "Produto não identificado e sem séries."}
        return "concluída sem dados", "sem séries"
    t = MK.trend_explorer(db, st["pid"], horizon=6, terms=_terms_q(st, out)) if st["pid"] else {"series": []}
    out["abas"]["previsoes"] = t
    return _with_data(len(t["series"]), f"{len(t['series'])} série(s)")


def direct_stage(st) -> dict | None:
    """Estágio 0–3 pelas evidências DIRETAS coletadas na pesquisa (volume autorizado e anúncios). Notícias e vídeos não
    sobem o estágio. VERDE (3) exige identificação confirmada + ≥ 12 meses de volume com crescimento significativo."""
    vol = st["direct"].get("volume") or []
    lst = st["direct"].get("listings") or 0
    ident = (st["u"] or {}).get("estado") == "confirmada"
    if not vol and not lst:
        return None
    longest = max((s["meses"] for s in vol), default=0)
    growth = any(s["meses"] >= 12 and (s.get("tendencia") or {}).get("significativa") and (s["tendencia"] or {}).get("direcao") == "crescimento" for s in vol)
    falta = []
    if ident and growth:
        stg, rule = 3, "volume de pesquisa autorizado com ≥ 12 meses e crescimento estatisticamente significativo, identificação confirmada"
    elif longest >= 3:
        stg, rule = 2, "volume de pesquisa autorizado com histórico, sem crescimento confirmado"
    else:
        stg, rule = 1, "sinal direto inicial (anúncios observados e/ou pouco histórico de volume)"
    if stg < 3:
        if not vol:
            falta.append("volume de pesquisa autorizado (Keyword Planner / Microsoft Advertising)")
        elif not growth:
            falta.append("crescimento estatisticamente significativo em ≥ 12 meses de volume")
        if not ident:
            falta.append("identificação confirmada do produto")
    return {"estagio": stg, "nome": {1: "Novo sinal", 2: "Em observação", 3: "Investigação recomendada"}[stg], "regra": rule, "faltando": falta,
            "origem": "evidências diretas desta pesquisa"}


def _s_evidence(db, ctx, params, out, st, rid, today, cancelled):
    from ..intel.semantics import origin_of
    pid = st["pid"]
    ent = pid or f"termo:{TG._norm(out['consulta'])}"
    n = 0
    for e in (st["p"] or {}).get("evidencias") or []:
        S.add_evidence(db, rid, {"entity_type": "produto", "entity_id": ent, "source": e.get("fonte") or "?", "source_record_id": str(e.get("serie")),
                                 "indicator": e.get("indicador") or e.get("metrica") or "?", "value": e.get("observacoes_n"), "unit": "observações",
                                 "country": e.get("pais"), "period_start": (e.get("periodo") or "").split(" a ")[0] or None,
                                 "period_end": (e.get("periodo") or "").split(" a ")[-1] or None, "source_capability": "historical_data",
                                 "confidence": "alta" if (e.get("observacoes_n") or 0) >= 12 else "média" if (e.get("observacoes_n") or 0) >= 4 else "baixa",
                                 "quality_status": "elegível" if (e.get("elegibilidade") or {}).get("tendencia") else "observada",
                                 "usage_restrictions": e.get("nao_e"), "origin": origin_of(e.get("fonte") or "", e.get("camada") or "observado",
                                                                                           e.get("metrica") or "")})
        n += 1
    for s in st["direct"].get("volume_all") or st["direct"].get("volume") or []:
        S.add_evidence(db, rid, {"entity_type": "produto", "entity_id": ent, "source": s["fonte"], "source_record_id": f"{s['mercado']}:{s['inicio']}:{s['fim']}",
                                 "indicator": "volume mensal de buscas", "value": s["ultimo"], "unit": "buscas/mês", "country": s["mercado"],
                                 "period_start": s["inicio"], "period_end": s["fim"], "source_capability": "search_volume",
                                 "confidence": "alta" if s["meses"] >= 12 else "média", "quality_status": "elegível" if s["meses"] >= 6 else "observada",
                                 "usage_restrictions": "aproximado pela fonte; não é vendas"})
        n += 1
    for c in st.get("collected") or []:
        if c["estado"] in TG.USEFUL and c["registros"] and c["capacidade"] in ("marketplace_listings", "product_search", "news_mentions"):
            S.add_evidence(db, rid, {"entity_type": "produto", "entity_id": ent, "source": c["id"], "source_record_id": f"{c['mercado']}:{c.get('termo') or ''}:{today.isoformat()}",
                                     "indicator": c["indicador"], "value": c["registros"], "unit": "registros", "country": c["mercado"],
                                     "source_capability": c["capacidade"], "confidence": "média", "collected_at": c.get("ultima_coleta"),
                                     "usage_restrictions": {"marketplace_listings": "anúncios não são vendas", "product_search": "vídeos não são avaliações de compradores",
                                                            "news_mentions": "atenção pública, não demanda"}[c["capacidade"]]})
            n += 1
    for c in (out["abas"].get("fornecedores") or {}).get("candidatos", [])[:20]:
        S.add_evidence(db, rid, {"entity_type": "empresa", "entity_id": str(c.get("company_id") or c["empresa"]), "source": ",".join(c["fontes"]),
                                 "source_record_id": out["consulta"], "indicator": f"fornecedor candidato ({c['tipo_correspondencia']})", "value": c["confianca"],
                                 "source_capability": "supplier_search", "confidence": c["confianca"],
                                 "usage_restrictions": "candidato para investigação, não fornecedor confirmado"})
        n += 1
    for s in (out["abas"].get("importacao") or {}).get("ncm", {}).get("estatisticas_agregadas", [])[:6]:
        S.add_evidence(db, rid, {"entity_type": "ncm", "entity_id": s["series_key"], "source": "comexstat", "source_record_id": s["series_key"],
                                 "indicator": s["indicator"], "value": s.get("ultimos_12"), "unit": s.get("unit"), "country": s.get("country"),
                                 "period_end": s.get("fim"), "source_capability": "trade_statistics", "confidence": "alta",
                                 "usage_restrictions": "estatística da classificação inteira, não do produto"})
        n += 1
    rows = db.query("SELECT * FROM research_evidence WHERE research_id = ? ORDER BY entity_type, source", (rid,))
    hist = db.query("SELECT COUNT(DISTINCT research_id) AS n FROM research_evidence WHERE entity_id = ?", (ent,))[0]["n"]
    out["abas"]["evidencias"] = {"itens": rows, "total": len(rows), "pesquisas_com_evidencias_desta_entidade": hist,
                                 "regra": "Cada observação é registrada uma única vez (fonte + registro + indicador + entidade): não há dupla contagem."}
    return _with_data(n, f"{n} evidência(s)")


def _s_decision(db, ctx, params, out, st, rid, today, cancelled):
    stage = st["stage"]
    ds = direct_stage(st)
    if ds and (not stage or ds["estagio"] > stage["estagio"]):
        stage = {**(stage or {}), **ds}
    p = st["p"] or ({"situacao": None, "confirmacao_cruzada": {}} if ds else None)
    d = IX.classify_decision(p, stage)
    d["base"] = (stage or {}).get("origem") or ("inteligência local" if st["stage"] else "sem evidências")
    out["decisao"] = d
    out["abas"]["visao_geral"]["decisao"] = d
    out["abas"]["visao_geral"]["estagio_direto"] = ds
    return ("concluída com dados" if d["cor"] != "CINZA" else "concluída sem dados", d["cor"])
