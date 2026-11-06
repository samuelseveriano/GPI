"""Marketplace Intelligence — Niche Finder, Keyword Intelligence, Marketplace Analyzer, Trend & Seasonality Explorer e
Review & Product Insights, todos sobre os dados LOCAIS do GPI (anúncios coletados por APIs autorizadas, observações de
pesquisa, séries de mercado e conteúdos/avaliações).

Nunca: vendas ou receita estimadas a partir de anúncios; volume de pesquisa sem fonte que o forneça; tendência sem teste
estatístico; quantidade de anúncios tratada como demanda."""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

import numpy as np


VOLUME_SOURCES = {"google_ads_kp"}            # fontes que fornecem VOLUME de pesquisa (faixas oficiais)
AUTH_NOTE = "Somente dados de APIs/fontes autorizadas já coletados pelo GPI; nada é raspado."


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


# ------------------------------------------------------------------------------------------------ agregados de anúncios
SOURCE_MARKET = {"mercadolivre": "BR", "ebay": "US"}        # marketplace consultado (não o país do vendedor)


def listing_stats(db, product_id: str | None, days: int = 30, today: date | None = None, terms: list[str] | None = None,
                  sources: list[str] | None = None) -> dict | None:
    """Anúncios do produto (pelo ID canônico e suas variantes) e, se informado, pelos termos da consulta direcionada."""
    today = today or date.today()
    since = (today - timedelta(days=days)).isoformat()
    pid = product_id or "§"
    fam = pid.split(":")[0]
    terms = [t for t in (terms or []) if t]
    rows = db.query("SELECT source, item_id, day, title, brand, price, currency, seller, country FROM market_listings "
                    "WHERE (product_id = ? OR product_id = ? OR product_id LIKE ?" + (" OR query IN (%s)" % ",".join("?" * len(terms)) if terms else "") +
                    ") AND day >= ?" + (" AND source IN (%s)" % ",".join("?" * len(sources)) if sources else ""),
                    (pid, fam, fam + ":%", *terms, since, *(sources or [])))
    if not rows:
        return None
    latest = {}
    for r in rows:
        k = (r["source"], r["item_id"])
        if k not in latest or r["day"] > latest[k]["day"]:
            latest[k] = r
    items = list(latest.values())
    from . import listing_match as LM
    target = product_id if product_id else None
    cls = Counter()
    elig = []
    for r in items:
        m = LM.classify(r["title"], target)
        r["correspondencia"] = m
        cls[m["classe"]] += 1
        if m["elegivel"] and r["price"] is not None:
            elig.append(r)
    unit = [r["price"] / r["correspondencia"]["unidades"] for r in elig]
    base = elig if target else items                              # sem alvo: só descritivo (todos), marcado como não comparável
    brands = Counter((r["brand"] or "não informada").lower() for r in base)
    total = sum(brands.values())
    hhi = round(sum((n / total) ** 2 for n in brands.values()) * 10000) if total else None
    cur = Counter(r["currency"] for r in base if r["currency"]).most_common(1)
    cur_all = {r["currency"] for r in elig if r["currency"]}
    obs_days = len({r["day"] for r in rows})
    return {"anuncios": len(items), "anuncios_elegiveis": len(elig) if target else None, "por_correspondencia": dict(cls),
            "cobertura_amostra": round(len(elig) / len(items), 2) if target and items else None,
            "vendedores_distintos": len({r["seller"] for r in base if r["seller"]}),
            "marcas_distintas": len([b for b in brands if b != "não informada"]), "marcas": brands.most_common(8),
            "concentracao_anuncios_hhi": hhi, "preco_mediano": _median(unit) if len(cur_all) <= 1 else None,
            "preco_min": min(unit) if unit and len(cur_all) <= 1 else None, "preco_max": max(unit) if unit and len(cur_all) <= 1 else None,
            "kits_ou_lotes": sum(1 for r in elig if r["correspondencia"]["kit_ou_lote"]), "moeda": cur[0][0] if cur else None,
            "moedas_misturadas": len(cur_all) > 1, "dias_observados": obs_days,
            "fontes": sorted({r["source"] for r in items}), "mercados": sorted({r["country"] for r in items if r["country"]}),
            "janela_dias": days, "exemplos_rejeitados": [{"titulo": r["title"][:120], "classe": r["correspondencia"]["classe"],
                                                          "motivo": r["correspondencia"]["motivo"]} for r in items if not r["correspondencia"]["elegivel"]][:8],
            "nota": "Anúncios observados (não são vendas). Preços mínimo/mediana/máximo só entre anúncios do produto exato ou variante "
                    "compatível, por unidade (kits/lotes divididos). Cabos, acessórios e outros produtos ficam fora."}


