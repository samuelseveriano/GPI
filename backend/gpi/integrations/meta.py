"""
Autenticação Meta em módulos independentes (v0.6.1).

Problema relatado: ao conectar, o Facebook exibia "Recurso indisponível. Como estamos atualizando detalhes
adicionais para esse aplicativo, o Login do Facebook está indisponível no momento." Essa tela é mostrada pela
própria Meta, ANTES de qualquer retorno ao GPI: o bloqueio está na configuração/estado do aplicativo no painel
da Meta, não no código do GPI. O GPI não pode (nem deve) contornar. O que mudou aqui:

* Cada módulo pede só as permissões dele (antes eram 5 de uma vez): login básico, Páginas, Instagram e
  Biblioteca de Anúncios. Permissões já concedidas são preservadas; um módulo novo usa auth_type=rerequest.
  Reduzir permissões NÃO garante que o bloqueio desapareça.
* Verificação do aplicativo (App ID + App Secret) sem login de usuário e, após o login, conferência das
  permissões realmente concedidas (debug_token).
* Erros devolvidos no redirecionamento (error, error_reason, error_description, error_code) viram mensagens claras.
"""
from __future__ import annotations

import time
import urllib.parse as up

from ..connectors.http import SourceError

MODULES = {
    "basico": {"nome": "Login básico", "escopos": ["public_profile"],
               "uso": "Valida o aplicativo e a conta. Não dá acesso a dados de Páginas, Instagram ou anúncios."},
    "paginas": {"nome": "Páginas do Facebook", "escopos": ["pages_show_list", "pages_read_engagement"],
                "uso": "Publicações e engajamento das páginas indicadas em Configurações.",
                "revisao": "pages_read_engagement exige revisão do app para usuários que não são administradores/testadores; "
                           "páginas de terceiros exigem o recurso Page Public Content Access."},
    "instagram": {"nome": "Instagram (hashtags)", "escopos": ["instagram_basic", "pages_show_list"],
                  "uso": "Hashtags de produtos (top/recent media) na conta profissional vinculada a uma Página.",
                  "revisao": "Exige o recurso Instagram Public Content Access aprovado na revisão do app."},
    "anuncios": {"nome": "Biblioteca de Anúncios", "escopos": ["ads_read"],
                 "uso": "Contagem de anúncios ativos (somente anúncios comerciais da União Europeia).",
                 "revisao": "Exige confirmação de identidade da pessoa na Meta e acesso à API da Biblioteca de Anúncios."},
}
CONNECTOR_MODULE = {"instagram": "instagram", "facebook": "paginas", "meta_ads": "anuncios"}
KNOWN_BLOCK = {
    "texto": "Recurso indisponível — o Login do Facebook está indisponível para este aplicativo",
    "causa": "Mensagem exibida pela Meta quando o aplicativo tem pendências de configuração ou de revisão. O GPI não "
             "consegue ver o estado interno do app; confira no painel da Meta:",
    "etapas": [
        "developers.facebook.com → Meus apps → o app → Painel: resolva os avisos de 'Ações necessárias' (ex.: Verificação "
        "de uso de dados, verificação da empresa, política de privacidade).",
        "Casos de uso → 'Autenticar e solicitar dados de usuários com o Login do Facebook' adicionado e configurado.",
        "Login do Facebook → Configurações: 'URIs de redirecionamento do OAuth válidos' contém exatamente a URL exibida no GPI.",
        "Modo do app: em Desenvolvimento, só administradores, desenvolvedores e testadores do app conseguem entrar — "
        "adicione sua conta em Funções do app; para outros usuários o app precisa estar Publicado (Live).",
        "Configurações → Básico: URL da política de privacidade e categoria preenchidas (obrigatórias para publicar).",
        "Permissões além de public_profile podem exigir revisão do app (App Review) antes de funcionar para não testadores.",
    ],
}


def authorize_url(c: dict, ver: str, redirect_uri: str, state: str, modulo: str = "basico", rerequest: bool = False) -> str:
    if modulo not in MODULES:
        raise SourceError("módulo Meta desconhecido", "restrita")
    q = {"client_id": c.get("client_id", ""), "redirect_uri": redirect_uri, "state": state, "response_type": "code",
         "scope": ",".join(MODULES[modulo]["escopos"])}
    if rerequest:
        q["auth_type"] = "rerequest"
    return f"https://www.facebook.com/{ver}/dialog/oauth?" + up.urlencode(q)


def callback_error(q) -> str | None:
    """Mensagem para erros devolvidos pela Meta no redirecionamento."""
    if not (q.get("error") or q.get("error_code") or q.get("error_message")):
        return None
    reason = q.get("error_reason") or ""
    desc = q.get("error_description") or q.get("error_message") or q.get("error") or ""
    if reason == "user_denied":
        return "Você recusou a autorização na tela da Meta. Nenhuma permissão foi concedida."
    return f"A Meta recusou o login: {desc[:200]}" + (f" (código {q.get('error_code')})" if q.get("error_code") else "") + \
        ". " + KNOWN_BLOCK["causa"] + " " + " ".join(f"{i + 1}) {e}" for i, e in enumerate(KNOWN_BLOCK["etapas"]))


def granted_scopes(http, c: dict, ver: str, token: str) -> dict:
    """debug_token com o token do app (App ID|App Secret): validade e permissões concedidas."""
    app = f"{c.get('client_id')}|{c.get('client_secret')}"
    r = http.request_json(f"https://graph.facebook.com/{ver}/debug_token?" + up.urlencode({"input_token": token, "access_token": app}), ttl=0)
    d = r.get("data") or {}
    return {"valido": bool(d.get("is_valid")), "escopos": sorted(d.get("scopes") or []), "expira_em": d.get("expires_at")}


