"""Matriz de fontes — registro VERIFICÁVEL de cobertura. Uma fonte só aparece como operacional quando houve consulta
bem-sucedida com registros gravados; adaptador criado ≠ fonte operacional."""
from __future__ import annotations

STATES = ["Operacional com dados reais", "Operacional sem resultados", "Autenticação pendente", "Permissão pendente",
          "Limite de requisições", "Indisponível", "Consulta manual", "Importação documental", "Não implementada", "Ainda não consultada"]

# id → (nome, URL oficial, tipo, países, granularidade, API, acesso, gratuidade, limitações, implementação)
META = {
    "comexstat": ("Comex Stat (MDIC)", "https://comexstat.mdic.gov.br", "estatística oficial de importação", "Brasil",
                  "NCM 8 / SH4 × país × mês (FOB, kg, quantidade)", "sim", "público", "gratuita",
                  "agregado: não identifica empresas; revisões e defasagem ~1 mês; HTTP 429 frequente", "conector + consulta direcionada"),
    "census": ("U.S. Census Bureau — International Trade API", "https://api.census.gov/data/timeseries/intltrade/imports/hs",
               "estatística oficial de importação", "EUA", "HS 2–10 × país × mês (valor, quantidade)", "sim",
               "público (chave gratuita opcional)", "gratuita", "agregado; dados suprimidos (D) não aparecem", "consulta direcionada"),
    "comtrade": ("UN Comtrade", "https://comtradeplus.un.org", "estatística internacional", "~200 países", "HS × parceiro × mês",
                 "sim", "público (preview) / chave gratuita", "gratuita com cota", "limite de registros por chamada; atraso de meses",
                 "conector (China → EUA/Alemanha/México)"),
    "usitc": ("USITC DataWeb", "https://dataweb.usitc.gov", "estatística oficial EUA (HTS)", "EUA", "HTS 10 × país", "sim (token)",
              "conta gratuita", "gratuita", "API com token não integrada nesta versão", "consulta manual"),
    "cbp_manifestos": ("CBP — manifestos de carga (AMS)", "https://www.cbp.gov/trade", "embarques individuais (B/L)", "EUA",
                       "embarque", "não (lote/licença/pedido formal)", "restrito", "não gratuito por empresa",
                       "sem API pública gratuita; partes podem pedir confidencialidade", "importação documental"),
    "usuario_arquivos": ("Arquivos do usuário (B/L, manifestos, planilhas)", "—", "embarques e empresas", "qualquer", "embarque",
                         "não", "local", "gratuita", "cobertura = o que o usuário importar", "importação documental"),
    "importyeti": ("ImportYeti (opcional)", "https://www.importyeti.com", "embarques EUA", "EUA", "embarque", "sim", "chave",
                   "pago (créditos)", "desligado no modo sem custos externos", "adaptador opcional"),
    "ebay": ("eBay Browse API", "https://developer.ebay.com/api-docs/buy/browse", "anúncios e preços", "EUA", "anúncio", "sim", "OAuth app",
             "gratuita com cota", "anúncios ativos; sem vendas", "conector"),
    "mercadolivre": ("Mercado Livre API", "https://developers.mercadolivre.com.br", "anúncios e tendências", "Brasil", "anúncio/termo",
                     "sim", "OAuth", "gratuita com cota", "acesso conforme permissões da aplicação", "conector"),
    "google_ads_kp": ("Google Ads Keyword Planner", "https://developers.google.com/google-ads/api", "volume de busca", "BR/EUA",
                      "termo × mês (faixas)", "sim", "OAuth + developer token", "gratuita com cota", "faixas de volume", "conector"),
    "msads_kp": ("Microsoft Advertising Ad Insight", "https://learn.microsoft.com/advertising", "volume de busca (Bing)", "BR/EUA",
                 "termo × mês", "sim", "OAuth", "gratuita com cota", "requer conta de anúncios", "conector"),
    "google_trends_rss": ("Google Trends — Trending Now (RSS)", "https://trends.google.com", "buscas em alta", "BR/EUA", "termo × dia",
                          "RSS", "público", "gratuita", "interesse relativo; não é volume", "conector"),
    "youtube": ("YouTube Data API", "https://developers.google.com/youtube/v3", "vídeos e métricas públicas", "global", "vídeo",
                "sim", "chave", "gratuita com cota", "não é avaliação de comprador", "conector"),
    "gdelt": ("GDELT DOC 2.0", "https://www.gdeltproject.org", "cobertura de notícias", "global", "termo × dia", "sim", "público",
              "gratuita", "menções em notícias ≠ demanda", "conector"),
    "anatel": ("Anatel — produtos homologados", "https://dados.gov.br", "registros regulatórios", "Brasil", "registro", "arquivo aberto",
               "público", "gratuita", "fabricante/titular por registro; não é volume", "conector"),
    "inmetro": ("Inmetro — registros", "https://dados.gov.br", "registros regulatórios", "Brasil", "registro", "arquivo aberto",
                "público", "gratuita", "fabricante/titular por registro", "conector"),
    "web_publico": ("Páginas públicas de produto (Schema.org/OpenGraph)", "—", "dados de produto", "global", "página", "HTTP",
                    "público, se permitido", "gratuita", "só com robots.txt permitindo e sites sem proibição nos termos", "leitura sob demanda"),
    "reddit": ("Reddit API", "https://www.reddit.com/dev/api", "menções", "global", "post", "sim", "OAuth + aprovação comercial",
               "restrita", "uso comercial exige aprovação", "Não implementada"),
}


