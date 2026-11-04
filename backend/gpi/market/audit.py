"""Auditoria de todas as fontes (v0.7.1) — matriz A–F gerada a partir do estado REAL do banco e dos conectores.

A configuração · B autenticação · C coleta · D processamento · E persistência · F visualização.
Nada é inferido de testes simulados: "validada" exige coleta real gravada; um token aceito não torna a fonte funcional.
Os conectores são descobertos automaticamente no registro (não há lista fixa).
"""
from __future__ import annotations

from ..connectors.registry import REMOVED_SOURCES, all_connectors
from ..integrations import registry as integ

LABEL = {"nao_configurada": "Não configurada", "aguardando_autorizacao": "Aguardando autorização", "autenticada": "Autenticada",
         "api_validada": "API validada", "coletando": "Coletando", "dados_armazenados": "Dados armazenados",
         "funcional": "Funcional", "restrita": "Restrita", "falha": "Falha", "sem_coleta": "Sem coleta ainda"}


def _counts(db, cid: str) -> dict:
    def q(sql, p=(cid,)):
        try:
            return db.query(sql, p)[0]
        except Exception:  # noqa: BLE001 — tabela ausente em bancos antigos
            return {}
    ms = q("SELECT COUNT(DISTINCT s.id) AS series, COUNT(o.series_id) AS obs, MAX(o.ref_date) AS ultima, "
           "SUM(CASE WHEN s.product_key IS NOT NULL THEN 1 ELSE 0 END) AS com_produto FROM market_series s "
           "LEFT JOIN market_obs o ON o.series_id = s.id WHERE s.source = ?")
    so = q("SELECT COUNT(*) AS n, SUM(CASE WHEN product_id IS NOT NULL THEN 1 ELSE 0 END) AS com_produto, "
           "SUM(commercial) AS comerciais, COUNT(DISTINCT country) AS paises, MAX(ref_date) AS ultima, "
           "COUNT(DISTINCT term) AS termos FROM search_observations WHERE source = ?")
    ci = q("SELECT COUNT(*) AS n, SUM(CASE WHEN product_key IS NOT NULL THEN 1 ELSE 0 END) AS com_produto, "
           "MAX(published_at) AS ultima FROM content_items WHERE source = ?")
    sc = q("SELECT COUNT(*) AS n, SUM(CASE WHEN product_id IS NOT NULL THEN 1 ELSE 0 END) AS com_produto, MAX(ref_date) AS ultima "
           "FROM social_observations WHERE platform = ?")
    jobs = db.query("SELECT state, COUNT(*) AS n FROM sync_jobs WHERE source = ? GROUP BY state", (cid,))
    last_err = db.query("SELECT last_error, updated_at FROM sync_jobs WHERE source = ? AND state = 'failed' ORDER BY updated_at DESC "
                        "LIMIT 1", (cid,))
    reg = int(ms.get("obs") or 0) + int(so.get("n") or 0) + int(ci.get("n") or 0) + int(sc.get("n") or 0)
    linked = int(ms.get("com_produto") or 0) + int(so.get("com_produto") or 0) + int(ci.get("com_produto") or 0) + int(sc.get("com_produto") or 0)
    ult = max([x for x in (ms.get("ultima"), so.get("ultima"), (ci.get("ultima") or "")[:10], sc.get("ultima")) if x] or [None])
    return {"registros": reg, "ligados_a_produto": linked, "ultima_data": ult, "jobs": {r["state"]: r["n"] for r in jobs},
            "ultimo_erro": (last_err[0]["last_error"] or "")[:300] if last_err else None,
            "termos": so.get("termos"), "paises": so.get("paises"), "series": ms.get("series")}