# ------------------------------------------------------------------------------------------------ Niche Finder
FILTERS = ["texto", "categoria", "preco_min", "preco_max", "crescimento_min", "anuncios_min", "anuncios_max", "marcas_max",
           "competicao", "confianca_min", "cobertura_min", "atributo", "cor", "estagio_min", "situacao"]
SORTS = {"oportunidade": lambda r: -(r["opportunity_score"] or -1), "crescimento": lambda r: -(r["crescimento"] if r["crescimento"] is not None else -1e9),
         "cobertura": lambda r: -(r["evidence_coverage"] or 0), "preco": lambda r: (r["preco_mediano"] is None, r["preco_mediano"] or 0),
         "anuncios": lambda r: (r["anuncios"] is None, r["anuncios"] or 0), "nome": lambda r: r["produto"].lower()}


def competition(ls: dict | None) -> str:
    """Não classifica concorrência só pela quantidade de anúncios de uma consulta. Exige ≥ 30 anúncios ELEGÍVEIS em ≥ 2
    dias de coleta; o resultado é a concentração de ANÚNCIOS por marca (indicativa), não participação de mercado."""
    if not ls or not ls.get("anuncios_elegiveis") or ls["anuncios_elegiveis"] < 30 or (ls.get("dias_observados") or 0) < 2:
        return "não avaliada"
    hhi = ls["concentracao_anuncios_hhi"] or 0
    return "indicativa: muitos anunciantes (baixa concentração)" if hhi < 1500 else \
        "indicativa: concentração moderada" if hhi < 2500 else "indicativa: alta concentração de anúncios"


def niche_rows(payload: dict, db, catalog: dict, stages: dict, today: date) -> list[dict]:
    from ..intel import commercial
    from .importx import classify_decision
    st = {x["produto_id"]: x for x in stages["itens"]}
    out = []
    for pid, p in (payload.get("produtos") or {}).items():
        sc = commercial.scores(p)
        ls = listing_stats(db, pid, 30, today)
        idx = p.get("indices") or {}
        cat = catalog.get(pid) or {}
        try:
            attrs = json.loads(cat.get("attributes") or "{}") if isinstance(cat.get("attributes"), str) else (cat.get("attributes") or {})
        except ValueError:
            attrs = {}
        s = st.get(pid)
        dec = classify_decision(p, s["estagio_evidencia"] if s else None)
        cov = idx.get("evidence_coverage")
        from . import naming as NM
        out.append({"produto_id": pid, "produto": (p.get("identificacao") or {}).get("produto") or NM.name_of(db, pid) or pid,
                    "categoria": (p.get("identificacao") or {}).get("categoria") or cat.get("category"),
                    "familia": (p.get("identificacao") or {}).get("familia") or cat.get("family"), "situacao": p.get("situacao"),
                    "opportunity_score": idx.get("opportunity_score"), "evidence_coverage": cov,
                    "confianca": "alta" if (cov or 0) >= 60 else "média" if (cov or 0) >= 30 else "baixa" if cov else "não avaliada",
                    "crescimento": sc["momentum"]["valor"], "crescimento_status": sc["momentum"]["status"],
                    "anuncios": ls["anuncios"] if ls else None, "vendedores": ls["vendedores_distintos"] if ls else None,
                    "marcas": ls["marcas_distintas"] if ls else None, "preco_mediano": ls["preco_mediano"] if ls else None,
                    "moeda": ls["moeda"] if ls else None, "competicao": competition(ls), "atributos": attrs,
                    "estagio": s["estagio"] if s else 0, "nome_estagio": s["nome_estagio"] if s else "Identificado",
                    "decisao": dec["cor"], "fontes": p.get("fontes") or []})
    return out


