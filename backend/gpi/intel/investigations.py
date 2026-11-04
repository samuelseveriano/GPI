"""Lista de investigação de produtos (v0.8, seção 25). Dados locais do usuário; nunca saem do computador."""
from __future__ import annotations

import json
from datetime import datetime

STATES = ["Novo sinal", "Em observação", "Investigação comercial", "Investigação técnica", "Investigação regulatória",
          "Aguardando fornecedor", "Aguardando dados", "Concluído", "Arquivado"]
ACTIVE = STATES[:7]
LIST_FIELDS = ("evidencias", "fontes", "fornecedores", "concorrentes", "exigencias", "documentos", "proximas_acoes")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _row(r: dict) -> dict:
    for k in LIST_FIELDS:
        try:
            r[k] = json.loads(r[k]) if r.get(k) else []
        except ValueError:
            r[k] = [r[k]]
    return r


def add(db, data: dict) -> dict:
    produto = (data.get("produto") or "").strip()
    if not produto:
        raise ValueError("informe o produto")
    estado = data.get("estado") or "Novo sinal"
    if estado not in STATES:
        raise ValueError("estado inválido")
    pid = data.get("produto_id")
    if pid:
        ex = db.query("SELECT id FROM investigations WHERE produto_id = ? AND estado NOT IN ('Concluído', 'Arquivado')", (pid,))
        if ex:
            return get(db, ex[0]["id"]) | {"ja_existia": True}
    ts = _now()
    vals = [json.dumps(_as_list(data.get(k)), ensure_ascii=False)[:8000] for k in LIST_FIELDS]
    with db.transaction():
        cur = db.execute("INSERT INTO investigations (produto_id, produto, estado, motivo, evidencias, fontes, fornecedores, concorrentes,"
                         " exigencias, documentos, proximas_acoes, criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (pid, produto[:200], estado, (data.get("motivo") or "")[:2000], *vals, ts, ts))
        iid = int(cur.lastrowid)
        db.execute("INSERT INTO investigation_events (investigation_id, estado, nota, criado_em) VALUES (?,?,?,?)",
                   (iid, estado, "criada", ts))
    return get(db, iid)


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x)[:500] for x in v][:100]
    return [x.strip() for x in str(v).split("\n") if x.strip()][:100]


def update(db, iid: int, data: dict) -> dict:
    cur = get(db, iid)
    if not cur:
        raise KeyError("investigação não encontrada")
    sets, params = [], []
    if "estado" in data:
        if data["estado"] not in STATES:
            raise ValueError("estado inválido")
        sets.append("estado = ?")
        params.append(data["estado"])
    if "motivo" in data:
        sets.append("motivo = ?")
        params.append((data["motivo"] or "")[:2000])
    for k in LIST_FIELDS:
        if k in data:
            sets.append(f"{k} = ?")
            params.append(json.dumps(_as_list(data[k]), ensure_ascii=False)[:8000])
    ts = _now()
    with db.transaction():
        if sets:
            db.execute(f"UPDATE investigations SET {', '.join(sets)}, atualizado_em = ? WHERE id = ?", (*params, ts, iid))
        if data.get("estado") and data["estado"] != cur["estado"] or data.get("nota"):
            db.execute("INSERT INTO investigation_events (investigation_id, estado, nota, criado_em) VALUES (?,?,?,?)",
                       (iid, data.get("estado") or cur["estado"], (data.get("nota") or "")[:1000], ts))
    return get(db, iid)


def get(db, iid: int) -> dict | None:
    r = db.query("SELECT * FROM investigations WHERE id = ?", (iid,))
    if not r:
        return None
    out = _row(r[0])
    out["historico"] = db.query("SELECT estado, nota, criado_em FROM investigation_events WHERE investigation_id = ? ORDER BY id", (iid,))
    return out


def list_all(db, estado: str | None = None) -> dict:
    rows = db.query("SELECT * FROM investigations" + (" WHERE estado = ?" if estado else "") + " ORDER BY atualizado_em DESC",
                    (estado,) if estado else ())
    items = [_row(r) for r in rows]
    return {"itens": items, "estados": STATES, "contagem": {s: sum(1 for i in items if i["estado"] == s) for s in STATES},
            "ativas": sum(1 for i in items if i["estado"] in ACTIVE)}


def active_count(db) -> int:
    try:
        return int(db.query(f"SELECT COUNT(*) AS n FROM investigations WHERE estado IN ({','.join('?' * len(ACTIVE))})", tuple(ACTIVE))[0]["n"])
    except Exception:  # noqa: BLE001
        return 0
