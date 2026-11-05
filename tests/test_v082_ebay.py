"""v0.8.2 — conformidade eBay (Marketplace Account Deletion) no GPI e diagnóstico da Browse API.

TESTES UNITÁRIOS/INTEGRAÇÃO LOCAL, sem credenciais: o Worker é simulado em Python com a MESMA verificação HMAC do
Worker real (e a assinatura é conferida contra o código JavaScript do Worker quando o Node está disponível).
Não provam a integração real — isso exige o Worker publicado e o keyset ativo (docs/EBAY_CLOUDFLARE_SETUP.md)."""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from test_v05 import Creds

from gpi.connectors.http import SourceError
from gpi.db import Database
from gpi.integrations import ebay_compliance as EC

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "t" * 48


class C2(Creds):
    def delete(self, k):
        self.d.pop(k, None)


class Store:
    def __init__(self):
        self.d = {}

    def save_result(self, k, v):
        self.d[k] = v

    def load_result(self, k):
        return self.d.get(k)


class FakeWorker:
    """Worker simulado: confere a assinatura HMAC, o horário e o nonce exatamente como src/index.js."""

    def __init__(self, items=(), token=TOKEN, down=False):
        self.items = {i["notification_id"]: dict(i, status="PENDING") for i in items}
        self.token, self.down, self.nonces, self.acks, self.calls = token, down, set(), [], []

    def request_json(self, url, method="GET", headers=None, ttl=None, _body=None, timeout=None, **k):
        self.calls.append((method, url))
        if self.down:
            raise SourceError("conexão recusada", "rede")
        assert url.startswith("https://") and ttl == 0
        h = {k.lower(): v for k, v in (headers or {}).items()}
        path = "/" + url.split("/", 3)[3].split("?")[0]
        body = _body or b""
        base = "\n".join([method, path, h["x-gpi-timestamp"], h["x-gpi-nonce"], hashlib.sha256(body).hexdigest()]).encode()
        good = hmac.new(self.token.encode(), base, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, h["x-gpi-signature"]) or abs(time.time() - int(h["x-gpi-timestamp"])) > 300 \
                or h["x-gpi-nonce"] in self.nonces:
            raise SourceError("HTTP 401", "http", status=401)
        self.nonces.add(h["x-gpi-nonce"])
        b = json.loads(body) if body else {}
        if path == "/gpi/v1/claim":
            # como o Worker real: RETRY_SCHEDULED só volta depois da espera (simulada aqui como "nunca nesta execução")
            got = [dict(i) for i in self.items.values() if i["status"] == "PENDING"][: b.get("limit", 50)]
            for i in got:
                self.items[i["notification_id"]]["status"] = "PROCESSING"
            return {"itens": got, "quantidade": len(got)}
        if path == "/gpi/v1/ack":
            self.acks.append(b)
            it = self.items[b["notification_id"]]
            it["status"] = {"DELETED": "COMPLETED", "NOT_FOUND": "COMPLETED", "NEEDS_REVIEW": "FAILED", "ERROR": "RETRY_SCHEDULED"}[b["result"]]
            return {"ok": True, "status": it["status"]}
        if path == "/gpi/v1/status":
            return {"pendentes": sum(i["status"] != "COMPLETED" for i in self.items.values()), "falhas": 0, "alerta": None}
        raise SourceError("HTTP 404", "http", status=404)


def _setup(tmp_path):
    data = tmp_path / "dados"
    (data / "backups").mkdir(parents=True)
    (data / "cache").mkdir()
    db = Database(data / "gpi.sqlite")
    creds = C2({"ebay": {"client_id": "a", "client_secret": "b", "sync_token": TOKEN}})
    rows = [("ebay", "1", "VendedorAlvo"), ("ebay", "2", EC.seller_pseudonym(creds, "vendedoralvo")), ("ebay", "3", "outro_vendedor"),
            ("mercadolivre", "4", "loja_ml")]
    for src, iid, seller in rows:
        db.execute("INSERT INTO market_listings (source, item_id, day, product_id, query, title, seller, collected_at) "
                   "VALUES (?, ?, '2026-11-01', 'p', 'q', 't', ?, '2026-11-01')", (src, iid, seller))
    db.backup(data / "backups")
    (data / "cache" / "abc.json").write_text(json.dumps({"itemSummaries": [{"seller": {"username": "vendedoralvo"}}]}), encoding="utf-8")
    (data / "cache" / "def.json").write_text(json.dumps({"itemSummaries": [{"seller": {"username": "outro_vendedor"}}]}), encoding="utf-8")
    rep = data / "relatorios"
    rep.mkdir()
    (rep / "r1.snapshot.json.gz").write_bytes(gzip.compress(json.dumps({"linhas": [{"vendedor": "VendedorAlvo"}]}).encode()))
    (rep / "r1.xlsx").write_bytes(b"x")
    (rep / "r2.snapshot.json.gz").write_bytes(gzip.compress(b'{"linhas": []}'))
    (rep / "r2.xlsx").write_bytes(b"y")
    return db, creds, data