def filter_niches(rows: list[dict], f: dict) -> list[dict]:
    def num(k):
        try:
            return float(f[k]) if f.get(k) not in (None, "") else None
        except (TypeError, ValueError):
            return None
    conf_rank = {"não avaliada": 0, "baixa": 1, "média": 2, "alta": 3}
    out = []
    for r in rows:
        t = (f.get("texto") or "").lower().strip()
        if t and t not in (r["produto"] + " " + (r["familia"] or "") + " " + r["produto_id"]).lower():
            continue
        if f.get("categoria") and (r["categoria"] or "") != f["categoria"]:
            continue
        if f.get("situacao") and r["situacao"] != f["situacao"]:
            continue
        if f.get("cor") and r["decisao"] != f["cor"].upper():
            continue
        # filtros numéricos: produto SEM o dado não passa no filtro (e a interface diz quantos ficaram de fora por falta de dado)
        for k, col, op in (("preco_min", "preco_mediano", "ge"), ("preco_max", "preco_mediano", "le"), ("crescimento_min", "crescimento", "ge"),
                           ("anuncios_min", "anuncios", "ge"), ("anuncios_max", "anuncios", "le"), ("marcas_max", "marcas", "le"),
                           ("cobertura_min", "evidence_coverage", "ge"), ("estagio_min", "estagio", "ge")):
            v = num(k)
            if v is None:
                continue
            x = r[col]
            if x is None or (op == "ge" and x < v) or (op == "le" and x > v):
                break
        else:
            if f.get("competicao") and r["competicao"] != f["competicao"]:
                continue
            if f.get("confianca_min") and conf_rank.get(r["confianca"], 0) < conf_rank.get(f["confianca_min"], 0):
                continue
            if f.get("atributo"):
                k, _, v = str(f["atributo"]).partition("=")
                av = r["atributos"].get(k.strip())
                if av is None or (v and v.strip().lower() not in str(av).lower()):
                    continue
            out.append(r)
    return out


# ------------------------------------------------------------------------------------------------ Keyword Intelligence
def _series_trend(points: list[tuple[str, float]]) -> dict | None:
    from ..analytics.classification import trend_test
    if len(points) < 6:
        return None
    y = np.asarray([v for _, v in sorted(points)], float)
    t = trend_test(y)
    return {"direcao": t.get("direcao"), "p_valor": t.get("p_valor"), "significativa": t.get("significativa"), "n": len(y)}


