"""Fase 2 — conectores, sincronização, normalização, AutoML, clusterização e ranking.
Dados sintéticos são usados SOMENTE aqui (tests/fake_sources.py)."""
import json
import threading
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fake_sources import FakeHttp
from gpi.connectors.base import FormatError
from gpi.connectors.http import HttpClient, HttpConfig, SourceError
from gpi.connectors.public import BcbPtax, ComexStat, IbgePmc, UnComtrade, WikimediaPageviews
from gpi.connectors.registry import all_connectors
from gpi.db import Database
from gpi.market import automl, intel, taxonomy as tx
from gpi.market.analysis import make_analyzer
from gpi.market.store import MarketStore
from gpi.market.sync import SyncManager

TODAY = date(2026, 10, 15)


# ---------------------------------------------------------------- normalização / deduplicação
def test_normalization_pt_en_accents_plural():
    assert tx.normalize_tokens("Lâmpadas de LED") == ["lampada", "led"]
    assert tx.normalize_tokens("Aquecedores elétricos") == ["aquecedor", "eletrico"]
    assert tx.normalize_tokens("Batteries for the phones") == ["battery", "phone"]
    assert tx.normalize_tokens("空气炸锅") == ["空气", "气炸", "炸锅"]


def test_similarity_and_dedupe():
    assert tx.similarity("Lâmpada LED", "lampadas led") > 0.9
    assert tx.similarity("Fritadeira elétrica", "Liquidificador") < 0.3
    groups = tx.dedupe(["Lâmpadas LED", "lampada led", "Power bank", "Power banks", "Liquidificador"])
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 2, 2]


# ---------------------------------------------------------------- cliente HTTP (servidor local real)
class _H(BaseHTTPRequestHandler):
    hits = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        n = _H.hits[self.path] = _H.hits.get(self.path, 0) + 1
        if self.path == "/flaky" and n < 3:
            self.send_response(429); self.send_header("Retry-After", "0"); self.end_headers(); return
        if self.path == "/forbidden":
            self.send_response(403); self.end_headers(); return
        if self.path == "/bad":
            self.send_response(200); self.end_headers(); self.wfile.write(b"<html>"); return
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "n": n}).encode())


@pytest.fixture(scope="module")
def local_server():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _client(tmp_path):
    sleeps = []
    c = HttpClient(tmp_path / "cache", HttpConfig(max_attempts=4, backoff_base=0.01, min_interval=0), sleep=sleeps.append)
    c.opener = __import__("urllib.request").request.build_opener(__import__("urllib.request").request.ProxyHandler({}))
    return c, sleeps


def test_http_retry_backoff_and_cache(tmp_path, local_server):
    c, sleeps = _client(tmp_path)
    r = c.request_json(local_server + "/flaky")
    assert r["ok"] and c.stats["retries"] == 2 and len(sleeps) >= 2
    r2 = c.request_json(local_server + "/flaky")            # cache: nenhuma nova requisição
    assert r2 == r and c.stats["cache_hits"] == 1


def test_http_forbidden_is_not_retried(tmp_path, local_server):
    c, _ = _client(tmp_path)
    with pytest.raises(SourceError) as e:
        c.request_json(local_server + "/forbidden", ttl=0)
    assert e.value.kind == "restrita" and _H.hits["/forbidden"] == 1


def test_http_invalid_json_and_cancel(tmp_path, local_server):
    c, _ = _client(tmp_path)
    with pytest.raises(SourceError) as e:
        c.request_json(local_server + "/bad", ttl=0)
    assert e.value.kind == "formato"
    c.cancel_event.set()
    with pytest.raises(SourceError) as e:
        c.request_json(local_server + "/ok", ttl=0)
    assert e.value.kind == "cancelada"


def test_http_network_failure_retries_then_fails(tmp_path):
    c, sleeps = _client(tmp_path)
    with pytest.raises(SourceError) as e:
        c.request_json("http://127.0.0.1:9/nada", ttl=0)
    assert e.value.kind == "rede" and len(sleeps) == 3


