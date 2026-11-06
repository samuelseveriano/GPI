"""Dashboard Product Intelligence consolidado (v0.9.1 MVP) — todos os números vêm do banco real. Cada seção diz o motivo
e a ação quando está vazia. Dados demonstrativos ficam fora (vendas demo, importações marcadas)."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date

from . import marketplace as MK
from . import naming as NM

GROWING = {"CRESCIMENTO", "CRESCIMENTO SUSTENTADO", "CRESCIMENTO RECENTE", "ACELERAÇÃO", "EMERGENTE", "EM ALTA", "ALTA"}


def _q(db, sql, p=()):
    try:
        return db.query(sql, p)
    except Exception:  # noqa: BLE001
        return []


def build(db, payload: dict, stages: dict, today: date) -> dict:
    prods = payload.get("produtos") or {}
    st = {x["produto_id"]: x for x in (stages or {}).get("itens", [])}
    # ---------------- A. portfólio
    grow = [pid for pid, p in prods.items() if any(g in str(p.get("situacao") or "").upper() for g in GROWING)]
    elig = [pid for pid, x in st.items() if x["estagio"] >= 3]
    insuf = [pid for pid, x in st.items() if x["estagio"] == 0]
    inv_open = _q(db, "SELECT COUNT(*) AS n FROM investigations WHERE estado NOT IN ('descartado', 'concluído', 'concluido', 'arquivado')")
    a = {"cadastrados": (_q(db, "SELECT COUNT(*) AS n FROM catalog_products") or [{"n": 0}])[0]["n"],
         "identificados": (_q(db, "SELECT COUNT(*) AS n FROM catalog_products WHERE evidence > 0") or [{"n": 0}])[0]["n"],
         "com_evidencias_comerciais": sum(1 for x in st.values() if x["estagio"] >= 1),
         "monitorados": (_q(db, "SELECT COUNT(*) AS n FROM monitored WHERE kind = 'produto'") or [{"n": 0}])[0]["n"],
         "investigacoes_abertas": (inv_open or [{"n": 0}])[0]["n"], "oportunidades_elegiveis": len(elig),
         "com_crescimento_observado": len(grow), "dados_insuficientes": len(insuf)}
    # ---------------- B. mercado
    rank = sorted(((pid, p) for pid, p in prods.items() if (p.get("indices") or {}).get("opportunity_score") is not None and st.get(pid, {}).get("estagio", 0) >= 1),
                  key=lambda kv: -kv[1]["indices"]["opportunity_score"])[:10]
    cats = Counter(((p.get("identificacao") or {}).get("categoria") or "—") for pid, p in prods.items() if st.get(pid, {}).get("estagio", 0) >= 1)
    mk = Counter(e.get("mercado") or "—" for p in prods.values() for e in p.get("evidencias") or [])
    recent = _q(db, "SELECT product_id, name_pt, name_en, first_seen FROM catalog_products WHERE origin != 'semente' ORDER BY first_seen DESC LIMIT 8")
    b = {"maior_interesse": [{"produto_id": pid, "produto": (p.get("identificacao") or {}).get("produto") or NM.name_of(db, pid),
                              "score": p["indices"]["opportunity_score"], "situacao": p.get("situacao"), "estagio": st[pid]["nome_estagio"]} for pid, p in rank],
         "crescimento": [{"produto_id": pid, "produto": (prods[pid].get("identificacao") or {}).get("produto") or NM.name_of(db, pid),
                          "situacao": prods[pid].get("situacao")} for pid in grow[:10]],
         "categorias": cats.most_common(8), "por_mercado": mk.most_common(8),
         "recem_identificados": [{"produto_id": r["product_id"], "produto": NM.name_of(db, r["product_id"]), "desde": r["first_seen"]} for r in recent]}
    # ---------------- C. concorrência (anúncios reais, só comparáveis)
    lp = _q(db, "SELECT product_id, COUNT(DISTINCT source || item_id) AS n FROM market_listings WHERE product_id IS NOT NULL "
                "GROUP BY product_id ORDER BY n DESC LIMIT 12")
    comp = []
    for r in lp:
        ls = MK.listing_stats(db, r["product_id"], 90, today)
        if ls:
            comp.append({"produto_id": r["product_id"], "produto": NM.name_of(db, r["product_id"]), "anuncios": ls["anuncios"],
                         "elegiveis": ls["anuncios_elegiveis"], "preco_min": ls["preco_min"], "mediana": ls["preco_mediano"],
                         "preco_max": ls["preco_max"], "moeda": ls["moeda"], "marcas": ls["marcas_distintas"]})
    chg = _q(db, "SELECT source, item_id, MIN(price) AS mn, MAX(price) AS mx, COUNT(DISTINCT day) AS d, MAX(title) AS t FROM market_listings "
                 "WHERE price IS NOT NULL GROUP BY source, item_id HAVING d >= 2 AND mx > mn * 1.1 ORDER BY (mx - mn) / mn DESC LIMIT 8")
    c = {"produtos_com_anuncios": len(lp), "faixas_preco": comp, "marcas_identificadas": (_q(db, "SELECT COUNT(DISTINCT LOWER(brand)) AS n FROM market_listings WHERE brand IS NOT NULL") or [{"n": 0}])[0]["n"],
         "mudancas_preco": [{"anuncio": r["t"], "fonte": r["source"], "de": r["mn"], "ate": r["mx"], "coletas": r["d"]} for r in chg],
         "nota": "Faixas de preço só entre anúncios do produto exato/variante compatível (por unidade). Anúncios não são vendas."}
    # ---------------- D. comércio exterior (Comex Stat agregado por NCM)
    ser = _q(db, "SELECT id, series_key, product_key, country, indicator, unit FROM market_series WHERE source = 'comexstat' AND indicator LIKE '%FOB%' LIMIT 400")
    growth = []
    origins = Counter()
    for s in ser:
        obs = _q(db, "SELECT ref_date, value FROM market_obs WHERE series_id = ? ORDER BY ref_date DESC LIMIT 24", (s["id"],))
        if len(obs) >= 24:
            last, prev = sum(o["value"] for o in obs[:12]), sum(o["value"] for o in obs[12:24])
            if prev > 0:
                growth.append({"serie": s["series_key"], "ncm": s["product_key"], "pais": s["country"], "ultimos_12m": round(last),
                               "anteriores_12m": round(prev), "variacao_pct": round(100 * (last / prev - 1), 1), "unidade": s["unit"]})
        if s["country"] and len(obs):
            origins[s["country"]] += obs[0]["value"] if obs else 0
    growth.sort(key=lambda x: -x["variacao_pct"])
    d = {"ncm_monitoradas": len({s["product_key"] for s in ser}), "maiores_variacoes": growth[:10], "menores_variacoes": growth[-5:][::-1] if len(growth) > 10 else [],
         "paises_origem": origins.most_common(8),
         "nota": "Estatística da classificação NCM inteira (todos os produtos da NCM), não do produto pesquisado. Variação: 12 meses × 12 anteriores."}
    # ---------------- E. qualidade
    ss = _q(db, "SELECT source, state, last_success, message FROM source_status")
    ok = [r for r in ss if r["state"] in ("funcional", "ok", "parcial")]
    bad = [r for r in ss if r["state"] not in ("funcional", "ok", "parcial", "nao_configurada", "desativada", None)]
    last_sync = (_q(db, "SELECT MAX(finished_at) AS f FROM sync_runs") or [{"f": None}])[0]["f"]
    jobs = _q(db, "SELECT result FROM research_jobs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 20")
    cv = defaultdict(Counter)
    for jr in jobs:
        res = json.loads(jr["result"] or "null") or {}
        for k in ("comercial", "contextual", "tecnica"):
            cv[k][((res.get("coberturas") or {}).get(k) or {}).get("nivel") or "—"] += 1
    alerts = _q(db, "SELECT COUNT(*) AS n FROM alert_state WHERE estado != 'resolvido' AND categoria = 'qualidade'")
    e = {"fontes_funcionando": len(ok), "fontes_indisponiveis": [{"fonte": r["source"], "estado": r["state"], "motivo": (r["message"] or "")[:160]} for r in bad][:10],
         "ultima_sincronizacao": last_sync, "coberturas_ultimas_pesquisas": {k: dict(v) for k, v in cv.items()},
         "alertas_qualidade": (alerts or [{"n": None}])[0]["n"]}
    empty = {
        "mercado": None if rank else "Nenhum produto com evidência comercial elegível — sincronize fontes de pesquisa/marketplace ou rode uma Pesquisa de Produtos.",
        "concorrencia": None if comp else "Nenhum anúncio coletado — conecte eBay/Mercado Livre e rode uma pesquisa direcionada.",
        "comex": None if ser else "Sem séries do Comex Stat — rode a sincronização (fonte pública, sem credencial).",
    }
    return {"portfolio": a, "mercado": b, "concorrencia": c, "comex": d, "qualidade": e, "vazios": empty,
            "links": {"portfolio": "#inteligencia-oportunidades", "mercado": "#nichos", "concorrencia": "#mkt-intel", "comex": "#brasil",
                      "qualidade": "#diagnostico-integracoes"}}
