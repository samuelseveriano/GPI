"""Coleta DIRECIONADA do Product Research — consulta as fontes externas autorizadas que aceitam pesquisa por um produto
específico, reutilizando os MESMOS conectores da sincronização (mesmos tokens, limites, cache HTTP, pseudonimização e
gravação). Nada de raspagem e nada pago sem autorização.

Seleção por capacidade real:
  * Mercado Livre — busca de anúncios por palavra-chave (OAuth do usuário)          → marketplace_listings
  * eBay Browse — anúncios e preços por palavra-chave (credenciais do usuário)       → marketplace_listings
  * Google Ads Keyword Planner — histórico de volume por palavra-chave (OAuth)       → search_volume
  * Microsoft Advertising — volume de buscas no Bing por palavra-chave (OAuth)       → search_volume
  * YouTube Data API — vídeos sobre o produto (chave do usuário; cota diária do GPI) → product_search (conteúdo)
  * GDELT DOC 2.0 — notícias que citam o produto (público, sem credencial)          → news_mentions (atenção pública ≠ demanda)

Fontes que NÃO aceitam consulta arbitrária por produto aparecem no diagnóstico com o motivo: Google Trends RSS (só
buscas em alta do dia), Google Trends BigQuery (só termos em alta por região), ranking de tendências do Mercado Livre
(lista geral) e Comex Stat (consultado por NCM, nunca por produto)."""
from __future__ import annotations

import time
import urllib.parse
from datetime import datetime, timedelta

from . import store as S

RUNS_SQL = """CREATE TABLE IF NOT EXISTS research_source_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
    market TEXT NOT NULL, query_norm TEXT NOT NULL, at TEXT NOT NULL, status TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
    detail TEXT, research_id INTEGER)"""
STATUS = {"com dados": "consulta feita e devolveu registros válidos", "sem dados": "consulta feita, nenhum registro válido",
          "cache válido": "consulta recente reaproveitada (dentro da validade do cache)",
          "não autorizada": "credencial ausente, expirada ou permissão negada pela fonte",
          "indisponível": "fonte fora do ar, sem rede ou cota/limite atingido", "falhou": "erro inesperado na consulta",
          "ignorada (modo rápido)": "fonte reservada para a pesquisa completa", "cancelada": "pesquisa cancelada pelo usuário",
          "não suporta consulta direcionada": "a fonte não permite consultar um produto arbitrário"}
USEFUL = {"com dados", "cache válido"}
TTL_DAYS = {"rapida": 7, "completa": 1}


def ensure(db):
    S.ensure(db)
    db.execute(RUNS_SQL)
    db.execute("CREATE INDEX IF NOT EXISTS idx_rsr ON research_source_runs(source, market, query_norm, at)")


def _norm(t: str) -> str:
    from ..products import nlp
    return nlp._norm(t or "")[:200]


# ------------------------------------------------------------------------------------------------ fontes
def _creds(ctx, name):
    try:
        return ctx.creds.get(name) if ctx.creds else {}
    except Exception:  # noqa: BLE001
        return {}


def _ml_search(ctx, job):
    """Busca de anúncios do Mercado Livre (API oficial /sites/MLB/search, com o token OAuth do usuário)."""
    from ..connectors.http import SourceError
    from ..integrations.ebay_compliance import seller_pseudonym
    from ..integrations.registry import ml_token
    from ..products import nlp
    tok = ml_token(ctx.http, ctx.creds)
    url = "https://api.mercadolibre.com/sites/MLB/search?" + urllib.parse.urlencode({"q": job["q"], "limit": 50})
    r = ctx.http.request_json(url, headers={"Authorization": f"Bearer {tok}"}, ttl=0)
    if not isinstance(r, dict) or not isinstance(r.get("results"), list):
        raise SourceError("Mercado Livre: resposta sem 'results'", "formato")
    day, ts = ctx.today.isoformat(), datetime.now().isoformat(timespec="seconds")
    n = 0
    with ctx.store.db.transaction():
        for it in r["results"]:
            if not it.get("id") or not it.get("title"):
                continue
            at = nlp.extract_attributes(it["title"])
            brand = next((a.get("value_name") for a in it.get("attributes") or [] if a.get("id") == "BRAND"), None) or at.get("marca")
            ctx.store.db.execute(
                "INSERT OR REPLACE INTO market_listings (source, item_id, day, product_id, query, title, brand, model, category, price, "
                "currency, original_price, country, seller, condition, url, extra, collected_at) "
                "VALUES ('mercadolivre', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BR', ?, ?, ?, NULL, ?)",
                (str(it["id"]), day, job.get("pid"), job["q"], str(it["title"])[:300], brand, at.get("modelo"), it.get("category_id"),
                 it.get("price"), it.get("currency_id"), it.get("original_price"),
                 seller_pseudonym(ctx.creds, str((it.get("seller") or {}).get("id") or "") or None),   # pseudônimo, nunca o ID
                 it.get("condition"), it.get("permalink"), ts))
            n += 1
    return n


