"""Mercado Livre — OAuth 2.0 Authorization Code + PKCE S256 com Redirect URI HTTPS (v0.7).

Documentação oficial consultada em 03/11/2026:
* Autenticação e autorização: https://developers.mercadolivre.com.br/en_us/authentication-and-authorization
  - fluxo documentado: somente Authorization Code (server side); grant_type aceitos: authorization_code e
    refresh_token (não há Device Authorization Grant nem client_credentials documentados);
  - redirect_uri: "has to match exactly" o cadastrado e deve ser estático (dados extras vão no ``state``);
  - PKCE opcional por aplicação (S256 recomendado); com PKCE ativo, code_challenge/code_verifier obrigatórios;
  - access token válido por 6 h (o exemplo da página mostra expires_in=10800 — usamos o valor devolvido);
  - refresh token de USO ÚNICO, válido por 6 meses: cada renovação devolve um novo, que precisa ser gravado.
* Cadastro da aplicação: "it is mandatory to use the HTTPS protocol in its redirection URI"
  (https://developers.mercadolibre.com.uy/en_us/register-your-application).

Por isso o endereço http://127.0.0.1:8765/oauth/callback não serve. Arquitetura adotada:

  GPI (local) ──abre navegador──▶ auth.mercadolivre.com.br/authorization?redirect_uri=<HTTPS>&state=<porta.aleatório>
       ▲                                                      │ login do usuário (o GPI não vê a senha)
       │ POST /api/oauth/mercadolivre/concluir                ▼
       │ (mesma origem, cabeçalho X-GPI)          página estática HTTPS (GitHub Pages, sem segredos)
       └── página local /oauth/mercadolivre/retorno ◀── navegação para http://127.0.0.1:<porta>/…#code=…&state=…

* A página HTTPS não guarda nada, não chama APIs e só navega para 127.0.0.1 numa porta numérica extraída do
  ``state`` (não é redirecionador aberto). O código vai no fragmento (#), que não é enviado em requisições HTTP
  nem aparece em logs de servidor; a página local o lê e o remove do histórico.
* O code_verifier (PKCE) e o client_secret nunca saem do GPI: um código interceptado não pode ser trocado por
  token. ``state`` aleatório de 256 bits, uso único, expira em 10 min (CSRF/reutilização).
* Alternativa sem navegação para 127.0.0.1 (ex.: navegador corporativo que bloqueia): a página HTTPS mostra o
  código para copiar e colar no GPI (mesma validação de state + PKCE).
"""
from __future__ import annotations

import re
import threading
import time
import urllib.parse

from ..connectors.http import SourceError
from .oauth import authorize_url

AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
API = "https://api.mercadolibre.com"
DEFAULT_REDIRECT = "https://samuelseveriano.github.io/GPI/oauth/mercadolivre/"
DOCS = "https://developers.mercadolivre.com.br/en_us/authentication-and-authorization"
LOCAL_RETURN = "/oauth/mercadolivre/retorno"

STATE_RX = re.compile(r"^(\d{4,5})\.([A-Za-z0-9_\-]{32,64})$")
CODE_RX = re.compile(r"^[A-Za-z0-9_\-.~]{8,300}$")
_refresh_lock = threading.Lock()


def redirect_problem(uri: str) -> str | None:
    """Valida o Redirect URI HTTPS cadastrado no DevCenter."""
    try:
        p = urllib.parse.urlsplit(uri or "")
    except ValueError:
        return "Redirect URI inválido"
    if p.scheme != "https":
        return "o Mercado Livre exige HTTPS no Redirect URI"
    if not p.hostname or p.hostname in ("localhost", "127.0.0.1", "::1"):
        return "use um domínio HTTPS público (ex.: GitHub Pages); 127.0.0.1/localhost não são aceitos"
    if p.query or p.fragment:
        return "o Redirect URI deve ser estático (sem ?parâmetros ou #fragmento)"
    if p.username or p.password:
        return "o Redirect URI não pode conter credenciais"
    return None


def redirect_uri(cfg: dict) -> str:
    return (cfg.get("ml_redirect_uri") or DEFAULT_REDIRECT).strip()


def make_state(port: int, rnd: str) -> str:
    return f"{int(port)}.{rnd}"


