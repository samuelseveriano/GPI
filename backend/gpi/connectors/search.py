"""
Fase 4 — fontes de interesse de PESQUISA por produto.

* GoogleTrendsTrending — feed RSS oficial "Trending Now" do Google Trends (exportação pública do
  próprio Google, por país). Traz as buscas em alta no momento com o tráfego em FAIXAS ("200+",
  "2.000+") — o GPI guarda o limite inferior e o rótulo da faixa, nunca um volume exato. Coleta
  diária: o histórico se forma com o uso (não há histórico retroativo no feed).
  Filtro de relevância comercial: só termos em que o NLP identifica um produto e cuja intenção não
  é notícia/entretenimento são marcados como comerciais; os demais ficam registrados, mas fora dos
  rankings de produtos. Atribuição obrigatória: "Fonte: Google Trends".
* GoogleAdsKeywordPlanner — API oficial do Google Ads (KeywordPlanIdeaService.GenerateKeywordIdeas).
  Exige conta Google Ads, developer token aprovado e OAuth do usuário (Central de Integrações).
  Fornece média mensal e histórico de 12 meses de buscas por palavra-chave e país — valores
  ARREDONDADOS pelo Google (tratados como aproximados) — e a concorrência publicitária.
  China continental não é consultada: o Google não representa a busca local chinesa.

Todas as observações vão para `search_observations` com fonte, país, período, métrica e unidade.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

from ..market.store import now_iso
from .base import Connector, FormatError, Job, require
from .http import SourceError

HT = "{https://trends.google.com/trending/rss}"
HT_OLD = "{https://trends.google.com/trends/trendingsearches/daily}"


def parse_traffic(s: str | None) -> tuple[float | None, str | None]:
    """'200+' → 200; '2,000+' / '2.000+' → 2000; '2K+' / '2 mil+' → 2000; '1M+' → 1000000."""
    if not s:
        return None, None
    raw = s.strip()
    t = raw.lower().replace(" ", "").rstrip("+")
    mult = 1
    if t.endswith(("k", "mil")):
        mult, t = 1000, re.sub(r"(k|mil)$", "", t)
    elif t.endswith(("m", "mi")):
        mult, t = 1_000_000, re.sub(r"(m|mi)$", "", t)
    t = t.replace(",", "").replace(".", "") if mult == 1 else t.replace(",", ".")
    try:
        return float(t) * mult, raw
    except ValueError:
        return None, raw


def parse_trending(xml_text: str) -> list[dict]:
    if "<!DOCTYPE" in xml_text[:4000].upper() or "<!ENTITY" in xml_text.upper():
        raise FormatError("feed com DTD/entidades rejeitado por segurança")
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as e:
        raise FormatError(f"feed do Google Trends inválido ({e})")
    require(root.tag == "rss", "Google Trends: documento não é RSS")
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        traffic = it.findtext(HT + "approx_traffic") or it.findtext(HT_OLD + "approx_traffic")
        val, label = parse_traffic(traffic)
        pub = it.findtext("pubDate")
        try:
            d = parsedate_to_datetime(pub).astimezone(timezone.utc).date() if pub else None
        except (TypeError, ValueError):
            d = None
        news = []
        for ni in list(it.iter(HT + "news_item")) + list(it.iter(HT_OLD + "news_item")):
            news.append({"titulo": (ni.findtext(HT + "news_item_title") or ni.findtext(HT_OLD + "news_item_title") or "").strip(),
                         "url": (ni.findtext(HT + "news_item_url") or ni.findtext(HT_OLD + "news_item_url") or "").strip()})
        out.append({"termo": title, "trafego": val, "faixa": label, "data": d.isoformat() if d else None,
                    "noticias": [n for n in news if n["titulo"]][:3]})
    return out


class GoogleTrendsTrending(Connector):
    id = "google_trends_rss"
    name = "Google Trends — Trending Now (RSS oficial)"
    reliability = "A"
    docs_url = "https://support.google.com/trends/answer/3076011"
    description = ("Buscas em alta no Google por país (feed RSS oficial do 'Trending Now'), com tráfego em faixas. "
                   "Os termos passam pelo NLP: produtos com intenção comercial alimentam os rankings de consumo.")
    limitations = ("Lista curta de termos em alta no momento (muitos são notícias/esportes); tráfego em faixas, não "
                   "volume exato; sem histórico retroativo — a série se forma com as coletas diárias.")
    order = 15
    stage = 1
    URLS = ["https://trends.google.com/trending/rss?geo={geo}",
            "https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}"]
    GEOS = {"BR": "Brasil", "US": "Estados Unidos"}

    def plan(self, ctx):
        geos = ctx.cfg.get("trends_geos") or list(self.GEOS)
        day = ctx.today.isoformat()
        # um job por país e dia (o feed muda ao longo do dia; a coleta diária forma a série)
        return [Job(f"{self.id}:{g}:{day}", {"geo": g}, refresh_days=None, priority=0) for g in geos]

    def run(self, job, ctx):
        geo = job.params["geo"]
        last = None
        for tpl in self.URLS:
            url = tpl.format(geo=geo)
            try:
                items = parse_trending(ctx.http.request_text(url, ttl=3 * 3600))
                break
            except SourceError as e:
                last = e
                if e.status != 404:
                    raise
        else:
            raise last or SourceError("Google Trends: feed indisponível", "http")
        from ..products.catalog import Catalog
        from ..products.intent import classify
        cat = Catalog(ctx.store.db, ctx.cfg)
        ts, n = now_iso(), 0
        with ctx.store.db.transaction():
            for it in items:
                if it["trafego"] is None:
                    continue
                intent = classify(it["termo"])
                ctx_text = it["termo"]
                pid = cat.observe(ctx_text, self.id, geo, intent["intencao"], strong=True)
                commercial = int(bool(pid) and intent["intencao"] not in ("noticia", "entretenimento"))
                ctx.store.db.execute(
                    "INSERT INTO search_observations (source, country, region, term, ref_date, period, metric, value,"
                    " value_high, unit, lang, product_id, intent, commercial, url, extra, collected_at)"
                    " VALUES (?, ?, '', ?, ?, 'dia', 'trafego_faixa', ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(source, country, region, term, ref_date, metric) DO UPDATE SET value = MAX(value, excluded.value),"
                    " extra = excluded.extra, product_id = excluded.product_id, intent = excluded.intent,"
                    " commercial = excluded.commercial, collected_at = excluded.collected_at",
                    (self.id, geo, it["termo"][:200], it["data"] or ctx.today.isoformat(), it["trafego"],
                     "buscas/dia (limite inferior da faixa)", intent["idioma"], pid, intent["intencao"], commercial,
                     tpl.format(geo=geo), json.dumps({"faixa": it["faixa"], "noticias": it["noticias"]}, ensure_ascii=False), ts))
                n += 1
        require(items, "Google Trends: feed sem itens")
        return [], []


# ----------------------------------------------------------------------------- Google Ads
GADS_VERSIONS = ["v23", "v22", "v21", "v20", "v19"]   # testadas da mais nova para a mais antiga
GEO = {"BR": ("geoTargetConstants/2076", "languageConstants/1014", "pt"),
       "US": ("geoTargetConstants/2840", "languageConstants/1000", "en")}
MONTHS = {m: i for i, m in enumerate(["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
                                       "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"], start=1)}


def gads_token(http, creds) -> str:
    c = creds.get("google_ads")
    if not c.get("refresh_token"):
        raise SourceError("Google Ads não conectado: use 'Conectar' na Central de Integrações", "restrita")
    if c.get("access_token") and float(c.get("expires_at", 0)) > time.time() + 60:
        return c["access_token"]
    r = http.request_json("https://oauth2.googleapis.com/token", "POST", form={
        "grant_type": "refresh_token", "client_id": c.get("client_id", ""), "client_secret": c.get("client_secret", ""),
        "refresh_token": c["refresh_token"]})
    if not r.get("access_token"):
        raise SourceError(f"Google não renovou o token: {r.get('error_description') or r.get('error')}", "restrita")
    creds.set("google_ads", {"access_token": r["access_token"], "expires_at": str(time.time() + float(r.get("expires_in", 3600)))})
    return r["access_token"]


def gads_call(http, creds, path: str, body: dict) -> dict:
    """POST na API do Google Ads, descobrindo a versão ativa (versões antigas são desligadas pelo Google)."""
    c = creds.get("google_ads")
    tok = gads_token(http, creds)
    cid = re.sub(r"\D", "", c.get("customer_id", ""))
    if not cid or not c.get("developer_token"):
        raise SourceError("informe o developer token e o ID da conta Google Ads (Central de Integrações)", "restrita")
    hdr = {"Authorization": f"Bearer {tok}", "developer-token": c["developer_token"]}
    if c.get("login_customer_id"):
        hdr["login-customer-id"] = re.sub(r"\D", "", c["login_customer_id"])
    versions = ([c["api_version"]] if c.get("api_version") else []) + [v for v in GADS_VERSIONS if v != c.get("api_version")]
    last = None
    for v in versions:
        try:
            r = http.request_json(f"https://googleads.googleapis.com/{v}/customers/{cid}{path}", "POST", body,
                                  headers=hdr, ttl=0)
            if c.get("api_version") != v:
                creds.set("google_ads", {"api_version": v})
            return r
        except SourceError as e:
            last = e
            if e.status in (404,) or (e.status == 400 and "UNSUPPORTED_VERSION" in str(e)):
                continue                       # versão desligada: tenta a anterior/seguinte
            raise
    raise last or SourceError("nenhuma versão da API do Google Ads respondeu", "http")


def parse_keyword_ideas(payload: dict) -> list[dict]:
    require(isinstance(payload, dict), "Google Ads: resposta inesperada")
    out = []
    for r in payload.get("results", []):
        m = r.get("keywordIdeaMetrics") or {}
        months = []
        for mv in m.get("monthlySearchVolumes", []) or []:
            mo = MONTHS.get(str(mv.get("month", "")).upper()) or (int(mv["month"]) - 1 if str(mv.get("month", "")).isdigit() else None)
            if mo and mv.get("year") and mv.get("monthlySearches") is not None:
                months.append((f"{int(mv['year']):04d}-{mo:02d}-01", float(mv["monthlySearches"])))
        avg = m.get("avgMonthlySearches")
        out.append({"termo": r.get("text", ""), "media_mensal": float(avg) if avg is not None else None,
                    "meses": sorted(months), "concorrencia": m.get("competition"),
                    "indice_concorrencia": m.get("competitionIndex")})
    return [o for o in out if o["termo"]]


class GoogleAdsKeywordPlanner(Connector):
    id = "google_ads_kp"
    name = "Google Ads — Planejador de palavras-chave (API oficial)"
    reliability = "A"
    docs_url = "https://developers.google.com/google-ads/api/docs/keyword-planning/generate-keyword-ideas"
    description = ("Média mensal e histórico de 12 meses de buscas por palavra-chave no Brasil e nos EUA, com "
                   "concorrência publicitária. Valores arredondados pelo Google (aproximados).")
    limitations = ("Exige conta Google Ads, developer token aprovado e autorização OAuth do usuário. Volumes são "
                   "arredondados e, em contas sem investimento, podem vir em faixas amplas.")
    order = 18
    stage = 2

    def available(self, ctx) -> bool:
        c = ctx.creds.get("google_ads") if ctx.creds else {}
        return bool(c.get("refresh_token") and c.get("developer_token") and c.get("customer_id"))

    def plan(self, ctx):
        from ..products.catalog import Catalog
        prods = [p for p in Catalog(ctx.store.db, ctx.cfg).products("produto")]
        prods.sort(key=lambda p: -(p["evidence"] or 0))
        prods = prods[:int(ctx.cfg.get("kp_max_products", 200))]
        jobs = []
        month = ctx.today.strftime("%Y-%m")
        for geo, (_g, _l, lang) in GEO.items():
            terms = [p["name_pt"] if lang == "pt" else p["name_en"] for p in prods]
            terms = [t for t in dict.fromkeys(terms) if t]
            for i in range(0, len(terms), 20):                       # até 20 sementes por chamada
                jobs.append(Job(f"{self.id}:{geo}:{month}:{i // 20}", {"geo": geo, "keywords": terms[i:i + 20]},
                                refresh_days=None, priority=3))
        return jobs

    def run(self, job, ctx):
        geo = job.params["geo"]
        g, l, lang = GEO[geo]
        body = {"language": l, "geoTargetConstants": [g], "includeAdultKeywords": False,
                "keywordPlanNetwork": "GOOGLE_SEARCH", "keywordSeed": {"keywords": job.params["keywords"]}}
        ideas = parse_keyword_ideas(gads_call(ctx.http, ctx.creds, ":generateKeywordIdeas", body))
        from ..products.catalog import Catalog
        from ..products.intent import classify
        cat = Catalog(ctx.store.db, ctx.cfg)
        ts = now_iso()
        for it in ideas[:int(ctx.cfg.get("kp_max_ideas_per_call", 300))]:
            intent = classify(it["termo"])
            pid = cat.observe(it["termo"], self.id, geo, intent["intencao"], strong=True, lang=lang)
            if not pid:
                continue                                     # ideia sem produto identificável: não entra
            extra = json.dumps({"concorrencia": it["concorrencia"], "indice_concorrencia": it["indice_concorrencia"],
                                "media_mensal": it["media_mensal"]})
            for d, v in it["meses"]:
                ctx.store.db.execute(
                    "INSERT OR REPLACE INTO search_observations (source, country, region, term, ref_date, period, metric,"
                    " value, value_high, unit, lang, product_id, intent, commercial, url, extra, collected_at)"
                    " VALUES (?, ?, '', ?, ?, 'mes', 'volume_mensal_aprox', ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (self.id, geo, it["termo"][:200], d, v, "buscas/mês (aproximado pelo Google)", lang, pid,
                     intent["intencao"], int(intent["intencao"] not in ("noticia", "entretenimento")),
                     self.docs_url, extra, ts))
        return [], []
