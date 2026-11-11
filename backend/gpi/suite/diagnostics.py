"""Diagnóstico das integrações e classificação dos erros das fontes (v0.9.1).

Cada erro vira um ESTADO específico com mensagem e ação objetivas — HTTP 429 (limite) ≠ 403 do proxy/túnel ≠ 403 do
servidor ≠ credencial sem permissão ≠ token expirado ≠ DNS/TLS/timeout/servidor. O teste de conexão usa uma operação
autorizada e de baixo custo, não consome créditos pagos e não altera credenciais válidas. Ter credencial NÃO é tratado
como permissão para todos os endpoints: o Mercado Livre, por exemplo, é testado em dois passos (token e busca)."""
from __future__ import annotations

import urllib.parse

from . import store as S

STATES = ["Não configurada", "Configurada", "Autorizada", "Funcional", "Funcional sem resultados", "Permissão insuficiente",
          "Token expirado", "Bloqueada pela rede", "Limite de requisições", "Indisponível"]

CAUSE = {
    "token": ("Token expirado", "não autorizada", "Credencial recusada (token ausente, inválido ou expirado).", "reconectar"),
    "permissao": ("Permissão insuficiente", "não autorizada", "A credencial é válida, mas não autoriza este recurso.", "permissoes"),
    "recusado": ("Indisponível", "indisponível", "O servidor de destino recusou o acesso (HTTP 403).", "tentar_depois"),
    "proxy": ("Bloqueada pela rede", "bloqueada pela rede",
              "Não foi possível estabelecer conexão com a fonte. Verifique as configurações de rede ou consulte a TI.", "ti"),
    "limite": ("Limite de requisições", "limite de requisições", "Limite de requisições atingido.", "tentar_depois"),
    "dns": ("Indisponível", "indisponível", "Endereço da fonte não resolvido (DNS).", "rede"),
    "tls": ("Bloqueada pela rede", "bloqueada pela rede", "Certificado TLS não verificado (inspeção da rede corporativa?).", "ti"),
    "timeout": ("Indisponível", "indisponível", "Tempo de conexão esgotado.", "tentar_depois"),
    "conexao_recusada": ("Indisponível", "indisponível", "A conexão foi recusada.", "tentar_depois"),
    "servidor": ("Indisponível", "indisponível", "Falha do servidor da fonte (HTTP 5xx).", "tentar_depois"),
    "rede": ("Indisponível", "indisponível", "Falha de rede.", "rede"),
    "nao_encontrado": ("Indisponível", "falhou", "Recurso não encontrado (HTTP 404) — endpoint pode ter mudado.", "suporte"),
    "formato": ("Indisponível", "falhou", "Resposta em formato inesperado.", "suporte"),
}
ACTIONS = {"reconectar": "Reconectar a integração (Central de Integrações → Conectar)",
           "permissoes": "Verificar as permissões/escopos do aplicativo no portal oficial da fonte e reconectar",
           "ti": "Pedir à TI a liberação do endereço (ver docs/TI.md); o GPI não contorna bloqueios",
           "tentar_depois": "Tentar mais tarde; o GPI respeita Retry-After e limita as novas tentativas",
           "rede": "Verificar a conexão com a internet e o DNS", "suporte": "Registrar o diagnóstico (exportar) e verificar a documentação da API",
           "configurar": "Abrir a Central de Integrações e configurar a fonte"}


def classify(e) -> dict:
    """SourceError (ou outra exceção) → estado do diagnóstico, estado da consulta, mensagem e ação."""
    cause = getattr(e, "cause", None)
    kind = getattr(e, "kind", None)
    if not cause:
        cause = {"restrita": "token" if getattr(e, "status", None) == 401 else "permissao", "limite": "limite", "bloqueada": "proxy",
                 "tls": "tls", "rede": "rede", "formato": "formato"}.get(kind, None)
        if kind == "restrita" and "não conectado" in str(e).lower():
            return {"estado": "Não configurada", "consulta": "não autorizada", "causa": "nao_configurada", "mensagem": str(e)[:300],
                    "acao": ACTIONS["configurar"], "acao_id": "configurar"}
    if cause not in CAUSE:
        return {"estado": "Indisponível", "consulta": "falhou", "causa": cause or "desconhecida", "mensagem": str(e)[:300],
                "acao": ACTIONS["suporte"], "acao_id": "suporte"}
    est, cons, msg, act = CAUSE[cause]
    det = str(e)[:300]
    return {"estado": est, "consulta": cons, "causa": cause, "mensagem": msg if msg in det else f"{msg} {det}", "acao": ACTIONS[act],
            "acao_id": act, "http": getattr(e, "status", None)}


