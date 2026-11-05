"""v0.8.1 — inteligência de mercado: estatística robusta, classes de evidência, scores sem nota neutra, idiomas ≠ países,
coberturas com fórmula, alertas agrupados e Product Discovery Engine (conjunto rotulado independente)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from gpi.intel import commercial, discovery
from gpi.intel import semantics as S
from gpi.products import insights, trends as T


def _months(n, start=1):
    return [((start - 1 + i) % 12) + 1 for i in range(n)]


# ------------------------------------------------------------------ sazonalidade robusta
def test_seasonality_needs_three_cycles_to_confirm():
    rng = np.random.default_rng(1)
    pat = np.array([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 3, 5], float)
    y24 = np.tile(pat, 2) * 100 + rng.normal(0, 3, 24)
    y48 = np.tile(pat, 4) * 100 + rng.normal(0, 3, 48)
    r24 = T.robust_seasonality(y24, _months(24), "busca_relativa")
    r48 = T.robust_seasonality(y48, _months(48), "busca_relativa")
    assert r24["classificacao"] != "confirmada" and not r24["significativa"]
    assert r48["classificacao"] == "confirmada" and r48["significativa"]
    assert r48["pico_mes"] == 12 and r48["criterios"]["pico_estavel_ok"]


def test_seasonality_noise_not_detected_and_attention_labelled():
    rng = np.random.default_rng(7)
    y = 100 + rng.normal(0, 10, 48)
    r = T.robust_seasonality(y, _months(48), "visualizacoes")
    assert r["classificacao"] != "confirmada"
    assert r["tipo_indicador"] == "atenção"


# ------------------------------------------------------------------ comparações múltiplas
def test_bh_adjust_monotone_and_controls_fdr():
    p = [0.001, 0.01, 0.02, 0.04, 0.3, 0.9]
    q = T.bh_adjust(p)
    assert all(qi >= pi for qi, pi in zip(q, p))
    assert q[0] <= q[1] <= q[2] <= q[3] <= q[4] <= q[5] <= 1
    # 100 p-valores uniformes (ruído): após BH quase nada fica abaixo de 0,05
    rng = np.random.default_rng(3)
    q2 = T.bh_adjust(list(rng.uniform(0, 1, 100)))
    assert sum(x < 0.05 for x in q2) <= 1
    assert T.bh_adjust([]) == []


# ------------------------------------------------------------------ idioma ≠ país
def test_language_pages_are_not_countries():
    assert "LANG:en" in T.LANG_PAGES and "LANG:en" not in T.GEO_PAGES
    assert set(T.GEO_PAGES) == {"BR", "US", "CN"}


def test_lead_lag_language_never_consistent():
    ll = {"correlacao": 0.9, "significativa": True, "estavel": True, "ganho_backtest": 0.3, "n": 60}
    c = T.classify_lead_lag(ll, "linguistica", "busca_relativa")
    assert c["classe_antecedencia"] != "sinal internacional consistente"
    assert T.classify_lead_lag(ll, "mista", "busca_relativa")["classe_antecedencia"] == "séries não comparáveis"


def test_lead_lag_weak_correlation_is_exploratory():
    ll = {"correlacao": 0.26, "significativa": True, "estavel": True, "ganho_backtest": 0.01, "n": 60}
    c = T.classify_lead_lag(ll, "geografica", "busca_relativa")
    assert c["classe_antecedencia"] == "relação exploratória"
    assert c["r2"] == pytest.approx(0.068, abs=1e-3)
    unstable = T.classify_lead_lag({**ll, "estavel": False}, "geografica", "busca_relativa")
    assert unstable["classe_antecedencia"] == "relação instável"
    for k in T.LL_CLASSES:
        assert isinstance(k, str)


def test_lead_lag_consistent_requires_everything():
    ll = {"correlacao": 0.6, "significativa": True, "estavel": True, "ganho_backtest": 0.12, "n": 48}
    metric = next(k for k, v in T.METRICS.items() if v.get("tipo") == "busca")
    assert T.classify_lead_lag(ll, "geografica", metric)["classe_antecedencia"] == "sinal internacional consistente"
    assert T.classify_lead_lag({**ll, "n": 12}, "geografica", metric)["classe_antecedencia"] == "relação exploratória"


# ------------------------------------------------------------------ Wikipédia não classifica demanda
def test_attention_series_never_gets_demand_status():
    s = {"metrica": {"tipo": "atencao"}, "ind": {"classe": "declínio", "n": 60, "media_3m": 500}, "n": 60}
    assert insights.series_status(s) == "EVIDÊNCIA INSUFICIENTE"


# ------------------------------------------------------------------ classes de evidência e scores
def _ev(tipo, **kw):
    e = {"tipo": tipo, "frequencia": "mes", "derivado": {}, "elegibilidade": {"tendencia": True, "previsao": False},
         "observacoes_n": 36, "completude_n": 36, "fonte": "f_" + tipo, "fonte_nome": "Fonte " + tipo, "mercado": "BR",
         "tipo_rotulo": "Interesse de pesquisa", "metrica": "m", "pagina": "BR", "periodo": "2023-01 a 2025-12"}
    e.update(kw)
    return e


def _prod(evs, pos=(), cov=0, ir=0):
    return {"produto_id": "p", "identificacao": {"produto": "Produto", "categoria": "c"}, "evidencias": evs,
            "confirmacao_cruzada": {"fontes_independentes_positivas": list(pos), "confirmado": len(pos) >= 2},
            "indices": {"evidence_coverage": cov, "import_readiness": ir}}


def test_evidence_classes_are_distinct():
    a = commercial.evidence_class(S.DEMAND)["classe"]
    b = commercial.evidence_class(S.COMMERCIAL)["classe"]
    c = commercial.evidence_class(S.SEARCH)["classe"]
    d = commercial.evidence_class(S.PUBLIC)["classe"]
    assert len({a, b, c, d}) == 4 and a == "A"
    assert d not in ("A", "B", "C")


def test_scores_have_no_neutral_fifty_without_data():
    sc = commercial.scores(_prod([]))
    for k in ("commercial_evidence", "momentum", "persistence", "cross_source_confirmation", "import_readiness",
              "investigation_priority"):
        assert sc[k]["valor"] is None, k
        assert sc[k]["status"] in ("não avaliado", "evidência insuficiente"), k
    assert sc["import_readiness"]["status"] == "não avaliado"


def test_wikipedia_only_product_has_no_priority():
    sc = commercial.scores(_prod([_ev(S.PUBLIC, derivado={"momentum": 0.8, "persistencia": 0.9})], cov=30))
    assert sc["investigation_priority"]["valor"] is None
    assert sc["momentum"]["valor"] is None


def test_search_product_gets_partial_priority_with_formula():
    sc = commercial.scores(_prod([_ev(S.SEARCH, derivado={"momentum": 0.2, "persistencia": 0.7})], cov=50))
    assert sc["momentum"]["valor"] == pytest.approx(20.0)
    assert sc["investigation_priority"]["valor"] is not None
    assert sc["investigation_priority"]["status"] == "parcial"     # sem evidência comercial
    assert "não entram como 50" in sc["investigation_priority"]["como"]


# ------------------------------------------------------------------ coberturas
def test_coverage_formulas_exclude_attention():
    P = {"a": _prod([_ev(S.SEARCH)]), "b": _prod([_ev(S.PUBLIC)]), "c": _prod([])}
    for k, p in P.items():
        p["produto_id"] = k
    cov = commercial.coverage(P, 10)
    assert cov["catalogo"]["numerador"] == 2 and cov["catalogo"]["valor"] == 20.0
    assert cov["comercial"]["numerador"] == 1 and cov["comercial"]["valor"] == 10.0
    for k in ("catalogo", "comercial", "temporal", "geografica", "previsao"):
        assert cov[k]["formula"]
    assert cov["geografica"]["por_mercado"]["LANG:en"]["dimensao"] == "público linguístico"


# ------------------------------------------------------------------ alertas
def test_failed_sources_grouped_into_single_alert():
    srcs = [{"id": f"s{i}", "estado": "falhou", "ultima_coleta_ok": None} for i in range(5)]
    al = commercial.alerts({}, {"verificacoes": []}, srcs, date(2026, 10, 1))
    errs = [a for a in al["itens"] if a["tipo"] == "erro de coleta"]
    assert len(errs) == 1 and "5 fonte(s)" in errs[0]["motivo"]
    assert set(al["contagem"]) <= {"comercial", "estatístico", "qualidade"}


# ------------------------------------------------------------------ Product Discovery Engine
def test_discovery_eval_set_quality():
    ev = discovery.evaluate()
    assert ev["casos"] >= 60
    assert ev["acuracia"] >= 0.9
    assert ev["taxa_incorreta"] <= 0.05
    assert ev["precision_produto_fisico"] >= 0.9


@pytest.mark.parametrize("term,cls", [("assinatura netflix", "serviço"), ("eletronicos", "categoria genérica")])
def test_discovery_services_and_generic(term, cls):
    assert discovery.classify(term, "pt")["classe"] == cls