# ---------------------------------------------------------------- parsers dos conectores
def test_ptax_parser_keeps_closing_quote():
    p = {"value": [{"cotacaoVenda": 5.1, "dataHoraCotacao": "2025-01-02 10:00:00", "tipoBoletim": "Abertura"},
                   {"cotacaoVenda": 5.2, "dataHoraCotacao": "2025-01-02 13:00:00", "tipoBoletim": "Fechamento PTAX"}]}
    assert BcbPtax.parse(p) == [("2025-01-02", 5.2)]
    with pytest.raises(FormatError):
        BcbPtax.parse({"x": 1})


def test_ptax_url_uses_documented_odata_parameters():
    u = BcbPtax().url("CNY", 2024, TODAY)
    assert "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)" in u
    assert "@moeda='CNY'" in u and "@dataInicial='01-01-2024'" in u and "12-31-2024" in u


def test_wikimedia_parsers():
    ll = {"query": {"pages": [{"title": "Air fryer", "langlinks": [{"lang": "pt", "title": "Fritadeira sem óleo"},
                                                                  {"lang": "zh", "title": "空气炸锅"}]}]}}
    assert WikimediaPageviews.parse_langlinks(ll, "Air fryer") == {"en": "Air fryer", "pt": "Fritadeira sem óleo", "zh": "空气炸锅"}
    assert WikimediaPageviews.parse_langlinks({"query": {"pages": [{"title": "X", "missing": True}]}}, "X") is None
    pv = {"items": [{"timestamp": "2024010100", "views": 10}, {"timestamp": "2024020100", "views": 12}]}
    assert WikimediaPageviews.parse_pageviews(pv) == [("2024-01-01", 10.0), ("2024-02-01", 12.0)]


def test_comex_parser_variants_and_errors():
    p = {"data": {"list": [
        {"year": "2024", "monthNumber": "03", "headingCode": "8539", "heading": "Lâmpadas", "metricFOB": "1000", "metricKG": "10"},
        {"coAno": 2024, "month": "Abril", "heading": "8516 - Fornos", "metricFOB": 5, "metricKG": None}]}}
    rows = ComexStat.parse(p, 2024)
    assert rows[0]["date"] == "2024-03-01" and rows[0]["code"] == "8539" and rows[0]["fob"] == 1000
    assert rows[1]["date"] == "2024-04-01" and rows[1]["code"] == "8516" and rows[1]["kg"] is None
    with pytest.raises(FormatError):
        ComexStat.parse({"data": {"list": [{"foo": 1}]}}, 2024)
    b = ComexStat().body("china", 2024)
    assert b["flow"] == "import" and b["filters"] == [{"filter": "country", "values": [160]}] and b["details"] == ["heading"]


def test_comtrade_parser_error_field():
    with pytest.raises(SourceError):
        UnComtrade.parse({"error": "limite excedido", "data": []})
    assert UnComtrade.parse({"error": "", "data": [{"period": "202401", "cmdCode": "8539", "primaryValue": 7}]})[0]["value"] == 7


def test_ibge_auto_discovery_of_table():
    f = FakeHttp(TODAY)
    t, _ = IbgePmc.pick_table(f._ibge("https://servicodados.ibge.gov.br/api/v3/agregados"))
    var, cls = IbgePmc.pick_query(f._ibge("x/metadados"))
    assert t == "9999" and var["id"] == 1 and "85[all]" in cls and "11046[1]" in cls
    series = IbgePmc.parse_values(f._ibge("valores"))
    assert {s[0] for s in series} == {"Móveis e eletrodomésticos", "Material de construção"}


# ---------------------------------------------------------------- sincronização
def _manager(tmp_path, http=None, analyzer=False, cfg=None):
    db = Database(tmp_path / "m.sqlite")
    cfg = {"history_start_year": 2022, "automl_budget_s": 8, "automl_ml_series": 0, **(cfg or {})}
    sm = SyncManager(db, tmp_path, cfg, http=http or FakeHttp(TODAY),
                     analyzer=make_analyzer(cfg) if analyzer else None, today_fn=lambda: TODAY)
    return sm, db


