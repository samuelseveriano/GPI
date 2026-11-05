# Meta — correção do "Retorno inválido ou incompleto" (GPI v0.8.2)

## Causa

Depois do "Continuar como Samuel", a Meta redireciona para
`https://samuelseveriano.github.io/GPI/oauth/meta/?code=…&state=…`. A página de retorno (`pages/oauth/meta/relay.js`)
só aceitava códigos de **8 a 300 caracteres**; o backend aceitava até 1.024. A Meta não documenta o tamanho do código
("an encrypted string unique to each login request") e os códigos do Login do Facebook passam de 300 caracteres. O
`state` gerado pelo GPI (`8765.` + 43 caracteres) passava na validação — o único teste que podia falhar era o do
código. Reproduzido: o relay antigo recusa códigos de 301, 412 e 2.048 caracteres; o novo aceita.

## Correção

* **relay.js** e **backend** com a mesma regra: 8–2.048 caracteres seguros para URL (`A–Z a–z 0–9 - _ . ~`).
* Cada recusa mostra um **código de diagnóstico** e o **tamanho** do código recebido — nunca o valor:

| Código | Mensagem |
|---|---|
| M01 | Meta não retornou um código de autorização. |
| M02 | O código recebido não corresponde ao formato esperado. |
| M03 | Parâmetro de segurança OAuth não recebido. |
| M04 | A solicitação de autorização não corresponde à sessão iniciada. |
| M05 | A autorização expirou. Inicie uma nova conexão. |
| M06 | Meta recusou a autorização. |
| M07 | O navegador não conseguiu concluir a comunicação com o GPI. |
| M08 | O código foi recebido, mas não foi possível concluir a autenticação. |
| M09 | Esta autorização já foi utilizada (reutilização bloqueada). |
| M10 | O token recebido pertence a outro aplicativo da Meta. |
| M11 | A Meta emitiu um token inválido. |

* O **backend** valida tudo de novo (não confia no JavaScript da página): state presente, formato, sessão, expiração
  (10 min) e uso único; distingue expirado (M05), reutilizado (M09) e desconhecido (M04, inclusive GPI reiniciado).
* O token só é gravado depois de conferido na Meta (`debug_token`): **válido** e emitido para **o App ID configurado**
  (`1663502878474287`). Token de outro app é descartado (M10).
* O assistente mostra as 10 etapas pedidas com status, resultado, possível causa e ação. Páginas, Instagram e Biblioteca
  de Anúncios ficam bloqueados até o Login básico ser **validado com uma consulta real (/me)**.

## Segurança do retorno pelo GitHub Pages

O código chega à página pública pela **query da URL**. Isso significa que ele pode ficar registrado nos logs da
infraestrutura do GitHub Pages/CDN e, por um instante, no histórico do navegador (a página remove a query logo ao
abrir). O `Referer` é bloqueado (`no-referrer`) e a página não carrega nada de terceiros. Por que o risco é aceitável:

* o código **sozinho não serve**: a troca exige o **App Secret**, que só existe no GPI (DPAPI);
* o código expira em minutos e é de **uso único**;
* o `state` é de uso único, com 256 bits, e ligado ao GPI que iniciou a conexão.

Alternativa mais restritiva, compatível com a Meta: modo **localhost** (`http://localhost:<porta>/oauth/callback`),
aceito pela Meta **somente com o app em modo de desenvolvimento** — o código não passa por nenhum servidor público.
O PKCE da Meta existe apenas no fluxo OIDC (marcado pela Meta como "em teste", exige `openid` e `nonce`); não foi
ativado para não trocar um fluxo estável por um em teste.

## Publicação

A página `https://samuelseveriano.github.io/GPI/oauth/meta/` só é atualizada quando o PR for **mesclado na `main`**
(o workflow `pages` publica apenas a partir da `main`). Até lá, a página publicada continua com o limite de 300.

## Passo a passo

1. **App ID** — developers.facebook.com → Meus apps → app → Configurações → Básico: `1663502878474287`. No GPI, o
   assistente mostra "App ID que o GPI enviará"; precisam ser iguais.
2. **Domínio** — Configurações → Básico → **Domínios do app**: `samuelseveriano.github.io`.
3. **URI OAuth** — Login do Facebook → Configurações → **URIs de redirecionamento do OAuth válidos**:
   `https://samuelseveriano.github.io/GPI/oauth/meta/` (exatamente, com a barra final).
4. **Login básico** — GPI → Central de Integrações → Assistente de conexão Meta → **Conectar — Login básico**.
5. **Callback** — se a página do GitHub mostrar um código M01–M06, a falha foi antes de chegar ao GPI; M07 = o
   navegador corporativo bloqueou o endereço local (use **Colar código**); M04/M05/M08–M11 aparecem no GPI.
6. **State** — o GPI aceita um retorno só uma vez e por até 10 minutos; não feche o GPI no meio do login.
7. **Autenticação** — **Verificar de novo**: etapas 8 (token conferido para este App ID) e 10 (consulta /me) em ✓.
8. **Permissões adicionais** — só depois do Login básico validado: **Conectar — Páginas/Instagram/Anúncios**.
9. **Instagram e Páginas** — o Instagram precisa ser conta **profissional** ligada a uma Página; o GPI usa o **ID
   numérico** da conta (não o @nome). Páginas de terceiros exigem o recurso *Page Public Content Access*.
10. **Aprovação da Meta** — `pages_read_engagement` (para não administradores), *Instagram Public Content Access* e
    `ads_read` (com identidade confirmada) dependem de revisão do app. A Biblioteca de Anúncios só devolve anúncios
    comerciais da **União Europeia** — não representam o mercado brasileiro.