def keywords(db, term: str, market: str | None = None) -> dict:
    from ..intel import understanding as U
    from ..products import nlp
    u = U.understand(term[:200], None)
    pid = u.get("produto_id")
    fam = (u.get("principal") or "")
    norm = nlp._norm(term)
    rows = []
    gen = []
    # traduções / sinônimos: nomes e aliases do catálogo (gerados pelo léxico do GPI, não observados)
    cat = db.query("SELECT product_id, name_pt, name_en, name_zh, category, family, parent_id FROM catalog_products WHERE product_id IN (?, ?)",
                   (pid or "", fam))
    pids = {c["product_id"] for c in cat} | ({pid} if pid else set())
    trans = {}
    for c in cat:
        for lang in ("pt", "en", "zh"):
            if c.get(f"name_{lang}"):
                trans.setdefault(lang, c[f"name_{lang}"])
    aliases = db.query("SELECT alias, lang, product_id FROM product_aliases WHERE product_id IN (%s) LIMIT 200" % ",".join("?" * len(pids)),
                       tuple(pids)) if pids else []
    for a in aliases:
        gen.append({"palavra": a["alias"], "tipo": "sinônimo/tradução (léxico GPI)", "idioma": a["lang"]})
    variants = db.query("SELECT product_id, name_pt, name_en FROM catalog_products WHERE parent_id IN (%s) LIMIT 50" % ",".join("?" * len(pids)),
                        tuple(pids)) if pids else []
    for v in variants:
        gen.append({"palavra": v["name_pt"] or v["name_en"] or v["product_id"], "tipo": "variante do catálogo", "idioma": "pt"})
    cats = {c["category"] for c in cat if c.get("category")}
    cat_terms = db.query("SELECT name_pt, name_en FROM catalog_products WHERE category IN (%s) AND level = 'produto' LIMIT 30"
                         % ",".join("?" * len(cats)), tuple(cats)) if cats else []
    for c in cat_terms:
        gen.append({"palavra": c["name_pt"] or c["name_en"], "tipo": "termo da mesma categoria", "idioma": "pt"})
    # observados: search_observations ligadas ao produto OU com o termo
    q = ("SELECT source, country, term, ref_date, metric, value, value_high, unit FROM search_observations WHERE (term LIKE ?" +
         (" OR product_id IN (%s)" % ",".join("?" * len(pids)) if pids else "") + ")" + (" AND country = ?" if market else "") +
         " ORDER BY ref_date LIMIT 20000")
    obs = db.query(q, (f"%{norm}%", *pids, *([market] if market else [])))
    grp = defaultdict(list)
    for o in obs:
        grp[(o["term"].lower(), o["source"], o["country"], o["metric"])].append(o)
    for (t, src, cc, metric), lst in grp.items():
        pts = [(o["ref_date"], o["value"]) for o in lst]
        tr = _series_trend(pts)
        last = lst[-1]
        has_vol = src in VOLUME_SOURCES and metric == "volume_mensal_aprox"
        rel = 1.0 if t == norm else 0.8 if norm in t else 0.6
        rows.append({"palavra": lst[0]["term"], "fonte": src, "mercado": cc, "metrica": metric,
                     "volume_disponivel": (f"{last['value']:.0f}" + (f"–{last['value_high']:.0f}" if last.get("value_high") else "") + f" {last['unit']}")
                     if has_vol else "não disponível (a fonte não informa volume)",
                     "tendencia": (f"{tr['direcao']} (p={tr['p_valor']:.3f})" if tr and tr.get("p_valor") is not None and tr.get("significativa")
                                   else "sem tendência significativa" if tr else "histórico insuficiente (< 6 períodos)"),
                     "relevancia": rel, "classe": "com volume verificado" if has_vol else ("com histórico" if tr else "observada"),
                     "periodos": len(lst), "ultimo": last["ref_date"]})
    rows.sort(key=lambda r: (-r["relevancia"], -r["periodos"]))
    seen = {r["palavra"].lower() for r in rows}
    generated = []
    for g in gen:
        if g["palavra"] and g["palavra"].lower() not in seen:
            seen.add(g["palavra"].lower())
            generated.append({**g, "fonte": "gerada pelo GPI", "volume_disponivel": "não disponível", "tendencia": "—", "classe": "gerada"})
    return {"termo": term, "entendimento": {"produto_id": pid, "principal": fam, "estado": u.get("estado"), "atributos": u.get("atributos")},
            "traducoes": trans, "observadas": rows[:300], "geradas": generated[:150],
            "legenda": {"observada": "termo que apareceu numa fonte coletada", "gerada": "sugestão do léxico/catálogo do GPI — nunca observada",
                        "com volume verificado": "fonte autorizada que informa volume (ex.: Google Ads Keyword Planner)",
                        "com histórico": "≥ 6 períodos observados (permite teste de tendência)"},
            "aviso": "Volume de pesquisa só é mostrado quando uma fonte autorizada o fornece. Interesse relativo e rankings não são volume."}