def test_sync_collects_with_full_provenance_and_is_idempotent(tmp_path):
    sm, db = _manager(tmp_path)
    s1 = sm.run("teste")
    st = sm.store.source_status()
    for sid in ("bcb_ptax", "wikimedia", "comexstat", "ibge_pmc"):
        assert st[sid]["state"] == "funcional" and st[sid]["validated"] == 1 and st[sid]["records"] > 0
    for sid in ("amazon_br", "shopee", "google_trends", "mercadolivre"):
        assert st[sid]["state"] == "restrita" and st[sid]["validated"] == 0
    # proveniência obrigatória em todas as séries
    for s in sm.store.series():
        for f in ("source", "indicator", "kind", "freq", "origin_url", "method", "reliability", "first_collected"):
            assert s[f], (s["series_key"], f)
    n_obs = db.query("SELECT COUNT(*) AS n FROM market_obs")[0]["n"]
    s2 = sm.run("teste2")                          # nada vencido → nada recoletado
    assert db.query("SELECT COUNT(*) AS n FROM market_obs")[0]["n"] == n_obs
    assert all(v["novas"] == 0 for v in s2["fontes"].values())
    # forçar recoleta de tudo: continua sem duplicar
    db.execute("UPDATE sync_jobs SET state = 'pending'")
    sm.run("teste3")
    assert db.query("SELECT COUNT(*) AS n FROM market_obs")[0]["n"] == n_obs
    dup = db.query("SELECT series_id, ref_date, COUNT(*) c FROM market_obs GROUP BY series_id, ref_date HAVING c > 1")
    assert dup == []


def test_revision_is_recorded(tmp_path):
    sm, db = _manager(tmp_path)
    sid = sm.store.upsert_series("x", dict(source="t", indicator="i", kind="observado", freq="M"))
    assert sm.store.upsert_obs(sid, [("2024-01-01", 1.0)]) == {"novas": 1, "revisadas": 0, "iguais": 0}
    assert sm.store.upsert_obs(sid, [("2024-01-01", 2.0)])["revisadas"] == 1
    assert db.query("SELECT value, revision FROM market_obs")[0] == {"value": 2.0, "revision": 1}


def test_failure_isolated_and_never_marked_functional(tmp_path):
    http = FakeHttp(TODAY, fail_hosts={"api-comexstat.mdic.gov.br"}, broken_format={"servicodados.ibge.gov.br"})
    sm, db = _manager(tmp_path, http)
    s = sm.run("teste")
    st = sm.store.source_status()
    assert st["comexstat"]["state"] == "falhou" and st["comexstat"]["validated"] == 0
    assert st["ibge_pmc"]["state"] == "falhou" and "IBGE" in st["ibge_pmc"]["message"]
    assert st["bcb_ptax"]["state"] == "funcional"          # demais fontes seguem funcionando
    assert not sm.store.series(source="comexstat") and not sm.store.series(source="ibge_pmc")
    # job com falha tem nova tentativa agendada (backoff), não fica em loop
    row = db.query("SELECT * FROM sync_jobs WHERE source = 'comexstat' AND state = 'failed' LIMIT 1")[0]
    assert row["attempts"] == 1 and datetime.fromisoformat(row["next_try"]) > datetime.now().astimezone()


def test_proxy_block_not_retried_and_run_partial(tmp_path):
    class Blocked(FakeHttp):
        def request_json(self, url, *a, **k):
            self.calls.append(url)
            raise SourceError("a rede/proxy da empresa bloqueou o acesso", "bloqueada")
        request_text = request_json
    http = Blocked(TODAY)
    sm, db = _manager(tmp_path, http)
    sm.run("teste")
    st = sm.store.source_status()
    assert all(st[s]["state"] == "falhou" for s in ("bcb_ptax", "wikimedia", "comexstat", "ibge_pmc"))
    assert len(http.calls) == 6                 # uma tentativa por fonte (4 públicas + RSS + Trends), sem insistência
    assert db.query("SELECT state FROM sync_runs")[0]["state"] == "parcial"
    assert sm.due()                             # semana não conta como concluída


