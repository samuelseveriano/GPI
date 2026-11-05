# Qualidade dos dados — GPI v0.8

Sequência obrigatória: **coleta → compreensão → normalização → validação → consolidação → análise estatística → ML →
inteligência comercial → dashboard → relatórios.** Os gates abaixo ficam entre as etapas. Dados reprovados não seguem
para as etapas seguintes, e o motivo é mostrado em **Fontes e Sistema → Qualidade dos Dados** (`GET /api/v08/qualidade`).

## Diagnóstico da v0.7.1 (inconsistências A–E)

| | Sintoma observado | Causa encontrada no código | Correção v0.8 |
|---|---|---|---|
| A | Dashboard com "3 fontes" apesar de dados de 11 fontes | O KPI contava só as fontes que viravam séries por produto (pesquisa + Wikipédia). Comex Stat, BCB, IBGE, Comtrade, YouTube e RSS nunca entram nessas séries, e ninguém explicava por quê | KPI "fontes funcionais" vem da situação real das fontes, e a tabela **Fontes elegíveis por indicador** diz, para cada índice, quais fontes entram e por que as outras não entram |
| B | Ranking liderado por leitura da Wikipédia (+139,9% câmera de ação…) | O dashboard escolhia o "sinal mais forte" e, sem dados de busca, usava a Wikipédia como se fosse demanda | A Wikipédia é tipada como ATENÇÃO PÚBLICA e não alimenta índices de pesquisa ou de sinal comercial. A variação é comparada à mediana dos artigos do mesmo idioma, e só atenção pública não gera prioridade de investigação |
| C | 40 "perdendo interesse", 0 "merecem investigação" | `declínio` disparava com uma única comparação de 3 meses (< −15%) sem significância nem base. Como o tráfego total da Wikipédia cai, quase todo artigo "caía" | DECLÍNIO exige tendência significativa, ou queda com base suficiente e persistência ≤ 40%. O restante vira VARIAÇÃO NÃO CONFIRMADA. Criadas classes intermediárias. **Os critérios de investigação não foram reduzidos** |
| D | Vídeos de entretenimento ligados a produtos, vídeos em inglês como "Brasil" | Todo vídeo devolvido pela busca recebia o produto da consulta. O idioma era ignorado | O título precisa confirmar o produto (mesma família e variante compatível). O mercado vem do idioma do vídeo, não do `regionCode` |
| E | Executivo com ~79 páginas | O executivo incluía todas as seções completas (até 150 linhas) e uma tabela de 17 colunas | Executivo de 5 páginas, mais Relatório Técnico separado e Relatório de Homologações |

Também corrigido: o ranking do Mercado Livre e as listas de alta geravam "% de crescimento" somando posições
(51 − posição). Isso foi removido: posição é avaliada só por persistência e posição.

## Etapa 1 — compreensão das fontes

`backend/gpi/intel/semantics.py` registra, para cada fonte: o que mede, unidade, frequência, cobertura, data de
referência, limitações, relevância e condições de uso. Também registra se a fonte pode ser combinada com outras
(YouTube e redes sociais: **não**, por política das plataformas). Toda métrica tem **um** tipo de evidência:

| Tipo | Exemplos | Não é |
|---|---|---|
| SEARCH_INTEREST | Google Ads, Bing, Trending Now, BigQuery | volume de vendas |
| COMMERCIAL_SEARCH_INTENT | ranking do Mercado Livre | volume de buscas (é posição) |
| PUBLIC_ATTENTION | Wikipédia, GDELT, RSS, notícias | intenção de compra |
| SOCIAL_ATTENTION | YouTube, TikTok, Instagram | vendas (exibido à parte) |
| FOREIGN_TRADE | Comex Stat, Comtrade | demanda de consumidores (é NCM/SH) |
| ACTUAL_DEMAND | vendas importadas pelo usuário | — |
| MARKET_OFFER / MACRO_CONTEXT | eBay; PTAX, IBGE | demanda de produto |

## Gate 1 — integridade

