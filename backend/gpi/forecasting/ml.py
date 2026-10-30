"""
Modelos de machine learning para séries temporais (scikit-learn, CPU, gratuitos).

Formulação autorregressiva recursiva, em razão ao nível recente (permite que
tendências continuem, o que árvores de decisão não fazem com valores brutos):
  ℓ_t = média(y_{t-1..t-L})
  x_t = [y_{t-1}/ℓ_t − 1, …, y_{t-L}/ℓ_t − 1, sen(2πt/m), cos(2πt/m)]
  alvo r_t = y_t/ℓ_t − 1,   ŷ_t = ℓ_t·(1 + f(x_t))
Previsões de h passos usam as próprias previsões como defasagens (recursivo).

Variância de previsão (aproximada): σ²·h, com σ estimado nos erros um-passo
de um bloco final reservado (20% do treino) — nunca nos resíduos dentro da
amostra, que subestimariam o erro de modelos flexíveis.
"""
from __future__ import annotations

import math

import numpy as np

from .models import ModelNotApplicable, ModelResult

MIN_N = 36


def _lags(m):
    return 12 if m >= 12 else (m if m > 1 else 6)


def _features(hist, t, L, m):
    lag = np.asarray(hist[t - L:t][::-1], float)
    lvl = float(np.mean(lag))
    rel = lag / lvl - 1 if lvl > 0 else np.zeros(L)
    f = list(rel)
    if m > 1:
        f += [math.sin(2 * math.pi * (t % m) / m), math.cos(2 * math.pi * (t % m) / m)]
    return f, lvl


def _design(y, L, m):
    X, T = [], []
    for t in range(L, len(y)):
        f, lvl = _features(y, t, L, m)
        if lvl > 0:
            X.append(f)
            T.append(y[t] / lvl - 1)
    return np.array(X), np.array(T)


def _predict_one(est, hist, L, m):
    f, lvl = _features(hist, len(hist), L, m)
    return lvl * (1 + float(est.predict(np.array([f]))[0])) if lvl > 0 else 0.0


def _fit_predict(make, y, h, m):
    L = _lags(m)
    X, t = _design(y, L, m)
    est = make()
    est.fit(X, t)
    hist = list(y)
    out = []
    for _ in range(h):
        v = max(_predict_one(est, hist, L, m), 0.0)
        out.append(v)
        hist.append(v)
    fitted = np.full(len(y), np.nan)
    idx = [t for t in range(L, len(y)) if np.mean(y[t - L:t]) > 0]
    if idx:
        lv = np.array([np.mean(y[t - L:t]) for t in idx])
        fitted[idx] = lv * (1 + est.predict(X))
    return np.array(out), fitted


def _ml(name, make, y, h, m):
    y = np.asarray(y, float)
    n = len(y)
    if n < MIN_N:
        raise ModelNotApplicable(f"são necessários ao menos {MIN_N} períodos")
    cut = int(n * 0.8)
    L = _lags(m)
    # σ: erros um-passo no bloco reservado (modelo treinado só antes dele)
    Xtr, ttr = _design(y[:cut], L, m)
    if len(ttr) < 12:
        raise ModelNotApplicable("histórico com valores positivos insuficiente")
    est = make()
    est.fit(Xtr, ttr)
    Xv = np.array([_features(y, t, L, m)[0] for t in range(cut, n)])
    lv = np.array([np.mean(y[t - L:t]) for t in range(cut, n)])
    errs = y[cut:] - lv * (1 + est.predict(Xv))
    s2 = float(np.mean(np.square(errs))) if len(errs) else float("nan")
    fc, fitted = _fit_predict(make, y, h, m)
    return ModelResult(name, fc, fitted, s2 * np.arange(1, h + 1), {"defasagens": L, "bloco_validacao": n - cut},
                       s2, interval_method="aproximado")


def random_forest(y, h, m=1, **_):
    from sklearn.ensemble import RandomForestRegressor
    return _ml("random_forest", lambda: RandomForestRegressor(
        n_estimators=100, min_samples_leaf=2, random_state=0, n_jobs=1), y, h, m)


def hist_gb(y, h, m=1, **_):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return _ml("hist_gb", lambda: HistGradientBoostingRegressor(
        max_iter=120, learning_rate=0.08, min_samples_leaf=5, random_state=0), y, h, m)
