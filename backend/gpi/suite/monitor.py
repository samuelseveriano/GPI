"""Produtos e fornecedores monitorados. Sem agendador próprio: os instantâneos são atualizados no fim de cada
sincronização (a mesma rotina semanal do GPI) ou quando o usuário pede 'Atualizar agora'.

Uma pesquisa manual pode virar monitoramento semanal com os termos (pt/en), o mercado e as fontes pertinentes: na
sincronização seguinte as MESMAS consultas direcionadas (modo rápido, respeitando cache e cotas) são repetidas e o
histórico permitido é acumulado — o produto não precisa aparecer no Radar Comercial."""
from __future__ import annotations

import json
from datetime import date

from . import marketplace as MK
from . import naming as NM
from . import store as S

EVENTS_SQL = """CREATE TABLE IF NOT EXISTS monitor_events (id INTEGER PRIMARY KEY AUTOINCREMENT, monitored_id INTEGER NOT NULL, at TEXT NOT NULL,
    mudancas TEXT NOT NULL)"""
KINDS = ("produto", "fornecedor")


def ensure(db):
    S.ensure(db)
    db.execute(EVENTS_SQL)


def add(db, kind: str, ref: str, label: str | None = None, notes: str | None = None, params: dict | None = None) -> dict:
    ensure(db)
    if kind not in KINDS:
        raise ValueError("tipo deve ser 'produto' ou 'fornecedor'")
    ref = str(ref).strip()[:200]
    if not ref:
        raise ValueError("referência vazia")
    if kind == "produto" and not label:
        label = NM.name_of(db, ref) if not ref.startswith("termo:") else ref[6:]
    pj = json.dumps(params, ensure_ascii=False) if params else None
    db.execute("INSERT INTO monitored (kind, ref, label, created_at, notes, params) VALUES (?, ?, ?, ?, ?, ?) "
               "ON CONFLICT(kind, ref) DO UPDATE SET params = COALESCE(excluded.params, monitored.params), label = COALESCE(excluded.label, monitored.label)",
               (kind, ref, (label or ref)[:200], S.now(), (notes or "")[:500] or None, pj))
    return {"ok": True, "semanal": bool(params)}


def from_research(db, result: dict, research_id: int) -> dict:
    """Transforma uma pesquisa em monitoramento semanal (termos, mercado e fontes pertinentes)."""
    ov = (result.get("abas") or {}).get("visao_geral") or {}
    pid = ov.get("produto_id")
    terms = ov.get("termos_consulta") or {"pt": result["consulta"], "en": result["consulta"]}
    par = result.get("parametros") or {}
    fontes = sorted({r["id"] for r in (result.get("coleta") or {}).get("resultados", []) if r["estado"] not in ("ignorada (modo rápido)",)})
    from . import targeted as TG
    ref = pid or f"termo:{TG._norm(result['consulta'])}"
    params = {"termos": terms, "mercado": par.get("mercado") or "BR", "comparacao": par.get("comparacao") or [], "fontes": fontes,
              "produto_id": pid, "pesquisa_origem": research_id, "consulta": result["consulta"]}
    r = add(db, "produto", ref, ov.get("produto") or result["consulta"], f"criado a partir da pesquisa nº {research_id}", params)
    return {**r, "ref": ref, "parametros": params}


def snapshot_product(db, pid: str, payload: dict | None, stages: dict | None, today: date, params: dict | None = None) -> dict:
    real = None if pid.startswith("termo:") else pid
    p = ((payload or {}).get("produtos") or {}).get(real or "") or {}
    st = next((x for x in (stages or {}).get("itens", []) if x["produto_id"] == real), None)
    terms = [t for t in ((params or {}).get("termos") or {}).values() if t]
    ls = MK.listing_stats(db, real, 30, today, terms) or {}
    vol = None
    if terms or real:
        from ..products import nlp
        tn = [nlp._norm(t) for t in terms] or ["§"]
        r = db.query("SELECT MAX(ref_date) AS m, COUNT(*) AS n FROM search_observations WHERE source IN ('google_ads_kp', 'msads_kp') AND "
                     "(product_id = ? OR LOWER(term) IN (%s))" % ",".join("?" * len(tn)), (real or "§", *tn))[0]
        vol = {"meses": r["n"], "ultimo_mes": r["m"]} if r["n"] else None
    return {"estagio": st["nome_estagio"] if st else None, "situacao": p.get("situacao"),
            "opportunity_score": (p.get("indices") or {}).get("opportunity_score"), "evidence_coverage": (p.get("indices") or {}).get("evidence_coverage"),
            "evidencias": len(p.get("evidencias") or []), "anuncios_30d": ls.get("anuncios"), "preco_mediano": ls.get("preco_mediano"),
            "vendedores": ls.get("vendedores_distintos"), "volume_meses": (vol or {}).get("meses"), "volume_ultimo_mes": (vol or {}).get("ultimo_mes")}


