# Meta — permissões dos módulos Páginas, Instagram e Biblioteca de Anúncios (GPI v0.9)

## Por que aparece "Invalid Scopes: pages_show_list, pages_read_engagement"

O Login básico funciona (etapas 1–10 do assistente em ✓, `/me` respondendo). O problema está nos **casos de uso** do
app `1663502878474287`. Pela documentação oficial da Meta ([Create an App](https://developers.facebook.com/documentation/development/create-an-app.md)):

* o caso de uso **"Authenticate and request data from users with Facebook Login"** é **incompatível** com
  **"Manage everything on your Page"**;
* casos de uso **não podem ser removidos** depois que o app é criado; ao adicionar, só aparecem os compatíveis.

Como o app foi criado com o caso de uso de Login, a Meta nunca aceitará as permissões de Páginas nele — e recusa na
própria tela do Facebook (o GPI não recebe esse erro). Colocar o escopo na URL não resolve.

## A solução: dois apps

| App | Para quê | Situação |
|---|---|---|
| **App de Login** (`1663502878474287`, o atual) | Login básico (`public_profile`) | **não mexa** — continua funcionando |
| **App de negócios** (novo) | Páginas, Instagram e Biblioteca de Anúncios | criar no painel da Meta |

O GPI não cria apps na sua conta. Passo a passo:

1. developers.facebook.com → **Meus apps → Criar app** → tipo **Empresa (Business)**.
2. Casos de uso: **Manage everything on your Page** e **Instagram → API with Facebook Login for Business** (é a
   variante que oferece busca de hashtags). Conecte o app a um portfólio empresarial se a Meta pedir.
3. **Configurações → Básico**: Domínios do app `samuelseveriano.github.io`; política de privacidade.
4. **Login do Facebook for Business → Configurações**: URI de redirecionamento
   `https://samuelseveriano.github.io/GPI/oauth/meta/` (a mesma do app de Login).
5. **Funções do app**: sua conta como administradora (em modo de desenvolvimento só quem tem função consegue entrar).
6. No GPI: Central de Integrações → **Meta — app de negócios**: App ID e App Secret do app NOVO (o GPI recusa o mesmo
   App ID do app de Login).
7. Assistente Meta → **Conectar — Páginas do Facebook** → **Diagnosticar módulos**.

## O que o diagnóstico por módulo mostra

Para Páginas, Instagram e Anúncios: app usado, caso de uso exigido, permissões necessárias × concedidas × recusadas,
conta ou Página associada, resultado da consulta real, erro oficial da Meta (código e mensagem) e a ação recomendada.

| Estado | Quando |
|---|---|
| **Conectado** | token com as permissões **e** consulta real bem-sucedida |
| **Sem permissão** | permissão recusada na tela da Meta, ausente no caso de uso, ou token inválido (código 190) |
| **Aprovação necessária** | permissão concedida, mas a Meta exige revisão/recurso (código 10 / 200–299) |
| **Configuração incompleta** | app de negócios ausente, módulo não autorizado, conta sem Página, Instagram não vinculado |
| **Não suportado** | consulta não suportada pela API (código 100) |
| **Erro de rede** | a Meta não respondeu |
| **Limite de uso** | códigos 4/17/32/613 |

## Requisitos de cada módulo

* **Páginas** — `pages_show_list`, `pages_read_engagement`. Acesso padrão vale para Páginas que **você administra**.
  Páginas de terceiros exigem o recurso *Page Public Content Access* (revisão do app + verificação da empresa). O GPI
  lista só as Páginas que a conta administra (`/me/accounts`).
* **Instagram** — Instagram API with **Facebook Login**: `instagram_basic` + `pages_show_list` + `pages_read_engagement`;
  conta **profissional** (Empresa ou Criador) vinculada a uma Página; o GPI usa o **ID numérico** da conta, não o @nome.
  Busca de hashtags exige o recurso **Instagram Public Content Access** (revisão do app) e é limitada a **30 hashtags
  distintas por 7 dias**. O diagnóstico usa `recently_searched_hashtags`, que não consome essa cota. A *Instagram API
  with Instagram Login* (`instagram_business_*`) não oferece busca de hashtags — por isso não é usada.
* **Biblioteca de Anúncios** — endpoint `ads_archive`; exige confirmação de identidade e acesso à API da Biblioteca.
  `ads_read` sozinho não garante acesso. Anúncios **comerciais** só existem para países da **União Europeia**: não são
  evidência do mercado brasileiro. Sem acesso, o módulo fica **Aprovação necessária** — o GPI não faz scraping.
