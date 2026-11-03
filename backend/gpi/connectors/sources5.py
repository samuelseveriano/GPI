"""
v0.5 — novas fontes de inteligência de produtos.

* Mercado Livre Trends (API oficial, GET /trends/MLB): termos mais buscados no Mercado Livre Brasil.
  Exige token OAuth do aplicativo do usuário (Central de Integrações). Guarda a POSIÇÃO na lista a
  cada coleta (histórico por sincronização) — posição não é volume de buscas.
* Google Trends no BigQuery (conjunto público bigquery-public-data.google_trends): top 25 e top 25 em
  alta por país e sub-região (international_*) e por área de mercado (DMA) nos EUA (top_terms,
  top_rising_terms). "score" é interesse RELATIVO (0–100) dentro da região e semana; não é volume.
  Exige projeto Google Cloud do usuário (faturamento é do projeto do usuário; a camada gratuita cobre
  1 TB/mês de consultas). Antes de cada consulta, um "dry run" mede os bytes; acima do limite
  configurado (bq_max_gb) a consulta não é executada. Só a partição mais recente é lida.
* eBay Browse API (oficial, OAuth de aplicativo — client credentials): anúncios (título, marca,
  preço, moeda, condição, vendedor) por produto. Quantidade de anúncios NÃO é venda.
* GDELT DOC 2.0 (público, sem chave): volume diário de artigos de notícias que citam o produto e
  manchetes recentes. Menções em notícias não medem consumo; servem para lançamentos e repercussão.
* Microsoft Advertising (Ad Insight, GetHistoricalSearchVolume): volume histórico de buscas no Bing.
  Exige conta, developer token e OAuth Microsoft. Implementado, mas NÃO validado com conta real.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

from ..market.store import now_iso
from .base import Connector, FormatError, Job, require
from .http import SourceError


def _observe_and_store(ctx, source, country, term, ref_date, period, metric, value, unit, url=None, extra=None,
                       region="", lang=None, strong=True):
    """Classifica o termo (NLP + intenção), associa ao catálogo e grava a observação (idempotente)."""
    from ..products.catalog import Catalog
    from ..products.intent import classify
    intent = classify(term)
    pid = Catalog(ctx.store.db, ctx.cfg).observe(term, source, country, intent["intencao"], strong=strong, lang=lang)
    commercial = int(bool(pid) and intent["intencao"] not in ("noticia", "entretenimento"))
    ctx.store.db.execute(
        "INSERT INTO search_observations (source, country, region, term, ref_date, period, metric, value, value_high, unit,"
        " lang, product_id, intent, commercial, url, extra, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(source, country, region, term, ref_date, metric) DO UPDATE SET value = excluded.value,"
        " product_id = excluded.product_id, intent = excluded.intent, commercial = excluded.commercial, extra = excluded.extra,"
        " collected_at = excluded.collected_at",
        (source, country, region or "", term[:200], ref_date, period, metric, float(value), unit, lang or intent["idioma"],
         pid, intent["intencao"], commercial, url, json.dumps(extra, ensure_ascii=False) if extra else None, now_iso()))
    return pid


# ============================================================================ Mercado Livre Trends
class MercadoLivreTrends(Connector):
    id = "ml_trends"
    name = "Mercado Livre — tendências de busca (API oficial)"
    reliability = "A"
    docs_url = "https://developers.mercadolivre.com.br/consulte-as-tendencias-de-busca-com-o-recurso-trends"
    description = "Termos mais buscados no Mercado Livre Brasil (geral e por categoria), com histórico de cada coleta."
    limitations = "Lista ordenada de termos: a posição indica popularidade relativa, não volume de buscas."
    order = 16
    stage = 1
    URL = "https://api.mercadolibre.com/trends/MLB"

    def available(self, ctx) -> bool:
        return bool(ctx.creds and ctx.creds.get("mercadolivre").get("access_token"))

    def plan(self, ctx):
        return [Job(f"{self.id}:{ctx.today.isoformat()}", {}, refresh_days=None, priority=0)]

    @staticmethod
    def parse(payload) -> list[dict]:
        require(isinstance(payload, list), "Mercado Livre Trends: resposta não é uma lista")
        out = []
        for i, r in enumerate(payload, start=1):
            require(isinstance(r, dict) and r.get("keyword"), "Mercado Livre Trends: item sem 'keyword'")
            out.append({"termo": str(r["keyword"]), "posicao": i, "url": r.get("url")})
        return out

    def run(self, job, ctx):
        from ..integrations.registry import ml_token
        tok = ml_token(ctx.http, ctx.creds)
        items = self.parse(ctx.http.request_json(self.URL, headers={"Authorization": f"Bearer {tok}"}, ttl=6 * 3600))
        with ctx.store.db.transaction():
            for it in items:
                _observe_and_store(ctx, self.id, "BR", it["termo"], ctx.today.isoformat(), "dia", "posicao_tendencia",
                                   it["posicao"], "posição na lista (1 = mais buscado)", it["url"], lang="pt")
        return [], []


# ============================================================================ Google Trends BigQuery
def google_token(http, creds, pid: str) -> str:
    c = creds.get(pid)
    if not c.get("refresh_token"):
        raise SourceError("integração Google não conectada: use 'Conectar' na Central de Integrações", "restrita")
    if c.get("access_token") and float(c.get("expires_at", 0)) > time.time() + 60:
        return c["access_token"]
    r = http.request_json("https://oauth2.googleapis.com/token", "POST", form={
        "grant_type": "refresh_token", "client_id": c.get("client_id", ""), "client_secret": c.get("client_secret", ""),
        "refresh_token": c["refresh_token"]})
    if not r.get("access_token"):
        raise SourceError(f"Google não renovou o token: {r.get('error_description') or r.get('error')}", "restrita")
    creds.set(pid, {"access_token": r["access_token"], "expires_at": str(time.time() + float(r.get("expires_in", 3600)))})
    return r["access_token"]


BQ_TABLES = {
    "international_top_terms": ("intl", "top"), "international_top_rising_terms": ("intl", "rising"),
    "top_terms": ("us", "top"), "top_rising_terms": ("us", "rising"),
}


def bq_sql(table: str, refresh: str, countries: list[str]) -> str:
    scope, kind = BQ_TABLES[table]
    gain = ", percent_gain" if kind == "rising" else ""
    if scope == "intl":
        cc = ", ".join("'" + re.sub(r"[^A-Z]", "", c.upper())[:2] + "'" for c in countries if c.upper() != "US") or "'BR'"
        return (f"SELECT term, country_code AS country, region_code AS region, region_name, week, score, rank{gain} "
                f"FROM `bigquery-public-data.google_trends.{table}` WHERE refresh_date = '{refresh}' "
                f"AND country_code IN ({cc}) AND week = (SELECT MAX(week) FROM `bigquery-public-data.google_trends.{table}` "
                f"WHERE refresh_date = '{refresh}')")
    return (f"SELECT term, 'US' AS country, CAST(dma_id AS STRING) AS region, dma_name AS region_name, week, score, rank{gain} "
            f"FROM `bigquery-public-data.google_trends.{table}` WHERE refresh_date = '{refresh}' "
            f"AND week = (SELECT MAX(week) FROM `bigquery-public-data.google_trends.{table}` WHERE refresh_date = '{refresh}')")


def bq_rows(payload: dict) -> list[dict]:
    require(isinstance(payload, dict) and "schema" in payload, "BigQuery: resposta sem 'schema'")
    names = [f["name"] for f in payload["schema"]["fields"]]
    return [{n: (c or {}).get("v") for n, c in zip(names, r.get("f", []))} for r in payload.get("rows", [])]


class GoogleTrendsBigQuery(Connector):
    id = "google_trends_bq"
    name = "Google Trends — BigQuery (conjunto público oficial)"
    reliability = "A"
    docs_url = "https://cloud.google.com/blog/products/data-analytics/international-google-trends-datasets-in-bigquery"
    description = ("Top 25 termos e top 25 em alta por país e sub-região (ISO 3166-2) e por área de mercado nos EUA, "
                   "com histórico semanal de interesse relativo.")
    limitations = ("Interesse relativo (0–100) dentro de cada região e semana — não é volume e não é comparável entre "
                   "regiões. Exige projeto Google Cloud do usuário; consultas acima do limite configurado não são executadas.")
    order = 17
    stage = 1
    API = "https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries"

    def available(self, ctx) -> bool:
        c = ctx.creds.get("google_bigquery") if ctx.creds else {}
        return bool(c.get("refresh_token") and c.get("project_id"))

    def plan(self, ctx):
        return [Job(f"{self.id}:{t}:{ctx.today.isoformat()}", {"table": t}, refresh_days=None, priority=1) for t in BQ_TABLES
                if BQ_TABLES[t][0] == "intl" or "US" in [g.upper() for g in (ctx.cfg.get("trends_geos") or ["BR", "US"])]]

    def _query(self, ctx, sql: str, dry: bool) -> dict:
        c = ctx.creds.get("google_bigquery")
        tok = google_token(ctx.http, ctx.creds, "google_bigquery")
        limit = int(float(ctx.cfg.get("bq_max_gb", 2.0)) * 1e9)
        body = {"query": sql, "useLegacySql": False, "dryRun": dry, "maximumBytesBilled": str(limit), "timeoutMs": 60000,
                "maxResults": 5000}
        return ctx.http.request_json(self.API.format(project=urllib.parse.quote(c["project_id"])), "POST", body,
                                     headers={"Authorization": f"Bearer {tok}"}, ttl=0, timeout=90)

    def run(self, job, ctx):
        table = job.params["table"]
        geos = ctx.cfg.get("trends_geos") or ["BR", "US"]
        limit_gb = float(ctx.cfg.get("bq_max_gb", 2.0))
        rows = []
        for back in (1, 2, 3):                                # partição diária mais recente disponível
            refresh = (ctx.today - timedelta(days=back)).isoformat()
            sql = bq_sql(table, refresh, geos)
            dry = self._query(ctx, sql, True)
            gb = int(dry.get("totalBytesProcessed", 0)) / 1e9
            if gb > limit_gb:
                raise SourceError(f"consulta ao BigQuery processaria {gb:.2f} GB (limite configurado: {limit_gb} GB); "
                                  "não executada", "limite")
            rows = bq_rows(self._query(ctx, sql, False))
            if rows:
                break
        scope, kind = BQ_TABLES[table]
        with ctx.store.db.transaction():
            for r in rows:
                extra = {"tabela": table, "tipo": "em alta" if kind == "rising" else "top", "rank": r.get("rank"),
                         "regiao": r.get("region_name"), "ganho_pct": r.get("percent_gain"), "refresh": refresh}
                _observe_and_store(ctx, self.id, r["country"], r["term"], str(r["week"])[:10], "semana",
                                   "score_trends_rising" if kind == "rising" else "score_trends", float(r["score"] or 0),
                                   "índice 0–100 (relativo à região e semana)", self.docs_url, extra, region=r.get("region") or "")
        return [], []


# ============================================================================ eBay Browse
def ebay_token(http, creds) -> str:
    c = creds.get("ebay")
    if not (c.get("client_id") and c.get("client_secret")):
        raise SourceError("informe App ID e Cert ID do eBay na Central de Integrações", "restrita")
    if c.get("access_token") and float(c.get("expires_at", 0)) > time.time() + 60:
        return c["access_token"]
    auth = base64.b64encode(f"{c['client_id']}:{c['client_secret']}".encode()).decode()
    r = http.request_json("https://api.ebay.com/identity/v1/oauth2/token", "POST",
                          form={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
                          headers={"Authorization": f"Basic {auth}"})
    if not r.get("access_token"):
        raise SourceError(f"eBay não emitiu token: {r.get('error_description') or r.get('error')}", "restrita")
    creds.set("ebay", {"access_token": r["access_token"], "expires_at": str(time.time() + float(r.get("expires_in", 7200)))})
    return r["access_token"]


def parse_ebay(payload: dict) -> list[dict]:
    require(isinstance(payload, dict), "eBay: resposta inesperada")
    out = []
    for it in payload.get("itemSummaries", []) or []:
        price = (it.get("price") or {})
        mp = (it.get("marketingPrice") or {}).get("originalPrice") or {}
        out.append({"id": it.get("itemId"), "titulo": it.get("title", ""), "preco": float(price["value"]) if price.get("value") else None,
                    "moeda": price.get("currency"), "preco_original": float(mp["value"]) if mp.get("value") else None,
                    "condicao": it.get("condition"), "vendedor": (it.get("seller") or {}).get("username"),
                    "url": it.get("itemWebUrl"), "categoria": ((it.get("categories") or [{}])[0]).get("categoryName"),
                    "pais": (it.get("itemLocation") or {}).get("country")})
    return [o for o in out if o["id"] and o["titulo"]]


class EbayBrowse(Connector):
    id = "ebay"
    name = "eBay — Browse API (anúncios e preços)"
    reliability = "A"
    docs_url = "https://developer.ebay.com/api-docs/buy/browse/overview.html"
    description = "Anúncios ativos por produto no eBay EUA: título, marca, preço, moeda, condição e vendedor."
    limitations = "Anúncios ativos não são vendas; um vendedor pode ter vários anúncios (o GPI deduplica por vendedor)."
    order = 82
    stage = 2
    URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    def available(self, ctx) -> bool:
        c = ctx.creds.get("ebay") if ctx.creds else {}
        return bool(c.get("client_id") and c.get("client_secret"))

    def plan(self, ctx):
        from ..products.catalog import Catalog
        prods = sorted(Catalog(ctx.store.db, ctx.cfg).products("produto"), key=lambda p: -(p["evidence"] or 0))
        n = int(ctx.cfg.get("ebay_max_products", 30))
        return [Job(f"{self.id}:{p['product_id']}:{ctx.today.isoformat()}", {"pid": p["product_id"], "q": p["name_en"]},
                    refresh_days=None, priority=5) for p in prods[:n] if p.get("name_en")]

    def run(self, job, ctx):
        tok = ebay_token(ctx.http, ctx.creds)
        url = self.URL + "?" + urllib.parse.urlencode({"q": job.params["q"], "limit": 50})
        items = parse_ebay(ctx.http.request_json(url, headers={"Authorization": f"Bearer {tok}",
                                                               "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}, ttl=12 * 3600))
        from ..products import nlp
        day, ts = ctx.today.isoformat(), now_iso()
        with ctx.store.db.transaction():
            for it in items:
                at = nlp.extract_attributes(it["titulo"])
                ctx.store.db.execute(
                    "INSERT OR REPLACE INTO market_listings (source, item_id, day, product_id, query, title, brand, model, category,"
                    " price, currency, original_price, country, seller, condition, url, extra, collected_at)"
                    " VALUES ('ebay', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                    (it["id"], day, job.params["pid"], job.params["q"], it["titulo"][:300], at.get("marca"), at.get("modelo"),
                     it["categoria"], it["preco"], it["moeda"], it["preco_original"], it["pais"] or "US", it["vendedor"],
                     it["condicao"], it["url"], ts))
        return [], []


# ============================================================================ GDELT
def parse_gdelt_timeline(payload: dict) -> list[tuple[str, float, float | None]]:
    require(isinstance(payload, dict) and isinstance(payload.get("timeline"), list), "GDELT: resposta sem 'timeline'")
    out = []
    for s in payload["timeline"]:
        for d in s.get("data", []):
            ds = str(d.get("date", ""))
            require(len(ds) >= 8, "GDELT: data inválida")
            out.append((f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}", float(d.get("value", 0)), float(d["norm"]) if d.get("norm") else None))
    return out


class Gdelt(Connector):
    id = "gdelt"
    name = "GDELT — notícias globais (DOC 2.0, público)"
    reliability = "B"
    docs_url = "https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/"
    description = "Quantidade diária de artigos de notícias que citam cada produto (12 meses) e manchetes recentes para lançamentos."
    limitations = "Repercussão na imprensa, não consumo. Termos ambíguos podem trazer notícias sem relação comercial."
    order = 84
    stage = 2
    URL = "https://api.gdeltproject.org/api/v2/doc/doc"

    def plan(self, ctx):
        from ..products.catalog import Catalog
        prods = sorted(Catalog(ctx.store.db, ctx.cfg).products("produto"), key=lambda p: -(p["evidence"] or 0))
        n = int(ctx.cfg.get("gdelt_max_products", 30))
        wk = ctx.today.isocalendar()
        return [Job(f"{self.id}:{p['product_id']}:{wk[0]}-{wk[1]}", {"pid": p["product_id"], "q": p["name_en"]},
                    refresh_days=None, priority=6) for p in prods[:n] if p.get("name_en") and len(p["name_en"]) > 3]

    def run(self, job, ctx):
        q = f'"{job.params["q"].lower()}"'
        url = self.URL + "?" + urllib.parse.urlencode({"query": q, "mode": "timelinevolraw", "format": "json", "timespan": "12m"})
        pts = parse_gdelt_timeline(ctx.http.request_json(url, ttl=24 * 3600, min_interval=5.5))
        months = {}
        for d, v, _ in pts:
            months[d[:7]] = months.get(d[:7], 0.0) + v
        with ctx.store.db.transaction():
            for m, v in months.items():
                ctx.store.db.execute(
                    "INSERT OR REPLACE INTO search_observations (source, country, region, term, ref_date, period, metric, value,"
                    " value_high, unit, lang, product_id, intent, commercial, url, extra, collected_at)"
                    " VALUES ('gdelt', 'GLOBAL:news', '', ?, ?, 'mes', 'noticias_gdelt', ?, NULL, 'artigos/mês', 'en', ?, 'noticia', 0, ?, NULL, ?)",
                    (job.params["q"], f"{m}-01", v, job.params["pid"], url, now_iso()))
        return [], []


# ============================================================================ Microsoft Advertising
MS_NS = "https://bingads.microsoft.com/AdInsight/v13"


def ms_token(http, creds) -> str:
    c = creds.get("msads")
    if not c.get("refresh_token"):
        raise SourceError("Microsoft Advertising não conectado: use 'Conectar' na Central de Integrações", "restrita")
    if c.get("access_token") and float(c.get("expires_at", 0)) > time.time() + 60:
        return c["access_token"]
    r = http.request_json("https://login.microsoftonline.com/common/oauth2/v2.0/token", "POST", form={
        "grant_type": "refresh_token", "client_id": c.get("client_id", ""), "refresh_token": c["refresh_token"],
        "scope": "https://ads.microsoft.com/msads.manage offline_access"})
    if not r.get("access_token"):
        raise SourceError(f"Microsoft não renovou o token: {r.get('error_description') or r.get('error')}", "restrita")
    creds.set("msads", {"access_token": r["access_token"], "refresh_token": r.get("refresh_token", c["refresh_token"]),
                        "expires_at": str(time.time() + float(r.get("expires_in", 3600)))})
    return r["access_token"]


def ms_envelope(c: dict, token: str, keywords: list[str], country: str, lang: str, start: date, end: date) -> str:
    from xml.sax.saxutils import escape
    kw = "".join(f"<a1:string>{escape(k)}</a1:string>" for k in keywords)
    d = lambda x: f"<Day>{x.day}</Day><Month>{x.month}</Month><Year>{x.year}</Year>"
    return (f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Header xmlns="{MS_NS}">'
            f"<AuthenticationToken>{escape(token)}</AuthenticationToken><CustomerAccountId>{escape(c.get('account_id', ''))}</CustomerAccountId>"
            f"<CustomerId>{escape(c.get('customer_id', ''))}</CustomerId><DeveloperToken>{escape(c.get('developer_token', ''))}</DeveloperToken>"
            f'</s:Header><s:Body><GetHistoricalSearchVolumeRequest xmlns="{MS_NS}">'
            f'<Keywords xmlns:a1="http://schemas.microsoft.com/2003/10/Serialization/Arrays">{kw}</Keywords>'
            f"<Language>{lang}</Language><PublisherCountries xmlns:a1=\"http://schemas.microsoft.com/2003/10/Serialization/Arrays\">"
            f"<a1:string>{country}</a1:string></PublisherCountries><StartDate>{d(start)}</StartDate><EndDate>{d(end)}</EndDate>"
            f"<TimePeriodRollup>Monthly</TimePeriodRollup></GetHistoricalSearchVolumeRequest></s:Body></s:Envelope>")


def parse_ms_volumes(xml_text: str) -> list[dict]:
    if "<!DOCTYPE" in xml_text[:2000].upper():
        raise FormatError("resposta com DTD rejeitada")
    root = ET.fromstring(xml_text.encode("utf-8"))
    strip = lambda t: t.split("}")[-1]
    fault = next((e for e in root.iter() if strip(e.tag) == "Fault"), None)
    if fault is not None:
        raise SourceError("Microsoft Advertising: " + " ".join((e.text or "") for e in fault.iter() if e.text)[:300], "http")
    out = []
    for ksc in (e for e in root.iter() if strip(e.tag) == "KeywordSearchCount"):
        kw = next((e.text for e in ksc.iter() if strip(e.tag) == "Keyword"), None)
        for sc in (e for e in ksc.iter() if strip(e.tag) == "SearchCount"):
            vals = {strip(x.tag): x.text for x in sc.iter()}
            if vals.get("Year") and vals.get("Month") and vals.get("SearchCount") is not None:
                out.append({"termo": kw, "mes": f"{int(vals['Year']):04d}-{int(vals['Month']):02d}-01",
                            "buscas": float(vals["SearchCount"])})
    return [o for o in out if o["termo"]]


class MicrosoftAdsKeywordPlanner(Connector):
    id = "msads_kp"
    name = "Microsoft Advertising — volume de buscas no Bing (Ad Insight)"
    reliability = "A"
    docs_url = "https://learn.microsoft.com/advertising/ad-insight-service/gethistoricalsearchvolume"
    description = "Volume mensal de buscas no Bing por palavra-chave, país e idioma."
    limitations = ("Exige conta Microsoft Advertising, developer token e OAuth. Implementado segundo a documentação, "
                   "mas ainda não validado com uma conta real.")
    order = 19
    stage = 2
    URL = "https://adinsight.api.bingads.microsoft.com/Api/Advertiser/AdInsight/v13/AdInsightService.svc"
    MARKETS = {"BR": ("BR", "Portuguese", "pt"), "US": ("US", "English", "en")}

    def available(self, ctx) -> bool:
        c = ctx.creds.get("msads") if ctx.creds else {}
        return bool(c.get("refresh_token") and c.get("developer_token") and c.get("customer_id") and c.get("account_id"))

    def plan(self, ctx):
        from ..products.catalog import Catalog
        prods = sorted(Catalog(ctx.store.db, ctx.cfg).products("produto"), key=lambda p: -(p["evidence"] or 0))[:100]
        month = ctx.today.strftime("%Y-%m")
        jobs = []
        for cc, (_c, _l, lang) in self.MARKETS.items():
            terms = [t for t in dict.fromkeys(p["name_pt"] if lang == "pt" else p["name_en"] for p in prods) if t]
            for i in range(0, len(terms), 20):
                jobs.append(Job(f"{self.id}:{cc}:{month}:{i // 20}", {"cc": cc, "keywords": terms[i:i + 20]}, None, 4))
        return jobs

    def run(self, job, ctx):
        c = ctx.creds.get("msads")
        tok = ms_token(ctx.http, ctx.creds)
        country, language, lang = self.MARKETS[job.params["cc"]]
        end = ctx.today.replace(day=1) - timedelta(days=1)
        start = date(end.year - 1, end.month, 1)
        xml = ms_envelope(c, tok, job.params["keywords"], country, language, start, end)
        raw = ctx.http.request_text(self.URL, headers={"Content-Type": "text/xml; charset=utf-8",
                                                       "SOAPAction": "GetHistoricalSearchVolume"}, ttl=0,
                                    method="POST", data=xml.encode("utf-8"))
        with ctx.store.db.transaction():
            for r in parse_ms_volumes(raw):
                _observe_and_store(ctx, self.id, job.params["cc"], r["termo"], r["mes"], "mes", "volume_bing",
                                   r["buscas"], "buscas/mês no Bing", self.docs_url, lang=lang)
        return [], []
