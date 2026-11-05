"""v0.9 — análises temporais novas com taxa de falsos positivos medida por simulação (dados SINTÉTICOS, só para
validar o método — nunca apresentados como mercado)."""
from __future__ import annotations

import numpy as np

from gpi.intel.mlrank import term_stats
from gpi.products.trends import pettitt, robust_acceleration


def test_pettitt_false_positive_rate_and_power():
    rng = np.random.default_rng(42)
    fpr = np.mean([pettitt(100 + rng.normal(0, 10, 36))["significativa"] for _ in range(1000)])
    power = np.mean([pettitt(np.r_[100 + rng.normal(0, 10, 18), 130 + rng.normal(0, 10, 18)])["significativa"] for _ in range(300)])
    assert fpr <= 0.06 and power >= 0.9
    assert pettitt(np.ones(12)) is None                               # série curta: não testa


def test_acceleration_needs_real_change_not_linear_growth():
    rng = np.random.default_rng(7)
    noise = np.mean([robust_acceleration(100 + rng.normal(0, 10, 36))["classe"] != "sem mudança detectada" for _ in range(1000)])
    lin = np.mean([robust_acceleration(100 + np.arange(36) * 2 + rng.normal(0, 3, 36))["classe"] == "acelerando" for _ in range(300)])
    real = np.mean([robust_acceleration(np.r_[100 + rng.normal(0, 3, 24), 100 + np.arange(12) * 6 + rng.normal(0, 3, 12)])["classe"]
                    == "acelerando" for _ in range(300)])
    assert noise <= 0.06 and lin <= 0.05 and real >= 0.9
    assert robust_acceleration(np.ones(20)) is None


def test_one_week_of_ranking_is_not_sustained_growth():
    r = term_stats({"2026-W44": 3}, ["2026-W44"])
    assert r["classe"] == "NOVO SINAL COMERCIAL" and r["crescimento"].startswith("não comprovado")
    assert r["permanencia_max_semanas"] == 1
