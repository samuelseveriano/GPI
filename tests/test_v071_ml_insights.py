"""v0.7.1 — auditoria do ML (backtesting sem vazamento, baseline, séries curtas/intermitentes, intervalos) e
Inteligência de Oportunidades (insights determinísticos, grupos, clusters). Séries SINTÉTICAS de teste."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import report_fixture as F

from gpi.db import Database
from gpi.forecasting.backtest import backtest
from gpi.market.automl import auto_forecast
from gpi.products import insights as I
from gpi.products import trends as T
from gpi.products.catalog import Catalog

RNG = np.random.default_rng(7)
IDX = lambda n: pd.period_range("2022-01", periods=n, freq="M").to_timestamp()   # noqa: E731


def ser(y):
    return pd.Series(np.asarray(y, float), index=IDX(len(y)))


def test_backtest_has_no_future_leakage():
    y = 100 + np.arange(48) * 2 + RNG.normal(0, 3, 48)
    a = backtest(y, 6, 12, ["naive", "ses", "holt_damped"], n_origins=4)
    y2 = y.copy()
    y2[-1] = 1e6                                    # muda só o último ponto (futuro de todas as origens exceto a última janela)
    b = backtest(y2, 6, 12, ["naive", "ses", "holt_damped"], n_origins=4)
    first = a["origens"][0]
    assert first + 6 <= len(y) - 1                 # a 1ª origem não enxerga o último ponto nem no teste
    # previsões dependem só de y[:T]: as métricas da 1ª origem em diante só mudam onde o ponto alterado é TESTE
    assert a["origens"] == b["origens"]
    for k in ("naive", "ses"):
        assert a["resultados"][k]["wape"] != b["resultados"][k]["wape"]      # o ponto entra como teste…
    r = auto_forecast(ser(y), {"source": "x"}, horizon=6)
    r2 = auto_forecast(ser(np.r_[y, [np.nan] * 0]), {"source": "x"}, horizon=6)
    assert r["previsao"] == r2["previsao"]                                 # reprodutível


@pytest.mark.parametrize("name,y,expect", [
    ("tendência", 100 + np.arange(48) * 3 + RNG.normal(0, 2, 48), "prevista"),
    ("sazonal", 100 + 30 * np.sin(np.arange(48) * 2 * np.pi / 12) + RNG.normal(0, 2, 48), "prevista"),
    ("estacionária", 100 + RNG.normal(0, 5, 48), "prevista"),
    ("intermitente", np.where(RNG.random(48) < 0.7, 0, RNG.integers(1, 6, 48)), "prevista"),
    ("mudança estrutural", np.r_[np.full(24, 50.0), np.full(24, 120.0)] + RNG.normal(0, 2, 48), "prevista"),
    ("anomalias", np.where(np.arange(48) % 17 == 0, 500, 100) + RNG.normal(0, 2, 48), "prevista"),
    ("curta", 100 + RNG.normal(0, 5, 8), "exploratoria"),
])
def test_series_types_and_intervals(name, y, expect):
    r = auto_forecast(ser(y), {"source": "x"}, horizon=6)
    assert r["status"] == expect, name
    if expect == "prevista":
        for lo, hi in (("lo80", "hi80"), ("lo90", "hi90"), ("lo95", "hi95")):
            assert all(a <= p + 1e-9 <= b + 1e-9 for a, p, b in zip(r[lo], r["previsao"], r[hi])), (name, lo)
        assert np.all(np.asarray(r["hi95"]) >= np.asarray(r["hi80"]) - 1e-9)
        assert "baseline_selecionado" in r
    else:
        assert "previsao" not in r and "sem previsão" in r["limitacao"]            # nada de previsão artificial


def test_baseline_used_when_nothing_beats_it():
    y = np.cumsum(RNG.normal(0, 1, 60)) + 100          # passeio aleatório: Naive é ótimo
    r = auto_forecast(ser(y), {"source": "x"}, horizon=6, allow_ml=False)
    if r["modelo"] == "naive":
        assert r["baseline_selecionado"] and any("baseline" in x for x in r["limitacoes"])
    else:
        assert (r["metricas"].get("fva_vs_naive") or 0) > 0


@pytest.fixture(scope="module")
def consumer(tmp_path_factory):
    d = tmp_path_factory.mktemp("ins")
    db = Database(d / "g.sqlite")
    F.build(db)
    r = T.analyze(db, {}, F.TODAY, forecasts=True)
    prods = {p["product_id"]: p for p in Catalog(db, {}).products()}
    yield db, r, prods
    db.close()


def test_insights_are_deterministic_and_grounded(consumer):
    db, r, prods = consumer
    a = I.build(r, db, prods)
    b = I.build(r, db, prods)
    assert a["itens"] == b["itens"] and a["clusters"] == b["clusters"]             # reprodutível
    assert a["itens"], "nenhum insight"
    valid = {"EMERGENTE", "CRESCIMENTO CONSISTENTE", "ACELERAÇÃO", "ESTÁVEL", "SAZONAL", "POSSÍVEL SATURAÇÃO", "DECLÍNIO",
             "EVIDÊNCIA INSUFICIENTE"}
    for it in a["itens"]:
        assert it["situacao"] in valid and it["confianca"] in ("alta", "moderada", "baixa")
        assert it["proxima_acao"] and it["analise"]
        assert "não são unidades vendidas" in it["limitacoes"][0]
        if it["situacao"] == "EVIDÊNCIA INSUFICIENTE":
            assert it["confianca"] == "baixa" and it["produto_id"] not in a["grupos"]["merecem_investigacao"]
    for k in ("crescendo", "perdendo_interesse", "crescimento_consistente", "possiveis_modismos", "sazonais",
              "eua_antes_do_brasil", "multiplas_fontes", "merecem_investigacao", "precisam_mais_dados"):
        assert k in a["grupos"]
    assert "não é probabilidade" in a["aviso"]


def test_small_series_never_big_opportunity():
    s = {"id": "x", "product_id": "p", "source": "google_trends_rss", "period": "mes", "country": "BR",
         "metrica": {"tipo": "busca", "rotulo": "x"}, "ind": {"n": 3, "classe": "crescimento", "crescimento": 4.0, "base_suficiente": False}}
    it = I.product_insight("p", [s], {"opportunity_score": 90, "evidence_coverage": 20}, {}, {})
    assert it["situacao"] == "EVIDÊNCIA INSUFICIENTE" and it["confianca"] == "baixa"


def test_clusters_interpretable_and_reproducible():
    items = []
    for i in range(12):
        g = [0.5, 0.05, -0.3][i % 3]
        items.append({"produto_id": f"p{i}", "nome": f"P{i}", "situacao": "ESTÁVEL", "crescimento_recente": g + RNG.normal(0, 0.01),
                      "volatilidade": [0.1, 0.1, 0.2][i % 3], "aceleracao": [0.2, 0.0, -0.1][i % 3],
                      "persistencia": {"positivos": [10, 6, 2][i % 3], "periodos": 12}, "sazonal": False})
    c1, c2 = I.clusters(items), I.clusters(items)
    assert c1 == c2 and c1["k"] >= 2 and c1["silhouette"] > 0.25
    names = {g["nome"] for g in c1["grupos"]}
    assert "Produtos com crescimento acelerado" in names and "Produtos em possível declínio" in names
    assert I.clusters(items[:4])["aviso"].startswith("apenas 4")


def test_insights_api(tmp_path):
    from test_api_integration import Srv
    s = Srv(tmp_path / "data")
    try:
        code, d = s.req("/api/consumer/insights")
        assert code == 200 and "grupos" in d and "aviso" in d
        code, one = s.req("/api/consumer/insights/produto-inexistente")
        assert code == 200 and one["situacao"] == "EVIDÊNCIA INSUFICIENTE"
    finally:
        s.stop()


def test_conformal_levels_not_identical_or_indefensible():
    from gpi.forecasting.advanced import conformal
    small = {3: [np.array([0.1, 0.2])], 2: [np.array([0.3, 0.1])], 1: [np.array([0.2, 0.2])]}
    c = conformal(small)
    assert c["quantis"] == {} and set(c["niveis_indisponiveis"]) == {"0.8", "0.9", "0.95"}     # n=2: nada defensável
    big = {o: [RNG.normal(0, 0.2, 6) for _ in range(30)] for o in (3, 2, 1)}
    c = conformal(big)
    q80, q95 = np.array(c["quantis"]["0.8"]), np.array(c["quantis"]["0.95"])
    assert np.all(q95 >= q80) and np.any(q95 > q80) and "0.8" in c["cobertura_observada"]
