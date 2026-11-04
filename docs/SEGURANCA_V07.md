# GPI v0.7 — Auditoria de segurança

Data: 03/11/2026 · branch `feature/gpi-v0.7` · base: `feature/gpi-v0.6.1` (009f32f).

## 1. Varredura de segredos (repositório e histórico)
| Ferramenta | Escopo | Resultado |
|---|---|---|
| `scripts/secret_scan.py` (regras para chaves Google, client secret OAuth, refresh token, GitHub, AWS, Slack, Meta, Mercado Livre, JWT, chaves privadas PEM, PFX em base64 e atribuições `secret/token/senha` de alta entropia; arquivos proibidos: `.sqlite/.db/.gguf/.pfx/.p12/.pem/.key/.env/credentials*.json`) | árvore atual + `git log -p --all` (50 commits, todas as branches) | **0 segredos, 0 arquivos proibidos** |
| Gitleaks v8.30.1 (regras padrão, `--redact`), no GitHub Actions | histórico completo (`fetch-depth: 0`) | 1ª execução: 2 achados `generic-api-key` em testes (`tests/test_v061.py:96`, `tests/test_v07_security.py:176`), ambos valores fictícios de teste (`ABCDEF123456`, `AUTHCODE…`) → incluídos na lista de exceções; execuções seguintes: **0 achados** |

Nenhuma credencial real foi encontrada; não há o que revogar nem motivo para reescrever o histórico. O relatório do
Gitleaks é publicado sem valores (`--redact`) e o resumo do workflow mostra só regra, arquivo, linha e commit.

