"""
Backtesting temporal (origem móvel, janela expansiva) e métricas de erro.

Regra anti-vazamento: em cada origem T_i o modelo (incluindo a otimização de
parâmetros e a escolha da especificação ETS por AICc) vê apenas y[0:T_i].
As métricas são calculadas somente sobre y[T_i : T_i+H], nunca vistos no ajuste.
"""
from __future__ import annotations

import math
import numpy as np
from scipy.stats import norm

from .models import MODELS, ModelNotApplicable, run_model


def interval(fc: np.ndarray, var_h: np.ndarray, level: float, nonneg=True):
    """ŷ ± z_{(1+nível)/2}·√Var(h); limite inferior truncado em 0 (vendas ≥ 0)."""
    z = norm.ppf(0.5 + level / 2)
    sd = np.sqrt(np.maximum(var_h, 0))
    lo, hi = fc - z * sd, fc + z * sd
    if nonneg:
        lo = np.maximum(lo, 0)
    return lo, hi


def metrics(actual, pred, lo80, hi80, scale_denoms):
    """
    actual/pred: matriz (origens × horizonte) com NaN onde não há observação.
    scale_denoms: por origem, média de (y_t − y_{t−1})² no treino (RMSSE).
    """
    e = pred - actual
    mask = ~np.isnan(actual)
    ae = np.abs(e[mask])
    sum_y = np.nansum(np.abs(actual))
    out = {
        "mae": float(ae.mean()),
        "rmse": float(math.sqrt(np.mean(e[mask] ** 2))),
        "wape": float(ae.sum() / sum_y) if sum_y > 0 else None,
        "bias": float(e[mask].mean()),
        "bias_pct": float(e[mask].sum() / np.nansum(actual)) if np.nansum(actual) != 0 else None,
        "cobertura_80": float(np.mean((actual[mask] >= lo80[mask]) & (actual[mask] <= hi80[mask]))),
        "n_erros": int(mask.sum()),
    }
    rs = []
    for i in range(actual.shape[0]):
        mi = mask[i]
        if mi.any() and scale_denoms[i] > 0:
            rs.append(math.sqrt(np.mean(e[i, mi] ** 2) / scale_denoms[i]))
    out["rmsse"] = float(np.mean(rs)) if rs else None
    return out


def backtest(y, h: int, m: int, model_keys=None, n_origins: int = 6,
             min_train: int | None = None):
    y = np.asarray(y, float)
    n = len(y)
    model_keys = model_keys or list(MODELS)
    if min_train is None:
        # Se houver dados, exige 2 ciclos + 2 no treino para que os modelos
        # sazonais participem de TODAS as origens (comparação justa).
        seasonal_min = 2 * m + 2
        if n - h - seasonal_min + 1 >= 3:
            min_train = seasonal_min
        else:
            min_train = max(8, n // 2)
    # Preferimos origens com o horizonte completo observado (T + h ≤ n);
    # se o histórico for curto, aceitamos horizontes parciais.
    last_origin = n - h if n - h >= min_train else n - 1
    first_origin = max(min_train, last_origin - n_origins + 1)
    origins = list(range(first_origin, last_origin + 1))
    if not origins or origins[0] < min_train:
        return {"origens": [], "resultados": {}, "aviso":
                f"histórico insuficiente para backtesting (n={n}, mínimo de treino={min_train})"}

    results = {}
    for key in model_keys:
        A = np.full((len(origins), h), np.nan)
        P = np.full_like(A, np.nan)
        L = np.full_like(A, np.nan)
        U = np.full_like(A, np.nan)
        den = np.zeros(len(origins))
        failed = None
        for i, T in enumerate(origins):
            train = y[:T]
            try:
                r = run_model(key, train, h, m)
            except ModelNotApplicable as ex:
                failed = str(ex)
                break
            test = y[T:T + h]
            A[i, :len(test)] = test
            P[i] = r.forecast
            L[i], U[i] = interval(r.forecast, r.var_h, 0.80)
            d = np.diff(train)
            den[i] = float(np.mean(d ** 2)) if len(d) else 0.0
        if failed:
            results[key] = {"erro": failed}
            continue
        results[key] = metrics(A, P, L, U, den)
    # Valor agregado em relação ao Naive (FVA)
    base = results.get("naive", {}).get("wape")
    for k, v in results.items():
        if "wape" in v and base and v["wape"] is not None:
            v["fva_vs_naive"] = 1 - v["wape"] / base
    return {"origens": [int(o) for o in origins], "resultados": results,
            "min_treino": min_train}


def select_best(bt: dict, criterion: str = "wape"):
    cands = [(v[criterion], k) for k, v in bt["resultados"].items()
             if v.get(criterion) is not None]
    if not cands:
        return None
    return min(cands)[1]
