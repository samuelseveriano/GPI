"""Fase 4 — inteligência de consumo. Todos os dados aqui são SINTÉTICOS (formato das fontes reais),
usados só para testar a lógica; nenhum é evidência de conexão real."""
import json
import math
import threading
import time
from datetime import date, timedelta

import numpy as np
import pytest

from gpi.connectors.base import Connector, Job
from gpi.connectors.http import SourceError
from gpi.connectors.public import UnComtrade
from gpi.connectors.search import (GoogleAdsKeywordPlanner, GoogleTrendsTrending, gads_call, parse_keyword_ideas,
                                   parse_traffic, parse_trending)
from gpi.db import MIGRATIONS, Database
from gpi.market.sync import SyncContext, SyncManager
from gpi.products import intent, nlp, trends
from gpi.products.catalog import Catalog
from gpi.products.labels import LABELED

TODAY = date(2026, 10, 15)


# ------------------------------------------------------------------ NLP: extração, idioma, normalização
@pytest.mark.parametrize("texto,chave,idioma", [
    ("Melhor carregador rápido para iPhone", "charger+fast+iphone_compat", "pt"),
    ("Best motorcycle helmet 2026", "helmet+motorcycle", "en"),
    ("Comprar capacete LS2", "helmet", "pt"),
    ("luminária solar", "lamp+solar", "pt"),
    ("câmera wi-fi", "camera+smart", "pt"),
    ("aspirador robô", "vacuum+robot", "pt"),
    ("parafusadeira sem fio", "drill+wireless", "pt"),
    ("tomada inteligente", "plug+smart", "pt"),
    ("sensor de presença", "motion_sensor", "pt"),
    ("ventilador portátil", "fan+portable", "pt"),
    ("retrovisor de moto", "mirror+motorcycle", "pt"),
    ("智能门锁", "lock+smart", "zh"),
    ("无线充电器", "charger+wireless", "zh"),
    ("太阳能灯", "lamp+solar", "zh"),
    ("机器人吸尘器", "vacuum+robot", "zh"),
])
def test_product_extraction(texto, chave, idioma):
    a = nlp.analyze(texto)
    assert a["idioma"] == idioma
    assert a["produto"]["chave"] == chave


def test_multilingual_dedup_same_key():
    keys = {nlp.analyze(t)["produto"]["chave"] for t in ("carregador sem fio", "wireless charger", "无线充电器",
                                                        "Carregador SEM FIO", "charger wireless")}
    assert keys == {"charger+wireless"}


def test_variants_are_distinct_but_same_family():
    a20, a140 = nlp.analyze("carregador USB-C 20W"), nlp.analyze("USB-C GaN charger 140W")
    assert a20["produto"]["variante"] == "20w" and a140["produto"]["variante"] == "140w"
    assert a20["produto"]["nucleo"] == a140["produto"]["nucleo"] == "charger"


def test_attributes():
    at = nlp.analyze("Power bank Anker 20000mAh USB-C 22,5W")["atributos"]
    assert at["capacidade_mah"] == "20000" and at["conector"] == "USB-C" and at["marca"] == "anker"
    assert nlp.analyze("Comprar capacete LS2 FF353")["atributos"]["modelo"] == "FF353"
    assert "modelo" not in nlp.analyze("carregador usb-c 20w")["atributos"]        # 20W é potência, não modelo
    assert nlp.analyze("65W 氮化镓充电器")["atributos"]["tecnologia"] == ["GaN"]


def test_non_product_text():
    assert nlp.analyze("resultado do jogo de futebol ontem")["produto"] is None


# ------------------------------------------------------------------ intenção
@pytest.mark.parametrize("texto,esperado", [
    ("Comprar capacete LS2", "compra"), ("Como pintar um capacete", "manutencao"),
    ("Capacete de personagem de anime", "entretenimento"), ("air fryer não liga", "problema_tecnico"),
    ("roomba vs roborock", "comparacao"), ("review fone qcy", "review"), ("Xiaomi lança novo aspirador", "noticia"),
    ("o que é carregador gan", "informacao"), ("扫地机器人哪个好", "comparacao"), ("充电宝价格", "compra"),
])
def test_intent_rules(texto, esperado):
    assert intent.classify(texto)["intencao"] == esperado


