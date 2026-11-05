# Inteligência de produtos — GPI v0.8

## Identificação canônica

A hierarquia é Categoria → Família → Produto → Variante. Variantes técnicas (20 W, 65 W, 140 W; 10.000 mAh e
20.000 mAh…) nunca são tratadas como o mesmo modelo.

Os idiomas reconhecidos são pt, en e zh (léxico conceitual) e es (tradução de termos de produto para a mesma chave).
Os atributos extraídos do texto são: marca, modelo, potência, tensão, capacidade, armazenamento, volume, tela,
resolução, conector, tecnologia e compatibilidade.

Na v0.8, a família "Móveis e escritório" (cadeira e mesa) foi incluída no léxico. "Cadeira gamer", termo típico do
ranking do Mercado Livre, antes não era reconhecida.

## Mercado Livre (posição, nunca volume)

O histórico é reduzido a uma observação por semana ISO por termo (a melhor posição da semana), para não duplicar
coletas feitas na mesma semana. Indicadores: semanas coletadas, semanas presente, persistência (frequência no Top 50),
melhor posição, posição média, última posição, variação de posição, entradas, saídas, reaparecimentos e estabilidade.

| Classe | Critério |
|---|---|
| NOVO SINAL COMERCIAL | 1 semana presente. Nunca é crescimento sustentado |
| SINAL EM OBSERVAÇÃO | 2–3 semanas presente |
| INTERESSE RECORRENTE | ≥ 4 semanas e persistência ≥ 50% |
| SINAL INTERMITENTE | ≥ 4 semanas e persistência < 50% |

## Indicadores (critérios matemáticos)

| Indicador | Critério |
|---|---|
| Momentum | média dos 3 últimos meses ÷ média dos 3 anteriores − 1. Com ≥ 15 meses, ano contra ano (mesmo trimestre). Só para métricas em que a variação percentual faz sentido |
| Aceleração | momentum atual − momentum anterior (p.p.). Exige ≥ 9 meses |
| Persistência | fração de variações mensais positivas nos últimos 12 meses (ano contra ano quando a série é sazonal) |
| Volatilidade | desvio-padrão das variações ÷ média dos valores > 0 |
| Sazonalidade | força e teste com ≥ 24 meses |
| Mudança de patamar | segmentação binária com penalidade 2·ln(n)·σ̂² sobre log(1 + y) |
| Anomalia | \|z robusto\| > 3,5 em relação à mediana móvel. **Uma anomalia não é tratada como demanda** |
| Reversão | inclinação Theil-Sen dos 6 últimos meses com sinal oposto à dos 6 anteriores, ambas com \|·\| ≥ 2%/mês |
| Atenção relativa (Wikipédia) | (1 + g) ÷ (1 + mediana dos artigos do idioma) − 1. Remove o fator comum (queda geral do tráfego) |
| Confirmação cruzada | ≥ 2 fontes independentes de demanda (pesquisa ou ranking) com sinal positivo. Wikipédia e notícias não contam |

Denominadores: não há crescimento percentual com base nula ou abaixo do nível mínimo da métrica (por exemplo, 100
buscas/mês no Google Ads ou 300 leituras/mês na Wikipédia).

## Situações

| Situação | Critério |
|---|---|
| NOVO SINAL COMERCIAL | primeira presença num ranking comercial (1 semana). Não é crescimento sustentado |
| EMERGENTE | primeira observação recente numa fonte de pesquisa (≤ 3 meses) |
| SINAL EM OBSERVAÇÃO | alta > 15% sem significância estatística, ou 2–3 semanas em ranking |
| INTERESSE RECORRENTE | no ranking em ≥ 4 semanas e em ≥ 50% das semanas coletadas |
| SINAL INTERMITENTE | no ranking em ≥ 4 semanas, mas em < 50% das semanas coletadas |
| CRESCIMENTO CONSISTENTE | tendência de alta significativa (Mann-Kendall/Theil-Sen; ano contra ano em série sazonal) com base suficiente |
| ACELERAÇÃO | crescimento consistente com aceleração > 10 p.p. |
| ESTÁVEL | evidência suficiente, sem tendência significativa |
| SAZONAL | sazonalidade significativa, sem tendência |
| POSSÍVEL SATURAÇÃO | crescimento com desaceleração > 10 p.p. e nível perto do máximo histórico |
| VARIAÇÃO NÃO CONFIRMADA | queda > 15% sem significância nem persistência. **Não é declínio** |
| DECLÍNIO | queda significativa, ou queda > 15% com base suficiente e persistência ≤ 40% |
| ATENÇÃO PÚBLICA EM ALTA | leituras/notícias acima da mediana dos demais produtos, sem evidência de pesquisa ou compra |
| EVIDÊNCIA INSUFICIENTE | sem série elegível de pesquisa nem sinal comercial |

**Investigar:** prioridade ≥ 55, cobertura ≥ 40, situação de crescimento ou interesse recorrente e correspondência
confirmada. Os demais casos ficam **em observação**, com o motivo.

## Insights (GPI Insights Engine)

O texto é gerado por regras determinísticas a partir dos números calculados. Cada insight tem 11 campos: produto,
mercado, indicador, fonte, período, evidência, método, interpretação, confiança, limitações e próxima investigação. Ele
também responde a 5 perguntas: o que aconteceu, qual é a evidência, o que significa, qual é a incerteza e o que
investigar agora. Os IDs das observações acompanham cada insight. A IA local é opcional e não altera números nem
evidências.

## Clusters

São 8 atributos adimensionais padronizados: crescimento, aceleração, persistência, volatilidade, sazonalidade,
estabilidade, recência e cobertura. K-Means (k = 2–6), hierárquico Ward e HDBSCAN são comparados pelo silhouette, e o
melhor é usado. Os nomes vêm de regras sobre os centróides: Crescimento consistente, Emergentes, Voláteis, Sazonais,
Em declínio e Estáveis. Produtos sem série elegível ficam em "Informação insuficiente".

## Dashboard, dossiê e lista de investigação

- **Dashboard:** 8 seções — visão executiva, produtos para investigar, radar comercial, emergentes, consistentes,
  alertas, comparação internacional (só quando comparável) e insights.
- **Dossiê** (`#dossie/<produto>`): identificação, índices com motivos, inteligência comercial, evidências por tipo
  (observado, derivado e previsto), linhagem e botões de importação.
- **Lista de Investigação:** 9 estados, histórico de mudanças e campos de motivo, evidências, fontes, fornecedores,
  concorrentes, exigências, documentos e próximas ações.
