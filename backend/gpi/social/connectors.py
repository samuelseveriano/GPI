"""
Conectores de redes sociais (v0.6) — somente APIs oficiais e autorizadas, sem raspagem.

* TikTok API for Business — Discovery (https://business-api.tiktok.com/open_api/v1.3/):
    GET discovery/trending_list/   hashtags populares por país (advertiser_id; date_range 1DAY/7DAY/30DAY/120DAY)
    GET discovery/search/          20 termos de busca em alta (business_id = open_id da conta TikTok)
    GET discovery/search/keyword/  20 termos recomendados para uma consulta (business_id)
  Cabeçalho "Access-Token". Resposta {code, message, data}; code ≠ 0 é erro. Caminhos conferidos no
  SDK Go bububa/tiktok-business (o portal de documentação da TikTok só abre com JavaScript). O
  caminho "/discovery/trending/search/" citado na especificação NÃO existe no SDK; o equivalente é
  "discovery/search/" e o caminho fica configurável (tiktok_search_path) caso a TikTok o altere.
  A TikTok Research API NÃO é usada: é restrita a pesquisa acadêmica não comercial.
* Instagram (Graph API com login do Facebook): ig_hashtag_search → top_media / recent_media.
  Exige o recurso "Instagram Public Content Access" aprovado na revisão do app e conta comercial
  ou de criador. Limite: 30 hashtags distintas por conta em 7 dias corridos — o GPI controla a cota
  (social_quota) e usa no máximo instagram_max_hashtags (padrão 25).
* Facebook Pages: publicações das páginas informadas pelo usuário (páginas que ele administra ou,
  com "Page Public Content Access" aprovado, páginas públicas). Só contagens: o texto é lido para
  identificar o produto e descartado.
* Biblioteca de Anúncios da Meta (ads_archive): a API só devolve anúncios comerciais que
  alcançaram a União Europeia (no Brasil, apenas anúncios políticos/eleitorais). O GPI conta anúncios
  ativos com o termo do produto em países da UE configuráveis e NÃO infere investimento nem alcance.
Somente agregados são guardados, com prazo de retenção por fonte (social/store.py).
"""
from __future__ import annotations

import json
import statistics
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from ..connectors.base import Connector, Job, require
from ..connectors.http import SourceError
from . import store as S

TT_API = "https://business-api.tiktok.com/open_api/v1.3/"


def _graph(ctx) -> str:
    return f"https://graph.facebook.com/{ctx.cfg.get('meta_graph_version', 'v23.0')}/"


def _top_products(ctx, n: int) -> list[dict]:
    """Produtos com mais evidências no catálogo (nomes em pt/en) — base das consultas por produto."""
    rows = ctx.store.db.query("SELECT product_id, canonical, name_pt, name_en FROM catalog_products WHERE level = 'produto' "
                              "ORDER BY evidence DESC, last_seen DESC LIMIT ?", (n,))
    return rows


def _tt_check(r) -> dict:
    require(isinstance(r, dict) and "code" in r, "TikTok: resposta sem 'code'")
    if r["code"] != 0:
        code, msg = r.get("code"), str(r.get("message") or "")[:200]
        kind = "limite" if code in (40100, 40133, 51021) or "limit" in msg.lower() else \
            "restrita" if code in (40001, 40002, 40104, 40105) or "permission" in msg.lower() or "auth" in msg.lower() else "http"
        raise SourceError(f"TikTok devolveu código {code}: {msg}", kind)
    return r.get("data") or {}


