"""Rotas da v0.8 (inteligência de produtos, qualidade, dossiê, investigação, inteligência regulatória)."""
from __future__ import annotations

import threading

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import investigations as INV
from . import semantics, service

_lock = threading.Lock()


def routes(db, sync, cfg) -> list[Route]:
    def j(o, code=200):
        return JSONResponse(o, status_code=code)

    def consumer():
        r = sync.store.load_result("consumer")
        if not r or "testes_multiplos" not in r:
            from ..products import trends
            r = trends.analyze(db, cfg, forecasts=False, today=sync.today_fn())
            sync.store.save_result("consumer", r)
        return r

    def payload(force=False):
        r = None if force else sync.store.load_result(service.RESULT)
        if r and r.get("versao") == "0.8.1":
            return r
        with _lock:
            r = None if force else sync.store.load_result(service.RESULT)
            if not r or r.get("versao") != "0.8.1":
                from ..products.catalog import Catalog
                prods = {p["product_id"]: p for p in Catalog(db, cfg).products()}
                r = service.compute(db, consumer(), prods, sync.today_fn())
                sync.store.save_result(service.RESULT, r)
        return r

    async def overview(_):
        r = await run_in_threadpool(payload)
        top = [x for x in r["ranking"] if x["nivel"] == "investigar"][:15]
        obs = [x for x in r["ranking"] if x["nivel"] == "observar"][:15]
        P = r["produtos"]
        pick = lambda keys: [{"produto_id": k, "produto": P[k]["identificacao"]["produto"], "situacao": P[k]["situacao"],  # noqa: E731
                              "fontes": P[k]["fontes"]} for k in keys if k in P]
        ins = [i for i in r["insights"] if i["situacao"] not in ("EVIDÊNCIA INSUFICIENTE",)][:12]
        return j({"kpis": r["kpis"], "top_investigar": top, "em_observacao": obs, "radar": r["radar"],
                  "emergentes": pick(r["grupos"]["emergentes"] + r["grupos"]["novo_sinal_comercial"] + r["grupos"]["em_observacao"])[:20],
                  "consistentes": pick(r["grupos"]["crescimento_consistente"] + r["grupos"]["interesse_recorrente"])[:20],
                  "alertas": r["alertas"][:40], "comparacao_internacional": r["comparacao_internacional"]["mercados"][:15],
                  "publicos_linguisticos": r["comparacao_internacional"]["publicos_linguisticos"][:15],
                  "insights": ins, "contagens": r["contagens"], "gates": {k: v.get("status") for k, v in r["gates"].items()},
                  "gerado_em": r.get("_gerado_em") or r["gerado_em"], "aviso": r["aviso"]})

    async def executive(_):
        """v0.8.1 — dashboard executivo (seções A–H)."""
        r = await run_in_threadpool(payload)
        k, P = r["kpis"], r["produtos"]
        rad = r.get("radar_candidatos") or []
        top = [x for x in rad if x["estado"] in ("Investigação recomendada", "Evidência comercial recorrente", "Investigação iniciada")][:12]
        prelim = [x for x in rad if x["estado"] in ("Novo sinal", "Em observação")][:15]
        comm = []
        for pid, p in P.items():
            for e in p["evidencias"]:
                if e["tipo"] in ("COMMERCIAL_SEARCH_INTENT", "SEARCH_INTEREST"):
                    d = e["derivado"]
                    comm.append({"produto_id": pid, "produto": p["identificacao"]["produto"], "fonte": e["fonte_nome"],
                                 "mercado": e["mercado"], "indicador": e["indicador"], "classe": e.get("classe_nome"),
                                 "historico": d.get("historico"), "valores": None if d.get("historico") else
                                 (e.get("serie_valores") or None), "semanas": d.get("semanas_presente"),
                                 "persistencia": d.get("persistencia"), "momentum": d.get("momentum"),
                                 "melhor_posicao": d.get("melhor_posicao"), "situacao": p["situacao"]})
        comm.sort(key=lambda x: (x["fonte"] != "Mercado Livre", -(x["semanas"] or 0), -(x["persistencia"] or 0)))
        al = (r.get("alertas_v081") or {}).get("itens", [])
        important = [a for a in al if a["severidade"] in ("alta", "média") and a["categoria_alerta"] in ("comercial", "qualidade")][:10]
        ins = [i for i in r["insights"] if i["situacao"] not in ("EVIDÊNCIA INSUFICIENTE", "ATENÇÃO PÚBLICA EM ALTA")][:8]
        fontes = r.get("fontes") or []
        health = {"funcionais": sum(1 for f in fontes if f["estado"] == "funcional"),
                  "com_falha": sum(1 for f in fontes if f["estado"] == "falhou"),
                  "sem_credenciais": sum(1 for f in fontes if f["estado"] in ("requer_autorizacao", "nao_configurada")),
                  "ultima_coleta": max((f["ultima_coleta_ok"] or "" for f in fontes), default="") or None,
                  "series_elegiveis": r["gates"]["4"]["elegiveis"], "gates": {g: v.get("status") for g, v in r["gates"].items()},
                  "problemas": [a for a in al if a["categoria_alerta"] == "qualidade"][:6]}
        return j({"panorama": {**{x: k.get(x) for x in ("produtos_monitorados", "produtos_com_dados_recentes", "com_evidencia_comercial",
                                                        "novos_sinais", "interesse_recorrente", "crescimento_confirmado", "em_investigacao",
                                                        "cobertura_comercial", "cobertura_comercial_formula", "ultima_atualizacao")}},
                  "coberturas": r.get("coberturas"), "top_investigacao": top, "radar_comercial": comm[:20],
                  "preliminares": prelim, "internacional": r["comparacao_internacional"], "alertas": important,
                  "insights": ins, "saude": health, "gerado_em": r.get("_gerado_em") or r["gerado_em"], "aviso": r["aviso"]})

    async def alerts_v081(request):
        r = await run_in_threadpool(payload)
        a = r.get("alertas_v081") or {"itens": []}
        q = request.query_params
        items = a["itens"]
        for key, field in (("categoria_alerta", "categoria_alerta"), ("mercado", "mercado"), ("categoria", "categoria"),
                           ("tipo", "tipo"), ("fonte", "fonte"), ("produto", "produto_id"), ("severidade", "severidade")):
            if q.get(key):
                items = [x for x in items if str(x.get(field) or "") == q[key]]
        if q.get("desde"):
            items = [x for x in items if (x.get("data") or "") >= q["desde"]]
        return j({**a, "itens": items[:300], "total": len(items)})

    async def candidates(_):
        r = await run_in_threadpool(payload)
        from .commercial import RADAR_STATES
        return j({"itens": r.get("radar_candidatos") or [], "estados": RADAR_STATES, "coberturas": r.get("coberturas"),
                  "aviso": "Recomendar investigação não exige tendência comprovada — a incerteza de cada item é explicada."})

    async def discovery_view(_):
        r = await run_in_threadpool(payload)
        from . import discovery
        ev = await run_in_threadpool(discovery.evaluate)
        return j({**(r.get("descoberta") or {}), "avaliacao": {k: v for k, v in ev.items() if k != "erros"}, "erros_avaliacao": ev["erros"]})

    async def dossier(request):
        pid = request.path_params["pid"]
        r = await run_in_threadpool(payload)
        p = r["produtos"].get(pid) or r["produtos"].get(pid.split(":")[0])
        if not p:
            return j({"produto_id": pid, "situacao": "EVIDÊNCIA INSUFICIENTE", "evidencias": [],
                      "mensagem": "Produto sem evidências coletadas: ausência de dados não indica baixa demanda."})
        ins = next((i for i in r["insights"] if i["produto_id"] == p["produto_id"]), None)
        clu = next((g["nome"] for g in r["clusters"].get("grupos", []) if p["produto_id"] in g["produtos"]), None)
        inv = db.query("SELECT id, estado FROM investigations WHERE produto_id = ? ORDER BY id DESC LIMIT 1", (p["produto_id"],))
        return j({**p, "insight": ins, "cluster": clu, "investigacao": inv[0] if inv else None})

    async def products(_):
        r = await run_in_threadpool(payload)
        return j({"ranking": r["ranking"], "grupos": r["grupos"], "contagens": r["contagens"], "clusters": r["clusters"],
                  "classes": r["classes"], "aviso": r["aviso"]})

    async def quality_page(_):
        r = await run_in_threadpool(payload)
        g = await run_in_threadpool(service.gates_full, db, r)
        return j({"gates": g, "fontes_por_indicador": r["fontes_por_indicador"]})

    async def metrics(_):
        return j(semantics.catalog())

    async def ml_rank(_):
        r = await run_in_threadpool(payload)
        return j(r["mercado_livre"])

    async def recompute(_):
        r = await run_in_threadpool(payload, True)
        return j({"ok": True, "segundos": r["segundos"], "produtos": len(r["produtos"])})

    async def inv_list(request):
        if request.method == "POST":
            try:
                return j(await run_in_threadpool(INV.add, db, await request.json()))
            except ValueError as e:
                return j({"erro": str(e)}, 400)
        return j(await run_in_threadpool(INV.list_all, db, request.query_params.get("estado")))

    async def inv_one(request):
        iid = request.path_params["iid"]
        if request.method == "POST":
            try:
                return j(await run_in_threadpool(INV.update, db, iid, await request.json()))
            except KeyError as e:
                return j({"erro": str(e)}, 404)
            except ValueError as e:
                return j({"erro": str(e)}, 400)
        r = await run_in_threadpool(INV.get, db, iid)
        return j(r) if r else j({"erro": "não encontrada"}, 404)

    return [Route("/api/v08/visao", overview), Route("/api/v08/produtos", products), Route("/api/v08/dossie/{pid:path}", dossier),
            Route("/api/v08/qualidade", quality_page), Route("/api/v08/metricas", metrics), Route("/api/v08/mercado-livre", ml_rank),
            Route("/api/v08/recalcular", recompute, methods=["POST"]),
            Route("/api/v081/executivo", executive), Route("/api/v081/alertas", alerts_v081),
            Route("/api/v081/candidatos", candidates), Route("/api/v081/descoberta", discovery_view),
            Route("/api/v08/investigacoes", inv_list, methods=["GET", "POST"]),
            Route("/api/v08/investigacoes/{iid:int}", inv_one, methods=["GET", "POST"])]


def _payload_for_v09(db, sync, cfg):
    """v0.9: mesmo resultado da inteligência (calculado sob o mesmo lock), para as rotas de decisão."""
    r = sync.store.load_result(service.RESULT)
    if r and r.get("versao") == "0.8.1":
        return r
    with _lock:
        r = sync.store.load_result(service.RESULT)
        if not r or r.get("versao") != "0.8.1":
            from ..products import trends
            from ..products.catalog import Catalog
            cons = sync.store.load_result("consumer")
            if not cons or "testes_multiplos" not in cons:
                cons = trends.analyze(db, cfg, forecasts=False, today=sync.today_fn())
                sync.store.save_result("consumer", cons)
            prods = {p["product_id"]: p for p in Catalog(db, cfg).products()}
            r = service.compute(db, cons, prods, sync.today_fn())
            sync.store.save_result(service.RESULT, r)
    return r
