# GPI — Global Product Intelligence · v0.7

> **v0.7 — Product Compliance & Security Intelligence:** novo módulo **Conformidade de Importação** (triagem regulatória
> Anatel/Inmetro/Receita/Siscomex com 5 estados, NCM, homologações, checklist PT/EN/中文, relatório de 17 seções), IA local
> opcional (llama.cpp + Qwen3 GGUF, pacote separado e verificado), OAuth do Mercado Livre com Redirect URI HTTPS, retirada de
> fontes sem acesso aberto e auditoria de segurança. Ver [docs/V07.md](docs/V07.md), [docs/SEGURANCA_V07.md](docs/SEGURANCA_V07.md),
> [docs/MERCADO_LIVRE_OAUTH.md](docs/MERCADO_LIVRE_OAUTH.md) e [docs/USO_CORPORATIVO.md](docs/USO_CORPORATIVO.md).


Plataforma **local e autônoma** de inteligência de produtos: coleta dados de fontes públicas e
autorizadas, analisa opiniões de consumidores, acompanha o YouTube, compara produtos, gera
previsões e ranqueia oportunidades — sem planilhas e sem configuração. Todas as fórmulas estão na
página *Metodologia* e são verificadas por testes.

- **Usuário final:** veja `MANUAL.md` (abrir com dois cliques em `GPI.exe`).
- **TI:** `docs/TI.md` (rede, arquivos, segurança). **Build do executável:** `docs/BUILD.md`.
- **Integrações e o que foi validado:** `docs/INTEGRACOES.md` e `docs/FONTES_V06.md` (relatório técnico por fonte).
- **Relatórios Excel/PDF:** `docs/RELATORIOS.md`. **Plano da v0.6:** `docs/PLANO_V06.md`.

> **Executável Windows:** o `GPI-Windows-Portable.zip` é gerado e testado pelo GitHub Actions
> (aba *Actions → windows-build → Artifacts*). O `GPI.exe` passa pelos testes A–J numa cópia
> sem Python instalado: inicialização, servidor, interface, modelos de ML dentro do pacote,
> persistência, exportação de relatórios XLSX/PDF, encerramento, integridade. Veja `docs/BUILD.md`.

## Executar

- **Usuário final (Windows):** extrair `GPI-Windows-Portable.zip` e clicar duas vezes em `GPI.exe`.
- **Desenvolvimento:** `pip install -r requirements.txt` (opcional: `-r requirements-optional.txt`) e
  `Start_GPI.bat` (Windows) ou `./start_gpi.sh` (Linux/macOS). Dados em `data/`.
- **Testes:** `pip install -r requirements-dev.txt` e `python -m pytest tests`.

## Versão 0.6.1 — Intelligent Sync & API Stability Update
Detalhes e diagnóstico completo em `docs/V061.md`.
- **Google Ads sem developer token** (descontinuado pelo Google em 09/09/2026): Client ID/Secret → Entrar com Google →
  contas identificadas automaticamente → diagnóstico de OAuth, conta, nível de acesso e permissão do planejador.
- **YouTube Intelligence** lê os vídeos armazenados diretamente do banco, com filtros, indicadores, diagnóstico A–E e
  "Atualizar agora" limitado pela cota.
- **Painel de sincronização** em tempo real (SSE) por API, com progresso real, histórico, novas tentativas, cancelamento
  cooperativo, log estruturado sem segredos e exportação de diagnóstico.
- **Conexões**: keep-alive, tempos de conexão/leitura separados, Retry-After, semáforo por host e métricas por host.
- **Meta** em módulos de permissões, verificação do app e orientação oficial para o bloqueio "Recurso indisponível".
- **Central de Integrações**: estados Configurado → Autenticado → Autorizado → Validado → Funcional, Restrito e Erro.

## Versão 0.6 — o que foi implementado

Pergunta que orienta a versão: *quais produtos específicos estão ganhando procura no Brasil e em outros mercados e,
entre eles, quais merecem ser investigados para importação da China?*

