"""Product Research — pesquisa rápida ou completa de um produto pelo nome (pt/en), com mercado, mercados de comparação,
período, objetivo e profundidade. Executa etapas REAIS (cada uma grava o próprio estado; a barra de progresso reflete o
que foi concluído, nunca um avanço simulado) e monta um dossiê de 9 abas: Visão geral, Demanda, Marketplaces, Produtos
semelhantes, Fornecedores, Importação, Qualidade, Previsões e Evidências.

Usa somente os dados já coletados pelo GPI (sincronizações autorizadas, arquivos do usuário e bases oficiais carregadas).
Coletar novos dados é responsabilidade da Sincronização — a pesquisa diz exatamente o que falta."""
from __future__ import annotations

import json
import threading
import traceback
from datetime import date, timedelta

from . import importx as IX
from . import marketplace as MK
from . import store as S
from . import suppliers as SP

STEPS = [("entender", "Entender o produto (Product Understanding)"), ("catalogo", "Localizar no catálogo e na inteligência"),
         ("demanda", "Demanda e pesquisa"), ("marketplaces", "Anúncios e preços observados"), ("semelhantes", "Produtos semelhantes"),
         ("fornecedores", "Fornecedores candidatos"), ("importacao", "NCM, regulatório e riscos"), ("qualidade", "Qualidade dos dados"),
         ("previsoes", "Tendências e previsões"), ("evidencias", "Registrar evidências"), ("decisao", "Classificar a decisão")]
QUICK_SKIP = {"previsoes"}
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


def get(db, rid: int) -> dict | None:
    S.ensure(db)
    r = db.query("SELECT * FROM research_jobs WHERE id = ?", (rid,))
    if not r:
        return None
    j = r[0]
    j["params"] = json.loads(j["params"] or "{}")
    j["steps"] = json.loads(j["steps"] or "[]")
    j["result"] = json.loads(j["result"]) if j["result"] else None
    done = sum(1 for s in j["steps"] if s["estado"] in ("concluída", "ignorada", "falhou"))
    j["progresso"] = {"concluidas": done, "total": len(j["steps"]), "pct": round(100 * done / len(j["steps"])) if j["steps"] else 0}
    return j


def history(db, limit: int = 200) -> list[dict]:
    S.ensure(db)
    rows = db.query("SELECT id, kind, query, params, status, product_id, created_at, finished_at, saved FROM research_jobs ORDER BY id DESC LIMIT ?",
                    (limit,))
    for r in rows:
        r["params"] = json.loads(r["params"] or "{}")
    return rows


def start(db, rid: int, ctx: dict) -> None:
    t = threading.Thread(target=run, args=(db, rid, ctx), daemon=True, name=f"gpi-pesquisa-{rid}")
    _running[rid] = t
    t.start()


def run(db, rid: int, ctx: dict) -> dict:
    """ctx: payload_fn, stages_fn, catalog_fn, ncm, today."""
    j = get(db, rid)
    steps = j["steps"]
    params = j["params"]
    today = ctx["today"]
    deep = params.get("profundidade", "rapida") == "completa"
    out = {"consulta": j["query"], "parametros": params, "abas": {}}
    st = {"u": None, "p": None, "stage": None, "pid": None}

    def mark(i, estado, detalhe=None):
        steps[i]["estado"] = estado
        if detalhe:
            steps[i]["detalhe"] = detalhe
        db.execute("UPDATE research_jobs SET steps = ?, status = ? WHERE id = ?", (json.dumps(steps, ensure_ascii=False), "executando", rid))

    funcs = {"entender": _s_understand, "catalogo": _s_catalog, "demanda": _s_demand, "marketplaces": _s_markets, "semelhantes": _s_similar,
             "fornecedores": _s_suppliers, "importacao": _s_import, "qualidade": _s_quality, "previsoes": _s_forecast,
             "evidencias": _s_evidence, "decisao": _s_decision}
    failed = 0
    for i, (k, _) in enumerate(STEPS):
        if k in QUICK_SKIP and not deep:
            mark(i, "ignorada", "pesquisa rápida (use a completa para previsões)")
            continue
        mark(i, "executando")
        try:
            det = funcs[k](db, ctx, params, out, st, rid, today)
            mark(i, "concluída", det)
        except Exception as e:  # noqa: BLE001
            failed += 1
            mark(i, "falhou", f"{type(e).__name__}: {str(e)[:200]}")
            out.setdefault("erros", []).append({"etapa": k, "erro": type(e).__name__, "detalhe": traceback.format_exc(limit=2)[-600:]})
    status = "concluída" if not failed else "concluída com falhas"
    db.execute("UPDATE research_jobs SET status = ?, result = ?, product_id = ?, finished_at = ?, steps = ? WHERE id = ?",
               (status, json.dumps(out, ensure_ascii=False, default=str), st["pid"], S.now(), json.dumps(steps, ensure_ascii=False), rid))
    _running.pop(rid, None)
    return out


