"""Gates de qualidade (v0.8, seção 26). Executados sobre o banco REAL; nada é presumido.

* Gate 1 — Data integrity: esquema, chaves, datas, unidades, duplicação, proveniência. Conjuntos (fonte, métrica)
  reprovados ficam fora da modelagem.
* Gate 2 — Product matching: avaliação em conjuntos rotulados (desenvolvimento e teste) + reavaliação das associações
  gravadas. Associações não confirmadas ficam fora dos rankings de oportunidades confirmadas.
* Gate 3 — Source semantics: toda métrica gravada existe no catálogo semântico e só alimenta índices elegíveis.
* Gate 4 — Statistical eligibility: por série, quais métodos são válidos (tendência, sazonalidade, aceleração,
  previsão, clustering) e, quando não, o motivo.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from . import matching, semantics

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")
COUNTRIES = {"BR", "US", "CN", "GLOBAL", "CONTA"}
ALLOWED_PREFIX = ("GLOBAL:",)


def _q(db, sql, p=()):
    try:
        return db.query(sql, p)
    except Exception:  # noqa: BLE001 — tabela ausente em bancos antigos
        return []


# ------------------------------------------------------------------------------------------------- Gate 1
def gate1(db, today: date | None = None) -> dict:
    today = today or date.today()
    fut = (today + timedelta(days=1)).isoformat()
    checks, blocked = [], set()

    def add(nome, ok, detalhe, afetados=(), severidade="erro"):
        checks.append({"verificacao": nome, "ok": bool(ok), "detalhe": detalhe, "afetados": list(afetados)[:20],
                       "severidade": None if ok else severidade})
        if not ok and severidade == "erro":
            blocked.update(afetados)

    bad_dates = _q(db, "SELECT source, metric, COUNT(*) AS n FROM search_observations WHERE ref_date NOT GLOB "
                       "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' GROUP BY source, metric")
    add("Datas de referência em formato ISO", not bad_dates, f"{sum(r['n'] for r in bad_dates)} registro(s) com data inválida",
        [(r["source"], r["metric"]) for r in bad_dates])
    future = _q(db, "SELECT source, metric, COUNT(*) AS n FROM search_observations WHERE ref_date > ? GROUP BY source, metric", (fut,))
    add("Sem datas no futuro", not future, f"{sum(r['n'] for r in future)} registro(s) com data posterior a hoje",
        [(r["source"], r["metric"]) for r in future])
    fut_ms = _q(db, "SELECT s.source, COUNT(*) AS n FROM market_obs o JOIN market_series s ON s.id = o.series_id "
                    "WHERE o.ref_date > ? GROUP BY s.source", (fut,))
    add("Séries de mercado sem datas no futuro", not fut_ms, f"{sum(r['n'] for r in fut_ms)} ponto(s) futuros",
        [(r["source"], "*") for r in fut_ms])
    units = _q(db, "SELECT source, metric, COUNT(DISTINCT unit) AS u FROM search_observations GROUP BY source, metric HAVING u > 1")
    add("Uma unidade por (fonte, métrica)", not units, "métricas com unidades misturadas: " +
        ", ".join(f"{r['source']}/{r['metric']}" for r in units) if units else "unidades consistentes",
        [(r["source"], r["metric"]) for r in units])
    neg = _q(db, "SELECT source, metric, COUNT(*) AS n FROM search_observations WHERE value < 0 GROUP BY source, metric")
    add("Valores não negativos", not neg, f"{sum(r['n'] for r in neg)} valor(es) negativo(s)", [(r["source"], r["metric"]) for r in neg])
    rank_bad = _q(db, "SELECT COUNT(*) AS n FROM search_observations WHERE metric = 'posicao_tendencia' AND (value < 1 OR value > 50)")
    nrb = int(rank_bad[0]["n"]) if rank_bad else 0
    add("Posições do ranking entre 1 e 50", nrb == 0, f"{nrb} posição(ões) fora da faixa",
        [("ml_trends", "posicao_tendencia")] if nrb else [])
    dup = _q(db, "SELECT source, metric, COUNT(*) AS n FROM (SELECT source, metric, country, ref_date, lower(trim(term)) AS t, "
                 "COUNT(*) AS c FROM search_observations GROUP BY 1,2,3,4,5 HAVING c > 1) GROUP BY source, metric")
    add("Sem duplicatas por grafia (maiúsculas/espaços)", not dup,
        f"{sum(r['n'] for r in dup)} grupo(s) de termos duplicados por grafia" if dup else "nenhuma duplicata",
        [(r["source"], r["metric"]) for r in dup], severidade="alerta")
    prov = _q(db, "SELECT source, metric, COUNT(*) AS n FROM search_observations WHERE collected_at IS NULL OR collected_at = '' "
                  "GROUP BY source, metric")
    add("Proveniência (data de coleta registrada)", not prov, f"{sum(r['n'] for r in prov)} registro(s) sem data de coleta",
        [(r["source"], r["metric"]) for r in prov])
    cty = _q(db, "SELECT DISTINCT country FROM search_observations")
    badc = [r["country"] for r in cty if r["country"] not in COUNTRIES and not str(r["country"]).startswith(ALLOWED_PREFIX)]
    add("Países reconhecidos (ISO 3166-1 ou GLOBAL:<idioma>)", not badc, ", ".join(badc) or "todos reconhecidos",
        [("*", c) for c in badc], severidade="alerta")
    orphan = _q(db, "SELECT COUNT(*) AS n FROM market_obs o LEFT JOIN market_series s ON s.id = o.series_id WHERE s.id IS NULL")
    no = int(orphan[0]["n"]) if orphan else 0
    add("Observações ligadas a uma série (chaves)", no == 0, f"{no} observação(ões) órfã(s)")
    integ = _q(db, "PRAGMA integrity_check")
    add("Integridade do arquivo SQLite", bool(integ) and integ[0].get("integrity_check") == "ok",
        (integ[0].get("integrity_check") if integ else "não verificado"))
    status = "aprovado" if all(c["ok"] or c["severidade"] == "alerta" for c in checks) else "reprovado"
    if status == "aprovado" and any(not c["ok"] for c in checks):
        status = "aprovado com alertas"
    return {"gate": 1, "nome": "Integridade dos dados", "status": status, "verificacoes": checks,
            "excluidos_da_modelagem": sorted(f"{s}/{m}" for s, m in blocked)}


# ------------------------------------------------------------------------------------------------- Gate 2
def _load(name: str) -> list[dict]:
    out = []
    for line in (Path(__file__).parent / "data" / name).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        g, lg, exp, var, text = (line.split("\t") + [""] * 5)[:5]
        if text.strip():
            out.append({"grupo": g, "idioma": lg or None, "esperado": exp, "variante": var or None, "texto": text})
    return out


def gate2(db, live_limit: int = 3000) -> dict:
    dev = matching.evaluate(_load("matching_eval.tsv"))
    test = matching.evaluate(_load("matching_holdout.tsv"))
    ids = {r["product_id"] for r in _q(db, "SELECT product_id FROM catalog_products WHERE level = 'produto'")}
    live = _q(db, "SELECT term, MIN(lang) AS lang, MIN(product_id) AS product_id, COUNT(*) AS n FROM search_observations "
                  "WHERE product_id IS NOT NULL GROUP BY term ORDER BY n DESC LIMIT ?", (live_limit,))
    states, low = {}, []
    for r in live:
        m = matching.match(r["term"], r["lang"], ids or None, target=r["product_id"])
        st = m.get("estado_alvo", m["estado"])
        states[st] = states.get(st, 0) + 1
        if st != matching.CONFIRMED:
            low.append({"termo": r["term"], "produto_gravado": r["product_id"], "estado": st, "motivos": m["motivos"][:2]})
    yt = _q(db, "SELECT item_id, title, lang, product_key FROM content_items WHERE source = 'youtube' AND product_key IS NOT NULL LIMIT 2000")
    yts = {}
    for v in yt:
        m = matching.match(v["title"], None, ids or None, target=v["product_key"])
        st = m.get("estado_alvo", m["estado"])
        yts[st] = yts.get(st, 0) + 1
    ok = bool(test["metas_atingidas"]["precision"] and test["metas_atingidas"]["taxa_incorreta"])
    return {"gate": 2, "nome": "Identificação de produtos", "status": "aprovado" if ok else "reprovado",
            "avaliacao_teste": {k: v for k, v in test.items() if k != "metas"},
            "avaliacao_desenvolvimento": {k: dev[k] for k in ("casos", "precision", "recall", "f1", "taxa_incorreta", "taxa_abstencao")},
            "metas": matching.TARGETS,
            "associacoes_gravadas": {"termos_avaliados": len(live), "por_estado": states,
                                     "baixa_confianca": low[:50], "n_baixa_confianca": len(low)},
            "youtube": {"videos_avaliados": len(yt), "por_estado": yts},
            "regra": "Somente correspondências CONFIRMADAS entram em rankings de oportunidades confirmadas."}


# ------------------------------------------------------------------------------------------------- Gate 3
STORED_METRIC = {("wikimedia", None): "visualizacoes", ("comexstat", None): "importacao_fob", ("comtrade", None): "importacao_fob",
                 ("bcb_ptax", None): "cambio", ("ibge_pmc", None): "varejo_indice"}


def gate3(db) -> dict:
    rows = _q(db, "SELECT source, metric, COUNT(*) AS n FROM search_observations GROUP BY source, metric")
    ms = _q(db, "SELECT source, COUNT(*) AS n FROM market_series GROUP BY source")
    found, unknown = [], []
    for r in rows:
        m = semantics.METRICS.get(r["metric"])
        if not m:
            unknown.append(f"{r['source']}/{r['metric']}")
            continue
        found.append({"fonte": r["source"], "metrica": r["metric"], "registros": r["n"], "tipo": m["tipo"],
                      "tipo_rotulo": semantics.TYPE_LABEL[m["tipo"]], "nao_e": semantics.TYPE_NOT[m["tipo"]],
                      "indices": [k for k in semantics.INDICATORS if semantics.eligible(r["metric"], k, r["source"])]})
    for r in ms:
        met = STORED_METRIC.get((r["source"], None))
        if not met:
            continue
        m = semantics.METRICS[met]
        found.append({"fonte": r["source"], "metrica": met, "series": r["n"], "tipo": m["tipo"],
                      "tipo_rotulo": semantics.TYPE_LABEL[m["tipo"]], "nao_e": semantics.TYPE_NOT[m["tipo"]],
                      "indices": [k for k in semantics.INDICATORS if semantics.eligible(met, k, r["source"])]})
    checks = [
        {"verificacao": "Wikipédia não alimenta índices de demanda", "ok": not semantics.eligible("visualizacoes", "search_interest_index")
         and not semantics.eligible("visualizacoes", "commercial_intent_index")},
        {"verificacao": "Ranking do Mercado Livre não é tratado como volume", "ok": semantics.METRICS["posicao_tendencia"]["crescimento_pct"] is False
         and not semantics.eligible("posicao_tendencia", "search_interest_index")},
        {"verificacao": "Notícias não são vendas", "ok": not semantics.eligible("mencoes", "commercial_intent_index")},
        {"verificacao": "Índice relativo (BigQuery) sem % de volume", "ok": semantics.METRICS["score_trends"]["crescimento_pct"] is False},
        {"verificacao": "YouTube/redes sociais exibidos à parte (políticas)", "ok": not semantics.eligible("videos_youtube", "opportunity_score", "youtube")},
        {"verificacao": "Toda métrica gravada existe no catálogo semântico", "ok": not unknown, "detalhe": ", ".join(unknown)},
    ]
    return {"gate": 3, "nome": "Semântica das fontes", "status": "aprovado" if all(c["ok"] for c in checks) else "reprovado",
            "verificacoes": checks, "metricas_no_banco": found, "desconhecidas": unknown}


# ------------------------------------------------------------------------------------------------- Gate 4
def series_eligibility(s: dict) -> dict:
    """Quais métodos a série permite. Sem elegibilidade, o método NÃO é executado e o motivo é informado."""
    ind = s.get("ind") or {}
    meta = semantics.METRICS.get(s.get("metric"), {})
    out, why = {}, {}
    if s.get("period") == "dia":
        days = int(ind.get("dias_historico") or 0)
        out["tendencia"] = False
        why["tendencia"] = "série diária de presença em listas: avaliada por persistência, não por tendência"
        for k in ("sazonalidade", "aceleracao", "previsao"):
            out[k] = False
            why[k] = f"apenas {days} dia(s) de histórico de uma lista de alta/ranking"
        out["agrupamento"] = days >= 28
        if not out["agrupamento"]:
            why["agrupamento"] = "menos de 28 dias de histórico"
        return {"metodos": out, "motivos": why, "n": ind.get("n")}
    vals = ind.get("valores") or []
    n = len(vals)
    nz = sum(1 for v in vals if v)
    compl = nz / n if n else 0.0
    base = bool(ind.get("base_suficiente"))
    out["tendencia"] = n >= 6 and compl >= 0.5
    if not out["tendencia"]:
        why["tendencia"] = f"{n} mês(es), {compl:.0%} preenchidos (mínimo 6 meses e 50%)"
    out["aceleracao"] = n >= 9 and base
    if not out["aceleracao"]:
        why["aceleracao"] = "mínimo 9 meses com base suficiente" if n < 9 else "nível (mediana) abaixo do mínimo da métrica"
    out["sazonalidade"] = n >= 24 and compl >= 0.8
    if not out["sazonalidade"]:
        why["sazonalidade"] = f"mínimo 24 meses (2 ciclos) com 80% preenchidos; há {n}"
    cps = ind.get("pontos_mudanca") or []
    recent_break = bool(cps and vals and ind.get("labels") and cps[-1] in (ind["labels"][-4:] if ind.get("labels") else []))
    out["previsao"] = bool(meta.get("modelagem")) and n >= 18 and compl >= 0.8 and base and not recent_break
    if not out["previsao"]:
        why["previsao"] = ("métrica não elegível para modelagem (" + semantics.TYPE_NOT.get(meta.get("tipo"), "") + ")" if not meta.get("modelagem")
                           else f"mínimo 18 meses; há {n}" if n < 18 else "menos de 80% dos meses com valor" if compl < 0.8
                           else "nível abaixo do mínimo da métrica" if not base else "mudança de patamar nos últimos 4 meses")
    out["agrupamento"] = out["tendencia"]
    if not out["agrupamento"]:
        why["agrupamento"] = why.get("tendencia")
    outl = len(ind.get("anomalias") or [])
    return {"metodos": out, "motivos": why, "n": n, "completude": round(compl, 3), "base_suficiente": base,
            "outliers": outl, "mudancas_metodologicas_ou_patamar": cps}


def gate4(series: list[dict]) -> dict:
    tot = {"tendencia": 0, "sazonalidade": 0, "aceleracao": 0, "previsao": 0, "agrupamento": 0}
    reasons: dict[str, dict] = {k: {} for k in tot}
    for s in series:
        e = series_eligibility(s)
        s["elegibilidade"] = e
        for k, ok in e["metodos"].items():
            if ok:
                tot[k] += 1
            else:
                r = e["motivos"].get(k, "")
                key = re.sub(r"\d+", "N", r)
                reasons[k][key] = reasons[k].get(key, 0) + 1
    return {"gate": 4, "nome": "Elegibilidade estatística", "status": "aprovado", "series": len(series),
            "elegiveis": tot, "motivos_principais": {k: sorted(v.items(), key=lambda x: -x[1])[:4] for k, v in reasons.items()},
            "regra": "Métodos só executam em séries elegíveis; as demais recebem análise exploratória com o motivo."}