def start(flows, creds, cfg: dict, port: int) -> dict:
    """Prepara a URL de autorização. O state leva a porta local (para a página HTTPS voltar ao GPI)."""
    c = creds.get("mercadolivre")
    cid = str(c.get("client_id") or "").strip()
    if not cid:
        raise SourceError("informe o App ID (client_id) do Mercado Livre", "restrita")
    if not cid.isdigit():
        raise SourceError("o App ID do Mercado Livre é numérico (DevCenter → Minhas aplicações)", "restrita")
    if not c.get("client_secret"):
        raise SourceError("informe a Secret Key da aplicação (fica cifrada no computador)", "restrita")
    uri = redirect_uri(cfg)
    prob = redirect_problem(uri)
    if prob:
        raise SourceError(prob, "restrita")
    rnd, verifier = flows.start("mercadolivre", {"redirect_uri": uri, "https_relay": True})
    # PendingFlows indexa pelo valor aleatório; o state público acrescenta a porta
    state = make_state(port, rnd)
    flows.rekey(rnd, state)
    return {"url": authorize_url(AUTH_URL, cid, uri, state, verifier), "state": state, "redirect_uri": uri}


def parse_pasted(text: str) -> tuple[str, str]:
    """Aceita o código + state colados manualmente, ou a URL completa do retorno (query ou fragmento)."""
    t = (text or "").strip()
    if "code=" in t:
        part = t.split("#", 1)[1] if "#" in t and "code=" in t.split("#", 1)[1] else (t.split("?", 1)[1] if "?" in t else t)
        q = urllib.parse.parse_qs(part)
        return (q.get("code") or [""])[0], (q.get("state") or [""])[0]
    return t, ""


def complete(http, creds, flows, code: str, state: str) -> dict:
    """Troca o código pelo token (com code_verifier e client_secret locais) e valida com /users/me."""
    if not STATE_RX.match(state or ""):
        raise SourceError("state ausente ou em formato inválido (proteção contra falsificação)", "restrita")
    if not CODE_RX.match(code or ""):
        raise SourceError("código de autorização ausente ou inválido", "restrita")
    f = flows.consume(state)
    if not f or f.get("provider") != "mercadolivre":
        raise SourceError("pedido expirado, já utilizado ou desconhecido — inicie a conexão novamente", "restrita")
    c = creds.get("mercadolivre")
    form = {"grant_type": "authorization_code", "client_id": c.get("client_id", ""),
            "client_secret": c.get("client_secret", ""), "code": code, "redirect_uri": f["redirect_uri"],
            "code_verifier": f["verifier"]}
    try:
        r = http.request_json(TOKEN_URL, "POST", form=form, ttl=0)
    except SourceError as e:
        raise SourceError(explain(e), e.kind, status=e.status, body=e.body) from None
    store(creds, r)
    me = users_me(http, creds)
    return {"ok": True, "user_id": me.get("id"), "apelido": me.get("nickname"), "pais": me.get("site_id")}


def store(creds, r: dict):
    if not isinstance(r, dict) or not r.get("access_token"):
        raise SourceError(f"Mercado Livre não emitiu token: {(r or {}).get('message') or (r or {}).get('error')}", "restrita")
    creds.set("mercadolivre", {"access_token": r["access_token"],
                               # refresh token de uso único: grava SEMPRE o novo (set ignora None → mantém o atual)
                               "refresh_token": r.get("refresh_token"),
                               "expires_at": str(time.time() + float(r.get("expires_in") or 21600)),
                               "user_id": str(r.get("user_id") or ""), "conectado_em": time.strftime("%Y-%m-%dT%H:%M:%S")})


def token(http, creds) -> str:
    """Access token válido, renovando uma única vez por vez (refresh token é de uso único)."""
    c = creds.get("mercadolivre")
    if not c.get("access_token"):
        raise SourceError("Mercado Livre não conectado: use 'Conectar' na Central de Integrações", "restrita")
    if float(c.get("expires_at", 0)) > time.time() + 120:
        return c["access_token"]
    with _refresh_lock:
        c = creds.get("mercadolivre")                       # outra thread pode ter renovado enquanto esperávamos
        if float(c.get("expires_at", 0)) > time.time() + 120:
            return c["access_token"]
        if not c.get("refresh_token"):
            raise SourceError("token do Mercado Livre expirado; conecte novamente", "restrita")
        try:
            r = http.request_json(TOKEN_URL, "POST", ttl=0, form={
                "grant_type": "refresh_token", "client_id": c.get("client_id", ""),
                "client_secret": c.get("client_secret", ""), "refresh_token": c["refresh_token"]})
        except SourceError as e:
            if e.status in (400, 401) and "invalid_grant" in ((e.body or "") + str(e)):
                creds.set("mercadolivre", {"precisa_reconectar": "1"})
                raise SourceError("autorização do Mercado Livre expirada ou revogada (refresh token de uso único já "
                                  "utilizado, mais de 6 meses, troca de senha ou revogação) — conecte novamente",
                                  "restrita", status=e.status) from None
            raise SourceError(explain(e), e.kind, retryable=e.retryable, status=e.status, body=e.body) from None
        store(creds, r)
        return r["access_token"]


