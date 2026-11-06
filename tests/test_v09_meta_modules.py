"""v0.9 — Meta: app de Login × app de negócios e diagnóstico por módulo. Graph API SIMULADA no formato oficial
(nenhuma credencial real): prova a lógica de diagnóstico, não o acesso real — que depende da configuração e da
revisão do app na Meta."""
from __future__ import annotations

import json
import urllib.parse as up

import pytest

from test_v081_meta import C2

from gpi.connectors.http import SourceError
from gpi.integrations import meta as MT
from gpi.integrations import meta_modules as MM
from gpi.integrations.oauth import PendingFlows

LOGIN, BIZ = "1663502878474287", "2000000000000001"


def creds(biz=True, tok=True, scopes="pages_show_list,pages_read_engagement,instagram_basic"):
    d = {"meta": {"client_id": LOGIN, "client_secret": "s1", "access_token": "EAAlogin", "escopos": "public_profile"}}
    if biz:
        d["meta_negocios"] = {"client_id": BIZ, "client_secret": "s2", **({"access_token": "EAAbiz", "escopos": scopes} if tok else {})}
    return C2(d)


class G:
    def __init__(self, granted=("pages_show_list", "pages_read_engagement", "instagram_basic", "ads_read"), declined=(),
                 pages=({"id": "1", "name": "Minha Loja", "instagram_business_account": {"id": "17841400000000001"}},),
                 hashtag_err=None, ads_err=None, net=False):
        self.granted, self.declined, self.pages, self.hashtag_err, self.ads_err, self.net = granted, declined, pages, hashtag_err, ads_err, net
        self.calls = []

    def request_json(self, url, *a, **k):
        self.calls.append(url)
        q = dict(up.parse_qsl(up.urlsplit(url).query))
        assert q.get("access_token") == "EAAbiz"                      # módulos usam o token do app de negócios
        if self.net:
            raise SourceError("timeout", "rede")
        if "me/permissions" in url:
            return {"data": [{"permission": p, "status": "granted"} for p in self.granted] +
                            [{"permission": p, "status": "declined"} for p in self.declined]}
        if "me/accounts" in url:
            return {"data": list(self.pages)}
        if "recently_searched_hashtags" in url:
            if self.hashtag_err:
                raise SourceError("HTTP 400", "http", status=400, body=json.dumps({"error": self.hashtag_err}))
            return {"data": []}
        if "ads_archive" in url:
            if self.ads_err:
                raise SourceError("HTTP 400", "http", status=400, body=json.dumps({"error": self.ads_err}))
            return {"data": [{"id": "9"}]}
        if "17841400000000001" in url:
            return {"id": "17841400000000001", "username": "minhaloja"}
        raise AssertionError(url)


def test_login_app_alone_explains_invalid_scopes_without_calling_meta():
    c = creds(biz=False)
    g = G()
    r = MM.diagnose(g, c, {})["modulos"]
    for m in ("paginas", "instagram", "anuncios"):
        assert r[m]["estado"] == "configuracao_incompleta" and r[m]["app"] == "login"
        assert "Invalid Scopes" in r[m]["pendencias"][0] and "app de negócios" in r[m]["acao"]
    assert g.calls == []                                               # não pede o que a Meta vai recusar


def test_basic_login_always_stays_on_login_app():
    c = creds()
    assert MT.app_key(c, "basico") == "meta" and MT.app_key(c, "paginas") == "meta_negocios"
    f = PendingFlows()
    b = MT.start(f, c, {}, 8765, "basico")
    p = MT.start(f, c, {}, 8765, "paginas")
    assert up.parse_qs(up.urlsplit(b["url"]).query)["client_id"] == [LOGIN]
    assert up.parse_qs(up.urlsplit(p["url"]).query)["client_id"] == [BIZ]
    assert up.parse_qs(up.urlsplit(p["url"]).query)["scope"] == ["pages_show_list,pages_read_engagement"]


