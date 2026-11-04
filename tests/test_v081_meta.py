"""v0.8.1 — OAuth da Meta: redirect HTTPS (GitHub Pages) × localhost, App ID trocado, state de uso único, assistente de
10 etapas e mensagens para os erros relatados. Respostas da Graph API SIMULADAS no formato oficial (sem credenciais reais)."""
from __future__ import annotations

import re
import urllib.parse as up

import pytest

from test_v05 import Creds

from gpi.connectors.http import SourceError
from gpi.integrations import meta as M
from gpi.integrations.oauth import PendingFlows


class C2(Creds):
    def delete(self, k):
        self.d.pop(k, None)


def creds(**kw):
    return C2({"meta": {"client_id": "1663502878474287", "client_secret": "s3cr3t", **kw}})


def test_redirect_is_https_relay_by_default_never_127():
    uri, mode = M.redirect_uri({}, 8765)
    assert uri.startswith("https://") and "127.0.0.1" not in uri and mode == "https_relay"
    uri2, mode2 = M.redirect_uri({"meta_redirect_mode": "localhost"}, 8765)
    assert uri2 == "http://localhost:8765/oauth/callback" and mode2 == "localhost"


def test_start_sends_configured_app_id_and_relay_state():
    c, f = creds(), PendingFlows()
    r = M.start(f, c, {}, 8765, "basico")
    q = up.parse_qs(up.urlsplit(r["url"]).query)
    assert q["client_id"] == ["1663502878474287"] and r["app_id_enviado"] == "1663502878474287"
    assert q["redirect_uri"] == [M.RELAY_DEFAULT] and q["scope"] == ["public_profile"]
    assert re.match(r"^8765\.[A-Za-z0-9_\-]{32,64}$", q["state"][0])
    with pytest.raises(SourceError):
        M.start(f, Creds({"meta": {"client_id": "abc", "client_secret": "x"}}), {}, 8765)


def test_changing_app_id_discards_previous_app_tokens():
    c = creds(access_token="EAAold", escopos="public_profile,pages_show_list", ig_user_id="178")
    c.d["meta"]["client_id"] = "1855094518955679"              # credenciais antigas de outro app
    assert M.reset_if_app_changed(c, "1663502878474287")
    left = c.get("meta")
    assert not left.get("access_token") and not left.get("escopos") and not left.get("ig_user_id")
    assert left.get("client_secret") == "s3cr3t"                   # o secret não é apagado (o usuário pode atualizá-lo)
    c.set("meta", {"client_id": "1663502878474287"})
    assert not M.reset_if_app_changed(c, "1663502878474287")           # mesmo App ID: nada é apagado


class Graph:
    """Graph API simulada: troca de código, token longo, debug_token, /me, /me/accounts, app."""

    def __init__(self, app_id="1663502878474287", token_app=None, fail=None):
        self.app_id, self.token_app, self.fail, self.calls = app_id, token_app or app_id, fail, []

    def request_json(self, url, *a, **k):
        self.calls.append(url)
        if self.fail and self.fail in url:
            raise SourceError("(#10) Application does not have permission for this action", "http", status=400)
        if "oauth/access_token" in url:
            return {"access_token": "EAAshort" if "code=" in url else "EAAlong", "expires_in": 5183944}
        if "debug_token" in url:
            return {"data": {"is_valid": True, "app_id": self.token_app, "scopes": ["public_profile", "pages_show_list"]}}
        if "/me/accounts" in url:
            return {"data": [{"name": "Loja", "id": "1"}]}
        if "/me?" in url:
            return {"id": "99", "name": "Teste"}
        if f"/{self.app_id}?" in url:
            return {"id": self.app_id, "name": "GPI", "app_domains": ["samuelseveriano.github.io"]}
        return {}