ITEM = {"notification_id": "n-0000000001", "ebay_username": "VendedorAlvo", "ebay_user_id": "uid-alvo", "event_date": "2026-11-01",
        "received_at": "2026-11-01T10:00:00Z"}


# 10. exclusão local completa e seletiva
def test_local_deletion_covers_db_backups_cache_reports_and_is_selective(tmp_path):
    db, creds, data = _setup(tmp_path)
    r = EC.process_one(db, data, data / "cache", creds, ITEM)
    assert r["result"] == "DELETED"
    assert r["contagens"]["banco"] == 2 and r["contagens"]["backups"] == 2 and r["contagens"]["cache"] == 1 and r["contagens"]["relatorios"] == 1
    left = {(x["source"], x["seller"]) for x in db.query("SELECT source, seller FROM market_listings")}
    assert left == {("ebay", "outro_vendedor"), ("mercadolivre", "loja_ml")}          # só o abrangido foi excluído
    bk = next((data / "backups").glob("*.sqlite"))
    con = sqlite3.connect(bk)
    assert con.execute("SELECT COUNT(*) FROM market_listings WHERE source = 'ebay' AND lower(seller) = 'vendedoralvo'").fetchone()[0] == 0
    con.close()
    assert not (data / "cache" / "abc.json").exists() and (data / "cache" / "def.json").exists()
    snap = gzip.decompress((data / "relatorios" / "r1.snapshot.json.gz").read_bytes()).decode()
    assert "VendedorAlvo" not in snap and not (data / "relatorios" / "r1.xlsx").exists()
    assert (data / "relatorios" / "r2.xlsx").exists()                                  # relatório sem o usuário intacto
    raw = bk.read_bytes()
    assert b"VendedorAlvo" not in raw and b"outro_vendedor" in raw                       # backup: VACUUM + secure_delete
    again = EC.process_one(db, data, data / "cache", creds, ITEM)
    assert again["result"] == "NOT_FOUND"                                                # idempotente


def test_main_db_file_has_no_residue_after_secure_delete(tmp_path):
    db, creds, data = _setup(tmp_path)
    EC.process_one(db, data, data / "cache", creds, ITEM)
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    blob = b"".join(p.read_bytes() for p in data.glob("gpi.sqlite*"))
    assert b"VendedorAlvo" not in blob and b"vendedoralvo" not in blob                  # secure_delete sobrescreveu
    assert b"outro_vendedor" in blob                                                     # o restante continua


# 8, 9, 11. GPI offline → reconectado; confirmação de processamento
def test_sync_offline_then_reconnected_confirms_processing(tmp_path):
    db, creds, data = _setup(tmp_path)
    st = Store()
    w = FakeWorker([ITEM], down=True)
    out = EC.sync(db, w, creds, data, data / "cache", st)
    assert out["situacao"] == "falhou" and "alcançar o Worker" in out["erros"][0]
    pseudo = EC.seller_pseudonym(creds, "VendedorAlvo")
    assert db.query("SELECT COUNT(*) AS n FROM market_listings WHERE source = 'ebay' AND (lower(seller) = 'vendedoralvo' OR seller = ?)",
                    (pseudo,))[0]["n"] == 2                                              # nada excluído enquanto offline
    w.down = False
    out = EC.sync(db, w, creds, data, data / "cache", st)
    assert out["situacao"] == "ok" and out["processadas"] == 1 and out["resultados"] == {"DELETED": 1}
    assert w.acks[0]["result"] == "DELETED" and "VendedorAlvo" not in json.dumps(w.acks)
    log = db.query("SELECT * FROM ebay_deletion_log")[0]
    assert log["confirmed_at"] and log["result"] == "DELETED" and "VendedorAlvo" not in json.dumps(log)
    assert EC.sync(db, w, creds, data, data / "cache", st)["processadas"] == 0          # nada pendente


# 12–13. autenticação
def test_invalid_sync_token_is_reported_clearly(tmp_path):
    db, creds, data = _setup(tmp_path)
    w = FakeWorker([ITEM], token="outro" * 10)
    out = EC.sync(db, w, creds, data, data / "cache", Store())
    assert out["situacao"] == "falhou" and "difere do Secret" in out["erros"][0]
    nocfg = C2({"ebay": {"client_id": "a", "client_secret": "b"}})
    out2 = EC.sync(db, FakeWorker(), nocfg, data, data / "cache", Store())
    assert out2["situacao"] == "nao_configurado"
    with pytest.raises(SourceError):
        EC._signed(FakeWorker(), C2({"ebay": {"sync_token": "curto"}}), "GET", "/gpi/v1/status")
    with pytest.raises(SourceError):
        EC.worker_url(C2({"ebay": {"worker_url": "http://inseguro.example"}}))


# 14. retentativas
def test_processing_error_is_acknowledged_as_error_for_retry(tmp_path, monkeypatch):
    db, creds, data = _setup(tmp_path)
    w = FakeWorker([ITEM])
    monkeypatch.setattr(EC, "process_one", lambda *a, **k: (_ for _ in ()).throw(OSError("disco")))
    out = EC.sync(db, w, creds, data, data / "cache", Store())
    assert w.acks[0]["result"] == "ERROR" and out["resultados"] == {"ERROR": 1}
    assert w.items["n-0000000001"]["status"] == "RETRY_SCHEDULED"


