# Relatório técnico das fontes — GPI v0.6

"Validada" = coleta real executada com registros gravados no banco (job 2 do GitHub Actions, runners nos EUA).
Fontes que exigem conta do usuário não podem ser validadas sem essa conta: o código, o parser e o armazenamento
são testados com respostas no formato documentado, mas **a integração não é declarada funcional**.

## Fontes de pesquisa e marketplaces

| Fonte | Endpoint | Autenticação | Custo | Limites | Campos usados | Cobertura | Histórico | Resultado real | Restrições de uso e armazenamento |
|---|---|---|---|---|---|---|---|---|---|
| Google Trends — Trending Now | `trends.google.com/trending/rss?geo=` | nenhuma | grátis | uso moderado (1 consulta/país/sincronização) | termo, faixa de tráfego, data, notícias | BR, US (configurável) | só a lista atual; o GPI acumula a cada coleta | **validada** (v0.5: 20 termos, nenhum de produto) | atribuição "Fonte: Google Trends" |
| Google Ads — Planejador (KeywordPlanIdeaService) | `googleads.googleapis.com/vNN/customers/{id}:generateKeywordIdeas` | OAuth 2.0 (escopo adwords) + developer token | grátis (conta Google Ads, sem anúncios) | nível **Explorer não acessa** o planejador; exige **Basic** (15.000 operações/dia) ou Standard | volume mensal aproximado (12 meses), concorrência, lances | por país/idioma | 12 meses por consulta; o GPI acumula | **não validada** (requer conta) | usar só para planejamento; volumes arredondados em faixas |
| Google Trends no BigQuery | `bigquery.googleapis.com/.../queries` (conjunto `bigquery-public-data.google_trends`) | OAuth (bigquery.readonly) + projeto Google Cloud | camada gratuita 1 TB/mês; o GPI mede cada consulta (dry run) e bloqueia acima de 2 GB | cotas do projeto | top 25 e em alta por região, semana, score 0–100 | ~50 países + DMAs dos EUA | 5 anos de semanas | **não validada** (requer projeto) | índice relativo, não volume |
| Microsoft Advertising — Ad Insight | SOAP `GetHistoricalSearchVolume` | OAuth Microsoft + developer token | grátis | cotas da conta | volume mensal de buscas no Bing | por país | até 24 meses | **não validada** e envelope SOAP não conferido com conta real | uso para planejamento |
| Mercado Livre Trends | `api.mercadolibre.com/trends/MLB` | OAuth do app do usuário | grátis | limites do app | termo, posição, link | Brasil | lista atual; o GPI acumula | **não validada** (requer app) | posição ≠ volume |
| eBay Browse | `api.ebay.com/buy/browse/v1/item_summary/search` | client credentials (app) | grátis | 5.000 chamadas/dia (padrão) | título, marca, preço, moeda, vendedor, condição | EUA | anúncios ativos | **não validada** (requer chave) | anúncios ≠ vendas |
| GDELT DOC 2.0 | `api.gdeltproject.org/api/v2/doc/doc` | nenhuma | grátis | ~1 consulta/5 s (o GPI usa 6,5 s) | artigos por dia, manchetes | mundo | ~3 meses no modo timeline | **validada** (v0.5: 12 registros; HTTP 429 frequente a partir do GitHub) | repercussão ≠ consumo |

## Redes sociais (v0.6)