# ============================================================================ TikTok
class TikTokDiscovery(Connector):
    id = "tiktok"
    name = "TikTok API for Business — Discovery"
    reliability = "B"
    docs_url = "https://business-api.tiktok.com/portal/docs"
    description = "Hashtags populares por país, termos de busca em alta e termos recomendados por produto no TikTok."
    limitations = ("Exige conta TikTok for Business, app aprovado no portal e autorização OAuth. Posição e visualizações "
                   "medem ATENÇÃO na plataforma — não são compras nem volume de pesquisas na internet.")
    order = 80
    stage = 2

    def available(self, ctx):
        c = ctx.creds.get("tiktok") if ctx.creds else {}
        return bool(c.get("access_token") and (c.get("advertiser_id") or c.get("business_id")))

    @property
    def restricted_reason(self):  # type: ignore[override]
        return "Requer autorização da TikTok API for Business (Central de Integrações → TikTok)."

    def plan(self, ctx):
        c = ctx.creds.get("tiktok")
        d = ctx.today.isoformat()
        jobs = []
        if c.get("advertiser_id"):
            for cc in ctx.cfg.get("tiktok_countries", ["BR", "US"]):
                jobs.append(Job(f"tiktok:hashtags:{cc}:{d}", {"country": cc}, None, priority=2))
        if c.get("business_id"):
            jobs.append(Job(f"tiktok:search:{d}", {}, None, priority=2))
            wk = f"{ctx.today.isocalendar()[0]}-W{ctx.today.isocalendar()[1]:02d}"
            for p in _top_products(ctx, int(ctx.cfg.get("tiktok_max_products", 20))):
                jobs.append(Job(f"tiktok:kw:{p['product_id']}:{wk}", {"pid": p["product_id"], "q": p["name_pt"] or p["canonical"]},
                                None, priority=4))
        return jobs

    def _get(self, ctx, path, params):
        c = ctx.creds.get("tiktok")
        url = TT_API + path + "?" + urllib.parse.urlencode(params)
        return _tt_check(ctx.http.request_json(url, headers={"Access-Token": c["access_token"]}, ttl=6 * 3600, min_interval=1.0))

    @staticmethod
    def parse_hashtags(data: dict) -> list[dict]:
        lst = data.get("list")
        require(isinstance(lst, list), "TikTok trending_list: 'data.list' ausente")
        out = []
        for h in lst:
            require(isinstance(h, dict) and h.get("hashtag_name"), "TikTok trending_list: item sem 'hashtag_name'")
            out.append({"hashtag": str(h["hashtag_name"]), "posicao": int(h.get("rank_position") or 0) or None,
                        "variacao_posicao": h.get("rank_change"), "visualizacoes": h.get("views"), "publicacoes": h.get("posts"),
                        "id": h.get("hashtag_id")})
        return out

    def run(self, job, ctx):
        db, d = ctx.store.db, ctx.today.isoformat()
        c = ctx.creds.get("tiktok")
        if job.key.startswith("tiktok:hashtags:"):
            cc = job.params["country"]
            data = self._get(ctx, "discovery/trending_list/", {"advertiser_id": c["advertiser_id"], "discovery_type": "HASHTAG",
                                                               "country_code": cc, "date_range": ctx.cfg.get("tiktok_date_range", "7DAY")})
            items = self.parse_hashtags(data)
            with db.transaction():
                for h in items:
                    pid, it = S.identify(db, ctx.cfg, h["hashtag"], self.id, cc)
                    url = f"https://www.tiktok.com/tag/{urllib.parse.quote(h['hashtag'])}"
                    ex = {"variacao_posicao": h["variacao_posicao"], "janela": ctx.cfg.get("tiktok_date_range", "7DAY")}
                    if h["posicao"]:
                        S.store(db, ctx.cfg, self.id, cc, "hashtag", h["hashtag"], d, "dia", "tt_hashtag_posicao", 201 - h["posicao"],
                                "pontos (201 − posição entre as hashtags populares)", url, ex, pid, it["intencao"], it["comercial"], ctx.today)
                    for k, metric, unit in (("visualizacoes", "tt_hashtag_views", "visualizações na janela da API"),
                                            ("publicacoes", "tt_hashtag_posts", "publicações na janela da API")):
                        if isinstance(h[k], (int, float)):
                            S.store(db, ctx.cfg, self.id, cc, "hashtag", h["hashtag"], d, "dia", metric, h[k], unit, url, ex,
                                    pid, it["intencao"], it["comercial"], ctx.today)
            return [], []
        if job.key.startswith("tiktok:search:"):
            path = ctx.cfg.get("tiktok_search_path", "discovery/search/")
            data = self._get(ctx, path, {"business_id": c["business_id"]})
            kws = data.get("search_keywords")
            require(isinstance(kws, list), "TikTok search: 'search_keywords' ausente")
            cc = ctx.cfg.get("tiktok_account_country") or "CONTA"
            with db.transaction():
                for i, kw in enumerate(kws, start=1):
                    pid, it = S.identify(db, ctx.cfg, str(kw), self.id, cc if cc != "CONTA" else None)
                    S.store(db, ctx.cfg, self.id, cc, "palavra_chave", str(kw), d, "dia", "tt_busca_posicao", 21 - i,
                            "pontos (21 − posição entre os 20 termos de busca em alta no TikTok)", None, None,
                            pid, it["intencao"], it["comercial"], ctx.today)
            return [], []
        # termos recomendados para um produto: alimentam a descoberta (variações e termos relacionados)
        data = self._get(ctx, "discovery/search/keyword/", {"business_id": c["business_id"], "query": job.params["q"][:255]})
        kws = data.get("search_keywords") or []
        require(isinstance(kws, list), "TikTok search/keyword: 'search_keywords' ausente")
        with db.transaction():
            for kw in kws:
                S.identify(db, ctx.cfg, str(kw), self.id, None)
        return [], []


