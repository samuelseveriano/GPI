# Auditoria das APIs — GPI v0.7.1

Fonte dos números: **coleta real** no job 2 do workflow `windows-build`
(run 41766765441, 04/11/2026, Ubuntu do GitHub, **sem nenhuma credencial**, amostra de até 6 requisições por fonte).
A matriz completa (A–F) é regenerada a cada execução em `auditoria_fontes.md` (artefato `validacao-conectores` e
resumo do job) e, no aplicativo, em **Saúde das Fontes**.

Etapas: A configuração · B autenticação · C coleta · D processamento · E persistência · F visualização.
Regra: um token aceito leva no máximo a "Autenticada"; "Funcional" exige coleta bem-sucedida + registros gravados +
registros ligados a produtos do catálogo.

## 1. Fontes públicas — VALIDADAS COM DADOS REAIS (CI)

| Fonte | Estado da sincronização (real) | Registros gravados | Observação |
|---|---|---|---|
| Google Trends — Trending Now (RSS) | funcional | 20 (10 BR + 10 US) | 0 termos com produto/comerciais nesta amostra: o feed do dia trazia notícias/esportes, corretamente **não** tratados como produtos |
| Wikimedia (pageviews) | funcional | 687 | séries ligadas aos produtos do catálogo |
| Feeds RSS especializados | funcional | 189 | manchetes ligadas a produtos |
| BCB PTAX | funcional | 966 | contexto cambial (não é fonte de produto) |
| Comex Stat (MDIC) | funcional | 86.114 | importações brasileiras por NCM |
| UN Comtrade | funcional | 120 | endpoint público sem chave; a chave é opcional |
| IBGE PMC | **falha** | 0 | tempo de conexão esgotado (15 s) com `servicodados.ibge.gov.br` a partir do CI — instabilidade do servidor/rota, não do código; nova tentativa com backoff |
| GDELT | **falha** | 0 | HTTP 429 ("one every 5 seconds"); o GPI respeitou o limite (63 s de espera) e adiou os jobs, como exigido |

Resumo da matriz A–F nesse run (fase final, mais exigente que o estado da sincronização): Funcional 2 · Dados armazenados 3 · Falha 2 · Não configurada 13 ·
Aguardando autorização 1 · Restrita 8 (29 fontes descobertas automaticamente no registro).

"Dados armazenados" (e não "Funcional") para Trends RSS, PTAX e Comex Stat significa: dados reais gravados, mas
nenhum ligado a um produto do catálogo nesta amostra — PTAX é contexto por natureza. Nesse run Comtrade ainda
aparecia em "Não configurada" (defeito 2 abaixo, já corrigido).

### Defeitos encontrados pela própria auditoria e corrigidos

1. **"0 novas observações" com registros gravados** (Trends RSS 20, RSS 189). Mesma classe do defeito do Mercado
   Livre: conectores que gravam direto nas tabelas não informavam a contagem. Correção genérica no sincronizador
   (contagem de linhas novas por fonte antes/depois de cada job; índice da chave primária) + teste
   `test_direct_write_connectors_count_new_rows`.
2. **Comtrade como "Não configurada" com 120 registros reais.** A fase considerava a falta de chave antes da
   evidência gravada. Agora dados reais gravados têm precedência + teste
   `test_audit_public_endpoint_with_data_is_not_unconfigured`.

Desempenho real (mesma coleta): sequencial 339,6 s · paralelo (4 workers) 201,4 s; maior custo em GDELT (429) e
Comtrade (1ª resposta ~3,7 s).

## 2. Fontes que exigem credenciais do proprietário — NÃO validadas no CI

Mercado Livre (tendências e `mercadolivre`), Google Trends BigQuery, Google Ads (Keyword Planner), Microsoft
Advertising, YouTube, Reddit, TikTok, Instagram, Facebook, Meta Ads Library, eBay.
Estado esperado sem credenciais: **Não configurada**. Validação: no PC do proprietário, conforme
`TESTE_CORPORATIVO.md`. O Mercado Livre teve o OAuth real confirmado pelo proprietário (50 termos em
`GET /trends/MLB`); a gravação/contagem desses termos foi corrigida e está coberta por teste, mas a confirmação
**com dados reais depois da correção** é o passo 4–6 do teste corporativo.

Google Notícias (RSS) é opt-in: **Aguardando autorização** até ser habilitado pelo usuário.

## 3. Fontes restritas (sem API pública utilizável) — Restrita

Amazon BR, Amazon US, Shopee, AliExpress, Taobao, Google Trends API (séries históricas, acesso por aprovação),
Trustpilot, comparadores de preço. Não há scraping que viole termos; ausência dessas fontes **não** é interpretada como
demanda baixa.

## 4. Fontes removidas — não reintroduzidas

Reclame Aqui · Baidu Index · 巨量算数 (Ocean Engine/Douyin) · Alibaba.com · Alibaba/1688 · JD.com.

## 5. Erros tratados (TESTADO com respostas simuladas)

Credenciais ausentes/inválidas, token expirado (refresh), timeout, 401/403/429 (Retry-After)/500, JSON inválido,
resposta vazia, persistência, coleta incremental, reabertura do aplicativo — `tests/test_v071_sync.py`,
`tests/test_v05.py`, `tests/test_v061.py` e testes de integração anteriores.