def test_intent_holdout_accuracy_and_no_default_purchase():
    holdout = [("melhor preço smartwatch", "compra"), ("cheap led strip", "compra"), ("drone dji vale a pena", "review"),
               ("humidifier not working", "problema_tecnico"), ("como limpar ventilador", "manutencao"),
               ("smart lock vs deadbolt", "comparacao"), ("apple announces new airpods", "noticia"),
               ("como funciona power bank", "informacao"), ("lego drone toy", "entretenimento"),
               ("onde comprar patinete elétrico", "compra"), ("fechadura eletrônica com defeito", "problema_tecnico"),
               ("unboxing projetor", "review")]
    acc = sum(intent.classify(t)["intencao"] == y for t, y in holdout) / len(holdout)
    assert acc >= 0.8
    r = intent.classify("air fryer")
    assert r["intencao"] == "informacao" and not r["comercial"] and r["confianca"] < 0.5


def test_supervised_model_gated_by_quality():
    m = intent.IntentModel(LABELED[:10])
    assert not m.info["supervisionado"] and "insuficientes" in m.info["motivo"]
    m2 = intent.IntentModel(LABELED)
    assert m2.info["exemplos"] == len(LABELED)
    if not m2.info["supervisionado"]:
        assert m2.info["acuracia_validacao_cruzada"] < 0.6        # só regras quando o modelo não é confiável


# ------------------------------------------------------------------ catálogo e descoberta
def test_catalog_seed_levels_and_ncm(tmp_path):
    db = Database(tmp_path / "c.sqlite")
    c = Catalog(db)
    c.ensure_seeded()
    p = c.get("charger+usb_c")
    assert p["level"] == "produto" and p["ncm_hint"] == "8504" and p["name_zh"]
    assert {v["product_id"] for v in p["variantes"]} >= {"charger+usb_c:20w", "charger+usb_c:65w", "charger+usb_c:140w"}
    assert c.get("charger+usb_c:65w")["parent_id"] == "charger+usb_c"
    assert c.get("helmet+motorcycle")["ncm_hint"] == "6506"
    assert c.get("mirror+motorcycle")["ncm_hint"] == "7009"
    assert c.get("motion_sensor")["ncm_hint"] is None                 # sem fundamento técnico: vazio
    n = len(c.products())
    c.ensure_seeded()
    assert len(c.products()) == n                                      # idempotente


def test_discovery_promotion_rules_and_limits(tmp_path):
    db = Database(tmp_path / "c.sqlite")
    c = Catalog(db, {"catalog_max_products": 10_000})
    c.ensure_seeded()
    assert c.observe("termômetro culinário digital", "rss") is None               # 1 ocorrência em notícia: candidato
    assert c.observe("termômetro culinário digital", "reddit") == "thermometer+electronic"   # 2ª fonte: promovido
    assert c.get("thermometer+electronic")["origin"] == "descoberto"
    assert c.observe("best webcam 4k", "google_trends_rss", "US", "compra", strong=True) == "webcam:4k"
    assert c.observe("notícia sobre economia", "rss") is None
    small = Catalog(db, {"catalog_max_products": 1})
    assert small.observe("seladora de pedal industrial", "google_ads_kp", strong=True) is None   # limite respeitado