# ============================================================================ Meta (Instagram, Facebook, Biblioteca de Anúncios)
def _meta_get(ctx, path, params):
    c = ctx.creds.get("meta")
    if not c.get("access_token"):
        raise SourceError("Meta não conectada: use 'Conectar' na Central de Integrações", "restrita")
    url = _graph(ctx) + path + "?" + urllib.parse.urlencode({**params, "access_token": c["access_token"]})
    r = ctx.http.request_json(url, ttl=3 * 3600, min_interval=0.5)
    require(isinstance(r, dict), "Meta: resposta não é um objeto")
    if r.get("error"):
        e = r["error"]
        code = e.get("code")
        kind = "limite" if code in (4, 17, 32, 613) else "restrita" if code in (10, 100, 190, 200) else "http"
        raise SourceError(f"Meta devolveu erro {code}: {str(e.get('message'))[:200]}", kind)
    return r


class InstagramHashtags(Connector):
    id = "instagram"
    name = "Instagram — hashtags (Graph API)"
    reliability = "B"
    docs_url = "https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/hashtag-search"
    description = "Engajamento das publicações principais e volume de publicações recentes em hashtags de produtos."
    limitations = ("Exige conta comercial/criador e o recurso Instagram Public Content Access aprovado pela Meta. "
                   "30 hashtags distintas por 7 dias. Curtidas e publicações medem atenção, não demanda.")
    order = 81
    stage = 2

    def available(self, ctx):
        from ..integrations.meta import module_ok
        c = ctx.creds.get("meta") if ctx.creds else {}
        return bool(module_ok(c, "instagram") and c.get("ig_user_id"))

    @property
    def restricted_reason(self):  # type: ignore[override]
        return "Requer conexão Meta com conta profissional do Instagram e o recurso Instagram Public Content Access."

    def plan(self, ctx):
        used = S.quota_used(ctx.store.db, self.id, ctx.today)
        cap = min(int(ctx.cfg.get("instagram_max_hashtags", 25)), 30)
        wk = f"{ctx.today.isocalendar()[0]}-W{ctx.today.isocalendar()[1]:02d}"
        jobs = []
        for p in _top_products(ctx, 60):
            tag = "".join(ch for ch in (p["name_pt"] or p["canonical"]).lower() if ch.isalnum())
            if len(tag) < 4:
                continue
            if tag not in used and len(used) >= cap:
                continue                                  # sem cota: hashtags já consultadas na semana continuam
            used.add(tag)
            jobs.append(Job(f"instagram:tag:{tag}:{wk}", {"tag": tag, "pid": p["product_id"]}, None, priority=4))
        return jobs

    @staticmethod
    def aggregate(top: list[dict], recent: list[dict], now: datetime) -> dict:
        likes = [m["like_count"] for m in top if isinstance(m.get("like_count"), int)]
        comments = [m["comments_count"] for m in top if isinstance(m.get("comments_count"), int)]
        r24 = 0
        for m in recent:
            ts = m.get("timestamp")
            try:
                t = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S") if ts else None
            except ValueError:
                t = None
            if t and now - t <= timedelta(hours=24):
                r24 += 1
        return {"top_n": len(top), "curtidas_mediana": statistics.median(likes) if likes else None,
                "comentarios_mediana": statistics.median(comments) if comments else None, "recentes_24h": r24,
                "recentes_lidas": len(recent)}

    def run(self, job, ctx):
        db, c = ctx.store.db, ctx.creds.get("meta")
        tag = job.params["tag"]
        r = _meta_get(ctx, "ig_hashtag_search", {"user_id": c["ig_user_id"], "q": tag})
        data = r.get("data") or []
        S.quota_add(db, self.id, tag, ctx.today)          # a consulta conta na cota mesmo sem resultado
        if not data:
            return [], []
        hid = data[0]["id"]
        fields = "id,media_type,like_count,comments_count,timestamp,permalink"
        top = (_meta_get(ctx, f"{hid}/top_media", {"user_id": c["ig_user_id"], "fields": fields, "limit": 50}).get("data") or [])
        recent = (_meta_get(ctx, f"{hid}/recent_media", {"user_id": c["ig_user_id"], "fields": "id,timestamp", "limit": 50}).get("data") or [])
        agg = self.aggregate(top, recent, datetime.now(timezone.utc).replace(tzinfo=None))
        pid, it = S.identify(db, ctx.cfg, tag, self.id, None)
        pid = pid or job.params.get("pid")
        url = f"https://www.instagram.com/explore/tags/{urllib.parse.quote(tag)}/"
        d = ctx.today.isoformat()
        with db.transaction():
            if agg["curtidas_mediana"] is not None:
                S.store(db, ctx.cfg, self.id, "CONTA", "hashtag", tag, d, "dia", "ig_top_curtidas", agg["curtidas_mediana"],
                        "curtidas por publicação (mediana das publicações principais)", url, {"publicacoes_top": agg["top_n"]},
                        pid, it["intencao"], it["comercial"], ctx.today)
            if agg["comentarios_mediana"] is not None:
                S.store(db, ctx.cfg, self.id, "CONTA", "hashtag", tag, d, "dia", "ig_top_comentarios", agg["comentarios_mediana"],
                        "comentários por publicação (mediana das publicações principais)", url, None, pid, it["intencao"], it["comercial"], ctx.today)
            S.store(db, ctx.cfg, self.id, "CONTA", "hashtag", tag, d, "dia", "ig_recentes_24h", agg["recentes_24h"],
                    "publicações nas últimas 24 h (a API devolve no máximo 50)", url, {"lidas": agg["recentes_lidas"]},
                    pid, it["intencao"], it["comercial"], ctx.today)
        return [], []