def test_complete_relay_flow_validates_state_once():
    c, f, g = creds(), PendingFlows(), Graph()
    r = M.start(f, c, {}, 8765)
    state = up.parse_qs(up.urlsplit(r["url"]).query)["state"][0]
    out = M.complete(g, c, f, {}, "AQBcode12345", state)
    assert out["ok"] and c.get("meta")["access_token"] == "EAAlong" and c.get("meta")["app_id_token"] == "1663502878474287"
    tok_ex = [u for u in g.calls if "oauth/access_token" in u][0]
    assert up.parse_qs(up.urlsplit(tok_ex).query)["redirect_uri"] == [M.RELAY_DEFAULT]   # mesma URI do pedido
    with pytest.raises(SourceError):                                       # replay do mesmo state
        M.complete(g, c, f, {}, "AQBcode12345", state)
    with pytest.raises(SourceError):
        M.complete(g, c, f, {}, "AQBcode12345", "8765.forjado")


def test_assistant_ten_steps_and_token_from_other_app():
    from gpi.db import Database
    import tempfile, pathlib
    db = Database(pathlib.Path(tempfile.mkdtemp()) / "a.sqlite")
    c = creds(access_token="EAAlong")
    a = M.assistant(Graph(), c, {}, db, 8765)
    names = [s["nome"] for s in a["etapas"]]
    assert names[:5] == ["Aplicativo identificado", "App ID validado", "App Secret validado", "Redirect URI validado", "Domínio autorizado"]
    assert len(a["etapas"]) == 10 and a["estado"] == "permissao_ausente"            # token recebido ≠ API funcional
    assert a["etapas"][7]["ok"] is False and "Páginas" in a["etapas"][7]["mensagem"]
    assert a["etapas"][4]["ok"] is True and a["etapas"][9]["ok"] is False          # domínio ok; nenhum dado coletado ainda
    assert "1663502878474287" in a["etapas"][0]["mensagem"]
    b = M.assistant(Graph(token_app="1855094518955679"), creds(access_token="EAAold"), {}, db, 8765)
    step6 = next(s for s in b["etapas"] if s["etapa"] == 6)
    assert step6["ok"] is False and step6.get("token_de_outro_app") and "não corresponde" in step6["acao"]
    d = M.assistant(Graph(fail="/me?"), c, {}, db, 8765)
    assert d["estado"] == "app_restrito"
    e = M.assistant(Graph(), C2({"meta": {}}), {}, db, 8765)
    assert e["estado"] == "nao_configurado" and not "s3cr3t" in str(e)


def test_reported_errors_get_actionable_messages():
    assert "HTTPS" in M.explain("Insecure Login Blocked: You can't get an access token from an insecure page")
    assert "Domínios do app" in M.explain("Não é possível carregar o URL: o domínio dessa URL não está incluído nos domínios do app")
    assert "Funções do app" in M.explain("App not active: This app is not currently accessible")


def test_api_routes_and_secret_never_returned(tmp_path):
    from test_api_integration import Srv
    s = Srv(tmp_path / "data")
    try:
        code, r = s.req("/api/integrations/meta/credentials", {"client_id": "1663502878474287", "client_secret": "s3cr3t"})
        assert code == 200
        code, st = s.req("/api/integrations/meta/oauth/start", {"modulo": "basico"})
        assert code == 200 and st["redirect_uri"] == M.RELAY_DEFAULT and "s3cr3t" not in str(st)
        code, r = s.req("/api/integrations/meta/redirect", {"modo": "localhost"})
        assert r["redirect_uri"] == f"http://localhost:{s.port}/oauth/callback"
        code, r = s.req("/api/integrations/meta/credentials", {"client_id": "abc"})
        assert code == 400
        code, r = s.req("/api/oauth/meta/concluir", {"code": "AQBcode12345", "state": "8765." + "a" * 40})
        assert code == 400 and "expirado" in r["erro"]
        code, html = s.req("/oauth/meta/retorno", raw=True)
        assert code == 200 and b"oauth_meta_retorno.js" in (html if isinstance(html, bytes) else html.encode())
    finally:
        s.stop()