# ------------------------------------------------------------------ Google Trends — Trending Now
TRENDING = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss"><channel>
<item><title>aspirador robô xiaomi</title><ht:approx_traffic>2.000+</ht:approx_traffic><pubDate>Wed, 14 Oct 2026 10:00:00 -0700</pubDate>
<ht:news_item><ht:news_item_title>Teste</ht:news_item_title><ht:news_item_url>https://exemplo.test/a</ht:news_item_url></ht:news_item></item>
<item><title>flamengo x palmeiras</title><ht:approx_traffic>500K+</ht:approx_traffic><pubDate>Wed, 14 Oct 2026 10:00:00 -0700</pubDate></item>
<item><title>recall air fryer marca x</title><ht:approx_traffic>200+</ht:approx_traffic><pubDate>Wed, 14 Oct 2026 10:00:00 -0700</pubDate></item>
</channel></rss>"""


class TrendsHttp:
    def __init__(self):
        self.calls = []
        self.cancel_event = threading.Event()

    def request_text(self, url, **kw):
        self.calls.append(url)
        if "trendingsearches" in url:
            raise AssertionError("não deveria usar o endereço antigo quando o novo responde")
        return TRENDING


def test_traffic_ranges():
    assert parse_traffic("2.000+") == (2000.0, "2.000+") and parse_traffic("500K+")[0] == 500000
    items = parse_trending(TRENDING)
    assert [i["faixa"] for i in items] == ["2.000+", "500K+", "200+"] and items[0]["noticias"][0]["url"]


def test_trending_connector_commercial_filter_and_idempotence(tmp_path):
    db = Database(tmp_path / "t.sqlite")
    from gpi.market.store import MarketStore
    store = MarketStore(db)
    ctx = SyncContext(TrendsHttp(), store, {}, TODAY)
    c = GoogleTrendsTrending()
    jobs = c.plan(ctx)
    assert {j.params["geo"] for j in jobs} == {"BR", "US"} and all(j.refresh_days is None for j in jobs)
    for _ in range(2):                                              # mesma coleta repetida não duplica
        c.run(jobs[0], ctx)
    rows = db.query("SELECT term, product_id, intent, commercial, value, extra FROM search_observations ORDER BY term")
    assert len(rows) == 3
    by = {r["term"]: r for r in rows}
    assert by["aspirador robô xiaomi"]["product_id"] == "vacuum+robot" and by["aspirador robô xiaomi"]["commercial"] == 1
    assert by["flamengo x palmeiras"]["product_id"] is None and by["flamengo x palmeiras"]["commercial"] == 0
    assert by["recall air fryer marca x"]["intent"] == "noticia" and by["recall air fryer marca x"]["commercial"] == 0
    assert json.loads(by["aspirador robô xiaomi"]["extra"])["faixa"] == "2.000+"


# ------------------------------------------------------------------ Google Ads Keyword Planner
ADS = {"results": [{"text": "air fryer", "keywordIdeaMetrics": {"avgMonthlySearches": "450000", "competition": "HIGH",
        "competitionIndex": "87", "monthlySearchVolumes": [{"month": "SEPTEMBER", "year": "2026", "monthlySearches": "450000"},
                                                           {"month": "AUGUST", "year": "2026", "monthlySearches": "368000"}]}},
       {"text": "receita de bolo", "keywordIdeaMetrics": {"avgMonthlySearches": "1000"}}]}


class FakeCreds:
    def __init__(self, d):
        self.d = d

    def get(self, k):
        return self.d.setdefault(k, {})

    def set(self, k, v):
        self.d.setdefault(k, {}).update(v)


class AdsHttp:
    def __init__(self, dead=("v23", "v22")):
        self.dead, self.urls = set(dead), []
        self.cancel_event = threading.Event()

    def request_json(self, url, method="GET", body=None, headers=None, ttl=None, form=None, **kw):
        self.urls.append(url)
        if "oauth2.googleapis.com/token" in url:
            return {"access_token": "tok", "expires_in": 3600}
        v = url.split("/")[3]
        if v in self.dead:
            raise SourceError("recurso não encontrado (HTTP 404)", "http", status=404)
        assert headers["developer-token"] == "DT" and headers["Authorization"] == "Bearer tok"
        return ADS


def test_keyword_ideas_parse_and_version_probe():
    ideas = parse_keyword_ideas(ADS)
    assert ideas[0]["meses"] == [("2026-08-01", 368000.0), ("2026-09-01", 450000.0)]
    creds = FakeCreds({"google_ads": {"refresh_token": "r", "developer_token": "DT", "customer_id": "123-456-7890"}})
    http = AdsHttp()
    gads_call(http, creds, ":generateKeywordIdeas", {})
    assert creds.get("google_ads")["api_version"] == "v21"            # versões desligadas foram puladas
    assert "/customers/1234567890:generateKeywordIdeas" in http.urls[-1]


def test_keyword_planner_unavailable_without_credentials_and_stores_approx_volume(tmp_path):
    db = Database(tmp_path / "k.sqlite")
    from gpi.market.store import MarketStore
    c = GoogleAdsKeywordPlanner()
    ctx0 = SyncContext(AdsHttp(), MarketStore(db), {}, TODAY, creds=FakeCreds({}))
    assert not c.available(ctx0)
    creds = FakeCreds({"google_ads": {"refresh_token": "r", "developer_token": "DT", "customer_id": "1"}})
    ctx = SyncContext(AdsHttp(dead=()), MarketStore(db), {}, TODAY, creds=creds)
    Catalog(db).ensure_seeded()
    assert c.available(ctx)
    jobs = c.plan(ctx)
    assert {j.params["geo"] for j in jobs} == {"BR", "US"} and all(len(j.params["keywords"]) <= 20 for j in jobs)
    c.run(jobs[0], ctx)
    rows = db.query("SELECT term, metric, unit, product_id FROM search_observations")
    assert {r["term"] for r in rows} == {"air fryer"}                  # ideia sem produto não entra
    assert rows[0]["metric"] == "volume_mensal_aprox" and "aproximado" in rows[0]["unit"]


# ------------------------------------------------------------------ UN Comtrade: limites documentados
def test_comtrade_respects_period_limits(tmp_path):
    db = Database(tmp_path / "ct.sqlite")
    from gpi.market.store import MarketStore
    st = MarketStore(db)
    st.save_result("discovery_headings", {"prioritarias": [{"codigo": "8516"}, {"codigo": "8504"}]})
    c = UnComtrade()
    no_key = c.plan(SyncContext(None, st, {}, TODAY, creds=FakeCreds({})))
    assert all("," not in j.params["period"] for j in no_key)            # preview: 1 período por chamada
    with_key = c.plan(SyncContext(None, st, {}, TODAY, creds=FakeCreds({"comtrade": {"api_key": "K"}})))
    assert all(1 <= len(j.params["period"].split(",")) <= 12 for j in with_key)
    assert len(with_key) < len(no_key) / 6
    old = [j for j in no_key if j.params["period"] < f"{TODAY.year - 1}01"]
    assert old and all(j.refresh_days is None for j in old)             # meses antigos não são recoletados


# ------------------------------------------------------------------ análise de tendências
def _obs(db, src, cc, pid, metric, pts, period="mes", com=1, intent_="compra"):
    for d, v in pts:
        db.execute("INSERT OR REPLACE INTO search_observations (source,country,region,term,ref_date,period,metric,value,unit,"
                   "lang,product_id,intent,commercial,collected_at) VALUES (?,?,'',?,?,?,?,?,'x','pt',?,?,?,?)",
                   (src, cc, pid, d, period, metric, v, pid, intent_, com, TODAY.isoformat()))


def _months(n, end=date(2026, 9, 1)):
    out, d = [], end
    for _ in range(n):
        out.append(d)
        d = date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 1)
    return [x.isoformat() for x in reversed(out)]


def test_rankings_separate_metrics_and_explain_missing_volume(tmp_path):
    db = Database(tmp_path / "r.sqlite")
    days = [(TODAY - timedelta(days=i)).isoformat() for i in range(8)]
    _obs(db, "google_trends_rss", "BR", "vacuum+robot", "trafego_faixa", [(d, 2000) for d in days], period="dia")
    r = trends.analyze(db, {}, TODAY, forecasts=False)
    br = r["paises"]["BR"]["rankings"]
    assert br["mais_pesquisados"]["itens"] == [] and "Google Ads" in br["mais_pesquisados"]["limitacao"]
    assert br["em_alta"]["itens"][0]["product_id"] == "vacuum+robot"
    assert all(i["metrica"] == "trafego_faixa" for i in br["em_alta"]["itens"])
    assert r["paises"]["CN"]["rankings"]["mais_pesquisados"]["itens"] == []
    assert any("China continental" in l for l in r["paises"]["CN"]["limitacoes"])
    assert br["emergentes"]["itens"][0]["product_id"] == "vacuum+robot"


def test_yoy_growth_seasonal_consistency_and_scores(tmp_path):
    db = Database(tmp_path / "y.sqlite")
    ms = _months(36)
    rng = np.random.default_rng(0)
    _obs(db, "google_ads_kp", "BR", "air_fryer", "volume_mensal_aprox",
         [(d, 10000 * (1 + 0.02 * k) * (1 + 0.3 * math.sin(2 * math.pi * int(d[5:7]) / 12)) + rng.normal(0, 200))
          for k, d in enumerate(ms)])
    _obs(db, "google_ads_kp", "BR", "lock+electronic", "volume_mensal_aprox",
         [(d, 3000 * (1 - 0.015 * k) + rng.normal(0, 40)) for k, d in enumerate(ms)])
    r = trends.analyze(db, {}, TODAY, forecasts=True)
    s = {x["product_id"]: x for x in r["series"]}
    assert s["air_fryer"]["ind"]["base_crescimento"].startswith("12 meses") and s["air_fryer"]["ind"]["crescimento"] > 0.1
    assert s["air_fryer"]["ind"]["classe"] == "crescimento consistente"
    assert s["air_fryer"]["ind"]["sazonalidade"]["significativa"]
    assert s["lock+electronic"]["ind"]["classe"] == "declínio"
    sc = r["scores"]["air_fryer"]
    assert 0 <= sc["opportunity_score"] <= 100 and sc["forecast_confidence"] > 0
    assert "sem preços observados: margem e rentabilidade não são estimadas" in sc["riscos"]
    assert sc["checklist_importacao"]["NCM/SH fundamentado"] and not sc["checklist_importacao"]["Preços observados"]
    f = next(v for k, v in r["previsoes"].items() if k.startswith("air_fryer"))
    assert f["tipo"] == "busca" and "não unidades vendidas" in f["tipo_descricao"]


def test_missing_source_does_not_penalize_opportunity(tmp_path):
    a = Database(tmp_path / "a.sqlite")
    ms = _months(30)
    pts = [(d, 1000 * (1 + 0.03 * k)) for k, d in enumerate(ms)]
    _obs(a, "google_ads_kp", "BR", "air_fryer", "volume_mensal_aprox", pts)
    s1 = trends.analyze(a, {}, TODAY, forecasts=False)["scores"]["air_fryer"]
    _obs(a, "google_ads_kp", "US", "air_fryer", "volume_mensal_aprox", pts)
    s2 = trends.analyze(a, {}, TODAY, forecasts=False)["scores"]["air_fryer"]
    assert s2["evidence_coverage"] >= s1["evidence_coverage"]
    assert abs(s2["opportunity_score"] - s1["opportunity_score"]) < 15


def test_change_points_anomalies_and_lead_lag():
    y = np.r_[np.full(20, 10.0), np.full(20, 30.0)] + np.random.default_rng(1).normal(0, 0.5, 40)
    cps = trends.change_points(y)
    assert cps and abs(cps[0] - 20) <= 1
    z = np.full(30, 100.0) + np.random.default_rng(2).normal(0, 2, 30)
    z[25] = 400
    assert 25 in trends.anomalies(z)
    rng = np.random.default_rng(3)
    lead = np.cumsum(rng.normal(0, 1, 60)) + 50
    a = np.exp(lead / 20) * 100
    b = np.r_[a[:3], a[:-3]]                      # B segue A com 3 meses de atraso
    ll = trends.lead_lag(a, b)
    assert ll["lag"] == 3 and ll["significativa"] and ll["interpretacao"] == "A antecede B"
    assert "não implica causalidade" in ll["aviso"]
    assert trends.lead_lag(a[:10], b[:10]) is None                  # histórico curto: sem análise


# ------------------------------------------------------------------ sincronização: paralelismo, etapas, cache
class Slow(Connector):
    def __init__(self, cid, stage=1, delay=0.3, log=None):
        self.id, self.name, self.stage, self.delay, self.log, self.order = cid, cid, stage, delay, log, 50

    def plan(self, ctx):
        return [Job(f"{self.id}:{i}", {"i": i}, refresh_days=None) for i in range(2)]

    def run(self, job, ctx):
        self.log.append((self.id, "ini", time.monotonic()))
        time.sleep(self.delay)
        self.log.append((self.id, "fim", time.monotonic()))
        return [], []


def test_parallel_sources_faster_and_stages_ordered(tmp_path):
    def run(workers):
        log = []
        db = Database(tmp_path / f"s{workers}.sqlite")
        conns = [Slow("a", 1, log=log), Slow("b", 1, log=log), Slow("c", 1, log=log), Slow("dep", 2, log=log)]
        sm = SyncManager(db, tmp_path, {"sync_workers": workers}, connectors=conns, http=TrendsHttp(), today_fn=lambda: TODAY)
        t0 = time.monotonic()
        sm.run("teste")
        return time.monotonic() - t0, log, db
    t_seq, _, _ = run(1)
    t_par, log, db = run(4)
    assert t_par < t_seq * 0.6                                        # 3 fontes independentes em paralelo
    start_dep = min(t for c, k, t in log if c == "dep" and k == "ini")
    end_stage1 = max(t for c, k, t in log if c != "dep" and k == "fim")
    assert start_dep >= end_stage1                                    # etapa 2 só após a etapa 1
    m = db.query("SELECT source, jobs_ok, seconds FROM source_metrics")
    assert {r["source"] for r in m} == {"a", "b", "c", "dep"} and all(r["jobs_ok"] == 2 for r in m)


# ------------------------------------------------------------------ migração de um banco da Fase 3
def test_migration_from_phase3_database_preserves_data(tmp_path):
    import sqlite3
    path = tmp_path / "fase3.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE schema_version (v INTEGER NOT NULL)")
    for i, stmts in enumerate(MIGRATIONS[:3], start=1):
        for s in stmts:
            con.execute(s)
        con.execute("INSERT INTO schema_version VALUES (?)", (i,))
    con.execute("INSERT INTO market_series (id, series_key, source, indicator, kind, freq, first_collected, last_collected)"
                " VALUES (1, 'comex:x', 'comexstat', 'Importação', 'observado', 'M', '2026-01-01', '2026-01-01')")
    con.executemany("INSERT INTO market_obs (series_id, ref_date, value, collected_at) VALUES (1, ?, ?, '2026-01-01')",
                    [(f"2020-{m:02d}-01", float(m)) for m in range(1, 13)])
    con.commit()
    con.close()
    db = Database(path)
    assert db.schema_version() == 4
    assert db.query("SELECT COUNT(*) AS n FROM market_obs")[0]["n"] == 12
    assert db.query("SELECT COUNT(*) AS n FROM catalog_products")[0]["n"] == 0
    Catalog(db).ensure_seeded()
    assert db.query("SELECT COUNT(*) AS n FROM market_obs")[0]["n"] == 12


# ------------------------------------------------------------------ API e regressão de Vendas próprias
def test_consumer_api_and_own_sales_still_work(tmp_path):
    import urllib.parse
    from test_api_integration import Srv
    srv = Srv(tmp_path / "d")                       # servidor real em 127.0.0.1 (mesmo usado nos testes da Fase 1)
    try:
        get = lambda path: srv.req(path)
        code, d = get("/api/consumer/dashboard")
        assert code == 200 and d["kpis"]["produtos_monitorados"] >= 100 and d["kpis"]["paises_com_buscas"] == []
        assert get("/api/consumer/country/CN")[1]["rankings"]["mais_pesquisados"]["itens"] == []
        assert get("/api/consumer/country/XX")[0] == 404
        p = get("/api/consumer/product/" + urllib.parse.quote("charger+usb_c:65w"))[1]
        assert p["produto"]["parent_id"] == "charger+usb_c"
        a = get("/api/consumer/analyze?texto=" + urllib.parse.quote("comprar fone bluetooth"))[1]
        assert a["produto"]["chave"] == "earbuds" and a["intencao"]["intencao"] == "compra"
        for path in ("/api/consumer/opportunities", "/api/consumer/alerts", "/api/consumer/anomalies", "/api/consumer/forecasts",
                     "/api/consumer/discovery", "/api/consumer/catalog?q=air", "/api/consumer/performance", "/api/consumer/compare"):
            assert get(path)[0] == 200, path
        # Vendas próprias (regressão): importar, listar, prever
        assert srv.req("/api/demo", {})[0] == 200
        sku = get("/api/skus")[1][0]["sku"]
        code, fc = srv.req("/api/forecast", {"sku": sku, "horizon": 3})
        assert code == 200 and len(fc["modelos"][fc["modelo_escolhido"]]["previsao"]) == 3
        html = srv.req("/", raw=True)[1].decode("utf-8")
        assert 'id="grp-sales-h"' in html and 'aria-controls="grp-sales"' in html and "consumer.js" in html and "shell.js" in html
    finally:
        srv.stop()


def test_no_dynamic_internal_imports_for_pyinstaller():
    """O PyInstaller só empacota módulos importados de forma estática: __import__("gpi...") faria o
    GPI.exe falhar com ModuleNotFoundError (aconteceu na Fase 4 com gpi.products.api)."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    offenders = [str(p) for p in (root / "backend" / "gpi").rglob("*.py") if '__import__("gpi' in p.read_text(encoding="utf-8")]
    assert offenders == []
    spec = (root / "packaging" / "gpi.spec").read_text(encoding="utf-8")
    assert 'sys.path.insert(0, os.path.join(ROOT, "backend"))' in spec and '"gpi.products.api"' in spec
