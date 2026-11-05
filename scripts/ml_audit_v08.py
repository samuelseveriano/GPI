"""Auditoria do Machine Learning (v0.8, seção 11 / Gate 5) em séries SINTÉTICAS de comportamento conhecido.

A. Cada modelo individual × cada tipo de série: backtesting de origem móvel (treino só com y[:T]); WAPE, MASE/RMSSE, viés,
   cobertura do IC 80% e FVA contra o Naive. Mostra onde cada modelo NÃO se aplica.
B. Modelos globais (LightGBM/XGBoost/CatBoost/HistGB em painel) × modelo local, nas mesmas origens — sem presumir
   superioridade dos globais.
C. Clustering: K-Means × Ward × HDBSCAN contra grupos conhecidos (Adjusted Rand Index) e silhouette.
D. Detecção: anomalias (|z robusto| > 3,5) e mudanças de patamar — precisão e recall contra pontos injetados.
Uso: python scripts/ml_audit_v08.py docs/ML_AUDIT_v08_resultados.md
"""
from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from gpi.forecasting import advanced  # noqa: E402
from gpi.forecasting.backtest import backtest  # noqa: E402
from gpi.forecasting.models import MODELS  # noqa: E402
from gpi.products.trends import anomalies, change_points  # noqa: E402

rng = np.random.default_rng(2026)
n = 60
t = np.arange(n)
SERIES = {
    "Tendência": 100 + t * 2.5 + rng.normal(0, 4, n),
    "Sazonal": 200 + 60 * np.sin(t * 2 * np.pi / 12) + rng.normal(0, 6, n),
    "Tend.+sazonal": 100 + t * 1.5 + 30 * np.sin(t * 2 * np.pi / 12) + rng.normal(0, 4, n),
    "Ruído": 150 + rng.normal(0, 10, n),
    "Passeio aleatório": 150 + np.cumsum(rng.normal(0, 5, n)),
    "Intermitente": np.where(rng.random(n) < 0.65, 0, rng.integers(1, 8, n)).astype(float),
    "Mudança estrutural": np.r_[np.full(30, 80.0), np.full(30, 140.0)] + rng.normal(0, 4, n),
    "Anomalias": np.where(t % 13 == 0, 600, 120) + rng.normal(0, 4, n),
}
out = []
f = lambda v, p=True: "—" if v is None or (isinstance(v, float) and not np.isfinite(v)) else (f"{v * 100:.1f}%" if p else f"{v:.2f}")  # noqa: E731

# ------------------------------------------------------------------------------------------------- A
keys = list(MODELS)
out.append("## A. Modelos individuais × tipos de série (WAPE no backtesting; — = não se aplica)\n")
out.append("| Modelo | " + " | ".join(SERIES) + " |")
out.append("|---|" + "---|" * len(SERIES))
best = {}
tA = time.time()
res_by_series = {}
for name, y in SERIES.items():
    bt = backtest(y, 6, 12, keys, n_origins=4)
    res_by_series[name] = bt
for k in keys:
    cells = []
    for name in SERIES:
        r = res_by_series[name]["resultados"].get(k) or {}
        cells.append(f(r.get("wape")) if not r.get("falhou") else "—")
    out.append(f"| {MODELS[k].name if hasattr(MODELS[k], 'name') else k} | " + " | ".join(cells) + " |")
out.append("")
out.append("| Série | Melhor modelo | WAPE | MASE/RMSSE | Viés | Cobertura IC80 | FVA vs Naive |")
out.append("|---|---|---|---|---|---|---|")
for name in SERIES:
    R = {k: v for k, v in res_by_series[name]["resultados"].items() if not v.get("falhou") and v.get("wape") is not None}
    if not R:
        continue
    b = min(R, key=lambda k: R[k]["wape"])
    nv = (R.get("naive") or {}).get("wape")
    fva = (1 - R[b]["wape"] / nv) if nv else None
    out.append(f"| {name} | {b} | {f(R[b]['wape'])} | {f(R[b].get('rmsse') or R[b].get('mase'), False)} | {f(R[b].get('bias_pct'))} | "
               f"{f(R[b].get('cobertura_80'))} | {f(fva)} |")
out.append(f"\nTempo da parte A: {time.time() - tA:.1f} s\n")

# ------------------------------------------------------------------------------------------------- B
out.append("## B. Modelos globais × local (painel de 36 séries relacionadas, 48 meses, horizonte 6, 3 origens)\n")
panel = []
for i in range(36):
    kind = i % 4
    base = rng.uniform(50, 500)
    yy = (base * (1 + rng.uniform(-0.01, 0.03)) ** np.arange(48) * (1 + (0.3 if kind in (1, 3) else 0.05) * np.sin(np.arange(48) * 2 * np.pi / 12))
          * (1 + rng.normal(0, 0.06, 48)))
    if kind == 3:
        yy[24:] *= 1.4
    panel.append({"id": f"s{i}", "y": np.maximum(yy, 1.0), "months": [m % 12 + 1 for m in range(48)],
                  "meta": {"fonte": "sintetica", "pais": "BR", "metrica": "x", "familia": f"f{i % 6}"}})
