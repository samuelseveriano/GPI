"""Rotas da inteligência regulatória (v0.8)."""
from __future__ import annotations

import json
from datetime import datetime

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import registry as R

ORGAOS = ("Anatel", "Inmetro")
RESULTS = ("encontrado_exato", "encontrado_provavel", "encontrado_semelhante", "nao_encontrado", "fonte_indisponivel", "inconclusivo")


def record_lookup(db, d: dict) -> dict:
    """Consulta manual assistida: registra o que o usuário viu na fonte oficial (nada é inventado pelo GPI)."""
    if d.get("orgao") not in ORGAOS:
        raise ValueError("órgão inválido")
    if d.get("resultado") not in RESULTS:
        raise ValueError("resultado inválido")
    url = (d.get("fonte_url") or "").strip()
    if not url.startswith(("https://", "http://")) or not any(h in url for h in ("anatel.gov.br", "inmetro.gov.br", "gov.br")):
        raise ValueError("informe o endereço da consulta oficial (anatel.gov.br / inmetro.gov.br)")
    ts = datetime.now().isoformat(timespec="seconds")
    cur = db.execute("INSERT INTO regulatory_lookups (orgao, fonte_url, data_consulta, produto_id, consulta, numero_registro, resultado,"
                     " informacoes, responsavel, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (d["orgao"], url[:500], (d.get("data_consulta") or ts[:10])[:10], d.get("produto_id"),
                      json.dumps(d.get("consulta") or {}, ensure_ascii=False)[:2000], (d.get("numero_registro") or "")[:80] or None,
                      d["resultado"], json.dumps(d.get("informacoes") or {}, ensure_ascii=False)[:4000],
                      (d.get("responsavel") or "")[:80] or None, ts))
    return {"id": int(cur.lastrowid), "criado_em": ts}


def lookups(db, produto_id: str | None = None) -> list[dict]:
    rows = db.query("SELECT * FROM regulatory_lookups" + (" WHERE produto_id = ?" if produto_id else "") + " ORDER BY id DESC LIMIT 200",
                    (produto_id,) if produto_id else ())
    for r in rows:
        for k in ("consulta", "informacoes"):
            try:
                r[k] = json.loads(r[k]) if r[k] else {}
            except ValueError:
                pass
    return rows


def search_all(db, q: dict) -> dict:
    org = q.get("orgao") or "todos"
    parts = []
    if org in ("todos", "Anatel"):
        parts.append(R.search_anatel(db, q))
    if org in ("todos", "Inmetro"):
        parts.append(R.search_inmetro(db, q))
    res = [x for p in parts for x in p["resultados"]]
    return {"consulta": q, "por_orgao": parts, "resultados": res, "empresas": R.companies(res),
            "campos": R.FIELD_DOC, "limitacoes": R.LIMITS,
            "manuais": lookups(db, q.get("produto_id")) if q.get("produto_id") else []}


def routes(db, http_factory) -> list[Route]:
    def j(o, code=200):
        return JSONResponse(o, status_code=code)

    async def status(_):
        return j({"anatel": R.anatel_status(db), "inmetro": R.inmetro_status(db), "campos": R.FIELD_DOC, "papeis": R.ROLES,
                  "correspondencias": R.MATCH_LABEL, "limitacoes": R.LIMITS})

    async def search(request):
        q = await request.json()
        return j(await run_in_threadpool(search_all, db, {k: (str(v)[:120] if v is not None else None) for k, v in q.items()}))

    async def compare(request):
        d = await request.json()
        spec, rec = d.get("especificacao") or {}, d.get("registro") or {}
        if not rec:
            res = await run_in_threadpool(search_all, db, {"modelo": spec.get("modelo"), "fabricante": spec.get("fabricante"),
                                                            "numero": spec.get("certificado")})
            cands = res["resultados"][:5]
            return j({"comparacoes": [R.compare(spec, c) for c in cands], "candidatos": len(res["resultados"]),
                      "mensagem": None if cands else "Nenhum registro oficial encontrado para comparar: SEM CORRESPONDÊNCIA CONFIRMADA."})
        return j({"comparacoes": [R.compare(spec, rec)]})

    async def inmetro_file(request):
        form = await request.form()
        f = form.get("arquivo")
        if not f:
            return j({"erro": "envie o arquivo oficial"}, 400)
        raw = await f.read()
        try:
            return j(await run_in_threadpool(R.load_inmetro_file, db, raw, f.filename or "arquivo"))
        except ValueError as e:
            return j({"erro": str(e)}, 400)

    async def manual(request):
        if request.method == "POST":
            try:
                return j(await run_in_threadpool(record_lookup, db, await request.json()))
            except ValueError as e:
                return j({"erro": str(e)}, 400)
        return j({"consultas": await run_in_threadpool(lookups, db, request.query_params.get("produto_id"))})

    return [Route("/api/regulatorio/status", status), Route("/api/regulatorio/pesquisar", search, methods=["POST"]),
            Route("/api/regulatorio/comparar", compare, methods=["POST"]),
            Route("/api/regulatorio/inmetro/arquivo", inmetro_file, methods=["POST"]),
            Route("/api/regulatorio/consultas", manual, methods=["GET", "POST"])]
