"""v0.5 — fontes novas (respostas no formato documentado, sintéticas), Discovery 2.0, ML avançado,
tendências, viabilidade, concorrência, reviews, configurações, busca e interface. Dados SINTÉTICOS:
servem para testar a lógica; nenhuma fonte é declarada validada por estes testes."""
import json
import math
import threading
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from gpi.connectors.sources5 import (BQ_TABLES, EbayBrowse, Gdelt, GoogleTrendsBigQuery, MercadoLivreTrends, bq_rows,
                                     bq_sql, ms_envelope, parse_ebay, parse_gdelt_timeline, parse_ms_volumes)
from gpi.connectors.http import SourceError
from gpi.db import MIGRATIONS, Database
from gpi.forecasting import advanced as A
from gpi.market.store import MarketStore
from gpi.market.sync import SyncContext
from gpi.market.viability import simulate
from gpi.products import discovery, trends
from gpi.products.catalog import Catalog

TODAY = date(2026, 11, 2)
ROOT = Path(__file__).resolve().parents[1]
HAS = A.libs()


class Creds:
    def __init__(self, d):
        self.d = d

    def get(self, k):
        return self.d.setdefault(k, {})

    def set(self, k, v):
        self.d.setdefault(k, {}).update(v)


class Http:
    def __init__(self, routes):
        self.routes, self.calls = routes, []
        self.cancel_event = threading.Event()

    def _match(self, url):
        self.calls.append(url)
        for k, v in self.routes.items():
            if k in url:
                return v(url) if callable(v) else v
        raise SourceError("não encontrado", "http", status=404)

    def request_json(self, url, method="GET", body=None, headers=None, ttl=None, min_interval=None, form=None, **kw):
        self.last = {"url": url, "body": body, "headers": headers, "form": form}
        return self._match(url)

    def request_text(self, url, **kw):
        return self._match(url)


def _ctx(tmp_path, http, creds=None, cfg=None):
    db = Database(tmp_path / "x.sqlite")
    Catalog(db).ensure_seeded()
    return SyncContext(http, MarketStore(db), cfg or {}, TODAY, creds=Creds(creds or {})), db


# ------------------------------------------------------------------ Mercado Livre Trends
def test_ml_trends_ranking_not_volume_and_history(tmp_path):
    payload = [{"keyword": "air fryer", "url": "https://lista.mercadolivre.com.br/air-fryer"},
               {"keyword": "camisa flamengo 2026", "url": "u"}, {"keyword": "fone bluetooth", "url": "u2"}]
    ctx, db = _ctx(tmp_path, Http({"/trends/MLB": payload}), {"mercadolivre": {"access_token": "t", "expires_at": "9e12"}})
    c = MercadoLivreTrends()
    assert c.available(ctx)
    c.run(c.plan(ctx)[0], ctx)
    c.run(c.plan(ctx)[0], ctx)                                    # repetir no mesmo dia não duplica
    rows = db.query("SELECT term, value, unit, product_id, commercial FROM search_observations ORDER BY value")
    assert [r["value"] for r in rows] == [1, 2, 3] and "posição" in rows[0]["unit"]
    assert rows[0]["product_id"] == "air_fryer" and rows[1]["commercial"] == 0
    assert not MercadoLivreTrends().available(_ctx(tmp_path / "b", Http({}))[0])


# ------------------------------------------------------------------ Google Trends BigQuery
def _bq_payload(rows, kind="top"):
    fields = ["term", "country", "region", "region_name", "week", "score", "rank"] + (["percent_gain"] if kind == "rising" else [])
    return {"schema": {"fields": [{"name": f} for f in fields]},
            "rows": [{"f": [{"v": r.get(f)} for f in fields]} for r in rows]}