# --------------------------------------------------------------------------------------------- integrações
SUITE_INTEGRATIONS = [  # (id do provedor na Central, conectores, capacidades)
    ("mercadolivre", ["mercadolivre", "ml_trends"], ["marketplace_listings (busca de anúncios)", "keyword_ranking"]),
    ("ebay", ["ebay"], ["marketplace_listings (EUA)"]),
    ("google_ads", ["google_ads_kp"], ["search_volume (BR, US)"]),
    ("msads", ["msads_kp"], ["search_volume (Bing)"]),
    ("youtube", ["youtube"], ["product_search (vídeos)"]),
    ("gdelt", ["gdelt"], ["news_mentions (global)"]),
    ("google_trends_rss", ["google_trends_rss"], ["search_interest (só termos em alta)"]),
    ("comexstat", ["comexstat"], ["trade_statistics (por NCM)"]),
]
DIAG_KEY = "suite:diag:"


def _configured(pid, creds, cfg) -> bool:
    c = lambda n: (creds.get(n) if creds else {}) or {}  # noqa: E731
    return {"mercadolivre": bool(c("mercadolivre").get("access_token") or cfg.get("mercadolivre_access_token")),
            "ebay": bool(c("ebay").get("client_id") and c("ebay").get("client_secret")),
            "google_ads": bool(c("google_ads").get("refresh_token")), "msads": bool(c("msads").get("refresh_token")),
            "youtube": bool(c("youtube").get("api_key"))}.get(pid, True)


def rows(db, sync, cfg) -> list[dict]:
    from . import targeted as TG
    TG.ensure(db)
    st = {r["source"]: r for r in db.query("SELECT * FROM source_status")}
    out = []
    for pid, conns, caps in SUITE_INTEGRATIONS:
        conf = _configured(pid, sync.creds, cfg)
        last_test = sync.store.load_result(DIAG_KEY + pid) or {}
        s = next((st[c] for c in conns if c in st), {}) or {}
        runs = db.query("SELECT * FROM research_source_runs WHERE source IN (%s) ORDER BY id DESC LIMIT 1" %
                        ",".join("?" * (len(conns) + 1)), (*conns, "mercadolivre_busca" if pid == "mercadolivre" else "§"))
        last_run = runs[0] if runs else None
        ok_run = db.query("SELECT at FROM research_source_runs WHERE source IN (%s) AND status IN ('com dados', 'sem dados') ORDER BY id DESC LIMIT 1" %
                          ",".join("?" * (len(conns) + 1)), (*conns, "mercadolivre_busca" if pid == "mercadolivre" else "§"))
        if not conf:
            estado = "Não configurada"
        elif last_test.get("estado"):
            estado = last_test["estado"]
        elif s.get("state") in ("funcional", "ok"):
            estado = "Funcional" if (s.get("records") or 0) else "Funcional sem resultados"
        else:
            estado = "Configurada"
        dados = {"registros_na_ultima_coleta": s.get("records"), "cobertura": [s.get("coverage_start"), s.get("coverage_end")]}
        out.append({"id": pid, "nome": _name(pid), "configuracao": "configurada" if conf else "não configurada",
                    "autenticacao": last_test.get("autenticacao") or ("não exigida" if pid in ("gdelt", "google_trends_rss", "comexstat") else
                                                                     "não testada" if conf else "ausente"),
                    "permissoes": last_test.get("permissoes") or [], "capacidades": caps, "estado": estado,
                    "ultima_tentativa": max(filter(None, [last_test.get("em"), (last_run or {}).get("at"), s.get("last_attempt")]), default=None),
                    "ultima_sucesso": max(filter(None, [s.get("last_success"), (ok_run[0]["at"] if ok_run else None),
                                                        last_test.get("em") if last_test.get("ok") else None]), default=None),
                    "erro_recente": last_test.get("mensagem") if not last_test.get("ok") else ((last_run or {}).get("detail") or s.get("message")),
                    "dados": dados, "acao": last_test.get("acao") or (ACTIONS["configurar"] if not conf else None),
                    "central": f"#integracoes/{pid}"})
    return out


def _name(pid):
    return {"mercadolivre": "Mercado Livre", "ebay": "eBay Browse API", "google_ads": "Google Ads Keyword Planner", "msads": "Microsoft Advertising",
            "youtube": "YouTube Data API", "gdelt": "GDELT (notícias, público)", "google_trends_rss": "Google Trends (RSS)",
            "comexstat": "Comex Stat"}.get(pid, pid)


