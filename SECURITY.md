# Política de segurança do GPI

## Versões com suporte
| Versão | Suporte de segurança |
|---|---|
| 0.7.x | sim |
| 0.6.x | somente correções críticas até a publicação da 0.7 |
| < 0.6 | não |

## Como relatar uma vulnerabilidade
**Não abra issue pública** para vulnerabilidades. Use o recurso privado do GitHub:
*Security → Advisories → Report a vulnerability* (relato privado de vulnerabilidade) neste repositório.

Inclua: versão do GPI, sistema operacional, passos para reproduzir, impacto esperado e, se possível, uma prova de
conceito mínima. **Nunca envie credenciais, tokens, bancos de dados, relatórios comerciais ou documentos de
fornecedores reais** no relato — substitua por valores fictícios.

Prazos de referência (projeto mantido por uma pessoa, sem SLA contratual):
* confirmação de recebimento: até 5 dias úteis;
* avaliação inicial e classificação de severidade: até 10 dias úteis;
* correção de severidade alta/crítica: assim que possível, com aviso no advisory.

Divulgação coordenada: pedimos que o relato não seja publicado antes da correção ou de 90 dias, o que vier primeiro.

## Escopo
* Aplicação local (servidor em `127.0.0.1:8765`, interface web, banco SQLite, armazenamento de credenciais com DPAPI).
* Pacote Windows (`GPI.exe`, ZIP portátil, pacote de modelo de IA local).
* Workflows do GitHub Actions deste repositório.
* Página de retorno OAuth publicada no GitHub Pages (`docs/oauth/`).

Fora do escopo: serviços de terceiros (Google, Meta, Mercado Livre, TikTok etc.), configurações do computador do
usuário e políticas corporativas.

## O que o GPI faz para se proteger (resumo)
* Servidor só em loopback; Host permitido (anti DNS rebinding), cabeçalho anti-CSRF, verificação de Origin, CSP sem
  scripts inline, limite de tamanho de corpo, proteção contra SSRF em URLs informadas pelo usuário.
* Credenciais cifradas com DPAPI (usuário do Windows); nunca enviadas ao front-end; logs sanitizados automaticamente.
* IA local sem acesso à rede, a comandos do sistema ou a arquivos fora das pastas autorizadas.
* Varredura de segredos (Gitleaks + script próprio) em todo o histórico, CodeQL, pip-audit, Dependabot e revisão de
  dependências; ações do GitHub fixadas por SHA; workflows com permissão mínima e sem segredos em pull requests.
* Ganchos locais: `git config core.hooksPath scripts/hooks` ativa a varredura antes de cada commit.

Detalhes e resultados da auditoria: [docs/SEGURANCA_V07.md](docs/SEGURANCA_V07.md).

## Se uma credencial for exposta
Apagar o arquivo ou o commit **não revoga** a credencial. Revogue/rotacione imediatamente no provedor
(Google Cloud, Meta, Mercado Livre, TikTok…), depois remova a referência do código e só então avalie limpeza de
histórico — reescrever histórico compartilhado exige autorização do responsável e afeta todos os clones e PRs.
