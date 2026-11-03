"""v0.6.1 — Google Ads sem developer token, YouTube (visualização e diagnóstico A–E), painel de sincronização,
cliente HTTP (keep-alive, tempos, Retry-After, segredos), Meta em módulos, estados das integrações e diagnóstico
exportável. Respostas no formato documentado (SIMULADAS): testam a lógica; nenhuma API é declarada validada aqui."""
import json
import socket
import threading
import time
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from test_api_integration import Srv
from test_v05 import Creds

from gpi.connectors.base import Connector, Job
from gpi.connectors.content import YouTube, youtube_queries
from gpi.connectors.http import HttpClient, HttpConfig, SourceError, redact, retry_after_seconds
from gpi.db import Database
from gpi.integrations import google_ads as GA
from gpi.integrations import meta as META
from gpi.market.content_store import ContentStore
from gpi.market.store import MarketStore
from gpi.market.sync import SyncContext, SyncManager
from gpi.market import youtube_view as YV
from gpi.products.catalog import Catalog
from gpi.sync_api import integration_state

ROOT = Path(__file__).resolve().parents[1]


# ===================================================================== cliente HTTP
class KA(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"               # keep-alive
    conns = set()

    def log_message(self, *a):
        pass

    def do_GET(self):
        KA.conns.add(self.client_address[1])
        path = self.path.split("?")[0]
        if path == "/429":
            body = b'{"erro": "limite"}'
            self.send_response(429)
            self.send_header("Retry-After", "0")
        elif path == "/429sem":
            body = b'{"erro": "limite"}'
            self.send_response(429)
        elif path == "/401":
            body = b'{"error": {"code": 401, "status": "UNAUTHENTICATED", "message": "token ruim"}}'
            self.send_response(401)
        else:
            body = b'{"ok": true}'
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def ka():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), KA)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _client(tmp_path, **kw):
    return HttpClient(tmp_path, HttpConfig(min_interval=0, max_attempts=3, backoff_base=0.01, **kw), sleep=lambda s: None)


def test_keep_alive_reuses_connection_and_measures_times(tmp_path, ka):
    KA.conns.clear()
    c = _client(tmp_path)
    for _ in range(5):
        assert c.request_json(ka + "/ok", ttl=0) == {"ok": True}
    hs = c.host_stats[ka.split("/")[2]]
    assert hs["conexoes_novas"] == 1 and hs["conexoes_reaproveitadas"] == 4 and len(KA.conns) == 1
    assert hs["primeira_resposta_s"] > 0 and "dns_s" in hs and "conexao_s" in hs


def test_permanent_errors_not_retried_and_keep_body_without_secrets(tmp_path, ka):
    c = _client(tmp_path)
    with pytest.raises(SourceError) as e:
        c.request_json(ka + "/401?key=SEGREDO123&x=1", ttl=0)
    assert e.value.kind == "restrita" and "UNAUTHENTICATED" in e.value.body and c.stats["retries"] == 0
    assert "SEGREDO123" not in str(e.value)


def test_retry_after_429_and_events(tmp_path, ka):
    events = []
    c = _client(tmp_path)
    c.on_event = events.append
    c.ctx_local.cur = {"fonte": "x"}
    with pytest.raises(SourceError) as e:
        c.request_json(ka + "/429?access_token=ABCDEF123456", ttl=0)
    assert e.value.kind == "limite" and c.stats["retries"] == 2
    assert c.source_stats["x"]["retentativas"] == 2 and any(ev.get("espera") is not None for ev in events)
    assert "ABCDEF123456" not in json.dumps(events)


def test_429_without_retry_after_backs_off_longer(tmp_path, ka):
    sleeps = []
    c = HttpClient(tmp_path, HttpConfig(min_interval=0, max_attempts=3, backoff_base=0.01), sleep=sleeps.append)
    with pytest.raises(SourceError):
        c.request_json(ka + "/429sem", ttl=0)
    assert len(sleeps) == 2 and 15 <= sleeps[0] <= 19 and 30 <= sleeps[1] <= 38     # 15 s, 30 s (+ jitter), não 2 s/4 s


