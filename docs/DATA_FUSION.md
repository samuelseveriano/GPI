# Product Intelligence Fusion Engine (PIFE) — GPI v0.8

```
fontes → staging (search_observations, market_obs, content_items, social_observations — dados brutos preservados)
      → Gate 1 (esquema, datas, unidades, duplicatas, proveniência)
      → identificação semântica do produto (intel/matching.py · Gate 2)
      → normalização de métricas (intel/semantics.py · Gate 3)
      → séries e evidências por produto (products/trends.build_series + intel/mlrank.py)
      → validação temporal e de elegibilidade (intel/quality.py · Gate 4)
      → análise estatística (momentum, aceleração, persistência, volatilidade, sazonalidade, mudança de patamar,
        anomalias, reversão, confirmação cruzada)
      → ML (somente séries elegíveis; AutoML com backtesting)
      → interpretação comercial (intel/insights_engine.py · Gate 6)
      → resultado único "intel08" → dashboard, dossiê e relatórios (Gate 8)
```

## Camadas

- **Observado:** valores das fontes, cada um com ID reproduzível:
  - `so:<fonte>|<país>|<data>|<métrica>|<termo>`
  - `ms:<série>@<data>`
- **Derivado:** indicadores calculados, com critério matemático documentado em `PRODUCT_INTELLIGENCE.md`.
- **Previsto:** só séries elegíveis no Gate 4 e com previsão validada por backtesting. Quando não há previsão, o motivo
  é exibido.

## Linhagem

Cada produto traz a consulta que reproduz suas observações e as 40 mais recentes. Cada insight traz os IDs das
observações em que se baseia.

## Índices (separados — nunca combinados num número único)

| Índice | Fontes elegíveis | Cálculo |
|---|---|---|
| Search Interest Index | só SEARCH_INTEREST | 50 + 50·tanh(momentum/0,4), ±10 se a tendência for significativa. Série diária: 100·min(1, dias em alta em 30 dias/10) |
| Commercial Intent Index | só ranking comercial | 100 × persistência × (1 − 0,5·(posição média − 1)/49). Com uma única semana, limitado a 40 |
| Public Attention Index | só PUBLIC_ATTENTION | 50 + 50·tanh(mediana da atenção relativa à coorte/0,4) |
| Evidence Coverage | todos os tipos de demanda | Σ peso × qualidade (pesquisa 35, comercial 30, atenção 15, comércio exterior 10, vendas 10) + 5 com ≥ 2 fontes de demanda |
| Forecast Confidence | séries elegíveis | 100 × (1 − WAPE), ou 30 quando o baseline é o selecionado |
| Opportunity Score | pesquisa, comercial, atenção | média ponderada (0,45/0,35/0,20) dos disponíveis × (0,6 + 0,4 × cobertura). **Sem pesquisa nem sinal comercial: não é calculado** |
| Import Readiness | análises de conformidade | situação regulatória registrada |

Índice ausente aparece como "—" com o motivo. **Ausência de dados não é baixa demanda.** Nenhum score é probabilidade
de sucesso.

## Políticas de fontes

YouTube, TikTok, Instagram, Facebook e Meta Ads não entram em nenhum índice consolidado: são exibidos à parte, conforme
as políticas das plataformas. A Wikipédia nunca confirma demanda. Comex Stat e Comtrade descrevem NCM/SH, não produtos,
e são contexto de importação.