- **Centro de Relatórios** (`backend/gpi/reports/`): 8 tipos (Radar Global, Mais Pesquisados/Interesse Relativo,
  Tendências por País, Social Media Intelligence, Previsões e ML, Oportunidades de Importação, Análise do Produto,
  Executivo) em **Excel, PDF e CSV**, gerados localmente (openpyxl + ReportLab). Filtros impressos no documento,
  natureza de cada dado (observado/estimado/projeção/derivado), histórico com snapshot para reprodução, exclusão
  com confirmação, exportação por página e relatório semanal automático opcional (desligado por padrão).
- **Tendências nas Redes Sociais** (`backend/gpi/social/`): TikTok API for Business (Discovery: hashtags populares
  por país, termos de busca em alta, termos recomendados), Instagram (hashtags, Graph API), Facebook (páginas
  informadas pelo usuário) e Biblioteca de Anúncios da Meta (anúncios ativos na UE) — todos com OAuth assistido e
  **não validados sem conta do usuário**; YouTube e Reddit (fase 3) integrados à análise. Retenção por fonte,
  cota de 30 hashtags/7 dias do Instagram, só agregados guardados.
- **Social Trend Score, Viral Product Radar e Search vs. Social**: normalização dentro de cada plataforma, seis
  classes do radar, indicadores separados de busca, social e marketplace com consistência de direção entre fontes.
- **Product Opportunity Engine 3.0**: nove dimensões (busca, social, marketplace, persistência, concorrência,
  risco de qualidade, cobertura, previsão, prontidão) e prioridade de investigação — sem probabilidade de sucesso,
  margem ou recomendação de compra.
- **ML com × sem sinais sociais**: backtesting de origem móvel sem vazamento; os sinais só são usados com ganho
  fora da amostra (≥ 2% de WAPE e ≥ 75% das origens).
- **Menu v0.6** (9 grupos, com Redes Sociais e Relatórios) e **Central de Integrações** por categoria
  (Pesquisas, Marketplaces, Redes Sociais, Dados Públicos) com situação de cada conector.
- **Pacote**: `GPI-Windows-Portable-v0.6.zip`; smoke test do executável gera e confere XLSX e PDF.

## Versão 0.5 — o que foi implementado

| Recurso | Situação |
|---|---|
| Menu lateral com 7 categorias expansíveis (uma aberta por vez, teclado, `aria-expanded/aria-controls`, seta, animação de 180 ms, `prefers-reduced-motion`), modo recolhido só com ícones SVG e dicas, busca global e indicador de status da coleta | ✅ testado no navegador em 1366×768 e 1920×1080 (38 rotas, sem erros de JavaScript) |
| Mercado Livre Trends, Google Trends no BigQuery (dry run + limite de custo), eBay Browse, GDELT, Microsoft Advertising, JD.com (restrito) | ✅ implementados e testados com respostas simuladas · ⚠️ validação real: GDELT no CI; os demais exigem credenciais do usuário (ver `docs/INTEGRACOES.md`) · ⚠️ Microsoft Advertising não validado |
| Discovery Engine 2.0: correção de grafia, aliases por similaridade (RapidFuzz ou difflib), bloqueio de agrupamento de variantes técnicas, embeddings multilíngues opcionais | ✅ testado · embeddings não incluídos no pacote (ver abaixo) |
| Modelo global multi-série (HistGB, LightGBM, XGBoost, CatBoost) × modelos locais por backtesting; escolha por série | ✅ testado (LightGBM/XGBoost/CatBoost no CI) |
| Intervalos conformais 80/90/95% com cobertura observada; SHAP (TreeSHAP nativo); Optuna com limites; ADWIN/Page-Hinkley; reconciliação BU/TD/MinT | ✅ testados |
| Early Trend Detection (persistência, aceleração, saturação, cobertura, confiança, base mínima) e International Trend Signal | ✅ testados |
| Review Intelligence 2.0, Análise de Concorrência, Viabilidade de Importação (Monte Carlo, cenários, sensibilidade, pedido ótimo) | ✅ testados |
| Configurações pela interface; estados vazios explicando o que falta | ✅ |
| GPI.exe: ícone, metadados 0.5.0, verificação do Microsoft Defender, relatório de segurança, SHA-256, ZIP `GPI-Windows-Portable-v0.5.zip`, assinatura opcional preparada | ✅ no workflow · ⚠️ **não assinado** (ver `docs/SEGURANCA.md`) |

