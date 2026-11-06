"""v0.9 — diagnóstico das permissões Meta POR MÓDULO (Páginas, Instagram, Biblioteca de Anúncios).

Achado da auditoria (documentação oficial da Meta, "Create an App"): o caso de uso "Authenticate and request data from
users with Facebook Login" é incompatível com "Manage everything on your Page", e casos de uso não podem ser removidos
de um app. Num app de Login, a Meta recusa pages_show_list/pages_read_engagement com "Invalid Scopes" — na própria
tela do Facebook, sem retorno ao GPI. Por isso o GPI aceita um SEGUNDO app ("de negócios") para os módulos de dados e
deduz a incompatibilidade pela configuração, sem pedir permissões que não serão aceitas.

Estados: conectado · sem_permissao · aprovacao_necessaria · configuracao_incompleta · nao_suportado · erro_rede · limite.
Nada é marcado "conectado" sem uma consulta oficial bem-sucedida com o token do módulo."""
from __future__ import annotations

import json
import urllib.parse as up

from ..connectors.http import SourceError
from . import meta as MT

STATES = {"conectado": "Conectado", "sem_permissao": "Sem permissão", "aprovacao_necessaria": "Aprovação necessária",
          "configuracao_incompleta": "Configuração incompleta", "nao_suportado": "Não suportado", "erro_rede": "Erro de rede",
          "limite": "Limite de uso atingido"}

REQ = {
    "paginas": {"permissoes": ["pages_show_list", "pages_read_engagement"],
                "caso_de_uso": "Manage everything on your Page (Gerenciar tudo na sua Página)",
                "aprovacao": "Acesso padrão basta para Páginas que você administra (com função no app). Páginas de terceiros "
                             "exigem o recurso Page Public Content Access (revisão do app e verificação da empresa)."},
    "instagram": {"permissoes": ["instagram_basic", "pages_show_list", "pages_read_engagement"],
                  "caso_de_uso": "Instagram — API with Facebook Login for Business (necessária para busca de hashtags)",
                  "aprovacao": "Busca de hashtags exige o recurso Instagram Public Content Access (revisão do app). Conta do "
                               "Instagram profissional (Empresa ou Criador) vinculada a uma Página. 30 hashtags distintas por 7 dias."},
    "anuncios": {"permissoes": ["ads_read"],
                 "caso_de_uso": "acesso à API da Biblioteca de Anúncios (Ad Library API)",
                 "aprovacao": "Exige confirmação de identidade na Meta e acesso à API da Biblioteca de Anúncios. Anúncios "
                              "comerciais completos só para países da União Europeia — não representam o Brasil."},
}


def _graph(cfg) -> str:
    return f"https://graph.facebook.com/{cfg.get('meta_graph_version', 'v23.0')}/"


def _call(http, url: str) -> tuple[dict | None, dict | None, str | None]:
    """(dados, erro_oficial, tipo_de_falha). Nunca devolve o token."""
    try:
        r = http.request_json(url, ttl=0)
    except SourceError as e:
        if e.kind in ("rede", "tls") and not getattr(e, "status", None):
            return None, None, "rede"
        body = getattr(e, "body", None) or ""
        try:
            err = (json.loads(body) or {}).get("error") or {}
        except (ValueError, TypeError):
            err = {}
        return None, {"code": err.get("code"), "subcode": err.get("error_subcode"), "mensagem": str(err.get("message") or e)[:240]}, "graph"
    if isinstance(r, dict) and r.get("error"):
        e = r["error"]
        return None, {"code": e.get("code"), "subcode": e.get("error_subcode"), "mensagem": str(e.get("message"))[:240]}, "graph"
    return r, None, None


def _state_from_error(err: dict | None, kind: str | None, missing: list[str]) -> str:
    if kind == "rede":
        return "erro_rede"
    code = (err or {}).get("code")
    if code in (4, 17, 32, 613):
        return "limite"
    if code == 190:
        return "sem_permissao"
    if code in (10,) or (isinstance(code, int) and 200 <= code < 300):
        return "sem_permissao" if missing else "aprovacao_necessaria"
    if code == 100:
        return "nao_suportado"
    return "configuracao_incompleta"


