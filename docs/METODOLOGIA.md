# Metodologia

A documentação completa, com todas as fórmulas renderizadas, está **dentro do programa**
em *Referência → Metodologia e Fórmulas* (arquivo `frontend/methodology.js`).

Mapa fórmula → código:

| Tema | Arquivo / função |
|---|---|
| Construção da série, lacunas, períodos incompletos | `backend/gpi/series.py · build_series` |
| Naive, Naive sazonal, média móvel | `backend/gpi/forecasting/models.py` |
| ETS aditivo (SES, Holt, amortecido, Holt-Winters), AICc | `models.py · ets, ets_auto` |
| Croston-SBA, TSB | `models.py · croston, tsb` |
| Intervalos de previsão | `backend/gpi/forecasting/backtest.py · interval` + `var_h` de cada modelo |
| Backtesting, MAE, RMSE, WAPE, Bias, RMSSE, cobertura, FVA | `backtest.py · backtest, metrics` |
| Theil–Sen, Mann–Kendall, força sazonal | `backend/gpi/analytics/classification.py` |
| ABC, XYZ, Syntetos–Boylan | `classification.py · abc, xyz_class, sbc` |
| Estoque de segurança, ROP, nível-alvo, EOQ | `backend/gpi/supply_chain/inventory.py · plan` |
| Coleta, idempotência, retry/backoff, proveniência | `backend/gpi/market/sync.py`, `connectors/http.py`, `market/store.py` |
| Descoberta, normalização, similaridade, deduplicação | `market/intel.py · discover`, `market/taxonomy.py` |
| Séries derivadas (participação, US$/kg, PTAX mensal) | `market/intel.py · build_derived`, `connectors/public.py · BcbPtax` |
| AutoML, Random Forest / HistGradientBoosting | `market/automl.py`, `forecasting/ml.py` |
| Score de oportunidade, rankings | `market/intel.py · opportunity, rankings` |
| Clusterização e rótulos | `market/intel.py · clusterize, label` |

As verificações numéricas estão em `tests/test_models.py` e `tests/test_data_and_analytics.py`
(ex.: Holt-Winters recupera tendência e sazonalidade exatas; intervalo de 80% do Naive
cobre ≈80% em passeio aleatório simulado; Mann–Kendall tem taxa de falso positivo < 10%
em ruído puro).
