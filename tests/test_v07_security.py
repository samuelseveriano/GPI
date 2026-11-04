"""Testes de segurança da v0.7 (servidor local, SSRF, sanitização, injeção em planilhas, varredura de segredos)."""
from __future__ import annotations

import http.client
import json
import logging
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from test_api_integration import Srv

from gpi.security import BodyLimit, RedactFilter, public_url_problem, safe_cell, scrub

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def srv(tmp_path):
    s = Srv(tmp_path / "data")
    yield s
    s.stop()


def raw(port, method, path, headers=None, body=b""):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for k, v in (headers or {}).items():
        c.putheader(k, v)
    if body:
        c.putheader("Content-Length", str(len(body)))
    c.endheaders(body or None)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict(r.getheaders()), data


def test_dns_rebinding_host_rejected(srv):
    st, _, _ = raw(srv.port, "GET", "/api/health", {"Host": "evil.example.com"})
    assert st == 403
    st, _, _ = raw(srv.port, "GET", "/api/health", {"Host": f"127.0.0.1:{srv.port}"})
    assert st == 200


def test_csrf_header_and_origin_required(srv):
    h = {"Host": f"127.0.0.1:{srv.port}", "Content-Type": "application/json"}
    st, _, _ = raw(srv.port, "POST", "/api/demo", h, b"{}")
    assert st == 403                                   # sem X-GPI (formulário/fetch simples de outro site)
    st, _, _ = raw(srv.port, "POST", "/api/demo", {**h, "X-GPI": "1", "Origin": "https://evil.example"}, b"{}")
    assert st == 403
    st, _, _ = raw(srv.port, "POST", "/api/shutdown", h, b"{}")
    assert st == 403                                   # shutdown exige o token local


