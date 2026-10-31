"""Testes de integração: servidor real em 127.0.0.1, banco em pasta temporária."""
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import uvicorn

from gpi.app import create_app

FRONT = Path(__file__).resolve().parents[1] / "frontend"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Srv:
    def __init__(self, data_dir):
        self.port = _free_port()
        self.app = create_app(data_dir, FRONT)
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port,
                                                    log_level="error"))
        self.t = threading.Thread(target=self.server.run, daemon=True)
        self.t.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)

    def req(self, path, data=None, method=None, headers=None, raw=False):
        h = {"Content-Type": "application/json", "X-GPI": "1", **(headers or {})}
        body = data if isinstance(data, (bytes, type(None))) else json.dumps(data).encode()
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body,
                                   method=method or ("POST" if data is not None else "GET"), headers=h)
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                b = resp.read()
                return resp.status, (b if raw else json.loads(b))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def stop(self):
        self.server.should_exit = True
        self.t.join(5)
        self.app.state.db.close()


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


def test_full_flow_and_restart(data_dir):
    s = Srv(data_dir)
    try:
        assert s.req("/api/health")[1]["ok"]
        code, r = s.req("/api/demo", {})
        assert code == 200 and r["linhas_validas"] > 1000
        st = s.req("/api/status")[1]
        assert st["tem_demo"] and st["somente_demo"]

        code, fc = s.req("/api/forecast", {"sku": "DEMO-001", "freq": "M", "horizon": 6})
        assert code == 200
        assert fc["modelo_escolhido"] in fc["modelos"]
        best = fc["modelos"][fc["modelo_escolhido"]]
        assert len(best["previsao"]) == 6
        assert all(lo <= p <= hi for lo, p, hi in zip(best["lo80"], best["previsao"], best["hi80"]))
        assert all(l95 <= l80 for l95, l80 in zip(best["lo95"], best["lo80"]))
        assert "naive" in fc["backtest"]["resultados"]

        code, inv = s.req("/api/inventory", {"run_id": fc["run_id"], "lead_time_days": 45,
                                              "review_days": 30, "service_level": 0.95,
                                              "on_hand": 10, "in_transit": 0})
        assert code == 200 and inv["qtd_sugerida"] >= 0 and inv["estoque_seguranca"] > 0

        code, ab = s.req("/api/abcxyz?freq=M&n=12")
        assert sum(ab["matriz"].values()) == 10

        code, x = s.req(f"/api/export/previsao.xlsx?run_id={fc['run_id']}", raw=True)
        assert code == 200 and x[:2] == b"PK"
        code, c = s.req("/api/export/abcxyz.csv", raw=True)
        assert code == 200 and b"sku" in c

        code, e = s.req("/api/forecast", {"sku": "NAO-EXISTE", "freq": "M", "horizon": 6})
        assert code == 400 and "erro" in e
    finally:
        s.stop()

    s2 = Srv(data_dir)   # reinício: dados e execuções preservados
    try:
        st = s2.req("/api/status")[1]
        assert st["linhas"] > 1000
        assert len(s2.req("/api/runs")[1]) == 1
    finally:
        s2.stop()


def test_host_guard_and_shutdown_token(data_dir):
    s = Srv(data_dir)
    try:
        code, _ = s.req("/api/health", headers={"Host": "attacker.example"})
        assert code == 403
        code, _ = s.req("/api/shutdown", {}, headers={"X-Token": "errado"})
        assert code == 403
    finally:
        s.stop()


def test_import_upload_and_delete(data_dir):
    s = Srv(data_dir)
    try:
        csv = "data;produto;quantidade\n01/01/2025;Caneca;3\n02/01/2025;Caneca;x\n".encode()
        code, r = s.req("/api/import", csv, headers={"X-Filename": "vendas%20jan.csv"})
        assert code == 200 and r["linhas_validas"] == 1 and r["linhas_rejeitadas"] == 1
        imp = s.req("/api/status")[1]["importacoes"][0]
        assert imp["filename"] == "vendas jan.csv"
        code, _ = s.req(f"/api/imports/{imp['id']}", method="DELETE")
        assert code == 200 and s.req("/api/status")[1]["linhas"] == 0
    finally:
        s.stop()


def test_forecast_rejects_wrong_types_with_400(data_dir):
    """Parâmetro com tipo errado (ex.: lista no lugar do SKU) é erro do cliente (400), não 500."""
    c = client(data_dir)
    c.post("/api/demo")
    for body in ({"sku": ["A", "B"], "horizon": 6}, {"horizon": 6},
                 {"sku": "DEMO-001", "models": "naive"}, {"sku": "DEMO-001", "models": [1, 2]}):
        r = c.post("/api/forecast", json=body)
        assert r.status_code == 400, (body, r.status_code)
