"""Validação estatística dos modelos de previsão (v0.7.1) em séries sintéticas de comportamento conhecido.

Para cada tipo de série: backtesting de origem móvel (4 origens, horizonte 6; o treino usa só y[:T]),
modelos candidatos do AutoML, modelo selecionado, WAPE, MASE/RMSSE, viés, FVA contra o Naive e cobertura do IC 80%.
Uso: python scripts/ml_validation.py docs/ML_VALIDATION_resultados.md
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from gpi.market.automl import auto_forecast  # noqa: E402

rng = np.random.default_rng(2026)
n = 60
SERIES = {
    "Tendência linear": 100 + np.arange(n) * 2.5 + rng.normal(0, 4, n),
    "Sazonal (12 meses)": 200 + 60 * np.sin(np.arange(n) * 2 * np.pi / 12) + rng.normal(0, 6, n),
    "Tendência + sazonalidade": 100 + np.arange(n) * 1.5 + 30 * np.sin(np.arange(n) * 2 * np.pi / 12) + rng.normal(0, 4, n),
    "Estacionária (ruído)": 150 + rng.normal(0, 10, n),
    "Passeio aleatório": 150 + np.cumsum(rng.normal(0, 5, n)),
    "Intermitente": np.where(rng.random(n) < 0.65, 0, rng.integers(1, 8, n)).astype(float),
    "Mudança estrutural": np.r_[np.full(30, 80.0), np.full(30, 140.0)] + rng.normal(0, 4, n),
    "Com anomalias": np.where(np.arange(n) % 13 == 0, 600, 120) + rng.normal(0, 4, n),
    "Curta (9 meses)": 100 + rng.normal(0, 5, 9),
}
rows = ["| Série | Status | Modelo selecionado | Baseline? | WAPE | MASE/RMSSE | Viés | FVA vs Naive | Cobertura IC80 | Candidatos |",
        "|---|---|---|---|---|---|---|---|---|---|"]
for name, y in SERIES.items():
    s = pd.Series(y, index=pd.period_range("2021-01", periods=len(y), freq="M").to_timestamp())
    r = auto_forecast(s, {"source": "validacao"}, horizon=6, allow_ml=True)
    if r["status"] != "prevista":
        rows.append(f"| {name} | {r['status']} | — | — | — | — | — | — | — | {r.get('limitacao', '')[:80]} |")
        continue
    m = r.get("metricas") or {}
    f = lambda v, p=True: "—" if v is None else (f"{v * 100:.1f}%" if p else f"{v:.2f}")   # noqa: E731
    rows.append(f"| {name} | prevista | {r['modelo_nome']} | {'sim' if r['baseline_selecionado'] else 'não'} | {f(m.get('wape'))} | "
                f"{f(m.get('rmsse'), False)} | {f(m.get('bias_pct'))} | {f(m.get('fva_vs_naive'))} | {f(m.get('cobertura_80'))} | "
                f"{', '.join(r['candidatos'])} |")
out = "\n".join(rows)
print(out)
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(out + "\n", encoding="utf-8")