def test_per_host_connect_timeout_override():
    cfg = HttpConfig()
    assert cfg.connect_timeout == 8 and cfg.connect_timeouts["api.gdeltproject.org"] == 25
    assert cfg.timeout == 30 and cfg.total_timeout == 150


def test_dependency_without_jobs_is_shown_as_ignored(tmp_path):
    class Dep(Fast):
        def plan(self, ctx):
            return []                                      # ex.: UN Comtrade sem posições SH descobertas
    sm, _ = _sm(tmp_path, [Dep("comtrade")])
    sm.run("teste")
    f = sm.snapshot()["fontes"]["comtrade"]
    assert f["estado"] == "ignorado" and "dependência" in f["motivo"]


def test_retry_after_formats_and_redaction():
    assert retry_after_seconds("120") == 120
    future = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(time.time() + 30))
    assert 20 <= retry_after_seconds(future) <= 31
    assert retry_after_seconds("lixo") is None
    s = redact("https://x/y?key=AIzaSyABC123&client_secret=abc123456&q=ok Bearer ya29.abcdefghijk refresh_token: 1//0abcdefghi")
    for secret in ("AIzaSyABC123", "abc123456", "ya29.abcdefghijk", "1//0abcdefghi"):
        assert secret not in s
    assert "q=ok" in s


