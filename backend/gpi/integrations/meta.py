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


# =============================================================================================== v0.8.1
# Diagnóstico das falhas relatadas:
#  B "conexão segura" → o GPI enviava redirect_uri http://127.0.0.1:<porta>/oauth/callback. A Meta aplica "Enforce HTTPS"
#    (obrigatório em apps novos) e só tolera http em "localhost" com o app em modo de desenvolvimento — 127.0.0.1 não.
#  C "domínio não incluído" → o host do redirect precisa estar em Configurações → Básico → Domínios do app; 127.0.0.1 não
#    pode ser cadastrado. Com o retorno HTTPS, o domínio é samuelseveriano.github.io.
#  A "aplicativo inativo" → estado do app no painel (modo desenvolvimento sem a sua conta em Funções, pendências de
#    verificação/política). O GPI não vê esse estado; o assistente orienta a conferência.
#  App ID divergente → as credenciais eram MESCLADAS: ao trocar o App ID, token/permissões/conta do Instagram do app
#    antigo continuavam guardados. Agora um App ID novo limpa tudo o que pertencia ao app anterior.
import re as _re

RELAY_DEFAULT = "https://samuelseveriano.github.io/GPI/oauth/meta/"
LOCAL_RETURN = "/oauth/meta/retorno"
STATE_RX = _re.compile(r"^(\d{4,5})\.([A-Za-z0-9_\-]{32,64})$")
CODE_RX = _re.compile(r"^[A-Za-z0-9_\-.~#]{8,1024}$")
APP_BOUND = ("access_token", "refresh_token", "expires_at", "escopos", "ig_user_id", "conectado_em", "app_id_token")
MODES = {"https_relay": "Retorno HTTPS (GitHub Pages) — recomendado; exige o domínio samuelseveriano.github.io no app",
         "localhost": "http://localhost — aceito pela Meta somente com o app em modo de desenvolvimento"}
ERRORS = [
    (_re.compile(r"insecure|insegur|secure connection|conex[aã]o segura|https", _re.I),
     "A Meta exige retorno HTTPS. Use o modo 'Retorno HTTPS (GitHub Pages)' e cadastre a URL exibida em "
     "Login do Facebook → Configurações → URIs de redirecionamento do OAuth válidos."),
    (_re.compile(r"domain|dom[ií]nio|URL Blocked|redirect_uri", _re.I),
     "Redirect URI não está autorizado pela Meta: cadastre exatamente a URL exibida no GPI nas URIs de redirecionamento e o "
     "domínio dela em Configurações → Básico → Domínios do app."),
    (_re.compile(r"not active|inativ|isn.t available|indispon[ií]vel|app not set up|not setup", _re.I),
     "Aplicativo inativo para esta conta: no painel da Meta, confira se o app está em Desenvolvimento com a sua conta em "
     "Funções do app (Administrador/Desenvolvedor/Testador) ou se está Publicado, e resolva os avisos de 'Ações necessárias'."),
]


def explain(text: str) -> str | None:
    for rx, msg in ERRORS:
        if rx.search(text or ""):
            return msg
    return None


def redirect_uri(cfg: dict, port: int) -> tuple[str, str]:
    mode = cfg.get("meta_redirect_mode") or "https_relay"
    if mode == "localhost":
        return f"http://localhost:{int(port)}/oauth/callback", mode
    return (cfg.get("meta_redirect_uri") or RELAY_DEFAULT).strip(), "https_relay"


def reset_if_app_changed(creds, new_client_id: str | None) -> bool:
    """Um App ID novo invalida tudo que pertencia ao app anterior (token, permissões, conta do Instagram)."""
    if not new_client_id:
        return False
    cur = creds.get("meta")
    old = str(cur.get("client_id") or "").strip()
    if old and old != str(new_client_id).strip():
        keep = {k: v for k, v in cur.items() if k not in APP_BOUND}
        creds.delete("meta")
        creds.set("meta", keep)
        return True
    return False


def start(flows, creds, cfg: dict, port: int, modulo: str = "basico") -> dict:
    c = creds.get("meta")
    cid = str(c.get("client_id") or "").strip()
    if not cid.isdigit():
        raise SourceError("o App ID da Meta é numérico (Configurações → Básico do app)", "restrita")
    if not c.get("client_secret"):
        raise SourceError("informe o App Secret (fica cifrado neste computador)", "restrita")
    if modulo not in MODULES:
        modulo = "basico"
    uri, mode = redirect_uri(cfg, port)
    ver = cfg.get("meta_graph_version", "v23.0")
    rnd, _ = flows.start("meta", {"redirect_uri": uri, "modo": modulo, "https_relay": mode == "https_relay"})
    state = rnd
    if mode == "https_relay":
        state = f"{int(port)}.{rnd}"
        flows.rekey(rnd, state)
    url = authorize_url(c, ver, uri, state, modulo, rerequest=bool(c.get("escopos")))
    return {"url": url, "redirect_uri": uri, "modo": mode, "app_id_enviado": cid, "modulo": modulo}


