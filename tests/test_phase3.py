"""Fase 3 — inicializador/empacotamento, Central de Integrações, OAuth PKCE, YouTube, Reddit, RSS,
NLP de opiniões, comparador, ML opcional e ranking ampliado. Dados sintéticos só nos testes."""
import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from fake_sources import FakeHttp
from gpi import main as launcher
from gpi.connectors.base import FormatError
from gpi.connectors.content import ProductMatcher, Reddit, YouTube, parse_feed
from gpi.connectors.http import SourceError
from gpi.db import Database
from gpi.integrations.credentials import CredentialStore
from gpi.integrations.oauth import PendingFlows, authorize_url, challenge_s256, make_verifier
from gpi.market import intel
from gpi.market.analysis import make_analyzer
from gpi.market.content_intel import extract_attributes
from gpi.market.sync import SyncManager
from gpi.nlp import reviews as nlp

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 15)


# ---------------------------------------------------------------- inicializador e empacotamento
def test_manifest_and_integrity(tmp_path):
    d = tmp_path / "GPI"
    (d / "_internal" / "frontend").mkdir(parents=True)
    (d / "GPI.exe").write_bytes(b"MZ fake")
    (d / "_internal" / "frontend" / "app.js").write_text("x")
    m = launcher.build_manifest(d)
    (d / "manifest.json").write_text(json.dumps(m))
    state = tmp_path / "integrity.json"
    assert launcher.verify_integrity(d, state) == (True, [])
    assert state.exists()                                     # verificação rápida nas próximas aberturas
    (d / "_internal" / "frontend" / "app.js").write_text("y")  # mesmo tamanho, conteúdo diferente
    os.utime(d / "_internal" / "frontend" / "app.js", (time.time() + 5, time.time() + 5))
    ok, probs = launcher.verify_integrity(d, state)
    assert not ok and "alterado" in probs[0]
    (d / "_internal" / "frontend" / "app.js").unlink()
    ok, probs = launcher.verify_integrity(d, state)
    assert not ok and "ausente" in probs[0]


