"""Rotas da Product Intelligence Suite (v0.9.1) — /api/suite/*. Mesmo servidor local (127.0.0.1), mesmo banco."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import capabilities as CAP
from . import export as EX
from . import importx as IX
from . import importyeti as IY
from . import marketplace as MK
from . import monitor as MON
from . import research as RS
from . import store as S
from . import suppliers as SP
from . import visual as V

MIME = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "pdf": "application/pdf"}
MAX_UPLOAD = 20 * 1024 * 1024


def routes(db, sync, cfg, comp_state=None, data_dir: Path | None = None) -> list[Route]:
    data_dir = Path(data_dir or cfg.get("_data_dir") or ".")

    def j(o, code=200):
        return JSONResponse(o, status_code=code)

    async def body(request: Request) -> dict:
        try:
            b = await request.json()
            return b if isinstance(b, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def today() -> date:
        try:
            return sync.today_fn()
        except Exception:  # noqa: BLE001
            return date.today()

    def payload():
        from ..intel.api import _payload_for_v09
        return _payload_for_v09(db, sync, cfg)

    def stages():
        from ..intel import decision as D
        return D.stages(payload(), db, today())

    def catalog():
        from ..products.catalog import Catalog
        return {p["product_id"]: p for p in Catalog(db, cfg).products()}

    def settings():
        return S.settings(sync.store)

    def ctx():
        return {"payload_fn": payload, "stages_fn": stages, "catalog_fn": catalog, "ncm": getattr(comp_state, "ncm", None),
                "today": today(), "cfg": cfg, "sync_ctx_fn": sync.context}

    async def upload(request: Request) -> tuple[bytes, str, dict]:
        """Corpo binário (sem dependência de multipart). Campos na query string; nome em X-Filename (sanitizado e usado só
        para exibição). O conteúdo é validado pelo módulo que o usa (assinatura, tamanho, estrutura)."""
        raw = await request.body()
        if len(raw) > MAX_UPLOAD:
            raise ValueError("arquivo grande demais")
        return raw, V.safe_label(request.headers.get("x-filename")), dict(request.query_params)

    def crop_of(f: dict):
        c = f.get("recorte")
        if not c:
            return None
        try:
            c = json.loads(c) if isinstance(c, str) else c
            return c if isinstance(c, dict) else None
        except ValueError:
            return None

    def err(e, code=400):
        return j({"erro": str(e)}, code)

    # ---------------------------------------------------------------- visão geral / configurações / provedores
    async def overview(request):
        def calc():
            S.ensure(db)
            MON.ensure(db)
            st = settings()
            c = lambda q, p=(): db.query(q, p)[0]["n"]  # noqa: E731
            demo = "(source LIKE '%demonstr%' OR source LIKE '%[DEMONSTRATIVO]%' OR source LIKE '%teste%' OR source LIKE '%exemplo%')"
            try:
                stg = stages()["itens"]
            except Exception:  # noqa: BLE001
                stg = []
            jobs = db.query("SELECT result FROM research_jobs WHERE finished_at IS NOT NULL")
            concl = sum(1 for r in jobs if (json.loads(r["result"] or "null") or {}).get("conclusiva"))
            produtos = {"cadastrados": c("SELECT COUNT(*) AS n FROM catalog_products"),
                        "identificados": c("SELECT COUNT(*) AS n FROM catalog_products WHERE evidence > 0"),
                        "com_evidencias_comerciais": sum(1 for x in stg if x["estagio"] >= 1),
                        "monitorados": c("SELECT COUNT(*) AS n FROM monitored WHERE kind = 'produto'"),
                        "investigacao_concluida": concl, "investigacao_inconclusiva": len(jobs) - concl}
            demos = {"vendas_demonstrativas": c("SELECT COUNT(*) AS n FROM imports WHERE is_demo = 1"),
                     "empresas": c(f"SELECT COUNT(*) AS n FROM companies WHERE {demo}"), "embarques": c(f"SELECT COUNT(*) AS n FROM trade_shipments WHERE {demo}"),
                     "evidencias_nao_reais": c("SELECT COUNT(*) AS n FROM research_evidence WHERE origin != 'REAL'")}
            from . import dashboard as DB_
            try:
                cons = DB_.build(db, payload(), {"itens": stg}, today())
            except Exception as e:  # noqa: BLE001
                cons = {"erro": f"{type(e).__name__}: {str(e)[:160]}"}
            return {"versao": "0.9.1", "configuracoes": st, "produtos": produtos, "consolidado": cons,
                    "contagens": {"pesquisas": c("SELECT COUNT(*) AS n FROM research_jobs"),
                                  "empresas": c(f"SELECT COUNT(*) AS n FROM companies WHERE verification_status NOT LIKE 'mesclada%' AND NOT {demo}"),
                                  "embarques": c(f"SELECT COUNT(*) AS n FROM trade_shipments WHERE NOT {demo}"), "relacoes": c("SELECT COUNT(*) AS n FROM trade_relationships"),
                                  "imagens_catalogo": c("SELECT COUNT(*) AS n FROM product_images"), "monitorados": c("SELECT COUNT(*) AS n FROM monitored"),
                                  "fornecedores_monitorados": c("SELECT COUNT(*) AS n FROM monitored WHERE kind = 'fornecedor'"),
                                  "duplicidades_pendentes": c("SELECT COUNT(*) AS n FROM company_merge_review WHERE estado = 'pendente'"),
                                  "cenarios": c("SELECT COUNT(*) AS n FROM import_scenarios")},
                    "demonstrativos": demos, "tem_demonstrativos": any(demos.values()),
                    "recentes": RS.history(db, 8), "modo_sem_custos": st["sem_custos"],
                    "notas": {"cadastrados": "produtos no catálogo canônico (sementes + descobertos + pesquisados)",
                              "identificados": "reconhecidos em alguma fonte coletada",
                              "com_evidencias_comerciais": "estágio ≥ 1 na inteligência (observação comercial ou de pesquisa)",
                              "investigacao_concluida": "pesquisa com fonte de evidência útil e decisão diferente de CINZA",
                              "investigacao_inconclusiva": "pesquisa encerrada sem evidência suficiente (dados insuficientes)",
                              "demonstrativos": "empresas/embarques com fonte marcada como demonstrativa/teste ficam fora das contagens principais"},
                    "regras": ["Modo sem custos externos ativo por padrão: nenhum crédito pago é consumido.",
                               "Score não é probabilidade. Dados ausentes não são evidência negativa."]}
        return j(await run_in_threadpool(calc))

    async def config_get(request):
        return j({"configuracoes": settings(), "visual_avancado": V.advanced_status(data_dir, settings()),
                  "importyeti": IY.status(db, sync.creds, settings())})

    async def config_set(request):
        b = await body(request)
        cur = S.save_settings(sync.store, b)
        if "importyeti_chave" in b:
            IY.set_key(sync.creds, str(b.get("importyeti_chave") or "")[:200] or None)
        return j({"ok": True, "configuracoes": cur})

    async def providers(request):
        st = settings()
        iy = IY.status(db, sync.creds, st)
        return j({"provedores": CAP.status_table(db, st, {"importyeti": {"status": iy["estado"], "orcamento": iy["orcamento"], "gasto": iy["gasto"]}}),
                  "capacidades": CAP.CAPS, "excluidos": CAP.EXCLUDED, "modo_sem_custos": st["sem_custos"]})

    # ---------------------------------------------------------------- Product Research
    async def research_start(request):
        b = await body(request)
        st = settings()
        params = {"idioma": b.get("idioma") or st["idioma"], "mercado": (b.get("mercado") or st["pais_padrao"])[:10],
                  "comparacao": [str(x)[:10] for x in (b.get("comparacao") or [])][:5], "periodo_meses": b.get("periodo_meses") or st["periodo_meses"],
                  "inicio": b.get("inicio"), "fim": b.get("fim"), "objetivo": (b.get("objetivo") or "")[:80],
                  "profundidade": b.get("profundidade") if b.get("profundidade") in ("rapida", "completa") else st["modo"],
                  "atualizar": bool(b.get("atualizar"))}
        try:
            rid = RS.create(db, b.get("consulta") or "", params)
        except ValueError as e:
            return err(e)
        if b.get("sincrono"):
            await run_in_threadpool(RS.run, db, rid, ctx())
        else:
            RS.start(db, rid, ctx())
        return j({"id": rid})

    async def research_get(request):
        r = RS.get(db, int(request.path_params["rid"]))
        return j(r) if r else j({"erro": "pesquisa não encontrada"}, 404)

    async def research_history(request):
        return j({"itens": RS.history(db, 300)})

    async def research_save(request):
        rid = int(request.path_params["rid"])
        b = await body(request)
        db.execute("UPDATE research_jobs SET saved = ? WHERE id = ?", (1 if b.get("salvar", True) else 0, rid))
        return j({"ok": True})

    async def research_export(request):
        r = RS.get(db, int(request.path_params["rid"]))
        fmt = request.path_params["fmt"]
        if not r or not r["result"] or fmt not in MIME:
            return j({"erro": "pesquisa sem resultado"}, 404)
        data = await run_in_threadpool((EX.xlsx if fmt == "xlsx" else EX.pdf), "pesquisa", r["result"], f"Pesquisa de produto: {r['query']}")
        return Response(data, media_type=MIME[fmt], headers={"Content-Disposition": f'attachment; filename="gpi-pesquisa-{r["id"]}.{fmt}"'})

    # ---------------------------------------------------------------- Marketplace Intelligence
    def niche_data(q):
        rows = MK.niche_rows(payload(), db, catalog(), stages(), today())
        f = {k: q.get(k) for k in MK.FILTERS if q.get(k) not in (None, "")}
        out = MK.filter_niches(rows, f)
        key = q.get("ordem") if q.get("ordem") in MK.SORTS else "oportunidade"
        out.sort(key=MK.SORTS[key])
        cats = sorted({r["categoria"] for r in rows if r["categoria"]})
        return {"itens": out[:500], "total": len(rows), "filtrados": len(out), "filtros": f, "ordem": key, "categorias": cats,
                "salvos": (sync.store.load_result("suite:nichos_salvos") or {}).get("itens", []),
                "nota": "Filtros numéricos excluem produtos SEM o dado (ausência ≠ valor baixo). Anúncios observados não são vendas; "
                        "competição = quantidade e concentração de anúncios por marca."}

    async def niches(request):
        return j(await run_in_threadpool(niche_data, dict(request.query_params)))

    async def niches_save(request):
        b = await body(request)
        cur = (sync.store.load_result("suite:nichos_salvos") or {}).get("itens", [])
        name = str(b.get("nome") or "").strip()[:80]
        if not name:
            return err("informe o nome")
        cur = [c for c in cur if c["nome"] != name] + [{"nome": name, "filtros": {k: v for k, v in (b.get("filtros") or {}).items() if k in MK.FILTERS},
                                                         "criado_em": S.now()}]
        sync.store.save_result("suite:nichos_salvos", {"itens": cur[-50:]})
        return j({"ok": True, "salvos": cur[-50:]})

    async def niches_export(request):
        fmt = request.path_params["fmt"]
        if fmt not in MIME:
            return err("formato")
        d = await run_in_threadpool(niche_data, dict(request.query_params))
        data = await run_in_threadpool((EX.xlsx if fmt == "xlsx" else EX.pdf), "nichos", d, "Explorador de nichos")
        return Response(data, media_type=MIME[fmt], headers={"Content-Disposition": f'attachment; filename="gpi-nichos.{fmt}"'})

    async def kw(request):
        t = (request.query_params.get("termo") or "").strip()
        if not t:
            return err("informe ?termo=")
        return j(await run_in_threadpool(MK.keywords, db, t[:200], request.query_params.get("mercado") or None))

    async def kw_export(request):
        fmt = request.path_params["fmt"]
        t = (request.query_params.get("termo") or "").strip()
        if fmt not in MIME or not t:
            return err("informe ?termo= e formato")
        d = await run_in_threadpool(MK.keywords, db, t[:200], request.query_params.get("mercado") or None)
        data = await run_in_threadpool((EX.xlsx if fmt == "xlsx" else EX.pdf), "palavras", d, f"Palavras-chave: {t}")
        return Response(data, media_type=MIME[fmt], headers={"Content-Disposition": f'attachment; filename="gpi-palavras.{fmt}"'})

    async def kw_reverse(request):
        return j(await run_in_threadpool(MK.reverse_listing, db, request.path_params["iid"][:40]))

    async def mkt_listing(request):
        ref = (request.query_params.get("ref") or "").strip()
        if not ref:
            return err("informe ?ref= (nome, URL ou ID do anúncio)")
        def calc():
            from . import url_lookup as UL
            r = MK.listing(db, ref[:500])
            if r.get("encontrado"):
                return r
            d = UL.detect(ref)
            if d["tipo"] != "anúncio de marketplace":
                return {**r, "url": d}
            api = UL.fetch_listing(db, sync, ref)            # consulta a API oficial do marketplace
            if api.get("ok") and api.get("gravado"):
                out = MK.listing(db, api["anuncio"]["id"])
                out["consulta_api"] = api
                return out
            return {**r, "consulta_api": api}
        return j(await run_in_threadpool(calc))

    async def mkt_compare(request):
        b = await body(request)
        return j(await run_in_threadpool(MK.compare_listings, db, [str(x)[:500] for x in (b.get("refs") or [])]))

    async def trend(request):
        pid = (request.query_params.get("produto") or "").strip()
        if not pid:
            return err("informe ?produto=")
        h = max(1, min(12, int(request.query_params.get("horizonte") or 6)))
        return j(await run_in_threadpool(MK.trend_explorer, db, pid[:200], h))

    async def reviews(request):
        return j(await run_in_threadpool(MK.review_insights, db, request.query_params.get("produto") or None))

    async def reviews_file(request):
        try:
            raw, name, _ = await upload(request)
            return j(await run_in_threadpool(MK.review_file, raw, name))
        except ValueError as e:
            return err(e)

    # ---------------------------------------------------------------- Visual Product Search
    async def img_search(request):
        from . import url_lookup as UL
        try:
            raw, name, f = await upload(request)
            url = (f.get("url") or "").strip()
            origem = None
            if not raw and url:
                raw, origem = await run_in_threadpool(image_from_url, url)
            res = await run_in_threadpool(V.search, db, data_dir, raw, crop_of(f), f.get("familia") or None, 30, settings())
            public = url if origem and origem["tipo"] == "URL direta de imagem" else (origem or {}).get("imagem")
            res["busca_externa"] = V.external_links(public or None)
            res["origem_url"] = origem
            from . import naming as NM
            for x in res["resultados"]:
                x["nome_comercial"] = NM.name_of(db, x["product_id"]) if x.get("product_id") else None
            res["consulta"]["nome"] = name
            if f.get("ebay") in ("1", "true", "sim"):          # envio ao eBay SÓ com autorização explícita do usuário
                res["ebay"] = await run_in_threadpool(UL.ebay_search_by_image, sync, raw)
            else:
                res["ebay"] = {"ok": False, "estado": "não solicitado", "motivo": "marque 'enviar ao eBay' para usar a busca por imagem oficial do eBay"}
            return j(res)
        except (V.ImageRejected, ValueError) as e:
            return err(e)

    def fetch_image(url: str) -> bytes:
        from ..security import public_url_problem
        prob = public_url_problem(url)
        if prob:
            raise ValueError(f"URL recusada: {prob}")
        try:
            r = sync.http.request_json(url, ttl=0, timeout=20, _binary=True, _max_bytes=V.MAX_BYTES)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"não foi possível baixar a imagem ({type(e).__name__}: {str(e)[:120]})") from e
        raw = r.get("_bytes") if isinstance(r, dict) else r          # o cliente HTTP devolve {"_bytes": ...}
        if not isinstance(raw, (bytes, bytearray)):
            raise ValueError("a URL não devolveu conteúdo binário")
        if raw[:64].lstrip()[:1] == b"<" or b"<html" in raw[:512].lower():
            raise ValueError("a URL devolveu uma PÁGINA (HTML), não uma imagem. Cole a URL direta da imagem ou o link de um anúncio eBay/Mercado Livre.")
        if not V.sniff(bytes(raw)):
            raise ValueError("o conteúdo da URL não é JPG, PNG nem WEBP")
        return bytes(raw)

    def image_from_url(url: str):
        """Imagem direta → baixa; anúncio eBay/Mercado Livre → API oficial → URL da foto autorizada → baixa; página → orientação."""
        from . import url_lookup as UL
        d = UL.detect(url)
        if d["tipo"] == "URL inválida":
            raise ValueError(f"URL recusada: {d['motivo']}")
        if d["tipo"] == "anúncio de marketplace":
            r = UL.fetch_listing(db, sync, url)
            if not r.get("ok"):
                raise ValueError(f"{d['provedor']}: {r.get('motivo')} — {r.get('acao') or r.get('alternativa') or ''}")
            img = (r.get("anuncio") or {}).get("imagem")
            if not img:
                raise ValueError("a API do marketplace não informou imagem para o anúncio")
            return fetch_image(img), {**d, "imagem": img, "anuncio": r["anuncio"], "produto_identificado": r.get("produto_identificado")}
        if d["tipo"] == "página de produto":
            try:
                return fetch_image(url), {**d, "tipo": "URL direta de imagem"}     # algumas URLs de imagem não têm extensão
            except ValueError:
                raise ValueError(d["motivo"]) from None
        return fetch_image(url), d

    async def img_add(request):
        try:
            raw, name, f = await upload(request)
            if not raw and f.get("url"):
                raw = await run_in_threadpool(fetch_image, f["url"])
            return j(await run_in_threadpool(V.add_to_catalog, db, data_dir, raw, f.get("rotulo") or name, f.get("produto_id") or None,
                                             f.get("familia") or None, "URL pública" if f.get("url") else "enviada pelo usuário", crop_of(f), settings()))
        except (V.ImageRejected, ValueError) as e:
            return err(e)

    async def img_compare(request):
        import base64
        b = await body(request)
        try:
            ra, rb = base64.b64decode(str(b.get("a") or ""), validate=True), base64.b64decode(str(b.get("b") or ""), validate=True)
            return j(await run_in_threadpool(V.compare, ra, rb))
        except (V.ImageRejected, ValueError) as e:
            return err(e)

    async def img_catalog(request):
        S.ensure(db)
        return j({"itens": db.query("SELECT image_id, label, product_id, family, source, width, height, created_at FROM product_images ORDER BY image_id DESC LIMIT 500"),
                  "avancado": V.advanced_status(data_dir, settings())})

    async def img_file(request):
        S.ensure(db)
        r = db.query("SELECT stored_path FROM product_images WHERE image_id = ?", (int(request.path_params["iid"]),))
        if not r:
            return j({"erro": "não encontrada"}, 404)
        p = (data_dir / "imagens_catalogo" / Path(r[0]["stored_path"]).name).resolve()
        if p.parent != (data_dir / "imagens_catalogo").resolve() or not p.exists():
            return j({"erro": "não encontrada"}, 404)
        return Response(p.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    async def img_delete(request):
        S.ensure(db)
        iid = int(request.path_params["iid"])
        r = db.query("SELECT stored_path FROM product_images WHERE image_id = ?", (iid,))
        if r:
            p = data_dir / "imagens_catalogo" / Path(r[0]["stored_path"]).name
            db.execute("DELETE FROM product_images WHERE image_id = ?", (iid,))
            try:
                p.unlink()
            except OSError:
                pass
        return j({"ok": True})

    # ---------------------------------------------------------------- Supplier Intelligence
    async def companies(request):
        q = request.query_params
        return j({"itens": await run_in_threadpool(SP.search_companies, db, q.get("q") or "", q.get("tipo") or None, q.get("pais") or None),
                  "tipos": S.TYPES, "pendentes_revisao": len(SP.merge_queue(db))})

    async def company_add(request):
        try:
            return j(await run_in_threadpool(SP.upsert_company, db, await body(request), "informado pelo usuário"))
        except ValueError as e:
            return err(e)

    async def company_get(request):
        try:
            return j(await run_in_threadpool(SP.profile, db, int(request.path_params["cid"])))
        except KeyError as e:
            return err(e, 404)

    async def company_export(request):
        fmt = request.path_params["fmt"]
        try:
            d = await run_in_threadpool(SP.profile, db, int(request.path_params["cid"]))
        except KeyError as e:
            return err(e, 404)
        data = await run_in_threadpool((EX.xlsx if fmt == "xlsx" else EX.pdf), "fornecedor", d, f"Fornecedor: {d['empresa']['legal_name']}")
        return Response(data, media_type=MIME[fmt], headers={"Content-Disposition": f'attachment; filename="gpi-fornecedor-{d["empresa"]["company_id"]}.{fmt}"'})

    async def company_network(request):
        return j(await run_in_threadpool(SP.network, db, int(request.path_params["cid"]), int(request.query_params.get("profundidade") or 2)))

    async def merges(request):
        return j({"itens": await run_in_threadpool(SP.merge_queue, db), "regra": "Nenhuma fusão é automática: você decide cada par."})

    async def merge_decide(request):
        b = await body(request)
        try:
            return j(await run_in_threadpool(SP.decide_merge, db, int(request.path_params["rid"]), str(b.get("decisao") or "")))
        except (KeyError, ValueError) as e:
            return err(e)

    async def import_file(request):
        kind = request.path_params["kind"]
        try:
            raw, name, f = await upload(request)
            fn = {"empresas": SP.import_companies, "embarques": SP.import_shipments}.get(kind)
            if not fn:
                return err("tipo deve ser 'empresas' ou 'embarques'")
            fonte = (f.get("fonte") or "")[:110] or None
            if f.get("demonstrativo") in ("1", "true", "sim"):
                fonte = "[DEMONSTRATIVO] " + (fonte or name)          # fica fora das contagens principais do Dashboard
            return j(await run_in_threadpool(fn, db, raw, name, fonte))
        except ValueError as e:
            return err(e)

    async def relation_add(request):
        b = await body(request)
        try:
            return j(await run_in_threadpool(SP.add_relationship, db, int(b.get("a")), int(b.get("b")), str(b.get("tipo") or "relação"),
                                             str(b.get("status") or ""), str(b.get("fonte") or "informado pelo usuário"), b.get("evidencia"),
                                             b.get("inicio"), b.get("fim")))
        except (TypeError, ValueError) as e:
            return err(e)

    async def regulatory_sync(request):
        return j(await run_in_threadpool(SP.sync_regulatory_relations, db))

    async def discover(request):
        q = request.query_params
        t = (q.get("q") or "").strip()
        if not t:
            return err("informe ?q=")
        return j(await run_in_threadpool(SP.discover, db, t[:200], q.get("familia") or None, q.get("produto") or None))

    async def evaluate(request):
        b = await body(request)
        try:
            return j(await run_in_threadpool(SP.evaluate, db, int(request.path_params["cid"]), str(b.get("dimensao") or "geral"),
                                             str(b.get("campo") or ""), str(b.get("valor") or ""), str(b.get("tipo") or ""), b.get("fonte"),
                                             b.get("documento")))
        except (KeyError, ValueError) as e:
            return err(e)

    async def link(request):
        b = await body(request)
        return j(await run_in_threadpool(SP.link_product, db, int(request.path_params["cid"]), b.get("produto_id"), b.get("familia"),
                                         str(b.get("relacao") or "fornece (declarado)"), str(b.get("fonte") or "informado pelo usuário"), b.get("evidencia")))

    async def match(request):
        q = request.query_params
        try:
            return j(await run_in_threadpool(SP.match_product, db, int(request.path_params["cid"]), q.get("produto"), q.get("familia"), q.get("q")))
        except KeyError as e:
            return err(e, 404)

    async def iy_status(request):
        return j(IY.status(db, sync.creds, settings()))

    async def iy_free(request):
        return j(await run_in_threadpool(IY.database_updated, db, sync.http, sync.creds))

    async def iy_query(request):
        b = await body(request)
        try:
            maxc = float(b.get("custo_maximo") or 0)
        except (TypeError, ValueError):
            maxc = 0.0
        r = await run_in_threadpool(IY.paid_query, db, sync.http, sync.creds, settings(), str(b.get("consulta") or ""),
                                    {k: v for k, v in (b.get("parametros") or {}).items()}, bool(b.get("autorizado")), maxc)
        if r.get("ok") and b.get("gravar_embarques"):
            r["importacao"] = await run_in_threadpool(SP.add_shipments, db, IY.shipments_from_response(r.get("dados")), "ImportYeti")
        return j(r)

    # ---------------------------------------------------------------- Import Intelligence
    async def import_view(request):
        q = (request.query_params.get("q") or "").strip()
        pid = (request.query_params.get("produto") or "").strip() or None
        if not q and not pid:
            return err("informe ?q= ou ?produto=")

        def calc():
            from ..intel import understanding as U
            u = U.understand(q or pid, None)
            p = (payload().get("produtos") or {}).get(pid or u.get("produto_id") or "")
            item = next((x for x in stages()["itens"] if x["produto_id"] == (pid or u.get("produto_id"))), None)
            hint = (db.query("SELECT ncm_hint FROM catalog_products WHERE product_id = ?", ((pid or u.get("produto_id") or "").split(":")[0],)) or [{}])[0].get("ncm_hint")
            ncm = IX.ncm_block(db, getattr(comp_state, "ncm", None), q or pid, hint)
            reg = IX.regulatory_block(db, q or pid)
            ls = MK.listing_stats(db, pid or u.get("produto_id") or "§", 30, today())
            from . import naming as NM
            return {"consulta": q or pid, "produto_id": pid or u.get("produto_id"), "identificacao": NM.describe(db, pid or u.get("produto_id"), u), "entendimento": {k: u.get(k) for k in ("principal", "estado", "atributos")},
                    "ncm": ncm, "regulatorio": reg, "riscos": IX.risks(u, reg, ncm, ls), "decisao": IX.classify_decision(p, item["estagio_evidencia"] if item else None),
                    "indicadores": IX.indicators(p, today().isoformat()), "simulador": {"campos": IX.FIELDS, "obrigatorios": IX.REQUIRED},
                    "cenarios": IX.list_scenarios(db, pid or u.get("produto_id")), "decisoes": IX.DECISION}
        return j(await run_in_threadpool(calc))

    async def simulate(request):
        b = await body(request)
        res = IX.simulate(b.get("parametros") or {})
        if res.get("calculado") and b.get("salvar"):
            res["salvo"] = IX.save_scenario(db, b.get("nome"), b.get("produto_id"), b.get("company_id"), b.get("parametros") or {}, res)
        return j(res)

    async def scenario_export(request):
        fmt = request.path_params["fmt"]
        r = db.query("SELECT * FROM import_scenarios WHERE id = ?", (int(request.path_params["sid"]),))
        if not r or fmt not in MIME:
            return j({"erro": "não encontrado"}, 404)
        data = await run_in_threadpool((EX.xlsx if fmt == "xlsx" else EX.pdf), "cenario", json.loads(r[0]["result"] or "{}"), f"Cenário: {r[0]['name'] or r[0]['id']}")
        return Response(data, media_type=MIME[fmt], headers={"Content-Disposition": f'attachment; filename="gpi-cenario-{r[0]["id"]}.{fmt}"'})

    # ---------------------------------------------------------------- monitorados / histórico
    async def mon_list(request):
        return j({"itens": await run_in_threadpool(MON.listing, db),
                  "nota": "Atualizados ao fim de cada sincronização (mesma rotina semanal) ou por 'Atualizar agora'."})

    async def mon_add(request):
        b = await body(request)
        try:
            return j(MON.add(db, str(b.get("tipo") or ""), str(b.get("ref") or ""), b.get("rotulo"), b.get("notas")))
        except ValueError as e:
            return err(e)

    async def mon_del(request):
        return j(MON.remove(db, int(request.path_params["mid"])))

    async def mon_refresh(request):
        return j(await run_in_threadpool(MON.refresh, db, payload, stages, today(), sync.context))

    async def diag_list(request):
        from . import diagnostics as DG
        return j({"itens": await run_in_threadpool(DG.rows, db, sync, cfg), "estados": DG.STATES,
                  "regras": ["O teste usa uma operação autorizada de baixo custo e não consome créditos pagos.",
                             "Credencial configurada não comprova permissão para todos os endpoints."]})

    async def diag_test(request):
        from . import diagnostics as DG
        return j(await run_in_threadpool(DG.test, db, sync, cfg, request.path_params["pid"][:40]))

    async def ml_preview(request):
        from . import diagnostics as DG
        b = await body(request)
        try:
            return j(await run_in_threadpool(DG.ml_search_preview, sync, str(b.get("q") or ""), int(b.get("limite") or 20)))
        except ValueError as e:
            return err(e)

    async def compliance_report(request):
        from ..compliance import features as CF
        from ..compliance import rules as CR
        from . import regassist
        b = await body(request)
        q = str(b.get("q") or "").strip()[:300]
        if not q:
            return err("informe o produto")
        fmt = request.path_params["fmt"]

        def calc():
            ach = CR.run(CF.extract({"descricao_tecnica": q}), None)
            f = regassist.ficha(db, q, {"achados": ach, "fontes": []}, b.get("fabricante"), b.get("modelo"))
            return (EX.xlsx if fmt == "xlsx" else EX.pdf)("conformidade", f, f"Conformidade preliminar: {f['produto']}")
        data = await run_in_threadpool(calc)
        return Response(data, media_type=MIME.get(fmt, MIME["xlsx"]), headers={"Content-Disposition": f'attachment; filename="gpi-conformidade-preliminar.{fmt}"'})

    async def research_cancel(request):
        return j(RS.cancel(db, int(request.path_params["rid"])))

    async def research_monitor(request):
        r = RS.get(db, int(request.path_params["rid"]))
        if not r or not r["result"]:
            return j({"erro": "pesquisa sem resultado"}, 404)
        return j(await run_in_threadpool(MON.from_research, db, r["result"], r["id"]))

    P = "/api/suite"
    return [
        Route(f"{P}/visao", overview), Route(f"{P}/config", config_get), Route(f"{P}/config", config_set, methods=["POST"]),
        Route(f"{P}/provedores", providers),
        Route(f"{P}/pesquisa", research_start, methods=["POST"]), Route(f"{P}/pesquisa/{{rid:int}}", research_get),
        Route(f"{P}/pesquisa/{{rid:int}}/salvar", research_save, methods=["POST"]),
        Route(f"{P}/pesquisa/{{rid:int}}/cancelar", research_cancel, methods=["POST"]),
        Route(f"{P}/conformidade/relatorio.{{fmt}}", compliance_report, methods=["POST"]),
        Route(f"{P}/diagnostico", diag_list), Route(f"{P}/diagnostico/{{pid}}/testar", diag_test, methods=["POST"]),
        Route(f"{P}/diagnostico/mercadolivre/pesquisa", ml_preview, methods=["POST"]),
        Route(f"{P}/pesquisa/{{rid:int}}/monitorar", research_monitor, methods=["POST"]),
        Route(f"{P}/pesquisa/{{rid:int}}.{{fmt}}", research_export), Route(f"{P}/historico", research_history),
        Route(f"{P}/nichos", niches), Route(f"{P}/nichos/salvar", niches_save, methods=["POST"]), Route(f"{P}/nichos.{{fmt}}", niches_export),
        Route(f"{P}/palavras", kw), Route(f"{P}/palavras.{{fmt}}", kw_export), Route(f"{P}/palavras/anuncio/{{iid}}", kw_reverse),
        Route(f"{P}/anuncio", mkt_listing), Route(f"{P}/anuncios/comparar", mkt_compare, methods=["POST"]),
        Route(f"{P}/tendencias", trend), Route(f"{P}/avaliacoes", reviews), Route(f"{P}/avaliacoes/arquivo", reviews_file, methods=["POST"]),
        Route(f"{P}/imagem/buscar", img_search, methods=["POST"]), Route(f"{P}/imagem/catalogo", img_catalog),
        Route(f"{P}/imagem/catalogo", img_add, methods=["POST"]), Route(f"{P}/imagem/comparar", img_compare, methods=["POST"]),
        Route(f"{P}/imagem/{{iid:int}}.jpg", img_file), Route(f"{P}/imagem/{{iid:int}}/excluir", img_delete, methods=["POST"]),
        Route(f"{P}/empresas", companies), Route(f"{P}/empresas", company_add, methods=["POST"]),
        Route(f"{P}/empresas/{{cid:int}}", company_get), Route(f"{P}/empresas/{{cid:int}}.{{fmt}}", company_export),
        Route(f"{P}/empresas/{{cid:int}}/rede", company_network), Route(f"{P}/empresas/{{cid:int}}/avaliar", evaluate, methods=["POST"]),
        Route(f"{P}/empresas/{{cid:int}}/produtos", link, methods=["POST"]), Route(f"{P}/empresas/{{cid:int}}/correspondencia", match),
        Route(f"{P}/duplicidades", merges), Route(f"{P}/duplicidades/{{rid:int}}", merge_decide, methods=["POST"]),
        Route(f"{P}/importar/{{kind}}", import_file, methods=["POST"]), Route(f"{P}/relacoes", relation_add, methods=["POST"]),
        Route(f"{P}/relacoes/regulatorias", regulatory_sync, methods=["POST"]), Route(f"{P}/descobrir", discover),
        Route(f"{P}/importyeti", iy_status), Route(f"{P}/importyeti/atualizacao", iy_free, methods=["POST"]),
        Route(f"{P}/importyeti/consulta", iy_query, methods=["POST"]),
        Route(f"{P}/importacao", import_view), Route(f"{P}/simular", simulate, methods=["POST"]),
        Route(f"{P}/cenarios/{{sid:int}}.{{fmt}}", scenario_export),
        Route(f"{P}/monitorados", mon_list), Route(f"{P}/monitorados", mon_add, methods=["POST"]),
        Route(f"{P}/monitorados/{{mid:int}}/excluir", mon_del, methods=["POST"]), Route(f"{P}/monitorados/atualizar", mon_refresh, methods=["POST"]),
    ]
