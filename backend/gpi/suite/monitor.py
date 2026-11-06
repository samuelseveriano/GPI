"""Produtos e fornecedores monitorados. Sem agendador próprio: os instantâneos são atualizados no fim de cada
sincronização (a mesma rotina semanal do GPI) ou quando o usuário pede 'Atualizar agora'."""
from __future__ import annotations

import json
from datetime import date

from . import marketplace as MK
from . import store as S

EVENTS_SQL = """CREATE TABLE IF NOT EXISTS monitor_events (id INTEGER PRIMARY KEY AUTOINCREMENT, monitored_id INTEGER NOT NULL, at TEXT NOT NULL,
    mudancas TEXT NOT NULL)"""
KINDS = ("produto", "fornecedor")


def ensure(db):
    S.ensure(db)
    db.execute(EVENTS_SQL)


def add(db, kind: str, ref: str, label: str | None = None, notes: str | None = None) -> dict:
    ensure(db)
    if kind not in KINDS:
        raise ValueError("tipo deve ser 'produto' ou 'fornecedor'")
    ref = str(ref).strip()[:200]
    if not ref:
        raise ValueError("referência vazia")
    db.execute("INSERT OR IGNORE INTO monitored (kind, ref, label, created_at, notes) VALUES (?, ?, ?, ?, ?)",
               (kind, ref, (label or ref)[:200], S.now(), (notes or "")[:500] or None))
    return {"ok": True}


def remove(db, mid: int) -> dict:
    ensure(db)
    db.execute("DELETE FROM monitored WHERE id = ?", (mid,))
    return {"ok": True}


def snapshot_product(db, pid: str, payload: dict | None, stages: dict | None, today: date) -> dict:
    p = ((payload or {}).get("produtos") or {}).get(pid) or {}
    st = next((x for x in (stages or {}).get("itens", []) if x["produto_id"] == pid), None)
    ls = MK.listing_stats(db, pid, 30, today) or {}
    return {"estagio": st["nome_estagio"] if st else None, "situacao": p.get("situacao"),
            "opportunity_score": (p.get("indices") or {}).get("opportunity_score"), "evidence_coverage": (p.get("indices") or {}).get("evidence_coverage"),
            "evidencias": len(p.get("evidencias") or []), "anuncios_30d": ls.get("anuncios"), "preco_mediano": ls.get("preco_mediano"),
            "vendedores": ls.get("vendedores_distintos")}


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
    out = []
    for k, v in new.items():
        if old.get(k) != v:
            out.append({"campo": k, "antes": old.get(k), "depois": v})
    return out


def refresh(db, payload_fn=None, stages_fn=None, today: date | None = None) -> dict:
    ensure(db)
    today = today or date.today()
    rows = db.query("SELECT * FROM monitored")
    if not rows:
        return {"monitorados": 0, "mudancas": 0}
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
            snap = snapshot_product(db, r["ref"], payload, stages, today) if r["kind"] == "produto" else snapshot_supplier(db, r["ref"])
        except Exception:  # noqa: BLE001
            continue
        old = json.loads(r["last_snapshot"]) if r["last_snapshot"] else None
        d = diff(old, snap)
        if d:
            db.execute("INSERT INTO monitor_events (monitored_id, at, mudancas) VALUES (?, ?, ?)", (r["id"], S.now(), json.dumps(d, ensure_ascii=False, default=str)))
            changes += 1
        db.execute("UPDATE monitored SET last_snapshot = ?, last_checked = ? WHERE id = ?", (json.dumps(snap, ensure_ascii=False, default=str), S.now(), r["id"]))
    return {"monitorados": len(rows), "mudancas": changes}


def listing(db) -> list[dict]:
    ensure(db)
    rows = db.query("SELECT * FROM monitored ORDER BY kind, label")
    for r in rows:
        r["last_snapshot"] = json.loads(r["last_snapshot"]) if r["last_snapshot"] else None
        r["eventos"] = [{"at": e["at"], "mudancas": json.loads(e["mudancas"])} for e in
                        db.query("SELECT at, mudancas FROM monitor_events WHERE monitored_id = ? ORDER BY id DESC LIMIT 10", (r["id"],))]
    return rows
