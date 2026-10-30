"""Verificação matemática dos modelos contra resultados conhecidos."""
import numpy as np
import pytest

from gpi.forecasting import models as M
from gpi.forecasting.backtest import backtest, interval, metrics


def test_naive_forecast_and_variance():
    y = np.array([3.0, 5, 4, 6, 8])
    r = M.naive(y, 3)
    assert np.allclose(r.forecast, 8)
    # resíduos: 2, -1, 2, 2 → σ² = 13/4
    assert r.sigma2 == pytest.approx(13 / 4)
    assert np.allclose(r.var_h, 13 / 4 * np.array([1, 2, 3]))


def test_seasonal_naive_indexing():
    y = np.arange(1, 25, dtype=float)          # 2 ciclos de 12
    r = M.seasonal_naive(y, 14, m=12)
    assert np.allclose(r.forecast[:12], y[12:24])
    assert r.forecast[12] == y[12] and r.forecast[13] == y[13]
    assert r.var_h[11] == pytest.approx(r.sigma2) and r.var_h[12] == pytest.approx(2 * r.sigma2)


def test_moving_average():
    y = np.array([1.0, 2, 3, 4, 5, 6])
    r = M.moving_average(y, 2, k=3)
    assert np.allclose(r.forecast, 5.0)
    assert r.fitted[3] == pytest.approx(2.0) and r.fitted[5] == pytest.approx(4.0)


def test_ets_filter_matches_hand_recursion():
    y = np.array([10.0, 12, 11, 13])
    a, l0 = 0.5, 10.0
    f, lT, _, _ = M._ets_filter(y, a, 0, 0, 1, l0, 0, np.zeros(0), False, False, 1)
    l, exp = l0, []
    for v in y:
        exp.append(l)
        l = l + a * (v - l)
    assert np.allclose(f, exp) and lT == pytest.approx(l)


def test_ets_constant_series():
    y = np.full(30, 7.0)
    r = M.ets(y, 5, "ANN")
    assert np.allclose(r.forecast, 7.0, atol=1e-6)


def test_holt_recovers_linear_trend():
    t = np.arange(40, dtype=float)
    y = 5 + 2 * t
    r = M.ets(y, 4, "AAN")
    assert np.allclose(r.forecast, 5 + 2 * np.arange(40, 44), atol=1e-2)


def test_holt_winters_recovers_trend_and_season():
    t = np.arange(60, dtype=float)
    season = np.array([5, 3, 0, -2, -4, -6, -4, -2, 0, 2, 4, 4], float)
    y = 100 + 1.5 * t + season[t.astype(int) % 12]
    r = M.ets(y, 12, "AAA", m=12)
    tf = np.arange(60, 72)
    assert np.allclose(r.forecast, 100 + 1.5 * tf + season[tf % 12], atol=0.05)


def test_ets_ann_variance_formula():
    rng = np.random.default_rng(0)
    y = 50 + np.cumsum(rng.normal(0, 1, 80)) * 0.3 + rng.normal(0, 1, 80)
    r = M.ets(y, 6, "ANN")
    a = r.params["alpha"]
    expected = r.sigma2 * (1 + np.arange(6) * a ** 2)  # σ²[1 + (h−1)α²]
    assert np.allclose(r.var_h, expected)


def test_ets_params_respect_constraints():
    rng = np.random.default_rng(3)
    t = np.arange(48)
    y = 80 + t + 10 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 2, 48)
    r = M.ets(y, 6, "AAdA", m=12)
    p = r.params
    assert 0 < p["alpha"] < 1 and 0 <= p["beta"] <= p["alpha"]
    assert 0 <= p["gamma"] <= 1 - p["alpha"] + 1e-9 and 0.8 <= p["phi"] <= 0.98


def test_ets_auto_prefers_seasonal_on_seasonal_data():
    rng = np.random.default_rng(1)
    t = np.arange(48)
    y = 100 + 2 * t + 15 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 3, 48)
    r = M.ets_auto(y, 12, m=12)
    assert r.params["spec"].endswith("A") and r.params["spec"] != "AAN"


def test_croston_sba_hand_example():
    y = np.array([0, 0, 4, 0, 0, 0, 2, 0, 6, 0], float)
    fitted, f = M._croston_run(y, 0.1, sba=False)
    # inicialização: z=4, p=3; em t=6 (q=4): z=3.8, p=3.1; em t=8 (q=2): z=4.02, p=2.99
    z = 4 + 0.1 * (2 - 4); p = 3 + 0.1 * (4 - 3)
    z = z + 0.1 * (6 - z); p = p + 0.1 * (2 - p)
    assert f == pytest.approx(z / p)
    _, f_sba = M._croston_run(y, 0.1, sba=True)
    assert f_sba == pytest.approx((1 - 0.05) * z / p)


def test_tsb_decays_after_obsolescence():
    y = np.r_[np.tile([0, 5, 0, 3], 10), np.zeros(20)]
    assert M.tsb(y, 1).forecast[0] < M.croston(y, 1).forecast[0]


def test_short_series_rejected():
    with pytest.raises(M.ModelNotApplicable):
        M.ets(np.array([1.0, 2.0]), 3, "AAA", m=12)


# ---------------------------------------------------------------- métricas
def test_metrics_known_values():
    A = np.array([[10.0, 20.0]])
    P = np.array([[12.0, 16.0]])
    lo, hi = P - 3, P + 3
    m = metrics(A, P, lo, hi, np.array([4.0]))
    assert m["mae"] == pytest.approx(3.0)
    assert m["wape"] == pytest.approx(6 / 30)
    assert m["bias"] == pytest.approx(-1.0)
    assert m["rmse"] == pytest.approx(np.sqrt(10))
    assert m["rmsse"] == pytest.approx(np.sqrt(10 / 4))
    assert m["cobertura_80"] == pytest.approx(0.5)


def test_backtest_has_no_leakage(monkeypatch):
    seen = []
    real = M.run_model

    def spy(key, y, h, m):
        seen.append(len(y))
        return real(key, y, h, m)

    import gpi.forecasting.backtest as B
    monkeypatch.setattr(B, "run_model", spy)
    y = np.arange(40, dtype=float)
    bt = B.backtest(y, 4, 1, ["naive"], n_origins=5)
    assert seen == bt["origens"]                  # treino termina exatamente na origem
    assert max(bt["origens"]) + 4 <= len(y)      # horizonte totalmente observado


def test_backtest_naive_errors_by_hand():
    y = np.array([1.0, 3, 2, 5, 4, 6, 8, 7, 9, 12, 10, 11])
    bt = backtest(y, 2, 1, ["naive"], n_origins=3, min_train=8)
    errs = []
    for T in bt["origens"]:
        errs += [y[T - 1] - y[T], y[T - 1] - y[T + 1]]
    assert bt["resultados"]["naive"]["mae"] == pytest.approx(np.mean(np.abs(errs)))


@pytest.mark.parametrize("seed", [11, 12])
def test_interval_calibration_random_walk(seed):
    """Num passeio aleatório o intervalo Naive de 80% deve cobrir ≈80%."""
    rng = np.random.default_rng(seed)
    y = 1000 + np.cumsum(rng.normal(0, 5, 600))
    bt = backtest(y, 1, 1, ["naive"], n_origins=300)
    assert 0.74 <= bt["resultados"]["naive"]["cobertura_80"] <= 0.86


def test_interval_truncated_at_zero():
    lo, hi = interval(np.array([1.0]), np.array([100.0]), 0.95)
    assert lo[0] == 0.0 and hi[0] > 1
