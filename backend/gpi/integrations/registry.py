"""
Catálogo da Central de Integrações: o que cada fonte exige, como conectar e como testar.

Tipos:
  auto      — pública, sem credencial: conectada automaticamente
  api_key   — chave de API gratuita obtida pelo usuário no portal oficial
  client_id — ID de aplicativo registrado pelo usuário (sem senha)
  oauth     — OAuth 2.0 com PKCE (login na página oficial do provedor)
  optin     — fonte pública com termos de uso que pedem aceite explícito
  approval  — exige aprovação/contrato do provedor (o GPI informa onde solicitar)
"""
from __future__ import annotations

import base64
import time

from ..connectors.http import SourceError

REDIRECT_PATH = "/oauth/callback"

PROVIDERS = [
    {"id": "publicas", "nome": "Fontes públicas oficiais", "tipo": "auto",
     "conectores": ["bcb_ptax", "wikimedia", "comexstat", "ibge_pmc", "comtrade"],
     "descricao": "Banco Central, Comex Stat, IBGE, UN Comtrade e Wikimedia. Não exigem cadastro: conectadas automaticamente.",
     "permissoes": "Somente leitura de dados públicos. Nenhum dado da empresa é enviado."},
    {"id": "youtube", "nome": "YouTube Data API v3", "tipo": "api_key", "conectores": ["youtube"],
     "campos": [{"nome": "api_key", "rotulo": "Chave de API", "secreto": True}],
     "descricao": "Vídeos de review, unboxing, comparativos e lançamentos sobre os produtos identificados.",
     "permissoes": "A chave só permite ler dados públicos do YouTube. Cota gratuita padrão: 10.000 unidades/dia "
                   "(uma busca custa 100). O GPI limita o uso diário (configurável) e respeita as políticas de "
                   "dados do YouTube: os dados ficam em página própria e não são misturados com outras fontes.",
     "como_obter": "Google Cloud Console → criar projeto → ativar 'YouTube Data API v3' → Credenciais → Chave de API.",
     "link": "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
     "documentacao": "https://developers.google.com/youtube/v3/getting-started"},
    {"id": "reddit", "nome": "Reddit API", "tipo": "client_id", "conectores": ["reddit"],
     "campos": [{"nome": "client_id", "rotulo": "Client ID do aplicativo (tipo 'installed app')", "secreto": False},
                {"nome": "uso_autorizado", "rotulo": "Confirmo que o uso é não comercial ou que a empresa tem contrato com o Reddit",
                 "secreto": False, "checkbox": True}],
     "descricao": "Discussões e opiniões de consumidores para a análise de reviews.",
     "permissoes": "Acesso somente leitura a conteúdo público (sem login de usuário). O nível gratuito do Reddit é "
                   "para uso não comercial; uso comercial exige contrato com o Reddit.",
     "como_obter": "reddit.com/prefs/apps → 'create app' → tipo 'installed app' → copie o ID abaixo do nome.",
     "link": "https://www.reddit.com/prefs/apps", "documentacao": "https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki"},
    {"id": "mercadolivre", "nome": "Mercado Livre", "tipo": "oauth", "conectores": ["mercadolivre", "ml_trends"],
     "campos": [{"nome": "client_id", "rotulo": "App ID", "secreto": False},
                {"nome": "client_secret", "rotulo": "Secret Key", "secreto": True}],
     "descricao": "Tendências de busca do Mercado Livre Brasil (termos mais buscados, com histórico de cada coleta).",
     "permissoes": "Login na página oficial do Mercado Livre (o GPI não vê sua senha), com PKCE S256. Somente "
                   "leitura. O Mercado Livre exige Redirect URI HTTPS: cadastre no DevCenter exatamente o endereço "
                   "HTTPS exibido abaixo (página de retorno estática, sem segredos). O code_verifier e a Secret Key "
                   "nunca saem deste computador.",
     "como_obter": "developers.mercadolivre.com.br → Minhas aplicações → criar aplicação: Redirect URI = endereço "
                   "HTTPS exibido abaixo; ative PKCE; escopos: leitura e acesso offline.",
     "link": "https://developers.mercadolivre.com.br/devcenter",
     "documentacao": "https://developers.mercadolivre.com.br/en_us/authentication-and-authorization",
     "oauth_https_relay": True,
     "auth_url": "https://auth.mercadolivre.com.br/authorization",
     "token_url": "https://api.mercadolibre.com/oauth/token"},
    {"id": "comtrade", "nome": "UN Comtrade (chave gratuita opcional)", "tipo": "api_key", "conectores": ["comtrade"],
     "campos": [{"nome": "api_key", "rotulo": "Primary key da assinatura 'comtrade - v1' (gratuita)", "secreto": True}],
     "descricao": "Sem chave, o GPI já usa o endpoint público (1 mês por chamada). Com a chave gratuita, cada chamada "
                  "traz até 12 meses: a coleta fica ~12× mais rápida e a cota é maior.",
     "permissoes": "Somente leitura de estatísticas públicas de comércio. Plano gratuito: cota diária de chamadas; "
                   "o GPI não usa endpoints pagos.",
     "como_obter": "comtradedeveloper.un.org → Sign up → Products → 'comtrade - v1' (free) → Subscribe → "
                   "Profile → copie a Primary key.",
     "link": "https://comtradedeveloper.un.org/", "documentacao": "https://comtradedeveloper.un.org/apis"},
    {"id": "rss", "nome": "Feeds RSS de sites especializados", "tipo": "auto", "conectores": ["rss"],
     "descricao": "Manchetes de sites de tecnologia e reviews (lista editável). Apenas título, resumo curto e link.",
     "permissoes": "Leitura de feeds publicados pelos próprios sites para distribuição. O GPI guarda manchete e "
                   "link e direciona ao site original."},
    {"id": "google_news", "nome": "Google Notícias (RSS)", "tipo": "optin", "conectores": ["google_news"],
     "descricao": "Notícias recentes sobre os produtos identificados.",
     "permissoes": "Os feeds do Google Notícias têm termos de uso próprios (uso pessoal/não comercial). "
                   "Fica desativado até você confirmar que o uso é permitido para a sua empresa.",
     "documentacao": "https://policies.google.com/terms"},
    {"id": "google_trends_rss", "nome": "Google Trends — Trending Now (RSS oficial)", "tipo": "auto",
     "conectores": ["google_trends_rss"],
     "descricao": "Buscas em alta no Google no Brasil e nos EUA, com tráfego em faixas. Conectado automaticamente.",
     "permissoes": "Leitura do feed público oficial do Google Trends. Os dados são exibidos com a atribuição "
                   "'Fonte: Google Trends'.", "link": "https://trends.google.com/trending?geo=BR"},
    {"id": "google_ads", "nome": "Google Ads — Planejador de palavras-chave", "tipo": "oauth", "conectores": ["google_ads_kp"],
     "assistente": "google_ads",
     "campos": [{"nome": "client_id", "rotulo": "OAuth Client ID (tipo 'App para computador')", "secreto": False},
                {"nome": "client_secret", "rotulo": "OAuth Client Secret", "secreto": True}],
     "descricao": "Volume mensal de buscas (aproximado) e histórico de 12 meses por produto, no Brasil e nos EUA.",
     "permissoes": "Login na página oficial do Google (o GPI não vê sua senha), com PKCE e o escopo "
                   "'https://www.googleapis.com/auth/adwords'. O GPI usa SOMENTE leitura de contas e o planejador de palavras-chave: "
                   "nenhum anúncio ou campanha é criado ou alterado. Developer token NÃO é mais necessário (descontinuado pelo Google em "
                   "09/09/2026): o acesso é do projeto Google Cloud dono do Client ID, e o planejador exige nível Basic ou Standard "
                   "(Explorer não acessa).",
     "como_obter": "1) console.cloud.google.com: ative a 'Google Ads API' no projeto e crie credenciais OAuth do tipo 'App para "
                   "computador'. 2) Em Google Ads API → Overview, confira o nível de acesso (Basic para palavras-chave). "
                   "3) Informe Client ID e Secret, clique em Entrar com Google e depois em Identificar contas disponíveis.",
     "link": "https://console.cloud.google.com/apis/library/googleads.googleapis.com",
     "documentacao": "https://developers.google.com/google-ads/api/docs/api-policy/developer-token",
     "auth_url": "https://accounts.google.com/o/oauth2/v2/auth", "token_url": "https://oauth2.googleapis.com/token",
     "revoke_url": "https://oauth2.googleapis.com/revoke",
     "scope": "https://www.googleapis.com/auth/adwords", "auth_extra": {"access_type": "offline", "prompt": "consent"}},
    {"id": "google_trends", "nome": "Google Trends API (séries históricas, alfa)", "tipo": "approval",
     "conectores": ["google_trends"],
     "descricao": "Interesse de busca relativo com escala consistente, 5 anos, por país e região (ISO 3166-2).",
     "permissoes": "Acesso em alfa mediante inscrição e aprovação do Google. Enquanto não houver acesso, o GPI usa o "
                   "Trending Now (RSS) e o Planejador do Google Ads.",
     "alternativas": "Trending Now (automático) · Planejador de palavras-chave do Google Ads (conexão assistida)",
     "link": "https://developers.google.com/search/blog/2025/07/trends-api"},
    {"id": "google_bigquery", "nome": "Google Trends no BigQuery (conjunto público)", "tipo": "oauth",
     "conectores": ["google_trends_bq"],
     "campos": [{"nome": "project_id", "rotulo": "ID do projeto Google Cloud (onde as consultas são contabilizadas)", "secreto": False},
                {"nome": "client_id", "rotulo": "OAuth Client ID (tipo 'App para computador')", "secreto": False},
                {"nome": "client_secret", "rotulo": "OAuth Client secret", "secreto": True}],
     "descricao": "Top 25 e em alta por país, região (ISO 3166-2) e área de mercado nos EUA, com histórico semanal de interesse relativo.",
     "permissoes": "Escopo somente leitura do BigQuery. As consultas usam o projeto informado: a camada gratuita do "
                   "BigQuery cobre 1 TB de consultas por mês; o GPI mede cada consulta antes (dry run) e não executa as que "
                   "passarem do limite definido em Configurações (padrão 2 GB). O GPI não ativa serviços pagos.",
     "como_obter": "console.cloud.google.com: crie um projeto, ative a 'BigQuery API' e crie credenciais OAuth do tipo "
                   "'App para computador'. Informe os dados e clique em Entrar.",
     "link": "https://console.cloud.google.com/bigquery", "documentacao": "https://cloud.google.com/blog/products/data-analytics/international-google-trends-datasets-in-bigquery",
     "auth_url": "https://accounts.google.com/o/oauth2/v2/auth", "token_url": "https://oauth2.googleapis.com/token",
     "revoke_url": "https://oauth2.googleapis.com/revoke",
     "scope": "https://www.googleapis.com/auth/bigquery.readonly", "auth_extra": {"access_type": "offline", "prompt": "consent"}},
    {"id": "ebay", "nome": "eBay — Browse API", "tipo": "api_key", "conectores": ["ebay"],
     "campos": [{"nome": "client_id", "rotulo": "App ID (Client ID) de produção", "secreto": False},
                {"nome": "client_secret", "rotulo": "Cert ID (Client Secret) de produção", "secreto": True}],
     "descricao": "Anúncios ativos, preços e marcas por produto no eBay EUA — base da análise de concorrência.",
     "permissoes": "Token de aplicativo (sem login de usuário) com o escopo público de leitura. Quantidade de anúncios não é venda.",
     "como_obter": "developer.ebay.com → criar conta → Application Keys → criar keyset de Production → copie App ID e Cert ID.",
     "link": "https://developer.ebay.com/my/keys", "documentacao": "https://developer.ebay.com/api-docs/buy/browse/overview.html"},
    {"id": "msads", "nome": "Microsoft Advertising — volume de buscas no Bing", "tipo": "oauth", "conectores": ["msads_kp"],
     "campos": [{"nome": "developer_token", "rotulo": "Developer token", "secreto": True},
                {"nome": "customer_id", "rotulo": "Customer ID", "secreto": False},
                {"nome": "account_id", "rotulo": "Account ID", "secreto": False},
                {"nome": "client_id", "rotulo": "Application (client) ID do registro no Microsoft Entra", "secreto": False}],
     "descricao": "Volume mensal de buscas no Bing por palavra-chave (Brasil e EUA).",
     "permissoes": "Login na página oficial da Microsoft com o escopo msads.manage; o GPI usa apenas a consulta de volume "
                   "histórico (nenhuma campanha é criada). Implementado segundo a documentação; ainda não validado com conta real.",
     "como_obter": "ads.microsoft.com: crie a conta → Developer Portal: solicite o developer token → portal do Azure: registre "
                   "um aplicativo (cliente público, redirecionamento http://127.0.0.1) → informe os IDs e clique em Entrar.",
     "link": "https://developers.ads.microsoft.com/", "documentacao": "https://learn.microsoft.com/advertising/ad-insight-service/gethistoricalsearchvolume",
     "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
     "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
     "scope": "https://ads.microsoft.com/msads.manage offline_access"},
    {"id": "gdelt", "nome": "GDELT — notícias globais", "tipo": "auto", "conectores": ["gdelt"],
     "descricao": "Repercussão dos produtos na imprensa mundial (artigos por mês). Conectado automaticamente.",
     "permissoes": "API pública e gratuita do GDELT Project; o GPI respeita o intervalo de 5 s entre consultas.",
     "link": "https://www.gdeltproject.org/"},
    {"id": "tiktok", "nome": "TikTok API for Business — Discovery", "tipo": "oauth", "oauth_especial": "tiktok",
     "conectores": ["tiktok"],
     "campos": [{"nome": "client_id", "rotulo": "App ID (portal TikTok API for Business)", "secreto": False},
                {"nome": "client_secret", "rotulo": "Secret do app", "secreto": True},
                {"nome": "auth_url", "rotulo": "URL de autorização de anunciante (copiada do portal, opcional)", "secreto": False},
                {"nome": "auth_url_conta", "rotulo": "URL de autorização de conta TikTok (copiada do portal, opcional)", "secreto": False},
                {"nome": "access_token", "rotulo": "OU: token de acesso de longo prazo gerado no portal", "secreto": True},
                {"nome": "advertiser_id", "rotulo": "Advertiser ID (hashtags populares)", "secreto": False},
                {"nome": "business_id", "rotulo": "Business ID / open_id da conta TikTok (termos de busca em alta)", "secreto": False}],
     "descricao": "Hashtags populares por país (com visualizações e publicações), 20 termos de busca em alta no TikTok e "
                  "termos recomendados por produto — recursos oficiais de descoberta (Discovery API).",
     "permissoes": "Login nas páginas oficiais da TikTok (o GPI não pede sua senha). Exige conta TikTok for Business e app "
                   "aprovado com acesso à Discovery API. A TikTok Research API NÃO é usada: é restrita a pesquisa acadêmica. "
                   "Posição e visualizações medem atenção na plataforma — não são compras.",
     "como_obter": "1) business-api.tiktok.com → My Apps → criar app (Marketing API) e solicitar os escopos de Discovery. "
                   "2) Cadastre a URL de redirecionamento exibida abaixo. 3) Copie o App ID, o Secret e a URL de autorização "
                   "do app. 4) Clique em Conectar (anunciante) e/ou Conectar conta TikTok. Se o portal exigir URL https, gere "
                   "um token de longo prazo no portal e informe-o com o Advertiser ID/Business ID.",
     "link": "https://business-api.tiktok.com/portal/apps", "documentacao": "https://business-api.tiktok.com/portal/docs"},
    {"id": "meta", "nome": "Meta — Instagram, Facebook e Biblioteca de Anúncios", "tipo": "oauth", "oauth_especial": "meta",
     "conectores": ["instagram", "facebook", "meta_ads"],
     "campos": [{"nome": "client_id", "rotulo": "App ID (Meta for Developers)", "secreto": False},
                {"nome": "client_secret", "rotulo": "App Secret", "secreto": True},
                {"nome": "ig_user_id", "rotulo": "ID da conta profissional do Instagram (preenchido ao conectar)", "secreto": False}],
     "descricao": "Central Meta: um login compartilhado para três conectores independentes — hashtags do Instagram, "
                  "páginas comerciais do Facebook e Biblioteca de Anúncios (UE).",
     "permissoes": "Login do Facebook na página oficial da Meta, em MÓDULOS independentes: login básico (public_profile), "
                   "Páginas (pages_show_list, pages_read_engagement), Instagram (instagram_basic, pages_show_list) e Biblioteca de "
                   "Anúncios (ads_read) — cada módulo pede só as suas permissões, somente leitura. Hashtags exigem o recurso Instagram Public Content "
                   "Access; páginas públicas de terceiros exigem Page Public Content Access; a Biblioteca de Anúncios exige "
                   "identidade verificada. Cada recurso depende da revisão do app pela Meta. O token de longo prazo vale ~60 dias.",
     "como_obter": "developers.facebook.com → Meus apps → criar app (tipo Empresa) → adicionar 'Login do Facebook' e "
                   "'Instagram Graph API' → cadastrar a URL de redirecionamento exibida abaixo → solicitar os recursos na "
                   "revisão do app → informar App ID e App Secret → Conectar.",
     "link": "https://developers.facebook.com/apps/", "documentacao": "https://developers.facebook.com/docs/facebook-login",
     "assistente": "meta"},
    {"id": "amazon", "nome": "Amazon Brasil / EUA", "tipo": "approval", "conectores": ["amazon_br", "amazon_us"],
     "descricao": "Preços e rankings de produtos.", "permissoes": "Product Advertising API: exige conta aprovada no "
     "Programa de Associados com vendas qualificadas.", "link": "https://associados.amazon.com.br/"},
    {"id": "shopee", "nome": "Shopee", "tipo": "approval", "conectores": ["shopee"],
     "descricao": "Produtos e preços.", "permissoes": "Open Platform exige parceiro aprovado.", "link": "https://open.shopee.com/"},
    {"id": "china_marketplaces", "nome": "AliExpress / Taobao", "tipo": "approval",
     "conectores": ["aliexpress", "taobao"], "descricao": "Fornecedores e preços na China.",
     "permissoes": "Plataformas abertas exigem app key aprovada (afiliados, dropshipping ou cadastro empresarial).",
     "link": "https://openservice.aliexpress.com/"},
    {"id": "trustpilot", "nome": "Trustpilot", "tipo": "approval", "conectores": ["trustpilot"],
     "descricao": "Avaliações de empresas.", "permissoes": "A API é oferecida a empresas clientes do Trustpilot "
     "(planos pagos); não há acesso público gratuito para coleta de avaliações de terceiros.",
     "link": "https://developers.trustpilot.com/"},
    {"id": "comparadores", "nome": "Comparadores de preço (Buscapé, Zoom, Google Shopping)", "tipo": "approval",
     "conectores": ["comparadores"], "descricao": "Preços praticados no varejo.",
     "permissoes": "Sem API pública para consulta de preços de terceiros; exige licença/parceria.",
     "link": "https://www.buscape.com.br/"},
]


