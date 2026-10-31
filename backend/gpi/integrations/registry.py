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
    {"id": "mercadolivre", "nome": "Mercado Livre", "tipo": "oauth", "conectores": ["mercadolivre"],
     "campos": [{"nome": "client_id", "rotulo": "App ID", "secreto": False},
                {"nome": "client_secret", "rotulo": "Secret Key", "secreto": True}],
     "descricao": "Tendências de busca do Mercado Livre Brasil.",
     "permissoes": "Login na página oficial do Mercado Livre (o GPI não vê sua senha), com PKCE. Somente leitura. "
                   "No DevCenter, cadastre a URL de redirecionamento exibida abaixo; se o Mercado Livre não aceitar "
                   "endereço http://127.0.0.1, a conexão OAuth não é possível nesta instalação.",
     "como_obter": "developers.mercadolivre.com.br → Minhas aplicações → criar aplicação (ative PKCE).",
     "link": "https://developers.mercadolivre.com.br/devcenter",
     "documentacao": "https://developers.mercadolivre.com.br/pt_br/autenticacao-e-autorizacao",
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
     "campos": [{"nome": "developer_token", "rotulo": "Developer token (Central da API do Google Ads)", "secreto": True},
                {"nome": "customer_id", "rotulo": "ID da conta Google Ads (ex.: 123-456-7890)", "secreto": False},
                {"nome": "login_customer_id", "rotulo": "ID da conta de administrador (MCC), se houver", "secreto": False},
                {"nome": "client_id", "rotulo": "OAuth Client ID (tipo 'App para computador')", "secreto": False},
                {"nome": "client_secret", "rotulo": "OAuth Client secret", "secreto": True}],
     "descricao": "Volume mensal de buscas (aproximado) e histórico de 12 meses por produto, no Brasil e nos EUA.",
     "permissoes": "Login na página oficial do Google (o GPI não vê sua senha) com o escopo "
                   "'https://www.googleapis.com/auth/adwords' — permite ler e gerenciar a conta de anúncios; o GPI usa "
                   "SOMENTE o planejador de palavras-chave (nenhum anúncio é criado ou alterado). O developer token "
                   "precisa estar aprovado (acesso Básico ou superior) para dados de contas reais.",
     "como_obter": "1) ads.google.com: crie/acesse uma conta (não precisa veicular anúncios). 2) Ferramentas → Central "
                   "da API: solicite o developer token. 3) console.cloud.google.com: ative a 'Google Ads API' e crie "
                   "credenciais OAuth do tipo 'App para computador'. 4) Preencha os campos e clique em Conectar.",
     "link": "https://developers.google.com/google-ads/api/docs/get-started/introduction",
     "documentacao": "https://developers.google.com/google-ads/api/docs/keyword-planning/generate-keyword-ideas",
     "auth_url": "https://accounts.google.com/o/oauth2/v2/auth", "token_url": "https://oauth2.googleapis.com/token",
     "scope": "https://www.googleapis.com/auth/adwords", "auth_extra": {"access_type": "offline", "prompt": "consent"}},
    {"id": "google_trends", "nome": "Google Trends API (séries históricas, alfa)", "tipo": "approval",
     "conectores": ["google_trends"],
     "descricao": "Interesse de busca relativo com escala consistente, 5 anos, por país e região (ISO 3166-2).",
     "permissoes": "Acesso em alfa mediante inscrição e aprovação do Google. Enquanto não houver acesso, o GPI usa o "
                   "Trending Now (RSS) e o Planejador do Google Ads.",
     "alternativas": "Trending Now (automático) · Planejador de palavras-chave do Google Ads (conexão assistida)",
     "link": "https://developers.google.com/search/blog/2025/07/trends-api"},
    {"id": "china_search", "nome": "Busca na China (Baidu Index, 巨量算数, Alibaba)", "tipo": "approval",
     "conectores": ["baidu_index", "ocean_engine", "alibaba_insights"],
     "descricao": "Interesse de busca de consumidores na China continental.",
     "permissoes": "Nenhuma dessas fontes oferece API aberta a terceiros: exigem login chinês, contrato pago ou "
                   "empresa registrada. O GPI não raspa nem contorna essas proteções. Visualizações da Wikipédia em "
                   "chinês NÃO equivalem a buscas na China e não são apresentadas como tal.",
     "alternativas": "Sinais de oferta (exportações chinesas via UN Comtrade/Comex Stat), claramente identificados",
     "link": "https://index.baidu.com/"},
    {"id": "msads", "nome": "Microsoft Advertising — Keyword Planner", "tipo": "approval", "conectores": ["msads_kp"],
     "descricao": "Volumes de busca no Bing.", "permissoes": "Exige conta e developer token Microsoft Advertising; "
     "não implementado nesta fase.", "link": "https://learn.microsoft.com/advertising/guides/get-started"},
    {"id": "amazon", "nome": "Amazon Brasil / EUA", "tipo": "approval", "conectores": ["amazon_br", "amazon_us"],
     "descricao": "Preços e rankings de produtos.", "permissoes": "Product Advertising API: exige conta aprovada no "
     "Programa de Associados com vendas qualificadas.", "link": "https://associados.amazon.com.br/"},
    {"id": "shopee", "nome": "Shopee", "tipo": "approval", "conectores": ["shopee"],
     "descricao": "Produtos e preços.", "permissoes": "Open Platform exige parceiro aprovado.", "link": "https://open.shopee.com/"},
    {"id": "china_marketplaces", "nome": "AliExpress / Alibaba / Taobao", "tipo": "approval",
     "conectores": ["aliexpress", "alibaba", "taobao"], "descricao": "Fornecedores e preços na China.",
     "permissoes": "Plataformas abertas exigem app key aprovada (afiliados, dropshipping ou cadastro empresarial).",
     "link": "https://openservice.aliexpress.com/"},
    {"id": "trustpilot", "nome": "Trustpilot", "tipo": "approval", "conectores": ["trustpilot"],
     "descricao": "Avaliações de empresas.", "permissoes": "A API é oferecida a empresas clientes do Trustpilot "
     "(planos pagos); não há acesso público gratuito para coleta de avaliações de terceiros.",
     "link": "https://developers.trustpilot.com/"},
    {"id": "reclame_aqui", "nome": "Reclame Aqui", "tipo": "approval", "conectores": ["reclame_aqui"],
     "descricao": "Reclamações de consumidores no Brasil.", "permissoes": "Não há API pública; acesso a dados somente "
     "por parceria comercial com o Reclame Aqui. O site não é raspado.", "link": "https://www.reclameaqui.com.br/"},
    {"id": "comparadores", "nome": "Comparadores de preço (Buscapé, Zoom, Google Shopping)", "tipo": "approval",
     "conectores": ["comparadores"], "descricao": "Preços praticados no varejo.",
     "permissoes": "Sem API pública para consulta de preços de terceiros; exige licença/parceria.",
     "link": "https://www.buscape.com.br/"},
]


