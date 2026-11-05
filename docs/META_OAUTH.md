# Conexão com a Meta (Facebook / Instagram) — GPI v0.8.1

## Por que dava erro

| Mensagem da Meta | Causa | Correção |
|---|---|---|
| **B** "Conexão insegura" / "não é seguro" | O GPI enviava `redirect_uri=http://127.0.0.1:<porta>/...`. O Login do Facebook exige HTTPS; `http` só é aceito para **`localhost`** e só com o app em modo de **desenvolvimento**. `127.0.0.1` é recusado. | Retorno HTTPS pelo GitHub Pages (padrão) ou `http://localhost` (modo dev). |
| **C** "O domínio desta URL não está incluído nos domínios do app" | O host do `redirect_uri` não estava em *Domínios do app*. | Adicionar `samuelseveriano.github.io` (ou `localhost`) em *Domínios do app*. |
| **A** "Aplicativo inativo" / "Login do Facebook indisponível" | Estado do app no painel da Meta (pendências de *Ações necessárias*, modo, papéis). O GPI não consegue alterar isso. | Resolver as pendências no painel; em modo de desenvolvimento, só quem tem papel no app consegue entrar. |
| App ID enviado ≠ App ID cadastrado | Ao trocar de app (`1855094518955679` → `1663502878474287`), credenciais e tokens antigos eram mesclados. | Trocar o App ID agora **apaga os tokens do app anterior**; o assistente compara o `app_id` do token (`debug_token`) com o App ID informado. |

## Como o retorno HTTPS funciona (sem expor segredo)

1. O GPI gera `state = <porta>.<aleatório>` (uso único, expiração curta) e abre a Meta com
   `redirect_uri=https://samuelseveriano.github.io/GPI/oauth/meta/`.
2. A página estática recebe `code` e `state` e os repassa **no fragmento (`#`)** para
   `http://127.0.0.1:<porta>/oauth/meta/retorno` — fragmentos não vão para logs de servidor.
   A página só aceita `state` no formato esperado e só redireciona para `127.0.0.1` (sem redirecionamento aberto).
3. O GPI local confere o `state` (CSRF / replay: consumido uma única vez) e troca o `code` pelo token **localmente**,
   com o App Secret guardado pelo DPAPI. O App Secret e os tokens **nunca** passam pela página pública.

A página só fica no ar depois que a branch for mesclada na `main` (o workflow `pages` publica apenas a partir da `main`).
Até lá, use o modo `localhost`.

## Passo a passo no painel da Meta

1. developers.facebook.com → Meus apps → app **1663502878474287**.
2. *Configurações → Básico*: confira App ID e App Secret; em **Domínios do app** adicione `samuelseveriano.github.io`
   (e `localhost`, se for usar o modo dev).
3. *Login do Facebook → Configurações*: em **URIs de redirecionamento do OAuth válidos** cadastre
   `https://samuelseveriano.github.io/GPI/oauth/meta/` (ou `http://localhost:8765/oauth/callback`).
4. Mantenha *Login no OAuth do cliente* e *Login no OAuth da Web* ativados; **não** desative "Forçar HTTPS".
5. Em modo de desenvolvimento, adicione sua conta em *Funções do app*.
6. No GPI: Integrações → Meta → informe App ID e App Secret → **Assistente de conexão**.

## Assistente (10 etapas, cada uma verificada na Meta)

App identificado · App ID validado · App Secret · redirect URI e domínio · autorização · token · token do mesmo app ·
perfil (`/me`) · Páginas (`/me/accounts`) · dados coletados. Estados possíveis: não configurado, configurado,
aguardando autorização, autorizado, permissão ausente, token de outro app, conectado com dados.

Módulos: login básico, Páginas, Instagram (exige conta Business ligada a uma Página) e Biblioteca de Anúncios
(anúncios comerciais só da União Europeia — não representam o Brasil; `ads_read` exige identidade confirmada).

**Pendente de validação real:** depende das suas credenciais e do estado do app no painel da Meta.