def _available(sid, ctx) -> tuple[bool, str]:
    c = lambda n: _creds(ctx, n)  # noqa: E731
    if sid == "mercadolivre_busca":
        ok = bool(c("mercadolivre").get("access_token") or ctx.cfg.get("mercadolivre_access_token"))
        return ok, "Mercado Livre não conectado (Central de Integrações → Mercado Livre → Conectar)"
    if sid == "ebay":
        e = c("ebay")
        if not (e.get("client_id") and e.get("client_secret")):
            return False, "eBay sem Client ID/Secret (Central de Integrações → eBay)"
        return bool(e.get("sync_token")), "eBay sem o fluxo Marketplace Account Deletion configurado (exigido para guardar anúncios)"
    if sid == "google_ads_kp":
        g = c("google_ads")
        return bool(g.get("refresh_token") and g.get("customer_id")), "Google Ads não conectado ou sem conta selecionada (acesso Basic ao Keyword Planner)"
    if sid == "msads_kp":
        m = c("msads")
        return bool(m.get("refresh_token") and m.get("developer_token") and m.get("customer_id") and m.get("account_id")), \
            "Microsoft Advertising não conectado (OAuth, developer token, customer e account ID)"
    if sid == "youtube":
        return bool(c("youtube").get("api_key")), "YouTube sem chave da Data API v3 (Central de Integrações → YouTube)"
    if sid == "gdelt":
        return True, ""
    return False, "fonte desconhecida"


def _run(sid, ctx, q_pt, q_en, pid, market):
    """Executa a consulta com o conector existente. Devolve a quantidade de registros válidos gravados."""
    from ..connectors.base import Job
    db = ctx.store.db
    start = datetime.now().isoformat(timespec="seconds")
    if sid == "mercadolivre_busca":
        return _ml_search(ctx, {"q": q_pt, "pid": pid})
    if sid == "ebay":
        from ..connectors.sources5 import EbayBrowse
        EbayBrowse().run(Job(f"pesquisa:ebay:{_norm(q_en)}", {"pid": pid, "q": q_en}), ctx)
        return db.query("SELECT COUNT(*) AS n FROM market_listings WHERE source = 'ebay' AND query = ? AND day = ?", (q_en, ctx.today.isoformat()))[0]["n"]
    if sid == "google_ads_kp":
        from ..connectors.search import GoogleAdsKeywordPlanner
        kws = [q_pt if market == "BR" else q_en]
        GoogleAdsKeywordPlanner().run(Job(f"pesquisa:kp:{market}:{_norm(kws[0])}", {"geo": market, "keywords": kws}), ctx)
        return db.query("SELECT COUNT(*) AS n FROM search_observations WHERE source = 'google_ads_kp' AND country = ? AND collected_at >= ?",
                        (market, start))[0]["n"]
    if sid == "msads_kp":
        from ..connectors.sources5 import MicrosoftAdsKeywordPlanner
        kws = [q_pt if market == "BR" else q_en]
        MicrosoftAdsKeywordPlanner().run(Job(f"pesquisa:msads:{market}:{_norm(kws[0])}", {"cc": market, "keywords": kws}), ctx)
        return db.query("SELECT COUNT(*) AS n FROM search_observations WHERE source = 'msads_kp' AND country = ? AND collected_at >= ?",
                        (market, start))[0]["n"]
    if sid == "youtube":
        from ..connectors.content import YouTube
        YouTube().run(Job(f"youtube:pesquisa:{_norm(q_pt)}:{int(time.time())}", {"product_key": pid, "q": q_pt}), ctx)
        return db.query("SELECT COUNT(*) AS n FROM content_items WHERE source = 'youtube' AND query = ?", (q_pt,))[0]["n"]
    if sid == "gdelt":
        from ..connectors.sources5 import Gdelt
        Gdelt().run(Job(f"pesquisa:gdelt:{_norm(q_en)}", {"pid": pid, "q": q_en}), ctx)
        return db.query("SELECT COUNT(*) AS n FROM search_observations WHERE source = 'gdelt' AND term = ? AND value > 0", (q_en,))[0]["n"]
    raise ValueError(sid)


