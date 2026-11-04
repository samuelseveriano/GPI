"""Rotas v0.6.1: painel de sincronização (eventos em tempo real), histórico, novas tentativas, diagnóstico das
integrações, assistente do Google Ads, YouTube Intelligence, módulos Meta e exportação de diagnóstico seguro."""
from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import time
from datetime import datetime

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from . import __version__
from .connectors.http import SourceError, redact
from .integrations import registry as integ

STATE_ORDER = ["configurado", "autenticado", "autorizado", "validado", "funcional"]
STATE_NAMES = {"nao_configurado": "Não configurado", "configurado": "Configurado", "autenticado": "Autenticado",
               "autorizado": "Autorizado", "validado": "Validado", "funcional": "Funcional", "restrito": "Restrito",
               "erro": "Erro", "disponivel": "Disponível (pública)"}


def integration_state(p: dict, item: dict, diag: dict | None) -> dict:
    """Estados separados: CONFIGURADO → AUTENTICADO → AUTORIZADO → VALIDADO → FUNCIONAL (+ RESTRITO / ERRO).
    'Funcional' exige coleta real gravada E legível pela aplicação; chave aceita não basta."""
    cred = item.get("credenciais") or {}
    conns = item.get("conectores") or []
    validated = any(c.get("validada") for c in conns)
    records = sum(int(c.get("registros") or 0) for c in conns)
    failing = any(c.get("estado") == "falhou" for c in conns if c.get("disponivel"))
    d = (diag or {}).get("resultado") or {}
    steps = {s["etapa"]: s for s in d.get("etapas", [])}
    if p["tipo"] == "approval":
        nivel = "restrito"
    elif p["tipo"] == "auto":
        nivel = "funcional" if validated and records else ("erro" if failing else "disponivel")
    else:
        configurado = bool(cred) or item.get("optin")
        autenticado = bool(cred.get("refresh_token") or cred.get("access_token") or cred.get("api_key")) and \
            not any(not s["ok"] for k, s in steps.items() if k in ("OAuth", "Login", "A — Autenticação"))
        authorized = autenticado and (d.get("estado") in ("autorizado", "validado", "funcional") or validated)
        if p["id"] == "google_ads":
            authorized = autenticado and d.get("estado") == "validado" or (autenticado and validated)
        nivel = "nao_configurado"
        if configurado:
            nivel = "configurado"
        if autenticado:
            nivel = "autenticado"
        if authorized:
            nivel = "autorizado"
        if authorized and (validated or d.get("estado") in ("validado", "funcional")):
            nivel = "validado"
        if nivel == "validado" and records and (d.get("estado") == "funcional" or (validated and records)):
            nivel = "funcional"
        if failing or d.get("estado") == "erro":
            nivel = "erro" if nivel not in ("funcional",) else nivel
        if d.get("estado") in ("basic", "producao", "sem_conta", "planejamento") and nivel != "funcional":
            nivel = "restrito" if d.get("estado") in ("basic", "producao") else "erro"
    return {"nivel": nivel, "rotulo": STATE_NAMES[nivel], "registros": records, "validada": validated,
            "diagnostico_em": (diag or {}).get("em"), "diagnostico_estado": d.get("estado"),
            "passos": [{"etapa": s["etapa"], "ok": s["ok"], "mensagem": s["mensagem"], "acao": s.get("acao")}
                       for s in d.get("etapas", [])]}


