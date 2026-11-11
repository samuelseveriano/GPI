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

import json
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
          "não suporta consulta direcionada": "a fonte não permite consultar um produto arbitrário",
          "não cobre o mercado": "a fonte não fornece dados para o mercado selecionado (não é usada como substituta)",
          "limite de requisições": "Limite de requisições atingido (Retry-After respeitado; novas tentativas limitadas)",
          "bloqueada pela rede": "proxy, túnel ou inspeção TLS da rede impediu a conexão"}
USEFUL = {"com dados", "cache válido"}
TTL_DAYS = {"rapida": 7, "completa": 1}


def ensure(db):
    S.ensure(db)
    db.execute(RUNS_SQL)
    have = {r["name"] for r in db.query("PRAGMA table_info(research_source_runs)")}
    for col in ("cache_key", "lang", "product_id", "params"):            # colunas da revisão final (ADD COLUMN, sem perda)
        if col not in have:
            db.execute(f"ALTER TABLE research_source_runs ADD COLUMN {col} TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS idx_rsr ON research_source_runs(source, market, query_norm, at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_rsr_key ON research_source_runs(cache_key, id)")


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
    try:
        r = ctx.http.request_json(url, headers={"Authorization": f"Bearer {tok}"}, ttl=0)
    except SourceError as e:
        if getattr(e, "status", None) != 401:
            raise
        # 401: token recusado antes do vencimento local → UMA renovação pelo fluxo OAuth oficial (refresh token) e nova tentativa
        c = ctx.creds.get("mercadolivre")
        if not c.get("refresh_token"):
            raise
        ctx.creds.set("mercadolivre", {"expires_at": "0"})
        tok = ml_token(ctx.http, ctx.creds)
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
                           "geo": "Brasil (site MLB)", "indicador": "anúncios e preços anunciados (não são vendas)", "modo": "rapida",
                           "acao_sem_dados": "verificar o termo; o Mercado Livre pode não ter anúncios para esta descrição"},
    "ebay": {"nome": "eBay Browse API", "capacidade": "marketplace_listings", "mercados": ["US"], "geo": "Estados Unidos (EBAY_US)",
             "indicador": "anúncios e preços anunciados (não são vendas)", "modo": "rapida", "acao_sem_dados": "testar o nome em inglês mais comum do produto"},
    "google_ads_kp": {"nome": "Google Ads Keyword Planner", "capacidade": "search_volume", "mercados": ["BR", "US"], "geo": "por país (geoTarget)",
                      "indicador": "volume mensal aproximado de buscas (12 meses)", "modo": "rapida",
                      "acao_sem_dados": "o Google não retornou ideias associáveis ao produto; testar sinônimos"},
    "msads_kp": {"nome": "Microsoft Advertising (Bing)", "capacidade": "search_volume", "mercados": ["BR", "US"], "geo": "por país",
                 "indicador": "volume mensal de buscas no Bing", "modo": "completa", "acao_sem_dados": "testar sinônimos"},
    "youtube": {"nome": "YouTube Data API", "capacidade": "product_search", "mercados": ["BR"], "geo": "Brasil (regionCode BR)",
                "indicador": "vídeos sobre o produto (não são avaliações de compradores)", "modo": "completa", "acao_sem_dados": "poucos vídeos recentes sobre o termo"},
    "gdelt": {"nome": "GDELT (notícias, público)", "capacidade": "news_mentions", "mercados": ["GLOBAL"], "geo": "global (sem segmentação por país)",
              "indicador": "artigos de notícias por mês (atenção pública, não demanda)", "modo": "completa",
              "acao_sem_dados": "termo pouco citado na imprensa (não indica falta de demanda)"},
}
NOT_TARGETABLE = {
    "google_trends_rss": ("Google Trends (RSS diário)", "search_interest", "só publica as buscas em alta do dia; não consulta um produto específico"),
    "google_trends_bq": ("Google Trends (BigQuery público)", "search_interest", "tabelas de termos em alta por região; não há histórico de termo arbitrário"),
    "ml_trends": ("Mercado Livre — tendências", "keyword_ranking", "ranking geral de buscas; não consulta um termo específico"),
    "comexstat": ("Comex Stat", "trade_statistics", "agregado por NCM; consultado pela NCM candidata, nunca pelo produto"),
}
NO_COVERAGE = "Não existem fontes de consulta direcionada disponíveis para este mercado."
METHOD_VERSION = "v091.2"
PARAMS = {"mercadolivre_busca": "limit=50", "ebay": "limit=50;EBAY_US", "google_ads_kp": "12m;GOOGLE_SEARCH", "msads_kp": "12m;Monthly",
          "youtube": "180d;review|teste|unboxing", "gdelt": "12m;timelinevolraw"}