def test_business_app_without_token_is_incomplete():
    r = MM.diagnose(G(), creds(tok=False), {})["modulos"]["paginas"]
    assert r["estado"] == "configuracao_incompleta" and "Conectar" in r["acao"]


def test_declined_vs_not_in_use_case():
    r = MM.diagnose(G(granted=("pages_show_list",), declined=("pages_read_engagement",)), creds(), {})["modulos"]["paginas"]
    assert r["estado"] == "sem_permissao" and "recusou" in r["acao"]
    r2 = MM.diagnose(G(granted=("pages_show_list",)), creds(), {})["modulos"]["paginas"]
    assert r2["estado"] == "sem_permissao" and "caso de uso" in r2["acao"]


def test_pages_connected_only_with_real_query_and_managed_pages():
    r = MM.diagnose(G(), creds(), {})["modulos"]["paginas"]
    assert r["estado"] == "conectado" and r["conta_ou_pagina"] == "Minha Loja" and r["consulta_real"]["ok"]
    assert "terceiros" in r["observacao"]
    r2 = MM.diagnose(G(pages=()), creds(), {})["modulos"]["paginas"]
    assert r2["estado"] == "configuracao_incompleta" and "sem Página" in r2["pendencias"][0]


def test_instagram_numeric_id_and_public_content_access():
    c = creds()
    r = MM.diagnose(G(), c, {})["modulos"]["instagram"]
    assert r["estado"] == "conectado" and "17841400000000001" in r["conta_ou_pagina"] and "@minhaloja" in r["conta_ou_pagina"]
    assert c.get("meta_negocios")["ig_user_id"] == "17841400000000001"       # ID numérico, não o @nome
    no = MM.diagnose(G(pages=({"id": "1", "name": "P"},)), creds(), {})["modulos"]["instagram"]
    assert no["estado"] == "configuracao_incompleta" and "vinculad" in no["pendencias"][0]
    ap = MM.diagnose(G(hashtag_err={"code": 10, "message": "Application does not have permission for this action"}), creds(), {})
    ig = ap["modulos"]["instagram"]
    assert ig["estado"] == "aprovacao_necessaria" and "Public Content Access" in ig["acao"]
    assert ig["erro_oficial"]["code"] == 10 and "permission" in ig["erro_oficial"]["mensagem"]


def test_ads_library_states():
    ok = MM.diagnose(G(), creds(), {})["modulos"]["anuncios"]
    assert ok["estado"] == "conectado" and "não são evidência do mercado brasileiro" in ok["observacao"]
    ap = MM.diagnose(G(ads_err={"code": 10, "error_subcode": 2332002, "message": "Application does not have permission"}), creds(), {})
    assert ap["modulos"]["anuncios"]["estado"] == "aprovacao_necessaria" and "identidade" in ap["modulos"]["anuncios"]["acao"]
    lim = MM.diagnose(G(ads_err={"code": 4, "message": "Application request limit reached"}), creds(), {})
    assert lim["modulos"]["anuncios"]["estado"] == "limite"
    bad = MM.diagnose(G(ads_err={"code": 100, "message": "Unsupported get request"}), creds(), {})
    assert bad["modulos"]["anuncios"]["estado"] == "nao_suportado"


def test_network_error_is_not_reported_as_permission():
    r = MM.diagnose(G(net=True), creds(), {})["modulos"]["paginas"]
    assert r["estado"] == "erro_rede" and r["estado_rotulo"] == "Erro de rede"


def test_changing_business_app_keeps_login_token():
    c = creds()
    assert MT.reset_if_app_changed(c, "2000000000000002", "meta_negocios")
    assert not c.get("meta_negocios").get("access_token") and c.get("meta")["access_token"] == "EAAlogin"


@pytest.mark.parametrize("estado", list(MM.STATES))
def test_every_state_has_a_label(estado):
    assert MM.STATES[estado]