def snapshot_supplier(db, cid: str) -> dict:
    c = int(cid)
    s = db.query("SELECT COUNT(*) AS n, MAX(date) AS ult FROM trade_shipments WHERE exporter_id = ? OR importer_id = ?", (c, c))[0]
    return {"embarques": s["n"], "ultimo_embarque": s["ult"],
            "relacoes": db.query("SELECT COUNT(*) AS n FROM trade_relationships WHERE a_id = ? OR b_id = ?", (c, c))[0]["n"],
            "avaliacoes": db.query("SELECT COUNT(*) AS n FROM supplier_evaluations WHERE company_id = ?", (c,))[0]["n"],
            "verificacao": (db.query("SELECT verification_status FROM companies WHERE company_id = ?", (c,)) or [{}])[0].get("verification_status")}


def diff(old: dict | None, new: dict) -> list[dict]:
    if not old:
        return []
    return [{"campo": k, "antes": old.get(k), "depois": v} for k, v in new.items() if old.get(k) != v]


def refresh(db, payload_fn=None, stages_fn=None, today: date | None = None, sync_ctx_fn=None) -> dict:
    """Com `sync_ctx_fn`, repete as consultas direcionadas compatíveis dos produtos monitorados (modo rápido: cache de
    7 dias, mercado principal, cotas respeitadas) antes de tirar o instantâneo."""
    ensure(db)
    today = today or date.today()
    rows = db.query("SELECT * FROM monitored")
    if not rows:
        return {"monitorados": 0, "mudancas": 0, "consultas": 0}
    consultas = 0
    if sync_ctx_fn:
        from . import targeted as TG
        for r in rows:
            par = json.loads(r["params"] or "null")
            if r["kind"] != "produto" or not par or not par.get("termos"):
                continue
            try:
                res = TG.collect(db, sync_ctx_fn, par["termos"].get("pt") or par.get("consulta"), par["termos"].get("en") or par.get("consulta"),
                                 par.get("produto_id"), [par.get("mercado") or "BR"], "rapida")
                consultas += sum(1 for x in res if x["consulta_realizada"])
            except Exception:  # noqa: BLE001
                continue
    payload = stages = None
    if any(r["kind"] == "produto" for r in rows):
        try:
            payload = payload_fn() if payload_fn else None
            stages = stages_fn() if stages_fn else None
        except Exception:  # noqa: BLE001
            payload = stages = None
    changes = 0
    for r in rows:
        try:
            snap = (snapshot_product(db, r["ref"], payload, stages, today, json.loads(r["params"] or "null")) if r["kind"] == "produto"
                    else snapshot_supplier(db, r["ref"]))
        except Exception:  # noqa: BLE001
            continue
        old = json.loads(r["last_snapshot"]) if r["last_snapshot"] else None
        d = diff(old, snap)
        if d:
            db.execute("INSERT INTO monitor_events (monitored_id, at, mudancas) VALUES (?, ?, ?)", (r["id"], S.now(), json.dumps(d, ensure_ascii=False, default=str)))
            changes += 1
        db.execute("UPDATE monitored SET last_snapshot = ?, last_checked = ? WHERE id = ?", (json.dumps(snap, ensure_ascii=False, default=str), S.now(), r["id"]))
    return {"monitorados": len(rows), "mudancas": changes, "consultas": consultas}


def listing(db) -> list[dict]:
    ensure(db)
    rows = db.query("SELECT * FROM monitored ORDER BY kind, label")
    for r in rows:
        r["last_snapshot"] = json.loads(r["last_snapshot"]) if r["last_snapshot"] else None
        r["params"] = json.loads(r["params"]) if r.get("params") else None
        r["semanal"] = bool(r["params"])
        r["eventos"] = [{"at": e["at"], "mudancas": json.loads(e["mudancas"])} for e in
                        db.query("SELECT at, mudancas FROM monitor_events WHERE monitored_id = ? ORDER BY id DESC LIMIT 10", (r["id"],))]
    return rows
