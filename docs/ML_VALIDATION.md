# GPI v0.7.1 — Validação do Machine Learning

## 1. O que foi auditado
| Item | Resultado da auditoria | Correção |
|---|---|---|
| Dados de entrada | Séries mensais regulares (sem preencher meses inexistentes); séries com < 12 meses ficam como **exploratórias** (sem previsão). | — |
| Backtesting | Origem móvel (4 origens, horizonte 6); cada origem treina só com `y[:T]` — sem vazamento (teste `test_backtest_has_no_future_leakage`). | — |
| Seleção | Menor WAPE entre candidatos; se FVA vs Naive ≤ 0, usa o Naive. | Agora o resultado informa **`baseline_selecionado`** e a limitação "nenhum modelo superou o baseline". |
| Candidatos | Em tendência linear limpa, o Holt **amortecido** subestimava a inclinação e o Naive vencia. | Holt (sem amortecimento) e ETS automático entram na disputa. |
| Intervalos | 80% e 95%. | **90%** acrescentado; os três são aninhados (testado). |
| Intervalos conformais do modelo global | Com calibração pequena, 80/90/95% saíam **idênticos** (todos = erro máximo) — indefensável. | Níveis sem calibração suficiente (⌈(n+1)·nível⌉ > n) ficam **indisponíveis** em vez de inventados. |
| Interesse ≠ vendas | Previsões de buscas/atenção são rotuladas como interesse; nenhuma conversão para unidades vendidas. | Repetido nos Insights e relatórios. |

## 2. Comparação estatística (séries sintéticas de comportamento conhecido)
Gerado por `python scripts/ml_validation.py` (semente fixa 2026). WAPE/MASE(RMSSE)/viés/FVA/cobertura são do backtesting
fora da amostra do modelo selecionado.

| Série | Status | Modelo selecionado | Baseline? | WAPE | MASE/RMSSE | Viés | FVA vs Naive | Cobertura IC80 | Candidatos |
|---|---|---|---|---|---|---|---|---|---|
| Tendência linear | prevista | Holt — ETS(A,A,N) | não | 1.5% | 0.68 | 1.4% | 49.7% | 62.5% | naive, ses, holt, holt_damped, ets_auto, seasonal_naive, random_forest, hist_gb |
| Sazonal (12 meses) | prevista | ETS automático (menor AICc) | não | 3.9% | 0.34 | -0.8% | 88.0% | 79.2% | naive, ses, holt, holt_damped, ets_auto, seasonal_naive, holt_winters, random_forest, hist_gb |
| Tendência + sazonalidade | prevista | ETS automático (menor AICc) | não | 1.9% | 0.29 | 1.0% | 89.0% | 83.3% | naive, ses, holt, holt_damped, ets_auto, seasonal_naive, holt_winters, random_forest, hist_gb |
| Estacionária (ruído) | prevista | Naive | sim | 7.2% | 1.23 | 1.5% | 0.0% | 87.5% | naive, ses, holt, holt_damped, ets_auto, seasonal_naive, random_forest, hist_gb |
| Passeio aleatório | prevista | Suavização exponencial simples — ETS(A,N,N) | não | 4.3% | 2.00 | -3.4% | 0.0% | 75.0% | naive, ses, holt, holt_damped, ets_auto, seasonal_naive, random_forest, hist_gb |
| Intermitente | prevista | Média móvel (k=3) | não | 132.0% | 0.54 | 4.0% | 5.7% | 91.7% | naive, moving_average, croston_sba, tsb |
| Mudança estrutural | prevista | Naive sazonal | não | 2.7% | 0.44 | 2.4% | 41.1% | 100.0% | naive, ses, holt, holt_damped, ets_auto, seasonal_naive, random_forest, hist_gb |
| Com anomalias | prevista | HistGradientBoosting (defasagens) | não | 3.4% | 0.04 | -1.5% | 96.7% | 100.0% | naive, ses, holt, holt_damped, ets_auto, seasonal_naive, random_forest, hist_gb |
| Curta (9 meses) | exploratoria | — | — | — | — | — | — | — | apenas 9 meses contínuos: sem previsão quantitativa; use a tendência como indica |

Leitura: em tendência e sazonalidade os modelos estruturais superam o Naive (FVA 50–89%); em ruído estacionário o
Naive permanece (baseline declarado); no passeio aleatório SES ≈ Naive; em séries intermitentes o WAPE é alto por
natureza (o MASE/RMSSE é a métrica adequada); série de 9 meses não recebe previsão. A cobertura empírica do IC 80% é
exibida — valores abaixo de 65% geram aviso de que a incerteza real é maior.

## 3. Classificação de tendências (Early Trend Detection)
| Situação | Critério |
|---|---|
| EVIDÊNCIA INSUFICIENTE | mensal: < 6 meses ou mediana abaixo da base mínima da métrica; diária: < 28 dias de histórico e < 5 dias em alta |
| EMERGENTE | primeira observação nos últimos 3 meses (30 dias nas diárias) ou alta > 15% sem significância |
| CRESCIMENTO CONSISTENTE | Mann-Kendall significativo (p < 0,05) com inclinação Theil-Sen positiva; em séries sazonais, ≥ 75% das variações ano contra ano positivas e mediana > 5% |
| ACELERAÇÃO | consistente + aceleração (crescimento 3m − crescimento 3m anterior) > 10 p.p. e base suficiente |
| POSSÍVEL SATURAÇÃO | crescimento > 0, aceleração < −10 p.p. e média dos 3 últimos ≥ 90% do máximo |
| DECLÍNIO | queda significativa ou variação < −15% |
| SAZONAL | força sazonal significativa sem tendência |
| ESTÁVEL | demais casos |

Crescimento: 3 meses contra os 3 anteriores, ou ano contra ano quando há ≥ 15 meses; diárias: 30 dias contra os 30
anteriores. Persistência: variações mensais positivas nos últimos 12 meses. Volatilidade: desvio-padrão das variações ÷
média (baixa < 0,2; moderada < 0,5; alta ≥ 0,5). Confiança: 60% confiança estatística da série + 40% número de fontes
com evidência (máx. 3); limitada a "baixa" com evidência insuficiente. Séries pequenas nunca entram em "merecem
investigação".

## 4. Clusterização
K-Means sobre atributos adimensionais padronizados (crescimento limitado a [−1, 3], volatilidade, aceleração, fração de
períodos positivos, sazonalidade) — nunca valores absolutos de unidades diferentes. k ∈ [2, 5] escolhido pelo
silhouette; com < 6 produtos com evidência suficiente, nada é agrupado. Nomes dos grupos derivam dos centróides
(regras na seção `CL_NAMES` de `products/insights.py`); produtos com evidência insuficiente ficam fora. Reprodutível
(semente fixa).

## 5. Lead-lag (comparação internacional)
Correlação cruzada das variações padronizadas, limite de significância e teste de estabilidade em duas metades;
apresentada como **sinal exploratório** — correlação não implica causalidade.
