"""
Conectores de conteúdo (Fase 3): YouTube Data API, Reddit, feeds RSS e Google Notícias.

Guardam itens de conteúdo (título, trecho curto, link, data, métricas) na tabela content_items,
sempre com o link original. Regras de uso respeitadas:
  * YouTube: só a API oficial (chave do usuário); sem download de vídeos nem transcrições;
    cota diária limitada pelo GPI; dados atualizados ou apagados em até 30 dias; dados do
    YouTube não são misturados com outras fontes nem usados em métricas derivadas complexas
    (ex.: análise de sentimento), conforme as políticas de desenvolvedor do YouTube.
  * Reddit: OAuth "installed client" (sem login de usuário); exige confirmação de uso autorizado.
  * RSS: feeds publicados pelos próprios sites; guarda manchete, resumo curto e link.
  * Google Notícias: somente após aceite explícito dos termos (opt-in).
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from ..market import taxonomy as tx
from ..market.store import now_iso
from .base import Connector, FormatError, Job, require
from .http import SourceError

RSS_DEFAULT = [
    {"nome": "Tecnoblog", "url": "https://tecnoblog.net/feed/", "idioma": "pt"},
    {"nome": "Canaltech", "url": "https://canaltech.com.br/rss/", "idioma": "pt"},
    {"nome": "Olhar Digital", "url": "https://olhardigital.com.br/feed/", "idioma": "pt"},
    {"nome": "TecMundo", "url": "https://rss.tecmundo.com.br/feed", "idioma": "pt"},
    {"nome": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "idioma": "en"},
    {"nome": "Engadget", "url": "https://www.engadget.com/rss.xml", "idioma": "en"},
]
VIDEO_TYPES = {
    "review": ["review", "analise", "avaliacao", "vale a pena", "opiniao"],
    "unboxing": ["unboxing", "abrindo a caixa", "desembalando"],
    "comparativo": [" vs ", "versus", "comparativo", "comparison", "qual comprar", "qual o melhor"],
    "teste": ["teste", "test", "testando", "testei", "durabilidade"],
    "reclamação": ["problema", "defeito", "nao compre", "don't buy", "dont buy", "golpe", "arrependi", "quebrou"],
    "lançamento": ["lancamento", "launch", "novo", "new", "2026", "2025"],
    "recomendação": ["melhores", "best", "top ", "recomendo", "recomendados", "guia de compra", "buying guide"],
}


# --------------------------------------------------------------------------- utilidades
def clean_html(s: str, limit: int = 400) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(re.sub(r"\s+", " ", s)).strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def _date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0 e Atom. Rejeita DTD/entidades (proteção contra XML malicioso)."""
    head = xml_text[:4000].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in xml_text.upper():
        raise FormatError("feed com DTD/entidades rejeitado por segurança")
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as e:
        raise FormatError(f"feed XML inválido ({e})")
    items = []
    ns_atom = "{http://www.w3.org/2005/Atom}"
    for it in root.iter("item"):
        items.append({"title": clean_html(it.findtext("title") or "", 300), "url": (it.findtext("link") or "").strip(),
                      "date": _date(it.findtext("pubDate")), "summary": clean_html(it.findtext("description") or ""),
                      "id": (it.findtext("guid") or it.findtext("link") or "").strip()})
    for it in root.iter(ns_atom + "entry"):
        link = it.find(ns_atom + "link")
        url = link.get("href") if link is not None else ""
        items.append({"title": clean_html(it.findtext(ns_atom + "title") or "", 300), "url": url,
                      "date": _date(it.findtext(ns_atom + "published") or it.findtext(ns_atom + "updated")),
                      "summary": clean_html(it.findtext(ns_atom + "summary") or it.findtext(ns_atom + "content") or ""),
                      "id": it.findtext(ns_atom + "id") or url})
    require(root.tag in ("rss", ns_atom + "feed") or items, "documento não é RSS nem Atom")
    return [i for i in items if i["title"] and i["url"]]


class ProductMatcher:
    """Associa textos aos produtos conhecidos (nomes pt/en/zh normalizados)."""

    def __init__(self, products: list[dict]):
        self.rules = []
        for p in products:
            if not p["product_key"].startswith("wiki:"):
                continue
            for n in (p.get("name_pt"), p.get("name_en"), p.get("name_zh")):
                toks = [t for t in tx.normalize_tokens(n or "") if len(t) > 1]
                if toks:
                    self.rules.append((p["product_key"], set(toks), len(toks)))

    def match(self, text: str) -> str | None:
        toks = set(tx.normalize_tokens(text))
        best = None
        for key, need, n in self.rules:
            if need <= toks and (best is None or n > best[1]):
                best = (key, n)
        return best[0] if best else None