## 2. Servidor local (127.0.0.1:8765)
| Item | Situação |
|---|---|
| Interface de rede | só `127.0.0.1` (teste `test_server_binds_loopback_only`); nunca `0.0.0.0` |
| DNS rebinding | cabeçalho `Host` restrito a `127.0.0.1`/`localhost` (403 caso contrário) |
| CSRF | POST/PUT/DELETE exigem `X-GPI: 1` (força preflight) e `Origin` do próprio GPI; `/api/shutdown` exige token local |
| CORS | nenhum `Access-Control-Allow-Origin` é emitido |
| XSS | **novo:** Content-Security-Policy `script-src 'self'` (sem inline/eval), `object-src 'none'`, `frame-ancestors 'none'`; o front-end escapa dados com `escH`; a página de retorno OAuth antiga agora escapa HTML |
| Outros cabeçalhos | `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, COOP/CORP `same-origin`, `Permissions-Policy` |
| Tamanho de corpo | **novo:** `BodyLimit` (2 MB padrão; 50 MB importação; 12 MB anexos; 42 MB tabela NCM; 310 MB dados Anatel), inclusive sem `Content-Length` → 413 |
| Uploads | anexos: extensão + assinatura do arquivo, 10 MB/arquivo, 30 MB/análise, recusa macros (`vbaProject.bin`), ActiveX, executáveis, HTML/JS/SVG, scripts; nome higienizado; arquivo salvo pelo hash (sem caminho do usuário) |
| Path traversal | arquivos estáticos via Starlette `StaticFiles`; downloads de relatórios só dentro da pasta de relatórios; nomes de manifesto do pacote de IA reduzidos ao nome base |
| SQL injection | consultas parametrizadas; nomes de colunas vêm de listas fixas |
| SSRF | **novo:** URLs informadas pelo usuário (feeds RSS) recusam esquemas ≠ http/https, credenciais na URL, loopback, redes privadas, link-local (metadados de nuvem 169.254.169.254), multicast; o DNS é conferido no momento da coleta; o atualizador regulatório só lê domínios governamentais |
| Injeção em planilhas | **novo:** `safe_cell` em CSV/XLSX (=, +, -, @ no início) |

## 3. Armazenamento e logs
* Credenciais: DPAPI do Windows (usuário atual), arquivo separado do banco; nunca enviadas ao front-end (só nomes de
  campos e valores mascarados); tokens nunca em parâmetros de URL do GPI.
* Mercado Livre: Secret Key e refresh token ficam no cofre DPAPI; o refresh token de uso único é gravado a cada renovação,
  com renovação serializada (sem corrida entre threads).
* **Novo:** `RedactFilter` em todos os handlers de log remove tokens Bearer, `access/refresh_token`, `client_secret`,
  `code`/`code_verifier`, chaves Google `AIza…`, `GOCSPX-…`, tokens Meta `EAA…`, Mercado Livre `APP_USR-…`, JWT — inclusive em
  tracebacks. Testado em `test_log_sanitization`.
* Anexos de fornecedores e documentos internos ficam em `%LOCALAPPDATA%\GPI\compliance\anexos` (fora do repositório).
* `.gitignore` e gancho `scripts/hooks/pre-commit` (ativar com `git config core.hooksPath scripts/hooks`) bloqueiam bancos,
  relatórios gerados, modelos GGUF, chaves e `.env`.

## 4. GitHub
| Controle | Situação |
|---|---|
| Secret scanning + push protection | **já ativos** no repositório (conferido pela API) |
| Dependabot (atualizações) | **preparado**: `.github/dependabot.yml` (pip e GitHub Actions, semanal) |
| Alertas/atualizações de segurança do Dependabot | **pendente — dono do repositório**: Settings → Code security → Dependabot alerts / security updates (a API de configurações não é acessível a partir desta sessão) |
| CodeQL | **ativo** (`security.yml`, Python e JavaScript, consultas `security-extended`) |
| Revisão de dependências em PR | **ativo** (`actions/dependency-review-action`, falha em severidade alta e em AGPL/SSPL) |
| pip-audit e licenças | **ativo** (`security.yml`); 1ª execução: nenhuma vulnerabilidade conhecida |
| Ações fixadas por SHA | security.yml, local-ai.yml e pages.yml; windows-build.yml usa tags principais (v5/v6) — Dependabot acompanha |
| Permissões dos workflows | `contents: read` em todos; `security-events: write` só no CodeQL; `pages: write`/`id-token: write` só no job de publicação |
| Código não confiável com segredos | nenhum workflow usa `pull_request_target`; builds de PR não recebem segredos; os segredos opcionais de assinatura só existem no job de build em push |
| Proteção de branch / revisão obrigatória | **pendente — dono do repositório** (recomendação abaixo); `CODEOWNERS` marca caminhos críticos |
| SECURITY.md / política de divulgação | **criado** (relato privado pelo GitHub) |

Recomendação de proteção da `main`: exigir PR, checks `windows-build` (jobs 1 e 3) e `security` (gitleaks, CodeQL),
bloquear force-push e exclusão; com um único mantenedor, 0 aprovações obrigatórias (o autor não pode aprovar o próprio PR)
e "Require review from Code Owners" quando houver um segundo revisor.

## 5. Dependências e pacote Windows
* SBOM CycloneDX (`relatorios/sbom.cdx.json`) gerado do ambiente empacotado no build.
* Nova dependência: `pypdf` (BSD) para ler texto de anexos PDF.
* Nenhum download de código em tempo de execução: a IA local só usa o pacote copiado pelo usuário/TI, com SHA-256 conferido;
  tabela NCM e dados da Anatel são dados (JSON/CSV), nunca executados.
* Defender, SHA-256 do exe/zip, relatório de segurança e assinatura opcional seguem como na v0.6.1; nada desativa
  Defender/SmartScreen e não há packers/ofuscação.

## 6. IA local (seção 19)
Sem rede (servidor só em 127.0.0.1, porta aleatória, chave por sessão; nenhum argumento de download), sem comandos do
sistema, sem ferramentas, sem credenciais, sem arquivos fora da pasta do modelo; documentos recuperados entram como dados
higienizados; a verificação remove normas/certificados inventados e afirmações de liberação; testes em `tests/test_v07_ai.py`.
