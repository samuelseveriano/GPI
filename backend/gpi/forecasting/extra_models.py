"""
Modelos opcionais (Fase 3): SARIMA (statsmodels), LightGBM e XGBoost.

São registrados somente se a biblioteca estiver instalada (o build do Windows as inclui;
o GPI funciona sem elas). Rodam em CPU com 1 thread.

SARIMA(p,d,q)(P,D,Q)_m: busca pequena em p,q,P,Q ∈ {0,1}, d ∈ {0,1}, D ∈ {0,1} (D=1 só com ≥ 3 ciclos),
escolhendo o menor AICc. Intervalos: variância de previsão do próprio modelo de espaço de estados.
LightGBM/XGBoost: mesma formulação em razão ao nível recente dos modelos de árvores da Fase 2.
"""
from __future__ import annotations

import itertools
import warnings

import numpy as np

from .models import ModelNotApplicable, ModelResult


def available() -> dict:
    out = {}
    for name, mod in (("sarima", "statsmodels"), ("lightgbm", "lightgbm"), ("xgboost", "xgboost")):
        try:
            __import__(mod)
            out[name] = True
        except ImportError:
            out[name] = False
    return out


def sarima(y, h, m=12, **_):
    try:
        from statsmodels.tsa.statespace.sarimax import SARIMAX
    except ImportError as e:
        raise ModelNotApplicable("statsmodels não instalado") from e
    y = np.asarray(y, float)
    n = len(y)
    if n < max(24, 2 * m):
        raise ModelNotApplicable(f"são necessários ao menos {max(24, 2 * m)} períodos")
    best = None
    seasonal = m > 1 and n >= 2 * m
    grid = itertools.product((0, 1), (0, 1), (0, 1), (0, 1) if seasonal else (0,), (0, 1) if seasonal else (0,),
                             (0, 1) if seasonal and n >= 3 * m else (0,))
    for p, d, q, P, Q, D in grid:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                mod = SARIMAX(y, order=(p, d, q), seasonal_order=(P, D, Q, m) if seasonal else (0, 0, 0, 0),
                              trend="c" if d + D == 0 else "n", enforce_stationarity=False, enforce_invertibility=False)
                res = mod.fit(disp=False, maxiter=200)
            k = p + q + P + Q + 2
            aicc = res.aic + 2 * k * (k + 1) / max(n - k - 1, 1)
            if np.isfinite(aicc) and (best is None or aicc < best[0]):
                best = (aicc, (p, d, q), (P, D, Q), res)
        except Exception:  # noqa: BLE001 — combinações que não convergem são descartadas
            continue
    if best is None:
        raise ModelNotApplicable("nenhuma especificação SARIMA convergiu")
    aicc, order, sorder, res = best
    fc = res.get_forecast(h)
    var = np.asarray(fc.var_pred_mean, float)
    fitted = np.asarray(res.fittedvalues, float)
    resid = y - fitted
    s2 = float(np.nanmean(resid[max(order[1], sorder[1] * m):] ** 2))
    return ModelResult("sarima", np.asarray(fc.predicted_mean, float), fitted, var,
                       {"ordem": str(order), "ordem_sazonal": str(sorder), "m": m}, s2, float(aicc), len(order) + len(sorder))


def lightgbm_model(y, h, m=12, **_):
    try:
        import lightgbm as lgb
    except ImportError as e:
        raise ModelNotApplicable("lightgbm não instalado") from e
    from .ml import _ml
    return _ml("lightgbm", lambda: lgb.LGBMRegressor(n_estimators=150, learning_rate=0.05, num_leaves=15,
                                                     min_child_samples=5, n_jobs=1, verbose=-1, random_state=0), y, h, m)


def xgboost_model(y, h, m=12, **_):
    try:
        import xgboost as xgb
    except ImportError as e:
        raise ModelNotApplicable("xgboost não instalado") from e
    from .ml import _ml
    return _ml("xgboost", lambda: xgb.XGBRegressor(n_estimators=150, learning_rate=0.05, max_depth=4, n_jobs=1,
                                                   random_state=0, verbosity=0), y, h, m)


def register(models: dict):
    av = available()
    if av["sarima"]:
        models["sarima"] = ("SARIMA (busca automática, menor AICc)", lambda y, h, **kw: sarima(y, h, kw.get("m", 12)))
    if av["lightgbm"]:
        models["lightgbm"] = ("LightGBM (defasagens)", lambda y, h, **kw: lightgbm_model(y, h, kw.get("m", 12)))
    if av["xgboost"]:
        models["xgboost"] = ("XGBoost (defasagens)", lambda y, h, **kw: xgboost_model(y, h, kw.get("m", 12)))
    return av