def keywords(ctx, limit: int, lang: str = "pt") -> list[tuple[str, str]]:
    """Palavras-chave geradas dos produtos já identificados, priorizados pelo ranking."""
    prods = {p["product_key"]: p for p in ctx.store.products() if p["product_key"].startswith("wiki:")}
    order = [i["product_key"] for i in (ctx.store.load_result("opportunities") or {}).get("itens", [])]
    keys = [k for k in order if k in prods] + [k for k in prods if k not in order]
    out = []
    for k in keys:
        p = prods[k]
        name = (p.get("name_pt") if lang == "pt" else p.get("name_en")) or p.get("name_en")
        if name:
            out.append((k, re.sub(r"\s*\(.*?\)", "", name)))
    return out[:limit]


def youtube_queries(ctx, limit: int) -> list[tuple[str, str]]:
    """v0.6.1: consultas do YouTube a partir do catálogo canônico (o mesmo usado pela inteligência de consumo),
    priorizado por evidências; os produtos da Fase 2 (wiki:) completam a lista. A chave gravada no vídeo é o
    product_id do catálogo, o que permite filtrar a página por produto e categoria."""
    try:
        rows = ctx.store.db.query("SELECT product_id, canonical, name_pt FROM catalog_products WHERE level = 'produto' "
                                  "ORDER BY evidence DESC, last_seen DESC LIMIT ?", (limit * 2,))
    except Exception:  # noqa: BLE001 — banco anterior à migração v4
        rows = []
    cat = [(r["product_id"], re.sub(r"\s*\(.*?\)", "", r["name_pt"] or r["canonical"] or "").strip()) for r in rows]
    wiki = keywords(ctx, limit)
    out, seen = [], set()
    for i in range(max(len(cat), len(wiki))):          # intercalados: catálogo e produtos priorizados da Fase 2
        for lst in (cat, wiki):
            if i < len(lst):
                k, q = lst[i]
                if q and q.lower() not in seen:
                    seen.add(q.lower())
                    out.append((k, q))
    return out[:limit]