def test_resume_interrupted_jobs(tmp_path):
    sm, db = _manager(tmp_path)
    sm.run("teste")
    db.execute("UPDATE sync_jobs SET state = 'running' WHERE job_key LIKE 'bcb_ptax:USD:%'")
    db.execute("INSERT INTO sync_runs (id, started_at, trigger, state) VALUES (99, '2026-01-01', 'x', 'rodando')")
    s = sm.run("retomada")
    assert s["retomados"] >= 1 and s["fontes"]["bcb_ptax"]["jobs_ok"] >= 1
    assert db.query("SELECT state FROM sync_runs WHERE id = 99")[0]["state"] == "interrompida"


def test_weekly_due_logic(tmp_path):
    sm, db = _manager(tmp_path)
    assert sm.due()
    now = datetime.now().astimezone()
    db.execute("INSERT INTO sync_runs (id, started_at, finished_at, trigger, state) VALUES (1, ?, ?, 't', 'concluida')",
               (now.isoformat(), now.isoformat()))
    assert not sm.due()
    old = (now - timedelta(days=8)).isoformat()
    db.execute("UPDATE sync_runs SET finished_at = ?", (old,))
    assert sm.due()


def test_connector_registry_has_required_sources():
    ids = {c.id for c in all_connectors()}
    assert {"amazon_br", "amazon_us", "mercadolivre", "shopee", "aliexpress", "taobao",
            "google_trends", "comexstat", "ibge_pmc", "bcb_ptax", "wikimedia", "comtrade"} <= ids
    # v0.7: fontes sem acesso aberto retiradas das integrações ativas
    assert not ids & {"reclame_aqui", "baidu_index", "ocean_engine", "alibaba", "alibaba_insights", "jd_com"}


# ---------------------------------------------------------------- AutoML
def _seasonal(n=72, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    v = 1000 + 5 * t + 300 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 20, n)
    idx = [str(p) + "-01" for p in pd.period_range("2019-01", periods=n, freq="M")]
    return pd.Series(v, index=idx)


def test_automl_selects_seasonal_model_and_reports_quality():
    r = automl.auto_forecast(_seasonal(), {"source": "comexstat"}, allow_ml=False)
    assert r["status"] == "prevista" and r["tipo"] == "importacao"
    assert r["perfil"]["sazonal"] and "holt_winters" in r["candidatos"]
    # v0.7.1: o ETS automático também disputa; vale se escolher uma especificação sazonal (ex.: AAA)
    seasonal_ets = r["modelo"] == "ets_auto" and str(r["parametros"].get("spec", "")).endswith("A")
    assert (r["modelo"] in ("holt_winters", "seasonal_naive") or seasonal_ets) and r["qualidade"] == "boa"
    assert len(r["previsao"]) == 12 and all(l <= p <= h for l, p, h in zip(r["lo80"], r["previsao"], r["hi80"]))


def test_automl_short_series_is_exploratory_and_interest_type():
    s = _seasonal(10)
    r = automl.auto_forecast(s, {"source": "wikimedia"})
    assert r["status"] == "exploratoria" and r["tipo"] == "interesse" and "previsao" not in r


def test_automl_gaps_are_not_filled():
    s = _seasonal(60).drop(index=["2021-06-01"])
    reg = automl.regular_monthly(s)
    assert str(reg.index[0]) == "2021-07" and not reg.isna().any()


def test_automl_reuses_and_evaluates_previous(tmp_path):
    db = Database(tmp_path / "a.sqlite")
    st = MarketStore(db)
    sid = st.upsert_series("s", dict(source="comexstat", indicator="i", kind="observado", freq="M"))
    full = _seasonal(66)
    st.upsert_obs(sid, list(full.iloc[:60].items()))
    assert automl.run_series(st, sid, allow_ml=False)["reutilizada"] is False
    assert automl.run_series(st, sid, allow_ml=False)["reutilizada"] is True
    st.upsert_obs(sid, list(full.iloc[60:].items()))
    automl.run_series(st, sid, allow_ml=False)
    ev = automl.latest(st, sid)["avaliacao_anteriores"]
    assert ev and ev[0]["periodos_avaliados"] == 6 and ev[0]["wape_realizado"] < 0.2