Datas ISO, sem datas futuras, uma unidade por (fonte, métrica), valores não negativos, posições do ranking entre 1 e
50, duplicatas por grafia (alerta), proveniência (data de coleta), países reconhecidos (alerta), observações órfãs e
`PRAGMA integrity_check`. Um par (fonte, métrica) reprovado fica **fora da modelagem**: os métodos dessa série são
marcados como não elegíveis, com o motivo.

## Gate 2 — identificação de produtos

Estados: **confirmada**, **provável**, **ambígua** e **não identificado**. Quando há ambiguidade, o termo original é
preservado e não é associado a nenhum produto. Só correspondências confirmadas entram no ranking de investigação.

Há dois conjuntos rotulados à mão (`backend/gpi/intel/data/`), em pt, en, es e zh, com termos comerciais, variantes,
sinônimos, vídeos, notícias, termos não comerciais e termos ambíguos:

| Conjunto | Uso | Casos | Precision | Recall | F1 | Incorretas | Abstenção |
|---|---|---|---|---|---|---|---|
| Desenvolvimento (`matching_eval.tsv`) | **usado para ajustar regras** (número otimista) | 141 | 100% | 100% | 100% | 0% | 25,5% |
| **Teste (`matching_holdout.tsv`)** | escrito antes de rodar o motor, **nunca usado para ajustar** | 81 | **98,4%** | **95,4%** | 96,9% | **1,2%** | 22,2% |

Antes dos ajustes, o conjunto de desenvolvimento dava precision 97,8% e recall 85,8%. Os ajustes feitos foram: termos
em espanhol, plurais, palavras polissêmicas avaliadas pela palavra (e não pelo conceito), "com/with" tratado como
característica, termos faltantes no léxico, e "película" que não deve ser lida como "filme". Um rótulo errado foi
corrigido ("sensor de presença" → `motion_sensor`).

Único erro no teste: "ssd 2tb". O produto foi identificado corretamente, mas a variante saiu normalizada como 2048 GB
e o rótulo dizia "2tb". O rótulo foi mantido como estava e o caso conta como erro.

**Metas documentadas:** precision ≥ 95%, associações incorretas ≤ 3%, recall ≥ 70%. A precisão é prioridade: o motor
deve preferir abster-se a associar errado. As metas não são atingidas reduzindo a abstenção às custas de erros.

O Gate 2 também reavalia, no banco real, os termos já associados e os vídeos do YouTube. Um produto com menos de 80%
de termos confirmados fica em observação, com o alerta "qualidade dos dados".

## Gate 3 — semântica

Verifica que a Wikipédia não alimenta índices de demanda, que o ranking não é tratado como volume, que notícias não
contam como venda, que índices relativos não geram % de volume e que YouTube e redes sociais ficam à parte. Também
verifica que toda métrica gravada no banco existe no catálogo semântico.

## Gate 4 — elegibilidade estatística

| Método | Requisito |
|---|---|
| Tendência | ≥ 6 meses e ≥ 50% dos meses com valor |
| Aceleração | ≥ 9 meses com base suficiente |
| Sazonalidade | ≥ 24 meses (2 ciclos) e ≥ 80% preenchidos |
| Previsão | métrica modelável, ≥ 18 meses, ≥ 80% preenchidos, base suficiente, sem mudança de patamar nos últimos 4 meses |
| Agrupamento | mesmos critérios da tendência |
| Séries diárias de lista ou ranking | só presença e persistência: sem tendência, sazonalidade ou previsão |

Uma série inelegível recebe análise exploratória e o motivo. **Nenhuma previsão é exibida sem elegibilidade.**

## Gates 6 e 8

- **Gate 6:** todo insight tem os 11 campos obrigatórios e os IDs das observações em que se baseia.
- **Gate 8 (consistência fim a fim):** as observações ligadas a produtos no banco são iguais à soma da linhagem; o
  ranking contém só produtos analisados; há um insight por produto; os KPIs batem com as contagens da fusão; as fontes
  funcionais batem com a situação gravada. O dashboard, o dossiê e os relatórios leem o **mesmo** resultado gravado
  (`intel08`).
