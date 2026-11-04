"""
Google Ads API — autenticação vigente (v0.6.1).

Mudança oficial: os developer tokens foram descontinuados em 09/09/2026. O acesso à API passou a ser
controlado pelo projeto Google Cloud dono das credenciais OAuth (Client ID/Secret). O cabeçalho
`developer-token` é opcional e ignorado pelos servidores, e uma versão futura vai rejeitá-lo — por isso o
GPI não o envia mais (um token antigo salvo é preservado, mas ignorado).
Fonte: https://developers.google.com/google-ads/api/docs/api-policy/developer-token

Fluxo assistido:
  1. Client ID / Client Secret (do projeto Google Cloud com a Google Ads API ativada).
  2. Login com Google (OAuth 2.0 + PKCE, escopo adwords) — o GPI nunca vê a senha.
  3. Contas acessíveis: GET customers:listAccessibleCustomers (não exige ID de conta) e, para cada conta,
     consulta GAQL ao recurso `customer` (nome, gerente/MCC, conta de teste). Contas-clientes de uma MCC
     vêm de `customer_client`. login-customer-id só é usado quando a conta é acessada por uma MCC.
  4. Diagnóstico: OAuth → contas → leitura da conta → planejador (KeywordPlanIdeaService) com 3 palavras.

Níveis de acesso (https://developers.google.com/google-ads/api/docs/api-policy/access-levels): Test só
acessa contas de teste; Explorer acessa produção mas NÃO o KeywordPlanIdeaService; Basic/Standard acessam.
Não existe uma chamada documentada que informe o nível do projeto; o GPI deduz pela sequência de chamadas e
mostra o código de erro devolvido, orientando a conferência no Google Cloud Console.
"""
from __future__ import annotations

import json
import re
import time

from ..connectors.http import SourceError

API = "https://googleads.googleapis.com/"
VERSIONS = ["v26", "v25", "v24", "v23", "v22"]     # da mais nova para a mais antiga; a ativa fica registrada
MSG = {
    "basic": "Login Google autorizado, mas o projeto ainda não possui acesso Basic necessário para consultar palavras-chave.",
    "sem_conta": "Conta Google Ads não encontrada.",
    "producao": "Projeto Google Cloud sem autorização para produção.",
    "planejamento": "Autorização de planejamento indisponível.",
}
HOW = {
    "basic": "No Google Cloud Console, abra 'Google Ads API' → 'Overview' do projeto dono do Client ID e solicite o nível Basic "
             "(exige verificação da marca do projeto). Explorer não permite o Planejador de palavras-chave.",
    "sem_conta": "Entre em ads.google.com com a MESMA conta Google usada no login do GPI e crie/aceite o acesso a uma conta "
                 "Google Ads (não é preciso veicular anúncios). Depois clique em 'Identificar contas disponíveis'.",
    "producao": "O projeto está no nível Test (só contas de teste). No Google Cloud Console → Google Ads API → Overview, "
                "solicite o nível Explorer e, para palavras-chave, o Basic.",
    "planejamento": "Confira o nível de acesso do projeto no Google Cloud Console e as permissões do usuário na conta Google Ads.",
}


def error_codes(e: SourceError) -> list[dict]:
    """Extrai os códigos do GoogleAdsFailure (ex.: {'authorizationError': 'USER_PERMISSION_DENIED'})."""
    out = []
    try:
        j = json.loads(e.body or "")
    except ValueError:
        j = None
    if isinstance(j, list) and j:
        j = j[0]
    err = (j or {}).get("error") if isinstance(j, dict) else None
    if err:
        for d in err.get("details") or []:
            for x in d.get("errors") or []:
                for k, v in (x.get("errorCode") or {}).items():
                    out.append({"tipo": k, "codigo": v, "mensagem": x.get("message", "")[:300]})
        if not out:
            out.append({"tipo": "status", "codigo": err.get("status") or str(err.get("code")), "mensagem": str(err.get("message", ""))[:300]})
    elif e.status:
        out.append({"tipo": "http", "codigo": str(e.status), "mensagem": str(e)[:300]})
    return out


def classify(e: SourceError, etapa: str) -> tuple[str, str]:
    """(chave da mensagem, código) para um erro em uma etapa: 'contas' | 'conta' | 'planejamento'."""
    codes = error_codes(e)
    flat = " ".join(f"{c['tipo']}:{c['codigo']}" for c in codes)
    code = codes[0]["codigo"] if codes else (str(e.status) if e.status else e.kind)
    if "NOT_ADS_USER" in flat or "CUSTOMER_NOT_FOUND" in flat:
        return "sem_conta", code
    if "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION" in flat or "DEVELOPER_TOKEN_NOT_APPROVED" in flat:
        return "producao", code
    if etapa == "planejamento" and (e.status in (401, 403) or "authorizationError" in flat or "ACTION_NOT_PERMITTED" in flat
                                    or "PERMISSION_DENIED" in flat):
        return "basic", code                       # conta legível, só o planejador recusado: nível do projeto
    if "ACTION_NOT_PERMITTED" in flat and etapa != "planejamento":
        return "producao", code                    # v24 e anteriores usam ACTION_NOT_PERMITTED para projeto Test
    return "planejamento", code