SOURCES = {
    "mercadolivre_busca": {"nome": "Mercado Livre — busca de anúncios", "capacidade": "marketplace_listings", "mercados": ["BR"],
                           "indicador": "anúncios e preços (não são vendas)", "modo": "rapida",
                           "acao_sem_dados": "verificar o termo; o Mercado Livre pode não ter anúncios para esta descrição"},
    "ebay": {"nome": "eBay Browse API", "capacidade": "marketplace_listings", "mercados": ["US"], "indicador": "anúncios e preços (não são vendas)",
             "modo": "rapida", "acao_sem_dados": "testar o nome em inglês mais comum do produto"},
    "google_ads_kp": {"nome": "Google Ads Keyword Planner", "capacidade": "search_volume", "mercados": ["BR", "US"],
                      "indicador": "volume mensal aproximado de buscas (12 meses)", "modo": "rapida",
                      "acao_sem_dados": "o Google não retornou ideias associáveis ao produto; testar sinônimos"},
    "msads_kp": {"nome": "Microsoft Advertising (Bing)", "capacidade": "search_volume", "mercados": ["BR", "US"],
                 "indicador": "volume mensal de buscas no Bing", "modo": "completa", "acao_sem_dados": "testar sinônimos"},
    "youtube": {"nome": "YouTube Data API", "capacidade": "product_search", "mercados": ["BR"], "indicador": "vídeos sobre o produto (não são avaliações de compradores)",
                "modo": "completa", "acao_sem_dados": "poucos vídeos recentes sobre o termo"},
    "gdelt": {"nome": "GDELT (notícias, público)", "capacidade": "news_mentions", "mercados": ["GLOBAL"],
              "indicador": "artigos de notícias por mês (atenção pública, não demanda)", "modo": "completa",
              "acao_sem_dados": "termo pouco citado na imprensa (não indica falta de demanda)"},
}
NOT_TARGETABLE = {
    "google_trends_rss": ("Google Trends (RSS diário)", "search_interest", "só publica as buscas em alta do dia; não consulta um produto específico"),
    "google_trends_bq": ("Google Trends (BigQuery público)", "search_interest", "tabelas de termos em alta por região; não há histórico de termo arbitrário"),
    "ml_trends": ("Mercado Livre — tendências", "keyword_ranking", "ranking geral de buscas; não consulta um termo específico"),
    "comexstat": ("Comex Stat", "trade_statistics", "agregado por NCM; consultado pela NCM candidata, nunca pelo produto"),
}


def plan(mode: str, markets: list[str]) -> list[tuple[str, str]]:
    """(fonte, mercado). Rápida: poucas fontes no mercado principal. Completa: tudo que for pertinente nos mercados escolhidos."""
    main = markets[0]
    out = []
    for sid, s in SOURCES.items():
        ms = [m for m in s["mercados"] if m in markets or m == "GLOBAL"]
        if mode == "rapida":
            if s["modo"] != "rapida":
                continue
            # rápida: mercado principal; para anúncios, se o principal não tiver a fonte, usa o mercado nativo dela
            ms = [main] if main in s["mercados"] else ([] if sid == "google_ads_kp" else s["mercados"][:1])
        elif not ms:
            ms = s["mercados"][:1] if s["capacidade"] == "marketplace_listings" else []
        out += [(sid, m) for m in ms]
    return out