NIVEL = {"auto": 1, "api_key": 2, "client_id": 2, "oauth": 2, "optin": 2, "approval": 3}
NIVEL_NOME = {1: "Conexão automática", 2: "Conexão assistida", 3: "Acesso restrito"}
for _p in PROVIDERS:
    _p["nivel"] = NIVEL[_p["tipo"]]
    _p["nivel_nome"] = NIVEL_NOME[_p["nivel"]]


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
            from ..connectors.search import gads_call
            r = gads_call(http, creds, ":generateKeywordIdeas", {
                "language": "languageConstants/1014", "geoTargetConstants": ["geoTargetConstants/2076"],
                "keywordPlanNetwork": "GOOGLE_SEARCH", "keywordSeed": {"keywords": ["air fryer"]}})
            n = len(r.get("results", []))
            return (n > 0, f"API respondeu ({creds.get('google_ads').get('api_version')}): {n} ideias de palavras-chave"
                    if n else "a API respondeu sem ideias (verifique o nível de acesso do developer token)")
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
    """Token de acesso do Mercado Livre, renovando com o refresh_token quando expirado."""
    c = creds.get("mercadolivre")
    if not c.get("access_token"):
        raise SourceError("Mercado Livre não conectado: use 'Conectar' na Central de Integrações", "restrita")
    if float(c.get("expires_at", 0)) > time.time() + 60:
        return c["access_token"]
    if not c.get("refresh_token"):
        raise SourceError("token do Mercado Livre expirado; conecte novamente", "restrita")
    r = http.request_json(provider("mercadolivre")["token_url"], "POST", form={
        "grant_type": "refresh_token", "client_id": c.get("client_id", ""), "client_secret": c.get("client_secret", ""),
        "refresh_token": c["refresh_token"]})
    store_ml_token(creds, r)
    return r["access_token"]


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
    if not r.get("access_token"):
        raise SourceError(f"Mercado Livre não emitiu token: {r.get('message') or r.get('error')}", "restrita")
    creds.set("mercadolivre", {"access_token": r["access_token"], "refresh_token": r.get("refresh_token"),
                               "expires_at": str(time.time() + float(r.get("expires_in", 21600))),
                               "user_id": str(r.get("user_id", ""))})
