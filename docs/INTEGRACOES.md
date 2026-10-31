# Registro de integrações — GPI v0.3 (Fase 3)

**Regra:** uma fonte só aparece como *funcional* na página **Saúde das fontes** depois de uma
coleta real validada **na instalação em uso**. Este documento registra o que foi implementado
e como foi verificado durante o desenvolvimento.

## Situação da verificação nesta entrega

O ambiente onde o código foi desenvolvido **não tinha acesso de rede** às APIs públicas
(todas as conexões eram bloqueadas). Por isso:

- Os conectores foram escritos a partir da documentação oficial e de clientes de código aberto
  dessas APIs, e os **parsers** foram testados com respostas sintéticas no formato documentado
  (`tests/fake_sources.py`, usadas somente nos testes).
- **Nenhuma coleta real foi executada durante o desenvolvimento.** A primeira coleta real
  acontece quando o GPI é aberto em uma máquina com acesso à internet. Se o formato real
  divergir do esperado, o conector falha com mensagem clara, não grava nada daquela coleta,
  e as demais fontes seguem funcionando.

| Fonte | Endpoint | Autenticação | Implementação | Confiança no formato |
|---|---|---|---|---|
| Banco Central — PTAX | `olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoMoedaPeriodo` | não | completa (USD, CNY, EUR; diário + média mensal derivada) | alta — campos `cotacaoVenda`, `dataHoraCotacao`, `tipoBoletim` confirmados na documentação/clientes |
| Wikimedia — pageviews | `wikimedia.org/api/rest_v1/metrics/pageviews/per-article/...` e `en.wikipedia.org/w/api.php` (langlinks) | não (User-Agent identificado) | completa (46 conceitos × pt/en/zh, mensal desde 07/2015) | alta |
| Comex Stat (MDIC) | `POST api-comexstat.mdic.gov.br/general` | não | completa (todas as posições SH4, China e total, FOB e kg, mensal) | média — corpo da requisição confirmado no doc.yaml oficial; os nomes dos campos da resposta não constam do doc.yaml, então o parser aceita as variações conhecidas e falha de forma explícita se nenhuma corresponder |
| IBGE — PMC | `servicodados.ibge.gov.br/api/v3/agregados` | não | completa, com localização automática da tabela pelos metadados | média — se o IBGE renomear a pesquisa/tabela, o conector informa "tabela não localizada" |
| UN Comtrade (preview) | `comtradeapi.un.org/public/v1/preview/C/M/HS` | não (limitada) | completa (EUA, Alemanha, México ← China, posições prioritárias) | média — a API pública pode limitar volume ou passar a exigir chave |
| Feeds RSS (6 sites padrão, lista editável) | URLs dos feeds | não | completa (RSS 2.0 e Atom; rejeita XML com DTD) | alta para o formato; os endereços dos feeds podem mudar — cada feed mostra seu próprio erro |
| Google Notícias (RSS) | `news.google.com/rss/search` | não, mas exige aceite dos termos (opt-in) | completa, desativada por padrão | média |
| YouTube Data API v3 | `googleapis.com/youtube/v3/search`, `videos` | **chave de API** do usuário | completa; cota diária limitada pelo GPI; atualização/exclusão em 30 dias; sem NLP nem mistura com outras fontes (políticas do YouTube) | alta (documentação oficial); não testada ao vivo |
| Reddit | `www.reddit.com/api/v1/access_token` (installed client), `oauth.reddit.com/search`, `/comments` | **Client ID** + confirmação de uso autorizado | completa | média; uso comercial exige contrato com o Reddit |
| Mercado Livre — trends | `api.mercadolibre.com/trends/MLB` | **OAuth com PKCE** pela Central de Integrações | implementada; inativa até a conexão | não testada; o DevCenter precisa aceitar a URL de redirecionamento `http://127.0.0.1:8765/oauth/callback` |
| Trustpilot / Reclame Aqui / comparadores de preço | — | contrato/parceria | restritas (sem raspagem) | — |
| Amazon BR / US | PA-API 5 | credenciais de Associado | restrita (não implementada) | — |
| Shopee | Open Platform | parceiro aprovado | restrita | — |
| AliExpress / Alibaba / Taobao | Open Platforms | app key aprovada | restritas | — |
| Google Trends | API oficial em acesso restrito (alfa) | inscrição | restrita (substituída por Wikimedia para interesse público) | — |