def complete(http, creds, flows, cfg: dict, code: str, state: str) -> dict:
    if not STATE_RX.match(state or ""):
        raise SourceError("state ausente ou inválido (proteção contra falsificação)", "restrita")
    if not CODE_RX.match(code or ""):
        raise SourceError("código de autorização ausente ou inválido", "restrita")
    f = flows.consume(state)
    if not f or f.get("provider") != "meta":
        raise SourceError("pedido expirado, já utilizado ou desconhecido — inicie a conexão novamente", "restrita")
    ver = cfg.get("meta_graph_version", "v23.0")
    try:
        vals = exchange(http, creds, code, f["redirect_uri"], ver, f.get("modo") or "basico")
    except SourceError as e:
        raise SourceError((explain(str(e)) or "") + f" Detalhe: {str(e)[:200]}", e.kind) from None
    creds.set("meta", {"app_id_token": str(creds.get("meta").get("client_id") or ""), "conectado_em": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return {"ok": True, "escopos": vals.get("escopos", ""), "instagram": bool(creds.get("meta").get("ig_user_id"))}


def parse_pasted(text: str) -> tuple[str, str]:
    t = (text or "").strip()
    part = t.split("#", 1)[1] if "#" in t else (t.split("?", 1)[1] if "?" in t else t)
    q = up.parse_qs(part)
    return (q.get("code") or [""])[0], (q.get("state") or [""])[0]


ASSIST_STATES = {"nao_configurado": "Não configurado", "configurado": "Configurado", "app_valido": "Aplicativo válido",
                 "autenticacao_pendente": "Autenticação pendente", "autenticado": "Autenticado",
                 "permissao_ausente": "Permissão ausente", "permissao_concedida": "Permissão concedida",
                 "app_restrito": "Aplicativo restrito", "endpoint_indisponivel": "Endpoint indisponível",
                 "api_validada": "API validada", "dados_coletados": "Dados coletados"}


def assistant(http, creds, cfg: dict, db, port: int) -> dict:
    """Assistente de conexão em 10 etapas. Cada etapa é verificada de verdade; nada é marcado como pronto por receber token."""
    ver = cfg.get("meta_graph_version", "v23.0")
    c = creds.get("meta")
    uri, mode = redirect_uri(cfg, port)
    host = up.urlsplit(uri).hostname or ""
    steps = []
    estado = "nao_configurado"

    def add(n, nome, ok, msg, acao=None, **kw):
        steps.append({"etapa": n, "nome": nome, "ok": ok, "mensagem": msg, "acao": acao, **kw})

    cid = str(c.get("client_id") or "")
    add(1, "Aplicativo identificado", bool(cid), f"App ID que o GPI enviará: {cid}" if cid else "nenhum App ID informado",
        None if cid else "Informe o App ID (Meta for Developers → app → Configurações → Básico).",
        app_id_enviado=cid or None)
    if not cid or not c.get("client_secret"):
        add(2, "App ID validado", False, "aguardando App ID e App Secret")
        return _assist(steps, estado, uri, mode, c)
    estado = "configurado"
    app = {}
    try:
        app = http.request_json(f"https://graph.facebook.com/{ver}/{up.quote(cid)}?" + up.urlencode(
            {"fields": "id,name,app_domains,privacy_policy_url", "access_token": f"{cid}|{c['client_secret']}"}), ttl=0)
        ok = str(app.get("id")) == cid
        add(2, "App ID validado", ok, f"a Meta reconhece o app '{app.get('name', cid)}'" if ok else "a Meta devolveu outro aplicativo",
            None if ok else "App ID enviado não corresponde ao aplicativo configurado.")
        add(3, "App Secret validado", ok, "App Secret aceito (token de aplicativo emitido)")
        estado = "app_valido" if ok else "configurado"
    except SourceError as e:
        msg = str(e)
        add(2, "App ID validado", False, f"a Meta recusou App ID/App Secret: {msg[:160]}",
            explain(msg) or "Confira App ID e App Secret em Configurações → Básico (o secret é redefinido se você clicar em 'Redefinir').")
        return _assist(steps, estado, uri, mode, c)
    https_ok = uri.startswith("https://") or (mode == "localhost" and host == "localhost")
    add(4, "Redirect URI validado", https_ok, f"{uri} ({MODES[mode]})",
        "Cadastre exatamente esta URL em Login do Facebook → Configurações → URIs de redirecionamento do OAuth válidos.",
        redirect_uri=uri)
    doms = [d.lower() for d in (app.get("app_domains") or [])]
    if doms:
        dom_ok = any(host == d or host.endswith("." + d) for d in doms)
        add(5, "Domínio autorizado", dom_ok, f"domínios do app: {', '.join(doms)}",
            None if dom_ok else f"Adicione '{host}' em Configurações → Básico → Domínios do app.")
    else:
        add(5, "Domínio autorizado", None, "a Meta não informou os domínios do app a este tipo de consulta",
            f"Confira se '{host}' está em Configurações → Básico → Domínios do app.")
    tok = c.get("access_token")
    if not tok:
        estado = "autenticacao_pendente"
        add(6, "Login básico concluído", False, "nenhum login concluído",
            "Clique em 'Conectar — Login básico'. Se a Meta mostrar 'Aplicativo inativo', confira o modo do app e as Funções do app.")
        return _assist(steps, estado, uri, mode, c)
    try:
        r = http.request_json(f"https://graph.facebook.com/{ver}/debug_token?" + up.urlencode(
            {"input_token": tok, "access_token": f"{cid}|{c['client_secret']}"}), ttl=0)
        d = r.get("data") or {}
    except SourceError as e:
        add(6, "Login básico concluído", False, f"não foi possível conferir o token: {str(e)[:160]}")
        return _assist(steps, "autenticacao_pendente", uri, mode, c)
    if str(d.get("app_id") or cid) != cid:
        add(6, "Login básico concluído", False, f"o token guardado pertence a OUTRO aplicativo ({d.get('app_id')})",
            "App ID enviado não corresponde ao aplicativo configurado: conecte de novo (o token antigo será descartado).",
            token_de_outro_app=True)
        return _assist(steps, "autenticacao_pendente", uri, mode, c)
    valid = bool(d.get("is_valid"))
    add(6, "Login básico concluído", valid, "token válido" if valid else "token expirado ou revogado",
        None if valid else "Conecte de novo pelo Login básico.")
    if not valid:
        return _assist(steps, "autenticacao_pendente", uri, mode, c)
    estado = "autenticado"
    scopes = sorted(d.get("scopes") or [])
    creds.set("meta", {"escopos": ",".join(scopes)})
    add(7, "Permissões identificadas", True, ", ".join(scopes) or "nenhuma além do perfil público", escopos=scopes)
    ms = module_status(creds.get("meta"))
    res = []
    for k, m in ms.items():
        if k == "basico":
            continue
        res.append({"modulo": m["nome"], "concedido": m["concedido"], "faltando": m["faltando"], "revisao": m.get("revisao")})
    any_mod = any(x["concedido"] for x in res)
    add(8, "Recursos disponíveis", any_mod, "; ".join(f"{x['modulo']}: {'concedido' if x['concedido'] else 'faltando ' + ', '.join(x['faltando'])}"
                                                     for x in res),
        None if any_mod else "Login autorizado, mas nenhuma permissão de Páginas, Instagram ou Anúncios foi concedida: use o "
                             "'Conectar' de cada módulo. Permissões avançadas exigem revisão do app pela Meta.", modulos=res)
    estado = "permissao_concedida" if any_mod else "permissao_ausente"
    try:
        me = http.request_json(f"https://graph.facebook.com/{ver}/me?" + up.urlencode({"fields": "id,name", "access_token": tok}), ttl=0)
        extra = ""
        if ms["paginas"]["concedido"] or ms["instagram"]["concedido"]:
            acc = http.request_json(f"https://graph.facebook.com/{ver}/me/accounts?" + up.urlencode(
                {"fields": "name,instagram_business_account", "access_token": tok}), ttl=0)
            pages = acc.get("data") or []
            igs = [p["instagram_business_account"]["id"] for p in pages if p.get("instagram_business_account")]
            extra = f"; {len(pages)} página(s) administrada(s); {len(igs)} conta(s) profissional(is) do Instagram"
        add(9, "Consulta real executada", bool(me.get("id")), f"/me respondeu (usuário {me.get('name', me.get('id'))}){extra}")
        estado = "api_validada" if any_mod else estado
    except SourceError as e:
        msg = str(e)
        st = "app_restrito" if "(#10)" in msg or "(#200)" in msg or "permission" in msg.lower() else "endpoint_indisponivel"
        add(9, "Consulta real executada", False, msg[:200], explain(msg) or "Recurso não liberado para este app/conta.")
        return _assist(steps, st, uri, mode, c)
    try:
        n = db.query("SELECT COUNT(*) AS n FROM social_observations WHERE platform IN ('instagram','facebook','meta_ads')")[0]["n"]
    except Exception:  # noqa: BLE001
        n = 0
    add(10, "Dados armazenados", n > 0, f"{n} registro(s) da Meta no banco" if n else "nenhum dado da Meta coletado ainda",
        None if n else "Ative os conectores em Configurações e sincronize.")
    if n:
        estado = "dados_coletados"
    return _assist(steps, estado, uri, mode, c)


def _assist(steps, estado, uri, mode, c) -> dict:
    return {"etapas": steps, "estado": estado, "estado_rotulo": ASSIST_STATES[estado], "redirect_uri": uri, "modo": mode,
            "modos": MODES, "app_id_enviado": c.get("client_id"), "modulos": module_status(c), "bloqueio_conhecido": KNOWN_BLOCK,
            "anuncios": {"paises": "configuráveis (padrão: DE, FR, ES, IT, PT)",
                         "nota": "A API da Biblioteca de Anúncios devolve anúncios comerciais apenas para a União Europeia; anúncios "
                                 "de temas políticos/sociais no Brasil não são comerciais. Dados europeus NÃO representam o mercado "
                                 "brasileiro. ads_read sozinho não garante acesso: exige identidade confirmada."},
            "aviso": "Uma URL de autorização correta não prova que o app tem permissão: cada etapa é verificada na Meta."}
