# GPI — Global Product Intelligence · v0.3 (Fase 3)

Plataforma **local e autônoma** de inteligência de produtos: coleta dados de fontes públicas e
autorizadas, analisa opiniões de consumidores, acompanha o YouTube, compara produtos, gera
previsões e ranqueia oportunidades — sem planilhas e sem configuração. Todas as fórmulas estão na
página *Metodologia* e são verificadas por testes.

- **Usuário final:** veja `MANUAL.md` (abrir com dois cliques em `GPI.exe`).
- **TI:** `docs/TI.md` (rede, arquivos, segurança). **Build do executável:** `docs/BUILD.md`.
- **Integrações e o que foi validado:** `docs/INTEGRACOES.md`.

> **Situação do executável Windows:** o `GPI.exe` **ainda não foi gerado** — o ambiente de
> desenvolvimento não permitia (Linux, sem rede, sem PyInstaller). O projeto inclui o
> inicializador pronto, a especificação do PyInstaller e um workflow do GitHub Actions que gera e
> testa o `GPI-Windows-Portable.zip`. Veja `docs/BUILD.md`.

## Executar

- **Usuário final (Windows):** extrair `GPI-Windows-Portable.zip` e clicar duas vezes em `GPI.exe`.
- **Desenvolvimento:** `pip install -r requirements.txt` (opcional: `-r requirements-optional.txt`) e
  `Start_GPI.bat` (Windows) ou `./start_gpi.sh` (Linux/macOS). Dados em `data/`.
- **Testes:** `pip install -r requirements-dev.txt` e `python -m pytest tests`.

## Fase 3 — o que foi implementado

| Recurso | Situação |
|---|---|
| Inicializador do `GPI.exe`: integridade (SHA-256), dados em `%LOCALAPPDATA%\GPI`, porta, navegador, janela de controle, encerramento seguro, `--smoke/--check/--stop` | ✅ testado (Linux) · ⚠️ `.exe` não gerado |
| PyInstaller one-folder + workflow Windows com testes de inicialização e validação real de conectores | ✅ escrito · ⚠️ não executado |
| Central de Integrações: conectar, testar, sincronizar, desconectar; chave de API, Client ID, OAuth 2.0 com PKCE, opt-in de termos, links oficiais para aprovação | ✅ testado (com respostas simuladas) |
| Cofre de credenciais (DPAPI no Windows; arquivo 0600 nos demais) | ✅ testado no Linux · ⚠️ DPAPI só roda no Windows |
| Proteção CSRF (cabeçalho obrigatório + Origin) | ✅ testado |
| YouTube Data API (quota, retenção de 30 dias, classificação por tipo de vídeo) | ✅ testado com respostas simuladas |
| Reddit, RSS (6 sites), Google Notícias (opt-in) | ✅ testado com respostas simuladas |
| Trustpilot, Reclame Aqui, comparadores de preço | ✅ restritos, com motivo (sem raspagem) |
| Review Intelligence: sentimento pt/en, 11 aspectos, alvo da reclamação, exemplos com link | ✅ testado (≥ 85% em 30 frases rotuladas) |
| Comparador de produtos com fonte e confiabilidade por atributo | ✅ testado |
| SARIMA, LightGBM, XGBoost no AutoML (se instalados) | ✅ código pronto · ⚠️ testes rodam só no CI (bibliotecas ausentes aqui) |
| Score com cobertura e confiança separadas; ausência de fonte não penaliza; 8 rankings novos | ✅ testado |
| 15 páginas no menu (Visão Geral, Radar Global, Brasil, China, Marketplaces, YouTube, Reviews, Comparador, ML, Forecasting, Clustering, Ranking, Central de Integrações, Saúde das Fontes, Metodologia) | ✅ verificado no navegador |

## Fase 2 — o que foi implementado

| Recurso | Situação |
|---|---|
| Conectores públicos: BCB PTAX, Wikimedia (pt/en/zh), Comex Stat (todas as posições SH4), IBGE PMC, UN Comtrade | ✅ implementados e testados com respostas simuladas · ⚠️ coleta real a confirmar na 1ª execução |
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
- SARIMA/SARIMAX, LightGBM e XGBoost: as bibliotecas não estavam disponíveis no ambiente de
  build para testes; o AutoML usa Holt-Winters/ETS e os modelos do scikit-learn. Podem ser
  adicionados como candidatos sem mudar a arquitetura.
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
Resultado nesta entrega: **89 testes aprovados e 3 ignorados** (modelos opcionais sem biblioteca instalada).

## Formato de importação
Uma linha por venda (ou por dia/SKU). Exemplo em `docs/modelo_importacao.csv`.
Obrigatórias: data, quantidade e SKU ou produto. Opcionais: categoria, preço unitário.

## Estrutura
```
backend/gpi/            servidor, banco, importação, regras
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