def test_bigquery_dry_run_limit_and_storage(tmp_path):
    rows = [{"term": "air fryer", "country": "BR", "region": "BR-SP", "region_name": "São Paulo", "week": "2026-10-25", "score": "87", "rank": "3"},
            {"term": "eleições 2026", "country": "BR", "region": "BR-SP", "region_name": "São Paulo", "week": "2026-10-25", "score": "100", "rank": "1"}]
    dry = {"totalBytesProcessed": str(int(0.5e9))}

    def route(url):
        return dry if Http_last["body"]["dryRun"] else _bq_payload(rows)
    http = Http({"bigquery.googleapis.com": lambda u: dry if http.last["body"]["dryRun"] else _bq_payload(rows),
                 "oauth2.googleapis.com/token": {"access_token": "a", "expires_in": 3600}})
    Http_last = None  # noqa: F841
    ctx, db = _ctx(tmp_path, http, {"google_bigquery": {"refresh_token": "r", "project_id": "meu-proj", "client_id": "c"}},
                   {"bq_max_gb": 2, "trends_geos": ["BR"]})
    c = GoogleTrendsBigQuery()
    jobs = c.plan(ctx)
    assert {j.params["table"] for j in jobs} == {"international_top_terms", "international_top_rising_terms"}
    c.run(jobs[0], ctx)
    r = db.query("SELECT term, region, metric, value, unit, commercial FROM search_observations ORDER BY term")
    assert r[0]["term"] == "air fryer" and r[0]["region"] == "BR-SP" and "relativo" in r[0]["unit"] and r[0]["commercial"] == 1
    assert r[1]["commercial"] == 0
    sql = bq_sql("international_top_terms", "2026-11-01", ["BR", "US"])
    assert "refresh_date = '2026-11-01'" in sql and "IN ('BR')" in sql             # partição filtrada; EUA vêm de top_terms
    dry["totalBytesProcessed"] = str(int(5e9))
    with pytest.raises(SourceError) as e:
        c.run(jobs[0], ctx)
    assert "não executada" in str(e.value)


# ------------------------------------------------------------------ eBay e GDELT e Microsoft
EBAY = {"itemSummaries": [{"itemId": f"v1|{i}", "title": f"Ninja Air Fryer {4 + i % 3}L AF{100 + i}", "price": {"value": str(80 + i), "currency": "USD"},
                           "seller": {"username": f"loja{i % 4}"}, "itemWebUrl": "https://ebay.test/x", "condition": "New",
                           **({"marketingPrice": {"originalPrice": {"value": "120", "currency": "USD"}}} if i % 5 == 0 else {})}
                          for i in range(12)]}


def test_ebay_listings_and_competition(tmp_path):
    http = Http({"identity/v1/oauth2/token": {"access_token": "t", "expires_in": 7200}, "item_summary/search": EBAY})
    ctx0, _ = _ctx(tmp_path / "sem", http, {"ebay": {"client_id": "a", "client_secret": "b"}}, {"ebay_max_products": 2})
    assert not EbayBrowse().available(ctx0)            # v0.8.2: sem conformidade de exclusão, nada do eBay é gravado
    ctx, db = _ctx(tmp_path, http, {"ebay": {"client_id": "a", "client_secret": "b", "sync_token": "s" * 40}}, {"ebay_max_products": 2})
    c = EbayBrowse()
    assert c.available(ctx) and len(c.plan(ctx)) == 2
    job = next(j for j in c.plan(ctx))
    c.run(job, ctx)
    assert len(parse_ebay(EBAY)) == 12
    from gpi.market.reviews2 import competition
    comp = competition(db)["itens"][0]
    assert comp["anuncios"] == 12 and comp["vendedores_unicos"] == 4 and comp["anuncios_em_promocao"] == 3
    assert 0 <= comp["pressao_competitiva"] <= 100 and comp["marcas"][0]["marca"] == "ninja"
    sellers = {r["seller"] for r in db.query("SELECT DISTINCT seller FROM market_listings WHERE source = 'ebay'")}
    assert sellers and all(x.startswith("h:") for x in sellers)          # v0.8.2: só pseudônimos


def test_gdelt_timeline_monthly(tmp_path):
    tl = {"timeline": [{"series": "Article Count", "data": [{"date": "20261001T000000Z", "value": 3, "norm": 900},
                                                            {"date": "20261002T000000Z", "value": 5, "norm": 950},
                                                            {"date": "20261101T000000Z", "value": 2, "norm": 800}]}]}
    assert parse_gdelt_timeline(tl)[1] == ("2026-10-02", 5.0, 950.0)
    ctx, db = _ctx(tmp_path, Http({"api.gdeltproject.org": tl}), cfg={"gdelt_max_products": 1})
    c = Gdelt()
    c.run(c.plan(ctx)[0], ctx)
    r = db.query("SELECT ref_date, value, metric, commercial FROM search_observations ORDER BY ref_date")
    assert [(x["ref_date"], x["value"]) for x in r] == [("2026-10-01", 8.0), ("2026-11-01", 2.0)]
    assert r[0]["metric"] == "noticias_gdelt" and r[0]["commercial"] == 0          # notícia não é consumo


