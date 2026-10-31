"""
API HTTP local (Starlette — a mesma base do FastAPI) e servidor dos arquivos da interface.
Escuta apenas em 127.0.0.1. Requisições com cabeçalho Host diferente de
localhost/127.0.0.1 são recusadas (proteção contra DNS rebinding).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import secrets
from urllib.parse import unquote, urlsplit
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__, db as dbmod, services as sv
from .demo import DEMO_SOURCE, make_demo_csv
from .forecasting.models import MODELS
from .importer import ImportErrorGPI, import_file
from .market import service as msv
from .market.analysis import make_analyzer
from .market.sync import SyncManager
from .integrations import registry as integ
from .integrations.oauth import PendingFlows, authorize_url
from starlette.responses import HTMLResponse

log = logging.getLogger("gpi")
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


class HostGuard(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"erro": "acesso permitido apenas localmente"}, 403)
        # Proteção CSRF: chamadas que alteram estado exigem o cabeçalho X-GPI (força preflight CORS,
        # que este servidor não autoriza) e, se houver Origin, ele deve ser o próprio GPI.
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.url.path.startswith("/api/") \
                and request.url.path != "/api/shutdown":
            origin = request.headers.get("origin")
            if request.headers.get("x-gpi") != "1":
                return JSONResponse({"erro": "requisição recusada (cabeçalho de segurança ausente)"}, 403)
            if origin and urlsplit(origin).hostname not in ALLOWED_HOSTS:
                return JSONResponse({"erro": "origem não permitida"}, 403)
        resp = await call_next(request)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "no-cache"
        return resp


def err(msg, code=400):
    return JSONResponse({"erro": msg}, code)


def to_csv(rows: list[dict], filename: str) -> Response:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow({k: (str(v).replace(".", ",") if isinstance(v, float) else v)
                        for k, v in r.items()})
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def to_xlsx(rows: list[dict], filename: str, sheet="Dados", notes: list[str] | None = None):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    if rows:
        ws.append(list(rows[0].keys()))
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append([v if not isinstance(v, (list, dict)) else json.dumps(v) for v in r.values()])
    if notes:
        ws2 = wb.create_sheet("Notas")
        for n in notes:
            ws2.append([n])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def create_app(data_dir: Path, frontend_dir: Path, shutdown_cb=None, cfg: dict | None = None,
               sync_http=None, connectors=None, start_sync: bool = False, today_fn=None) -> Starlette:
    cfg = cfg or {}
    data_dir.mkdir(parents=True, exist_ok=True)
    ext = ".duckdb" if dbmod.ENGINE == "duckdb" else ".sqlite"
    db = dbmod.Database(data_dir / f"gpi{ext}")
    sync = SyncManager(db, data_dir, cfg, connectors=connectors, http=sync_http,
                       analyzer=make_analyzer(cfg), today_fn=today_fn)
    if start_sync:
        sync.start_scheduler()
    token = secrets.token_urlsafe(24)
    (data_dir / "shutdown.token").write_text(token)

    async def body_json(request):
        try:
            return await request.json()
        except Exception:
            return {}

    async def health(_):
        return JSONResponse({"ok": True, "versao": __version__, "app": "gpi-global-product-intelligence"})

    async def status(_):
        st = sv.status(db, dbmod.ENGINE)
        st["versao"] = __version__
        st["modelos"] = {k: v[0] for k, v in MODELS.items()}
        return JSONResponse(st)

    async def do_import(request: Request):
        name = unquote(request.headers.get("x-filename", "arquivo.csv"))
        content = await request.body()
        try:
            res = import_file(db, Path(name).name, content)
        except ImportErrorGPI as e:
            return err(str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("falha na importação")
            return err(f"não foi possível ler o arquivo: {e}")
        log.info("importação %s: %s linhas válidas, %s rejeitadas", res["import_id"],
                 res["linhas_validas"], res["linhas_rejeitadas"])
        return JSONResponse(res)

    async def demo(_):
        try:
            res = import_file(db, "dados_demonstrativos.csv", make_demo_csv(),
                              source=DEMO_SOURCE, is_demo=True)
        except ImportErrorGPI as e:
            return err(str(e))
        return JSONResponse(res)

    async def delete_import(request):
        db.delete_import(int(request.path_params["iid"]))
        return JSONResponse({"ok": True})

    async def skus(request):
        q = request.query_params
        return JSONResponse(sv.skus(db, q.get("q", ""), q.get("categoria", "")))

    async def history(request):
        q = request.query_params
        try:
            return JSONResponse(sv.history(db, q["sku"], q.get("freq", "M"),
                                           q.get("zero_fill", "1") == "1"))
        except (ValueError, KeyError) as e:
            return err(str(e))

    async def overview(request):
        return JSONResponse(sv.overview(db, request.query_params.get("freq", "M")))

    async def trends(request):
        return JSONResponse(await run_in_threadpool(sv.trends_table, db, request.query_params.get("freq", "M")))

    async def abcxyz(request):
        q = request.query_params
        return JSONResponse(await run_in_threadpool(sv.abcxyz, db, q.get("freq", "M"), int(q.get("n", 12))))

    async def forecast(request):
        b = await body_json(request)
        try:
            h = int(b.get("horizon", 6))
            if not 1 <= h <= 104:
                return err("horizonte deve estar entre 1 e 104 períodos")
            if not isinstance(b.get("sku"), str) or not b["sku"]:
                return err("'sku' deve ser um texto")
            if b.get("models") is not None and not (isinstance(b["models"], list)
                                                    and all(isinstance(x, str) for x in b["models"])):
                return err("'models' deve ser uma lista de nomes de modelos")
            res = await run_in_threadpool(sv.forecast, db, b["sku"], b.get("freq", "M"), h, b.get("models"),
                              b.get("criterion", "wape"), int(b.get("n_origins", 6)),
                              bool(b.get("zero_fill", True)))
        except (ValueError, KeyError) as e:
            return err(str(e))
        return JSONResponse(res)

    async def run(request):
        try:
            return JSONResponse(sv.get_run(db, int(request.path_params["rid"])))
        except KeyError:
            return err("execução não encontrada", 404)

    async def runs(_):
        return JSONResponse(db.query(
            "SELECT id, created_at, sku, freq, horizon, model FROM forecast_runs ORDER BY id DESC LIMIT 50"))

    async def inventory(request):
        b = await body_json(request)
        try:
            p = {k: float(b[k]) for k in ("lead_time_days", "review_days", "service_level",
                                          "on_hand", "in_transit")}
            for k in ("moq", "order_multiple", "lead_time_sd_days", "unit_cost",
                      "order_cost", "holding_rate_year"):
                if b.get(k) not in (None, ""):
                    p[k] = float(b[k])
            if not 0.5 <= p["service_level"] < 1:
                return err("nível de serviço deve estar entre 50% e 99,9%")
            return JSONResponse(sv.inventory_plan(db, int(b["run_id"]), b.get("model"), p))
        except (KeyError, ValueError) as e:
            return err(f"parâmetro inválido: {e}")

    async def export(request):
        kind, fmt = request.path_params["kind"], request.path_params["fmt"]
        q = request.query_params
        notes = ["Gerado pelo GPI — Global Product Intelligence", f"Versão {__version__}"]
        if kind == "abcxyz":
            data = sv.abcxyz(db, q.get("freq", "M"), int(q.get("n", 12)))
            rows = data["linhas"]
            notes.append(f"Base ABC: {data.get('base_abc')}; janela {data.get('janela')}")
        elif kind == "previsao":
            p = sv.get_run(db, int(q["run_id"]))
            mk = q.get("model") or p["modelo_escolhido"]
            f = p["modelos"][mk]
            rows = [{"periodo": lab, "previsao": f["previsao"][i], "lim_inf_80": f["lo80"][i],
                     "lim_sup_80": f["hi80"][i], "lim_inf_95": f["lo95"][i],
                     "lim_sup_95": f["hi95"][i]} for i, lab in enumerate(p["labels_futuro"])]
            bt = p["backtest"]["resultados"].get(mk, {})
            notes += [f"SKU {p['sku']} — modelo {f['nome']}",
                      f"Backtesting: WAPE={bt.get('wape')}, MAE={bt.get('mae')}, "
                      f"RMSSE={bt.get('rmsse')}, cobertura 80%={bt.get('cobertura_80')}",
                      "Previsões são estimativas estatísticas, não fatos."]
        elif kind == "historico":
            h = sv.history(db, q["sku"], q.get("freq", "M"))
            rows = [{"periodo": l, "quantidade": v} for l, v in zip(h["labels"], h["valores"])]
        elif kind == "backtest":
            p = sv.get_run(db, int(q["run_id"]))
            rows = [{"modelo": p["nomes"].get(k, k), **v} for k, v in p["backtest"]["resultados"].items()]
        else:
            return err("tipo de exportação desconhecido", 404)
        fname = f"gpi_{kind}.{fmt}"
        if fmt == "csv":
            return to_csv(rows, fname)
        if fmt == "xlsx":
            return to_xlsx(rows, fname, notes=notes)
        return err("formato inválido")

    async def backup(_):
        path = db.backup(data_dir / "backups")
        return JSONResponse({"arquivo": path.name})

    async def shutdown(request):
        if request.headers.get("x-token") != token:
            return err("token inválido", 403)
        if shutdown_cb:
            shutdown_cb()
        return JSONResponse({"ok": True})

    # ------------------------------------------------------------ inteligência de mercado (Fase 2)
    async def sync_status(_):
        runs = db.query("SELECT id, started_at, finished_at, trigger, state FROM sync_runs ORDER BY id DESC LIMIT 10")
        return JSONResponse({**sync.state, "ultimas": runs, "devida": sync.due(),
                             "auto_sync": cfg.get("auto_sync", True)})

    async def sync_run(_):
        return JSONResponse({"iniciada": sync.start("manual")})

    async def sync_cancel(_):
        sync.cancel()
        return JSONResponse({"ok": True})

    async def m_sources(_):
        return JSONResponse(msv.sources(sync.store, sync.connectors, cfg, sync.creds))

    async def m_overview(_):
        return JSONResponse(await run_in_threadpool(msv.overview, sync.store))

    async def m_series(request):
        q = request.query_params
        rows = sync.store.series(source=q.get("source"), product_key=q.get("product_key"))
        return JSONResponse(sv._clean(rows[:2000]))

    async def m_series_one(request):
        p = msv.series_payload(sync.store, int(request.path_params["sid"]))
        return JSONResponse(p) if p else err("série não encontrada", 404)

    async def m_product(request):
        p = msv.product(sync.store, request.path_params["key"])
        return JSONResponse(p) if p else err("produto não encontrado", 404)

    async def m_search(request):
        return JSONResponse(msv.search(sync.store, request.query_params.get("q", "")))

    async def m_forecasts(_):
        return JSONResponse(await run_in_threadpool(msv.forecasts, sync.store))

    async def m_opps(_):
        return JSONResponse(sync.store.load_result("opportunities") or {})

    async def m_clusters(_):
        return JSONResponse(sync.store.load_result("clusters") or {})

    async def m_export(request):
        fmt = request.path_params["fmt"]
        items = (sync.store.load_result("opportunities") or {}).get("itens", [])
        rows = [{"produto": i["nome"], "chave": i["product_key"], "categoria": i["categoria"], "score": i["score"],
                 "rotulo": i["rotulo"], "crescimento_12m": i["crescimento_12m"], "fontes": ", ".join(i["fontes"]),
                 "evidencias": " | ".join(i["evidencias"]), "riscos": " | ".join(i["riscos"]),
                 **{f"comp_{k}": v for k, v in i["componentes"].items()}} for i in items]
        notes = ["Score heurístico de oportunidade (0–100). NÃO é probabilidade de sucesso.",
                 "Não constitui recomendação de importação: custos, margem, demanda e risco precisam ser estimados."]
        if fmt == "csv":
            return to_csv(rows, "gpi_oportunidades.csv")
        return to_xlsx(rows, "gpi_oportunidades.xlsx", "Oportunidades", notes)

    # ------------------------------------------------------------ Central de Integrações (Fase 3)
    flows = PendingFlows()
    EDITABLE_SETTINGS = {"rss_feeds", "google_news_optin", "youtube_daily_units", "auto_sync", "proxy", "ca_bundle",
                         "contact"}

    def save_user_settings(values: dict):
        uf = data_dir / "config.json"
        try:
            cur = json.loads(uf.read_text(encoding="utf-8")) if uf.exists() else {}
        except ValueError:
            cur = {}
        cur.update(values)
        uf.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        cfg.update(values)

    def redirect_uri(request) -> str:
        return f"http://127.0.0.1:{request.url.port or 8765}{integ.REDIRECT_PATH}"

    async def integrations(request):
        st = sync.store.source_status()
        cons = {c.id: c for c in sync.connectors}
        ctx = sync.context()
        out = []
        for p in integ.PROVIDERS:
            states = []
            for cid in p["conectores"]:
                c = cons.get(cid)
                s0 = st.get(cid) or {}
                avail = c.available(ctx) if c else False
                states.append({"id": cid, "nome": c.name if c else cid, "disponivel": avail,
                               "estado": (s0.get("state") or "nao_testada") if avail else "restrita",
                               "validada": bool(s0.get("validated")), "ultima_coleta": s0.get("last_success"),
                               "registros": s0.get("records", 0), "mensagem": s0.get("message"),
                               "cobertura": [s0.get("coverage_start"), s0.get("coverage_end")]})
            conectado = any(x["disponivel"] for x in states)
            item = {**{k: v for k, v in p.items() if k not in ("auth_url", "token_url")}, "conectores": states,
                    "conectado": conectado, "credenciais": sync.creds.masked(p["id"]),
                    "protecao": sync.creds.protection}
            if p["tipo"] == "oauth":
                item["redirect_uri"] = redirect_uri(request)
            if p["id"] == "rss":
                from .connectors.content import RSS_DEFAULT
                item["feeds"] = cfg.get("rss_feeds") or RSS_DEFAULT
            if p["id"] == "google_news":
                item["optin"] = bool(cfg.get("google_news_optin"))
                item["conectado"] = item["optin"]
            if p["id"] == "youtube":
                item["cota_diaria"] = cfg.get("youtube_daily_units", 3000)
            out.append(item)
        return JSONResponse(sv._clean(out))

    async def integ_credentials(request):
        p = integ.provider(request.path_params["pid"])
        if not p or not p.get("campos"):
            return err("esta integração não usa credenciais", 404)
        b = await body_json(request)
        allowed = {f["nome"]: f for f in p["campos"]}
        values = {}
        for k, v in b.items():
            if k in allowed:
                values[k] = bool(v) if allowed[k].get("checkbox") else str(v).strip()[:500]
        if not values:
            return err("nenhum campo válido informado")
        sync.creds.set(p["id"], values)
        log.info("credenciais atualizadas para %s (campos: %s)", p["id"], ", ".join(values))
        return JSONResponse({"ok": True, "credenciais": sync.creds.masked(p["id"])})

    async def integ_delete(request):
        pid = request.path_params["pid"]
        sync.creds.delete(pid)
        if pid == "google_news":
            save_user_settings({"google_news_optin": False})
        return JSONResponse({"ok": True})

    async def integ_test(request):
        pid = request.path_params["pid"]
        ok, msg = await run_in_threadpool(integ.test_connection, pid, sync.http, sync.creds, cfg)
        return JSONResponse({"ok": ok, "mensagem": msg})

    async def integ_sync(request):
        p = integ.provider(request.path_params["pid"])
        if not p:
            return err("integração desconhecida", 404)
        return JSONResponse({"iniciada": sync.start("manual", p["conectores"])})

    async def integ_settings(request):
        b = await body_json(request)
        vals = {k: v for k, v in b.items() if k in EDITABLE_SETTINGS}
        if "rss_feeds" in vals:
            feeds = []
            for f in vals["rss_feeds"][:50]:
                u = str(f.get("url", "")).strip()
                if urlsplit(u).scheme in ("http", "https") and urlsplit(u).netloc:
                    feeds.append({"nome": str(f.get("nome") or urlsplit(u).netloc)[:80], "url": u,
                                  "idioma": f.get("idioma", "pt")})
            vals["rss_feeds"] = feeds
        if "youtube_daily_units" in vals:
            vals["youtube_daily_units"] = max(100, min(10000, int(vals["youtube_daily_units"])))
        save_user_settings(vals)
        return JSONResponse({"ok": True})

    async def oauth_start(request):
        p = integ.provider(request.path_params["pid"])
        if not p or p["tipo"] != "oauth":
            return err("integração sem OAuth", 404)
        c = sync.creds.get(p["id"])
        if not c.get("client_id"):
            return err("informe primeiro o App ID (client_id)")
        state, verifier = flows.start(p["id"], {"redirect_uri": redirect_uri(request)})
        return JSONResponse({"url": authorize_url(p["auth_url"], c["client_id"], redirect_uri(request), state, verifier)})

    async def oauth_callback(request):
        q = request.query_params
        page = lambda title, msg: HTMLResponse(
            f"<!doctype html><meta charset=utf-8><title>GPI</title><body style='font-family:sans-serif;padding:40px'>"
            f"<h2>{title}</h2><p>{msg}</p><p>Pode fechar esta janela e voltar ao GPI.</p></body>")
        f = flows.consume(q.get("state", ""))
        if not f:
            return page("Conexão não concluída", "Pedido expirado ou inválido (proteção contra falsificação). Tente novamente.")
        if q.get("error"):
            return page("Conexão recusada", "O provedor informou: " + str(q.get("error"))[:200])
        p = integ.provider(f["provider"])
        c = sync.creds.get(p["id"])
        try:
            r = await run_in_threadpool(sync.http.request_json, p["token_url"], "POST", None, None, 0, None, {
                "grant_type": "authorization_code", "client_id": c.get("client_id", ""),
                "client_secret": c.get("client_secret", ""), "code": q.get("code", ""),
                "redirect_uri": f["redirect_uri"], "code_verifier": f["verifier"]})
            integ.store_ml_token(sync.creds, r)
        except Exception as e:  # noqa: BLE001
            log.warning("OAuth %s falhou: %s", p["id"], e)
            return page("Conexão não concluída", "Falha ao obter o token: " + str(e)[:300])
        return page("Conectado ✔", f"{p['nome']} conectado ao GPI. O token fica guardado com {sync.creds.protection}.")

    async def m_youtube(_):
        return JSONResponse(await run_in_threadpool(msv.youtube, sync.store))

    async def m_reviews(_):
        return JSONResponse(await run_in_threadpool(msv.reviews, sync.store))

    async def m_compare(request):
        keys = [k for k in request.query_params.get("keys", "").split(",") if k][:4]
        if len(keys) < 2:
            return err("selecione de 2 a 4 produtos")
        return JSONResponse(await run_in_threadpool(msv.compare, sync.store, keys))

    async def m_marketplaces(_):
        return JSONResponse(await run_in_threadpool(msv.marketplaces, sync.store, sync.connectors, cfg, sync.creds))

    async def m_models(_):
        from .forecasting.models import EXTRA_AVAILABLE
        return JSONResponse({"modelos": {k: v[0] for k, v in MODELS.items()}, "opcionais": EXTRA_AVAILABLE})

    async def app_quit(_):
        if shutdown_cb:
            shutdown_cb()
        return JSONResponse({"ok": True})

    async def index(_):
        return FileResponse(frontend_dir / "index.html")

    routes = [
        Route("/", index),
        Route("/api/health", health),
        Route("/api/status", status),
        Route("/api/import", do_import, methods=["POST"]),
        Route("/api/demo", demo, methods=["POST"]),
        Route("/api/imports/{iid:int}", delete_import, methods=["DELETE"]),
        Route("/api/skus", skus),
        Route("/api/history", history),
        Route("/api/overview", overview),
        Route("/api/trends", trends),
        Route("/api/abcxyz", abcxyz),
        Route("/api/forecast", forecast, methods=["POST"]),
        Route("/api/runs", runs),
        Route("/api/runs/{rid:int}", run),
        Route("/api/inventory", inventory, methods=["POST"]),
        Route("/api/export/{kind}.{fmt}", export),
        Route("/api/backup", backup, methods=["POST"]),
        Route("/api/shutdown", shutdown, methods=["POST"]),
        Route("/api/sync/status", sync_status),
        Route("/api/sync/run", sync_run, methods=["POST"]),
        Route("/api/sync/cancel", sync_cancel, methods=["POST"]),
        Route("/api/market/sources", m_sources),
        Route("/api/market/overview", m_overview),
        Route("/api/market/series", m_series),
        Route("/api/market/series/{sid:int}", m_series_one),
        Route("/api/market/product/{key:path}", m_product),
        Route("/api/market/search", m_search),
        Route("/api/market/opportunities", m_opps),
        Route("/api/market/forecasts", m_forecasts),
        Route("/api/market/clusters", m_clusters),
        Route("/api/market/export/oportunidades.{fmt}", m_export),
        Route("/api/integrations", integrations),
        Route("/api/integrations/{pid}/credentials", integ_credentials, methods=["POST"]),
        Route("/api/integrations/{pid}", integ_delete, methods=["DELETE"]),
        Route("/api/integrations/{pid}/test", integ_test, methods=["POST"]),
        Route("/api/integrations/{pid}/sync", integ_sync, methods=["POST"]),
        Route("/api/integrations/{pid}/settings", integ_settings, methods=["POST"]),
        Route("/api/integrations/{pid}/oauth/start", oauth_start, methods=["POST"]),
        Route("/oauth/callback", oauth_callback),
        Route("/api/app/quit", app_quit, methods=["POST"]),
        Route("/api/market/youtube", m_youtube),
        Route("/api/market/reviews", m_reviews),
        Route("/api/market/compare", m_compare),
        Route("/api/market/marketplaces", m_marketplaces),
        Route("/api/market/models", m_models),
        Mount("/static", StaticFiles(directory=frontend_dir), name="static"),
    ]
    app = Starlette(routes=routes, middleware=[Middleware(HostGuard)])
    app.state.db = db
    app.state.sync = sync
    return app
