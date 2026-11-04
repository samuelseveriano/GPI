# Auditoria do ML — v0.8 (séries sintéticas)

## A. Modelos individuais × tipos de série (WAPE no backtesting; — = não se aplica)

| Modelo | Tendência | Sazonal | Tend.+sazonal | Ruído | Passeio aleatório | Intermitente | Mudança estrutural | Anomalias |
|---|---|---|---|---|---|---|---|---|
| naive | 3.1% | 32.3% | 16.8% | 7.2% | 4.3% | 140.0% | 4.6% | 104.0% |
| seasonal_naive | 12.1% | 4.4% | 8.2% | 9.9% | 7.3% | 136.0% | 2.7% | 39.4% |
| moving_average | 3.1% | 32.7% | 16.6% | 7.4% | 3.9% | 132.0% | 3.4% | 78.7% |
| ses | 3.1% | 32.3% | 16.8% | 8.0% | 4.3% | 161.3% | 4.1% | 47.7% |
| holt | 1.5% | 35.1% | 22.0% | 9.6% | 4.4% | 168.4% | 6.0% | 41.4% |
| holt_damped | 3.6% | 31.1% | 19.7% | 8.1% | 4.3% | 168.6% | 4.1% | 41.2% |
| holt_winters | 1.4% | 3.9% | 1.9% | 10.4% | 4.3% | 138.3% | 10.4% | 36.0% |
| ets_auto | 1.5% | 3.9% | 1.9% | 8.0% | 4.3% | 161.3% | 4.1% | 47.7% |
| croston_sba | 15.0% | 18.9% | 10.1% | 9.9% | 10.1% | 147.4% | 10.0% | 58.0% |
| tsb | 4.3% | 26.9% | 13.1% | 7.4% | 3.7% | 159.3% | 2.5% | 66.5% |
| random_forest | 4.7% | 4.0% | 4.0% | 7.9% | 5.4% | 209.1% | 2.8% | 105.6% |
| hist_gb | 4.4% | 4.8% | 4.3% | 7.7% | 5.9% | 302.0% | 3.1% | 3.4% |

| Série | Melhor modelo | WAPE | MASE/RMSSE | Viés | Cobertura IC80 | FVA vs Naive |
|---|---|---|---|---|---|---|
| Tendência | holt_winters | 1.4% | 0.60 | 1.2% | 95.8% | 54.0% |
| Sazonal | ets_auto | 3.9% | 0.34 | -0.8% | 79.2% | 88.0% |
| Tend.+sazonal | holt_winters | 1.9% | 0.29 | 1.0% | 83.3% | 89.0% |
| Ruído | naive | 7.2% | 1.23 | 1.5% | 87.5% | 0.0% |
| Passeio aleatório | tsb | 3.7% | 1.81 | -3.1% | 75.0% | 14.4% |
| Intermitente | moving_average | 132.0% | 0.54 | 4.0% | 91.7% | 5.7% |
| Mudança estrutural | tsb | 2.5% | 0.40 | 0.2% | 100.0% | 45.2% |
| Anomalias | hist_gb | 3.4% | 0.04 | -1.5% | 100.0% | 96.7% |

Tempo da parte A: 27.6 s

## B. Modelos globais × local (painel de 36 séries relacionadas, 48 meses, horizonte 6, 3 origens)

| Modelo | WAPE médio | WAPE mediano | n (série×origem) | Séries em que venceu |
|---|---|---|---|---|
| hist_gb_global | 9.5% | 6.8% | 108 | 23 |
| local | 14.2% | 7.3% | 108 | 13 |

Conclusão B: melhor global = hist_gb_global (9.5%) × local (14.2%) → o global foi MELHOR neste painel. O GPI só usa o global por série quando ele vence o local no backtesting dessa série.

Tempo da parte B: 55.0 s

## C. Clustering contra 4 grupos conhecidos (60 produtos sintéticos, 8 atributos adimensionais)

| Método | ARI | Silhouette |
|---|---|---|
| K-Means (k=4) | 1.000 | 0.625 |
| Hierárquico Ward (k=4) | 1.000 | 0.625 |
| HDBSCAN | 1.000 (ruído: 0) | 0.625 |

## D. Detecção de anomalias e mudanças de patamar (100 séries sintéticas de 48 meses)

| Detector | Precisão | Recall |
|---|---|---|
| Anomalias (|z robusto| > 3,5) | 69.9% | 100.0% |
| Mudança de patamar (±2 meses) | 77.5% | 100.0% |