def test_microsoft_soap_envelope_and_parse():
    env = ms_envelope({"developer_token": "D", "customer_id": "1", "account_id": "2"}, "tok", ["air fryer", "a&b"], "BR",
                      "Portuguese", date(2025, 10, 1), date(2026, 9, 30))
    assert "<DeveloperToken>D</DeveloperToken>" in env and "a&amp;b" in env and "<TimePeriodRollup>Monthly" in env
    xml = ('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><GetHistoricalSearchVolumeResponse xmlns="x">'
           '<KeywordSearchCounts><KeywordSearchCount><Keyword>air fryer</Keyword><SearchCountsByAttributes><SearchCountsByAttributes>'
           '<SearchCounts><SearchCount><DayMonthAndYear><Day>1</Day><Month>9</Month><Year>2026</Year></DayMonthAndYear>'
           '<SearchCount>12345</SearchCount></SearchCount></SearchCounts></SearchCountsByAttributes></SearchCountsByAttributes>'
           '</KeywordSearchCount></KeywordSearchCounts></GetHistoricalSearchVolumeResponse></s:Body></s:Envelope>')
    assert parse_ms_volumes(xml) == [{"termo": "air fryer", "mes": "2026-09-01", "buscas": 12345.0}]
    fault = '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><s:Fault><faultstring>Invalid token</faultstring></s:Fault></s:Body></s:Envelope>'
    with pytest.raises(SourceError):
        parse_ms_volumes(fault)


# ------------------------------------------------------------------ Discovery 2.0
def test_typo_correction_and_no_false_grouping():
    assert discovery.analyze("carregadro sem fio")["produto"]["chave"] == "charger+wireless"
    assert discovery.analyze("umidifcador de ar")["produto"]["chave"] == "humidifier"
    assert not discovery.compatible("carregador usb-c 20w", "carregador usb-c 140w")
    assert discovery.compatible("carregador gan 65w", "65w gan charger")
    assert discovery.analyze("capacete de bicicleta")["produto"]["chave"] != "helmet+motorcycle"
    assert discovery.analyze("notícia sobre economia")["produto"] is None
    assert discovery.similarity("carregador usb c 65w", "carregador usb-c 65 w") >= 90


def test_catalog_uses_discovery_for_typos(tmp_path):
    db = Database(tmp_path / "c.sqlite")
    c = Catalog(db)
    c.ensure_seeded()
    assert c.observe("fechdura eletronica", "google_trends_rss", "BR", "compra", strong=True) == "lock+electronic"


@pytest.mark.skipif(not HAS["rapidfuzz"], reason="RapidFuzz não instalado (roda no CI)")
def test_rapidfuzz_backend_active():
    assert discovery.BACKEND == "rapidfuzz" and discovery.similarity("air fryer 4l", "4l air fryer") == 100


# ------------------------------------------------------------------ ML avançado
def _panel(n_series=12, n=48, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n_series):
        m = [(k % 12) + 1 for k in range(n)]
        y = 1000 * (1 + 0.03 * (i % 4) * np.arange(n) / 12) * (1 + 0.25 * np.sin(2 * np.pi * np.array(m) / 12)) * rng.lognormal(0, 0.05, n)
        out.append({"id": f"s{i}", "y": y, "months": m, "labels": [f"{2022 + k // 12}-{(k % 12) + 1:02d}" for k in range(n)],
                    "nome": f"p{i}", "meta": {"family": f"f{i % 3}", "category": f"c{i % 2}", "country": "BR", "source": "kp"}})
    return out