def _state_from(row: dict | None, auth: bool, has_creds: bool, impl: str) -> str:
    if impl in ("consulta manual",):
        return "Consulta manual"
    if impl == "importação documental":
        return "Importação documental"
    if impl == "Não implementada":
        return "Não implementada"
    if auth and not has_creds:
        return "Autenticação pendente"
    if not row:
        return "Ainda não consultada"
    st = (row.get("state") or "").lower()
    if "limite" in st or "429" in (row.get("message") or ""):
        return "Limite de requisições"
    if "permiss" in st or "403" in (row.get("message") or ""):
        return "Permissão pendente"
    if "autoriz" in st or "token" in st or "401" in (row.get("message") or ""):
        return "Autenticação pendente"
    if row.get("records"):
        return "Operacional com dados reais" if row.get("last_success") else "Indisponível"
    if st in ("ok", "funcional", "sem dados", "sem resultados", "concluido", "atualizado") or row.get("last_success"):
        return "Operacional sem resultados"
    return "Indisponível"


def build(db, creds_ok: dict | None = None) -> list[dict]:
    creds_ok = creds_ok or {}
    st = {r["source"]: dict(r) for r in db.query("SELECT * FROM source_status")}
    try:
        tq = db.query("SELECT source, state, message, SUM(rows) AS n, MAX(queried_at) AS ultima, "
                      "MAX(CASE WHEN state = 'com dados' THEN queried_at END) AS ok FROM trade_queries GROUP BY source")
    except Exception:  # noqa: BLE001
        tq = []
    for r in tq:
        if r["source"] not in st or r["source"] == "census":
            st[r["source"]] = {"state": r["state"], "message": r["message"], "records": r["n"], "last_attempt": r["ultima"],
                               "last_success": r["ok"]}
    try:
        tr = db.query("SELECT source, MAX(status) AS state, MAX(at) AS ultima, SUM(n) AS n FROM research_source_runs GROUP BY source")
    except Exception:  # noqa: BLE001
        tr = []
    for r in tr:
        st.setdefault(r["source"], {"state": r["state"], "records": r["n"], "last_attempt": r["ultima"],
                                    "last_success": r["ultima"] if r["n"] else None})
    try:
        ship = db.query("SELECT COUNT(*) AS n, MAX(imported_at) AS u FROM trade_shipments")[0]
    except Exception:  # noqa: BLE001
        ship = {"n": 0, "u": None}
    out = []
    for k, (nome, url, tipo, paises, gran, api, acesso, gr, lim, impl) in META.items():
        row = st.get(k)
        auth = acesso not in ("público", "local", "público (chave gratuita opcional)", "público (preview) / chave gratuita",
                              "público, se permitido", "restrito")
        estado = _state_from(row, auth and k not in ("usitc",), creds_ok.get(k, not auth), impl)
        regs = (row or {}).get("records")
        if k == "usuario_arquivos":
            regs, estado = ship["n"], "Operacional com dados reais" if ship["n"] else "Importação documental"
        out.append({"id": k, "nome": nome, "url_oficial": url, "tipo": tipo, "paises": paises, "granularidade": gran, "api": api,
                    "acesso": acesso, "gratuidade": gr, "limitacoes": lim, "implementacao": impl,
                    "ultima_sincronizacao": (row or {}).get("last_attempt") or (ship["u"] if k == "usuario_arquivos" else None),
                    "ultima_consulta_ok": (row or {}).get("last_success"), "registros": regs,
                    "erros": (row or {}).get("message") if estado in ("Indisponível", "Limite de requisições", "Permissão pendente",
                                                                     "Autenticação pendente") else None,
                    "estado": estado})
    return out