class FacebookPages(Connector):
    id = "facebook"
    name = "Facebook — páginas comerciais (Graph API)"
    reliability = "B"
    docs_url = "https://developers.facebook.com/docs/pages-api"
    description = "Publicações de páginas comerciais informadas por você que citam produtos do catálogo, com reações, comentários e compartilhamentos."
    limitations = ("Páginas que você administra, ou páginas públicas somente com o recurso Page Public Content Access aprovado. "
                   "Mede atenção ao conteúdo da página, não vendas.")
    order = 82
    stage = 2

    def available(self, ctx):
        from ..integrations.meta import module_ok
        c = ctx.creds.get("meta") if ctx.creds else {}
        return bool(module_ok(c, "facebook") and ctx.cfg.get("facebook_pages"))

    @property
    def restricted_reason(self):  # type: ignore[override]
        return "Requer conexão Meta e a lista de páginas a acompanhar (Configurações → Facebook)."

    def plan(self, ctx):
        wk = f"{ctx.today.isocalendar()[0]}-W{ctx.today.isocalendar()[1]:02d}"
        return [Job(f"facebook:page:{p}:{wk}", {"page": p}, None, priority=4) for p in ctx.cfg.get("facebook_pages", [])[:20]]

    def run(self, job, ctx):
        db = ctx.store.db
        since = int((datetime.now(timezone.utc) - timedelta(days=int(ctx.cfg.get("facebook_days", 90)))).timestamp())
        r = _meta_get(ctx, f"{urllib.parse.quote(str(job.params['page']))}/posts",
                      {"fields": "created_time,message,permalink_url,shares,reactions.summary(total_count).limit(0),"
                                 "comments.summary(total_count).limit(0)", "since": since, "limit": 100})
        posts = r.get("data")
        require(isinstance(posts, list), "Facebook posts: 'data' ausente")
        agg = defaultdict(lambda: {"n": 0, "inter": 0})
        from ..products.catalog import Catalog
        cat = Catalog(db, ctx.cfg)
        for p in posts:
            msg = p.get("message") or ""
            m = cat.match(msg[:500]) if msg else None        # o texto é usado só aqui e descartado
            if not m:
                continue
            month = (p.get("created_time") or "")[:7]
            if len(month) != 7:
                continue
            inter = int(((p.get("reactions") or {}).get("summary") or {}).get("total_count") or 0) + \
                int(((p.get("comments") or {}).get("summary") or {}).get("total_count") or 0) + int((p.get("shares") or {}).get("count") or 0)
            a = agg[(m["familia"], month)]
            a["n"] += 1
            a["inter"] += inter
        page = str(job.params["page"])
        with db.transaction():
            for (pid, month), a in agg.items():
                url = f"https://www.facebook.com/{urllib.parse.quote(page)}"
                S.store(db, ctx.cfg, self.id, "CONTA", "pagina", f"{page} · {pid}", month + "-01", "mes", "fb_mencoes", a["n"],
                        "publicações da página que citam o produto, por mês", url, None, pid, "comercial", 1, ctx.today)
                S.store(db, ctx.cfg, self.id, "CONTA", "pagina", f"{page} · {pid}", month + "-01", "mes", "fb_interacoes", a["inter"],
                        "reações + comentários + compartilhamentos nessas publicações, por mês", url, None, pid, "comercial", 1, ctx.today)
        return [], []