def test_global_vs_local_backtest_and_conformal():
    ev = A.evaluate(_panel(), 6, 3)
    assert {"local", "hist_gb_global"} <= set(ev["resumo"])
    assert sum(ev["vitorias_por_serie"].values()) == 12
    c = A.conformal(ev["erros"]["hist_gb_global"])
    q = c["quantis"]
    assert all(a <= b <= d for a, b, d in zip(q["0.8"], q["0.9"], q["0.95"]))      # intervalos aninhados
    assert set(c["cobertura_observada"]) == {"0.8", "0.9", "0.95"}
    lo, hi = A.interval(np.array([100.0, 200.0]), [0.1, 0.2])
    assert lo[0] < 100 < hi[0]


def test_drift_detectors_and_reconciliation():
    rng = np.random.default_rng(1)
    y = np.r_[np.full(24, 100.0), np.full(24, 250.0)] * rng.lognormal(0, 0.03, 48)
    ev = A.detect_drift(y, [str(i) for i in range(48)])
    assert ev and all(e["direcao"] == "alta" and 24 <= e["indice"] <= 40 for e in ev)
    assert A.detect_drift(np.full(30, 50.0) * rng.lognormal(0, 0.02, 30), [str(i) for i in range(30)]) == []
    S, _ = A.summing_matrix({}, 3)
    yhat = np.array([[10.0], [3.0], [3.0], [3.0]])
    for m in ("bu", "mint_ols", "mint_wls"):
        r = A.reconcile(S, yhat, m)
        assert abs(r[0, 0] - r[1:, 0].sum()) < 1e-9                         # coerência: total = soma das bases
    td = A.reconcile(S, yhat, "td", hist=np.array([[1.0, 1], [1, 1], [2, 2]]))
    assert np.allclose(td[1:, 0], [2.5, 2.5, 5])


def test_run_all_reuses_when_unchanged_and_skips_indices():
    series = []
    for s in _panel(6):
        series.append({"id": s["id"] + "|BR|google_ads_kp|volume_mensal_aprox", "product_id": "air_fryer", "country": "BR",
                       "source": "google_ads_kp", "metric": "volume_mensal_aprox", "period": "mes", "categoria": "c", "nome": s["nome"],
                       "ind": {"n": 48, "labels": s["labels"], "valores": s["y"].tolist()}})
    cons = {"series": series}
    r1 = A.run_all(cons, {"ml_tuning_trials": 0})
    g = r1["grupos"]["volume_mensal_aprox"]
    assert not g["reutilizado"] and g["por_serie"] and all(len(v["previsao"]) == 6 for v in g["por_serie"].values())
    assert any(v["intervalos"] for v in g["por_serie"].values())
    r2 = A.run_all(cons, {"ml_tuning_trials": 0}, previous=r1)
    assert r2["grupos"]["volume_mensal_aprox"]["reutilizado"]


@pytest.mark.skipif(not (HAS["lightgbm"] and HAS["catboost"]), reason="LightGBM/CatBoost não instalados (rodam no CI)")
def test_global_boosting_models_and_shap():
    p = _panel()
    ev = A.evaluate(p, 6, 2)
    assert {"lightgbm_global", "catboost_global"} <= set(ev["resumo"])
    X, y = A.panel(p)
    fm = A.fit("lightgbm_global", A.make_models()["lightgbm_global"], X, y)
    e = A.explain(fm, X)
    assert e["metodo"].startswith("SHAP") and abs(sum(f["peso"] for f in e["fatores"]) - 1) < 1e-6


@pytest.mark.skipif(not (HAS["optuna"] and HAS["lightgbm"]), reason="Optuna/LightGBM não instalados (rodam no CI)")
def test_optuna_respects_limits():
    r = A.tune_lightgbm(_panel(8), trials=3, seconds=60)
    assert r and r["tentativas"] <= 3


@pytest.mark.skipif(not HAS["river"], reason="River não instalado (roda no CI)")
def test_river_drift_backend():
    y = np.r_[np.full(24, 100.0), np.full(24, 260.0)]
    assert any("River" in e["detector"] for e in A.detect_drift(y, [str(i) for i in range(48)]))


