"""Declaração de capacidades dos conectores e verificações antes de qualquer consulta da suíte.

Para cada consulta: (1) capacidade declarada, (2) autenticação, (3) cota, (4) custo, (5) cache, depois normalização,
registro de evidências e limitações. Provedor que não declara a capacidade nunca é usado para ela (ex.: ranking não é
volume de pesquisa; Comex Stat não identifica empresas)."""
from __future__ import annotations

CAPS = ["keyword_search", "product_search", "image_search", "marketplace_listings", "search_volume", "trade_statistics",
        "supplier_search", "shipment_search", "historical_data"]

# custo: "gratuito" | "gratuito com cota" | "pago opcional". Todos os itens "pago" ficam desligados por padrão.
PROVIDERS = {
    "ebay": {"nome": "eBay Browse API", "caps": ["product_search", "marketplace_listings"], "custo": "gratuito com cota", "auth": True,
             "limites": "anúncios ativos; sem vendas nem receita"},
    "mercadolivre": {"nome": "Mercado Livre (OAuth)", "caps": ["product_search", "marketplace_listings"], "custo": "gratuito com cota", "auth": True,
                     "limites": "acesso conforme as permissões da aplicação; sem vendas de terceiros"},
    "ml_trends": {"nome": "Mercado Livre — tendências", "caps": ["keyword_search", "historical_data"], "custo": "gratuito com cota", "auth": True,
                  "limites": "ranking de buscas (posição), não volume"},
    "google_trends_rss": {"nome": "Google Trends (RSS diário)", "caps": ["keyword_search"], "custo": "gratuito", "auth": False,
                          "limites": "buscas em alta do dia; faixa de tráfego aproximada"},
    "google_trends_bq": {"nome": "Google Trends (BigQuery público)", "caps": ["keyword_search", "historical_data"], "custo": "gratuito com cota",
                         "auth": True, "limites": "termos em alta por região; interesse relativo"},
    "google_ads_kp": {"nome": "Google Ads Keyword Planner", "caps": ["keyword_search", "search_volume", "historical_data"], "custo": "gratuito com cota",
                      "auth": True, "limites": "faixas de volume; requer conta Google Ads"},
    "msads_kp": {"nome": "Microsoft Advertising Keyword Planner", "caps": ["keyword_search", "search_volume"], "custo": "gratuito com cota",
                 "auth": True, "limites": "requer conta Microsoft Advertising"},
    "wikimedia": {"nome": "Wikipédia (visualizações)", "caps": ["historical_data"], "custo": "gratuito", "auth": False,
                  "limites": "atenção pública — não é intenção de compra"},
    "comexstat": {"nome": "Comex Stat (MDIC)", "caps": ["trade_statistics", "historical_data"], "custo": "gratuito", "auth": False,
                  "limites": "agregado por NCM/país; não identifica empresas"},
    "comtrade": {"nome": "UN Comtrade", "caps": ["trade_statistics", "historical_data"], "custo": "gratuito com cota", "auth": False,
                 "limites": "agregado por HS/país"},
    "anatel": {"nome": "Anatel — produtos homologados (dados abertos)", "caps": ["supplier_search", "historical_data"], "custo": "gratuito",
               "auth": False, "limites": "fabricante e titular por registro; não é volume nem relação comercial ativa"},
    "inmetro": {"nome": "Inmetro — registros (dados abertos)", "caps": ["supplier_search"], "custo": "gratuito", "auth": False,
                "limites": "fabricante e titular por registro"},
    "usuario_arquivos": {"nome": "Planilhas do usuário (fornecedores, embarques, avaliações)", "caps": ["supplier_search", "shipment_search"],
                         "custo": "gratuito", "auth": False, "limites": "cobertura = o que o usuário importar"},
    "visual_local": {"nome": "Busca visual local (Pillow + NumPy)", "caps": ["image_search"], "custo": "gratuito", "auth": False,
                     "limites": "compara com o catálogo visual do GPI; semelhança ≠ mesmo fabricante"},
    "busca_reversa_assistida": {"nome": "Google Lens / TinEye / Yandex (navegador)", "caps": ["image_search"], "custo": "gratuito", "auth": False,
                                "limites": "aberto pelo usuário; o GPI não envia imagens nem lê resultados"},
    "youtube": {"nome": "YouTube Data API", "caps": ["product_search", "historical_data"], "custo": "gratuito com cota", "auth": True,
                "limites": "vídeos e métricas públicas; não é avaliação de comprador"},
    "importyeti": {"nome": "ImportYeti (opcional)", "caps": ["supplier_search", "shipment_search", "historical_data"], "custo": "pago opcional",
                   "auth": True, "limites": "embarques dos EUA; desligado no modo sem custos externos"},
}
EXCLUDED = [{"nome": "Bing Visual Search", "motivo": "API descontinuada — nenhuma integração nova"},
            {"nome": "Google Custom Search JSON API", "motivo": "não é dependência essencial; não usado"},
            {"nome": "Google Cloud Vision / serviços pagos de visão", "motivo": "pagos — fora do modo sem custos"}]


def providers_for(cap: str) -> list[str]:
    return [k for k, v in PROVIDERS.items() if cap in v["caps"]]


def status_table(db, settings: dict, extra: dict | None = None) -> list[dict]:
    st = {r["source"]: r for r in db.query("SELECT source, state, message, last_success FROM source_status")}
    out = []
    for k, v in PROVIDERS.items():
        s = st.get(k) or {}
        paid_off = v["custo"].startswith("pago") and settings.get("sem_custos")
        out.append({"id": k, "fonte": v["nome"], "capacidades": v["caps"], "custo": v["custo"], "autenticacao": "sim" if v["auth"] else "não",
                    "status": "desligado (sem custos externos)" if paid_off else (s.get("state") or ("local" if k in ("visual_local", "usuario_arquivos",
                              "busca_reversa_assistida", "anatel", "inmetro") else "não sincronizado")),
                    "ultima_coleta": s.get("last_success"), "limitacoes": v["limites"], **((extra or {}).get(k) or {})})
    return out


def preflight(db, cap: str, provider: str, settings: dict, has_cache: bool = False) -> dict:
    """Checagens antes de consultar. Devolve {'ok': bool, 'etapas': [...]} — o motivo de cada recusa fica registrado."""
    v = PROVIDERS.get(provider)
    steps = []
    if not v or cap not in v["caps"]:
        return {"ok": False, "etapas": [{"etapa": "capacidade", "ok": False, "detalhe": f"{provider} não declara '{cap}'"}]}
    steps.append({"etapa": "capacidade", "ok": True})
    st = db.query("SELECT state FROM source_status WHERE source = ?", (provider,))
    auth_ok = not v["auth"] or (st and st[0]["state"] in ("funcional", "parcial", "ok"))
    steps.append({"etapa": "autenticação", "ok": bool(auth_ok), "detalhe": None if auth_ok else "não configurada ou sem validação"})
    paid = v["custo"].startswith("pago")
    cost_ok = not paid or (not settings.get("sem_custos") and float(settings.get("orcamento_creditos") or 0) > 0)
    steps.append({"etapa": "custo", "ok": cost_ok, "detalhe": v["custo"]})
    steps.append({"etapa": "cota", "ok": True, "detalhe": "controlada pelo cliente HTTP do GPI (limites e cache por fonte)"})
    steps.append({"etapa": "cache", "ok": True, "detalhe": "resultado em cache" if has_cache else "sem cache"})
    return {"ok": all(s["ok"] for s in steps), "etapas": steps}
