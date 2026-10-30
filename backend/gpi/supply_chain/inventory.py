"""
Política de reposição baseada na previsão e no erro medido no backtesting.

Premissas (exibidas na interface):
  * Erros de previsão por período ~ Normal(0, σ_d²), independentes entre períodos.
    σ_d = RMSE do backtesting do modelo escolhido (erro fora da amostra).
  * Nível de serviço = nível de serviço de ciclo (probabilidade de não romper
    o estoque durante um ciclo de reposição), não fill rate.
  * Recomendação é uma sugestão: exige aprovação humana. Nenhuma compra é feita.
"""
from __future__ import annotations

import math
import numpy as np
from scipy.stats import norm

DAYS_PER_PERIOD = {"W": 7.0, "M": 30.4375}


def cumulative_demand(forecast: np.ndarray, periods: float) -> float:
    """Soma da previsão em 'periods' períodos (fração do último período proporcional)."""
    full = int(math.floor(periods))
    frac = periods - full
    f = np.asarray(forecast, float)
    if full + (1 if frac > 0 else 0) > len(f):
        # horizonte maior que a previsão: repete o último valor e sinaliza
        f = np.r_[f, np.full(full + 1 - len(f), f[-1])]
    return float(f[:full].sum() + (f[full] * frac if frac > 0 else 0.0))


def plan(forecast, sigma_d: float, freq: str, lead_time_days: float,
         review_days: float, service_level: float, on_hand: float,
         in_transit: float, moq: float = 0, order_multiple: float = 1,
         lead_time_sd_days: float = 0.0, unit_cost: float | None = None,
         order_cost: float | None = None, holding_rate_year: float | None = None):
    dpp = DAYS_PER_PERIOD[freq]
    L = lead_time_days / dpp
    R = review_days / dpp
    sL = lead_time_sd_days / dpp
    z = float(norm.ppf(service_level))
    f = np.asarray(forecast, float)
    horizon_short = (L + R) > len(f)

    d_mean = float(np.mean(f[:max(1, math.ceil(L + R))]))
    D_L = cumulative_demand(f, L)
    D_LR = cumulative_demand(f, L + R)
    # σ da demanda no tempo de proteção, com variabilidade do lead time:
    # σ_P = √( P·σ_d² + d̄²·σ_L² )
    sigma_L = math.sqrt(L * sigma_d ** 2 + d_mean ** 2 * sL ** 2)
    sigma_LR = math.sqrt((L + R) * sigma_d ** 2 + d_mean ** 2 * sL ** 2)
    ss = z * sigma_L
    ss_lr = z * sigma_LR
    rop = D_L + ss
    S = D_LR + ss_lr
    position = on_hand + in_transit
    q_raw = max(0.0, S - position)
    q = q_raw
    if q > 0:
        mult = max(order_multiple or 1, 1)
        q = math.ceil(q / mult) * mult
        if moq and q < moq:
            q = float(moq)
    out = {
        "z": z, "L_periodos": L, "R_periodos": R, "demanda_media_periodo": d_mean,
        "demanda_lead_time": D_L, "demanda_L_mais_R": D_LR,
        "sigma_d": sigma_d, "sigma_lead_time": sigma_L, "sigma_L_mais_R": sigma_LR,
        "estoque_seguranca": ss, "ponto_reposicao": rop,
        "estoque_seguranca_revisao": ss_lr, "nivel_alvo_S": S,
        "posicao_estoque": position, "deve_pedir_agora": position <= rop,
        "qtd_calculada": q_raw, "qtd_sugerida": q,
        "efeito_moq": bool(q_raw > 0 and moq and q_raw < moq),
        "cobertura_periodos": (position / d_mean) if d_mean > 0 else None,
        "horizonte_insuficiente": horizon_short,
    }
    if unit_cost:
        out["capital_necessario"] = q * unit_cost
    if unit_cost and order_cost and holding_rate_year:
        annual = d_mean * (365.25 / dpp)
        H = holding_rate_year * unit_cost
        out["eoq"] = math.sqrt(2 * annual * order_cost / H) if H > 0 else None
        out["demanda_anual_estimada"] = annual
    return out
