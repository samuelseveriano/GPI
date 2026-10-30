"""
Modelos de previsão implementados de forma explícita (sem caixa-preta).

Cada função recebe uma série y (numpy, ordem cronológica, sem lacunas) e devolve
um ModelResult com:
  - forecast[h]  : previsão pontual para T+1..T+H
  - fitted[t]    : previsão um-passo-à-frente dentro da amostra (NaN onde indefinida)
  - var_h[h]     : variância do erro de previsão em h passos (para intervalos)
  - params       : parâmetros estimados
  - formula      : identificador da fórmula documentada na página Metodologia

As fórmulas estão em docs/METODOLOGIA.md e na página "Metodologia" da interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
import numpy as np
from scipy.optimize import minimize


class ModelNotApplicable(Exception):
    """O modelo não pode ser ajustado a esta série (ex.: histórico curto)."""


@dataclass
class ModelResult:
    name: str
    forecast: np.ndarray
    fitted: np.ndarray
    var_h: np.ndarray
    params: dict = field(default_factory=dict)
    sigma2: float = float("nan")
    aicc: float | None = None
    n_params: int = 0
    interval_method: str = "analitico"


def _sigma2(resid: np.ndarray, n_params: int) -> float:
    r = resid[~np.isnan(resid)]
    dof = max(len(r) - n_params, 1)
    return float(np.sum(r ** 2) / dof)


# --------------------------------------------------------------------------- #
# Referências simples
# --------------------------------------------------------------------------- #
def naive(y: np.ndarray, h: int, **_) -> ModelResult:
    """ŷ(T+h) = y(T).  Passeio aleatório: Var(h) = h·σ²."""
    if len(y) < 2:
        raise ModelNotApplicable("são necessários ao menos 2 períodos")
    fitted = np.r_[np.nan, y[:-1]]
    s2 = _sigma2(y - fitted, 0)
    return ModelResult("naive", np.full(h, y[-1]), fitted,
                       s2 * np.arange(1, h + 1), {}, s2)


def seasonal_naive(y: np.ndarray, h: int, m: int, **_) -> ModelResult:
    """ŷ(T+h) = y(T + h − m·(⌊(h−1)/m⌋+1)).  Var(h) = σ²·(⌊(h−1)/m⌋+1)."""
    if m < 2:
        raise ModelNotApplicable("frequência sem sazonalidade definida")
    if len(y) < m + 1:
        raise ModelNotApplicable(f"são necessários ao menos {m + 1} períodos")
    T = len(y)
    fitted = np.r_[np.full(m, np.nan), y[:-m]]
    s2 = _sigma2(y - fitted, 0)
    k = (np.arange(1, h + 1) - 1) // m + 1
    idx = T + np.arange(1, h + 1) - m * k  # posição 1-based → 0-based
    fc = y[idx - 1]
    return ModelResult("seasonal_naive", fc, fitted, s2 * k, {"m": m}, s2)


def moving_average(y: np.ndarray, h: int, k: int = 3, **_) -> ModelResult:
    """ŷ(T+h) = (1/k)·Σ_{i=0}^{k−1} y(T−i).  Var(h) ≈ σ²·(1 + 1/k) (nível constante)."""
    if len(y) < k + 2:
        raise ModelNotApplicable(f"são necessários ao menos {k + 2} períodos")
    c = np.convolve(y, np.ones(k) / k, mode="valid")  # c[j] = média de y[j..j+k-1]
    fitted = np.r_[np.full(k, np.nan), c[:-1]]
    s2 = _sigma2(y - fitted, 0)
    return ModelResult("moving_average", np.full(h, c[-1]), fitted,
                       np.full(h, s2 * (1 + 1 / k)), {"k": k}, s2,
                       interval_method="aproximado")


# --------------------------------------------------------------------------- #
# ETS aditivo (forma de correção de erros) — Hyndman et al. (2008), classe 1
# --------------------------------------------------------------------------- #
ETS_SPECS = {
    # código: (tendência, amortecida, sazonal)
    "ANN": (False, False, False),   # suavização exponencial simples
    "AAN": (True, False, False),    # Holt linear
    "AAdN": (True, True, False),    # Holt amortecido
    "ANA": (False, False, True),    # nível + sazonalidade aditiva
    "AAA": (True, False, True),     # Holt-Winters aditivo
    "AAdA": (True, True, True),     # Holt-Winters aditivo amortecido
}


def _ets_initial(y: np.ndarray, trend: bool, m: int, seasonal: bool):
    """Inicialização heurística clássica (Hyndman et al., 2008, §2.6.1)."""
    if seasonal:
        # Regressão linear nos primeiros ciclos completos (até 3) remove a
        # tendência; a média dos resíduos por posição do ciclo dá os sazonais.
        k = min(len(y) // m, 3) * m
        t = np.arange(k)
        b, a = np.polyfit(t, y[:k], 1)
        resid = y[:k] - (a + b * t)
        s0 = resid.reshape(-1, m).mean(axis=0)
        s0 = s0 - s0.mean()  # restrição Σ s = 0
        l0 = float(a - b) if trend else float(y[:k].mean())
        b0 = float(b) if trend else 0.0
    else:
        l0 = float(y[0])
        b0 = float(y[1] - y[0]) if (trend and len(y) > 1) else 0.0
        s0 = np.zeros(0)
    return l0, b0, s0


def _ets_filter(y, alpha, beta, gamma, phi, l0, b0, s0, trend, seasonal, m):
    n = len(y)
    fitted = np.empty(n)
    l, b = l0, b0
    s = list(s0)  # s[-m] é o estado sazonal do mesmo período do ciclo anterior
    for t in range(n):
        st = s[-m] if seasonal else 0.0
        bt = phi * b if trend else 0.0
        yhat = l + bt + st
        fitted[t] = yhat
        e = y[t] - yhat
        l = l + bt + alpha * e
        if trend:
            b = bt + beta * e
        if seasonal:
            s.append(st + gamma * e)
    return fitted, l, b, np.array(s[-m:]) if seasonal else np.zeros(0)


def _ets_params_from_theta(theta, trend, damped, seasonal):
    # Reparametrização garante 0<α<1, 0<β<α, 0<γ<1−α, 0.8≤φ≤0.98
    i = 0
    alpha = theta[i]; i += 1
    beta = gamma = 0.0
    phi = 1.0
    if trend:
        beta = alpha * theta[i]; i += 1
    if seasonal:
        gamma = (1 - alpha) * theta[i]; i += 1
    if damped:
        phi = theta[i]; i += 1
    return alpha, beta, gamma, phi


def ets(y: np.ndarray, h: int, spec: str = "ANN", m: int = 1, **_) -> ModelResult:
    trend, damped, seasonal = ETS_SPECS[spec]
    n = len(y)
    if seasonal and m < 2:
        raise ModelNotApplicable("frequência sem sazonalidade definida")
    min_n = 2 * m + 2 if seasonal else (4 if trend else 3)
    if n < min_n:
        raise ModelNotApplicable(f"são necessários ao menos {min_n} períodos")

    l0, b0, s0 = _ets_initial(y, trend, m, seasonal)
    x0 = [0.3]; bounds = [(1e-4, 0.9999)]
    if trend:
        x0.append(0.1); bounds.append((1e-4, 0.9999))
    if seasonal:
        x0.append(0.1); bounds.append((1e-4, 0.9999))
    if damped:
        x0.append(0.95); bounds.append((0.8, 0.98))
    # nível e tendência iniciais também são otimizados
    scale = max(float(np.std(y)), 1e-6)
    x0 += [l0] + ([b0] if trend else [])
    bounds += [(None, None)] + ([(None, None)] if trend else [])
    n_smooth = 1 + trend + seasonal + damped
    # Estados sazonais iniciais otimizados quando m ≤ 13 (mensal/trimestral);
    # para m maior (semanal, m=52) mantém-se a inicialização heurística.
    opt_seas = seasonal and m <= 13
    i_seas = n_smooth + 1 + int(trend)
    if opt_seas:
        x0 += list(s0[:-1]); bounds += [(None, None)] * (m - 1)

    def unpack(theta):
        a, b, g, p = _ets_params_from_theta(theta, trend, damped, seasonal)
        L0 = theta[n_smooth]
        B0 = theta[n_smooth + 1] if trend else 0.0
        if opt_seas:
            free = np.asarray(theta[i_seas:i_seas + m - 1])
            S0 = np.r_[free, -free.sum()]       # Σ s = 0
        else:
            S0 = s0
        return a, b, g, p, L0, B0, S0

    def sse(theta):
        a, b, g, p, L0, B0, S0 = unpack(theta)
        f, *_ = _ets_filter(y, a, b, g, p, L0, B0, S0, trend, seasonal, m)
        return float(np.sum((y - f) ** 2)) / scale ** 2

    res = minimize(sse, np.array(x0, float), method="L-BFGS-B", bounds=bounds)
    alpha, beta, gamma, phi, L0, B0, S0 = unpack(res.x)
    fitted, lT, bT, sT = _ets_filter(y, alpha, beta, gamma, phi, L0, B0, S0,
                                     trend, seasonal, m)
    resid = y - fitted
    # p = parâmetros de suavização + estados iniciais (ℓ0, b0, m−1 sazonais) + σ
    p = n_smooth + 1 + int(trend) + (m - 1 if seasonal else 0) + 1
    SSE = float(np.sum(resid ** 2))
    s2 = SSE / max(n - (p - 1), 1)
    aicc = (n * math.log(max(SSE, 1e-12) / n) + 2 * p +
            (2 * p * (p + 1) / (n - p - 1) if n - p - 1 > 0 else math.inf))

    hs = np.arange(1, h + 1)
    if trend:
        phi_sum = np.cumsum(phi ** hs)  # φ + φ² + … + φ^h
        fc = lT + phi_sum * bT
    else:
        fc = np.full(h, lT)
    if seasonal:
        k = (hs - 1) // m
        fc = fc + sT[(hs - 1) - m * k]  # sT[0] é o estado do período T−m+1
    # Variância analítica (classe 1): Var(h) = σ²[1 + Σ_{j=1}^{h−1} c_j²]
    var_h = np.empty(h)
    acc = 0.0
    for i, hh in enumerate(hs):
        var_h[i] = s2 * (1 + acc)
        j = hh  # c_j para o próximo passo
        cj = alpha
        if trend:
            cj += beta * (np.sum(phi ** np.arange(1, j + 1)))
        if seasonal and j % m == 0:
            cj += gamma
        acc += cj ** 2
    params = {"alpha": float(alpha), "beta": float(beta), "gamma": float(gamma),
              "phi": float(phi), "l0": float(L0), "b0": float(B0), "spec": spec,
              "m": m if seasonal else 1, "convergiu": bool(res.success)}
    return ModelResult(f"ets_{spec}", fc, fitted, var_h, params, s2, aicc, p)


def ets_auto(y: np.ndarray, h: int, m: int = 1, **_) -> ModelResult:
    """Escolhe a especificação ETS de menor AICc (somente dados de treino)."""
    best, tried = None, {}
    for spec, (_, _, seas) in ETS_SPECS.items():
        if seas and (m < 2 or len(y) < 2 * m + 2):
            continue
        try:
            r = ets(y, h, spec, m)
        except ModelNotApplicable:
            continue
        tried[spec] = r.aicc
        if best is None or r.aicc < best.aicc:
            best = r
    if best is None:
        raise ModelNotApplicable("histórico insuficiente para qualquer ETS")
    best.params["aicc_candidatos"] = {k: round(v, 2) for k, v in tried.items()}
    best.name = "ets_auto"
    return best


# --------------------------------------------------------------------------- #
# Demanda intermitente
# --------------------------------------------------------------------------- #
_GRID = (0.05, 0.1, 0.15, 0.2, 0.3)


def _croston_run(y, alpha, sba):
    nz = np.flatnonzero(y > 0)
    if len(nz) < 2:
        raise ModelNotApplicable("são necessárias ao menos 2 ocorrências de demanda")
    z, p = float(y[nz[0]]), float(nz[0] + 1)
    q = 1
    fitted = np.full(len(y), np.nan)
    factor = (1 - alpha / 2) if sba else 1.0
    for t in range(nz[0] + 1, len(y)):
        fitted[t] = factor * z / p
        if y[t] > 0:
            z += alpha * (y[t] - z)
            p += alpha * (q - p)
            q = 1
        else:
            q += 1
    return fitted, factor * z / p


def croston(y: np.ndarray, h: int, sba: bool = True, **_) -> ModelResult:
    """Croston (1972) com correção de Syntetos–Boylan (SBA) por padrão."""
    best = None
    for a in _GRID:
        fitted, f = _croston_run(y, a, sba)
        mse = np.nanmean((y - fitted) ** 2)
        if best is None or mse < best[0]:
            best = (mse, a, fitted, f)
    _, a, fitted, f = best
    s2 = _sigma2(y - fitted, 1)
    return ModelResult("croston_sba" if sba else "croston", np.full(h, f), fitted,
                       np.full(h, s2), {"alpha": a, "sba": sba}, s2,
                       interval_method="aproximado")


def tsb(y: np.ndarray, h: int, **_) -> ModelResult:
    """Teunter–Syntetos–Babai (2011): probabilidade atualizada todo período."""
    nz = np.flatnonzero(y > 0)
    if len(nz) < 2:
        raise ModelNotApplicable("são necessárias ao menos 2 ocorrências de demanda")
    best = None
    for a in _GRID:
        for b in _GRID:
            z, d = float(y[nz[0]]), len(nz) / len(y)
            fitted = np.full(len(y), np.nan)
            for t in range(nz[0] + 1, len(y)):
                fitted[t] = d * z
                occ = 1.0 if y[t] > 0 else 0.0
                d += b * (occ - d)
                if occ:
                    z += a * (y[t] - z)
            mse = np.nanmean((y - fitted) ** 2)
            if best is None or mse < best[0]:
                best = (mse, a, b, fitted, d * z)
    _, a, b, fitted, f = best
    s2 = _sigma2(y - fitted, 2)
    return ModelResult("tsb", np.full(h, f), fitted, np.full(h, s2),
                       {"alpha": a, "beta": b}, s2, interval_method="aproximado")


MODELS = {
    "naive": ("Naive", naive),
    "seasonal_naive": ("Naive sazonal", seasonal_naive),
    "moving_average": ("Média móvel (k=3)", moving_average),
    "ses": ("Suavização exponencial simples — ETS(A,N,N)",
            lambda y, h, **kw: ets(y, h, "ANN", kw.get("m", 1))),
    "holt": ("Holt — ETS(A,A,N)", lambda y, h, **kw: ets(y, h, "AAN", kw.get("m", 1))),
    "holt_damped": ("Holt amortecido — ETS(A,Ad,N)",
                    lambda y, h, **kw: ets(y, h, "AAdN", kw.get("m", 1))),
    "holt_winters": ("Holt-Winters aditivo — ETS(A,A,A)",
                     lambda y, h, **kw: ets(y, h, "AAA", kw.get("m", 1))),
    "ets_auto": ("ETS automático (menor AICc)", ets_auto),
    "croston_sba": ("Croston-SBA (intermitente)", croston),
    "tsb": ("TSB (intermitente)", tsb),
    # Machine learning (Fase 2) — importação tardia evita dependência circular
    "random_forest": ("Random Forest (defasagens)",
                      lambda y, h, **kw: __import__("gpi.forecasting.ml", fromlist=["x"]).random_forest(y, h, kw.get("m", 1))),
    "hist_gb": ("HistGradientBoosting (defasagens)",
                lambda y, h, **kw: __import__("gpi.forecasting.ml", fromlist=["x"]).hist_gb(y, h, kw.get("m", 1))),
}


def run_model(key: str, y: np.ndarray, h: int, m: int) -> ModelResult:
    if key not in MODELS:
        raise KeyError(key)
    y = np.asarray(y, dtype=float)
    if np.any(np.isnan(y)):
        raise ModelNotApplicable("a série contém valores ausentes")
    try:
        r = MODELS[key][1](y, h, m=m)
    except ModelNotApplicable:
        raise
    except Exception as e:  # noqa: BLE001 — falha de um modelo não derruba a previsão dos demais
        logging.getLogger("gpi.models").exception("modelo %s falhou (n=%d, h=%d, m=%d)", key, len(y), h, m)
        raise ModelNotApplicable(f"falha interna do modelo ({type(e).__name__}: {e})") from e
    f = np.asarray(r.forecast, dtype=float)
    if f.shape != (h,) or not np.all(np.isfinite(f)):
        logging.getLogger("gpi.models").warning("modelo %s gerou previsão inválida: %s", key, f)
        raise ModelNotApplicable("o modelo gerou previsão inválida (valores não finitos)")
    return r


# Modelos opcionais (Fase 3): SARIMA, LightGBM e XGBoost — registrados só se instalados
from . import extra_models as _extra  # noqa: E402

EXTRA_AVAILABLE = _extra.register(MODELS)