MIN_REPEAT_MIN = 10          # mesmo com "Atualizar fontes", a mesma consulta não é repetida em menos de 10 minutos


def plan(mode: str, markets: list[str]) -> list[tuple[str, str, str]]:
    """(fonte, mercado consultado, papel). Papel: principal | comparativo | global.
    * Rápida: só fontes do mercado PRINCIPAL (nunca o mercado nativo de outra fonte como substituto).
    * Completa: principal + comparativos escolhidos + fontes globais (rotuladas GLOBAL, nunca atribuídas ao Brasil)."""
    main, comps = markets[0], [m for m in markets[1:] if m != markets[0]]
    out = []
    for sid, s in SOURCES.items():
        if mode == "rapida" and s["modo"] != "rapida":
            continue
        if main in s["mercados"]:
            out.append((sid, main, "principal"))
        if mode == "completa":
            out += [(sid, m, "comparativo") for m in comps if m in s["mercados"]]
            if "GLOBAL" in s["mercados"]:
                out.append((sid, "GLOBAL", "global"))
    return out


def market_coverage(mode: str, markets: list[str]) -> dict:
    p = plan(mode, markets)
    cov = {}
    for i, m in enumerate(markets):
        srcs = sorted({sid for sid, mk, _ in p if mk == m})
        role = "principal" if i == 0 else ("comparativo" if mode == "completa" else "comparativo (só na pesquisa completa)")
        cov[m] = {"papel": role, "fontes": [SOURCES[x]["nome"] for x in srcs], "mensagem": None if srcs or (i and mode != "completa") else NO_COVERAGE}
    if any(mk == "GLOBAL" for _, mk, _ in p):
        cov["GLOBAL"] = {"papel": "global", "fontes": [SOURCES[x]["nome"] for x, mk, _ in p if mk == "GLOBAL"],
                         "mensagem": "Fonte global — não é atribuída a nenhum país."}
    return cov


def cache_key(sid, market, lang, term, pid) -> str:
    import hashlib
    return hashlib.sha1("|".join([sid, market, lang or "", _norm(term), pid or "", PARAMS.get(sid, ""), METHOD_VERSION]).encode()).hexdigest()[:32]


def _lang(sid, market):
    return "en" if market in ("US", "GLOBAL") or sid in ("ebay", "gdelt") else "pt"