# ------------------------------------------------------------------ tendências (Early Trend Detection)
def _obs(db, src, cc, pid, metric, pts, period="mes"):
    for d, v in pts:
        db.execute("INSERT OR REPLACE INTO search_observations (source,country,region,term,ref_date,period,metric,value,unit,lang,"
                   "product_id,intent,commercial,collected_at) VALUES (?,?,'',?,?,?,?,?,'x','pt',?,'compra',1,'2026-11-01')",
                   (src, cc, pid, d, period, metric, v, pid))


def _months(n, end=date(2026, 10, 1)):
    out, d = [], end
    for _ in range(n):
        out.append(d.isoformat())
        d = date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 1)
    return list(reversed(out))


def test_small_series_do_not_dominate_and_international_signal(tmp_path):
    db = Database(tmp_path / "t.sqlite")
    ms = _months(36)
    _obs(db, "google_ads_kp", "BR", "air_fryer", "volume_mensal_aprox", [(d, 2000 * (1 + 0.02 * k)) for k, d in enumerate(ms)])
    _obs(db, "google_ads_kp", "BR", "drone", "volume_mensal_aprox", [(d, 1 if k < 30 else 9) for k, d in enumerate(ms)])   # minúscula, +800%
    _obs(db, "google_ads_kp", "US", "air_fryer", "volume_mensal_aprox",
         [(d, 8000 * (1 + (0.06 * k if k < 30 else 1.8))) for k, d in enumerate(ms)])
    r = trends.analyze(db, {}, TODAY, forecasts=False)
    ids = [i["product_id"] for i in r["paises"]["BR"]["rankings"]["maior_crescimento"]["itens"]]
    assert "drone" not in ids and "air_fryer" in ids
    s = next(x for x in r["series"] if x["product_id"] == "air_fryer" and x["country"] == "BR")
    for k in ("persistencia", "cobertura", "confianca_classificacao", "base_suficiente"):
        assert k in s["ind"]
    sig = r["scores"]["air_fryer"]["sinal_internacional"]
    assert sig and sig["mercado_antecedente"] == "Estados Unidos" and "investigação" in sig["rotulo"]
    assert "não garante" in sig["aviso"]
    for k in ("crescimento_acelerado", "estaveis", "saturacao", "listas_de_busca", "sinal_internacional"):
        assert k in r["paises"]["BR"]["rankings"] and r["paises"]["BR"]["rankings"][k]["mede"]


def test_ranking_lists_are_not_volume(tmp_path):
    db = Database(tmp_path / "l.sqlite")
    days = [(TODAY - timedelta(days=i)).isoformat() for i in range(5)]
    _obs(db, "ml_trends", "BR", "air_fryer", "posicao_tendencia", [(d, 3) for d in days], period="dia")
    r = trends.analyze(db, {}, TODAY, forecasts=False)
    br = r["paises"]["BR"]["rankings"]
    assert br["listas_de_busca"]["itens"][0]["product_id"] == "air_fryer" and br["mais_pesquisados"]["itens"] == []
    assert "NÃO é volume" in br["listas_de_busca"]["mede"]


# ------------------------------------------------------------------ viabilidade
def test_viability_requires_user_data_and_simulates():
    r = simulate({"fob_usd": 12})
    assert r["status"] == "dados insuficientes" and any("frete_usd" in f for f in r["faltando"])
    p = {"fob_usd": {"min": 10, "base": 12, "max": 15}, "frete_usd": 1.5, "cambio": 5.5, "preco_venda_brl": {"min": 180, "base": 220, "max": 250},
         "demanda_mensal": {"min": 50, "base": 120, "max": 200}, "ii": 20, "ipi": 10, "pis": 2.1, "cofins": 9.65, "icms": 18,
         "moq": 200, "lote": 50, "orcamento_brl": 60000}
    r = simulate(p, 4000)
    assert r["status"] == "ok" and r["quantidade_sugerida"] >= 200 and r["quantidade_sugerida"] % 50 == 0
    assert r["investimento_base"] <= 60000 and r["cenarios"]["pessimista"] < r["cenarios"]["base"] < r["cenarios"]["otimista"]
    c = r["custo_base"]
    cif = (12 + 1.5) * 5.5
    assert abs(c["cif"] - cif) < 1e-9 and abs(c["icms"] / ((c["custo_unitario"] - c["despesas"]))  - 0.18) < 1e-9  # ICMS por dentro
    assert r["sensibilidade"][0]["variavel"] in ("demanda_mensal", "preco_venda_brl", "fob_usd")
    assert simulate({**p, "orcamento_brl": 100})["quantidade_sugerida"] is None