def users_me(http, creds) -> dict:
    tok = token(http, creds)
    try:
        return http.request_json(f"{API}/users/me", headers={"Authorization": f"Bearer {tok}"}, ttl=0)
    except SourceError as e:
        raise SourceError(explain(e), e.kind, status=e.status, body=e.body) from None


def explain(e: SourceError) -> str:
    """Mensagens claras para os erros documentados e para o bloqueio do CloudFront."""
    txt = f"{e} {e.body or ''}".lower()
    if e.status == 403 and ("cloudfront" in txt or "request blocked" in txt):
        return ("Bloqueio na borda do Mercado Livre (CloudFront 403 — 'Request blocked'): a requisição foi recusada "
                "antes de chegar à API. Causas comuns: Redirect URI http/127.0.0.1 na autorização, rede/VPN/proxy "
                "corporativo com IP bloqueado ou filtro do WAF. O GPI não contorna esse bloqueio; teste em outra rede "
                "e, se persistir, abra chamado no suporte do DevCenter informando data/hora e o ID da requisição "
                "CloudFront exibido na página de erro.")
    for k, msg in (("invalid_client", "App ID ou Secret Key inválidos"),
                   ("invalid_grant", "código expirado/já utilizado, ou redirect_uri/client_id diferentes do pedido "
                                     "original — inicie a conexão novamente"),
                   ("invalid_scope", "escopo inválido (use read/offline_access na aplicação)"),
                   ("unsupported_grant_type", "tipo de concessão não suportado"),
                   ("local_rate_limited", "limite temporário de requisições — tente em alguns segundos")):
        if k in txt:
            return f"Mercado Livre: {msg}."
    if e.status == 403:
        return "Mercado Livre: acesso negado (token de outro usuário, conta sem acesso ao domínio do país ou app sem permissão)."
    return str(e)


def diagnose(http, creds, cfg: dict) -> dict:
    """Etapas verificáveis sem expor segredos. Distingue configuração local de consultas reais."""
    c = creds.get("mercadolivre")
    uri = redirect_uri(cfg)
    etapas = []

    def add(nome, ok, detalhe, real=False):
        etapas.append({"etapa": nome, "ok": bool(ok), "mensagem": detalhe, "consulta_real": real})
        return ok

    add("App ID", str(c.get("client_id") or "").isdigit(), "numérico" if str(c.get("client_id") or "").isdigit()
        else "ausente ou não numérico")
    add("Secret Key", bool(c.get("client_secret")), "configurada (cifrada)" if c.get("client_secret") else "ausente")
    prob = redirect_problem(uri)
    add("Redirect URI HTTPS", not prob, prob or f"{uri} — deve ser idêntico ao cadastrado no DevCenter")
    if not c.get("access_token"):
        configurado = all(e["ok"] for e in etapas)
        add("Autorização", False, "ainda não conectado (clique em Conectar)")
        return {"estado": "configurado" if configurado else "incompleto", "etapas": etapas}
    try:
        me = users_me(http, creds)
        add("Token + /users/me", True, f"usuário {me.get('nickname') or me.get('id')} ({me.get('site_id')})", real=True)
    except SourceError as e:
        add("Token + /users/me", False, str(e), real=True)
        return {"estado": "erro", "etapas": etapas}
    try:
        tok = token(http, creds)
        t = http.request_json(f"{API}/trends/MLB", headers={"Authorization": f"Bearer {tok}"}, ttl=0)
        n = len(t) if isinstance(t, list) else 0
        add("Tendências /trends/MLB", n > 0, f"{n} termos devolvidos", real=True)
    except SourceError as e:
        add("Tendências /trends/MLB", False, explain(e), real=True)
    ok = all(e["ok"] for e in etapas)
    return {"estado": "validado" if ok else "erro", "etapas": etapas}