# 15–16. histórico e dados pessoais
def test_status_and_history_do_not_expose_personal_data(tmp_path):
    db, creds, data = _setup(tmp_path)
    st = Store()
    EC.sync(db, FakeWorker([ITEM]), creds, data, data / "cache", st)
    s = EC.local_status(db, creds, st)
    txt = json.dumps(s, default=str)
    assert "VendedorAlvo" not in txt and TOKEN not in txt and s["processadas_local"] == {"DELETED": 1}
    assert s["vendedores_em_texto"] == 0                                                 # antigos pseudonimizados


def test_existing_plain_sellers_are_pseudonymized_and_competition_kept(tmp_path):
    db, creds, data = _setup(tmp_path)
    assert EC.pseudonymize_existing(db, creds) == 2                                      # VendedorAlvo e outro_vendedor
    vals = [r["seller"] for r in db.query("SELECT seller FROM market_listings WHERE source = 'ebay'")]
    assert all(v.startswith("h:") for v in vals)
    # o mesmo vendedor (texto antigo + pseudônimo novo) passa a contar uma vez só: 2 vendedores distintos
    assert db.query("SELECT COUNT(DISTINCT seller) AS n FROM market_listings WHERE source = 'ebay'")[0]["n"] == 2
    assert EC.seller_pseudonym(creds, "VendedorAlvo") == EC.seller_pseudonym(creds, " vendedoralvo ")
    assert EC.pseudonymize_existing(db, creds) == 0                                      # idempotente


def test_collection_blocked_without_compliance_and_alert_shown(tmp_path):
    db, _, _ = _setup(tmp_path)
    c = C2({"ebay": {"client_id": "a", "client_secret": "b"}})
    s = EC.local_status(db, c, Store())
    assert s["coleta_permitida"] is False and any("bloqueada" in a for a in s["alertas"])


# assinatura idêntica à do Worker JavaScript
def test_hmac_matches_worker_javascript():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js não disponível")
    js = ("import { syncSignature } from './src/index.js';"
          "console.log(await syncSignature('" + TOKEN + "', 'POST', '/gpi/v1/ack', '1762000000', 'abcdefghijklmnop', '{\"a\":1}'));")
    r = subprocess.run([node, "--input-type=module", "-e", js], cwd=ROOT / "cloudflare" / "ebay-notifications",
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    base = "\n".join(["POST", "/gpi/v1/ack", "1762000000", "abcdefghijklmnop", hashlib.sha256(b'{"a":1}').hexdigest()]).encode()
    assert r.stdout.strip() == hmac.new(TOKEN.encode(), base, hashlib.sha256).hexdigest()


# Browse API: estados distintos
class EbayApi:
    def __init__(self, token=None, search=None):
        self.token, self.search = token, search

    def request_json(self, url, *a, **k):
        if "oauth2/token" in url:
            if isinstance(self.token, SourceError):
                raise self.token
            return {"access_token": "T", "expires_in": 7200}
        if isinstance(self.search, SourceError):
            raise self.search
        return self.search


@pytest.mark.parametrize("token,search,state", [
    (SourceError("HTTP 401 invalid_client", "http", status=401, body='{"error":"invalid_client"}'), None, "credencial_invalida"),
    (None, SourceError("HTTP 403", "http", status=403, body='{"errors":[{"errorId":1100,"message":"Access denied"}]}'), "api_nao_autorizada"),
    (None, SourceError("HTTP 403", "http", status=403, body='{"errors":[{"message":"Insufficient permissions"}]}'), "permissao_ausente"),
    (None, SourceError("HTTP 429", "limite", status=429), "limite"),
    (None, SourceError("HTTP 503", "http", status=503), "falha_interna"),
    (SourceError("timeout", "rede"), None, "rede"),
    (None, {"total": 1234, "itemSummaries": [{"itemId": "1"}]}, "ok"),
])
def test_browse_diagnosis_distinguishes_failures(tmp_path, token, search, state):
    db, creds, _ = _setup(tmp_path)
    r = EC.browse_diagnose(EbayApi(token, search), creds, db, Store())
    assert r["estado"] == state
    assert "T" != json.dumps(r).count("access_token")


def test_browse_token_alone_is_not_api_authorization(tmp_path):
    db, creds, _ = _setup(tmp_path)
    r = EC.browse_diagnose(EbayApi(None, SourceError("HTTP 403", "http", status=403, body="Access denied")), creds, db, Store())
    assert r["etapas"][2]["ok"] is True and r["estado"] != "ok"                          # token emitido ≠ API liberada


def test_keyset_disabled_hint_when_compliance_missing(tmp_path):
    db, _, _ = _setup(tmp_path)
    c = C2({"ebay": {"client_id": "a", "client_secret": "b"}})
    r = EC.browse_diagnose(EbayApi(SourceError("HTTP 401", "http", status=401, body="invalid_client"), None), c, db, Store())
    assert r["estado"] == "keyset_desativado" and "conformidade" in r["etapas"][1]["acao"]