CATEGORIAS = {"pesquisas": "Pesquisas", "marketplaces": "Marketplaces", "redes_sociais": "Redes Sociais",
              "dados_publicos": "Dados Públicos", "conteudo": "Notícias e Avaliações"}
CATEGORIA_DE = {
    "google_trends_rss": ["pesquisas"], "google_ads": ["pesquisas"], "google_bigquery": ["pesquisas"], "google_trends": ["pesquisas"],
    "msads": ["pesquisas"], "mercadolivre": ["pesquisas", "marketplaces"],
    "ebay": ["marketplaces"], "amazon": ["marketplaces"], "shopee": ["marketplaces"], "china_marketplaces": ["marketplaces"],
    "comparadores": ["marketplaces"], "tiktok": ["redes_sociais"], "meta": ["redes_sociais"], "youtube": ["redes_sociais"],
    "reddit": ["redes_sociais"], "publicas": ["dados_publicos"], "comtrade": ["dados_publicos"], "gdelt": ["dados_publicos"],
    "rss": ["conteudo"], "google_news": ["conteudo"], "trustpilot": ["conteudo"],
}
NIVEL = {"auto": 1, "api_key": 2, "client_id": 2, "oauth": 2, "optin": 2, "approval": 3}
NIVEL_NOME = {1: "Conexão automática", 2: "Conexão assistida", 3: "Acesso restrito"}
for _p in PROVIDERS:
    _p["nivel"] = NIVEL[_p["tipo"]]
    _p["nivel_nome"] = NIVEL_NOME[_p["nivel"]]
    _p["categorias"] = CATEGORIA_DE.get(_p["id"], ["conteudo"])

