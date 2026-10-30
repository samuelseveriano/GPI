"""
Classificações de portfólio e testes de tendência.

ABC   — participação acumulada na receita (ou volume, se não houver preço).
XYZ   — coeficiente de variação da demanda por período.
SBC   — Syntetos–Boylan–Croston (2005): ADI × CV² dos tamanhos não nulos.
Tendência — inclinação de Theil–Sen + teste de Mann–Kendall (τ de Kendall).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

ABC_LIMITS = (0.80, 0.95)
XYZ_LIMITS = (0.5, 1.0)
ADI_CUT, CV2_CUT = 1.32, 0.49


def abc(values: pd.Series, limits=ABC_LIMITS) -> pd.DataFrame:
    """values: valor (receita ou volume) por SKU."""
    v = values.sort_values(ascending=False)
    total = v.sum()
    share = v / total if total > 0 else v * 0
    cum = share.cumsum()
    # A classe é definida pela participação acumulada ANTES de incluir o item,
    # garantindo que o item que cruza 80% ainda seja A.
    prev = cum - share
    cls = np.where(prev < limits[0], "A", np.where(prev < limits[1], "B", "C"))
    return pd.DataFrame({"valor": v, "participacao": share, "acumulado": cum, "abc": cls})


def xyz_cv(series: np.ndarray) -> float | None:
    mu = float(np.mean(series))
    if mu <= 0 or len(series) < 2:
        return None
    return float(np.std(series, ddof=1) / mu)


def xyz_class(cv: float | None, limits=XYZ_LIMITS) -> str:
    if cv is None:
        return "—"
    return "X" if cv <= limits[0] else ("Y" if cv <= limits[1] else "Z")


def sbc(series: np.ndarray) -> dict:
    nz = series[series > 0]
    if len(nz) == 0:
        return {"adi": None, "cv2": None, "padrao": "sem demanda"}
    adi = len(series) / len(nz)
    cv2 = float((np.std(nz, ddof=1) / np.mean(nz)) ** 2) if len(nz) > 1 else 0.0
    if adi < ADI_CUT:
        p = "suave" if cv2 < CV2_CUT else "errática"
    else:
        p = "intermitente" if cv2 < CV2_CUT else "irregular (lumpy)"
    return {"adi": float(adi), "cv2": cv2, "padrao": p}


def trend_test(y: np.ndarray, alpha: float = 0.05) -> dict:
    n = len(y)
    if n < 6:
        return {"n": n, "aviso": "mínimo de 6 períodos"}
    t = np.arange(n)
    slope, intercept, lo, hi = stats.theilslopes(y, t, alpha=0.95)
    tau, p = stats.kendalltau(t, y)
    mean = float(np.mean(y))
    sig = bool(p < alpha) if not np.isnan(p) else False
    direction = "estável"
    if sig:
        direction = "crescimento" if slope > 0 else "queda"
    return {"n": n, "inclinacao": float(slope), "ic95": [float(lo), float(hi)],
            "inclinacao_relativa": float(slope / mean) if mean > 0 else None,
            "tau": float(tau) if not np.isnan(tau) else None,
            "p_valor": float(p) if not np.isnan(p) else None,
            "significativa": sig, "direcao": direction}


def seasonality_strength(y: np.ndarray, m: int) -> dict | None:
    """
    F_s = max(0, 1 − Var(R)/Var(S+R)) via decomposição clássica aditiva, e teste de
    Kruskal–Wallis entre as posições do ciclo na série sem tendência.
    Em séries curtas F_s é enviesado para cima; por isso a sazonalidade só é
    declarada quando o teste é significativo (p < 0,05).
    """
    if m < 2 or len(y) < 2 * m:
        return None
    s = pd.Series(y, dtype=float)
    if m % 2 == 0:
        trend = s.rolling(m, center=True).mean().rolling(2).mean().shift(-1)
    else:
        trend = s.rolling(m, center=True).mean()
    detr = s - trend
    pos = pd.Series(np.arange(len(y)) % m)
    seas = detr.groupby(pos).transform("mean")
    seas = seas - detr.groupby(pos).mean().mean()
    rem = detr - seas
    ok = ~rem.isna()
    v_sr = np.var((seas + rem)[ok])
    if v_sr <= 0:
        return None
    fs = float(max(0.0, 1 - np.var(rem[ok]) / v_sr))
    groups = [g.values for _, g in detr[ok].groupby(pos[ok]) if len(g) > 0]
    try:
        p = float(stats.kruskal(*groups).pvalue)
    except ValueError:
        p = None
    return {"fs": fs, "p_valor": p, "significativa": bool(p is not None and p < 0.05),
            "ciclos": len(y) / m}
