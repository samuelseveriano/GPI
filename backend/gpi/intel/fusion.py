"""Product Intelligence Fusion Engine — PIFE (v0.8, seções 5, 8, 10, 13).

Fluxo: séries por produto (trends.build_series/indicators) → Gate 4 (elegibilidade) → evidências por tipo semântico
(nunca convertidas entre si) → índices separados → situação → insight rastreável.

Camadas: OBSERVADO (valores das fontes, com IDs de observação), DERIVADO (indicadores calculados), PREVISTO (somente
séries elegíveis com backtesting).

Linhagem: cada evidência carrega IDs reproduzíveis das observações —
  so:<fonte>|<país>|<data>|<métrica>|<termo>   (search_observations)
  ms:<id da série>@<data>                       (market_series/market_obs)

Critérios matemáticos (documentados em docs/PRODUCT_INTELLIGENCE.md):
* momentum      = média dos 3 últimos meses ÷ 3 anteriores − 1 (ano contra ano quando ≥ 15 meses)
* aceleração    = momentum atual − momentum anterior (p.p.), ≥ 9 meses
* persistência  = fração de variações mensais positivas nos últimos 12 meses (ano contra ano em série sazonal)
* volatilidade  = desvio das variações ÷ média (valores > 0)
* sazonalidade  = força STL-like com teste (trends.seasonality_strength), ≥ 24 meses
* mudança de patamar = segmentação binária com penalidade 2·ln(n)·σ²; anomalias = |z robusto| > 3,5
* reversão      = inclinação Theil-Sen dos 6 últimos meses com sinal oposto à dos 6 anteriores, ambas |·| ≥ 2%/mês
* atenção relativa (Wikipédia) = (1 + crescimento do artigo) ÷ (1 + mediana dos artigos do mesmo idioma) − 1
* confirmação cruzada = ≥ 2 fontes INDEPENDENTES de demanda (pesquisa ou ranking comercial) com sinal positivo
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

import numpy as np

from . import matching, mlrank, quality, semantics
from .semantics import COMMERCIAL, PUBLIC, SEARCH

DEMAND = (SEARCH, COMMERCIAL)
GROWING = {"EMERGENTE", "CRESCIMENTO CONSISTENTE", "ACELERAÇÃO"}
INTERMEDIATE = {"NOVO SINAL COMERCIAL", "SINAL EM OBSERVAÇÃO", "INTERESSE RECORRENTE", "SINAL INTERMITENTE",
                "ATENÇÃO PÚBLICA EM ALTA", "VARIAÇÃO NÃO CONFIRMADA"}
CLASSES = ["NOVO SINAL COMERCIAL", "EMERGENTE", "SINAL EM OBSERVAÇÃO", "INTERESSE RECORRENTE", "SINAL INTERMITENTE",
           "CRESCIMENTO CONSISTENTE", "ACELERAÇÃO", "ESTÁVEL", "SAZONAL", "POSSÍVEL SATURAÇÃO", "VARIAÇÃO NÃO CONFIRMADA",
           "POSSÍVEL DECLÍNIO", "MUDANÇA NA FONTE", "DECLÍNIO", "ATENÇÃO PÚBLICA EM ALTA", "EVIDÊNCIA INSUFICIENTE"]
CLASS_DEF = {
    "NOVO SINAL COMERCIAL": "Primeira presença num ranking comercial (1 semana). Não é crescimento sustentado.",
    "EMERGENTE": "Primeira observação recente numa fonte de pesquisa (≤ 3 meses).",
    "SINAL EM OBSERVAÇÃO": "Sinal interessante, mas ainda insuficiente: alta > 15% sem significância estatística, ou 2–3 semanas em ranking.",
    "INTERESSE RECORRENTE": "Presente no ranking comercial em ≥ 4 semanas e em ≥ 50% das semanas coletadas.",
    "SINAL INTERMITENTE": "Presente no ranking em ≥ 4 semanas, mas em < 50% das semanas coletadas.",
    "CRESCIMENTO CONSISTENTE": "Tendência de alta significativa (Mann-Kendall/Theil-Sen; ano contra ano em série sazonal) com base suficiente.",
    "ACELERAÇÃO": "Crescimento consistente com aceleração > 10 p.p.",
    "ESTÁVEL": "Evidência suficiente, sem tendência significativa.",
    "SAZONAL": "Sazonalidade significativa, sem tendência.",
    "POSSÍVEL SATURAÇÃO": "Crescimento com desaceleração > 10 p.p. e nível perto do máximo histórico.",
    "VARIAÇÃO NÃO CONFIRMADA": "Queda > 15% na comparação recente, sem significância estatística nem persistência — não é declínio.",
    "DECLÍNIO": "Declínio confirmado NA MÉTRICA OBSERVADA: tendência de queda significativa após correção para múltiplos testes (BH), ou queda > 15% com base suficiente e persistência ≤ 40%.",
    "POSSÍVEL DECLÍNIO": "Queda > 15% com base suficiente e persistência baixa, sem significância após a correção para múltiplos testes.",
    "MUDANÇA NA FONTE": "A queda acompanha a queda geral da fonte (mediana dos artigos do mesmo idioma) — não é queda específica do produto.",
    "ATENÇÃO PÚBLICA EM ALTA": "Leituras/notícias acima da mediana dos demais produtos, SEM evidência de pesquisa ou compra.",
    "EVIDÊNCIA INSUFICIENTE": "Sem série elegível de pesquisa ou sinal comercial.",
}
NEXT = {
    "NOVO SINAL COMERCIAL": "Acompanhar as próximas semanas do ranking e verificar fontes independentes de interesse comercial.",
    "EMERGENTE": "Acompanhar mais períodos e buscar confirmação em fonte independente antes de investir esforço comercial.",
    "SINAL EM OBSERVAÇÃO": "Manter em observação; buscar uma segunda fonte de demanda (volume de buscas ou ranking comercial).",
    "INTERESSE RECORRENTE": "Investigar preços, concorrência e especificações; conferir volume de buscas para dimensionar a procura.",
    "SINAL INTERMITENTE": "Verificar se a presença é sazonal ou promocional antes de investigar.",
    "CRESCIMENTO CONSISTENTE": "Investigar preços, concorrência, especificações, fornecedores e requisitos de importação.",
    "ACELERAÇÃO": "Prioridade de investigação: confirmar em fonte independente, levantar fornecedores e requisitos regulatórios.",
    "ESTÁVEL": "Demanda estável: avaliar diferenciação, preço e concorrência.",
    "SAZONAL": "Planejar a investigação antes do pico sazonal; comparar o mesmo período de anos diferentes.",
    "POSSÍVEL SATURAÇÃO": "Cautela: verificar concorrência e se o crescimento está perdendo força.",
    "VARIAÇÃO NÃO CONFIRMADA": "Aguardar novos períodos: a queda ainda não é estatisticamente confirmada.",
    "DECLÍNIO": "Baixa prioridade enquanto a queda persistir (vale para a métrica observada, não para vendas).",
    "POSSÍVEL DECLÍNIO": "Acompanhar: a queda ainda não é estatisticamente confirmada.",
    "MUDANÇA NA FONTE": "Desconsiderar como sinal do produto: a fonte inteira mudou de patamar.",
    "ATENÇÃO PÚBLICA EM ALTA": "Atenção não é demanda: verificar volume de buscas ou ranking comercial antes de qualquer conclusão.",
    "EVIDÊNCIA INSUFICIENTE": "Coletar dados de pesquisa ou ranking comercial (mais períodos ou outra fonte).",
}


def _tanh_index(g: float | None, scale: float = 0.4) -> float | None:
    if g is None or not np.isfinite(g):
        return None
    return float(max(0.0, min(100.0, 50 + 50 * math.tanh(g / scale))))


def _theil(y) -> float | None:
    y = np.asarray(y, float)
    if len(y) < 4 or np.mean(y) <= 0:
        return None
    sl = [(y[j] - y[i]) / (j - i) for i in range(len(y)) for j in range(i + 1, len(y))]
    return float(np.median(sl) / np.mean(y))


def reversal(vals) -> dict | None:
    v = [x for x in (vals or [])]
    if len(v) < 12:
        return None
    a, b = _theil(v[-12:-6]), _theil(v[-6:])
    if a is None or b is None:
        return None
    if abs(a) >= 0.02 and abs(b) >= 0.02 and a * b < 0:
        return {"de": "alta" if a > 0 else "queda", "para": "alta" if b > 0 else "queda",
                "inclinacao_anterior": round(a, 4), "inclinacao_recente": round(b, 4)}
    return None


def cohort_medians(series: list[dict]) -> dict:
    """Mediana do crescimento da Wikipédia por idioma, só entre artigos com base suficiente (fator comum)."""
    by = defaultdict(list)
    for s in series:
        ind = s.get("ind") or {}
        if s.get("metric") == "visualizacoes" and ind.get("crescimento") is not None and ind.get("base_suficiente"):
            by[s["country"]].append(ind["crescimento"])
    return {k: float(np.median(v)) for k, v in by.items() if len(v) >= 5}


def lineage(db, pid: str) -> dict:
    fam = pid.split(":")[0]
    rows = db.query("SELECT source, country, ref_date, metric, term FROM search_observations WHERE product_id = ? OR product_id LIKE ? "
                    "ORDER BY ref_date DESC LIMIT 40", (fam, fam + ":%"))
    n = db.query("SELECT COUNT(*) AS n FROM search_observations WHERE product_id = ? OR product_id LIKE ?", (fam, fam + ":%"))[0]["n"]
    ids = [f"so:{r['source']}|{r['country']}|{r['ref_date']}|{r['metric']}|{r['term']}" for r in rows]
    return {"ids": ids, "total": int(n), "consulta": f"search_observations WHERE product_id = '{fam}' OR product_id LIKE '{fam}:%'"}


def _evidence(s: dict, cohort: dict, fc: dict) -> dict:
    ind = s.get("ind") or {}
    meta = semantics.METRICS.get(s["metric"], {})
    tipo = meta.get("tipo")
    e = s.get("elegibilidade") or quality.series_eligibility(s)
    ev = {"serie": s["id"], "camada": "observado", "tipo": tipo, "tipo_rotulo": semantics.TYPE_LABEL.get(tipo),
          "nao_e": semantics.TYPE_NOT.get(tipo), "metrica": s["metric"], "indicador": meta.get("nome_comercial"),
          "unidade": meta.get("unidade"), "fonte": s["source"], "fonte_nome": s.get("fonte_nome") or s["source"],
          "mercado": s.get("pais_nome") or s.get("country"), "pais": s.get("country"),
          "periodo": f"{ind.get('primeiro') or '—'} a {ind.get('ultimo') or '—'}", "observacoes_n": ind.get("n"),
          "frequencia": s.get("period"), "elegibilidade": e["metodos"], "motivos_inelegibilidade": e["motivos"],
          "classe_serie": ind.get("classe"), "pagina": s.get("page"),
          "dimensao": "público linguístico" if str(s.get("page", "")).startswith("LANG:") else "mercado geográfico",
          "completude_n": sum(1 for v in (ind.get("valores") or []) if v),
          "serie_valores": [round(float(v), 2) for v in (ind.get("valores") or [])[-24:]],
          "serie_rotulos": (ind.get("labels") or [])[-24:]}
    from .commercial import evidence_class
    ev.update(evidence_class(tipo))
    if s.get("market_series_id"):
        labs = ind.get("labels") or []
        ev["observacoes"] = [f"ms:{s['market_series_id']}@{d}-01" for d in labs[-12:]]
    derived = {}
    if meta.get("crescimento_pct") and e["metodos"].get("tendencia"):
        derived["momentum"] = ind.get("crescimento")
        derived["base_momentum"] = ind.get("base_crescimento")
    if e["metodos"].get("aceleracao"):
        derived["aceleracao"] = ind.get("aceleracao")
    if e["metodos"].get("tendencia"):
        derived["persistencia"] = ind.get("persistencia")
        derived["volatilidade"] = ind.get("volatilidade")
        derived["tendencia"] = ind.get("tendencia")
        derived["mudancas_patamar"] = ind.get("pontos_mudanca") or []
        derived["anomalias"] = ind.get("anomalias") or []
        derived["reversao"] = reversal(ind.get("valores"))
    if e["metodos"].get("sazonalidade") or (ind.get("sazonalidade") or {}).get("classificacao") in ("confirmada", "possível"):
        derived["sazonalidade"] = ind.get("sazonalidade")
    if s["metric"] == "visualizacoes" and ind.get("crescimento") is not None and s["country"] in cohort:
        med = cohort[s["country"]]
        derived["mediana_coorte"] = med
        derived["atencao_relativa"] = (1 + ind["crescimento"]) / (1 + med) - 1 if (1 + med) > 0 else None
    if s.get("period") == "dia":
        derived["dias_em_alta_30d"] = ind.get("dias_em_alta_30d")
        derived["dias_historico"] = ind.get("dias_historico")
    ev["derivado"] = derived
    f = fc.get(s["id"])
    if f and e["metodos"].get("previsao") and f.get("status") == "prevista":
        ev["previsto"] = {"camada": "previsto", "modelo": f.get("modelo_nome") or f.get("modelo"),
                          "horizonte": len(f.get("previsao") or []), "metricas": f.get("metricas"),
                          "baseline_selecionado": bool(f.get("baseline_selecionado") or f.get("modelo") == "naive"),
                          "intervalos": [k for k in ("lo80", "lo90", "lo95") if f.get(k)], "limitacoes": f.get("limitacoes")}
    elif f and not e["metodos"].get("previsao"):
        ev["previsao_bloqueada"] = e["motivos"].get("previsao")
    return ev


def _demand_status(ev: dict) -> str:
    """Situação a partir da principal evidência de PESQUISA elegível (critérios v0.8, mais rígidos que a v0.7.1)."""
    d, cls = ev["derivado"], ev["classe_serie"]
    if ev["frequencia"] == "dia":
        return "EMERGENTE" if cls == "emergente" else "SINAL EM OBSERVAÇÃO" if cls == "presença recorrente" else "EVIDÊNCIA INSUFICIENTE"
    if not ev["elegibilidade"].get("tendencia"):
        return "EVIDÊNCIA INSUFICIENTE"
    tt = d.get("tendencia") or {}
    g = d.get("momentum")
    sig = tt.get("significativa_bh", tt.get("significativa"))          # v0.8.1: significância ajustada (BH) quando houver
    sig_up = sig and tt.get("direcao") == "crescimento"
    sig_dn = sig and tt.get("direcao") == "queda"
    pers = d.get("persistencia")
    if cls == "emergente":
        return "EMERGENTE"
    if cls == "possível saturação":
        return "POSSÍVEL SATURAÇÃO"
    if cls == "crescimento acelerado":
        return "ACELERAÇÃO"
    if cls == "crescimento consistente" or (sig_up and (g or 0) > 0):
        return "CRESCIMENTO CONSISTENTE"
    if (g or 0) > 0.15:
        return "SINAL EM OBSERVAÇÃO"
    if sig_dn or ((g or 0) < -0.15 and pers is not None and pers <= 0.4 and ev["elegibilidade"].get("aceleracao")):
        return "DECLÍNIO"
    if cls == "mudança na fonte":
        return "MUDANÇA NA FONTE"
    if (g or 0) < -0.15 and cls == "possível declínio":
        return "POSSÍVEL DECLÍNIO"
    if (g or 0) < -0.15:
        return "VARIAÇÃO NÃO CONFIRMADA"
    if cls == "sazonal":
        return "SAZONAL"
    return "ESTÁVEL"


def _match_quality(db, pid: str, cache: dict, ids: set) -> dict:
    fam = pid.split(":")[0]
    if fam in cache:
        return cache[fam]
    rows = db.query("SELECT DISTINCT term, lang FROM search_observations WHERE product_id = ? OR product_id LIKE ? LIMIT 60",
                    (fam, fam + ":%"))
    st = defaultdict(int)
    for r in rows:
        m = matching.match(r["term"], r["lang"], ids or None, target=fam)
        st[m.get("estado_alvo", m["estado"])] += 1
    n = sum(st.values())
    conf = st.get(matching.CONFIRMED, 0) / n if n else None
    out = {"termos": n, "por_estado": dict(st), "fracao_confirmada": conf,
           "confiavel": conf is None or conf >= 0.8}
    cache[fam] = out
    return out


def product(pid: str, lst: list[dict], prod: dict, ml: dict | None, fc: dict, sc: dict, cohort: dict,
            mq: dict | None, lin: dict | None) -> dict:
    # o ranking do Mercado Livre é tratado só pelo mlrank (uma observação por semana, sem %): a série diária antiga sai
    evs = [_evidence(s, cohort, fc) for s in lst if s["metric"] != "posicao_tendencia"]
    # sinal comercial (Mercado Livre) — evidência própria
    if ml:
        evs.append({"serie": f"{pid}|BR|ml_trends|posicao_tendencia", "camada": "observado", "tipo": COMMERCIAL,
                    "tipo_rotulo": semantics.TYPE_LABEL[COMMERCIAL], "nao_e": semantics.TYPE_NOT[COMMERCIAL],
                    "metrica": "posicao_tendencia", "indicador": semantics.METRICS["posicao_tendencia"]["nome_comercial"],
                    "unidade": "posição (1–50)", "fonte": "ml_trends", "fonte_nome": "Mercado Livre", "mercado": "Brasil", "pais": "BR",
                    "periodo": f"{ml['primeira_semana']} a {ml['ultima_semana']}", "observacoes_n": ml["n_observacoes"],
                    "frequencia": "semana", "elegibilidade": {"tendencia": False, "previsao": False},
                    "motivos_inelegibilidade": {"previsao": "ranking sem volume — avaliado por persistência e posição"},
                    "derivado": {k: ml.get(k) for k in ("semanas_coletadas", "semanas_presente", "persistencia", "melhor_posicao",
                                                       "posicao_media", "ultima_posicao", "variacao_posicao", "entradas", "saidas",
                                                       "reaparecimentos", "estabilidade", "classe", "primeira_semana", "ultima_semana",
                                                       "historico")},
                    "pagina": "BR", "dimensao": "mercado geográfico", "classe": "B", "classe_nome": "Intenção comercial",
                    "observacoes": ml["observacoes"], "termos": ml["termos"], "classe_serie": ml["classe"]})
    by_type = defaultdict(list)
    for e in evs:
        by_type[e["tipo"]].append(e)
    # ---------- índices separados
    idx, why = {}, {}
    search = [e for e in by_type.get(SEARCH, []) if e["elegibilidade"].get("tendencia") or e["frequencia"] == "dia"]
    best_s = None
    if search:
        best_s = max(search, key=lambda e: ((e["pais"] == "BR"), e["observacoes_n"] or 0))
        d = best_s["derivado"]
        if best_s["frequencia"] == "dia":
            idx["search_interest_index"] = round(100 * min(1.0, (d.get("dias_em_alta_30d") or 0) / 10), 1)
        else:
            v = _tanh_index(d.get("momentum"))
            tt = d.get("tendencia") or {}
            if v is not None and tt.get("significativa"):
                v = max(0.0, min(100.0, v + (10 if tt.get("direcao") == "crescimento" else -10)))
            idx["search_interest_index"] = None if v is None else round(v, 1)
    else:
        idx["search_interest_index"] = None
        why["search_interest_index"] = ("sem série de pesquisa elegível" if by_type.get(SEARCH)
                                        else "nenhuma fonte de pesquisa com dados para este produto")
    if ml:
        cii = 100 * (ml["persistencia"] or 0) * (1 - 0.5 * ((ml["posicao_media"] or 50) - 1) / 49)
        if ml["semanas_presente"] == 1:
            cii = min(cii, 40.0)
        idx["commercial_intent_index"] = round(cii, 1)
    else:
        idx["commercial_intent_index"] = None
        why["commercial_intent_index"] = "produto não apareceu em ranking comercial coletado"
    pub = [e for e in by_type.get(PUBLIC, []) if e["elegibilidade"].get("tendencia")]
    if pub:
        rel = [e["derivado"].get("atencao_relativa", e["derivado"].get("momentum")) for e in pub]
        rel = [r for r in rel if r is not None]
        idx["public_attention_index"] = round(_tanh_index(float(np.median(rel))), 1) if rel else None
        if not rel:
            why["public_attention_index"] = "séries de atenção sem variação calculável"
    else:
        idx["public_attention_index"] = None
        why["public_attention_index"] = "sem série de atenção pública elegível"
    # cobertura: tipos de evidência elegível × qualidade
    W = {SEARCH: 35, COMMERCIAL: 30, PUBLIC: 15, semantics.TRADE: 10, semantics.DEMAND: 10}
    cov = 0.0
    for t, w in W.items():
        lst_t = by_type.get(t, [])
        if not lst_t:
            continue
        if t == COMMERCIAL:
            q = min(1.0, (ml or {}).get("semanas_presente", 0) / 8)
        else:
            q = max(min(1.0, (e["observacoes_n"] or 0) / (24 if e["frequencia"] != "dia" else 60)) for e in lst_t)
        cov += w * q
    n_src = len({e["fonte"] for e in evs if e["tipo"] in DEMAND})
    idx["evidence_coverage"] = round(min(100.0, cov + (5 if n_src >= 2 else 0)), 1)
    fcs = [e["previsto"] for e in evs if e.get("previsto")]
    if fcs:
        f = fcs[0]
        w = (f.get("metricas") or {}).get("wape")
        idx["forecast_confidence"] = 30.0 if f["baseline_selecionado"] else round(max(0.0, 100 * (1 - min(1.0, w or 1.0))), 1)
    else:
        idx["forecast_confidence"] = None
        why["forecast_confidence"] = next((e["motivos_inelegibilidade"].get("previsao") for e in evs
                                           if e["motivos_inelegibilidade"].get("previsao")), "sem série elegível para previsão")
    idx["import_readiness"] = sc.get("import_readiness")
    if idx["import_readiness"] is None:
        why["import_readiness"] = "sem análise de conformidade registrada para o produto"
    parts = [(0.45, idx["search_interest_index"]), (0.35, idx["commercial_intent_index"]), (0.20, idx["public_attention_index"])]
    if idx["search_interest_index"] is None and idx["commercial_intent_index"] is None:
        idx["opportunity_score"] = None
        why["opportunity_score"] = ("apenas atenção pública (notícias/enciclopédia): sem evidência de pesquisa ou compra"
                                    if idx["public_attention_index"] is not None else "sem evidência de pesquisa ou sinal comercial")
    else:
        num = sum(w * v for w, v in parts if v is not None)
        den = sum(w for w, v in parts if v is not None)
        idx["opportunity_score"] = round(num / den * (0.6 + 0.4 * idx["evidence_coverage"] / 100), 1)
    # ---------- situação
    status = _demand_status(best_s) if best_s else None
    if ml and (status in (None, "EVIDÊNCIA INSUFICIENTE")):
        status = ml["classe"]
    if status in (None, "EVIDÊNCIA INSUFICIENTE") and idx["public_attention_index"] is not None and idx["public_attention_index"] >= 65:
        status = "ATENÇÃO PÚBLICA EM ALTA"
    status = status or "EVIDÊNCIA INSUFICIENTE"
    positive = set()
    for e in evs:
        if e["tipo"] not in DEMAND:
            continue
        d = e["derivado"]
        if e["tipo"] == COMMERCIAL and (d.get("semanas_presente") or 0) >= 2:
            positive.add(e["fonte"])
        elif (d.get("momentum") or 0) > 0.05 and (d.get("tendencia") or {}).get("significativa"):
            positive.add(e["fonte"])
        elif e["frequencia"] == "dia" and (d.get("dias_em_alta_30d") or 0) >= 3:
            positive.add(e["fonte"])
    cross = {"fontes_independentes_positivas": sorted(positive), "confirmado": len(positive) >= 2,
             "nota": "Wikipédia e notícias não contam como confirmação de demanda."}
    radar = ("crescimento confirmado por fontes independentes" if cross["confirmado"] and status in GROWING | {"INTERESSE RECORRENTE"}
             else "crescimento observado" if status in GROWING else "interesse recorrente" if status == "INTERESSE RECORRENTE"
             else "primeira observação" if status in ("NOVO SINAL COMERCIAL", "EMERGENTE") else None)
    alerts = []
    for e in evs:
        d = e["derivado"]
        if d.get("mudancas_patamar"):
            alerts.append({"tipo": "mudança de patamar", "serie": e["serie"], "quando": d["mudancas_patamar"][-1], "fonte": e["fonte_nome"]})
        if d.get("anomalias"):
            alerts.append({"tipo": "anomalia", "serie": e["serie"], "quando": d["anomalias"][-1], "fonte": e["fonte_nome"]})
        if d.get("reversao"):
            alerts.append({"tipo": "possível reversão", "serie": e["serie"], "detalhe": d["reversao"], "fonte": e["fonte_nome"]})
    if status == "DECLÍNIO":
        alerts.append({"tipo": "declínio", "serie": best_s["serie"] if best_s else None, "fonte": best_s["fonte_nome"] if best_s else None})
    if mq and not mq["confiavel"]:
        alerts.append({"tipo": "qualidade dos dados", "detalhe": f"apenas {mq['fracao_confirmada']:.0%} dos termos associados ao produto "
                       "têm correspondência confirmada"})
    out = {"produto_id": pid, "identificacao": _ident(pid, prod), "situacao": status, "definicao_situacao": CLASS_DEF[status],
            "radar": radar, "indices": idx, "indices_motivos": why, "evidencias": evs, "confirmacao_cruzada": cross,
            "alertas": alerts, "correspondencia": mq, "linhagem": lin,
            "fontes": sorted({e["fonte_nome"] for e in evs}), "tipos_evidencia": sorted({e["tipo"] for e in evs if e["tipo"]}),
            "proxima_acao": NEXT[status]}
    from . import commercial
    out["pontuacao"] = commercial.scores(out)
    out["niveis"] = commercial.levels(out)
    return out


def _ident(pid: str, prod: dict) -> dict:
    a = prod.get("attributes") or {}
    return {"produto": prod.get("canonical") or pid, "categoria": prod.get("category"), "familia": prod.get("family"),
            "nivel": prod.get("level"), "variante": prod.get("canonical") if prod.get("level") == "variante" else None,
            "marca": a.get("marca"), "modelo": a.get("modelo"),
            "especificacoes": {k: v for k, v in a.items() if k not in ("marca", "modelo", "qualificadores")},
            "nomes": {"pt": prod.get("name_pt"), "en": prod.get("name_en"), "zh": prod.get("name_zh")}}


def build(db, result: dict, catalog_products: dict, today: date | None = None, with_lineage: bool = True) -> dict:
    series = result.get("series") or []
    g1 = quality.gate1(db, today)
    blocked = set(g1["excluidos_da_modelagem"])
    g4 = quality.gate4(series)
    for s in series:                      # Gate 1: dados reprovados não avançam para análise/modelagem
        if f"{s['source']}/{s['metric']}" in blocked or f"{s['source']}/*" in blocked:
            e = s["elegibilidade"]
            for k in e["metodos"]:
                e["metodos"][k] = False
                e["motivos"][k] = "dados reprovados no Gate 1 (integridade) — ver Qualidade dos Dados"
    cohort = cohort_medians(series)
    ml = mlrank.analyze(db) if "ml_trends/posicao_tendencia" not in blocked else {"por_produto": {}, "semanas_coletadas": [],
                                                                                   "termos": [], "bloqueado": "Gate 1"}
    by = defaultdict(list)
    for s in series:
        by[s["product_id"]].append(s)
    for pid in ml["por_produto"]:
        by.setdefault(pid, [])
    ids = {r["product_id"] for r in db.query("SELECT product_id FROM catalog_products WHERE level = 'produto'")}
    cache: dict = {}
    items = {}
    for pid, lst in by.items():
        items[pid] = product(pid, lst, catalog_products.get(pid, {}), ml["por_produto"].get(pid), result.get("previsoes") or {},
                             (result.get("scores") or {}).get(pid) or {}, cohort, _match_quality(db, pid, cache, ids),
                             lineage(db, pid) if with_lineage else None)
    return {"produtos": items, "gate1": g1, "gate4": g4, "coorte_wikipedia": cohort, "mercado_livre": ml,
            "classes": [{"classe": c, "definicao": CLASS_DEF[c]} for c in CLASSES], "gerado_em": result.get("gerado_em")}
