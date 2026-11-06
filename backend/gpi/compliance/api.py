"""Rotas da Conformidade de Importação e da IA local."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..ai import assistant as AS
from ..ai.runtime import DEFAULTS as IA_DEFAULTS, LocalLLM, limits
from . import attachments as AT
from . import certs as C
from . import checklist as CK
from . import engine as E
from . import updater as U
from .knowledge import KnowledgeBase
from .ncm import NcmTable

log = logging.getLogger("gpi.conformidade")
SUPPLIER_FIELDS = ("nome", "nome_local", "pais", "cidade", "provincia", "site", "contato", "produtos", "certificacoes", "observacoes")


def setup(app_state, db, data_dir: Path, cfg: dict, http_getter, save_settings, app_dirs: list[Path]):
    bundled_ncm = next((d / "dados_oficiais" / "ncm.json" for d in app_dirs if (d / "dados_oficiais" / "ncm.json").exists()), None)
    kb = KnowledgeBase(db, data_dir)
    ncm = NcmTable(db, bundled_ncm)
    ia_dirs = [d / "ia" for d in app_dirs] + [data_dir / "ia"]
    llm = LocalLLM(cfg, ia_dirs)
    app_state.compliance_kb, app_state.ncm, app_state.ai = kb, ncm, llm
    def j(o, code=200):
        return JSONResponse(o, status_code=code)

    async def body(request):
        try:
            return await request.json()
        except Exception:  # noqa: BLE001
            return {}

    # ------------------------------------------------------------ painel / base
    async def status(_):
        def run():
            return {"base": kb.freshness(), "documentos": len(kb.all()), "conflitos": kb.conflicts(), "ncm": ncm.meta(),
                    "anatel": C.anatel_meta(db), "ia": llm.status(), "atualizacoes": U.history(db, 5),
                    "analises": len(db.query("SELECT id FROM compliance_analyses")),
                    "estados": {str(k): v for k, v in E.R.STATE_LABEL.items()}}
        return j(await run_in_threadpool(run))

    async def docs(request):
        q = request.query_params
        if q.get("q") or q.get("orgao") or q.get("tag"):
            res = await run_in_threadpool(kb.search, q.get("q", ""), q.get("orgao") or None,
                                          [q["tag"]] if q.get("tag") else None, None, q.get("ncm") or None,
                                          q.get("revogados") != "1", 30)
        else:
            res = await run_in_threadpool(kb.all)
        return j({"documentos": res, "frescor": kb.freshness()})

    async def doc(request):
        d = kb.doc(request.path_params["did"])
        if not d:
            return j({"erro": "documento não encontrado"}, 404)
        return j({**d, "historico": kb.history(d["id"])})

    async def kb_check(_):
        try:
            return j(await run_in_threadpool(U.check_online, db, kb, http_getter()))
        except Exception as e:  # noqa: BLE001
            return j({"erro": str(e)[:300]}, 400)

    async def kb_pack(request):
        sha = request.headers.get("x-sha256", "")
        raw = await request.body()
        try:
            return j(await run_in_threadpool(U.import_pack, db, kb, raw, sha))
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            return j({"erro": str(e)[:300]}, 400)
        except Exception as e:  # noqa: BLE001 — zip inválido etc.
            return j({"erro": f"pacote inválido ({type(e).__name__})"}, 400)

    async def kb_export(_):
        raw = await run_in_threadpool(U.export_pack, kb, datetime.now().strftime("%Y.%m.%d"))
        import hashlib
        return Response(raw, media_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="GPI-Base-Regulatoria.zip"', "X-SHA256": hashlib.sha256(raw).hexdigest()})

    # ------------------------------------------------------------ análise
    async def analyze(request):
        b = await body(request)
        form = b.get("formulario") if isinstance(b.get("formulario"), dict) else {}
        if not any(str(form.get(k) or "").strip() for k in ("nome_comercial", "modelo", "descricao_tecnica")):
            return j({"erro": "informe ao menos o nome comercial, o modelo ou a descrição técnica"}, 400)
        ids = [int(x) for x in (b.get("anexos") or []) if str(x).isdigit()][:20]
        mode = "ia_local" if b.get("modo") == "ia_local" else "essencial"
        ats = db.query(f"SELECT id, nome, tipo, tamanho, sha256 FROM compliance_attachments WHERE id IN ({','.join('?' * len(ids))})",
                       tuple(ids)) if ids else []

        def run():
            return E.analyze(db, kb, ncm, form, AT.texts(db, ids), ats, llm if mode == "ia_local" else None, cfg, mode)
        try:
            return j(await run_in_threadpool(run))
        except ValueError as e:
            return j({"erro": str(e)}, 400)

    async def analyses(request):
        return j({"analises": await run_in_threadpool(E.history, db, request.query_params.get("product_id"))})

    async def analysis(request):
        a = await run_in_threadpool(E.load, db, int(request.path_params["aid"]))
        return j(a) if a else j({"erro": "análise não encontrada"}, 404)

    async def upload(request):
        name = unquote(request.headers.get("x-filename", "anexo"))
        raw = await request.body()
        try:
            return j(await run_in_threadpool(AT.store, db, data_dir, None, name, raw))
        except AT.AttachmentError as e:
            return j({"erro": str(e)}, 400)

    # ------------------------------------------------------------ NCM
    async def ncm_validate(request):
        b = await body(request)
        from . import features as F
        feats = F.extract(b) if b.get("descricao_tecnica") else None
        out = ncm.validate(str(b.get("ncm") or ""), feats)
        return j(out)

    async def ncm_candidates(request):
        b = await body(request)
        txt = str(b.get("texto") or "")[:2000]
        return j({"candidatos": await run_in_threadpool(ncm.candidates, txt), "meta": ncm.meta(),
                  "aviso": "Candidatos para investigação, por semelhança de palavras com as descrições oficiais. "
                           "Não são classificação fiscal."})

    async def ncm_update(_):
        try:
            return j(await run_in_threadpool(ncm.update_official, http_getter()))
        except Exception as e:  # noqa: BLE001
            return j({"erro": f"não foi possível baixar a tabela oficial: {str(e)[:200]}"}, 400)

    async def ncm_file(request):
        raw = await request.body()
        try:
            return j(await run_in_threadpool(ncm.load_bytes, raw, "arquivo informado pelo usuário"))
        except (ValueError, json.JSONDecodeError) as e:
            return j({"erro": str(e)[:300]}, 400)

    # ------------------------------------------------------------ homologações / certificados
    async def anatel_update(_):
        try:
            return j(await run_in_threadpool(C.update_anatel, db, http_getter()))
        except Exception as e:  # noqa: BLE001
            return j({"erro": f"não foi possível baixar os dados abertos da Anatel: {str(e)[:200]}"}, 400)

    async def anatel_file(request):
        raw = await request.body()
        try:
            return j(await run_in_threadpool(C.load_anatel_zip, db, raw, "arquivo informado pelo usuário"))
        except Exception as e:  # noqa: BLE001
            return j({"erro": str(e)[:300]}, 400)

    async def anatel_query(request):
        b = await body(request)
        return j(await run_in_threadpool(C.anatel_lookup, db, str(b.get("numero") or ""), str(b.get("fabricante") or ""),
                                         str(b.get("modelo") or "")))

    async def cert_record(request):
        b = await body(request)
        try:
            rid = C.record_check(db, b.get("analise_id"), str(b.get("orgao")), b.get("consulta") or {}, str(b.get("resultado")),
                                 str(b.get("evidencia") or ""), "usuário (consulta manual)")
        except ValueError as e:
            return j({"erro": str(e)}, 400)
        return j({"id": rid, "aviso": "Registro da consulta manual informado pelo usuário — não é verificação automática."})

    async def cert_list(request):
        aid = request.query_params.get("analise_id")
        rows = db.query("SELECT * FROM compliance_cert_checks" + (" WHERE analysis_id = ?" if aid else "") + " ORDER BY id DESC LIMIT 200",
                        (int(aid),) if aid else ())
        return j({"consultas": rows, "links": C.manual_links()})

    # ------------------------------------------------------------ checklist
    async def checklist(request):
        a = await run_in_threadpool(E.load, db, int(request.path_params["aid"]))
        if not a:
            return j({"erro": "análise não encontrada"}, 404)
        return j(a.get("checklist") or CK.build(a))

    # ------------------------------------------------------------ fornecedores (informados pelo usuário)
    async def suppliers(request):
        if request.method == "GET":
            return j({"fornecedores": db.query("SELECT * FROM suppliers ORDER BY nome")})
        b = await body(request)
        vals = {k: str(b.get(k) or "").strip()[:2000] for k in SUPPLIER_FIELDS}
        if not vals["nome"]:
            return j({"erro": "informe o nome do fornecedor"}, 400)
        vals["pais"] = (vals["pais"] or "CN")[:2].upper()
        now = datetime.now().isoformat(timespec="seconds")
        if str(b.get("id") or "").isdigit():
            sets = ", ".join(f"{k} = ?" for k in SUPPLIER_FIELDS)
            db.execute(f"UPDATE suppliers SET {sets}, atualizado_em = ? WHERE id = ?", (*vals.values(), now, int(b["id"])))
            return j({"id": int(b["id"])})
        cur = db.execute(f"INSERT INTO suppliers ({', '.join(SUPPLIER_FIELDS)}, criado_em, atualizado_em) VALUES "
                         f"({', '.join('?' * len(SUPPLIER_FIELDS))}, ?, ?)", (*vals.values(), now, now))
        return j({"id": int(cur.lastrowid)})

    async def supplier_delete(request):
        b = await body(request)
        if not b.get("confirmar"):
            return j({"erro": "confirmação necessária"}, 400)
        db.execute("DELETE FROM suppliers WHERE id = ?", (int(request.path_params["sid"]),))
        return j({"ok": True})

    # ------------------------------------------------------------ assistente / IA local
    async def ask(request):
        b = await body(request)
        q = str(b.get("pergunta") or "").strip()
        if not q:
            return j({"erro": "digite uma pergunta"}, 400)
        ctx = {"req_id": str(b.get("req_id") or uuid.uuid4().hex)[:40]}
        if str(b.get("analise_id") or "").isdigit():
            a = E.load(db, int(b["analise_id"]))
            if a:
                ctx.update(formulario=a.get("formulario") or {}, ncm=a.get("ncm"))
        mode = "ia_local" if b.get("modo") == "ia_local" else ("essencial" if b.get("modo") == "essencial" else None)
        def run():
            r = AS.answer(q, kb, llm, cfg, ctx, mode)
            try:                                    # v0.9.1: ficha de investigação (identificação + questões + registros + checklist)
                from ..suite import regassist
                r["investigacao"] = regassist.ficha(db, q, r, b.get("fabricante"), b.get("modelo"))
            except Exception as e:  # noqa: BLE001
                r["investigacao"] = {"erro": f"{type(e).__name__}: {str(e)[:120]}"}
            return r
        return j(await run_in_threadpool(run))

    async def ask_cancel(request):
        b = await body(request)
        return j({"cancelada": llm.cancel(str(b.get("req_id") or ""))})

    async def ia_status(request):
        return j(await run_in_threadpool(llm.status, request.query_params.get("verificar") == "1"))

    async def ia_config(request):
        b = await body(request)
        vals = {k: b[k] for k in IA_DEFAULTS if k in b}
        if "ia_modo" in vals and vals["ia_modo"] not in ("essencial", "ia_local"):
            return j({"erro": "modo inválido"}, 400)
        try:
            lim = limits({**cfg, **vals})
        except (TypeError, ValueError):
            return j({"erro": "valores inválidos"}, 400)
        save_settings({k: lim[k] if k != "ia_modo" else vals.get("ia_modo", cfg.get("ia_modo", "essencial")) for k in vals})
        if llm.running() and any(k in vals for k in ("ia_ram_mb", "ia_threads", "ia_contexto")):
            llm.stop()                                   # novos limites valem no próximo carregamento
        return j({"ok": True, "limites": limits(cfg)})

    async def ia_load(_):
        try:
            await run_in_threadpool(llm.ensure_started)
            return j(llm.status())
        except Exception as e:  # noqa: BLE001
            return j({"erro": str(e)[:300], **llm.status()}, 400)

    async def ia_unload(_):
        await run_in_threadpool(llm.stop)
        return j(llm.status())

    return [
        Route("/api/compliance/status", status), Route("/api/compliance/docs", docs),
        Route("/api/compliance/docs/{did}", doc), Route("/api/compliance/base/verificar", kb_check, methods=["POST"]),
        Route("/api/compliance/base/pacote", kb_pack, methods=["POST"]), Route("/api/compliance/base/exportar", kb_export),
        Route("/api/compliance/analisar", analyze, methods=["POST"]), Route("/api/compliance/analises", analyses),
        Route("/api/compliance/analises/{aid:int}", analysis), Route("/api/compliance/anexos", upload, methods=["POST"]),
        Route("/api/compliance/ncm/validar", ncm_validate, methods=["POST"]),
        Route("/api/compliance/ncm/candidatos", ncm_candidates, methods=["POST"]),
        Route("/api/compliance/ncm/atualizar", ncm_update, methods=["POST"]),
        Route("/api/compliance/ncm/arquivo", ncm_file, methods=["POST"]),
        Route("/api/compliance/anatel/atualizar", anatel_update, methods=["POST"]),
        Route("/api/compliance/anatel/arquivo", anatel_file, methods=["POST"]),
        Route("/api/compliance/anatel/consultar", anatel_query, methods=["POST"]),
        Route("/api/compliance/certificados", cert_list), Route("/api/compliance/certificados", cert_record, methods=["POST"]),
        Route("/api/compliance/checklist/{aid:int}", checklist),
        Route("/api/compliance/fornecedores", suppliers, methods=["GET", "POST"]),
        Route("/api/compliance/fornecedores/{sid:int}/excluir", supplier_delete, methods=["POST"]),
        Route("/api/compliance/assistente", ask, methods=["POST"]),
        Route("/api/compliance/assistente/cancelar", ask_cancel, methods=["POST"]),
        Route("/api/ia/status", ia_status), Route("/api/ia/config", ia_config, methods=["POST"]),
        Route("/api/ia/carregar", ia_load, methods=["POST"]), Route("/api/ia/descarregar", ia_unload, methods=["POST"]),
    ]