**Decisões técnicas:** MLForecast e HierarchicalForecast não foram incluídos (dependem de compilação JIT/numba, pesada
para o pacote portátil); o modelo global e a reconciliação foram implementados diretamente com as mesmas técnicas e
testes. MAPIE: o método conformal foi implementado diretamente (a API de séries temporais do MAPIE mudou na v1 e não
pôde ser validada aqui). OR-Tools: a otimização do pedido é exata em uma dimensão, sem necessidade de solver.
Polars/DuckDB: sem ganho mensurável no volume atual (SQLite + pandas). Sentence-transformers: opcional e não
empacotado (PyTorch + modelo ≈ 1 GB); quando presente em `modelos/`, só sugere produtos relacionados.

## Fase 4 — inteligência de consumo (o que foi implementado)

O foco passou a ser **produtos específicos** (ex.: carregador USB-C 65W, capacete de moto, fechadura
eletrônica), não posições SH4. Três dimensões ficam separadas e nunca são misturadas: **consumo**
(interesse de busca), **comércio exterior** (importações) e **mercado** (preços, reviews, conteúdo).

| Recurso | Situação |
|---|---|
| Catálogo canônico Categoria → Família → Produto → Variante, pt/en/zh, ~110 produtos de referência + descoberta automática (candidatos promovidos com evidência), SH4 só quando fundamentado | ✅ testado |
| NLP local: limpeza, idioma, tokens (chinês por máxima correspondência), conceitos, atributos (potência, mAh, conector, marca, modelo), chave conceitual multilíngue, variantes | ✅ testado (15 termos de referência em 3 idiomas) |
| Intenção de busca (compra, comparação, review, problema, manutenção, informação, entretenimento, notícia): regras + modelo supervisionado com controle de qualidade | ✅ regras ≥ 80% em conjunto separado · ⚠️ o modelo supervisionado fica desligado até atingir acurácia ≥ 0,60 (hoje 0,40 com 92 rótulos) |
| Google Trends — Trending Now (RSS oficial), Brasil e EUA, filtro de relevância comercial | ✅ implementado e testado com resposta simulada · validação real no CI (ver `docs/INTEGRACOES.md`) |
| Google Ads — Planejador de palavras-chave (API oficial, OAuth + developer token, descoberta da versão ativa) | ✅ implementado e testado com respostas simuladas · ⚠️ não validado com conta real (exige credenciais do usuário) |
| China: Baidu Index, 巨量算数, Alibaba | 🚫 sem API aberta — identificados como acesso restrito; a página da China mostra a limitação em vez de rankings fictícios |
| Rankings separados que declaram o que medem; "mais pesquisados" só com volume de buscas | ✅ testado |
| Crescimento ano contra ano, tendência (Mann–Kendall), sazonalidade, aceleração, pontos de mudança, anomalias | ✅ testado |
| Comparação internacional com lead-lag exploratório (significância, estabilidade, backtest) | ✅ testado |
| Opportunity Score, Evidence Coverage, Forecast Confidence, Import Readiness (separados; sem margem nem quantidade de compra) | ✅ testado |
| Coleta em paralelo por etapas (concorrência limitada por fonte), disjuntor por host, ETag/304, gzip, métricas por fonte | ✅ testado |
| IBGE: corrigido o erro "byte 0x8b" (resposta gzip sem descompressão) | ✅ testado com servidor local · ⚠️ o IBGE não responde a partir dos EUA (CI); validar numa rede brasileira |
| UN Comtrade: 1 período por chamada sem chave; até 12 com a chave gratuita opcional | ✅ testado |
| Novo menu; submenu recolhível "Vendas próprias"; páginas Brasil, China, EUA, produto, comparação, oportunidades, alertas, emergentes, previsão de tendências, anomalias, catálogo, desempenho | ✅ verificado no navegador (sem erros de JavaScript) |
| Migração automática do banco da Fase 3 (v3 → v4), sem apagar dados | ✅ testado |