# ---------------------------------------------------------------- pipeline completo, clusters e ranking
def test_full_autonomous_pipeline_and_offline_api(tmp_path):
    sm, db = _manager(tmp_path, analyzer=True)
    s = sm.run("abertura")
    a = s["analise"]
    assert "erro" not in a["descoberta"] and a["descoberta"]["posicoes"] >= 10
    assert a["oportunidades"]["produtos"] > 10 and a["previsoes"]["treinadas"] > 0
    opp = sm.store.load_result("opportunities")
    assert abs(sum(opp["pesos"].values()) - 1) < 1e-9
    for it in opp["itens"]:
        assert it["score"] is None or 0 <= it["score"] <= 100
        assert it["rotulo"] in intel.LABELS
    rk = opp["rankings"]
    for k in ("emergentes", "crescimento_consistente", "investigacao_importacao", "possivel_declinio",
              "categorias_aceleracao", "sinais_brasil"):
        assert k in rk
    assert all(len(v) <= 20 for k, v in rk.items() if k != "categorias_aceleracao")
    # o produto com crescimento de 90% a.a. deve superar o de −20% a.a.
    sc = {i["product_key"]: i["score"] for i in opp["itens"]}
    assert sc["sh4:8541"] > sc["sh4:8544"]
    assert "sh4:8544" in rk["possivel_declinio"]
    cl = sm.store.load_result("clusters")
    assert cl["k"] >= 3 and -1 <= cl["silhueta"] <= 1 and len(cl["itens"]) >= 6
    assert all(c["nome"] for c in cl["clusters"])
    # séries derivadas identificadas como derivadas
    der = sm.store.series(source="gpi")
    assert der and all(d["kind"] == "derivado" for d in der)
    # modo offline: todas as fontes falham, mas os resultados anteriores continuam disponíveis
    hosts = {"olinda.bcb.gov.br", "en.wikipedia.org", "wikimedia.org", "api-comexstat.mdic.gov.br",
             "servicodados.ibge.gov.br", "comtradeapi.un.org"}
    sm.http = FakeHttp(TODAY, fail_hosts=hosts)
    db.execute("UPDATE sync_jobs SET state = 'pending'")
    sm.run("offline")
    from gpi.market import service
    ov = service.overview(sm.store)
    assert ov["n_obs"] > 0 and ov["top"]
    st = sm.store.source_status()
    assert st["comexstat"]["state"] == "falhou" and st["comexstat"]["validated"] == 1   # já validada antes


def test_label_rules():
    assert intel.label({"crescimento_12m": 0.8, "aceleracao": 0.1}, 0.2)[0] == "Tendência emergente"
    assert intel.label({"crescimento_12m": -0.3}, 0.5)[0] == "Possível declínio"
    assert intel.label({"crescimento_12m": 0.05, "tendencia_sig": True, "tendencia_dir": "crescimento"}, 0.6)[0] == "Crescimento estável"
    assert intel.label({"crescimento_12m": 0.0, "volatilidade": 0.05, "sazonalidade": 0.0}, 0.6)[0] == "Mercado maduro"


def test_api_market_endpoints_offline(tmp_path):
    """A API sobe e responde mesmo sem nenhuma fonte acessível (sem dados inventados)."""
    import socket
    import urllib.request
    import uvicorn
    from gpi.app import create_app
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    app = create_app(tmp_path / "d", Path(__file__).resolve().parents[1] / "frontend", cfg={"auto_sync": False},
                     sync_http=FakeHttp(TODAY, fail_hosts={"x"}), today_fn=lambda: TODAY)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    while not srv.started:
        time.sleep(0.05)
    try:
        get = lambda p: json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}{p}").read())
        ov = get("/api/market/overview")
        assert ov["n_obs"] == 0 and ov["top"] == []
        src = get("/api/market/sources")
        assert all(s["estado"] in ("restrita", "nao_testada") for s in src)
        assert not any(s["validada"] for s in src)
        assert get("/api/sync/status")["devida"] is True
    finally:
        srv.should_exit = True
        t.join(5)
        app.state.db.close()
