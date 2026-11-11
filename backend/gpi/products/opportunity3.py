"""
Product Opportunity Engine 3.0 (v0.6): transforma pesquisas, marketplaces e redes sociais em
oportunidades de INVESTIGAÇÃO comercial.

Nove dimensões (0–100, vazias quando não há dados — nunca preenchidas com suposições):
  Consumer Search Strength · Social Momentum · Marketplace Evidence · Trend Persistence ·
  Competition Pressure · Product Quality Risk · Evidence Coverage · Forecast Confidence · Import Readiness

Índice (0–100) = média ponderada das dimensões disponíveis, renormalizada pela cobertura:
  busca 25% · social 10% · marketplace 15% · persistência 15% · (100 − concorrência) 10% ·
  (100 − risco de qualidade) 10% · confiança da previsão 5% · prontidão de importação 10%.
Prioridade de investigação: "Evidência insuficiente" quando a cobertura de evidências < 40 ou há
menos de duas dimensões de demanda; "Alta" quando índice ≥ 65 e pelo menos dois tipos de fonte
independentes apontam crescimento; "Média" quando índice ≥ 45; "Baixa" nos demais.
Não calcula probabilidade de sucesso, margem nem recomenda pedidos de compra.
"""
from __future__ import annotations

import math

import numpy as np

from .trends import METRICS

W = {"consumer_search_strength": 0.25, "social_momentum": 0.10, "marketplace_evidence": 0.15, "trend_persistence": 0.15,
     "competition_pressure": 0.10, "product_quality_risk": 0.10, "forecast_confidence": 0.05, "import_readiness": 0.10}
INVERTED = {"competition_pressure", "product_quality_risk"}
DEMAND = ("consumer_search_strength", "social_momentum", "marketplace_evidence", "trend_persistence")


def _sq(g):
    return max(0.0, min(1.0, 0.5 + 0.5 * math.tanh(2 * g)))


def _offer_summary(c: dict) -> dict:
    return {"tipo_evidencia": "Oferta observada", "mercado": c.get("mercado"), "fonte": c.get("fonte"), "moeda": c.get("moeda"),
            "anuncios": c.get("anuncios"), "anuncios_elegiveis": c.get("anuncios_elegiveis"),
            "excluidos": c.get("excluidos_acessorios_incompativeis"), "concorrentes_observados": c.get("concorrentes_observados", c.get("vendedores_unicos")),
            "marcas_distintas": c.get("marcas_distintas"), "preco_min": c.get("preco_min"), "preco_mediano": c.get("preco_mediano"),
            "preco_max": c.get("preco_max"), "posicionamento": c.get("posicionamento"), "pressao_competitiva": c.get("pressao_competitiva"),
            "dias_observados": c.get("dias_observados"), "ultima_coleta": c.get("ultima_coleta"), "status": c.get("status"),
            "afeta_indicadores_do_mercado": c.get("mercado") == MARKET}


GROUPS = {"Interesse do consumidor": ("consumer_search_strength", "social_momentum", "trend_persistence"),
          "Mercado": ("competition_pressure", "marketplace_evidence"),
          "Viabilidade": ("import_readiness", "product_quality_risk"),
          "Confiabilidade": ("forecast_confidence",)}


def _groups(d: dict) -> dict:
    out = {g: {k: d[k] for k in ks if k in d} for g, ks in GROUPS.items()}
    out["Comércio exterior"] = "contexto — não entra no índice (importação ≠ procura)"
    return out


def _trade(pid: str, ctx: dict) -> dict | None:
    from .catalog import NCM_HINT
    from ..suite.trade import EXTRA_SH4
    head = pid.split("+")[0].split(":")[0]
    sh4 = NCM_HINT.get(head) or EXTRA_SH4.get(head)
    t = ctx.get(sh4) if sh4 else None
    if not t:
        return {"sh4_candidata": sh4, "estado": "sem série Comex Stat de 24 meses"} if sh4 else None
    return {"sh4_candidata": sh4, "descricao": t["descricao"], "variacao_12m_pct": t["variacao_12m_pct"], "ultimos_12m_usd": t["ultimos_12m_usd"],
            "ate": t["ate"], "tipo_evidencia": "Informações contextuais (classificação ampla, Brasil)"}


MARKET = "BR"      # indicadores de decisão do GPI (importação para o Brasil): só oferta do mercado brasileiro entra no índice


