"""Rotas v0.9 — Product Understanding, revisão humana, evidências de vídeo, estágios, investigação e alertas."""
from __future__ import annotations

import json
import time

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import understanding as U
from . import understanding_eval as E


def routes(db, sync, cfg) -> list[Route]:
    def j(o, code=200):
        return JSONResponse(o, status_code=code)

    async def body(request: Request) -> dict:
        try:
            b = await request.json()
            return b if isinstance(b, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    async def understanding_view(request):
        U.ensure(db)

        def calc():
            ev = {}
            for name in ("understanding_test_v09.tsv", "understanding_dev_v09.tsv"):
                r = E.evaluate(E.load(name), E.baseline_analyzer)
                r["erros"] = r["erros"][:20]
                ev["teste" if "test" in name else "desenvolvimento"] = r
            levels = {r["tipo"]: r["n"] for r in db.query("SELECT tipo, COUNT(*) AS n FROM product_taxonomy GROUP BY tipo")}
            rev = {r["k"]: r["n"] for r in db.query("SELECT CASE WHEN decisao IS NULL THEN 'pendentes' ELSE 'decididas' END AS k, "
                                                       "COUNT(*) AS n FROM association_review GROUP BY k")}
            last = db.query("SELECT payload FROM analysis_results WHERE name = 'v09_reavaliacao_conteudo'")
            return {"avaliacao": ev, "taxonomia": levels, "revisao": rev,
                    "reavaliacao_videos": json.loads(last[0]["payload"]) if last else None,
                    "nota": "Conjuntos rotulados pequenos e escritos pelo mesmo autor das regras: mostram que as classes de erro "
                            "conhecidas foram corrigidas, não substituem a revisão em dados reais (fila de revisão)."}
        return j(await run_in_threadpool(calc))

    async def understand_text(request):
        t = (request.query_params.get("texto") or "")[:500]
        if not t.strip():
            return j({"erro": "informe ?texto="}, 400)
        return j(U.understand(t, request.query_params.get("idioma") or None, request.query_params.get("alvo") or None))

    async def taxonomy(request):
        U.ensure(db)
        lv = request.query_params.get("nivel")
        q = "SELECT * FROM product_taxonomy" + (" WHERE nivel = ?" if lv else "") + " ORDER BY nivel, observacoes DESC LIMIT 2000"
        return j({"nos": db.query(q, (int(lv),) if lv else ()), "niveis": U.LEVELS})

    async def review_list(request):
        U.ensure(db)
        pend = request.query_params.get("todas") != "1"
        rows = db.query("SELECT * FROM association_review" + (" WHERE decisao IS NULL" if pend else "") +
                        " ORDER BY criado_em DESC LIMIT 500")
        for r in rows:
            r["motivos"] = json.loads(r["motivos"] or "[]")
        return j({"itens": rows, "regra": "Associação ambígua ou provável não alimenta conclusões comerciais até ser confirmada aqui."})

    async def review_decide(request):
        U.ensure(db)
        rid = int(request.path_params["rid"])
        b = await body(request)
        dec = b.get("decisao")
        if dec not in ("confirmar", "rejeitar"):
            return j({"erro": "decisao deve ser 'confirmar' ou 'rejeitar'"}, 400)
        prod = str(b.get("produto") or "").strip()[:120] or None
        if dec == "confirmar" and not prod:
            return j({"erro": "informe o produto (chave do catálogo) ao confirmar"}, 400)
        row = db.query("SELECT fonte, item_id FROM association_review WHERE id = ?", (rid,))
        if not row:
            return j({"erro": "item não encontrado"}, 404)
        db.execute("UPDATE association_review SET decisao = ?, produto_decidido = ?, decidido_em = ?, justificativa = ? WHERE id = ?",
                   (dec, prod, time.strftime("%Y-%m-%dT%H:%M:%S"), str(b.get("justificativa") or "")[:300], rid))
        if row[0]["fonte"] == "youtube":
            db.execute("UPDATE content_items SET product_key = ? WHERE source = 'youtube' AND item_id = ?",
                       (prod if dec == "confirmar" else None, row[0]["item_id"]))
        return j({"ok": True})

    async def product_videos(request):
        """Módulo de evidências de vídeo por produto (seção 5.4). Métricas oficiais do YouTube exibidas como tais;
        contexto e atributos são do GPI; nada vira demanda ou satisfação."""
        pid = request.path_params["pid"]
        rows = db.query("SELECT item_id, title, author, published_at, url, metrics FROM content_items "
                        "WHERE source = 'youtube' AND product_key = ? ORDER BY published_at DESC LIMIT 200", (pid,))
        U.ensure(db)
        pend = db.query("SELECT r.item_id, r.texto, r.motivos FROM association_review r WHERE r.fonte = 'youtube' AND r.decisao IS NULL "
                        "AND r.sugestao = ? LIMIT 50", (pid.split("+")[0],))
        out = []
        for r in rows:
            m = json.loads(r["metrics"] or "{}")
            cv = m.get("correspondencia_v09") or {}
            out.append({"titulo": r["title"], "canal": r["author"], "data": r["published_at"], "url": r["url"],
                        "metricas_oficiais_youtube": {k: m.get(k) for k in ("viewCount", "likeCount", "commentCount") if k in m},
                        "contexto_gpi": (m.get("contexto_gpi") or {}).get("rotulo"), "nivel": cv.get("nivel"),
                        "atributos_explicitos": m.get("atributos_explicitos") or {}, "correspondencia": cv.get("estado")})
        return j({"produto": pid, "videos": out, "nao_confirmados": [{"titulo": p["texto"], "motivos": json.loads(p["motivos"] or "[]")}
                                                                      for p in pend],
                  "avisos": ["Visualizações não são vendas; curtidas não são satisfação de compradores.",
                             "Contexto (review, unboxing…) é classificação textual do GPI, não categoria do YouTube.",
                             "O YouTube não é usado como confirmação independente de demanda comercial."]})

    rs = [Route("/api/v09/compreensao", understanding_view), Route("/api/v09/entender", understand_text),
          Route("/api/v09/taxonomia", taxonomy), Route("/api/v09/revisao", review_list),
          Route("/api/v09/revisao/{rid:int}", review_decide, methods=["POST"]),
          Route("/api/v09/produto/{pid:path}/videos", product_videos)]
    try:
        from .decision import routes as decision_routes   # estágios, investigação, alertas (v0.9)
        rs += decision_routes(db, sync, cfg)
    except ImportError:
        pass
    return rs