def _granted(http, cfg, c) -> tuple[list[str], list[str], dict | None, str | None]:
    tok = c.get("access_token")
    d, err, kind = _call(http, _graph(cfg) + "me/permissions?" + up.urlencode({"access_token": tok}))
    if d is None:
        return [], [], err, kind
    g = [p["permission"] for p in d.get("data", []) if p.get("status") == "granted"]
    dec = [p["permission"] for p in d.get("data", []) if p.get("status") == "declined"]
    return g, dec, None, None


def diagnose(http, creds, cfg: dict) -> dict:
    out = {}
    for mod in ("paginas", "instagram", "anuncios"):
        out[mod] = _one(http, creds, cfg, mod)
    login = creds.get(MT.LOGIN_APP) or {}
    biz = creds.get(MT.BUSINESS_APP) or {}
    return {"modulos": out, "estados": STATES,
            "apps": {"login": {"app_id": login.get("client_id"), "conectado": bool(login.get("access_token"))},
                     "negocios": {"app_id": biz.get("client_id"), "configurado": bool(biz.get("client_id")),
                                  "conectado": bool(biz.get("access_token"))}},
            "regra": "Login básico continua no app atual; Páginas, Instagram e Anúncios usam o app de negócios."}


def _one(http, creds, cfg, mod: str) -> dict:
    req = REQ[mod]
    app = MT.app_key(creds, mod)
    c = creds.get(app) or {}
    r = {"modulo": mod, "nome": MT.MODULES[mod]["nome"], "app": "negócios" if app == MT.BUSINESS_APP else "login",
         "app_id": c.get("client_id"), "permissoes_necessarias": req["permissoes"], "caso_de_uso": req["caso_de_uso"],
         "aprovacao_exigida": req["aprovacao"], "permissoes_concedidas": [], "permissoes_recusadas": [], "pendencias": [],
         "conta_ou_pagina": None, "consulta_real": None, "erro_oficial": None, "estado": None, "acao": None}

    def done(estado, acao, pend=None):
        r["estado"], r["estado_rotulo"], r["acao"] = estado, STATES[estado], acao
        if pend:
            r["pendencias"].append(pend)
        return r
    tok = c.get("access_token")
    scopes = [s for s in str(c.get("escopos") or "").split(",") if s]
    if app == MT.LOGIN_APP and not set(req["permissoes"]) <= set(scopes):
        return done("configuracao_incompleta",
                    "Crie um app de negócios na Meta com o caso de uso '" + req["caso_de_uso"] + "' e informe o App ID e o "
                    "App Secret dele em Central de Integrações → Meta (app de negócios). O app atual continua no Login básico.",
                    "o app de Login (caso de uso 'Authenticate and request data from users with Facebook Login') não pode "
                    "receber estas permissões — a Meta responde 'Invalid Scopes'")
    if not str(c.get("client_id") or "").isdigit() or not c.get("client_secret"):
        return done("configuracao_incompleta", "Informe App ID e App Secret do app de negócios.", "credenciais do app ausentes")
    if not tok:
        return done("configuracao_incompleta", f"Clique em 'Conectar — {r['nome']}'.", "módulo ainda não autorizado")
    g, dec, err, kind = _granted(http, cfg, c)
    if kind:
        r["erro_oficial"] = err
        return done(_state_from_error(err, kind, req["permissoes"]), "Confira a conexão e conecte o módulo de novo.")
    r["permissoes_concedidas"], r["permissoes_recusadas"] = g, dec
    missing = [p for p in req["permissoes"] if p not in g]
    if missing:
        acao = ("Você recusou " + ", ".join(p for p in missing if p in dec) + " na tela da Meta: conecte o módulo de novo e aceite."
                if any(p in dec for p in missing) else
                "Confira se o caso de uso do app inclui " + ", ".join(missing) + " (Casos de uso → Personalizar → Permissões) e conecte de novo.")
        return done("sem_permissao", acao, "permissões não concedidas ao token: " + ", ".join(missing))
    G, tq = _graph(cfg), {"access_token": tok}
    pages, err, kind = _call(http, G + "me/accounts?" + up.urlencode({**tq, "fields": "id,name,instagram_business_account"}))
    if kind:
        r["erro_oficial"] = err
        return done(_state_from_error(err, kind, missing), "Veja o erro oficial e conecte de novo.")
    plist = (pages or {}).get("data") or []
    if mod in ("paginas", "instagram") and not plist:
        r["consulta_real"] = {"ok": True, "resultado": "nenhuma Página administrada por esta conta"}
        return done("configuracao_incompleta", "Use uma conta com função de administrador numa Página do Facebook.",
                    "conta sem Página administrada")
    if mod == "paginas":
        r["conta_ou_pagina"] = ", ".join(p.get("name", "?") for p in plist[:5])
        r["consulta_real"] = {"ok": True, "resultado": f"{len(plist)} Página(s) administrada(s) listada(s) por /me/accounts"}
        r["observacao"] = "Somente Páginas que você administra. Páginas de terceiros exigem Page Public Content Access."
        return done("conectado", None)
    if mod == "instagram":
        ig = next((p["instagram_business_account"]["id"] for p in plist if p.get("instagram_business_account")), None)
        if not ig:
            r["consulta_real"] = {"ok": True, "resultado": "nenhuma conta profissional do Instagram vinculada às Páginas"}
            return done("configuracao_incompleta", "Vincule uma conta do Instagram Empresa/Criador a uma das Páginas.",
                        "Instagram profissional não vinculado")
        acc, err, kind = _call(http, G + str(ig) + "?" + up.urlencode({**tq, "fields": "id,username"}))
        r["conta_ou_pagina"] = f"@{(acc or {}).get('username', '?')} (ID numérico {ig})"
        # recently_searched_hashtags exige o mesmo recurso da busca, mas NÃO consome a cota de 30 hashtags/7 dias
        hs, err, kind = _call(http, G + f"{ig}/recently_searched_hashtags?" + up.urlencode({**tq, "limit": 1}))
        if kind:
            r["erro_oficial"] = err
            r["consulta_real"] = {"ok": False, "resultado": "busca de hashtags recusada pela Meta"}
            return done(_state_from_error(err, kind, []),
                        "Solicite o recurso Instagram Public Content Access na revisão do app (App Review).")
        r["consulta_real"] = {"ok": True, "resultado": "conta lida e acesso à busca de hashtags confirmado"}
        if not creds.get(MT.app_key(creds, mod)).get("ig_user_id"):
            creds.set(MT.app_key(creds, mod), {"ig_user_id": str(ig)})
        return done("conectado", None)
    # anúncios: consulta mínima na Biblioteca (UE, onde há anúncios comerciais)
    ad, err, kind = _call(http, G + "ads_archive?" + up.urlencode({**tq, "search_terms": "air fryer", "ad_reached_countries": '["DE"]',
                                                                    "ad_type": "ALL", "fields": "id", "limit": 1}))
    if kind:
        r["erro_oficial"] = err
        r["consulta_real"] = {"ok": False, "resultado": "consulta à Biblioteca de Anúncios recusada"}
        return done(_state_from_error(err, kind, []),
                    "Confirme sua identidade (facebook.com/ID) e solicite acesso à API da Biblioteca de Anúncios.")
    r["consulta_real"] = {"ok": True, "resultado": f"{len((ad or {}).get('data') or [])} anúncio(s) na amostra (Alemanha)"}
    r["observacao"] = "Anúncios comerciais só existem para a União Europeia: não são evidência do mercado brasileiro."
    return done("conectado", None)