def token(http, creds) -> str:
    c = creds.get("google_ads")
    if not c.get("refresh_token"):
        raise SourceError("Google Ads não conectado: use 'Entrar com Google' na Central de Integrações", "restrita")
    if c.get("access_token") and float(c.get("expires_at", 0)) > time.time() + 60:
        return c["access_token"]
    r = http.request_json("https://oauth2.googleapis.com/token", "POST", form={
        "grant_type": "refresh_token", "client_id": c.get("client_id", ""), "client_secret": c.get("client_secret", ""),
        "refresh_token": c["refresh_token"]})
    if not r.get("access_token"):
        raise SourceError(f"Google não renovou o token: {r.get('error_description') or r.get('error')}", "restrita")
    creds.set("google_ads", {"access_token": r["access_token"], "expires_at": str(time.time() + float(r.get("expires_in", 3600)))})
    return r["access_token"]


def _digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def call(http, creds, path: str, body: dict | None = None, method: str = "POST", customer: str | None = None,
         login_customer: str | None = None, use_login: bool = True) -> dict:
    """Chamada REST oficial, sem developer token; descobre a versão ativa (versões antigas são desligadas)."""
    c = creds.get("google_ads")
    hdr = {"Authorization": f"Bearer {token(http, creds)}"}
    lc = _digits(login_customer if login_customer is not None else (c.get("login_customer_id") if use_login else ""))
    if lc:
        hdr["login-customer-id"] = lc
    cust = _digits(customer if customer is not None else c.get("customer_id"))
    url_path = path if path.startswith("customers:") else f"customers/{cust}{path}"
    if not path.startswith("customers:") and not cust:
        raise SourceError("selecione a conta Google Ads (Central de Integrações → Identificar contas disponíveis)", "restrita")
    versions = ([c["api_version"]] if c.get("api_version") in VERSIONS else []) + [v for v in VERSIONS if v != c.get("api_version")]
    last = None
    for v in versions:
        try:
            r = http.request_json(f"{API}{v}/{url_path}", method, body if method == "POST" else None, headers=hdr, ttl=0)
            if c.get("api_version") != v:
                creds.set("google_ads", {"api_version": v})
            return r
        except SourceError as e:
            last = e
            if e.status == 404 or (e.status == 400 and "UNSUPPORTED_VERSION" in (e.body or str(e))):
                continue                                        # versão desligada ou inexistente: tenta outra
            raise
    raise last or SourceError("nenhuma versão da API do Google Ads respondeu", "http")


def customer_info(http, creds, cid: str, login: str | None = None) -> dict:
    q = ("SELECT customer.id, customer.descriptive_name, customer.manager, customer.test_account, customer.currency_code, "
         "customer.time_zone, customer.status FROM customer LIMIT 1")
    r = call(http, creds, "/googleAds:search", {"query": q}, customer=cid, login_customer=login or "")
    row = ((r.get("results") or [{}])[0]).get("customer") or {}
    return {"customer_id": _digits(row.get("id") or cid), "nome": row.get("descriptiveName") or "(sem nome)",
            "gerente": bool(row.get("manager")), "teste": bool(row.get("testAccount")), "moeda": row.get("currencyCode"),
            "status": row.get("status"), "via_gerente": login or None}


def discover(http, creds) -> dict:
    """Contas realmente acessíveis pelo usuário autenticado (sem exigir MCC)."""
    r = call(http, creds, "customers:listAccessibleCustomers", method="GET", use_login=False)
    ids = [_digits(n.split("/")[-1]) for n in (r.get("resourceNames") or [])]
    contas, erros = [], []
    for cid in ids[:50]:
        try:
            info = customer_info(http, creds, cid)
        except SourceError as e:
            erros.append({"customer_id": cid, "erro": error_codes(e)})
            contas.append({"customer_id": cid, "nome": "(sem leitura direta)", "gerente": None, "teste": None, "via_gerente": None})
            continue
        contas.append(info)
        if info["gerente"]:
            q = ("SELECT customer_client.id, customer_client.descriptive_name, customer_client.manager, "
                 "customer_client.test_account, customer_client.level FROM customer_client WHERE customer_client.level = 1")
            try:
                rr = call(http, creds, "/googleAds:search", {"query": q}, customer=cid, login_customer=cid)
                for row in rr.get("results") or []:
                    cc = row.get("customerClient") or {}
                    if _digits(cc.get("id")) and _digits(cc.get("id")) not in ids:
                        contas.append({"customer_id": _digits(cc.get("id")), "nome": cc.get("descriptiveName") or "(sem nome)",
                                       "gerente": bool(cc.get("manager")), "teste": bool(cc.get("testAccount")),
                                       "via_gerente": cid})
            except SourceError as e:
                erros.append({"customer_id": cid, "erro": error_codes(e)})
    creds.set("google_ads", {"contas": json.dumps(contas, ensure_ascii=False)})
    out = {"contas": contas, "erros": erros}
    if not ids:
        out["mensagem"], out["acao"] = MSG["sem_conta"], HOW["sem_conta"]
    return out