def routes(db, sync, cfg, data_dir, save_settings=None) -> list[Route]:
    def j(o, code=200):
        return JSONResponse(o, status_code=code)

    async def db_integrity(_):
        return j(await run_in_threadpool(db.integrity))

    async def source_audit(request):
        from .market.audit import audit
        return j(await run_in_threadpool(audit, db, sync.store, sync.creds, cfg, sync.connectors))

    async def removed(_):
        from .market.service import removed_sources
        return j({"fontes": removed_sources(db)})

    async def body(request):
        try:
            return await request.json()
        except Exception:  # noqa: BLE001
            return {}

    # ------------------------------------------------------------------ painel de sincronização
    async def panel(_):
        return j(await run_in_threadpool(sync.snapshot))

    async def events(request):
        """Server-Sent Events: envia o estado só quando muda (sem duplicatas) e um 'ping' a cada 15 s.
        O navegador reconecta sozinho (EventSource); 'retry' orienta o intervalo de reconexão."""
        async def gen():
            last, last_ping = None, time.monotonic()
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                snap = await run_in_threadpool(sync.snapshot)
                h = hashlib.sha1(json.dumps(snap, sort_keys=True, default=str).encode()).hexdigest()
                if h != last:
                    last = h
                    yield f"id: {snap.get('execucao') or 0}-{snap.get('versao', 0)}\nevent: estado\ndata: {json.dumps(snap, ensure_ascii=False, default=str)}\n\n"
                elif time.monotonic() - last_ping > 15:
                    last_ping = time.monotonic()
                    yield ": ping\n\n"
                await asyncio.sleep(1.0 if snap.get("rodando") else 5.0)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def history(_):
        return j({"execucoes": await run_in_threadpool(sync.history)})

    async def retry_failed(_):
        return j(await run_in_threadpool(sync.retry_failed))

    async def run_all(request):
        b = await body(request)
        only = [x for x in (b.get("fontes") or []) if isinstance(x, str)] or None
        # v0.7.1: "Atualizar fonte" (manual=True) ignora o TTL/backoff LOCAL dessas fontes; cotas da API continuam valendo
        return j({"iniciada": sync.start("manual", only, manual=bool(b.get("manual") and only))})

    # ------------------------------------------------------------------ diagnóstico por integração
    def _diagnose(pid: str) -> dict:
        if pid == "google_ads":
            from .integrations.google_ads import diagnose
            res = diagnose(sync.http, sync.creds)
        elif pid == "youtube":
            from .market.youtube_view import diagnose
            res = diagnose(sync.http, sync.creds, cfg, db, sync.content)
        elif pid == "meta":
            from .integrations.meta import diagnose
            res = diagnose(sync.http, sync.creds, cfg)
        elif pid == "mercadolivre":
            from .integrations.mercadolivre import diagnose
            res = diagnose(sync.http, sync.creds, cfg)
        else:
            ok, msg = integ.test_connection(pid, sync.http, sync.creds, cfg)
            p = integ.provider(pid) or {"conectores": []}
            st = sync.store.source_status()
            recs = sum(int((st.get(c) or {}).get("records") or 0) for c in p["conectores"])
            val = any((st.get(c) or {}).get("validated") for c in p["conectores"])
            res = {"etapas": [{"etapa": "Conexão", "ok": ok, "mensagem": msg},
                              {"etapa": "Coleta real gravada", "ok": bool(val and recs),
                               "mensagem": f"{recs} registros armazenados" if recs else "nenhuma coleta real gravada ainda"}],
                   "estado": "funcional" if ok and val and recs else ("autorizado" if ok else "erro")}
        out = {"em": datetime.now().astimezone().isoformat(timespec="seconds"), "resultado": res}
        sync.store.save_result(f"diag:{pid}", out)
        return out

    async def diagnose(request):
        pid = request.path_params["pid"]
        if not integ.provider(pid):
            return j({"erro": "integração desconhecida"}, 404)
        try:
            return j(await run_in_threadpool(_diagnose, pid))
        except SourceError as e:
            return j({"em": None, "resultado": {"etapas": [{"etapa": "Diagnóstico", "ok": False, "mensagem": str(e)}],
                                                "estado": "erro"}})

    # ------------------------------------------------------------------ Google Ads (assistente)
    async def gads_accounts(_):
        from .integrations.google_ads import classify, discover, MSG, HOW
        try:
            return j(await run_in_threadpool(discover, sync.http, sync.creds))
        except SourceError as e:
            k, code = classify(e, "contas")
            return j({"contas": [], "mensagem": MSG[k], "acao": HOW[k], "codigo": code}, 200)

    async def gads_select(request):
        from .integrations.google_ads import select
        b = await body(request)
        try:
            return j(select(sync.creds, b.get("customer_id"), b.get("login_customer_id")))
        except ValueError as e:
            return j({"erro": str(e)}, 400)

    async def gads_info(_):
        c = sync.creds.get("google_ads")
        return j({"configurado": bool(c.get("client_id")), "autenticado": bool(c.get("refresh_token")),
                  "conta": c.get("customer_id") or None, "administradora": c.get("login_customer_id") or None,
                  "contas": json.loads(c.get("contas") or "[]"), "versao_api": c.get("api_version"),
                  "developer_token": "descontinuado em 09/09/2026 — não é usado" if c.get("developer_token") else "não necessário",
                  "ultimo_diagnostico": sync.store.load_result("diag:google_ads")})

    # ------------------------------------------------------------------ YouTube
    async def yt_status(_):
        from .market.youtube_view import status
        return j(await run_in_threadpool(status, db, cfg))

    async def yt_videos(request):
        from .market.youtube_view import videos
        q = request.query_params
        dias = q.get("dias")
        return j(await run_in_threadpool(videos, db, q.get("produto") or None, q.get("categoria") or None, q.get("q") or None,
                                         int(dias) if dias and dias.isdigit() else None, q.get("canal") or None))

    async def yt_refresh(_):
        """Atualizar agora: no máximo youtube_manual_max_searches buscas (padrão 5 ≈ 505 unidades), sempre dentro do
        limite diário do GPI. Não dispara milhares de chamadas."""
        from .market.youtube_view import status
        st = await run_in_threadpool(status, db, cfg)
        need = 101 * int(cfg.get("youtube_manual_max_searches", 5)) + 5
        if st["restante_no_limite_gpi"] < 101:
            return j({"iniciada": False, "mensagem": "limite diário do GPI para o YouTube já foi atingido hoje; tente amanhã "
                                                     "ou ajuste o limite na Central de Integrações"})
        ok = sync.start("atualizar-youtube", ["youtube"], force=True)
        return j({"iniciada": ok, "mensagem": (f"atualização iniciada (até ~{min(need, st['restante_no_limite_gpi'])} unidades)"
                                               if ok else "já existe uma sincronização em andamento")})

    # ------------------------------------------------------------------ Meta
    async def meta_modules(_):
        from .integrations.meta import KNOWN_BLOCK, module_status
        return j({"modulos": module_status(sync.creds.get("meta")), "bloqueio_conhecido": KNOWN_BLOCK,
                  "ultimo_diagnostico": sync.store.load_result("diag:meta")})

    # ------------------------------------------------------------------ diagnóstico exportável (sem segredos)
    def _export() -> dict:
        import os
        st = sync.store.source_status()
        provs = []
        for p in integ.PROVIDERS:
            cred = sync.creds.get(p["id"]) if p.get("campos") or p["tipo"] == "oauth" else {}
            provs.append({"id": p["id"], "tipo": p["tipo"],
                          "campos_configurados": sorted(k for k, v in (cred or {}).items() if v and k not in ("contas",)),
                          "diagnostico": (sync.store.load_result(f"diag:{p['id']}") or {})})
        logs = []
        d = os.path.join(str(data_dir), "logs", "sync")
        if os.path.isdir(d):
            files = sorted(os.listdir(d))[-3:]
            for f in files:
                try:
                    with open(os.path.join(d, f), encoding="utf-8") as fh:
                        logs += [json.loads(x) for x in fh.read().splitlines()[-400:] if x.strip()]
                except (OSError, ValueError):
                    pass
        out = {"gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"), "versao_gpi": __version__,
               "sistema": {"os": platform.platform(), "python": platform.python_version()},
               "fontes": st, "integracoes": provs, "sincronizacao_atual": sync.snapshot(), "historico": sync.history(10),
               "metricas_http": getattr(sync.http, "host_stats", {}), "eventos_recentes": logs[-1200:],
               "config": {k: v for k, v in cfg.items() if not any(x in k.lower() for x in ("token", "secret", "key", "senha", "password", "proxy"))},
               "aviso": "Arquivo sem chaves de API, tokens, segredos OAuth ou senhas (removidos automaticamente)."}
        txt = redact(json.dumps(out, ensure_ascii=False, default=str))
        return json.loads(txt)

    async def export_diag(_):
        data = await run_in_threadpool(_export)
        name = f"GPI_diagnostico_{datetime.now():%Y%m%d-%H%M%S}.json"
        return Response(json.dumps(data, ensure_ascii=False, indent=1, default=str), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    return [
        Route("/api/sources/removed", removed),
        Route("/api/sources/audit", source_audit),
        Route("/api/db/integrity", db_integrity),
        Route("/api/sync/panel", panel), Route("/api/sync/events", events), Route("/api/sync/history", history),
        Route("/api/sync/retry-failed", retry_failed, methods=["POST"]), Route("/api/sync/start", run_all, methods=["POST"]),
        Route("/api/integrations/{pid}/diagnose", diagnose, methods=["POST"]),
        Route("/api/integrations/google_ads/accounts", gads_accounts, methods=["POST"]),
        Route("/api/integrations/google_ads/select", gads_select, methods=["POST"]),
        Route("/api/integrations/google_ads/info", gads_info),
        Route("/api/youtube/status", yt_status), Route("/api/youtube/videos", yt_videos),
        Route("/api/integrations/youtube/refresh", yt_refresh, methods=["POST"]),
        Route("/api/integrations/meta/modules", meta_modules),
        Route("/api/diagnostics/export", export_diag),
    ]