def reverse_listing(db, listing_id: str) -> dict:
    """Hipóteses de palavras-chave a partir do TÍTULO de um anúncio já coletado. Não revela as palavras que geram tráfego."""
    from ..intel import understanding as U
    from ..products import nlp
    r = db.query("SELECT source, item_id, title, brand, model, product_id FROM market_listings WHERE item_id = ? ORDER BY day DESC LIMIT 1",
                 (listing_id.strip(),))
    if not r:
        return {"encontrado": False, "mensagem": "Anúncio não está entre os coletados pelo GPI (colete pela integração autorizada)."}
    t = r[0]["title"] or ""
    u = U.understand(t, None)
    toks = [w for w in nlp._norm(t).split() if len(w) > 2]
    grams = Counter()
    for n in (2, 3):
        for i in range(len(toks) - n + 1):
            grams[" ".join(toks[i:i + n])] += 1
    hyp = [{"palavra": g, "tipo": "n-grama do título"} for g, _ in grams.most_common(12)]
    for k, v in (u.get("atributos") or {}).items():
        if v and k in ("potencia_w", "capacidade", "modelo", "marca"):
            hyp.append({"palavra": f"{u.get('principal') or ''} {v if not isinstance(v, list) else ' '.join(v)}".strip(), "tipo": f"atributo ({k})"})
    return {"encontrado": True, "anuncio": r[0], "hipoteses": hyp, "entendimento": {"principal": u.get("principal"), "estado": u.get("estado")},
            "aviso": "HIPÓTESES geradas do título. O GPI não tem acesso às palavras que de fato levam compradores ao anúncio."}


# ------------------------------------------------------------------------------------------------ Marketplace Analyzer
URL_IDS = [re.compile(r"ebay\.[a-z.]+/itm/(?:[^/]+/)?(\d{9,15})"), re.compile(r"\b(MLB-?\d{6,12})\b", re.I), re.compile(r"\b(\d{9,15})\b")]


def parse_listing_ref(ref: str) -> str:
    ref = (ref or "").strip()
    for rx in URL_IDS:
        m = rx.search(ref)
        if m:
            return m.group(1).upper().replace("MLB-", "MLB")
    return ref


def listing(db, ref: str) -> dict:
    iid = parse_listing_ref(ref)
    rows = db.query("SELECT * FROM market_listings WHERE item_id = ? ORDER BY day", (iid,))
    if not rows:
        like = db.query("SELECT item_id, source, title, MAX(day) AS ultimo FROM market_listings WHERE LOWER(title) LIKE ? GROUP BY source, item_id "
                        "ORDER BY ultimo DESC LIMIT 30", (f"%{ref.lower()[:80]}%",))
        return {"encontrado": False, "id": iid, "busca_por_nome": like,
                "mensagem": "Anúncio não coletado. Use a integração autorizada (eBay Browse/Mercado Livre) para coletá-lo; o GPI não raspa páginas."}
    last = rows[-1]
    hist = [{"dia": r["day"], "preco": r["price"], "moeda": r["currency"], "preco_original": r["original_price"]} for r in rows]
    prices = [h["preco"] for h in hist if h["preco"] is not None]
    return {"encontrado": True, "id": iid, "fonte": last["source"], "titulo": last["title"], "marca": last["brand"], "modelo": last["model"],
            "categoria": last["category"], "condicao": last["condition"], "vendedor": last["seller"], "pais": last["country"], "url": last["url"],
            "produto_id": last["product_id"], "historico_precos": hist, "observacoes": len(hist), "primeira": rows[0]["day"], "ultima": last["day"],
            "preco_atual": last["price"], "variacao_preco_pct": round(100 * (prices[-1] / prices[0] - 1), 2) if len(prices) >= 2 and prices[0] else None,
            "nao_disponivel": ["vendas", "receita", "estoque"],
            "aviso": "Histórico de preço montado só com observações reais coletadas (dias sem coleta não são preenchidos). "
                     "Vendas e receita não são informadas pelas APIs usadas e não são estimadas."}


def compare_listings(db, refs: list[str]) -> dict:
    refs = [r for r in refs if str(r).strip()][:5]
    items = [listing(db, r) for r in refs]
    return {"itens": items, "limite": 5, "aviso": "Comparação de anúncios observados; não inclui vendas nem receita."}


# ------------------------------------------------------------------------------------------------ Trend & Seasonality Explorer
def _monthly(points: list[tuple[str, float]]) -> tuple[list[str], list[float]]:
    by = defaultdict(list)
    for d, v in points:
        by[d[:7]].append(v)
    ks = sorted(by)
    return ks, [float(np.mean(by[k])) for k in ks]


