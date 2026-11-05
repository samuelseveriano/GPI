"""v0.8.2 — correção do retorno OAuth da Meta ("Retorno inválido ou incompleto").

TESTES UNITÁRIOS / DE INTEGRAÇÃO LOCAL: a Graph API é SIMULADA no formato oficial; nenhuma credencial real.
Não provam que o login real funciona — isso exige o App ID/Secret do usuário (teste dependente de credenciais,
roteiro em docs/META_OAUTH_FIX.md). A lógica da página pública (relay.js) é testada em Node por
.github/pages/verify_relay.js (workflow pages)."""
from __future__ import annotations

import re
import time
import urllib.parse as up
from pathlib import Path

import pytest

from test_v081_meta import C2, Graph, creds

from gpi.connectors.http import SourceError
from gpi.integrations import meta as M
from gpi.integrations.oauth import PendingFlows

ROOT = Path(__file__).resolve().parents[1]


def _state(f, c, port=8765):
    r = M.start(f, c, {}, port)
    return up.parse_qs(up.urlsplit(r["url"]).query)["state"][0]


def _diag(fn):
    with pytest.raises(SourceError) as ei:
        fn()
    return getattr(ei.value, "diag", None), str(ei.value)


def _code(n):
    return ("AQ" + "Bx9_-" * 500)[:n]


# 1–3: tamanhos de código — a causa do bug era o limite de 300 caracteres no relay
@pytest.mark.parametrize("n", [8, 120, 301, 412, 1024, 2048])
def test_codes_short_long_and_above_300_are_accepted(n):
    c, f, g = creds(), PendingFlows(), Graph()
    out = M.complete(g, c, f, {}, _code(n), _state(f, c))
    assert out["ok"] and out["estado"] == "autenticado"


def test_relay_and_backend_use_the_same_code_rule():
    js = (ROOT / "pages/oauth/meta/relay.js").read_text(encoding="utf-8")
    mn, mx = int(re.search(r"CODE_MIN = (\d+)", js).group(1)), int(re.search(r"CODE_MAX = (\d+)", js).group(1))
    assert (mn, mx) == (8, 2048)
    assert M.CODE_RX.match("A" * mx) and not M.CODE_RX.match("A" * (mx + 1)) and not M.CODE_RX.match("A" * (mn - 1))
    assert "{8,300}" not in js                                   # o limite antigo não voltou


# 4–5
def test_invalid_code_and_missing_code():
    c, f = creds(), PendingFlows()
    d, msg = _diag(lambda: M.complete(Graph(), c, f, {}, "abc<script>x", _state(f, c)))
    assert d == "M02" and "<script>" not in msg
    d, _ = _diag(lambda: M.complete(Graph(), c, f, {}, "", _state(f, c)))
    assert d == "M01"
    d, _ = _diag(lambda: M.complete(Graph(), c, f, {}, "A" * 2049, _state(f, c)))
    assert d == "M02"


# 6–9: state
def test_state_valid_missing_invalid_expired():
    c, f, g = creds(), PendingFlows(), Graph()
    s = _state(f, c)
    assert re.match(r"^8765\.[A-Za-z0-9_\-]{43}$", s)            # 256 bits, porta local na frente
    assert _diag(lambda: M.complete(g, c, f, {}, _code(400), ""))[0] == "M03"
    assert _diag(lambda: M.complete(g, c, f, {}, _code(400), "8765.forjado"))[0] == "M04"
    assert _diag(lambda: M.complete(g, c, f, {}, _code(400), "8765." + "b" * 43))[0] == "M04"   # outra sessão
    short = PendingFlows(ttl=0.01)
    s2 = _state(short, c)
    time.sleep(0.05)
    assert _diag(lambda: M.complete(g, c, short, {}, _code(400), s2))[0] == "M05"
    assert M.complete(g, c, f, {}, _code(400), s)["ok"]          # o state válido continua funcionando


# 10: replay
def test_replay_is_refused_with_specific_diagnosis():
    c, f, g = creds(), PendingFlows(), Graph()
    s = _state(f, c)
    assert M.complete(g, c, f, {}, _code(400), s)["ok"]
    d, msg = _diag(lambda: M.complete(g, c, f, {}, _code(400), s))
    assert d == "M09" and _code(400) not in msg
    assert sum("oauth/access_token" in u and "code=" in u for u in g.calls) == 1   # o código não foi trocado de novo


# 11: erro devolvido pela Meta
def test_meta_error_is_reported():
    msg = M.callback_error({"error": "access_denied", "error_reason": "user_denied", "error_description": "Permissions error"})
    assert "recusou" in msg
    js = (ROOT / "pages/oauth/meta/relay.js").read_text(encoding="utf-8")
    assert "Meta recusou a autorização." in js and "'M06'" in js


# 12–13: retorno HTTPS e comunicação com o GPI local
def test_https_return_and_local_handoff_target():
    c, f = creds(), PendingFlows()
    r = M.start(f, c, {}, 8765)
    assert r["redirect_uri"] == "https://samuelseveriano.github.io/GPI/oauth/meta/" and r["modo"] == "https_relay"
    js = (ROOT / "pages/oauth/meta/relay.js").read_text(encoding="utf-8")
    assert "'http://127.0.0.1:' + port + '/oauth/meta/retorno#'" in js       # destino fixo, código no fragmento
    assert not re.search(r"fetch\(|XMLHttpRequest|localStorage|document\.cookie", js)
    local = (ROOT / "frontend/oauth_meta_retorno.js").read_text(encoding="utf-8")
    assert "M07" in local and "/api/oauth/meta/concluir" in local


