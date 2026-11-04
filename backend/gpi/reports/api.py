"""Rotas HTTP do Centro de Relatórios (v0.6)."""
from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from .service import ReportService

MEDIA = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "pdf": "application/pdf",
         "csv": "text/csv; charset=utf-8"}


def routes(svc: ReportService) -> list[Route]:
    def j(o, code=200):
        return JSONResponse(o, status_code=code)

    async def body(request):
        try:
            return await request.json()
        except Exception:  # noqa: BLE001
            return {}

    async def types(_):
        return j({"tipos": await run_in_threadpool(svc.types), "filtros": await run_in_threadpool(svc.filter_options),
                  "relatorio_semanal": bool(svc.cfg.get("auto_report_weekly", False))})

    async def generate(request):
        b = await body(request)
        tipo, fmt = b.get("tipo"), (b.get("formato") or "xlsx").lower()
        filtros = b.get("filtros") if isinstance(b.get("filtros"), dict) else {}
        try:
            r = await run_in_threadpool(svc.generate, tipo, fmt, filtros, "pagina" if b.get("pagina") else "manual")
        except ValueError as e:
            return j({"erro": str(e)}, 400)
        return j(r, 200 if r["status"] == "gerado" else 500)

    async def history(request):
        return j({"relatorios": await run_in_threadpool(svc.history, request.query_params.get("tipo"))})

    async def download(request):
        rid = int(request.path_params["rid"])
        p = await run_in_threadpool(svc.file, rid)
        if not p:
            return j({"erro": "arquivo indisponível (excluído ou com erro)"}, 404)
        fmt = p.suffix.lstrip(".")
        inline = request.query_params.get("abrir") == "1" and fmt == "pdf"
        return FileResponse(p, media_type=MEDIA.get(fmt, "application/octet-stream"), filename=p.name,
                            content_disposition_type="inline" if inline else "attachment")

    async def regenerate(request):
        b = await body(request)
        try:
            r = await run_in_threadpool(svc.regenerate, int(request.path_params["rid"]), b.get("modo") or "snapshot")
        except KeyError as e:
            return j({"erro": str(e)}, 404)
        except ValueError as e:
            return j({"erro": str(e)}, 400)
        return j(r)

    async def delete(request):
        b = await body(request)
        try:
            r = await run_in_threadpool(svc.delete, int(request.path_params["rid"]), b.get("confirmar") is True)
        except PermissionError as e:
            return j({"erro": str(e)}, 400)
        except KeyError as e:
            return j({"erro": str(e)}, 404)
        return j(r)

    async def notifications(request):
        if request.method == "POST":
            await run_in_threadpool(svc.mark_seen)
            return j({"ok": True})
        return j({"novos": await run_in_threadpool(svc.notifications)})

    return [
        Route("/api/reports/types", types),
        Route("/api/reports/generate", generate, methods=["POST"]),
        Route("/api/reports", history),
        Route("/api/reports/notifications", notifications, methods=["GET", "POST"]),
        Route("/api/reports/{rid:int}/download", download),
        Route("/api/reports/{rid:int}/regenerate", regenerate, methods=["POST"]),
        Route("/api/reports/{rid:int}", delete, methods=["DELETE"]),
    ]