def trend_explorer(db, product_id: str, horizon: int = 6, terms: list[str] | None = None) -> dict:
    from ..analytics.classification import trend_test
    from ..products import trends as T
    fam = product_id.split(":")[0]
    out = []
    ser = db.query("SELECT id, series_key, source, indicator, kind, country, unit, freq FROM market_series WHERE product_key IN (?, ?) "
                     "OR product_key LIKE ?", (product_id, fam, fam + ":%"))
    for s in ser:
        obs = db.query("SELECT ref_date, value FROM market_obs WHERE series_id = ? ORDER BY ref_date", (s["id"],))
        out.append({"rotulo": f"{s['indicator']} · {s['source']} · {s['country'] or '—'}", "fonte": s["source"], "tipo": s["kind"],
                    "pontos": [(o["ref_date"], o["value"]) for o in obs], "unidade": s["unit"]})
    from ..products import nlp
    tn = [nlp._norm(t) for t in (terms or []) if t]
    so = db.query("SELECT source, country, metric, ref_date, value, unit FROM search_observations WHERE (product_id IN (?, ?) "
                  "OR product_id LIKE ?" + (" OR LOWER(term) IN (%s)" % ",".join("?" * len(tn)) if tn else "") + ") ORDER BY ref_date",
                  (product_id, fam, fam + ":%", *tn))
    grp = defaultdict(list)
    for o in so:
        grp[(o["source"], o["country"], o["metric"], o["unit"])].append((o["ref_date"], o["value"]))
    for (src, cc, metric, unit), pts in grp.items():
        out.append({"rotulo": f"{metric} · {src} · {cc}", "fonte": src, "tipo": metric, "pontos": pts, "unidade": unit})
    res = []
    for s in out:
        months, y = _monthly(s["pontos"])
        n = len(y)
        a = {"rotulo": s["rotulo"], "fonte": s["fonte"], "unidade": s["unidade"], "meses": months, "valores": [round(v, 4) for v in y], "n": n}
        if n >= 6:
            tt = trend_test(np.asarray(y))
            a["tendencia"] = {k: tt.get(k) for k in ("direcao", "p_valor", "significativa", "inclinacao_relativa")}
        a["mudanca_regime"] = T.pettitt(y) if n >= 24 else None
        a["aceleracao"] = T.robust_acceleration(y) if n >= 24 else None
        try:
            a["sazonalidade"] = T.robust_seasonality(y, [int(m[5:7]) for m in months], s["tipo"] or "") if n >= 24 else None
        except Exception:  # noqa: BLE001
            a["sazonalidade"] = None
        a["previsao"] = _forecast(y, months, horizon) if n >= 12 else None
        a["limitacoes"] = [] if n >= 24 else ["menos de 24 meses: sem teste de mudança de regime, aceleração ou sazonalidade"]
        if n < 6:
            a["limitacoes"].append("menos de 6 meses: sem teste de tendência")
        res.append(a)
    return {"produto_id": product_id, "series": res,
            "vazio": None if res else "Nenhuma série histórica para este produto (sincronize fontes de pesquisa/mercado).",
            "nota": "Testes reutilizados do módulo de tendências (Mann–Kendall/Theil–Sen, Pettitt, aceleração robusta, sazonalidade com 3 ciclos)."}


