# Mercado Livre — OAuth com Redirect URI HTTPS (GPI v0.7)

> A página HTTPS (pasta `pages/`) é publicada pelo workflow `pages` a partir da `main`. A conclusão do login no
> computador (rota local `/oauth/mercadolivre/retorno` e troca do código por token) faz parte do **GPI v0.7** (PR #3).

## 1. O que a documentação oficial diz (consultada em 03/11/2026)
| Ponto | Situação oficial | Fonte |
|---|---|---|
| Fluxo | Somente **Authorization Code** (server side). `grant_type` aceitos: `authorization_code` e `refresh_token`. | [Autenticação e autorização](https://developers.mercadolivre.com.br/en_us/authentication-and-authorization) |
| Device Authorization Grant | **Não documentado** — não foi usado. | idem |
| Redirect URI | "**it is mandatory to use the HTTPS protocol**"; deve ser **idêntico** ao cadastrado e **estático** (dados extras vão no `state`). | [Registro da aplicação](https://developers.mercadolibre.com.uy/en_us/register-your-application) e página acima |
| PKCE | Opcional por aplicação ("Use PKCE"), recomendado; com PKCE ativo, `code_challenge`/`code_verifier` são obrigatórios. `S256` usado (plain não recomendado). | idem |
| `state` | Recomendado; o Mercado Livre não o valida — a validação é do integrador. | idem |
| Access token | 6 h (o exemplo da página mostra `expires_in: 10800`; o GPI usa o valor devolvido). | idem |
| Refresh token | **Uso único**, 6 meses; cada renovação devolve um novo. | idem |
| Erros | `invalid_client`, `invalid_grant`, `invalid_scope`, `invalid_request`, `unsupported_grant_type`, `local_rate_limited` (429), `forbidden` (403). | idem |
| Requisitos da conta | login com a conta principal (não colaborador), KYC válido. | idem |

Conclusão: `http://127.0.0.1:8765/oauth/callback` não é aceito; não existe fluxo nativo para aplicativos instalados sem
HTTPS. O erro "403 ERROR — CloudFront — Request blocked" é um bloqueio na borda (CDN/WAF) do Mercado Livre; com a
URI http/IP local ele é esperado, e o GPI não tenta contorná-lo.

## 2. Arquitetura adotada — página de retorno HTTPS estática (GitHub Pages)
```
GPI (127.0.0.1) ─abre─▶ auth.mercadolivre.com.br/authorization?redirect_uri=https://samuelseveriano.github.io/GPI/oauth/mercadolivre/&state=<porta>.<aleatório>&code_challenge=…
                                            │ login no site oficial (o GPI não vê a senha)
                                            ▼
           página HTTPS estática (sem segredos, sem rede) ── navegação ──▶ http://127.0.0.1:<porta>/oauth/mercadolivre/retorno#code=…&state=…
                                                                                   │ POST mesma origem (X-GPI)
                                                                                   ▼
                                    GPI troca o código por token com code_verifier + Secret Key (só existem no GPI)
```

Avaliação dos critérios da especificação:
1. **Mercado Livre aceitar o domínio** — `github.io` é HTTPS público; a aceitação final é feita pelo DevCenter ao salvar a
   aplicação (**depende do usuário/Mercado Livre** — não pôde ser testado sem a conta). Se o DevCenter exigir apenas
   raiz de domínio, use um repositório `samuelseveriano.github.io` (raiz) ou o domínio próprio (seção 4).
2. **Compatível com as políticas** — é o Authorization Code documentado, com Redirect URI HTTPS estático e `state`.
3. **Sem segredos em página pública** — a página é HTML/JS estático (`pages/`), sem chaves; CSP `default-src 'none'`.
4. **Entrega segura do código** — o código vai no fragmento `#` (não é enviado em requisições nem fica em logs de
   servidor), é removido da barra de endereço/histórico, e sozinho é inútil: a troca exige o `code_verifier` (PKCE)
   e a Secret Key, que nunca saem do computador.
5. **CSRF, reutilização e interceptação** — `state` com 256 bits aleatórios, uso único, expira em 10 min; código de
   uso único no Mercado Livre; PKCE S256 impede que um código interceptado seja trocado por terceiros.
6. **Restrições do navegador** — é uma **navegação de nível superior** HTTPS→`http://127.0.0.1` (não uma requisição
   em segundo plano), portanto não é bloqueada como conteúdo misto; navegadores com política de acesso à rede local
   podem pedir confirmação. Se bloquear, a página mostra o código para **colar no GPI** (mesmas verificações).

Não é redirecionador aberto: o destino é sempre `127.0.0.1`, com porta numérica (1024–65535) extraída do `state`.
O Client Secret e o Refresh Token nunca passam pela página. A verificação TLS nunca é desativada.

## 3. Passo a passo para conectar
1. O dono do repositório ativa o GitHub Pages **uma vez**: *Settings → Pages → Source: GitHub Actions*; depois
   *Actions → pages → Run workflow* (publica só a pasta `pages/`). Conferir que
   `https://samuelseveriano.github.io/GPI/oauth/mercadolivre/` abre a página "GPI — retorno da autorização".
2. DevCenter → Minhas aplicações → sua aplicação: **Redirect URI** = `https://samuelseveriano.github.io/GPI/oauth/mercadolivre/`
   (idêntico, com a barra final); ativar **PKCE**; escopos leitura e acesso offline.
3. GPI → Central de Integrações → Mercado Livre: App ID e Secret Key → *Salvar dados do aplicativo* → *Entrar com
   Mercado Livre*. Após o login, o navegador volta ao GPI e mostra "Mercado Livre conectado".
4. *Diagnosticar integração*: App ID, Secret Key, Redirect URI, token + `/users/me` (consulta real) e `/trends/MLB`
   (consulta real).

## 4. Alternativa: callback HTTPS em domínio próprio
Se o DevCenter recusar `github.io`, publique a mesma pasta `pages/` em qualquer hospedagem estática HTTPS sob domínio
controlado (ex.: domínio próprio apontando para o GitHub Pages — custo do domínio, ~R$ 40/ano em `.com.br`; ou
Cloudflare Pages/Netlify no plano gratuito). Não é necessário servidor com código: a página não processa nada.
Depois, informe o novo endereço no campo *Redirect URI HTTPS* do GPI (mesmo valor do DevCenter).

## 5. Estado da validação
| Item | Situação |
|---|---|
| Construção da URL, `state`, PKCE S256, troca código→token, renovação (uso único, concorrência), `/users/me`, `/trends/MLB`, persistência, CloudFront | **teste automatizado (simulado)** — `tests/test_v07_mercadolivre.py` |
| Lógica da página HTTPS (validação, anti-redirecionamento aberto) | **teste automatizado** em Node.js |
| Autorização real, aceitação do domínio no DevCenter, tendências reais do Brasil | **pendente — depende do App ID/Secret do usuário** e da ativação do GitHub Pages |
| Windows | rotas incluídas no executável e no teste de fumaça (página de retorno local) |

Se o CloudFront continuar bloqueando com a URI HTTPS, o diagnóstico mostra a mensagem com as causas possíveis; o que
resta depende do suporte do Mercado Livre (informar data/hora e o ID de requisição da página de erro).
