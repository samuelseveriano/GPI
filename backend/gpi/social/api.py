"""Rotas HTTP de Tendências nas Redes Sociais e do Opportunity Engine 3.0 (v0.6)."""
from __future__ import annotations

import threading

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route

from .store import PLATFORM_NAMES

CONNECT = {
    "tiktok": "Central de Integrações → TikTok: conta TikTok for Business, app no portal TikTok API for Business com o escopo "
              "de Discovery e autorização OAuth (advertiser_id para hashtags; conta TikTok/open_id para termos de busca).",
    "instagram": "Central de Integrações → Meta: conta profissional do Instagram vinculada a uma página, app Meta com "
                 "instagram_basic e o recurso Instagram Public Content Access aprovado na revisão do app.",
    "facebook": "Central de Integrações → Meta e, em Configurações, a lista de páginas a acompanhar (páginas que você "
                "administra; páginas públicas exigem o recurso Page Public Content Access).",
    "youtube": "Central de Integrações → YouTube: chave gratuita da YouTube Data API v3. Para entrar nos índices combinados, "
               "confirme em Configurações a aceitação do caso de uso 'Analytics & Reporting'.",
    "meta_ads": "Central de Integrações → Meta, identidade verificada na Meta e ativação em Configurações (somente anúncios da UE).",
    "reddit": "Central de Integrações → Reddit (uso não comercial ou contrato com o Reddit).",
}


def routes(db, sync, cfg) -> list[Route]:
    lock = threading.Lock()

    def social() -> dict:
        r = sync.store.load_result("social")
        if r:
            return r
        with lock:
            r = sync.store.load_result("social")
            if not r:
                from . import analysis
                r = analysis.analyze(db, cfg, consumer=sync.store.load_result("consumer") or {})
                sync.store.save_result("social", r)
        return r

    def opp3() -> dict:
        r = sync.store.load_result("opportunity3")
        if r:
            return r
        from ..products import opportunity3
        r = opportunity3.build(sync.store.load_result("consumer") or {}, social(), sync.store.load_result("reviews2"),
                               sync.store.load_result("competition"), db)
        sync.store.save_result("opportunity3", r)
        return r

    def j(o, code=200):
        return JSONResponse(o, status_code=code)

    async def overview(_):
        r = await run_in_threadpool(social)
        ranking = sorted(r["scores"].values(), key=lambda v: -(v["social_trend_score"] or 0))
        return j({"plataformas": r["plataformas"], "ranking": ranking[:100], "radar_contagem": {k: len(v) for k, v in r["radar"].items()},
                  "search_vs_social": r["search_vs_social"][:100], "avisos": r["avisos"], "pesos": r["pesos"],
                  "metricas": r["metricas"], "gerado_em": r.get("_gerado_em") or r["gerado_em"], "como_conectar": CONNECT})

    async def platform(request):
        p = request.path_params["pid"]
        if p not in PLATFORM_NAMES:
            return j({"erro": "plataforma desconhecida"}, 404)
        r = await run_in_threadpool(social)
        series = [s for s in r["series"] if s["platform"] == p]
        series.sort(key=lambda s: -((s["ind"].get("crescimento") or -9)))
        return j({"plataforma": p, "nome": PLATFORM_NAMES[p], "status": r["plataformas"].get(p), "series": series[:200],
                  "hashtags": [h for h in r["hashtags"] if h["platform"] == p][:200], "como_conectar": CONNECT.get(p),
                  "metricas": {k: v for k, v in r["metricas"].items()}, "avisos": r["avisos"]})

    async def viral(_):
        r = await run_in_threadpool(social)
        return j({"radar": r["radar"], "avisos": r["avisos"] + ["Um produto viral não tem demanda comercial sustentável garantida."]})

    async def opportunities(_):
        return j(await run_in_threadpool(opp3))

    return [Route("/api/social/overview", overview), Route("/api/social/platform/{pid}", platform),
            Route("/api/social/viral", viral), Route("/api/opportunities3", opportunities)]