def audit(db, store, creds, cfg: dict, connectors=None) -> dict:
    conns = connectors if connectors is not None else all_connectors()
    st = store.source_status()
    by_conn = {c: p for p in integ.PROVIDERS for c in p.get("conectores", [])}

    class Ctx:
        pass
    ctx = Ctx()
    ctx.cfg, ctx.creds = cfg, creds
    rows = []
    for c in conns:
        p = by_conn.get(c.id) or {}
        tipo = p.get("tipo", "auto")
        needs_auth = tipo not in ("auto",) and tipo != "optin"
        cfields = [f["nome"] for f in p.get("campos", [])]
        saved = creds.get(p["id"]) if p.get("id") and creds is not None else {}
        configured = (not needs_auth) or bool(saved and any(saved.get(f) for f in cfields)) or bool(saved.get("access_token"))
        try:
            available = bool(c.available(ctx))
        except Exception:  # noqa: BLE001
            available = False
        s = st.get(c.id) or {}
        n = _counts(db, c.id)
        has_token = bool(saved.get("access_token") or saved.get("refresh_token") or saved.get("api_key"))
        # etapa final, da mais forte para a mais fraca
        if tipo == "approval" and not available:
            fase = "restrita"
        elif not configured:
            fase = "nao_configurada"
        elif not available:
            fase = "aguardando_autorizacao"
        elif s.get("state") == "falhou" and not n["registros"]:
            fase = "falha"
        elif n["registros"] and s.get("last_success") and n["ligados_a_produto"]:
            fase = "funcional"
        elif n["registros"]:
            fase = "dados_armazenados"
        elif s.get("validated"):
            fase = "api_validada"
        elif n["jobs"].get("running") or n["jobs"].get("pending"):
            fase = "coletando"
        elif needs_auth and has_token:
            fase = "autenticada"
        elif n["jobs"].get("failed"):
            fase = "falha"
        else:
            fase = "api_validada" if s.get("last_success") else "sem_coleta" if not needs_auth else "autenticada"
        rows.append({
            "fonte": c.id, "nome": c.name, "integracao": p.get("id"), "documentacao": getattr(c, "docs_url", None),
            "A_configuracao": {"registrado": True, "exige_autenticacao": needs_auth, "credenciais_configuradas": configured,
                               "habilitado": available, "tipo": tipo},
            "B_autenticacao": {"token_salvo": has_token, "precisa_reconectar": bool(saved.get("precisa_reconectar")),
                               "estado_salvo": s.get("state")},
            "C_coleta": {"jobs": n["jobs"], "ultimo_erro": n["ultimo_erro"] or (s.get("message") if s.get("state") == "falhou" else None),
                         "ultima_tentativa": s.get("last_attempt"), "ultima_coleta_ok": s.get("last_success")},
            "D_processamento": {"termos_distintos": n["termos"], "paises": n["paises"], "series": n["series"]},
            "E_persistencia": {"registros": n["registros"], "registros_status": s.get("records"),
                               "contagem_consistente": int(s.get("records") or 0) == n["registros"] if s else None,
                               "ultima_data": n["ultima_data"]},
            "F_visualizacao": {"ligados_a_produto": n["ligados_a_produto"],
                               "aparece_no_dashboard": bool(n["ligados_a_produto"])},
            "fase": fase, "fase_rotulo": LABEL[fase],
        })
    removed = [{"fonte": k, "nome": v[0], "motivo": v[1]} for k, v in REMOVED_SOURCES.items()]
    resumo = {}
    for r in rows:
        resumo[r["fase"]] = resumo.get(r["fase"], 0) + 1
    return {"fontes": rows, "resumo": {LABEL[k]: v for k, v in resumo.items()}, "removidas": removed}


def markdown(a: dict) -> str:
    out = ["| Fonte | Autenticação | Credenciais | Habilitada | Última coleta OK | Registros | Ligados a produto | Fase | Último erro |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in a["fontes"]:
        A, C, E, F = r["A_configuracao"], r["C_coleta"], r["E_persistencia"], r["F_visualizacao"]
        out.append(f"| {r['nome']} | {'sim' if A['exige_autenticacao'] else 'não'} | {'sim' if A['credenciais_configuradas'] else 'não'} | "
                   f"{'sim' if A['habilitado'] else 'não'} | {(C['ultima_coleta_ok'] or '—')[:16]} | {E['registros']} | "
                   f"{F['ligados_a_produto']} | {r['fase_rotulo']} | {(C['ultimo_erro'] or '').replace('|', '/')[:120]} |")
    return "\n".join(out)