def test(db, sync, cfg, pid: str) -> dict:
    """Teste de baixo custo. Nunca consome créditos pagos e nunca grava/alterna credenciais (exceto a renovação normal de
    um token expirado pelo próprio fluxo OAuth da fonte)."""
    from ..connectors.http import SourceError
    res = {"id": pid, "em": S.now(), "ok": False, "permissoes": [], "etapas": []}
    if not _configured(pid, sync.creds, cfg):
        res.update({"estado": "Não configurada", "autenticacao": "ausente", "mensagem": f"{_name(pid)} não configurado.", "acao": ACTIONS["configurar"]})
        sync.store.save_result(DIAG_KEY + pid, res)
        return res
    try:
        if pid == "mercadolivre":
            from ..integrations.registry import ml_token
            tok = ml_token(sync.http, sync.creds)
            me = sync.http.request_json("https://api.mercadolibre.com/users/me", headers={"Authorization": f"Bearer {tok}"}, ttl=0)
            res["etapas"].append({"etapa": "token (users/me)", "ok": bool(me.get("id")), "detalhe": f"conta {me.get('site_id') or ''}".strip()})
            res["autenticacao"] = "autorizada"
            res["permissoes"].append("leitura da conta")
            try:
                r = sync.http.request_json("https://api.mercadolibre.com/sites/MLB/search?" + urllib.parse.urlencode({"q": "carregador", "limit": 1}),
                                           headers={"Authorization": f"Bearer {tok}"}, ttl=0)
                n = len((r or {}).get("results") or [])
                res["etapas"].append({"etapa": "busca de anúncios (sites/MLB/search, 1 item)", "ok": True, "detalhe": f"{n} resultado(s)"})
                res["permissoes"].append("busca de anúncios")
                res.update({"ok": True, "estado": "Funcional" if n else "Funcional sem resultados", "mensagem": "Token e busca de anúncios funcionando."})
            except SourceError as e:
                c = classify(e)
                res["etapas"].append({"etapa": "busca de anúncios (sites/MLB/search, 1 item)", "ok": False, "detalhe": c["mensagem"]})
                res.update({"estado": "Autorizada" if c["causa"] in ("permissao", "recusado") else c["estado"],
                            "mensagem": "Conta autorizada, mas a busca de anúncios não está disponível para este aplicativo: " + c["mensagem"],
                            "acao": ("No DevCenter do Mercado Livre, confira se o aplicativo está ativo, com os escopos de leitura e o "
                                     "domínio MLB; depois reconecte. Sem permissão de busca, o GPI usa só as tendências de busca.")
                            if c["causa"] in ("permissao", "recusado") else c["acao"]})
        else:
            from ..integrations import registry as integ
            ok, msg = integ.test_connection(pid, sync.http, sync.creds, cfg)
            res.update({"ok": ok, "estado": "Funcional" if ok else "Indisponível", "mensagem": msg,
                        "autenticacao": ("não exigida" if pid in ("gdelt", "google_trends_rss", "comexstat") else "autorizada") if ok else "não confirmada"})
            if ok:
                res["permissoes"].append("operação de teste da fonte")
    except SourceError as e:
        c = classify(e)
        res.update({"estado": c["estado"], "mensagem": c["mensagem"], "acao": c["acao"], "causa": c["causa"],
                    "autenticacao": "expirada/recusada" if c["causa"] == "token" else "não confirmada"})
    except Exception as e:  # noqa: BLE001
        res.update({"estado": "Indisponível", "mensagem": f"{type(e).__name__}: {str(e)[:200]}", "acao": ACTIONS["suporte"]})
    sync.store.save_result(DIAG_KEY + pid, res)
    return res


def ml_search_preview(sync, query: str, limit: int = 20) -> dict:
    """Pesquisa de TESTE no Mercado Livre: mostra os anúncios sem gravá-los. Preço anunciado ≠ preço de venda; sem vendas."""
    from ..connectors.http import SourceError
    from ..integrations.registry import ml_token
    from ..products import nlp
    q = (query or "").strip()[:120]
    if not q:
        raise ValueError("informe o termo")
    try:
        tok = ml_token(sync.http, sync.creds)
        r = sync.http.request_json("https://api.mercadolibre.com/sites/MLB/search?" + urllib.parse.urlencode({"q": q, "limit": max(1, min(50, limit))}),
                                   headers={"Authorization": f"Bearer {tok}"}, ttl=0)
    except SourceError as e:
        return {"ok": False, **classify(e), "consulta": q}
    items = []
    for it in (r or {}).get("results") or []:
        at = nlp.extract_attributes(it.get("title") or "")
        attrs = {a.get("name") or a.get("id"): a.get("value_name") for a in it.get("attributes") or [] if a.get("value_name")}
        items.append({"produto": q, "titulo": it.get("title"), "preco_anunciado": it.get("price"), "moeda": it.get("currency_id"),
                      "marketplace": "Mercado Livre Brasil (MLB)", "id": it.get("id"), "link": it.get("permalink"), "coletado_em": S.now(),
                      "caracteristicas": {**{k: v for k, v in at.items() if v}, **dict(list(attrs.items())[:8])}})
    return {"ok": True, "consulta": q, "itens": items, "total_api": ((r or {}).get("paging") or {}).get("total"), "gravado": False,
            "avisos": ["Pré-visualização: nada foi gravado no banco.", "Preço anunciado não é preço de venda efetiva.",
                       "A API não informa vendas de terceiros; nenhuma venda é estimada."]}