tB = time.time()
try:
    ev = advanced.evaluate(panel, h=6, origins=3, cfg={})
    out.append("| Modelo | WAPE médio | WAPE mediano | n (série×origem) | Séries em que venceu |")
    out.append("|---|---|---|---|---|")
    for k, v in sorted(ev["resumo"].items(), key=lambda kv: kv[1]["wape_medio"]):
        out.append(f"| {k} | {f(v['wape_medio'])} | {f(v['wape_mediano'])} | {v['n']} | {ev['vitorias_por_serie'].get(k, 0)} |")
    loc = ev["resumo"].get("local", {}).get("wape_medio")
    glob = {k: v["wape_medio"] for k, v in ev["resumo"].items() if k != "local"}
    if loc and glob:
        bk = min(glob, key=glob.get)
        out.append(f"\nConclusão B: melhor global = {bk} ({f(glob[bk])}) × local ({f(loc)}) → "
                   + ("o global foi MELHOR neste painel" if glob[bk] < loc else "o global NÃO superou o local neste painel")
                   + ". O GPI só usa o global por série quando ele vence o local no backtesting dessa série.")
except Exception as e:  # noqa: BLE001
    out.append(f"Modelos globais indisponíveis neste ambiente: {e}")
out.append(f"\nTempo da parte B: {time.time() - tB:.1f} s\n")

# ------------------------------------------------------------------------------------------------- C
from sklearn.cluster import AgglomerativeClustering, KMeans  # noqa: E402
from sklearn.metrics import adjusted_rand_score, silhouette_score  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
centers = np.array([[0.5, 0.1, 0.8, 0.2, 0, 1, 0, 0.7], [0.0, 0.0, 0.5, 0.15, 1, 1, 0, 0.8], [-0.3, -0.1, 0.25, 0.3, 0, 0, 0, 0.6],
                    [0.2, 0.0, 0.5, 1.2, 0, 0, 1, 0.3]])
X, ytrue = [], []
for g, c in enumerate(centers):
    for _ in range(15):
        X.append(c + rng.normal(0, [0.08, 0.05, 0.08, 0.08, 0.1, 0.2, 0.15, 0.08]))
        ytrue.append(g)
Xs = StandardScaler().fit_transform(np.array(X))
out.append("## C. Clustering contra 4 grupos conhecidos (60 produtos sintéticos, 8 atributos adimensionais)\n")
out.append("| Método | ARI | Silhouette |")
out.append("|---|---|---|")
for nm, model in (("K-Means (k=4)", KMeans(4, n_init=10, random_state=0)), ("Hierárquico Ward (k=4)", AgglomerativeClustering(4))):
    lab = model.fit_predict(Xs)
    out.append(f"| {nm} | {adjusted_rand_score(ytrue, lab):.3f} | {silhouette_score(Xs, lab):.3f} |")
try:
    from sklearn.cluster import HDBSCAN
    lab = HDBSCAN(min_cluster_size=6, copy=True).fit_predict(Xs)
    m = lab >= 0
    out.append(f"| HDBSCAN | {adjusted_rand_score(np.array(ytrue)[m], lab[m]):.3f} (ruído: {(~m).sum()}) | "
               f"{silhouette_score(Xs[m], lab[m]):.3f} |")
except Exception as e:  # noqa: BLE001
    out.append(f"| HDBSCAN | indisponível ({e}) | — |")
out.append("")

# ------------------------------------------------------------------------------------------------- D
out.append("## D. Detecção de anomalias e mudanças de patamar (100 séries sintéticas de 48 meses)\n")
tp = fp = fn = 0
cp_tp = cp_fp = cp_fn = 0
for _ in range(100):
    y = 100 + rng.normal(0, 5, 48)
    idx = rng.choice(np.arange(6, 42), 2, replace=False)
    y[idx] *= rng.choice([2.5, 0.3], 2)
    found = set(anomalies(np.log1p(y)))
    tp += len(found & set(idx))
    fp += len(found - set(idx))
    fn += len(set(idx) - found)
    z = 100 + rng.normal(0, 5, 48)
    k = int(rng.integers(12, 36))
    z[k:] += rng.choice([40, -40])
    c = change_points(np.log1p(z))
    hit = any(abs(x - k) <= 2 for x in c)
    cp_tp += hit
    cp_fn += (not hit)
    cp_fp += sum(1 for x in c if abs(x - k) > 2)
out.append("| Detector | Precisão | Recall |")
out.append("|---|---|---|")
out.append(f"| Anomalias (|z robusto| > 3,5) | {tp / max(1, tp + fp):.1%} | {tp / max(1, tp + fn):.1%} |")
out.append(f"| Mudança de patamar (±2 meses) | {cp_tp / max(1, cp_tp + cp_fp):.1%} | {cp_tp / max(1, cp_tp + cp_fn):.1%} |")
txt = "\n".join(out)
print(txt)
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text("# Auditoria do ML — v0.8 (séries sintéticas)\n\n" + txt + "\n", encoding="utf-8")