def build(consumer: dict, social: dict | None, reviews: dict | None, competition: dict | None, db=None) -> dict:
    social = social or {}
    series = consumer.get("series", [])
    scores = consumer.get("scores", {})
    svs = {r["product_id"]: r for r in social.get("search_vs_social", [])}
    soc = social.get("scores", {})
    rev = {r["product_id"]: r for r in (reviews or {}).get("produtos", [])}
    comp = {}
    for c in (competition or {}).get("itens", []):
        comp.setdefault(c["product_id"], []).append(c)
    # nível de busca relativo dentro de cada métrica (percentil) — nunca entre métricas
    lvl = {}
    for metric in {s["metric"] for s in series}:
        vals = {s["id"]: s["ind"].get("media_3m", s["ind"].get("soma_30d")) for s in series if s["metric"] == metric}
        vals = {k: v for k, v in vals.items() if v is not None}
        if len(vals) >= 2:
            ks = sorted(vals, key=vals.get)
            for i, k in enumerate(ks):
                lvl[k] = i / (len(ks) - 1)
        elif vals:
            lvl[next(iter(vals))] = 0.5
    by = {}
    for s in series:
        by.setdefault(s["product_id"], []).append(s)
    ids = set(by) | set(soc) | {p for p, cs in comp.items() if any(c.get("anuncios_elegiveis") for c in cs)}
    rows = []
    trade_ctx = {}
    if db is not None:
        try:
            from ..suite.trade import category_growth
            trade_ctx = {i["codigo"]: i for i in category_growth(db, 100000, 0)["itens"]}
        except Exception:  # noqa: BLE001 — contexto opcional
            trade_ctx = {}
    for pid in ids:
        lst = by.get(pid, [])
        sc = scores.get(pid, {})
        d = {}
        srch = [s for s in lst if METRICS.get(s["metric"], {}).get("tipo") in ("busca", "busca_ranking") and s["source"] != "ml_trends"]
        if srch:
            parts = [0.5 * lvl.get(s["id"], 0.5) + 0.5 * (_sq(s["ind"]["crescimento"]) if s["ind"].get("crescimento") is not None else 0.5)
                     for s in srch]
            d["consumer_search_strength"] = round(100 * max(parts), 1)
        if soc.get(pid, {}).get("social_trend_score") is not None:
            d["social_momentum"] = soc[pid]["social_trend_score"]
        if svs.get(pid, {}).get("marketplace_signals") is not None:
            d["marketplace_evidence"] = svs[pid]["marketplace_signals"]
        pers = sc.get("componentes", {}).get("persistencia")
        sp = (soc.get(pid) or {}).get("componentes", {}).get("persistencia")
        vals = [v for v in (pers, sp) if v is not None]
        if vals:
            d["trend_persistence"] = round(100 * float(np.mean(vals)), 1)
        # v0.9.1 MVP: só a oferta do mercado do índice (Brasil) entra; anúncios dos EUA ficam como oferta observada
        # contextual e NÃO influenciam indicadores brasileiros. Amostra pequena → pressão None (dimensão ausente).
        local = [c for c in comp.get(pid, []) if c.get("mercado", MARKET) == MARKET]
        cp = [c.get("pressao_competitiva") for c in local if c.get("pressao_competitiva") is not None]
        if cp:
            d["competition_pressure"] = round(float(np.mean(cp)), 1)
        elif sc.get("componentes", {}).get("concorrencia_baixa") is not None:
            d["competition_pressure"] = round(100 * (1 - sc["componentes"]["concorrencia_baixa"]), 1)
        r = rev.get(pid)
        if r and r.get("suficiente"):
            tech = sum(x["mencoes"] for x in r.get("problemas_tecnicos", []))
            crit = sum(x["mencoes"] for x in r.get("criticas", []))
            d["product_quality_risk"] = round(100 * min(1.0, (tech + 0.5 * max(0, crit - tech)) / max(1, r["n"])), 1)
        if sc.get("forecast_confidence"):
            d["forecast_confidence"] = sc["forecast_confidence"]
        ready = dict(sc.get("checklist_importacao") or {})
        if any(c.get("anuncios_elegiveis", 1) for c in local):
            ready["Preços observados"] = True
        if ready:
            d["import_readiness"] = round(100 * sum(bool(v) for v in ready.values()) / len(ready), 1)
        types = sum(1 for k in ("consumer_search_strength", "social_momentum", "marketplace_evidence") if k in d) + \
            (1 if "product_quality_risk" in d else 0) + (1 if ready.get("Importações monitoradas (Comex Stat)") else 0)
        d["evidence_coverage"] = round(100 * types / 5, 1)
        avail = {k: v for k, v in d.items() if k in W}
        cov = sum(W[k] for k in avail)
        idx = None
        if cov:
            idx = round(sum(W[k] * ((100 - v) if k in INVERTED else v) for k, v in avail.items()) / cov, 1)
        rising = []
        if (svs.get(pid) or {}).get("search_growth") is not None and svs[pid]["search_growth"] > 0.05:
            rising.append("busca")
        elif any((s["ind"].get("crescimento") or 0) > 0.05 for s in srch):
            rising.append("busca")
        if (soc.get(pid) or {}).get("crescimento_social") is not None and soc[pid]["crescimento_social"] > 0.05:
            rising.append("social")
        if (d.get("marketplace_evidence") or 0) >= 40:
            rising.append("marketplace")
        ndem = sum(1 for k in DEMAND if k in d)
        if d["evidence_coverage"] < 40 or ndem < 2:
            prio = "Evidência insuficiente"
        elif idx is not None and idx >= 65 and len(rising) >= 2:
            prio = "Alta"
        elif idx is not None and idx >= 45:
            prio = "Média"
        else:
            prio = "Baixa"
        risks = list(sc.get("riscos", []))
        if (soc.get(pid) or {}).get("somente_uma_plataforma"):
            risks.append("atenção social em uma única plataforma")
        if (soc.get(pid) or {}).get("classe_radar") == "Viralização recente":
            risks.append("pico recente nas redes: pode ser passageiro")
        if (d.get("product_quality_risk") or 0) >= 40:
            risks.append("reclamações técnicas frequentes nas avaliações")
        if (d.get("competition_pressure") or 0) >= 66:
            risks.append("pressão competitiva alta")
        nxt = []
        if "consumer_search_strength" not in d:
            nxt.append("medir o volume de buscas (Google Ads/Microsoft Advertising)")
        if not ready.get("NCM/SH fundamentado"):
            nxt.append("classificar o NCM com um despachante")
        if not ready.get("Preços observados"):
            nxt.append("levantar preços de venda no varejo")
        nxt.append("cotar fornecedores e custos de importação (Viabilidade de Importação)")
        if "product_quality_risk" not in d:
            nxt.append("ler avaliações de consumidores do produto")
        nome = (lst[0]["nome"] if lst else soc.get(pid, {}).get("nome"))
        if not nome and db is not None:
            from ..suite import naming as NM
            nome = NM.name_of(db, pid)
        nome = nome or pid
        cat = (lst[0].get("categoria") if lst else soc.get(pid, {}).get("categoria"))
        elig = prio != "Evidência insuficiente"
        # v0.9.1: o índice é renormalizado pelos pesos DISPONÍVEIS — com 1 dimensão a 100 ele virava 100 com evidência
        # insuficiente. Agora só é exibido como índice de decisão quando elegível; caso contrário fica como parcial.
        expl = [{"dimensao": k, "peso": W[k], "valor": v, "invertido": k in INVERTED,
                 "contribuicao": round(W[k] * ((100 - v) if k in INVERTED else v) / cov, 1) if cov else None} for k, v in avail.items()]
        rows.append({"product_id": pid, "nome": nome, "categoria": cat, "indice": idx if elig else None, "indice_parcial": idx,
                     "elegivel_para_decisao": elig, "explicacao": {"componentes": expl, "dimensoes_ausentes": [k for k in W if k not in avail],
                                                                    "peso_disponivel": round(cov / sum(W.values()), 2),
                                                                    "motivo": None if elig else "cobertura < 40% ou menos de 2 dimensões de demanda: "
                                                                    "índice parcial NÃO elegível para decisão"},
                     "prioridade": prio, "dimensoes": d,
                     "oferta_observada": [_offer_summary(c) for c in comp.get(pid, [])],
                     "dimensoes_agrupadas": _groups(d),
                     "comercio_exterior": _trade(pid, trade_ctx),
                     "tipos_de_evidencia": {
                         "Oferta observada": bool(comp.get(pid)),
                         "Interesse de pesquisa": "consumer_search_strength" in d,
                         # só série MENSAL de busca com ≥ 15 meses (crescimento 12m) e tendência significativa; oferta nunca conta
                         "Crescimento comprovado": any((s["ind"].get("crescimento_12m") or 0) > 0.05 and
                                                       ((s["ind"].get("tendencia") or {}).get("p_valor") or 1) < 0.05 for s in srch),
                         "Informações contextuais": bool(soc.get(pid)) or any(c.get("mercado") != MARKET for c in comp.get(pid, [])),
                         "Evidência insuficiente": not elig},
                     "cobertura_indice": round(cov / sum(W.values()), 2), "fontes_em_alta": rising,
                     "fornecedores": "não verificado (sem fonte autorizada conectada)",
                     "ncm": None, "riscos": list(dict.fromkeys(risks)), "proximos_passos": nxt})
    if db is not None:
        hints = {r["product_id"]: r["ncm_hint"] for r in db.query("SELECT product_id, ncm_hint FROM catalog_products WHERE ncm_hint IS NOT NULL")}
        for r in rows:
            r["ncm"] = hints.get(r["product_id"])
    order = {"Alta": 0, "Média": 1, "Baixa": 2, "Evidência insuficiente": 3}
    rows.sort(key=lambda r: (order[r["prioridade"]], -(r["indice"] if r["indice"] is not None else -1)))
    return {"produtos": rows, "pesos": W, "metodologia": __doc__.strip(),
            "aviso": "Classificação para priorizar investigação. Não é probabilidade de sucesso, margem nem recomendação de compra."}