Scraping não é usado em nenhuma fonte. Nenhum login, CAPTCHA, limite ou bloqueio é contornado.

## Fase 4 — fontes de interesse de busca e níveis de conexão

A Central de Integrações agrupa as fontes em três níveis:

| Nível | Significado | Fontes |
|---|---|---|
| 1 — Conexão automática | públicas, sem credencial | BCB, Comex Stat, IBGE, UN Comtrade (preview), Wikimedia, RSS, **Google Trends — Trending Now** |
| 2 — Conexão assistida | chave gratuita, ID de aplicativo, OAuth ou aceite de termos | **Google Ads — Planejador de palavras-chave**, **UN Comtrade (chave gratuita)**, YouTube, Reddit, Mercado Livre, Google Notícias |
| 3 — Acesso restrito | aprovação, contrato ou sem API pública | **Google Trends API (alfa)**, **Baidu Index**, **巨量算数**, **Alibaba/1688**, **Microsoft Advertising**, Amazon, Shopee, AliExpress, Taobao, Trustpilot, Reclame Aqui, comparadores |

| Fonte | Situação verificada (out/2026) | O que o GPI faz |
|---|---|---|
| Google Trends API oficial | alfa, acesso por inscrição e aprovação (interesse relativo, escala consistente, 5 anos, ISO 3166-2) | marcada como restrita, com link de inscrição; nenhum endpoint é presumido |
| Google Trends — Trending Now (RSS) | exportação pública oficial, tráfego em faixas | coleta diária BR e EUA; NLP + filtro comercial; limite inferior da faixa, nunca volume exato |
| Google Ads — KeywordPlanIdeaService | exige conta, developer token (acesso Básico ou superior) e OAuth | botão "Conectar"; volumes tratados como aproximados; China não consultada |
| Baidu Index / 巨量算数 / Alibaba | sem API aberta a terceiros; ferramentas existentes usam cookies de sessão | não implementado (seria contornar autenticação) |
| Microsoft Advertising | exige conta e developer token; API SOAP | não implementado nesta fase |

## Lista de conectores validados com resposta real

Resultado da coleta real no GitHub Actions (job *2. Validação real dos conectores*, runner Ubuntu nos EUA,
31/10/2026; artefato `validacao-conectores`). Amostra de até 6 requisições por fonte — a sincronização
completa no computador do usuário coleta o histórico inteiro.

| Fonte | Situação | Registros na amostra |
|---|---|---|
| BCB PTAX (câmbio USD e CNY) | ✅ validada | 962 |
| Wikimedia (interesse público por produto) | ✅ validada | 681 |
| Comex Stat (importações da China por SH4) | ✅ validada | 86.114 |
| UN Comtrade (exportações chinesas) | ✅ validada | 120 |
| Feeds RSS (6 sites) | ✅ validada | 190 itens |
| IBGE PMC | ❌ falhou — tempo esgotado a partir dos EUA (Windows e Ubuntu); provável bloqueio de acesso do exterior; confirmar numa rede brasileira | 0 |
| Google Notícias, YouTube, Reddit, Mercado Livre | ⏸ não testadas — exigem opt-in ou credencial do usuário | — |
| Amazon, Shopee, AliExpress, Alibaba, Taobao, Google Trends, Trustpilot, Reclame Aqui, comparadores | 🚫 restritas — sem API pública gratuita autorizada (não há raspagem) | — |

Uma fonte só é marcada "validada" quando grava pelo menos um registro real; uma API que responde sem dados
aparece como "sem dados". Na instalação do usuário, a página *Saúde das Fontes* faz a mesma verificação na
rede da empresa, que pode bloquear endereços diferentes dos bloqueados no GitHub.

## O que verificar na primeira execução
1. Abrir o GPI e aguardar a sincronização (barra azul no topo).
2. Em **Saúde das fontes**, cada fonte pública deve ficar *funcional* com registros > 0.
3. Se alguma falhar, a coluna *Situação* mostra o motivo:
   - "falha de rede" / "acesso negado": a rede da empresa bloqueia o endereço (ver `docs/TI.md`);
   - "certificado TLS não verificado": configurar `ca_bundle` com a cadeia fornecida pela TI;
   - "campos esperados ausentes" / "tabela não localizada": a fonte mudou o formato — o log
     `data/logs/gpi.log` traz o detalhe para ajuste do conector.