class MetaAdLibrary(Connector):
    id = "meta_ads"
    name = "Biblioteca de Anúncios da Meta (API)"
    reliability = "B"
    docs_url = "https://www.facebook.com/ads/library/api/"
    description = "Quantidade de anúncios ativos que citam o produto, em países da União Europeia (sinal de atividade publicitária)."
    limitations = ("A API só inclui anúncios comerciais que alcançaram a UE; no Brasil, só anúncios políticos/eleitorais. "
                   "Exige verificação de identidade na Meta. Contagem de anúncios não indica investimento, alcance nem vendas.")
    order = 83
    stage = 2

    def available(self, ctx):
        from ..integrations.meta import module_ok
        c = ctx.creds.get("meta") if ctx.creds else {}
        return bool(module_ok(c, "meta_ads") and ctx.cfg.get("meta_ads_enabled", False))

    @property
    def restricted_reason(self):  # type: ignore[override]
        return "Requer conexão Meta com acesso à API da Biblioteca de Anúncios (identidade verificada) e ativação em Configurações."

    def plan(self, ctx):
        wk = f"{ctx.today.isocalendar()[0]}-W{ctx.today.isocalendar()[1]:02d}"
        return [Job(f"meta_ads:{p['product_id']}:{wk}", {"pid": p["product_id"], "q": p["name_en"] or p["canonical"]}, None, priority=5)
                for p in _top_products(ctx, int(ctx.cfg.get("meta_ads_max_products", 20)))]

    def run(self, job, ctx):
        countries = [c.upper() for c in ctx.cfg.get("meta_ads_countries", ["DE", "FR", "ES", "IT", "PT"])][:10]
        params = {"search_terms": job.params["q"][:100], "ad_reached_countries": json.dumps(countries), "ad_type": "ALL",
                  "ad_active_status": "ACTIVE", "fields": "id", "limit": 100}
        n, path, pages = 0, "ads_archive", 0
        while pages < 5:
            r = _meta_get(ctx, path, params)
            data = r.get("data")
            require(isinstance(data, list), "Biblioteca de Anúncios: 'data' ausente")
            n += len(data)
            pages += 1
            nxt = ((r.get("paging") or {}).get("cursors") or {}).get("after")
            if not nxt or len(data) < 100:
                break
            params = {**params, "after": nxt}
        url = "https://www.facebook.com/ads/library/?" + urllib.parse.urlencode(
            {"active_status": "active", "ad_type": "all", "q": job.params["q"], "search_type": "keyword_unordered"})
        S.store(ctx.store.db, ctx.cfg, self.id, "UE", "anuncios", job.params["q"], ctx.today.isoformat(), "dia", "meta_anuncios", n,
                f"anúncios ativos encontrados (máx. 500) em {', '.join(countries)}", url, {"paises": countries, "truncado": n >= 500},
                job.params["pid"], "comercial", 1, ctx.today)
        return [], []


def social_connectors():
    return [TikTokDiscovery(), InstagramHashtags(), FacebookPages(), MetaAdLibrary()]