def collect(db, ctx_fn, q_pt: str, q_en: str, pid: str | None, markets: list[str], mode: str, force: bool = False,
            research_id: int | None = None, cancelled=lambda: False) -> list[dict]:
    """Executa (ou reaproveita do cache) as consultas direcionadas. Uma fonte com erro não interrompe as demais."""
    ensure(db)
    from ..connectors.http import SourceError
    ctx = None
    try:
        ctx = ctx_fn()
    except Exception as e:  # noqa: BLE001
        return [{"id": sid, **_base(sid, m), "estado": "indisponível", "consulta_realizada": False, "registros": 0,
                 "motivo": f"contexto de sincronização indisponível ({type(e).__name__})", "acao": "reiniciar o GPI"} for sid, m in plan(mode, markets)]
    out = []
    planned = plan(mode, markets)
    for sid, s in SOURCES.items():
        if not any(p[0] == sid for p in planned) and mode == "rapida" and s["modo"] == "completa":
            out.append({"id": sid, **_base(sid, s["mercados"][0]), "estado": "ignorada (modo rápido)", "consulta_realizada": False,
                        "registros": 0, "motivo": "reservada para a pesquisa completa", "acao": "usar a pesquisa completa"})
    for sid, market in planned:
        b = _base(sid, market)
        if cancelled():
            out.append({"id": sid, **b, "estado": "cancelada", "consulta_realizada": False, "registros": 0, "motivo": "pesquisa cancelada", "acao": None})
            continue
        ok, why = _available(sid, ctx)
        b["autenticacao"] = "não exigida" if sid == "gdelt" else ("configurada" if ok else "ausente")
        if not ok:
            out.append({"id": sid, **b, "estado": "não autorizada", "consulta_realizada": False, "registros": 0, "motivo": why,
                        "acao": "configurar a integração na Central de Integrações"})
            continue
        q = q_en if (market in ("US", "GLOBAL") or sid in ("ebay", "gdelt")) else q_pt
        qn = _norm(q)
        last = db.query("SELECT * FROM research_source_runs WHERE source = ? AND market = ? AND query_norm = ? AND status IN ('com dados', 'sem dados') "
                        "ORDER BY id DESC LIMIT 1", (sid, market, qn))
        if last and not force:
            age = datetime.now() - datetime.fromisoformat(last[0]["at"])
            if age <= timedelta(days=TTL_DAYS.get(mode, 7)):
                out.append({"id": sid, **b, "estado": "cache válido" if last[0]["status"] == "com dados" else "sem dados",
                            "consulta_realizada": False, "registros": last[0]["n"], "ultima_coleta": last[0]["at"],
                            "motivo": None if last[0]["status"] == "com dados" else "a última consulta (dentro da validade do cache) não trouxe registros",
                            "acao": None if last[0]["status"] == "com dados" else s["acao_sem_dados"], "cache": f"válido ({age.days} dia(s))"})
                continue
            b["cache"] = f"expirado ({age.days} dia(s)) — consultado novamente"
        try:
            n = int(_run(sid, ctx, q_pt, q_en, pid, market) or 0)
            st, motivo, acao = ("com dados", None, None) if n else ("sem dados", "a fonte respondeu sem registros válidos para o termo", s["acao_sem_dados"])
        except SourceError as e:
            n = 0
            st = {"restrita": "não autorizada", "limite": "indisponível", "rede": "indisponível", "tls": "indisponível", "bloqueada": "indisponível",
                  "cancelada": "cancelada"}.get(e.kind, "falhou")
            motivo = str(e)[:300]
            acao = {"não autorizada": "reconectar a integração ou verificar as permissões do aplicativo",
                    "indisponível": "tentar mais tarde ou pedir à TI a liberação do endereço (cota, limite, rede ou proxy)"}.get(st, "ver o registro de diagnóstico")
        except Exception as e:  # noqa: BLE001
            n, st, motivo, acao = 0, "falhou", f"{type(e).__name__}: {str(e)[:200]}", "ver o registro de diagnóstico"
        now = datetime.now().isoformat(timespec="seconds")
        db.execute("INSERT INTO research_source_runs (source, market, query_norm, at, status, n, detail, research_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (sid, market, qn, now, st, n, motivo, research_id))
        out.append({"id": sid, **b, "estado": st, "consulta_realizada": st not in ("cancelada",) and not (st == "não autorizada" and "não conectado" in (motivo or "")),
                    "registros": n, "motivo": motivo, "acao": acao, "ultima_coleta": now, "termo": q})
    return out


def _base(sid, market):
    s = SOURCES[sid]
    return {"fonte": s["nome"], "capacidade": s["capacidade"], "mercado": market, "indicador": s["indicador"], "autenticacao": None,
            "estado_integracao": None, "ultima_coleta": None, "cache": None}


def diagnostics(db, collected: list[dict], local: dict, ncm_state: dict, visual_count: int) -> list[dict]:
    """Painel 'Fontes e cobertura desta investigação': consultas direcionadas + dados locais + fontes sem consulta por produto."""
    rows = []
    st = {r["source"]: r for r in db.query("SELECT source, state, last_success FROM source_status")}
    for c in collected:
        sid = "mercadolivre" if c["id"] == "mercadolivre_busca" else c["id"]
        rows.append({**c, "estado_integracao": (st.get(sid) or {}).get("state") or ("pública" if c["id"] == "gdelt" else "não sincronizada"),
                     "ultima_coleta": c.get("ultima_coleta") or (st.get(sid) or {}).get("last_success"), "tipo": "consulta direcionada"})
    rows.append({"id": "local", "fonte": "Banco local do GPI (sincronizações anteriores)", "capacidade": "historical_data", "mercado": "—",
                 "tipo": "dados locais", "estado": "com dados" if local.get("n") else "sem dados", "consulta_realizada": True,
                 "registros": local.get("n", 0), "motivo": None if local.get("n") else "produto sem observações anteriores no banco local",
                 "acao": None if local.get("n") else "monitorar o produto para acumular histórico", "autenticacao": "não exigida"})
    for sid, (nome, cap, why) in NOT_TARGETABLE.items():
        if sid == "comexstat":
            n = ncm_state.get("series", 0)
            rows.append({"id": sid, "fonte": nome, "capacidade": cap, "mercado": "BR", "tipo": "por NCM", "autenticacao": "não exigida",
                         "estado": "com dados" if n else "sem dados", "consulta_realizada": bool(ncm_state.get("candidatas")), "registros": n,
                         "motivo": None if n else ("NCM ainda não validada — sem candidata na tabela NCM" if not ncm_state.get("candidatas")
                                                   else "sem série local para as NCM candidatas"),
                         "acao": None if n else "carregar a tabela NCM (Conformidade) e validar a NCM com o despachante", "estado_integracao": (st.get(sid) or {}).get("state"),
                         "ultima_coleta": (st.get(sid) or {}).get("last_success")})
            continue
        rows.append({"id": sid, "fonte": nome, "capacidade": cap, "mercado": "—", "tipo": "sem consulta por produto", "estado": "não suporta consulta direcionada",
                     "consulta_realizada": False, "registros": 0, "motivo": why, "acao": None, "autenticacao": "—",
                     "estado_integracao": (st.get(sid) or {}).get("state"), "ultima_coleta": (st.get(sid) or {}).get("last_success")})
    rows.append({"id": "visual", "fonte": "Catálogo visual local", "capacidade": "image_search", "mercado": "—", "tipo": "dados locais",
                 "estado": "contexto (não é evidência)" if visual_count else "sem dados", "consulta_realizada": False, "registros": visual_count,
                 "autenticacao": "não exigida",
                 "motivo": None if visual_count >= 20 else (f"{visual_count} imagem(ns) no catálogo; cobertura insuficiente para busca ampla" if visual_count
                                                            else "catálogo visual vazio"),
                 "acao": None if visual_count >= 20 else "adicionar imagens de referência em Pesquisa por Imagem"})
    return rows


def coverage(rows: list[dict]) -> dict:
    useful = [r for r in rows if r["estado"] in USEFUL and r.get("registros")]
    queried = [r for r in rows if r.get("tipo") == "consulta direcionada"]
    return {"fontes_com_evidencia": len(useful), "fontes_consultadas": sum(1 for r in queried if r["consulta_realizada"]),
            "fontes_previstas": len(queried), "registros_validos": sum(r.get("registros") or 0 for r in useful),
            "capacidades_cobertas": sorted({r["capacidade"] for r in useful}),
            "fontes": [r["fonte"] for r in useful]}