# 14–16: token válido, token recusado, App ID divergente
def test_token_valid_refused_and_other_app():
    c, f = creds(), PendingFlows()
    out = M.complete(Graph(), c, f, {}, _code(400), _state(f, c))
    assert out["app_id"] == "1663502878474287" and c.get("meta")["access_token"] == "EAAlong"

    class NoToken(Graph):
        def request_json(self, url, *a, **k):
            if "oauth/access_token" in url:
                return {"error": {"message": "Invalid verification code format."}}
            return super().request_json(url, *a, **k)
    c2, f2 = creds(), PendingFlows()
    d, _ = _diag(lambda: M.complete(NoToken(), c2, f2, {}, _code(400), _state(f2, c2)))
    assert d == "M08" and not c2.get("meta").get("access_token")

    c3, f3 = creds(), PendingFlows()
    d, msg = _diag(lambda: M.complete(Graph(token_app="1855094518955679"), c3, f3, {}, _code(400), _state(f3, c3)))
    assert d == "M10" and "1855094518955679" in msg
    assert not c3.get("meta").get("access_token")               # token de outro app NÃO é gravado

    class Invalid(Graph):
        def request_json(self, url, *a, **k):
            if "debug_token" in url:
                return {"data": {"is_valid": False, "app_id": "1663502878474287"}}
            return super().request_json(url, *a, **k)
    c4, f4 = creds(), PendingFlows()
    assert _diag(lambda: M.complete(Invalid(), c4, f4, {}, _code(400), _state(f4, c4)))[0] == "M11"
    assert not c4.get("meta").get("access_token")


# 17: permissão ausente
def test_missing_permission_is_visible_per_module():
    c, f = creds(), PendingFlows()
    M.complete(Graph(), c, f, {}, _code(400), _state(f, c))
    ms = M.module_status(c.get("meta"))
    assert ms["basico"]["concedido"] is True
    assert ms["anuncios"]["concedido"] is False and "ads_read" in ms["anuncios"]["faltando"]


# 18: autorização expirada do lado da Meta (código vencido)
def test_code_expired_at_meta():
    class Expired(Graph):
        def request_json(self, url, *a, **k):
            if "oauth/access_token" in url and "code=" in url:
                raise SourceError("This authorization code has expired.", "http", status=400)
            return super().request_json(url, *a, **k)
    c, f = creds(), PendingFlows()
    assert _diag(lambda: M.complete(Expired(), c, f, {}, _code(400), _state(f, c)))[0] == "M05"


# 19: login básico ponta a ponta (simulado)
def test_basic_login_end_to_end_simulated():
    c, f, g = creds(), PendingFlows(), Graph()
    r = M.start(f, c, {}, 8765, "basico")
    q = up.parse_qs(up.urlsplit(r["url"]).query)
    assert q["scope"] == ["public_profile"] and q["client_id"] == ["1663502878474287"] and q["response_type"] == ["code"]
    out = M.complete(g, c, f, {}, _code(412), q["state"][0])
    assert out["estado"] == "autenticado" and "public_profile" in out["escopos"]
    assert any("debug_token" in u for u in g.calls)              # token conferido antes de gravar


# 20: reabertura do aplicativo
def test_reopen_loses_pending_flow_but_keeps_token():
    c, f = creds(), PendingFlows()
    s = _state(f, c)
    reopened = PendingFlows()                                     # GPI fechado e aberto: fluxos em memória somem
    d, msg = _diag(lambda: M.complete(Graph(), c, reopened, {}, _code(400), s))
    assert d == "M04" and "reiniciado" in msg
    f2 = PendingFlows()
    M.complete(Graph(), c, f2, {}, _code(400), _state(f2, c))
    assert C2({"meta": dict(c.get("meta"))}).get("meta")["access_token"] == "EAAlong"   # token persiste nas credenciais


def test_diagnostic_messages_match_request():
    assert M.DIAG["M01"] == "Meta não retornou um código de autorização."
    assert M.DIAG["M04"] == "A solicitação de autorização não corresponde à sessão iniciada."
    assert M.DIAG["M07"] == "O navegador não conseguiu concluir a comunicação com o GPI."
    assert M.DIAG["M08"] == "O código foi recebido, mas não foi possível concluir a autenticação."


def test_assistant_checklist_never_ok_just_because_facebook_screen_appeared(tmp_path):
    from gpi.db import Database
    db = Database(tmp_path / "a.sqlite")
    a = M.assistant(Graph(), creds(), {}, db, 8765)              # app válido, nenhum login concluído
    ck = M.checklist(a, None, started=True)
    assert [r["etapa"] for r in ck] == list(range(1, 11))
    assert all(set(r) >= {"status", "descricao", "resultado", "possivel_causa", "acao"} for r in ck)
    assert ck[0]["status"] == "ok" and ck[7]["status"] != "ok" and ck[9]["status"] != "ok"
    bad = M.checklist(a, {"diagnostico": "M02", "tamanho_codigo": 412}, started=True)
    assert bad[5]["status"] == "falhou" and "412 caracteres" in bad[5]["resultado"] and bad[5]["possivel_causa"]
    rep = M.checklist(a, {"diagnostico": "M09"}, started=True)
    assert rep[6]["status"] == "falhou"
    done = M.assistant(Graph(), creds(access_token="EAAlong"), {}, db, 8765)
    ok = M.checklist(done, {"diagnostico": "OK"}, started=True)
    assert ok[7]["status"] == "ok" and ok[9]["status"] == "ok"   # token conferido + /me respondeu