# ------------------------------------------------------------------------------------------------- etapas
def _s_understand(db, ctx, params, out, st, rid, today):
    from ..intel import understanding as U
    q = out["consulta"]
    u = U.understand(q, params.get("idioma") or None)
    st["u"] = u
    out["abas"]["visao_geral"] = {"entendimento": {k: u.get(k) for k in ("principal", "produto_id", "estado", "nivel_rotulo", "taxonomia",
                                                                         "atributos", "contexto", "motivos")}}
    return f"{u.get('estado')}: {u.get('produto_id') or 'não identificado'}"


def _s_catalog(db, ctx, params, out, st, rid, today):
    u = st["u"]
    payload = ctx["payload_fn"]()
    prods = payload.get("produtos") or {}
    cands = [c for c in (u.get("produto_id"), u.get("principal")) if c]
    from ..products.catalog import Catalog
    m = Catalog(db, ctx.get("cfg") or {}).match(out["consulta"])
    if m:
        cands = [m.get("variante"), m["familia"], *cands]
    pid = next((c for c in cands if c and c in prods), None) or next((c for c in cands if c), None)
    st["pid"] = pid
    st["p"] = prods.get(pid) if pid else None
    stages = ctx["stages_fn"]()
    item = next((x for x in stages["itens"] if x["produto_id"] == pid), None)
    st["stage"] = item["estagio_evidencia"] if item else None
    ov = out["abas"]["visao_geral"]
    ov.update({"produto_id": pid, "no_catalogo": bool(m), "na_inteligencia": st["p"] is not None,
               "produto": ((st["p"] or {}).get("identificacao") or {}).get("produto") or _catalog_name(db, pid) or pid,
               "situacao": (st["p"] or {}).get("situacao"), "estagio": item["estagio"] if item else 0,
               "nome_estagio": item["nome_estagio"] if item else "Identificado" if pid else "Não identificado",
               "proximas_acoes": item["proximas_acoes"] if item else ["Sincronizar fontes de pesquisa/marketplace para este produto"],
               "indicadores": IX.indicators(st["p"], today.isoformat()),
               "investigar_url": f"#dossie/{pid}" if st["p"] else None})
    return "encontrado na inteligência" if st["p"] else ("no catálogo, sem evidências" if pid else "fora do catálogo")


def _catalog_name(db, pid):
    if not pid:
        return None
    r = db.query("SELECT name_pt, name_en FROM catalog_products WHERE product_id IN (?, ?) ORDER BY (product_id = ?) DESC LIMIT 1",
                 (pid, pid.split(":")[0], pid))
    if not r:
        return None
    n = r[0]["name_pt"] or r[0]["name_en"]
    return n + (f" ({pid.split(':')[1]})" if ":" in pid and n else "") if n else None


def _s_demand(db, ctx, params, out, st, rid, today):
    since, until = _period(params, today)
    markets = [params.get("mercado") or "BR", *[m for m in (params.get("comparacao") or []) if m]][:6]
    st["pid"]
    evs = [e for e in (st["p"] or {}).get("evidencias") or []]
    kw = MK.keywords(db, out["consulta"])
    rows = []
    for m in markets:
        mrows = [r for r in kw["observadas"] if r["mercado"] in (m, f"GLOBAL:{params.get('idioma') or 'pt'}") and r["ultimo"] >= since[:len(r["ultimo"])]]
        rows.append({"mercado": m, "termos_observados": len(mrows), "com_volume": sum(1 for r in mrows if r["classe"] == "com volume verificado"),
                     "com_historico": sum(1 for r in mrows if r["classe"] == "com histórico"), "exemplos": mrows[:8]})
    out["abas"]["demanda"] = {"periodo": [since, until], "mercados": rows,
                              "evidencias_inteligencia": [{k: e.get(k) for k in ("fonte_nome", "tipo_rotulo", "indicador", "mercado", "periodo",
                                                                                  "observacoes_n", "nao_e")} for e in evs],
                              "traducoes": kw["traducoes"], "palavras_geradas": kw["geradas"][:20], "legenda": kw["legenda"],
                              "aviso": kw["aviso"], "vazio": None if (evs or any(r["termos_observados"] for r in rows)) else
                              "Sem observações de pesquisa para este produto no período. Sincronize Google Trends/Keyword Planner/Mercado Livre."}
    return f"{len(evs)} evidência(s); {sum(r['termos_observados'] for r in rows)} termo(s) observados"