def exchange(http, creds, code: str, redirect_uri: str, ver: str, modulo: str = "basico") -> dict:
    """Código → token curto → token de longo prazo (~60 dias) → permissões concedidas → conta do Instagram (se aplicável)."""
    c = creds.get("meta")
    g = f"https://graph.facebook.com/{ver}/"
    r = http.request_json(g + "oauth/access_token?" + up.urlencode({"client_id": c.get("client_id"), "redirect_uri": redirect_uri,
                                                                      "client_secret": c.get("client_secret"), "code": code}), ttl=0)
    if not r.get("access_token"):
        raise SourceError(f"Meta não emitiu token: {(r.get('error') or {}).get('message', r)}", "restrita")
    ll = http.request_json(g + "oauth/access_token?" + up.urlencode({"grant_type": "fb_exchange_token", "client_id": c.get("client_id"),
                                                                       "client_secret": c.get("client_secret"),
                                                                       "fb_exchange_token": r["access_token"]}), ttl=0)
    tok = ll.get("access_token") or r["access_token"]
    vals = {"access_token": tok, "expires_at": str(time.time() + float(ll.get("expires_in", r.get("expires_in", 3600))))}
    try:
        gs = granted_scopes(http, c, ver, tok)
        vals["escopos"] = ",".join(gs["escopos"])
    except SourceError:
        pass
    if modulo == "instagram" or "instagram_basic" in vals.get("escopos", ""):
        try:
            acc = http.request_json(g + "me/accounts?" + up.urlencode({"fields": "name,instagram_business_account", "access_token": tok}), ttl=0)
            ig = next((a["instagram_business_account"]["id"] for a in acc.get("data", []) if a.get("instagram_business_account")), None)
            if ig and not c.get("ig_user_id"):
                vals["ig_user_id"] = ig
        except SourceError:
            pass
    creds.set("meta", vals)
    return vals


def module_status(c: dict) -> dict:
    granted = set(filter(None, (c.get("escopos") or "").split(",")))
    out = {}
    for k, m in MODULES.items():
        need = set(m["escopos"])
        out[k] = {"nome": m["nome"], "escopos": m["escopos"], "uso": m["uso"], "revisao": m.get("revisao"),
                  "concedido": bool(c.get("access_token")) and need <= granted,
                  "faltando": sorted(need - granted) if c.get("access_token") else sorted(need)}
    return out


def module_ok(c: dict, connector_id: str) -> bool:
    """Tokens antigos (sem registro de permissões) continuam valendo; com registro, exige as permissões do módulo."""
    if not c.get("access_token"):
        return False
    if not c.get("escopos"):
        return True
    return set(MODULES[CONNECTOR_MODULE[connector_id]]["escopos"]) <= set(c["escopos"].split(","))


def diagnose(http, creds, cfg: dict) -> dict:
    ver = cfg.get("meta_graph_version", "v23.0")
    c = creds.get("meta")
    steps = []

    def add(nome, ok, msg, **kw):
        steps.append({"etapa": nome, "ok": ok, "mensagem": msg, **kw})
    if not (c.get("client_id") and c.get("client_secret")):
        add("Aplicativo", False, "informe App ID e App Secret")
        return {"etapas": steps, "estado": "nao_configurado", "modulos": module_status(c), "bloqueio_conhecido": KNOWN_BLOCK}
    try:
        app = http.request_json(f"https://graph.facebook.com/{ver}/{up.quote(c['client_id'])}?" + up.urlencode(
            {"fields": "id,name", "access_token": f"{c['client_id']}|{c['client_secret']}"}), ttl=0)
        add("Aplicativo", bool(app.get("id")), f"App ID e App Secret válidos ({app.get('name', app.get('id'))})")
    except SourceError as e:
        add("Aplicativo", False, f"a Meta recusou App ID/App Secret: {e}", acao="Confira os dados em Configurações → Básico do app.")
        return {"etapas": steps, "estado": "erro", "modulos": module_status(c), "bloqueio_conhecido": KNOWN_BLOCK}
    if not c.get("access_token"):
        add("Login", False, "nenhum login concluído", acao="Use 'Conectar' do módulo Login básico. Se a Meta mostrar "
            "'Recurso indisponível', siga a lista de verificação abaixo.")
        return {"etapas": steps, "estado": "configurado", "modulos": module_status(c), "bloqueio_conhecido": KNOWN_BLOCK}
    try:
        gs = granted_scopes(http, c, ver, c["access_token"])
        creds.set("meta", {"escopos": ",".join(gs["escopos"])})
        c = creds.get("meta")
        add("Login", gs["valido"], "token válido" if gs["valido"] else "token expirado ou revogado — conecte de novo",
            escopos=gs["escopos"])
    except SourceError as e:
        add("Login", False, f"não foi possível conferir o token: {e}")
        return {"etapas": steps, "estado": "erro", "modulos": module_status(c), "bloqueio_conhecido": KNOWN_BLOCK}
    ms = module_status(c)
    for k, m in ms.items():
        if k == "basico":
            continue
        add(f"Permissões — {m['nome']}", m["concedido"], "concedidas" if m["concedido"] else f"faltando: {', '.join(m['faltando'])}",
            acao=None if m["concedido"] else (m.get("revisao") or "Use 'Conectar' deste módulo."))
    if ms["instagram"]["concedido"]:
        add("Instagram — conta profissional", bool(c.get("ig_user_id")), "conta vinculada encontrada" if c.get("ig_user_id")
            else "nenhuma conta profissional do Instagram vinculada às suas Páginas")
    any_mod = any(m["concedido"] for k, m in ms.items() if k != "basico")
    return {"etapas": steps, "estado": "autorizado" if any_mod else "autenticado",
            "modulos": ms, "bloqueio_conhecido": KNOWN_BLOCK}