def test_data_dir_resolution(monkeypatch, tmp_path):
    monkeypatch.delenv("GPI_DATA_DIR", raising=False)
    monkeypatch.setattr(launcher, "frozen", lambda: True)
    monkeypatch.setattr(launcher, "app_dir", lambda: tmp_path / "Programa")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    assert launcher.data_dir({}) == tmp_path / "AppData" / "Local" / "GPI"        # separado dos executáveis
    (tmp_path / "Programa").mkdir()
    (tmp_path / "Programa" / "portable.flag").write_text("")
    assert launcher.data_dir({}) == tmp_path / "Programa" / "dados"               # modo pen-drive
    monkeypatch.setenv("GPI_DATA_DIR", str(tmp_path / "x"))
    assert launcher.data_dir({}) == tmp_path / "x"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_smoke_startup_subprocess_and_persistence(tmp_path):
    env = {**os.environ, "GPI_DATA_DIR": str(tmp_path / "dados"), "PYTHONPATH": str(ROOT / "backend")}
    port = _free_port()
    for _ in range(2):                                           # 2ª execução reabre o mesmo banco
        r = subprocess.run([sys.executable, "-m", "gpi.main", "--smoke", "--port", str(port)], env=env,
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr[-2000:]
        assert "SMOKE OK" in r.stdout
    assert (tmp_path / "dados" / "gpi.sqlite").exists()
    assert (tmp_path / "dados" / "config.json").exists()        # configuração do usuário na pasta de dados
    assert not (tmp_path / "dados" / "gpi.run.json").exists()   # encerramento limpo


def test_full_start_stop_cycle(tmp_path):
    env = {**os.environ, "GPI_DATA_DIR": str(tmp_path / "d"), "PYTHONPATH": str(ROOT / "backend")}
    cfg = tmp_path / "d"
    cfg.mkdir()
    (cfg / "config.json").write_text(json.dumps({"auto_sync": False}))
    port = _free_port()
    p = subprocess.Popen([sys.executable, "-m", "gpi.main", "--no-browser", "--console", "--port", str(port)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(80):
            if launcher.gpi_running(port):
                break
            time.sleep(0.25)
        assert launcher.gpi_running(port)
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "Global Product Intelligence" in html
        r = subprocess.run([sys.executable, "-m", "gpi.main", "--stop"], env=env, capture_output=True, text=True, timeout=30)
        assert "encerrado" in r.stdout.lower()
        assert p.wait(30) == 0
    finally:
        if p.poll() is None:
            p.kill()


def test_packaging_files_present():
    spec = (ROOT / "packaging" / "gpi.spec").read_text()
    assert "console=False" in spec and "upx=False" in spec and 'name="GPI"' in spec
    wf = (ROOT / ".github" / "workflows" / "windows-build.yml").read_text()
    for step in ("windows-latest", "pytest", "pyinstaller", "smoke_test.ps1", "GPI-Windows-Portable.zip", "upload-artifact"):
        assert step in wf
    assert "secrets." not in wf                                   # sem credenciais no workflow


# ---------------------------------------------------------------- credenciais e OAuth
def test_credential_store_masks_and_restricts(tmp_path):
    c = CredentialStore(tmp_path, force_plain=True)
    c.set("youtube", {"api_key": "AIzaSyABCDEFGHIJKLMNOP"})
    assert c.get("youtube")["api_key"] == "AIzaSyABCDEFGHIJKLMNOP"
    assert "ABCDEFGHIJ" not in json.dumps(c.masked("youtube"))
    if os.name != "nt":
        assert oct(os.stat(tmp_path / "credentials.bin").st_mode & 0o777) == "0o600"
    c.delete("youtube")
    assert c.get("youtube") == {}


def test_pkce_s256_and_flows():
    v = make_verifier()
    assert 43 <= len(v) <= 128
    expect = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert challenge_s256(v) == expect and len(expect) == 43
    f = PendingFlows(ttl=60)
    state, ver = f.start("mercadolivre")
    u = authorize_url("https://auth.mercadolivre.com.br/authorization", "123", "http://127.0.0.1:8765/oauth/callback", state, ver)
    assert "code_challenge_method=S256" in u and f"code_challenge={challenge_s256(ver)}" in u and "state=" + state in u
    assert f.consume(state)["verifier"] == ver
    assert f.consume(state) is None                               # uso único
    f2 = PendingFlows(ttl=-1)
    s2, _ = f2.start("x")
    assert f2.consume(s2) is None                                 # expirado


# ---------------------------------------------------------------- API: segurança e Central de Integrações
class _Srv:
    def __init__(self, tmp_path, http=None, cfg=None):
        import uvicorn
        from gpi.app import create_app
        self.port = _free_port()
        self.app = create_app(tmp_path / "d", ROOT / "frontend", cfg={"auto_sync": False, **(cfg or {})},
                              sync_http=http or FakeHttp(TODAY), today_fn=lambda: TODAY)
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error"))
        self.t = threading.Thread(target=self.server.run, daemon=True)
        self.t.start()
        while not self.server.started:
            time.sleep(0.05)

    def req(self, path, data=None, method=None, headers=None):
        h = {"Content-Type": "application/json", "X-GPI": "1", **(headers or {})}
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method or ("POST" if data is not None else "GET"),
                                   data=None if data is None else json.dumps(data).encode(), headers=h)
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                b = resp.read()
                try:
                    return resp.status, json.loads(b)
                except ValueError:
                    return resp.status, b.decode()
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def stop(self):
        self.server.should_exit = True
        self.t.join(5)
        self.app.state.db.close()


def test_csrf_protection(tmp_path):
    s = _Srv(tmp_path)
    try:
        assert s.req("/api/sync/run", {}, headers={"X-GPI": ""})[0] == 403
        assert s.req("/api/sync/run", {}, headers={"Origin": "https://malicioso.example"})[0] == 403
        assert s.req("/api/integrations/youtube/credentials", {"api_key": "x"}, headers={"X-GPI": "0"})[0] == 403
        assert s.req("/api/health")[0] == 200
    finally:
        s.stop()


def test_integration_center_flow(tmp_path):
    s = _Srv(tmp_path)
    try:
        code, lst = s.req("/api/integrations")
        ids = {p["id"]: p for p in lst}
        assert ids["publicas"]["tipo"] == "auto" and ids["youtube"]["tipo"] == "api_key"
        assert ids["mercadolivre"]["tipo"] == "oauth" and ids["mercadolivre"]["redirect_uri"].endswith("/oauth/callback")
        assert ids["reclame_aqui"]["tipo"] == "approval" and ids["reclame_aqui"]["link"]
        assert not ids["youtube"]["conectado"]
        # chave de API: salvar, testar (chamada simulada no formato real), mascarar
        assert s.req("/api/integrations/youtube/credentials", {"api_key": "AIzaTESTE1234567890", "outro": "x"})[0] == 200
        code, t = s.req("/api/integrations/youtube/test", {})
        assert t["ok"] and "chave válida" in t["mensagem"]
        lst = {p["id"]: p for p in s.req("/api/integrations")[1]}
        assert lst["youtube"]["conectado"] and "TESTE1234" not in json.dumps(lst["youtube"]["credenciais"])
        # Reddit sem confirmação de uso autorizado não conecta
        s.req("/api/integrations/reddit/credentials", {"client_id": "abc"})
        assert not s.req("/api/integrations/reddit/test", {})[1]["ok"]
        s.req("/api/integrations/reddit/credentials", {"uso_autorizado": True})
        assert s.req("/api/integrations/reddit/test", {})[1]["ok"]
        # OAuth: exige App ID; callback com state inválido é recusado
        assert s.req("/api/integrations/mercadolivre/oauth/start", {})[0] == 400
        s.req("/api/integrations/mercadolivre/credentials", {"client_id": "123", "client_secret": "seg"})
        code, o = s.req("/api/integrations/mercadolivre/oauth/start", {})
        assert code == 200 and "code_challenge=" in o["url"]
        code, html = s.req("/oauth/callback?state=forjado&code=x")
        assert "não concluída" in html
        # configurações: feeds inválidos descartados, opt-in do Google Notícias
        s.req("/api/integrations/rss/settings", {"rss_feeds": [{"url": "javascript:alert(1)"}, {"url": "https://a.test/feed", "nome": "A"}]})
        assert s.req("/api/integrations")[1][[p["id"] for p in lst.values()].index("rss")]["feeds"] == [
            {"nome": "A", "url": "https://a.test/feed", "idioma": "pt"}]
        s.req("/api/integrations/google_news/settings", {"google_news_optin": True})
        assert {p["id"]: p for p in s.req("/api/integrations")[1]}["google_news"]["conectado"]
        # desconectar apaga a credencial
        s.req("/api/integrations/youtube", method="DELETE", data=None, headers={})
        assert not {p["id"]: p for p in s.req("/api/integrations")[1]}["youtube"]["conectado"]
    finally:
        s.stop()


# ---------------------------------------------------------------- conectores de conteúdo
def test_rss_and_atom_parsing_and_xml_safety():
    rss = "<rss version='2.0'><channel><item><title>A &amp; B</title><link>https://x.test/1</link>" \
          "<pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Resumo&lt;/p&gt;</description></item></channel></rss>"
    it = parse_feed(rss)[0]
    assert it == {"title": "A & B", "url": "https://x.test/1", "date": "2026-10-05", "summary": "Resumo", "id": "https://x.test/1"}
    atom = "<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>T</title><link href='https://y.test/2'/>" \
           "<updated>2026-10-01T00:00:00Z</updated><summary>S</summary><id>u2</id></entry></feed>"
    assert parse_feed(atom)[0]["url"] == "https://y.test/2"
    with pytest.raises(FormatError):
        parse_feed("<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'aaaa'>]><rss><channel></channel></rss>")


def test_youtube_parse_classify_and_quota(tmp_path):
    rows = YouTube.parse_videos({"items": [{"id": "abc", "snippet": {"title": "Air fryer: unboxing e review", "channelTitle": "C",
                                                                        "publishedAt": "2026-09-01T00:00:00Z"},
                                            "statistics": {"viewCount": "10", "likeCount": "2"}}]}, "wiki:air-fryer")
    assert rows[0]["url"] == "https://www.youtube.com/watch?v=abc" and rows[0]["metrics"]["viewCount"] == 10
    assert set(rows[0]["metrics"]["tipos"]) >= {"unboxing", "review"} and "commentCount" not in rows[0]["metrics"]
    db = Database(tmp_path / "y.sqlite")
    sm = SyncManager(db, tmp_path, {"history_start_year": 2025, "youtube_daily_units": 150}, http=FakeHttp(TODAY),
                     today_fn=lambda: TODAY)
    sm.creds.set("youtube", {"api_key": "k"})
    sm.run("t1", only=["wikimedia"])                    # produtos primeiro (palavras-chave)
    res = sm.run("t2", only=["youtube"])["fontes"]["youtube"]
    assert res["jobs_ok"] == 2 and sm.content.quota_used("youtube", TODAY.isoformat()) == 101   # busca 100 + vídeos 1
    db.execute("UPDATE sync_jobs SET state = 'pending'")
    res = sm.run("t3", only=["youtube"])["fontes"]["youtube"]
    assert "limite diário" in res.get("cota", "") and sm.content.quota_used("youtube", TODAY.isoformat()) <= 150
    assert sm.store.source_status()["youtube"]["state"] == "funcional"
    # retenção: vídeos não atualizados há mais de 30 dias são apagados
    old = (datetime.now().astimezone() - timedelta(days=31)).isoformat()
    db.execute("UPDATE content_items SET refreshed_at = ? WHERE source = 'youtube'", (old,))
    assert sm.content.purge("youtube", 30) > 0 and sm.content.count("youtube")["n"] == 0


def test_reddit_requires_authorized_use_and_skips_deleted():
    class Ctx:
        class creds:
            @staticmethod
            def get(_):
                return {"client_id": "x"}
    assert not Reddit().available(Ctx)
    lst = Reddit.parse_listing({"data": {"children": [
        {"kind": "t3", "data": {"name": "t3_1", "title": "ok", "selftext": "great", "permalink": "/r/a/1", "created_utc": 1, "subreddit": "a"}},
        {"kind": "t3", "data": {"name": "t3_2", "title": "x", "author": "[deleted]", "permalink": "/r/a/2", "created_utc": 1}}]}})
    assert [r["item_id"] for r in lst] == ["t3_1"]


def test_product_matcher():
    m = ProductMatcher([{"product_key": "wiki:air-fryer", "name_pt": "Fritadeira elétrica", "name_en": "Air fryer", "name_zh": "空气炸锅"},
                        {"product_key": "wiki:power-bank", "name_pt": None, "name_en": "Power bank", "name_zh": None}])
    assert m.match("Review: Air Fryers baratas") == "wiki:air-fryer"
    assert m.match("Melhor fritadeira elétrica do ano") == "wiki:air-fryer"
    assert m.match("新款空气炸锅评测") == "wiki:air-fryer"
    assert m.match("bateria portátil") is None


# ---------------------------------------------------------------- NLP de opiniões
LABELED = [
    ("Produto excelente, recomendo muito!", "positivo"), ("Não recomendo, quebrou em duas semanas", "negativo"),
    ("A bateria descarrega muito rápido, péssima", "negativo"), ("Chegou rápido mas o produto esquenta demais", "negativo"),
    ("Não é ruim, funciona bem", "positivo"), ("Entrega atrasou 20 dias, vendedor não responde", "negativo"),
    ("Comprei ontem", "neutro"), ("Great value for money, works perfectly", "positivo"),
    ("Stopped working after a month, total junk", "negativo"), ("Não gostei do acabamento", "negativo"),
    ("Custo-benefício excelente", "positivo"), ("It overheats and the battery died", "negativo"),
    ("Montagem fácil e manual claro", "positivo"), ("Deu choque na tomada, perigoso", "negativo"),
    ("O produto é bom, porém o atendimento foi péssimo", "negativo"), ("Muito bom", "positivo"),
    ("Superou minhas expectativas", "positivo"), ("Veio com defeito", "negativo"), ("Chegou hoje pelos Correios", "neutro"),
    ("Silencioso e potente, adorei", "positivo"), ("Barulhento demais", "negativo"), ("Not bad at all", "positivo"),
    ("I love it, best purchase this year", "positivo"), ("Terrible customer service, no refund", "negativo"),
    ("O modelo tem 5 litros", "neutro"), ("Nunca mais compro, lixo", "negativo"), ("Funciona, mas é fraco", "negativo"),
    ("Durável e resistente", "positivo"), ("The charger is flimsy and broke", "negativo"), ("Recomendo a todos", "positivo"),
]


def test_sentiment_accuracy_on_labeled_set():
    hits = sum(nlp.analyze(t)["label"] == l for t, l in LABELED)
    assert hits / len(LABELED) >= 0.85, hits


def test_aspects_and_complaint_target():
    a = nlp.analyze("A bateria inchou e o produto esquenta muito")
    assert {"bateria", "aquecimento"} <= set(a["aspects"]) and a["target"] == "produto"
    assert nlp.analyze("Entrega atrasou e a embalagem chegou amassada")["target"] == "entrega"
    assert nlp.analyze("Atendimento péssimo, sem reembolso")["target"] == "atendimento"
    assert "defeito_eletrico" in nlp.analyze("deu choque e queimou o disjuntor")["aspects"]


def test_attribute_extraction():
    a = extract_attributes([{"texto": "Air fryer 4 litros, 1500W, bivolt, 12 meses de garantia, aço inox, 30 x 25 x 20 cm",
                             "fonte": "rss", "url": "u"}])
    assert a["capacidade"][0]["valor"] == "4 litros" and a["potencia"][0]["valor"] == "1500 w"
    assert a["voltagem"][0]["valor"] == "bivolt" and a["garantia"][0]["valor"] == "12 meses"
    assert a["material"][0]["valor"] in ("aço inox", "aco inox") and a["dimensoes"][0]["valor"].startswith("30 x 25 x 20")
    assert extract_attributes([{"texto": "sem números aqui", "fonte": "rss", "url": "u"}]) == {}


# ---------------------------------------------------------------- pipeline completo da Fase 3
@pytest.fixture(scope="module")
def full(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("f3")
    db = Database(tmp / "f.sqlite")
    cfg = {"history_start_year": 2022, "automl_budget_s": 8, "automl_ml_series": 0, "google_news_optin": True,
           "youtube_daily_units": 3000, "rss_feeds": [{"nome": "Teste", "url": "https://tecnoblog.net/feed/", "idioma": "pt"}]}
    sm = SyncManager(db, tmp, cfg, http=FakeHttp(TODAY), analyzer=make_analyzer(cfg), today_fn=lambda: TODAY)
    sm.creds.set("youtube", {"api_key": "k"})
    sm.creds.set("reddit", {"client_id": "c", "uso_autorizado": True})
    sm.run("abertura")
    sm.run("segunda")            # conteúdo coletado após os produtos existirem
    db.execute("UPDATE sync_jobs SET state = 'pending'")
    s = sm.run("terceira")
    return sm, s


def test_full_pipeline_content_sources(full):
    sm, s = full
    st = sm.store.source_status()
    for src in ("rss", "google_news", "youtube", "reddit"):
        assert st[src]["state"] == "funcional" and st[src]["records"] > 0, src
    for src in ("trustpilot", "reclame_aqui", "comparadores", "amazon_br"):
        assert st[src]["state"] == "restrita"
    assert "erro" not in s["analise"]["conteudo"] and s["analise"]["conteudo"]["analisados_nlp"] >= 0


def test_youtube_data_not_mixed_or_nlp_processed(full):
    sm, _ = full
    yt = sm.content.items("youtube")
    assert yt and all(v["sentiment"] is None for v in yt)
    summ = sm.store.load_result("youtube")
    assert summ["total_videos"] == len(yt) and "sem combinação" in summ["aviso"]
    for it in sm.store.load_result("opportunities")["itens"]:
        assert not any("youtube" in str(c) for c in it["componentes"])
        assert "youtube" not in it["fontes"]


def test_review_summary_and_rankings(full):
    sm, _ = full
    rv = sm.store.load_result("reviews")
    assert rv["total_opinioes"] > 0 and "não representam taxa de defeito" in rv["aviso"]
    p = next(p for p in rv["produtos"] if p["n"] >= 5)
    assert p["positivos"] + p["negativos"] + p["neutros"] == p["n"]
    assert all(e["url"] for e in p["exemplos_negativos"] + p["exemplos_positivos"])
    opp = sm.store.load_result("opportunities")
    assert abs(sum(opp["pesos"].values()) - 1) < 1e-9 and "diversidade_fontes" not in opp["pesos"]
    for it in opp["itens"]:
        assert 0 <= it["cobertura"] <= 1 and 0 <= it["confianca"] <= 1
        avail = {k for k, v in it["componentes"].items() if v is not None}
        assert abs(it["cobertura"] - sum(opp["pesos"][k] for k in avail)) < 1e-3
        if it["score"] is not None:   # score usa só componentes disponíveis (ausência não penaliza)
            sc = 100 * sum(opp["pesos"][k] * it["componentes"][k] for k in avail) / it["cobertura"]
            assert abs(sc - it["score"]) < 0.2
    for k in ("produtos_emergentes", "mais_pesquisados", "em_crescimento", "avaliacoes_favoraveis",
              "problemas_recorrentes", "promissores_importacao", "alto_risco"):
        assert k in opp["rankings"]
    ment = [s for s in sm.store.series(source="gpi") if s["series_key"].startswith("gpi:mentions:")]
    assert ment and all(s["kind"] == "derivado" for s in ment)


def test_comparator(full):
    from gpi.market import service
    sm, _ = full
    keys = [i["product_key"] for i in sm.store.load_result("opportunities")["itens"] if i["product_key"].startswith("wiki:")][:2]
    c = service.compare(sm.store, keys)
    rows = {r["atributo"]: r["valores"] for r in c["linhas"]}
    assert len(c["produtos"]) == 2
    assert rows["Marca"][0]["valor"].startswith("não disponível")
    assert rows["Possíveis fornecedores"][0]["valor"].startswith("sem fonte autorizada")
    for vals in rows.values():
        for v in vals:
            assert v is not None and "valor" in v and "confiabilidade" in v


# ---------------------------------------------------------------- ML opcional
def test_optional_models_registered_only_if_installed():
    from gpi.forecasting.models import EXTRA_AVAILABLE, MODELS
    for name, key in (("statsmodels", "sarima"), ("lightgbm", "lightgbm"), ("xgboost", "xgboost")):
        try:
            __import__(name)
            assert key in MODELS and EXTRA_AVAILABLE[key]
        except ImportError:
            assert key not in MODELS and not EXTRA_AVAILABLE[key]


@pytest.mark.parametrize("key,lib", [("sarima", "statsmodels"), ("lightgbm", "lightgbm"), ("xgboost", "xgboost")])
def test_optional_model_forecasts(key, lib):
    pytest.importorskip(lib)
    import numpy as np
    from gpi.forecasting.models import run_model
    t = np.arange(72)
    y = 100 + 2 * t + 15 * np.sin(2 * np.pi * t / 12) + np.random.default_rng(0).normal(0, 2, 72)
    r = run_model(key, y, 12, 12)
    true = 100 + 2 * np.arange(72, 84) + 15 * np.sin(2 * np.pi * np.arange(72, 84) / 12)
    assert np.mean(np.abs(r.forecast - true)) / np.mean(true) < 0.1
    assert np.all(r.var_h > 0)


def test_forecast_types_are_separated():
    from gpi.market.automl import forecast_type
    assert forecast_type({"source": "comexstat"}) == "importacao"
    assert forecast_type({"source": "wikimedia"}) == "interesse"
    assert forecast_type({"source": "gpi", "indicator": "Menções em notícias e discussões"}) == "popularidade"
    assert forecast_type({"source": "bcb_ptax"}) == "indicador"


# ---------------------------------------------------------------- correções do build Windows
def test_selftest_runs_builtin_models(tmp_path):
    """--selftest executa cada modelo do pacote; os embutidos precisam funcionar sempre.
    SARIMA/LightGBM/XGBoost só são exigidos onde as bibliotecas existem (build do Windows)."""
    code = launcher.selftest(tmp_path)
    out = json.loads((tmp_path / "selftest.json").read_text(encoding="utf-8"))
    for k in ("naive", "seasonal_naive", "holt_winters", "ets_auto", "croston_sba", "random_forest", "hist_gb"):
        assert out["modelos"][k]["ok"], (k, out["modelos"][k])
    from gpi.forecasting.extra_models import available
    missing_libs = [k for k, ok in available().items() if not ok]
    assert sorted(out["exigidos_com_falha"]) == sorted(missing_libs)
    assert code == (0 if not missing_libs else 6)


def test_source_without_records_is_not_validated(tmp_path):
    """Uma API que responde sem gravar nenhum registro não é declarada validada."""
    from gpi.market.store import MarketStore
    st = MarketStore(Database(tmp_path / "x.sqlite"))
    st.set_source_status("fonte_x", "funcional", "0 novas observações", success=True, validated=True)
    s = st.source_status()["fonte_x"]
    assert s["state"] == "sem dados" and not s["validated"]


def test_stop_right_after_start_exits_promptly(tmp_path):
    """--stop enviado logo que o servidor responde: o processo deve sair (antes havia espera de 30 s)."""
    env = {**os.environ, "GPI_DATA_DIR": str(tmp_path / "d"), "PYTHONPATH": str(ROOT / "backend")}
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "config.json").write_text(json.dumps({"auto_sync": False}))
    port = _free_port()
    p = subprocess.Popen([sys.executable, "-m", "gpi.main", "--no-browser", "--console", "--port", str(port)], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(200):
            if launcher.gpi_running(port):
                break
            time.sleep(0.05)
        subprocess.run([sys.executable, "-m", "gpi.main", "--stop"], env=env, capture_output=True, timeout=30)
        assert p.wait(15) == 0
    finally:
        if p.poll() is None:
            p.kill()


def test_unexpected_model_error_does_not_break_forecast(tmp_path, monkeypatch):
    """Erro inesperado em um modelo vira 'não aplicável' — a previsão dos demais continua."""
    from gpi.forecasting import models as fm
    from gpi import services as sv
    monkeypatch.setitem(fm.MODELS, "quebra", ("Modelo com erro", lambda y, h, **kw: 1 / 0))
    db = Database(tmp_path / "f.sqlite")
    from gpi.demo import DEMO_SOURCE, make_demo_csv
    from gpi.importer import import_file
    import_file(db, "demo.csv", make_demo_csv(), source=DEMO_SOURCE, is_demo=True)
    sku = sv.skus(db)[0]["sku"]
    res = sv.forecast(db, sku, "M", 6, ["naive", "quebra", "seasonal_naive"])
    assert "falha interna" in res["modelos"]["quebra"]["erro"]
    assert res["modelo_escolhido"] in ("naive", "seasonal_naive")