**Limites importantes:** o feed "Trending Now" lista poucas buscas por dia (muitas são notícias); o histórico
se forma com as coletas diárias. Volumes mensais por produto exigem conectar o Google Ads. Não há fonte
autorizada de buscas na China continental. Visualizações da Wikipédia e menções são exibidas como sinais
auxiliares, com rótulo próprio — nunca como "pesquisas".

## Fase 3 — o que foi implementado

| Recurso | Situação |
|---|---|
| Inicializador do `GPI.exe`: integridade (SHA-256), dados em `%LOCALAPPDATA%\GPI`, porta, navegador, janela de controle, encerramento seguro, `--smoke/--check/--stop/--selftest` | ✅ testado no Windows (CI) e no Linux |
| PyInstaller one-folder + workflow Windows com testes do executável (A–H) e validação real de conectores | ✅ executado no GitHub Actions |
| Central de Integrações: conectar, testar, sincronizar, desconectar; chave de API, Client ID, OAuth 2.0 com PKCE, opt-in de termos, links oficiais para aprovação | ✅ testado (com respostas simuladas) |
| Cofre de credenciais (DPAPI no Windows; arquivo 0600 nos demais) | ✅ testado no Linux · ⚠️ DPAPI só roda no Windows |
| Proteção CSRF (cabeçalho obrigatório + Origin) | ✅ testado |
| YouTube Data API (quota, retenção de 30 dias, classificação por tipo de vídeo) | ✅ testado com respostas simuladas |
| Reddit, RSS (6 sites), Google Notícias (opt-in) | ✅ testado com respostas simuladas |
| Trustpilot, Reclame Aqui, comparadores de preço | ✅ restritos, com motivo (sem raspagem) |
| Review Intelligence: sentimento pt/en, 11 aspectos, alvo da reclamação, exemplos com link | ✅ testado (≥ 85% em 30 frases rotuladas) |
| Comparador de produtos com fonte e confiabilidade por atributo | ✅ testado |
| SARIMA, LightGBM, XGBoost no AutoML | ✅ testados no CI e executados dentro do `GPI.exe` (`--selftest`) |
| Score com cobertura e confiança separadas; ausência de fonte não penaliza; 8 rankings novos | ✅ testado |
| 15 páginas no menu (Visão Geral, Radar Global, Brasil, China, Marketplaces, YouTube, Reviews, Comparador, ML, Forecasting, Clustering, Ranking, Central de Integrações, Saúde das Fontes, Metodologia) | ✅ verificado no navegador |

## Fase 2 — o que foi implementado