def _s_markets(db, ctx, params, out, st, rid, today):
    pid = st["pid"]
    ls = MK.listing_stats(db, pid, 30, today) if pid else None
    ls90 = MK.listing_stats(db, pid, 90, today) if pid else None
    recent = db.query("SELECT source, item_id, title, brand, price, currency, seller, MAX(day) AS dia, url FROM market_listings WHERE product_id = ? "
                      "OR product_id LIKE ? GROUP BY source, item_id ORDER BY dia DESC LIMIT 25", (pid or "", (pid or "§") + ":%")) if pid else []
    out["abas"]["marketplaces"] = {"ultimos_30_dias": ls, "ultimos_90_dias": ls90, "anuncios": recent, "competicao": MK.competition(ls),
                                   "nao_disponivel": ["vendas", "receita", "unidades vendidas"],
                                   "vazio": None if ls or ls90 else "Nenhum anúncio coletado para este produto (eBay Browse / Mercado Livre).",
                                   "aviso": MK.AUTH_NOTE + " Quantidade de anúncios não é demanda."}
    return f"{(ls or ls90 or {}).get('anuncios', 0)} anúncio(s)"


def _s_similar(db, ctx, params, out, st, rid, today):
    pid = st["pid"]
    if not pid:
        out["abas"]["semelhantes"] = {"itens": [], "vazio": "Produto não identificado."}
        return "sem produto"
    fam = pid.split(":")[0]
    cat = db.query("SELECT category FROM catalog_products WHERE product_id IN (?, ?)", (pid, fam))
    payload = ctx["payload_fn"]().get("produtos") or {}
    items = []
    for r in db.query("SELECT product_id, name_pt, name_en, level, parent_id, category FROM catalog_products WHERE (parent_id = ? OR product_id = ? "
                      "OR category = ?) AND product_id != ? LIMIT 60", (fam, fam, cat[0]["category"] if cat else "§", pid)):
        rel = "variante da mesma família" if r["parent_id"] == fam else "família" if r["product_id"] == fam else "mesma categoria"
        p = payload.get(r["product_id"])
        items.append({"produto_id": r["product_id"], "nome": r["name_pt"] or r["name_en"] or r["product_id"], "relacao": rel,
                      "situacao": (p or {}).get("situacao"), "opportunity_score": ((p or {}).get("indices") or {}).get("opportunity_score"),
                      "anuncios_30d": (MK.listing_stats(db, r["product_id"], 30, today) or {}).get("anuncios")})
    order = {"variante da mesma família": 0, "família": 1, "mesma categoria": 2}
    items.sort(key=lambda x: (order[x["relacao"]], -(x["opportunity_score"] or -1)))
    out["abas"]["semelhantes"] = {"itens": items[:40], "nota": "Semelhança pela taxonomia do catálogo — não é equivalência técnica."}
    return f"{len(items)} produto(s)"


def _s_suppliers(db, ctx, params, out, st, rid, today):
    fam = (st["pid"] or "").split(":")[0] or None
    d = SP.discover(db, out["consulta"], family=fam, product_id=st["pid"], limit=30)
    out["abas"]["fornecedores"] = d
    return f"{len(d['candidatos'])} candidato(s)"


def _s_import(db, ctx, params, out, st, rid, today):
    cat = db.query("SELECT ncm_hint FROM catalog_products WHERE product_id = ?", ((st["pid"] or "").split(":")[0],)) if st["pid"] else []
    text = out["consulta"]
    ncm = IX.ncm_block(db, ctx.get("ncm"), text, (cat[0]["ncm_hint"] if cat else None))
    reg = IX.regulatory_block(db, text)
    ls = (out["abas"].get("marketplaces") or {}).get("ultimos_30_dias")
    out["abas"]["importacao"] = {"ncm": ncm, "regulatorio": reg, "riscos": IX.risks(st["u"], reg, ncm, ls),
                                 "cenarios_salvos": IX.list_scenarios(db, st["pid"]) if st["pid"] else [],
                                 "simulador": {"campos": IX.FIELDS, "obrigatorios": IX.REQUIRED}}
    return f"{len(ncm['candidatas'])} NCM candidata(s); {reg.get('registros_encontrados', 0)} registro(s) regulatório(s)"