def select(creds, customer_id: str, login_customer_id: str | None = None) -> dict:
    cid = _digits(customer_id)
    if not cid:
        raise ValueError("ID de conta inválido")
    contas = json.loads(creds.get("google_ads").get("contas") or "[]")
    known = next((c for c in contas if c["customer_id"] == cid), None)
    lc = _digits(login_customer_id) if login_customer_id else (known or {}).get("via_gerente") or ""
    creds.set("google_ads", {"customer_id": cid, "login_customer_id": lc})
    return {"customer_id": cid, "login_customer_id": lc or None, "nome": (known or {}).get("nome")}


def diagnose(http, creds, keywords: list[str] | None = None) -> dict:
    """Etapas independentes; nenhuma chamada cria ou altera campanhas. Custo: 1 listagem, 1 leitura de conta e
    1 consulta de ideias com até 3 palavras-chave (Brasil, português)."""
    keywords = keywords or ["carregador usb-c", "fechadura inteligente", "air fryer"]
    c = creds.get("google_ads")
    steps = []

    def add(nome, ok, msg, **kw):
        steps.append({"etapa": nome, "ok": ok, "mensagem": msg, **kw})
    add("Configuração", bool(c.get("client_id")), "Client ID salvo" if c.get("client_id") else "informe o OAuth Client ID",
        developer_token="descontinuado em 09/09/2026 — não é usado" if c.get("developer_token") else "não necessário")
    if not c.get("client_id"):
        return {"etapas": steps, "estado": "nao_configurado"}
    try:
        token(http, creds)
        add("OAuth", True, "Login Google autorizado (token válido e renovável)")
    except SourceError as e:
        add("OAuth", False, str(e), acao="Clique em 'Entrar com Google'.")
        return {"etapas": steps, "estado": "nao_autenticado"}
    try:
        d = discover(http, creds)
        if not d["contas"]:
            add("Contas", False, MSG["sem_conta"], acao=HOW["sem_conta"])
            return {"etapas": steps, "estado": "sem_conta"}
        add("Contas", True, f"{len(d['contas'])} conta(s) acessível(is)", contas=d["contas"])
    except SourceError as e:
        k, code = classify(e, "contas")
        add("Contas", False, MSG[k], codigo=code, acao=HOW[k])
        return {"etapas": steps, "estado": k}
    c = creds.get("google_ads")
    if not c.get("customer_id"):
        usable = [x for x in d["contas"] if x.get("gerente") is False]
        if len(usable) == 1:
            select(creds, usable[0]["customer_id"], usable[0].get("via_gerente"))
            c = creds.get("google_ads")
        else:
            add("Conta selecionada", False, "selecione a conta Google Ads que será usada", acao="Escolha a conta na lista.")
            return {"etapas": steps, "estado": "selecionar_conta"}
    try:
        info = customer_info(http, creds, c["customer_id"], c.get("login_customer_id") or None)
        tipo = "conta de teste" if info["teste"] else "conta de produção"
        add("Conta selecionada", True, f"{info['nome']} ({info['customer_id']}) — {tipo}"
            + (f", via administradora {c.get('login_customer_id')}" if c.get("login_customer_id") else ""))
    except SourceError as e:
        k, code = classify(e, "conta")
        add("Conta selecionada", False, MSG[k], codigo=code, acao=HOW[k])
        return {"etapas": steps, "estado": k}
    body = {"language": "languageConstants/1014", "geoTargetConstants": ["geoTargetConstants/2076"], "includeAdultKeywords": False,
            "keywordPlanNetwork": "GOOGLE_SEARCH", "keywordSeed": {"keywords": keywords[:3]}}
    try:
        from ..connectors.search import parse_keyword_ideas
        ideas = parse_keyword_ideas(call(http, creds, ":generateKeywordIdeas", body))
        seeds = {k.lower() for k in keywords}
        sample = sorted(ideas, key=lambda i: (i["termo"].lower() not in seeds, -(i["media_mensal"] or 0)))[:10]
        add("Planejamento de palavras-chave", bool(ideas), f"{len(ideas)} ideias retornadas (Brasil, português)" if ideas
            else "a API respondeu sem ideias", resultados=[{"palavra_chave": i["termo"], "media_mensal_aprox": i["media_mensal"],
                                                            "meses_historico": len(i["meses"]), "pais": "BR", "idioma": "pt",
                                                            "fonte": "Google Ads — KeywordPlanIdeaService"} for i in sample])
        return {"etapas": steps, "estado": "validado" if ideas else "sem_dados", "nivel_acesso": "Basic ou Standard (deduzido: o planejador respondeu)"}
    except SourceError as e:
        k, code = classify(e, "planejamento")
        add("Planejamento de palavras-chave", False, MSG[k], codigo=code, acao=HOW[k])
        return {"etapas": steps, "estado": k, "nivel_acesso": "Test ou Explorer (deduzido: a conta foi lida, o planejador foi recusado)"
                if k == "basic" else "indeterminado"}