def _forecast(y, months, h):
    from ..forecasting.advanced import local_forecast
    y = np.asarray(y, float)
    hold = min(3, len(y) // 4)
    model, fc = local_forecast(y[:-hold], hold)
    actual = y[-hold:]
    wape = float(np.abs(actual - fc[:hold]).sum() / max(1e-9, np.abs(actual).sum()))
    naive = float(np.abs(actual - y[-hold - 1]).sum() / max(1e-9, np.abs(actual).sum()))
    model2, fut = local_forecast(y, h)
    y0, m0 = int(months[-1][:4]), int(months[-1][5:7])
    labels = []
    for i in range(1, h + 1):
        mm = m0 + i
        labels.append(f"{y0 + (mm - 1) // 12}-{(mm - 1) % 12 + 1:02d}")
    return {"modelo": model2, "meses": labels, "valores": [round(float(v), 4) for v in fut], "backtest_wape": round(wape, 4),
            "ingenuo_wape": round(naive, 4), "melhor_que_ingenuo": wape < naive,
            "nota": "Previsão da MÉTRICA observada (não de vendas). Validação na janela final retida."
                    + ("" if wape < naive else " O modelo não superou o ingênuo nessa validação: use com cautela.")}


# ------------------------------------------------------------------------------------------------ Review & Product Insights
REVIEW_COLS = {"texto": ["texto", "review", "comentario", "comentário", "comment", "text", "avaliacao", "avaliação", "content"],
               "nota": ["nota", "rating", "estrelas", "stars", "score"], "data": ["data", "date", "created_at"],
               "produto": ["produto", "product", "sku", "item"], "fonte": ["fonte", "source", "marketplace", "loja"]}


def wilson_lb(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    return round((p + z * z / (2 * n) - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n), 4)


def review_file(raw: bytes, filename: str) -> dict:
    """Análise local de avaliações exportadas pelo próprio usuário (CSV/XLSX). Não é enviado a nenhum serviço."""
    from ..nlp import reviews as RV
    from .suppliers import read_table, _map
    rows = read_table(raw, filename)
    recs = []
    for r in rows:
        m = _map(r, REVIEW_COLS)
        if not m.get("texto") and not m.get("nota"):
            continue
        a = RV.analyze(m.get("texto") or "")
        try:
            nota = float(str(m.get("nota")).replace(",", ".")) if m.get("nota") else None
        except ValueError:
            nota = None
        recs.append({**m, "nota": nota, "sentimento": a["label"], "aspectos": a["aspects"]})
    by = defaultdict(list)
    for r in recs:
        by[r.get("produto") or "(sem produto)"].append(r)
    prods = []
    for p, lst in by.items():
        n = len(lst)
        notas = [r["nota"] for r in lst if r["nota"] is not None]
        neg = sum(1 for r in lst if (r["nota"] is not None and r["nota"] <= 2) or (r["nota"] is None and r["sentimento"] == "negativo"))
        asp = defaultdict(list)
        for r in lst:
            for k, v in r["aspectos"].items():
                asp[k].append(v)
        problems = sorted([{"aspecto": k, "mencoes": len(v), "media": round(float(np.mean(v)), 3),
                            "classificacao": "recorrente" if len(v) >= 3 and np.mean(v) < -0.05 else "relato isolado" if np.mean(v) < -0.05 else "neutro/positivo"}
                           for k, v in asp.items()], key=lambda x: (x["media"], -x["mencoes"]))
        prods.append({"produto": p, "avaliacoes": n, "nota_media": round(float(np.mean(notas)), 2) if notas else None,
                      "distribuicao_notas": dict(Counter(int(round(x)) for x in notas)), "negativas": neg, "negativas_lb95": wilson_lb(neg, n),
                      "aspectos": problems[:12], "amostra_pequena": n < 30})
    prods.sort(key=lambda x: -(x["negativas_lb95"] or 0))
    return {"arquivo": filename[:120], "linhas": len(rows), "avaliacoes_validas": len(recs), "produtos": prods,
            "avisos": ["Análise das avaliações do arquivo enviado (fonte: você). Não representa todas as avaliações do produto.",
                       "Proporção de críticas pelo limite inferior de Wilson (95%) — amostras pequenas não viram 'mais criticado'.",
                       "Um relato isolado não é taxa de defeito."]}


def review_insights(db, product_id: str | None = None) -> dict:
    from ..market.content_intel import review_summary
    from ..market.content_store import ContentStore
    from ..market.store import MarketStore
    r = review_summary(MarketStore(db), ContentStore(db))
    if product_id:
        fam = product_id.split(":")[0]
        r["produtos"] = [p for p in r.get("produtos", []) if p.get("produto") in (product_id, fam) or p.get("product_key") in (product_id, fam)]
    return r