# ------------------------------------------------------------------ API, migração, interface e empacotamento
def test_settings_search_models_and_migration_v5(tmp_path):
    from test_api_integration import Srv
    srv = Srv(tmp_path / "d")
    try:
        code, d = srv.req("/api/settings")
        assert code == 200 and d["valores"]["sync_workers"] == 4
        assert srv.req("/api/settings", {"sync_workers": 99})[0] == 400
        assert srv.req("/api/settings", {"sync_workers": 3, "catalog_max_products": ""})[0] == 200
        assert srv.req("/api/settings")[1]["valores"]["sync_workers"] == 3
        res = srv.req("/api/search?q=fechadura")[1]["itens"]
        assert any(r["href"] == "#produto-consumo/lock+electronic" for r in res)
        assert srv.req("/api/search?q=brasil")[1]["itens"][0]["href"] == "#consumo/BR"
        for path in ("/api/consumer/models", "/api/consumer/reviews2", "/api/consumer/competition", "/api/import/defaults"):
            assert srv.req(path)[0] == 200, path
        assert srv.req("/api/import/simulate", {"parametros": {"fob_usd": 1}})[1]["status"] == "dados insuficientes"
        db = srv.app.state.db
        assert db.schema_version() == len(MIGRATIONS) >= 5                  # v0.6+ acrescenta migrações
        for t in ("market_listings", "model_registry", "drift_events"):
            assert db.query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] == 0
    finally:
        srv.stop()


def test_sidebar_structure_accessibility_and_routes():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    import re
    groups = re.findall(r'<button type="button" class="grp-h" id="(grp-[a-z]+-h)" aria-expanded="false" aria-controls="(grp-[a-z]+)"', html)
    assert len(groups) >= 7 and all(f'id="{c}"' in html for _, c in groups)
    for label in ("Visão Geral", "Inteligência de Consumo", "Inteligência de Mercado", "Machine Learning", "Comércio Exterior",
                  "Vendas Próprias", "Fontes e Sistema"):
        assert label in html
    hrefs = re.findall(r'<a href="#([^"]+)" data-tip', html)
    assert len(hrefs) == len(set(hrefs))                                       # sem duplicar páginas
    js = "".join((ROOT / "frontend" / f).read_text(encoding="utf-8") for f in ("app.js", "market.js", "market3.js", "consumer.js", "v05.js", "v06.js", "v061.js")
                 + tuple(p.name for p in sorted((ROOT / "frontend").glob("v0[78]*.js"))))   # v0.7+: módulos novos
    for h in hrefs:
        assert f"'{h.split('/')[0]}'" in js or f"{h.split('/')[0]}:" in js or f"'{h.split('/')[0]}':" in js, h
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css and "side-mini" in css and "--t: 180ms" in css
    shell = (ROOT / "frontend" / "shell.js").read_text(encoding="utf-8")
    assert "aria-expanded" in shell and "ArrowDown" in shell and "localStorage" in shell and "try {" in shell


def test_windows_packaging_metadata():
    vi = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    from gpi import __version__
    assert __version__ in vi and "Global Product Intelligence" in vi and "Market Research and Demand Forecasting" in vi
    assert "StringStruct('CompanyName'" not in vi                                 # sem identidade de editor não comprovada
    assert (ROOT / "packaging" / "gpi.ico").exists()
    spec = (ROOT / "packaging" / "gpi.spec").read_text(encoding="utf-8")
    assert "upx=False" in spec and "uac_admin" not in spec.replace("uac_admin=False", "") and 'icon=' in spec
    wf = (ROOT / ".github" / "workflows" / "windows-build.yml").read_text(encoding="utf-8")
    assert "MpCmdRun" in wf and "Get-FileHash" in wf and (f"GPI-Windows-Portable-v{__version__}.zip" in wf or f"GPI-Windows-Portable-v{__version__.rsplit('.', 1)[0]}.zip" in wf)
    assert "SIGNING_ENABLED" in wf                                               # assinatura opcional, só com secrets configurados
