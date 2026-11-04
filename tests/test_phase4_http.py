"""Fase 4 — cliente HTTP: compressão (caso IBGE), HTML no lugar de JSON, erros, timeout,
revalidação condicional (ETag/304) e disjuntor. Servidor HTTP local real; nenhum dado de mercado."""
import gzip
import json
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gpi.connectors.http import HttpClient, HttpConfig, SourceError, decode_body

PAYLOAD = {"ok": True, "texto": "ação 智能门锁"}


class H(BaseHTTPRequestHandler):
    hits = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", headers=None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        H.hits[self.path] = H.hits.get(self.path, 0) + 1
        js = json.dumps(PAYLOAD, ensure_ascii=False).encode()
        if self.path == "/json":
            self._send(200, js, {"Content-Type": "application/json"})
        elif self.path == "/gzip":
            self._send(200, gzip.compress(js), {"Content-Encoding": "gzip", "Content-Type": "application/json"})
        elif self.path == "/gzip-sem-cabecalho":           # como o IBGE: gzip sem Content-Encoding
            self._send(200, gzip.compress(js), {"Content-Type": "application/json"})
        elif self.path == "/deflate":
            self._send(200, zlib.compress(js), {"Content-Encoding": "deflate"})
        elif self.path == "/html":
            self._send(200, b"<!DOCTYPE html><html><body>Manutencao</body></html>", {"Content-Type": "text/html"})
        elif self.path == "/invalido":
            self._send(200, b"{quebrado", {"Content-Type": "application/json"})
        elif self.path == "/erro500":
            self._send(500, b"falha interna")
        elif self.path == "/erro400":
            self._send(400, b"parametro invalido")
        elif self.path == "/lento":
            time.sleep(1.5)
            self._send(200, js)
        elif self.path == "/etag":
            if self.headers.get("If-None-Match") == '"v1"':
                self._send(304)
            else:
                self._send(200, js, {"ETag": '"v1"', "Content-Type": "application/json"})
        else:
            self._send(404, b"nao encontrado")


@pytest.fixture(scope="module")
def base():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def client(tmp_path, monkeypatch):
    for v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(v, raising=False)
    return HttpClient(tmp_path, HttpConfig(timeout=5, max_attempts=2, backoff_base=0.01, min_interval=0),
                      sleep=lambda s: None)


def test_plain_and_compressed_json(base, client):
    for path in ("/json", "/gzip", "/gzip-sem-cabecalho", "/deflate"):
        assert client.request_json(base + path, ttl=0) == PAYLOAD, path


def test_decode_body_never_decompresses_twice():
    js = b'{"a": 1}'
    assert decode_body(js, "gzip") == js                 # cabeçalho diz gzip, mas o corpo já veio descomprimido
    assert decode_body(gzip.compress(js), None) == js
    with pytest.raises(SourceError):
        decode_body(b"\x1f\x8b\x08quebrado", "gzip")


def test_html_and_invalid_json_are_format_errors(base, client):
    with pytest.raises(SourceError) as e:
        client.request_json(base + "/html", ttl=0)
    assert e.value.kind == "formato" and "HTML" in str(e.value)
    with pytest.raises(SourceError) as e:
        client.request_json(base + "/invalido", ttl=0)
    assert e.value.kind == "formato"


def test_http_errors_and_timeout(base, client):
    with pytest.raises(SourceError) as e:
        client.request_json(base + "/erro400", ttl=0)
    assert e.value.status == 400 and not e.value.retryable
    with pytest.raises(SourceError) as e:
        client.request_json(base + "/erro500", ttl=0)
    assert e.value.status == 500 and e.value.retryable
    with pytest.raises(SourceError) as e:
        client.request_json(base + "/lento", ttl=0, timeout=0.3)
    assert e.value.kind == "rede"


def test_etag_revalidation_reuses_content(base, client):
    url = base + "/etag"
    assert client.request_json(url, ttl=0.01) == PAYLOAD
    time.sleep(0.05)                                     # cache vencido → pedido condicional
    assert client.request_json(url, ttl=0.01) == PAYLOAD
    host = url.split("/")[2]
    assert client.host_stats[host]["revalidadas_304"] == 1


def test_circuit_breaker_suspends_failing_host(base, client):
    client.cfg.breaker_threshold = 2
    for _ in range(2):
        with pytest.raises(SourceError):
            client.request_json(base + "/erro500", ttl=0)
    n = H.hits.get("/erro500", 0)
    with pytest.raises(SourceError) as e:
        client.request_json(base + "/json", ttl=0)
    assert "suspenso" in str(e.value)
    assert H.hits.get("/erro500", 0) == n                  # nenhuma nova requisição ao host suspenso
    client.reset_breakers()
    assert client.request_json(base + "/json", ttl=0) == PAYLOAD