TT_HOSTS = ("business-api.tiktok.com", "ads.tiktok.com", "www.tiktok.com", "open.tiktokapis.com")


def tiktok_authorize_url(c: dict, mode: str, redirect_uri: str, state: str) -> str:
    """Usa a URL de autorização copiada do portal da TikTok (não inventa endereço) e só aceita hosts da TikTok."""
    import urllib.parse as up
    base = (c.get("auth_url_conta") if mode == "conta" else c.get("auth_url")) or ""
    u = up.urlsplit(base)
    if u.scheme != "https" or u.hostname not in TT_HOSTS:
        raise SourceError("informe a URL de autorização copiada do portal TikTok API for Business (https://business-api.tiktok.com/...)",
                          "restrita")
    q = dict(up.parse_qsl(u.query))
    q.update({"state": state, "redirect_uri": redirect_uri})
    q.setdefault("app_id" if mode != "conta" else "client_key", c.get("client_id", ""))
    return up.urlunsplit((u.scheme, u.netloc, u.path, up.urlencode(q), ""))


def tiktok_exchange(http, creds, code: str, mode: str, redirect_uri: str) -> dict:
    c = creds.get("tiktok")
    if mode == "conta":
        r = http.request_json("https://business-api.tiktok.com/open_api/v1.3/tt_user/oauth2/token/", "POST",
                              {"client_id": c.get("client_id"), "client_secret": c.get("client_secret"), "grant_type": "authorization_code",
                               "auth_code": code, "redirect_uri": redirect_uri}, ttl=0)
    else:
        r = http.request_json("https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/", "POST",
                              {"app_id": c.get("client_id"), "secret": c.get("client_secret"), "auth_code": code}, ttl=0)
    if not isinstance(r, dict) or r.get("code") != 0:
        raise SourceError(f"TikTok não emitiu token: {(r or {}).get('message') if isinstance(r, dict) else r}", "restrita")
    d = r.get("data") or {}
    if mode == "conta":
        vals = {"access_token": d.get("access_token"), "business_id": d.get("open_id"), "refresh_token": d.get("refresh_token")}
    else:
        adv = d.get("advertiser_ids") or []
        vals = {"access_token": d.get("access_token"), "advertiser_id": str(adv[0]) if adv else c.get("advertiser_id", "")}
    creds.set("tiktok", {k: v for k, v in vals.items() if v})
    return vals