def _s_quality(db, ctx, params, out, st, rid, today):
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
    ind = IX.indicators(st["p"], today.isoformat())
    out["abas"]["qualidade"] = {"evidence_coverage": ind["evidence_coverage"], "frescor": ind["data_freshness"], "origens": origins,
                                "identificacao": (st["u"] or {}).get("estado"), "associacoes_em_revisao": pend[0]["n"],
                                "fontes": sorted({e.get("fonte_nome") or e.get("fonte") for e in evs}),
                                "regras": ["Dados DEMONSTRATIVOS/SIMULADOS nunca entram como evidência comercial.",
                                           "Identificação não confirmada impede recomendação (estágio 3).",
                                           "Ausência de dado não é evidência negativa."]}
    v = ind["evidence_coverage"]["valor"]
    return "cobertura " + ("não avaliada (sem evidências)" if v is None else f"{v:.0f}")


def _s_forecast(db, ctx, params, out, st, rid, today):
    if not st["pid"]:
        out["abas"]["previsoes"] = {"series": [], "vazio": "Produto não identificado."}
        return "sem produto"
    t = MK.trend_explorer(db, st["pid"], horizon=6)
    out["abas"]["previsoes"] = t
    return f"{len(t['series'])} série(s)"


def _s_evidence(db, ctx, params, out, st, rid, today):
    from ..intel.semantics import origin_of
    pid = st["pid"]
    n = 0
    for e in (st["p"] or {}).get("evidencias") or []:
        S.add_evidence(db, rid, {"entity_type": "produto", "entity_id": pid, "source": e.get("fonte") or "?", "source_record_id": str(e.get("serie")),
                                 "indicator": e.get("indicador") or e.get("metrica") or "?", "value": e.get("observacoes_n"), "unit": "observações",
                                 "country": e.get("pais"), "period_start": (e.get("periodo") or "").split(" a ")[0] or None,
                                 "period_end": (e.get("periodo") or "").split(" a ")[-1] or None, "source_capability": "historical_data",
                                 "confidence": "alta" if (e.get("observacoes_n") or 0) >= 12 else "média" if (e.get("observacoes_n") or 0) >= 4 else "baixa",
                                 "quality_status": "elegível" if (e.get("elegibilidade") or {}).get("tendencia") else "observada",
                                 "usage_restrictions": e.get("nao_e"), "origin": origin_of(e.get("fonte") or "", e.get("camada") or "observado",
                                                                                           e.get("metrica") or "")})
        n += 1
    ls = (out["abas"].get("marketplaces") or {}).get("ultimos_30_dias")
    if ls:
        S.add_evidence(db, rid, {"entity_type": "produto", "entity_id": pid, "source": "market_listings", "source_record_id": f"30d:{today.isoformat()}",
                                 "indicator": "anúncios observados (30 dias)", "value": ls["anuncios"], "unit": "anúncios",
                                 "source_capability": "marketplace_listings", "confidence": "média", "usage_restrictions": "não é volume de vendas"})
        n += 1
    for c in (out["abas"].get("fornecedores") or {}).get("candidatos", [])[:20]:
        S.add_evidence(db, rid, {"entity_type": "empresa", "entity_id": str(c.get("company_id") or c["empresa"]), "source": ",".join(c["fontes"]),
                                 "source_record_id": out["consulta"], "indicator": "fornecedor candidato", "value": c["confianca"],
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
    out["abas"]["evidencias"] = {"itens": rows, "total": len(rows),
                                 "regra": "Cada observação é registrada uma única vez (fonte + registro + indicador + entidade): não há dupla contagem."}
    return f"{n} evidência(s)"


def _s_decision(db, ctx, params, out, st, rid, today):
    d = IX.classify_decision(st["p"], st["stage"])
    out["decisao"] = d
    out["abas"]["visao_geral"]["decisao"] = d
    return d["cor"]