def collect(db, ctx_fn, q_pt: str, q_en: str, pid: str | None, markets: list[str], mode: str, force: bool = False,
            research_id: int | None = None, cancelled=lambda: False) -> list[dict]:
    """Executa (ou reaproveita do cache) as consultas direcionadas. Uma fonte com erro não interrompe as demais."""
    from ..connectors.http import SourceError
    from . import diagnostics as DG
    ensure(db)
    markets = list(dict.fromkeys(m.upper() for m in markets if m)) or ["BR"]
    planned = plan(mode, markets)
    try:
        ctx = ctx_fn()
    except Exception as e:  # noqa: BLE001
        return [{"id": sid, **_base(sid, m, role), "estado": "indisponível", "consulta_realizada": False, "registros": 0,
                 "motivo": f"contexto dos conectores indisponível ({type(e).__name__})", "acao": "reiniciar o GPI"} for sid, m, role in planned]
    out = []
    for sid, s in SOURCES.items():                      # transparência: o que NÃO foi consultado e por quê
        if any(p[0] == sid for p in planned):
            continue
        if mode == "rapida" and s["modo"] == "completa":
            st, why, act = "ignorada (modo rápido)", "reservada para a pesquisa completa", "usar a pesquisa completa"
        else:
            st = "não cobre o mercado"
            why = f"{s['nome']} cobre {s['geo']}; não é usada como substituta de {', '.join(markets)}"
            act = None if mode == "completa" else "incluir esse mercado na comparação (pesquisa completa)"
        out.append({"id": sid, **_base(sid, s["mercados"][0], "não consultado"), "estado": st, "consulta_realizada": False, "registros": 0,
                    "motivo": why, "acao": act})
    for sid, market, role in planned:
        b = _base(sid, market, role)
        s = SOURCES[sid]
        if cancelled():
            out.append({"id": sid, **b, "estado": "cancelada", "consulta_realizada": False, "registros": 0, "motivo": "pesquisa cancelada", "acao": None})
            continue
        ok, why = _available(sid, ctx)
        b["autenticacao"] = "não exigida" if sid == "gdelt" else ("configurada" if ok else "ausente")
        if not ok:
            out.append({"id": sid, **b, "estado": "não autorizada", "consulta_realizada": False, "registros": 0, "motivo": why,
                        "acao": "abrir a Central de Integrações", "central": _central(sid)})
            continue
        lang = _lang(sid, market)
        q = q_en if lang == "en" else q_pt
        ck = cache_key(sid, market, lang, q, pid)
        last = db.query("SELECT * FROM research_source_runs WHERE cache_key = ? AND status IN ('com dados', 'sem dados') ORDER BY id DESC LIMIT 1", (ck,))
        if last:
            age = datetime.now() - datetime.fromisoformat(last[0]["at"])
            fresh = age <= timedelta(days=TTL_DAYS.get(mode, 7))
            recent = age <= timedelta(minutes=MIN_REPEAT_MIN)
            if (fresh and not force) or recent:
                why_cache = (f"consulta idêntica há {int(age.total_seconds() // 60)} min — não repetida para respeitar os limites da API"
                             if force and recent else None)
                out.append({"id": sid, **b, "estado": "cache válido" if last[0]["status"] == "com dados" else "sem dados", "consulta_realizada": False,
                            "registros": last[0]["n"], "ultima_coleta": last[0]["at"], "termo": q,
                            "motivo": why_cache or (None if last[0]["status"] == "com dados" else "a última consulta (dentro da validade do cache) não trouxe registros"),
                            "acao": None if last[0]["status"] == "com dados" else s["acao_sem_dados"],
                            "cache": f"válido ({age.days} dia(s); chave: fonte+mercado+idioma+termo+produto+parâmetros+versão)"})
                continue
            b["cache"] = f"expirado ({age.days} dia(s)) — consultado novamente" if not force else "atualização forçada"
        diag = None
        try:
            n = int(_run(sid, ctx, q_pt, q_en, pid, market) or 0)
            st, motivo, acao = ("com dados", None, None) if n else ("sem dados", "a fonte respondeu sem registros válidos para o termo", s["acao_sem_dados"])
        except SourceError as e:
            n = 0
            diag = DG.classify(e)
            st, motivo, acao = ("cancelada", str(e), None) if e.kind == "cancelada" else (diag["consulta"], diag["mensagem"], diag["acao"])
        except Exception as e:  # noqa: BLE001
            n, st, motivo, acao = 0, "falhou", f"{type(e).__name__}: {str(e)[:200]}", "ver o registro de diagnóstico"
        now = datetime.now().isoformat(timespec="seconds")
        db.execute("INSERT INTO research_source_runs (source, market, query_norm, at, status, n, detail, research_id, cache_key, lang, product_id, params) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (sid, market, _norm(q), now, st, n, motivo, research_id, ck, lang, pid, PARAMS.get(sid)))
        out.append({"id": sid, **b, "estado": st, "consulta_realizada": True, "registros": n, "motivo": motivo, "acao": acao, "ultima_coleta": now,
                    "termo": q, "causa": (diag or {}).get("causa"), "http": (diag or {}).get("http"),
                    "central": _central(sid) if st == "não autorizada" else None})
    return out


DEPENDENT_RESULTS = ("intel08", "consumer", "opportunity3", "competition")


def _load(db, name):
    r = db.query("SELECT payload FROM analysis_results WHERE name = ?", (name,))
    return json.loads(r[0]["payload"]) if r else None


def _save(db, name, payload):
    db.execute("INSERT INTO analysis_results (name, created_at, payload) VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
               "created_at = excluded.created_at, payload = excluded.payload",
               (name, datetime.now().isoformat(timespec="seconds"), json.dumps(payload, ensure_ascii=False)))


def refresh_commercial(db, pids: set[str]) -> dict:
    """Nova oferta observada → recalcula SÓ os indicadores comerciais (competition) dos produtos afetados e as linhas
    desses produtos no Opportunity Engine, a partir dos demais resultados em cache (sem recalcular o banco inteiro)."""
    from ..market import reviews2
    from ..products import opportunity3
    pids = {p for p in pids if p}
    if not pids:
        return {"produtos": [], "recalculados": []}
    comp = reviews2.competition(db, only=pids, prev=_load(db, "competition"))
    _save(db, "competition", comp)
    done = ["competition"]
    cons = _load(db, "consumer")
    new = opportunity3.build(cons or {}, _load(db, "social"), _load(db, "reviews2"), comp, db)
    if cons is None:        # análise de busca invalidada/ausente: não grava uma oportunidade sem a busca (recalculada no próximo acesso)
        return {"produtos": sorted(pids), "recalculados": done, "opportunity3": new}
    prev = _load(db, "opportunity3")
    if prev and prev.get("produtos") is not None:
        rows = [r for r in prev["produtos"] if r["product_id"] not in pids] + [r for r in new["produtos"] if r["product_id"] in pids]
        order = {"Alta": 0, "Média": 1, "Baixa": 2, "Evidência insuficiente": 3}
        rows.sort(key=lambda r: (order.get(r["prioridade"], 4), -(r["indice"] if r["indice"] is not None else -1)))
        new = {**prev, "produtos": rows}
        new.pop("_gerado_em", None)
    _save(db, "opportunity3", new)
    done.append("opportunity3")
    return {"produtos": sorted(pids), "recalculados": done, "opportunity3": new}


def invalidate(db, res: list[dict], pid: str | None = None) -> list[str]:
    """Nova evidência de uma consulta direcionada → atualiza SÓ os resultados derivados dependentes. Volume de pesquisa
    invalida tudo o que depende de busca (recalculado no próximo acesso); anúncios recalculam na hora os indicadores
    comerciais e a oportunidade do produto afetado (sem reiniciar o GPI e sem recalcular o banco inteiro)."""
    fresh = [r for r in res if r.get("consulta_realizada") and r["estado"] == "com dados"]
    if not fresh:
        return []
    if any(r["capacidade"] == "search_volume" for r in fresh):
        names = list(DEPENDENT_RESULTS)
        try:
            db.execute("DELETE FROM analysis_results WHERE name IN (%s)" % ",".join("?" * len(names)), tuple(names))
        except Exception:  # noqa: BLE001
            return []
        return names
    pids = {pid} if pid else set()
    if not pids:
        return []
    try:
        return refresh_commercial(db, pids)["recalculados"]
    except Exception:  # noqa: BLE001 — falha no recálculo não pode derrubar a pesquisa; o próximo acesso recalcula
        db.execute("DELETE FROM analysis_results WHERE name IN ('competition', 'opportunity3')")
        return ["competition", "opportunity3"]


def _central(sid):
    return "#integracoes/" + {"mercadolivre_busca": "mercadolivre", "google_ads_kp": "google_ads", "msads_kp": "msads"}.get(sid, sid)


def _base(sid, market, role="principal"):
    s = SOURCES[sid]
    return {"fonte": s["nome"], "capacidade": s["capacidade"], "mercado": market, "papel": role, "cobertura_geografica": s["geo"],
            "indicador": s["indicador"], "autenticacao": None, "estado_integracao": None, "ultima_coleta": None, "cache": None}


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


COMMERCIAL_CAPS = {"search_volume", "marketplace_listings", "historical_data", "sales"}


def coverage(rows: list[dict]) -> dict:
    """Resumo das fontes. `fontes_com_evidencia` conta SÓ fontes com evidência COMERCIAL (volume autorizado, anúncios/preços,
    histórico local de procura); notícias, vídeos e imagens ficam em `fontes_contextuais`."""
    useful = [r for r in rows if r["estado"] in USEFUL and r.get("registros")]
    comm = [r for r in useful if r["capacidade"] in COMMERCIAL_CAPS]
    queried = [r for r in rows if r.get("tipo") == "consulta direcionada" and r["estado"] not in ("não cobre o mercado", "ignorada (modo rápido)")]
    return {"fontes_com_evidencia": len(comm), "fontes_contextuais": len(useful) - len(comm),
            "fontes_consultadas": sum(1 for r in queried if r["consulta_realizada"]), "fontes_previstas": len(queried),
            "registros_validos": sum(r.get("registros") or 0 for r in comm), "capacidades_cobertas": sorted({r["capacidade"] for r in comm}),
            "fontes": [r["fonte"] for r in comm]}