def meta_authorize_url(c: dict, ver: str, redirect_uri: str, state: str, modulo: str = "basico", rerequest: bool = False) -> str:
    from .meta import authorize_url
    return authorize_url(c, ver, redirect_uri, state, modulo, rerequest)


def meta_exchange(http, creds, code: str, redirect_uri: str, ver: str, modulo: str = "basico") -> dict:
    from .meta import exchange
    return exchange(http, creds, code, redirect_uri, ver, modulo)


def provider(pid: str) -> dict | None:
    return next((p for p in PROVIDERS if p["id"] == pid), None)


# ---------------------------------------------------------------------- testes de conexão (chamadas reais)
def test_connection(pid: str, http, creds, cfg: dict) -> tuple[bool, str]:
    try:
        if pid == "youtube":
            key = creds.get("youtube").get("api_key")
            if not key:
                return False, "informe a chave de API"
            r = http.request_json("https://www.googleapis.com/youtube/v3/i18nRegions?part=snippet&hl=pt_BR&key=" + key, ttl=0)
            return (True, f"chave válida ({len(r.get('items', []))} regiões retornadas; custo: 1 unidade)") \
                if isinstance(r, dict) and "items" in r else (False, "resposta inesperada do YouTube")
        if pid == "reddit":
            c = creds.get("reddit")
            if not c.get("client_id"):
                return False, "informe o Client ID"
            if not c.get("uso_autorizado"):
                return False, "confirme que o uso é não comercial ou contratado"
            tok = reddit_token(http, c["client_id"])
            return True, f"token obtido (válido por {tok.get('expires_in', '?')} s)"
        if pid == "mercadolivre":
            tok = ml_token(http, creds)
            me = http.request_json("https://api.mercadolibre.com/users/me", headers={"Authorization": f"Bearer {tok}"}, ttl=0)
            return True, f"conectado como {me.get('nickname', me.get('id'))}"
        if pid == "google_trends_rss":
            from ..connectors.search import parse_trending
            res = []
            for geo in ("BR", "US"):
                items = parse_trending(http.request_text(f"https://trends.google.com/trending/rss?geo={geo}", ttl=0))
                res.append(f"{geo}: {len(items)} buscas em alta")
            return True, "; ".join(res)
        if pid == "google_ads":
            from .google_ads import diagnose
            d = diagnose(http, creds)
            last = d["etapas"][-1]
            return d["estado"] == "validado", " · ".join(f"{x['etapa']}: {'ok' if x['ok'] else x['mensagem']}" for x in d["etapas"]) \
                if d["estado"] != "validado" else f"Planejador respondeu: {last['mensagem']}"
        if pid == "ebay":
            from ..connectors.sources5 import EbayBrowse, ebay_token, parse_ebay
            tok = ebay_token(http, creds)
            r = http.request_json(EbayBrowse.URL + "?q=air+fryer&limit=3", ttl=0,
                                  headers={"Authorization": f"Bearer {tok}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
            return True, f"token obtido; {len(parse_ebay(r))} anúncio(s) retornado(s) para 'air fryer'"
        if pid == "google_bigquery":
            from ..connectors.sources5 import google_token
            tok = google_token(http, creds, "google_bigquery")
            c = creds.get("google_bigquery")
            r = http.request_json(f"https://bigquery.googleapis.com/bigquery/v2/projects/{c.get('project_id')}/queries", "POST",
                                  {"query": "SELECT 1", "useLegacySql": False, "dryRun": True}, ttl=0,
                                  headers={"Authorization": f"Bearer {tok}"})
            return True, f"projeto {c.get('project_id')} aceitou consultas (teste sem custo: dry run)"
        if pid == "gdelt":
            from ..connectors.sources5 import Gdelt, parse_gdelt_timeline
            pts = parse_gdelt_timeline(http.request_json(Gdelt.URL + '?query=%22air%20fryer%22&mode=timelinevolraw&format=json&timespan=1m', ttl=0))
            return True, f"GDELT respondeu ({len(pts)} dias)"
        if pid == "msads":
            from ..connectors.sources5 import ms_token
            ms_token(http, creds)
            return True, "token Microsoft obtido (a consulta de volume é validada na primeira sincronização)"
        if pid == "comtrade":
            key = creds.get("comtrade").get("api_key")
            if not key:
                return False, "informe a chave"
            r = http.request_json("https://comtradeapi.un.org/data/v1/get/C/A/HS?reporterCode=76&period=2023"
                                  "&partnerCode=156&cmdCode=TOTAL&flowCode=M", ttl=0,
                                  headers={"Ocp-Apim-Subscription-Key": key})
            n = len(r.get("data") or []) if isinstance(r, dict) else 0
            return (n > 0, f"chave válida ({n} registro retornado: importações do Brasil vindas da China, 2023)"
                    if n else f"a API respondeu sem dados: {str(r)[:200]}")
        if pid == "rss":
            from ..connectors.content import RSS_DEFAULT, parse_feed
            feeds = cfg.get("rss_feeds") or RSS_DEFAULT
            okc, msgs = 0, []
            for f in feeds[:3]:
                try:
                    items = parse_feed(http.request_text(f["url"], ttl=0))
                    okc += 1
                    msgs.append(f"{f['nome']}: {len(items)} itens")
                except SourceError as e:
                    msgs.append(f"{f['nome']}: {e}")
            return okc > 0, "; ".join(msgs)
        if pid == "google_news":
            from ..connectors.content import parse_feed
            items = parse_feed(http.request_text(
                "https://news.google.com/rss/search?q=eletr%C3%B4nicos&hl=pt-BR&gl=BR&ceid=BR:pt-419", ttl=0))
            return True, f"{len(items)} notícias retornadas"
        if pid == "tiktok":
            c = creds.get("tiktok")
            if not c.get("access_token"):
                return False, "conecte pelo OAuth ou informe o token de acesso gerado no portal"
            from ..social.connectors import TT_API, _tt_check
            msgs = []
            if c.get("advertiser_id"):
                d = _tt_check(http.request_json(TT_API + "discovery/trending_list/?advertiser_id=" + c["advertiser_id"] +
                                                "&discovery_type=HASHTAG&country_code=BR&date_range=7DAY", ttl=0,
                                                headers={"Access-Token": c["access_token"]}))
                msgs.append(f"{len(d.get('list') or [])} hashtags populares (BR)")
            if c.get("business_id"):
                d = _tt_check(http.request_json(TT_API + cfg.get("tiktok_search_path", "discovery/search/") + "?business_id=" +
                                                c["business_id"], ttl=0, headers={"Access-Token": c["access_token"]}))
                msgs.append(f"{len(d.get('search_keywords') or [])} termos de busca em alta")
            return (bool(msgs), "; ".join(msgs) or "informe o Advertiser ID ou o Business ID")
        if pid == "meta":
            c = creds.get("meta")
            if not c.get("access_token"):
                return False, "use 'Conectar' para entrar com a conta Meta"
            import urllib.parse as up
            g = f"https://graph.facebook.com/{cfg.get('meta_graph_version', 'v23.0')}/"
            me = http.request_json(g + "me?" + up.urlencode({"fields": "id,name", "access_token": c["access_token"]}), ttl=0)
            if me.get("error"):
                return False, f"Meta: {me['error'].get('message')}"
            msg = f"token válido ({me.get('name', me.get('id'))})"
            if c.get("ig_user_id"):
                ig = http.request_json(g + c["ig_user_id"] + "?" + up.urlencode({"fields": "username", "access_token": c["access_token"]}), ttl=0)
                msg += f"; Instagram: {ig.get('username') or (ig.get('error') or {}).get('message')}"
            else:
                msg += "; nenhuma conta profissional do Instagram vinculada"
            return True, msg
        if pid == "publicas":
            r = http.request_json("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/Moedas?$format=json", ttl=0)
            return (True, f"Banco Central respondeu ({len(r.get('value', []))} moedas)") if "value" in r else (False, "resposta inesperada")
        return False, "esta fonte exige aprovação do provedor; não há teste disponível sem credenciais"
    except SourceError as e:
        return False, str(e)


def reddit_token(http, client_id: str) -> dict:
    auth = base64.b64encode(f"{client_id}:".encode()).decode()
    r = http.request_json("https://www.reddit.com/api/v1/access_token", "POST",
                          form={"grant_type": "https://oauth.reddit.com/grants/installed_client",
                                "device_id": "DO_NOT_TRACK_THIS_DEVICE"},
                          headers={"Authorization": f"Basic {auth}"})
    if not r.get("access_token"):
        raise SourceError(f"Reddit não emitiu token: {r.get('error', r)}", "restrita")
    return r


def ml_token(http, creds) -> str:
    """Token de acesso do Mercado Livre (renovação com refresh token de uso único — ver mercadolivre.py)."""
    from .mercadolivre import token
    return token(http, creds)


def store_oauth_token(creds, pid: str, r: dict):
    if pid == "mercadolivre":
        return store_ml_token(creds, r)
    if not r.get("access_token"):
        raise SourceError(f"o provedor não emitiu token: {r.get('error_description') or r.get('error')}", "restrita")
    data = {"access_token": r["access_token"], "expires_at": str(time.time() + float(r.get("expires_in", 3600)))}
    if r.get("refresh_token"):
        data["refresh_token"] = r["refresh_token"]
    creds.set(pid, data)


def store_ml_token(creds, r: dict):
    from .mercadolivre import store
    store(creds, r)