| Fonte | Endpoint | Autenticação | Custo | Limites | Campos usados | Cobertura | Histórico | Resultado real | Restrições de uso e armazenamento |
|---|---|---|---|---|---|---|---|---|---|
| TikTok API for Business — Discovery | `business-api.tiktok.com/open_api/v1.3/discovery/trending_list/`, `discovery/search/`, `discovery/search/keyword/` (cabeçalho `Access-Token`) | OAuth do portal TikTok for Business (advertiser_id para hashtags; open_id/business_id da conta para termos) ou token de longo prazo gerado no portal | grátis com conta Business e app aprovado | limites por app (códigos 40100/51021 tratados como limite) | hashtag, posição, variação de posição, visualizações e publicações da janela, termos em alta (20), termos recomendados (20) | hashtags: país (`country_code`, padrão US); termos: região da conta (a API não informa o país) | janela 1/7/30/120 dias; o GPI acumula a cada coleta | **não validada** (requer conta) | Research API não usada (acadêmica). Caminho `/discovery/trending/search/` citado na especificação **não existe** no SDK conferido; usado `discovery/search/` (configurável). Retenção padrão 90 dias |
| Instagram — Hashtag Search | `graph.facebook.com/vNN/ig_hashtag_search`, `/{hashtag}/top_media`, `/{hashtag}/recent_media` | Login do Facebook (instagram_basic) + recurso **Instagram Public Content Access** aprovado + conta profissional | grátis | **30 hashtags distintas por conta em 7 dias**; recent_media até 50 itens | curtidas e comentários (medianas do top), publicações em 24 h | global (sem país) | não há série histórica na API; o GPI acumula | **não validada** (requer app aprovado) | só agregados; legendas e usuários não guardados; retenção 90 dias |
| Facebook — Pages | `graph.facebook.com/vNN/{page}/posts` | Login do Facebook (pages_read_engagement); páginas de terceiros exigem **Page Public Content Access** | grátis | rate limit da plataforma | data, reações, comentários, compartilhamentos (texto lido e descartado) | páginas escolhidas pelo usuário | últimos 90 dias por coleta | **não validada** | só contagens mensais por produto; retenção 90 dias |
| Biblioteca de Anúncios da Meta | `graph.facebook.com/vNN/ads_archive` | token com `ads_read` + identidade verificada | grátis | não documentado (o GPI lê no máximo 500 anúncios por produto) | quantidade de anúncios ativos com o termo | **anúncios comerciais só da UE**; no Brasil apenas anúncios políticos/eleitorais | anúncios ativos | **não validada** | não informa investimento/alcance de anúncios comerciais; o GPI não estima |
| YouTube Data API v3 | `www.googleapis.com/youtube/v3/search`, `videos` | chave de API | grátis (10.000 unidades/dia; busca = 100) | cota diária configurável | contagem de vídeos e visualizações por produto | por região/idioma | 180 dias por busca | **não validada** nesta versão (requer chave) | estatísticas até 36 meses; títulos/descrições 30 dias; métricas derivadas só com o caso de uso "Analytics & Reporting" aceito (opção `youtube_em_indices`, desligada por padrão) |
| Reddit | `oauth.reddit.com` (installed client) | client_id + confirmação de uso | grátis só para uso não comercial | 100 consultas/min (OAuth) | menções em discussões | global | recente | **não validada** | uso comercial exige contrato com o Reddit |

## Dados públicos

| Fonte | Resultado real (CI) | Observação |
|---|---|---|
| Banco Central (PTAX) | validada | — |
| Comex Stat | validada | 12 s entre chamadas (HTTP 429) |
| UN Comtrade | validada (endpoint público, 1 mês por chamada) | chave gratuita opcional acelera 12× |
| Wikimedia | validada | atenção, não buscas |
| IBGE | **não validada**: sem resposta a partir dos EUA | confirmar numa rede brasileira |

## Fontes chinesas
Baidu Index, 巨量算数 (Ocean Engine), Alibaba e JD.com não oferecem API aberta a terceiros. Ficam como **restritas**
com o motivo; nada é raspado. Não há fonte autorizada de buscas de consumidores na China continental.

## Custos potenciais
Nenhuma fonte usada pelo GPI cobra por padrão. Custos só podem surgir se o próprio usuário ativar recursos pagos nas
contas dele: BigQuery acima de 1 TB/mês (o GPI bloqueia consultas acima de 2 GB cada), planos pagos de APIs de
terceiros ou contrato comercial do Reddit. O GPI não ativa serviços pagos.
