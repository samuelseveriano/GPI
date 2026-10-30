# GPI — Informações para a equipe de TI

## Resumo
Aplicação web **local**. Um processo Python serve a interface e a API em
`http://127.0.0.1:8765` (loopback). Nenhuma porta é exposta à rede.

| Item | Valor |
|---|---|
| Privilégios de administrador | **não** necessários |
| Instalação / registro do Windows | nenhum (pasta portátil, copiar e executar) |
| Serviços do Windows, Docker, WSL | não usa |
| Porta | TCP 8765 em 127.0.0.1 (se ocupada, tenta 8766–8774) |
| Conexões de saída | somente HTTPS (443) de leitura para as APIs públicas listadas abaixo |
| Telemetria | inexistente |
| Interpretador | Python oficial "embeddable" (python.org, assinado pela PSF) em `portable\python` |
| Banco de dados | arquivo local `data\gpi.sqlite` (SQLite embutido) ou `data\gpi.duckdb` se o pacote DuckDB estiver presente |

## Arquivos gerados (todos dentro da pasta do programa)
- `data\gpi.sqlite` (+ `-wal`, `-shm`) — banco local
- `data\logs\gpi.log` — log rotativo (2 MB × 5); não registra conteúdo de planilhas
- `data\backups\` — backups manuais criados pelo usuário
- `data\gpi.run.json` e `data\shutdown.token` — porta/PID e token de encerramento; apagados ao sair

## Proteções
- Servidor ligado apenas a `127.0.0.1`.
- Requisições cujo cabeçalho `Host` não seja `127.0.0.1`/`localhost` são recusadas (HTTP 403) — mitiga DNS rebinding.
- Encerramento remoto exige token aleatório gravado localmente (usado por `Stop_GPI.bat`).
- Importação: somente `.csv`/`.xlsx`, limite de 50 MB, validação de assinatura do XLSX, sem execução de macros (openpyxl não executa VBA).
- Interface sem recursos externos (sem CDN, fontes ou scripts de terceiros).

## Execução
- Iniciar: `Start_GPI.bat` (abre o navegador padrão).
- Encerrar: fechar a janela ou `Stop_GPI.bat`.
- Diagnóstico: `Start_GPI.bat --check` (verifica dependências, pasta gravável, porta).

## Se a política bloquear
Se a execução de `python.exe` a partir de pastas de usuário for bloqueada por
AppLocker/WDAC/EDR, o programa **não tenta contornar**. Opções: liberar o hash/assinatura
do Python embeddable e a pasta do GPI, ou usar o MODO B (servidor web aprovado — previsto).

## Modo B (servidor aprovado) — preparação
O mesmo backend pode ser servido por um servidor interno atrás de proxy reverso com HTTPS
e autenticação corporativa. Nesta versão (fase 1) ainda **não há autenticação própria**:
não exponha o processo diretamente na rede.

## Conexões externas (Fase 2)

Todas são **HTTPS, porta 443, somente leitura**, feitas pelo próprio processo do GPI. Nenhum
dado da empresa é enviado (as requisições contêm apenas parâmetros de consulta como ano,
moeda ou título de artigo).

| Endereço | Uso | Método | Volume aproximado |
|---|---|---|---|
| `olinda.bcb.gov.br` | câmbio PTAX (Banco Central) | GET | ~30 na 1ª vez; ~3/semana |
| `en.wikipedia.org` | nomes dos produtos em pt/zh (links interlínguas) | GET | ~46 a cada 90 dias |
| `wikimedia.org` | visualizações mensais de páginas | GET | ~140/semana |
| `api-comexstat.mdic.gov.br` | importações por NCM/SH4 (MDIC) | POST (consulta) | ~22 na 1ª vez; ~4/semana |
| `servicodados.ibge.gov.br` | Pesquisa Mensal de Comércio | GET | ~3/semana |
| `comtradeapi.un.org` | comparação internacional | GET | ~18 na 1ª vez; ~6/semana |
| `api.mercadolibre.com`, `auth.mercadolivre.com.br` | somente se o Mercado Livre for conectado (OAuth PKCE) | GET/POST | 1/semana |
| `www.googleapis.com` | YouTube Data API — somente se uma chave for informada | GET | até o limite diário configurado |
| `www.reddit.com`, `oauth.reddit.com` | Reddit — somente se um Client ID for informado | GET/POST | ~25/semana |
| `news.google.com` | Google Notícias — somente após aceite dos termos | GET | ~15/semana |
| Sites de RSS (padrão: tecnoblog.net, canaltech.com.br, olhardigital.com.br, rss.tecmundo.com.br, www.theverge.com, www.engadget.com — lista editável) | manchetes | GET | 1 por feed/dia |

Intervalo mínimo entre requisições ao mesmo host: 0,2 s a 6 s (Comex Stat). Respostas ficam em
cache em `data/cache/`.

**Proxy corporativo:** usa `HTTPS_PROXY` do sistema ou `"proxy": "http://proxy.empresa:8080"` em
`config/gpi.json`. **Certificados:** se a inspeção TLS da empresa ou a cadeia ICP-Brasil não for
reconhecida, informe em `"ca_bundle"` o caminho de um arquivo PEM fornecido pela TI. A verificação
TLS **nunca** é desativada.

Para desligar toda conexão externa: `"auto_sync": false` em `config/gpi.json` (o botão
"Atualizar agora" continua disponível para uso manual).

## Arquivos adicionais
- `data/cache/` — cache das respostas das APIs (pode ser apagado a qualquer momento)
- Banco: tabelas `market_series`, `market_obs`, `source_status`, `sync_jobs`, `sync_runs`,
  `products`, `auto_forecasts`, `analysis_results` (migração v2, aplicada automaticamente)

## Recursos
A primeira análise completa (previsões automáticas) usa 1 núcleo de CPU por alguns minutos;
há um limite de tempo (`automl_budget_s`, padrão 420 s) e o restante continua nas
sincronizações seguintes. As séries cujos dados não mudaram não são retreinadas.

## Versão Windows portátil (Fase 3)
- `GPI.exe` (PyInstaller, one-folder, sem console). Não instala nada, não altera registro, não cria serviço.
- Programa: a pasta extraída (somente leitura em uso normal). Integridade verificada a cada abertura por `manifest.json` (SHA-256).
- Dados do usuário: `%LOCALAPPDATA%\GPI` (banco, logs, cache, `config.json`, `credentials.bin`). Variável `GPI_DATA_DIR` permite outro local; `portable.flag` ao lado do exe usa a pasta `dados`.
- Credenciais: criptografadas com a DPAPI do Windows (CryptProtectData, escopo do usuário).
- Proteções HTTP adicionais: chamadas que alteram estado exigem cabeçalho `X-GPI` e rejeitam `Origin` externo (CSRF); `X-Frame-Options: DENY`.
- Encerramento: fechar a janela "GPI em execução", `GPI.exe --stop` ou *Sistema → Encerrar*. Conexões abertas do navegador não impedem o encerramento (limite de 5 s).
- Diagnóstico: `GPI.exe --check` não funciona com console oculto; use o log `%LOCALAPPDATA%\GPI\logs\gpi.log`.