def test_security_headers_and_csp(srv):
    st, hd, _ = raw(srv.port, "GET", "/", {"Host": f"127.0.0.1:{srv.port}"})
    assert st == 200
    csp = hd["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-eval" not in csp and "frame-ancestors 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert hd["x-frame-options"] == "DENY" and hd["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in {k.lower() for k in hd}


def test_cors_preflight_not_granted(srv):
    st, hd, _ = raw(srv.port, "OPTIONS", "/api/demo", {"Host": f"127.0.0.1:{srv.port}", "Origin": "https://evil.example",
                                                        "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in {k.lower() for k in hd}


def test_body_limit_returns_413(srv):
    big = b"{" + b" " * (3 * 1024 * 1024) + b"}"
    st, _, data = raw(srv.port, "POST", "/api/integrations/settings",
                      {"Host": f"127.0.0.1:{srv.port}", "X-GPI": "1", "Content-Type": "application/json"}, big)
    assert st == 413 and "limite" in json.loads(data)["erro"]


def test_body_limit_chunked_without_content_length():
    import asyncio
    asyncio.run(_chunked())


async def _chunked():
    called = {}

    async def app(scope, receive, send):
        while True:
            m = await receive()
            if not m.get("more_body"):
                break
        called["ok"] = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = BodyLimit(app, default=10)
    chunks = [{"type": "http.request", "body": b"x" * 8, "more_body": True},
              {"type": "http.request", "body": b"x" * 8, "more_body": False}]
    sent = []

    async def receive():
        return chunks.pop(0)

    async def send(m):
        sent.append(m)

    await mw({"type": "http", "path": "/api/x", "headers": []}, receive, send)
    assert sent[0]["status"] == 413 and "ok" not in called


def test_path_traversal_static(srv):
    for p in ("/static/../backend/gpi/app.py", "/static/%2e%2e/%2e%2e/LEIA-ME.txt", "/static/..%5c..%5cLEIA-ME.txt"):
        st, _, body = raw(srv.port, "GET", p, {"Host": f"127.0.0.1:{srv.port}"})
        assert st in (400, 404) or b"create_app" not in body


@pytest.mark.parametrize("url,ok", [
    ("https://tecnoblog.net/feed/", True),
    ("http://127.0.0.1:8765/api/status", False),
    ("http://localhost/x", False),
    ("http://169.254.169.254/latest/meta-data/", False),
    ("http://10.0.0.5/feed", False),
    ("http://192.168.1.1/", False),
    ("http://[::1]/", False),
    ("http://[::ffff:127.0.0.1]/", False),
    ("http://0x7f000001/", False),          # não é IP literal válido p/ ipaddress → resolvido (falha) ou recusado
    ("file:///etc/passwd", False),
    ("ftp://example.com/feed", False),
    ("https://user:pw@example.com/feed", False),
    ("http://intranet.local/feed", False),
])
def test_ssrf_guard(url, ok):
    def fake_resolver(host, port, proto=0):
        if host == "tecnoblog.net":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("104.21.1.1", port))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
    assert (public_url_problem(url, resolver=fake_resolver) is None) == ok


def test_ssrf_dns_pointing_to_private_is_refused():
    def r(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]
    assert "interno" in public_url_problem("https://rebind.example.com/feed", resolver=r)


def test_settings_reject_internal_feed(srv):
    st, _ = srv.req("/api/integrations/rss/settings", {"rss_feeds": [
        {"nome": "ok", "url": "https://tecnoblog.net/feed/"},
        {"nome": "interno", "url": "http://127.0.0.1:8765/api/status"},
        {"nome": "meta", "url": "http://169.254.169.254/"}]})
    assert st == 200
    saved = json.loads((Path(srv.app.state.db.path).parent / "config.json").read_text(encoding="utf-8"))
    assert [f["url"] for f in saved["rss_feeds"]] == ["https://tecnoblog.net/feed/"]


def test_log_sanitization(tmp_path):
    secret_vals = ["GOCSPX-abcdefghijklmnopqrstuvwx", "1//0gAbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdef",
                   "EAAB" + "x1" * 40, "APP_USR-1234567890123456-110316-abcdef0123456789abcdef0123456789-123456789",
                   "AIza" + "B" * 35]
    log = logging.getLogger("gpi.teste.redact")
    h = logging.FileHandler(tmp_path / "t.log", encoding="utf-8")
    h.addFilter(RedactFilter())
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log.info("token %s url https://x.test/cb?code=AUTHCODE123456&state=s1 refresh_token=%s", secret_vals[0], secret_vals[1])
    log.info("Authorization: Bearer %s / %s / %s / %s", secret_vals[2], secret_vals[3], secret_vals[4], "code_verifier=VERIF1234567890")
    try:
        raise ValueError("falha em https://api.example/x?access_token=" + secret_vals[0])
    except ValueError:
        log.exception("erro")
    h.close()
    txt = (tmp_path / "t.log").read_text(encoding="utf-8")
    for v in secret_vals + ["AUTHCODE123456", "VERIF1234567890"]:
        assert v not in txt
    assert "state=s1" in txt and "ValueError" in txt


def test_scrub_keeps_normal_text():
    assert scrub("Sincronização concluída: 120 registros, código 200") == "Sincronização concluída: 120 registros, código 200"


@pytest.mark.parametrize("v,exp", [("=HYPERLINK(\"http://x\")", "'=HYPERLINK(\"http://x\")"), ("+cmd", "'+cmd"),
                                   ("@SUM(A1)", "'@SUM(A1)"), ("-12,5", "-12,5"), ("normal", "normal"), (5, 5)])
def test_formula_injection(v, exp):
    assert safe_cell(v) == exp


def test_secret_scan_tree_and_history_clean():
    for args in ([], ["--historico"]):
        r = subprocess.run([sys.executable, "scripts/secret_scan.py", *args], cwd=ROOT, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout[-2000:]


def test_secret_scan_detects_and_never_prints_value(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import secret_scan
    fake = "GOCSPX-" + "Q7w" * 8
    achados = list(secret_scan.analisar_linha(f'client_secret = "{fake}"'))
    assert achados and achados[0][0].startswith("Client secret")
    a = []
    secret_scan.varrer_texto(f'+++ b/x.py\n@@ -0,0 +1 @@\n+k="{fake}"', "patch", a)
    assert a and fake not in repr(a)
    assert secret_scan.PROIBIDOS.search("data/gpi.sqlite") and secret_scan.PROIBIDOS.search("models/qwen.gguf")


def test_server_binds_loopback_only():
    src = (ROOT / "backend/gpi/main.py").read_text(encoding="utf-8")
    assert 'HOST = "127.0.0.1"' in src and "0.0.0.0" not in src


def test_workflows_minimal_permissions_and_no_pr_target():
    for wf in (ROOT / ".github/workflows").glob("*.yml"):
        t = wf.read_text(encoding="utf-8")
        assert "pull_request_target" not in t, wf.name
        assert "permissions:\n  contents: read" in t, wf.name