| Recurso | Situação |
|---|---|
| Conectores públicos: BCB PTAX, Wikimedia (pt/en/zh), Comex Stat (todas as posições SH4), IBGE PMC, UN Comtrade | ✅ coleta real validada para PTAX, Wikimedia, Comex Stat, Comtrade e RSS · ❌ IBGE sem resposta a partir dos EUA (ver `docs/INTEGRACOES.md`) |
| Fontes restritas identificadas com motivo: Amazon BR/US, Shopee, AliExpress, Alibaba, Taobao, Google Trends; Mercado Livre ativável com token OAuth | ✅ |
| Proveniência completa por série e observação (fonte, URL, coleta, referência, país, categoria, unidade, moeda, tipo, confiabilidade, método, revisões) | ✅ testado |
| Sincronização automática na abertura e semanal; jobs idempotentes, retry/backoff, rate limit, cache, retomada após falha, cancelamento | ✅ testado |
| Descoberta automática de produtos (todas as posições SH4 importadas da China), taxonomia inicial, normalização pt/en/zh e deduplicação | ✅ testado |
| Séries derivadas: participação da China, preço indicativo US$/kg, PTAX média mensal | ✅ |
| AutoML: perfil da série, candidatos, backtesting, escolha, intervalos, qualidade, retreino por hash, avaliação de previsões antigas | ✅ testado |
| Novos modelos: Random Forest e HistGradientBoosting (scikit-learn, CPU) | ✅ testado |
| Clusterização: K-Means (k por silhueta), Aglomerativo, HDBSCAN, PCA, Isolation Forest, rótulos interpretáveis | ✅ testado |
| Score de oportunidade 0–100 com pesos documentados e 6 rankings | ✅ testado |
| Painel autônomo: Visão global, Brasil, China, Machine learning, Oportunidades, Saúde das fontes; origem de qualquer série com um clique | ✅ |
| Funcionamento offline com dados já coletados | ✅ testado |

**Não implementado nesta fase (e por quê):**
- Fornecedores chineses: não há fonte gratuita autorizada; a aba China mostra preços médios
  indicativos de importação (Comex Stat), não cotações.
- Comparações regionais por UF no Brasil.

## Fase 1 (preservada)

| Recurso | Situação |
|---|---|
| Servidor local 127.0.0.1, proteção de Host, encerramento seguro, logs | ✅ |
| Banco local com migrações versionadas (v1 → v2 automática) e backup | ✅ |
| Importação CSV/XLSX, dados demonstrativos identificados | ✅ |
| 10 modelos estatísticos + backtesting + intervalos | ✅ (agora 12 com os de ML) |
| Tendência, sazonalidade, ABC/XYZ, estoque, exportações | ✅ |

## Desvios da arquitetura recomendada (e por quê)
- **Starlette** em vez de FastAPI: é a base do FastAPI, com a mesma API ASGI; reduz dependências. Migrar para FastAPI é direto.
- **SQLite** como padrão (DuckDB opcional): faz parte do Python, zero instalação — ideal para o modo portátil.
- **JavaScript puro** em vez de React/Vite/ECharts: sem etapa de build nem Node.js; gráficos em SVG e fórmulas em MathML, tudo offline. Uma migração para React é possível quando a interface crescer.
- **Modelos implementados explicitamente** (numpy/scipy) em vez de StatsForecast: cada linha corresponde a uma fórmula documentada, o que facilita auditoria.

## Testes
```
pip install -r requirements-dev.txt
python -m pytest tests
```
Resultado local: **145 aprovados e 3 ignorados** (os 3 exigem statsmodels/LightGBM/XGBoost). No CI do Windows,
com essas bibliotecas instaladas, a suíte completa é aprovada antes de cada build.

## Formato de importação
Uma linha por venda (ou por dia/SKU). Exemplo em `docs/modelo_importacao.csv`.
Obrigatórias: data, quantidade e SKU ou produto. Opcionais: categoria, preço unitário.

## Estrutura
```
backend/gpi/            servidor, banco, importação, regras
  products/             Fase 4: léxico pt/en/zh, NLP, intenção, catálogo, tendências de consumo, API
  connectors/           conectores das fontes (HTTP com retry/cache/proxy)
  market/               sincronização, descoberta, AutoML, clusters, oportunidades
  forecasting/          modelos estatísticos e de ML, backtesting
  analytics/            tendência, sazonalidade, ABC/XYZ
  supply_chain/         estoque e reposição
frontend/               interface (HTML/CSS/JS, sem build)
tests/                  testes unitários e de integração
config/gpi.json         porta, pasta de dados, proxy, ca_bundle, sincronização automática
docs/                   TI.md (rede e segurança), INTEGRACOES.md, METODOLOGIA.md, modelo de importação
scripts/                build_portable.ps1
data/                   criado na execução: banco, logs, backups
```