def week_tag(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# --------------------------------------------------------------------------- RSS
class RssFeeds(Connector):
    id, name, order = "rss", "Feeds RSS de sites especializados", 70
    reliability = "B"
    docs_url = "https://www.rssboard.org/rss-specification"
    description = "Manchetes de sites de tecnologia e reviews (lista editável na Central de Integrações)."
    limitations = "Somente manchete, resumo curto e link; cobertura histórica limitada ao que o feed publica (dias/semanas)."

    def plan(self, ctx):
        feeds = ctx.cfg.get("rss_feeds") or RSS_DEFAULT
        return [Job(f"rss:{f['url']}:{ctx.today.isoformat()}", {"feed": f}, refresh_days=None, priority=3) for f in feeds]

    def run(self, job, ctx):
        f = job.params["feed"]
        items = parse_feed(ctx.http.request_text(f["url"], ttl=6 * 3600, min_interval=1.0))
        rows = [{"item_id": it["id"] or it["url"], "kind": "artigo", "title": it["title"], "text": it["summary"],
                 "url": it["url"], "author": f["nome"], "published_at": it["date"], "lang": f.get("idioma"),
                 "query": None, "metrics": None} for it in items]
        ctx.content.upsert(self.id, rows)
        return [], []


class GoogleNews(Connector):
    id, name, order = "google_news", "Google Notícias (RSS)", 72
    stage = 2          # consultas montadas a partir dos produtos descobertos na etapa 1
    reliability = "B"
    docs_url = "https://news.google.com/"
    description = "Notícias recentes sobre os produtos identificados (busca por palavra-chave)."
    limitations = "Requer aceite dos termos do Google pelo usuário (opt-in). Manchete e link apenas."

    def available(self, ctx):
        return bool(ctx.cfg.get("google_news_optin"))

    @property
    def restricted_reason(self):  # type: ignore[override]
        return "Desativado até o aceite explícito dos termos de uso na Central de Integrações (opt-in)."

    def plan(self, ctx):
        wk = week_tag(ctx.today)
        return [Job(f"gnews:{k}:{wk}", {"product_key": k, "q": q}, None, priority=4) for k, q in keywords(ctx, 15)]

    def run(self, job, ctx):
        q = job.params["q"]
        url = ("https://news.google.com/rss/search?" +
               urllib.parse.urlencode({"q": q, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}))
        items = parse_feed(ctx.http.request_text(url, ttl=12 * 3600, min_interval=2.0))
        rows = [{"item_id": it["id"] or it["url"], "kind": "noticia", "title": it["title"], "text": it["summary"],
                 "url": it["url"], "author": "Google Notícias", "published_at": it["date"], "lang": "pt",
                 "query": q, "product_key": job.params["product_key"], "metrics": None} for it in items]
        ctx.content.upsert(self.id, rows)
        return [], []


# --------------------------------------------------------------------------- YouTube
class YouTube(Connector):
    id, name, order = "youtube", "YouTube Data API v3", 74
    stage = 2          # consultas montadas a partir dos produtos descobertos na etapa 1
    reliability = "B"
    docs_url = "https://developers.google.com/youtube/v3/docs"
    description = ("Vídeos de review, unboxing, comparativos, testes e lançamentos sobre os produtos identificados, "
                   "com visualizações, curtidas e comentários públicos.")
    limitations = ("Cota diária da chave (busca = 100 unidades). Dados exibidos em página própria, atualizados ou "
                   "excluídos em até 30 dias, sem combinação com outras fontes (políticas do YouTube).")
    API = "https://www.googleapis.com/youtube/v3/"

    def available(self, ctx):
        return bool(ctx.creds and ctx.creds.get("youtube").get("api_key"))

    @property
    def restricted_reason(self):  # type: ignore[override]
        return "Requer uma chave gratuita da YouTube Data API v3 (Central de Integrações → YouTube)."

    REGION = "BR"                       # país da consulta (regionCode) — exibido na página

    def plan(self, ctx):
        wk = week_tag(ctx.today)
        n = max(1, int(ctx.cfg.get("youtube_daily_units", 3000)) // 150)
        if getattr(ctx, "force", False):
            # "Atualizar agora": poucas buscas novas (padrão 5 = ~505 unidades), nunca acima do limite diário do GPI
            m = max(1, min(n, int(ctx.cfg.get("youtube_manual_max_searches", 5))))
            stamp = datetime.now().strftime("%Y-%m-%dT%H")
            jobs = [Job(f"youtube:manual:{k}:{stamp}", {"product_key": k, "q": q}, None, priority=2)
                    for k, q in youtube_queries(ctx, m)]
            jobs.append(Job(f"youtube:refresh:{ctx.today.isoformat()}", {}, None, priority=5))
            return jobs
        jobs = [Job(f"youtube:search:{k}:{wk}", {"product_key": k, "q": q}, None, priority=3)
                for k, q in youtube_queries(ctx, min(n, 20))]
        jobs.append(Job(f"youtube:refresh:{ctx.today.isoformat()}", {}, None, priority=5))
        return jobs

    def _spend(self, ctx, units):
        day = ctx.today.isoformat()
        used = ctx.content.quota_used(self.id, day)
        limit = int(ctx.cfg.get("youtube_daily_units", 3000))
        if used + units > limit:
            raise SourceError(f"limite diário de {limit} unidades do YouTube definido no GPI foi atingido "
                              f"({used} usadas); continua amanhã", "limite")
        ctx.content.quota_add(self.id, day, units)

    def _get(self, ctx, method, params):
        key = ctx.creds.get("youtube")["api_key"]
        url = self.API + method + "?" + urllib.parse.urlencode({**params, "key": key})
        r = ctx.http.request_json(url, ttl=0, min_interval=0.2)
        require(isinstance(r, dict) and "items" in r, f"YouTube {method}: resposta sem 'items'")
        return r

    @staticmethod
    def classify(title: str) -> list[str]:
        t = " " + tx.strip_accents(title).lower() + " "
        return [k for k, terms in VIDEO_TYPES.items() if any(term in t for term in terms)] or ["outros"]

    @staticmethod
    def parse_videos(payload, product_key=None, query=None) -> list[dict]:
        rows = []
        for v in payload["items"]:
            sn, st = v.get("snippet", {}), v.get("statistics", {})
            vid = v.get("id")
            require(isinstance(vid, str) and sn.get("title"), "YouTube videos.list: item sem id/título")
            metrics = {k: int(st[k]) for k in ("viewCount", "likeCount", "commentCount") if str(st.get(k, "")).isdigit()}
            rows.append({"item_id": vid, "kind": "video", "title": sn["title"][:300],
                         "text": (sn.get("description") or "")[:300], "url": f"https://www.youtube.com/watch?v={vid}",
                         "author": sn.get("channelTitle"), "published_at": (sn.get("publishedAt") or "")[:10] or None,
                         "lang": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage"),
                         "category": sn.get("categoryId"), "product_key": product_key, "query": query,
                         "metrics": {**metrics, "tipos": YouTube.classify(sn["title"])}})
        return rows

    def run(self, job, ctx):
        if job.key.startswith("youtube:refresh:"):
            ids = ctx.content.ids_to_refresh(self.id, days=7)
            for i in range(0, len(ids), 50):
                self._spend(ctx, 1)
                r = self._get(ctx, "videos", {"part": "snippet,statistics", "id": ",".join(ids[i:i + 50]), "maxResults": 50})
                ctx.content.upsert(self.id, self.parse_videos(r), keep_product=True)
            ctx.content.purge(self.id, days=30)          # política: não manter dados não atualizados > 30 dias
            return [], []
        q, pk = job.params["q"], job.params["product_key"]
        self._spend(ctx, 100)
        after = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%SZ")
        s = self._get(ctx, "search", {"part": "id", "type": "video", "q": f"{q} review OR teste OR unboxing",
                                      "maxResults": 25, "order": "relevance", "regionCode": self.REGION,
                                      "relevanceLanguage": "pt", "publishedAfter": after})
        ids = [it["id"]["videoId"] for it in s["items"] if isinstance(it.get("id"), dict) and it["id"].get("videoId")]
        if ids:
            self._spend(ctx, 1)
            v = self._get(ctx, "videos", {"part": "snippet,statistics", "id": ",".join(ids)})
            r = ctx.content.upsert(self.id, self.parse_videos(v, pk, q))
            self.last_counts = r
        return [], []


# --------------------------------------------------------------------------- Reddit
class Reddit(Connector):
    id, name, order = "reddit", "Reddit (discussões de consumidores)", 76
    stage = 2          # consultas montadas a partir dos produtos descobertos na etapa 1
    reliability = "B"
    docs_url = "https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki"
    description = "Publicações e comentários públicos sobre os produtos, usados na análise de opiniões."
    limitations = ("Nível gratuito: uso não comercial, ~100 consultas/min com OAuth. Uso comercial exige contrato "
                   "com o Reddit. Conteúdo excluído pelo autor deixa de ser exibido na atualização seguinte.")

    def available(self, ctx):
        c = ctx.creds.get("reddit") if ctx.creds else {}
        return bool(c.get("client_id") and c.get("uso_autorizado"))

    @property
    def restricted_reason(self):  # type: ignore[override]
        return ("Requer Client ID de aplicativo Reddit e confirmação de uso autorizado (o nível gratuito é para uso "
                "não comercial).")

    _tok = {"v": None, "exp": 0}

    def _token(self, ctx):
        if self._tok["v"] and self._tok["exp"] > time.time() + 60:
            return self._tok["v"]
        from ..integrations.registry import reddit_token
        r = reddit_token(ctx.http, ctx.creds.get("reddit")["client_id"])
        self._tok.update(v=r["access_token"], exp=time.time() + float(r.get("expires_in", 3600)))
        return self._tok["v"]

    def plan(self, ctx):
        wk = week_tag(ctx.today)
        return [Job(f"reddit:{k}:{wk}", {"product_key": k, "q": q}, None, priority=4) for k, q in keywords(ctx, 20, "en")]

    @staticmethod
    def parse_listing(payload) -> list[dict]:
        require(isinstance(payload, dict) and isinstance(payload.get("data", {}).get("children"), list),
                "Reddit: listagem sem data.children")
        rows = []
        for ch in payload["data"]["children"]:
            d = ch.get("data", {})
            if ch.get("kind") not in ("t3", "t1") or d.get("removed_by_category") or d.get("author") == "[deleted]":
                continue
            body = d.get("selftext") if ch["kind"] == "t3" else d.get("body")
            rows.append({"item_id": d.get("name") or d.get("id"), "kind": "post" if ch["kind"] == "t3" else "comentario",
                         "title": (d.get("title") or "")[:300], "text": (body or "")[:1000],
                         "url": "https://www.reddit.com" + d.get("permalink", ""), "author": f"r/{d.get('subreddit', '')}",
                         "published_at": datetime.fromtimestamp(float(d.get("created_utc", 0)), timezone.utc).date().isoformat(),
                         "lang": "en", "metrics": {"score": d.get("score"), "num_comments": d.get("num_comments")}})
        return rows

    def run(self, job, ctx):
        tok = self._token(ctx)
        h = {"Authorization": f"bearer {tok}"}
        url = "https://oauth.reddit.com/search?" + urllib.parse.urlencode(
            {"q": f'"{job.params["q"]}"', "sort": "relevance", "t": "year", "limit": 50, "type": "link"})
        posts = self.parse_listing(ctx.http.request_json(url, headers=h, ttl=0, min_interval=1.0))
        for p in posts:
            p["product_key"], p["query"] = job.params["product_key"], job.params["q"]
        rows = list(posts)
        for p in sorted(posts, key=lambda x: -(x["metrics"].get("num_comments") or 0))[:3]:
            pid = p["item_id"].split("_")[-1]
            r = ctx.http.request_json(f"https://oauth.reddit.com/comments/{pid}?limit=40&depth=1&sort=top",
                                      headers=h, ttl=0, min_interval=1.0)
            if isinstance(r, list) and len(r) > 1:
                for c in self.parse_listing(r[1]):
                    c.update(product_key=job.params["product_key"], query=job.params["q"], title=p["title"])
                    rows.append(c)
        ctx.content.upsert(self.id, rows)
        ctx.content.purge(self.id, days=120)
        return [], []