def test_connect_timeout_separate_from_read_timeout(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(0)                                       # aceita conexão mas nunca responde → tempo de LEITURA
    port = sock.getsockname()[1]
    c = _client(tmp_path, connect_timeout=2, timeout=0.3)
    c.cfg.max_attempts = 1
    t = time.monotonic()
    with pytest.raises(SourceError) as e:
        c.request_json(f"http://127.0.0.1:{port}/x", ttl=0)
    assert "leitura" in str(e.value) and time.monotonic() - t < 2
    sock.close()


# ===================================================================== Google Ads
ADS_IDEAS = {"results": [{"text": "air fryer", "keywordIdeaMetrics": {"avgMonthlySearches": "450000", "competition": "HIGH",
             "monthlySearchVolumes": [{"year": "2026", "month": "SEPTEMBER", "monthlySearches": "450000"}]}}]}


class GHttp:
    """Simula a API REST do Google Ads (formato documentado)."""
    def __init__(self, accounts=("1234567890",), planner_error=None, account_error=None, manager=False):
        self.calls, self.accounts, self.planner_error, self.account_error, self.manager = [], list(accounts), planner_error, account_error, manager
        self.cancel_event = threading.Event()

    def request_json(self, url, method="GET", body=None, headers=None, ttl=None, form=None, **kw):
        self.calls.append({"url": url, "headers": headers or {}, "body": body, "form": form})
        if "oauth2.googleapis.com/token" in url:
            return {"access_token": "tok", "expires_in": 3600}
        assert "developer-token" not in (headers or {})
        if url.endswith("customers:listAccessibleCustomers"):
            return {"resourceNames": [f"customers/{a}" for a in self.accounts]}
        if url.endswith("googleAds:search"):
            if self.account_error:
                raise self.account_error
            if "customer_client" in body["query"]:
                return {"results": [{"customerClient": {"id": "5550001111", "descriptiveName": "Loja", "manager": False, "level": 1}}]}
            cid = url.split("/customers/")[1].split("/")[0]
            return {"results": [{"customer": {"id": cid, "descriptiveName": f"Conta {cid}", "manager": self.manager and cid == self.accounts[0],
                                              "testAccount": False, "currencyCode": "BRL"}}]}
        if url.endswith(":generateKeywordIdeas"):
            if self.planner_error:
                raise self.planner_error
            return ADS_IDEAS
        raise SourceError("não encontrado", "http", status=404)


def _err(status, code_type, code):
    body = json.dumps({"error": {"code": status, "status": "PERMISSION_DENIED", "details": [
        {"@type": "type.googleapis.com/google.ads.googleads.v26.errors.GoogleAdsFailure",
         "errors": [{"errorCode": {code_type: code}, "message": "sem permissão"}]}]}})
    return SourceError(f"HTTP {status}", "restrita", status=status, body=body)


def test_google_ads_no_developer_token_and_single_account_auto_selected():
    creds = Creds({"google_ads": {"client_id": "cid", "client_secret": "s", "refresh_token": "r", "developer_token": "ANTIGO"}})
    http = GHttp()
    d = GA.diagnose(http, creds)
    assert d["estado"] == "validado" and creds.get("google_ads")["customer_id"] == "1234567890"
    assert all("developer-token" not in c["headers"] for c in http.calls)                 # nunca enviado
    assert all("login-customer-id" not in c["headers"] for c in http.calls)               # sem MCC: não usado
    plan = d["etapas"][-1]
    r = plan["resultados"][0]
    assert r["palavra_chave"] == "air fryer" and r["media_mensal_aprox"] == 450000 and r["pais"] == "BR" and r["idioma"] == "pt"
    assert d["etapas"][0]["developer_token"].startswith("descontinuado")
    assert http.calls[-1]["body"]["keywordSeed"]["keywords"] == ["carregador usb-c", "fechadura inteligente", "air fryer"]


def test_google_ads_manager_hierarchy_uses_login_customer_only_when_needed():
    creds = Creds({"google_ads": {"client_id": "cid", "refresh_token": "r"}})
    http = GHttp(accounts=("9990001111",), manager=True)
    d = GA.discover(http, creds)
    ids = {c["customer_id"]: c for c in d["contas"]}
    assert ids["9990001111"]["gerente"] and ids["5550001111"]["via_gerente"] == "9990001111"
    GA.select(creds, "5550001111")
    assert creds.get("google_ads")["login_customer_id"] == "9990001111"
    GA.call(http, creds, ":generateKeywordIdeas", {"keywordSeed": {"keywords": ["x"]}})
    assert http.calls[-1]["headers"]["login-customer-id"] == "9990001111"
    list_call = next(c for c in http.calls if c["url"].endswith("listAccessibleCustomers"))
    assert "login-customer-id" not in list_call["headers"]


@pytest.mark.parametrize("err,etapa,esperado", [
    (_err(403, "authorizationError", "ACTION_NOT_PERMITTED"), "planejamento", "basic"),
    (_err(403, "authorizationError", "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"), "conta", "producao"),
    (_err(403, "authorizationError", "ACTION_NOT_PERMITTED"), "conta", "producao"),
    (_err(401, "authenticationError", "NOT_ADS_USER"), "contas", "sem_conta"),
    (_err(400, "requestError", "INVALID_INPUT"), "planejamento", "planejamento"),
])
def test_google_ads_error_classification(err, etapa, esperado):
    assert GA.classify(err, etapa)[0] == esperado


def test_google_ads_diagnose_distinguishes_oauth_from_planner_permission():
    creds = Creds({"google_ads": {"client_id": "cid", "refresh_token": "r"}})
    d = GA.diagnose(GHttp(planner_error=_err(403, "authorizationError", "ACTION_NOT_PERMITTED")), creds)
    assert d["estado"] == "basic" and d["etapas"][1]["ok"] and d["etapas"][3]["ok"]       # OAuth e conta ok
    assert d["etapas"][-1]["mensagem"] == GA.MSG["basic"] and "Basic" in d["etapas"][-1]["acao"]
    assert "Explorer" in d["nivel_acesso"]
    d2 = GA.diagnose(GHttp(accounts=()), Creds({"google_ads": {"client_id": "cid", "refresh_token": "r"}}))
    assert d2["estado"] == "sem_conta" and d2["etapas"][-1]["mensagem"] == "Conta Google Ads não encontrada."
    d3 = GA.diagnose(GHttp(account_error=_err(403, "authorizationError", "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION")),
                     Creds({"google_ads": {"client_id": "cid", "refresh_token": "r", "customer_id": "1234567890"}}))
    assert d3["estado"] == "producao"
    d4 = GA.diagnose(GHttp(), Creds({"google_ads": {"client_id": "cid"}}))
    assert d4["estado"] == "nao_autenticado"


def test_google_ads_token_renewal_and_connector_availability(tmp_path):
    creds = Creds({"google_ads": {"client_id": "cid", "refresh_token": "r", "access_token": "velho", "expires_at": "1"}})
    http = GHttp()
    assert GA.token(http, creds) == "tok" and float(creds.get("google_ads")["expires_at"]) > time.time()
    from gpi.connectors.search import GoogleAdsKeywordPlanner
    db = Database(tmp_path / "g.sqlite")
    k = GoogleAdsKeywordPlanner()
    ctx = SyncContext(http, MarketStore(db), {}, date.today(), creds=Creds({"google_ads": {"refresh_token": "r"}}))
    assert not k.available(ctx) and "conta" in k.restricted_reason                        # falta só selecionar a conta
    ctx.creds.set("google_ads", {"customer_id": "1"})
    assert k.available(ctx)                                                                 # sem developer token


def test_google_ads_provider_fields_without_developer_token():
    from gpi.integrations.registry import provider
    p = provider("google_ads")
    assert [f["nome"] for f in p["campos"]] == ["client_id", "client_secret"] and p["revoke_url"].endswith("/revoke")
    assert "09/09/2026" in p["permissoes"]


# ===================================================================== YouTube
def _yt_ctx(tmp_path, http, cfg=None):
    db = Database(tmp_path / "y.sqlite")
    Catalog(db).ensure_seeded()
    st = MarketStore(db)
    ctx = SyncContext(http, st, cfg or {}, date.today(), ContentStore(db), creds=Creds({"youtube": {"api_key": "K"}}))
    return ctx, db


class YHttp:
    def __init__(self):
        self.calls, self.stats = [], {"cache_hits": 0}
        self.cancel_event = threading.Event()

    def request_json(self, url, method="GET", body=None, headers=None, ttl=None, **kw):
        self.calls.append(url)
        if "i18nRegions" in url:
            return {"items": [{"id": "BR"}]}
        if "/search?" in url:
            return {"items": [{"id": {"videoId": "vid1"}}]}
        if "/videos?" in url:
            return {"items": [{"id": "vid1", "snippet": {"title": "Review carregador USB-C 65W", "channelTitle": "Canal X",
                                                           "publishedAt": "2026-10-20T10:00:00Z"},
                               "statistics": {"viewCount": "1500", "likeCount": "40", "commentCount": "3"}}]}
        raise SourceError("x", "http", status=404)


def test_youtube_diagnose_a_to_e_and_page_visibility(tmp_path):
    http = YHttp()
    ctx, db = _yt_ctx(tmp_path, http)
    d = YV.diagnose(http, ctx.creds, {}, db, ctx.content)
    assert [s["etapa"][0] for s in d["etapas"]] == ["A", "B", "C", "D", "E"] and all(s["ok"] for s in d["etapas"])
    assert d["estado"] == "funcional" and d["unidades"] == 102
    v = YV.videos(db)
    assert v["total"] == 1 and v["videos"][0]["canal"] == "Canal X" and v["videos"][0]["visualizacoes"] == 1500
    assert v["videos"][0]["produto_id"].startswith("charger") and v["videos"][0]["pais_consulta"] == "BR"
    assert ContentStore(db).quota_used("youtube", date.today().isoformat()) == 102
    st = YV.status(db, {})
    assert st["videos_armazenados"] == 1 and "VÍDEO único" in st["o_que_conta"] and st["restante_no_limite_gpi"] == 3000 - 102
    assert "não é informada pela API" in st["cota_aviso"]


def test_youtube_diagnose_reports_rejected_key(tmp_path):
    class Bad(YHttp):
        def request_json(self, url, **kw):
            raise SourceError("acesso negado (HTTP 400): API key not valid", "http", status=400)
    ctx, db = _yt_ctx(tmp_path, Bad())
    d = YV.diagnose(ctx.http, ctx.creds, {}, db, ctx.content)
    assert d["estado"] == "erro" and not d["etapas"][0]["ok"] and len(d["etapas"]) == 1        # não gasta pesquisa


def test_youtube_filters_and_counts_videos_not_observations(tmp_path):
    ctx, db = _yt_ctx(tmp_path, YHttp())
    rows = [{"item_id": f"v{i}", "kind": "video", "title": f"Air fryer review {i}" if i % 2 else f"Câmera teste {i}",
             "url": f"https://www.youtube.com/watch?v=v{i}", "author": "Canal A" if i < 3 else "Canal B",
             "published_at": (date.today() - timedelta(days=10 * i)).isoformat(), "product_key": "air_fryer" if i % 2 else "camera",
             "query": "air fryer" if i % 2 else "câmera", "metrics": {"viewCount": 100 * i, "likeCount": i}} for i in range(6)]
    ctx.content.upsert("youtube", rows)
    ctx.content.upsert("youtube", rows)                                                    # nova coleta: atualiza, não duplica
    assert YV.status(db, {})["videos_armazenados"] == 6
    assert YV.videos(db, produto="air_fryer")["total"] == 3
    assert YV.videos(db, q="câmera")["total"] == 3
    assert YV.videos(db, canal="canal a")["total"] == 3
    assert YV.videos(db, dias=25)["total"] == 3
    assert {v["categoria"] for v in YV.videos(db, categoria="Casa inteligente e segurança")["videos"]} == {"Casa inteligente e segurança"}


def test_youtube_manual_refresh_is_capped_and_queries_use_catalog(tmp_path):
    ctx, db = _yt_ctx(tmp_path, YHttp(), {"youtube_daily_units": 3000, "youtube_manual_max_searches": 5})
    q = youtube_queries(ctx, 20)
    assert q and all(isinstance(k, str) for k, _ in q) and any(k == "air_fryer" or not k.startswith("wiki:") for k, _ in q)
    normal = YouTube().plan(ctx)
    ctx.force = True
    manual = YouTube().plan(ctx)
    searches = [j for j in manual if ":manual:" in j.key]
    assert len(searches) == 5 and len([j for j in normal if ":search:" in j.key]) == 20
    ctx2, _ = _yt_ctx(tmp_path / "b", YHttp(), {"youtube_daily_units": 200})
    ctx2.force = True
    assert len([j for j in YouTube().plan(ctx2) if ":manual:" in j.key]) == 1             # limite diário baixo: 1 busca


def test_youtube_quota_limit_blocks_extra_searches(tmp_path):
    ctx, db = _yt_ctx(tmp_path, YHttp(), {"youtube_daily_units": 150})
    y = YouTube()
    ctx.content.quota_add("youtube", ctx.today.isoformat(), 120)
    with pytest.raises(SourceError) as e:
        y.run(Job("youtube:search:air_fryer:x", {"product_key": "air_fryer", "q": "air fryer"}), ctx)
    assert e.value.kind == "limite" and "diário" in str(e.value)


# ===================================================================== sincronização
class Fast(Connector):
    def __init__(self, cid, ok=True, avail=True, err=None, stage=1, delay=0.05):
        self.id, self.name, self.order, self.stage = cid, cid.upper(), 50, stage
        self.ok, self.avail, self.err, self.delay = ok, avail, err, delay
        self.restricted_reason = None if avail else "precisa de chave"

    def available(self, ctx):
        return self.avail

    def plan(self, ctx):
        return [Job(f"{self.id}:{i}", {}, refresh_days=None) for i in range(2)]

    def run(self, job, ctx):
        time.sleep(self.delay)
        if self.err:
            raise SourceError(self.err, "limite" if "429" in self.err else "http")
        return [], []


def _sm(tmp_path, conns, **cfg):
    db = Database(tmp_path / "s.sqlite")
    sm = SyncManager(db, tmp_path, {"sync_workers": 3, **cfg}, connectors=conns, http=HttpClient(tmp_path / "c", HttpConfig()),
                     creds=Creds({}))
    return sm, db


def test_sync_panel_states_real_progress_and_partial_result(tmp_path):
    conns = [Fast("comexstat"), Fast("google_ads_kp", avail=False), Fast("gdelt", err="HTTP 429: limite"), Fast("youtube")]
    sm, db = _sm(tmp_path, conns)
    seen = []
    t = threading.Thread(target=sm.run, args=("teste",))
    t.start()
    while t.is_alive():
        s = sm.snapshot()
        if s["percentual"] is not None:
            seen.append(s["percentual"])
        time.sleep(0.01)
    s = sm.snapshot()
    f = s["fontes"]
    assert f["google_ads_kp"]["estado"] == "requer_autorizacao" and f["google_ads_kp"].get("inicio") is None   # resolvida no início
    assert f["gdelt"]["estado"] == "limite" and "429" in f["gdelt"]["motivo"]
    assert f["comexstat"]["estado"] == "concluido" and f["comexstat"]["jobs_total"] == 2 and f["comexstat"]["segundos"] > 0
    assert s["titulo"] == "Sincronização concluída com restrições" and s["fase"] == "parcial" and s["percentual"] == 100
    assert seen == sorted(seen) and max(seen[:-1] or [0]) < 100                                # monótono, sem 100 antes do fim
    assert all(v["simbolo"] for v in f.values())                                               # estado não depende só de cor
    assert "fontes concluídas" in s["resumo"] and "com falha" in s["resumo"]
    h = sm.history()
    assert h[0]["rotulo"] == "Concluída com restrições" and h[0]["fontes"]["gdelt"]["estado"] == "limite"


def test_sync_priority_order_and_failed_source_does_not_block(tmp_path):
    order = []

    class Rec(Fast):
        def run(self, job, ctx):
            order.append(self.id)
            return super().run(job, ctx)
    conns = [Rec("comexstat"), Rec("youtube"), Rec("ebay", err="HTTP 500: falhou"), Rec("google_trends_rss"), Rec("ml_trends")]
    sm, _ = _sm(tmp_path, conns, sync_workers=1)
    sm.run("teste")
    firsts = list(dict.fromkeys(order))
    assert firsts == ["ml_trends", "google_trends_rss", "ebay", "youtube", "comexstat"]          # prioridade comercial
    assert sm.snapshot()["fontes"]["comexstat"]["estado"] == "concluido"                      # falha anterior não bloqueou


def test_sync_cancel_marks_sources_and_retry_failed(tmp_path):
    conns = [Fast("a1", delay=0.3), Fast("a2", delay=0.3), Fast("bad", err="HTTP 500: x", delay=0.01)]
    sm, db = _sm(tmp_path, conns, sync_workers=1)
    t = threading.Thread(target=sm.run, args=("teste",))
    t.start()
    time.sleep(0.2)
    sm.cancel()
    t.join(10)
    s = sm.snapshot()
    assert s["titulo"] == "Sincronização cancelada" and any(v["estado"] == "cancelado" for v in s["fontes"].values())
    sm.http.cancel_event.clear()
    conns[2].err = "HTTP 500: x"
    sm.run("teste2", ["bad"])
    assert "bad" in sm.failed_sources()
    conns[2].err = None
    r = sm.retry_failed()
    assert r["iniciada"] and r["fontes"] == ["bad"]
    sm._thread.join(10)
    assert sm.snapshot()["fontes"]["bad"]["estado"] == "concluido" and "bad" not in sm.failed_sources()


def test_sync_structured_log_has_no_secrets(tmp_path, ka):
    class Net(Fast):
        def run(self, job, ctx):
            ctx.http.request_json(ka + "/ok?key=MINHACHAVE123&access_token=TOKEN987654", ttl=0)
            return [], []
    sm, _ = _sm(tmp_path, [Net("rss")])
    sm.http.cfg.min_interval = 0
    sm.run("teste")
    logs = list((tmp_path / "logs" / "sync").glob("*.jsonl"))
    txt = logs[0].read_text(encoding="utf-8")
    lines = [json.loads(x) for x in txt.splitlines()]
    assert {l["tipo"] for l in lines} >= {"inicio", "fonte_inicio", "requisicao", "fonte_fim", "fim"}
    req = next(l for l in lines if l["tipo"] == "requisicao")
    assert req["fonte"] == "rss" and req["status"] == 200 and "job" in req and "segundos" in req
    assert "MINHACHAVE123" not in txt and "TOKEN987654" not in txt


# ===================================================================== Meta
def test_meta_modules_request_minimal_scopes_and_rerequest():
    c = {"client_id": "123", "client_secret": "s"}
    u = META.authorize_url(c, "v23.0", "http://127.0.0.1:8765/oauth/callback", "st", "basico")
    assert "scope=public_profile" in u and "ads_read" not in u and "auth_type" not in u
    u2 = META.authorize_url(c, "v23.0", "http://127.0.0.1:8765/oauth/callback", "st", "anuncios", rerequest=True)
    assert "scope=ads_read" in u2 and "auth_type=rerequest" in u2 and "redirect_uri=http%3A%2F%2F127.0.0.1" in u2
    with pytest.raises(SourceError):
        META.authorize_url(c, "v23.0", "x", "st", "tudo")
    ms = META.module_status({"access_token": "t", "escopos": "public_profile,pages_show_list,pages_read_engagement"})
    assert ms["paginas"]["concedido"] and not ms["instagram"]["concedido"] and ms["instagram"]["faltando"] == ["instagram_basic"]
    assert META.module_ok({"access_token": "t", "escopos": "public_profile"}, "meta_ads") is False
    assert META.module_ok({"access_token": "t"}, "meta_ads") is True                       # token antigo sem registro


def test_meta_callback_errors_and_known_block_guidance():
    assert "recusou a autorização" in META.callback_error({"error": "access_denied", "error_reason": "user_denied"})
    msg = META.callback_error({"error_code": "1349220", "error_message": "Feature Unavailable"})
    assert "Feature Unavailable" in msg and "URIs de redirecionamento" in msg and "Modo do app" in msg
    assert META.callback_error({"code": "abc"}) is None


class MHttp:
    def __init__(self, app_ok=True, scopes=("public_profile", "pages_show_list", "pages_read_engagement")):
        self.app_ok, self.scopes, self.calls = app_ok, scopes, []
        self.cancel_event = threading.Event()

    def request_json(self, url, method="GET", **kw):
        self.calls.append(url)
        if "debug_token" in url:
            return {"data": {"is_valid": True, "scopes": list(self.scopes)}}
        if not self.app_ok:
            raise SourceError("HTTP 400: Error validating client secret", "http", status=400)
        return {"id": "123", "name": "GPI App"}


def test_meta_diagnose_app_check_and_permissions():
    creds = Creds({"meta": {"client_id": "123", "client_secret": "s"}})
    d = META.diagnose(MHttp(app_ok=False), creds, {})
    assert d["estado"] == "erro" and "App Secret" in d["etapas"][0]["mensagem"] and d["bloqueio_conhecido"]["etapas"]
    d = META.diagnose(MHttp(), creds, {})
    assert d["estado"] == "configurado" and "Recurso indisponível" in d["etapas"][-1]["acao"]
    creds.set("meta", {"access_token": "tok"})
    d = META.diagnose(MHttp(), creds, {})
    st = {s["etapa"]: s for s in d["etapas"]}
    assert d["estado"] == "autorizado" and st["Permissões — Páginas do Facebook"]["ok"]
    assert not st["Permissões — Biblioteca de Anúncios"]["ok"] and "identidade" in st["Permissões — Biblioteca de Anúncios"]["acao"]


# ===================================================================== estados das integrações e API
def test_integration_states_are_separated():
    p = {"id": "youtube", "tipo": "api_key"}
    base = {"credenciais": {"api_key": "AIz…123"}, "conectores": [{"validada": False, "registros": 0, "estado": "nao_testada", "disponivel": True}]}
    assert integration_state(p, {"credenciais": {}, "conectores": []}, None)["nivel"] == "nao_configurado"
    assert integration_state(p, base, None)["nivel"] == "autenticado"                       # chave aceita ≠ funcional
    ok = {"credenciais": {"api_key": "x"}, "conectores": [{"validada": True, "registros": 494, "estado": "funcional", "disponivel": True}],
          "conectado": True}
    assert integration_state(p, ok, None)["nivel"] == "funcional"
    gads = {"id": "google_ads", "tipo": "oauth"}
    diag = {"em": "x", "resultado": {"estado": "basic", "etapas": [{"etapa": "OAuth", "ok": True, "mensagem": "ok"}]}}
    st = integration_state(gads, {"credenciais": {"refresh_token": "r"}, "conectores": [{"validada": False, "registros": 0}]}, diag)
    assert st["nivel"] == "restrito" and st["passos"][0]["etapa"] == "OAuth"
    assert integration_state({"id": "amazon", "tipo": "approval"}, {"conectores": []}, None)["nivel"] == "restrito"


def test_v061_routes_sse_csrf_and_safe_export(tmp_path):
    d = tmp_path / "data"
    s = Srv(d)
    try:
        s.app.state.sync.creds.set("youtube", {"api_key": "AIzaSySEGREDOYT1234"})
        code, p = s.req("/api/sync/panel")
        assert code == 200 and "fontes" in p and "titulo" in p
        assert s.req("/api/sync/history")[0] == 200
        assert s.req("/api/sync/retry-failed", {}, headers={"X-GPI": "0"})[0] == 403          # CSRF preservado
        assert s.req("/api/integrations/google_ads/accounts", {}, headers={"X-GPI": "0"})[0] == 403
        code, info = s.req("/api/integrations/google_ads/info")
        assert code == 200 and info["autenticado"] is False and info["developer_token"] == "não necessário"
        assert s.req("/api/integrations/google_ads/select", {"customer_id": ""})[0] == 400
        assert s.req("/api/youtube/status")[1]["videos_armazenados"] == 0
        assert s.req("/api/youtube/videos?q=x")[1]["total"] == 0
        assert s.req("/api/integrations/meta/modules")[1]["modulos"]["basico"]["escopos"] == ["public_profile"]
        code, ints = s.req("/api/integrations?v=6")
        yt = next(x for x in ints["integracoes"] if x["id"] == "youtube")
        assert yt["estados"]["nivel"] == "autenticado" and yt["diagnosticavel"]
        code, raw = s.req("/api/diagnostics/export", raw=True)
        txt = raw.decode("utf-8")
        assert code == 200 and "AIzaSySEGREDOYT1234" not in txt and '"versao_gpi"' in txt and "api_key" in txt
        # SSE: o primeiro evento chega sem recarregar a página
        sock = socket.create_connection(("127.0.0.1", s.port), timeout=5)
        sock.sendall(b"GET /api/sync/events HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: text/event-stream\r\n\r\n")
        buf = b""
        while b"event: estado" not in buf:
            buf += sock.recv(65536)
        sock.close()
        assert b"text/event-stream" in buf and b"retry: 3000" in buf and b'"fontes"' in buf
    finally:
        s.stop()


def test_frontend_v061_wiring():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "v061.js").read_text(encoding="utf-8")
    assert "v061.js" in html and 'href="#sincronizacao"' in html
    for s in ("EventSource('/api/sync/events')", "Ver detalhes", "Tentar novamente fontes com falha", "Ver histórico", "Exportar diagnóstico",
              "Cancelar sincronização", "Atualizar fontes", "Identificar contas disponíveis", "Verificar acesso", "Sincronizar dados",
              "Diagnosticar integração", "Consultar vídeos armazenados", "Atualizar agora", "role=\"progressbar\""):
        assert s in js, s
    assert "GPI_V061(" in (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
