"""
Persistência dos dados de mercado com proveniência completa.

Cada série guarda: fonte, indicador, tipo (observado | estimado_terceiros |
derivado), produto, categoria, país, unidade, moeda, frequência, URL de origem,
método de obtenção e grau de confiabilidade. Cada observação guarda a data de
referência, a data de coleta e o número de revisões (quando a fonte corrige um
valor já coletado).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

KINDS = {"observado": "Histórico observado", "estimado_terceiros": "Estimado por terceiros",
         "derivado": "Série derivada (calculada pelo GPI)", "projecao": "Projeção do sistema"}
RELIABILITY = {"A": "Estatística oficial", "B": "Dados abertos de plataforma (contagem direta)",
               "C": "Estimativa de terceiros"}
SERIES_FIELDS = ("source", "indicator", "kind", "product_key", "product_name", "category",
                 "country", "unit", "currency", "freq", "origin_url", "method", "reliability")


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class MarketStore:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------ séries
    def upsert_series(self, series_key: str, meta: dict) -> int:
        missing = [f for f in ("source", "indicator", "kind", "freq") if not meta.get(f)]
        if missing:
            raise ValueError(f"metadados obrigatórios ausentes: {missing}")
        if meta["kind"] not in KINDS:
            raise ValueError(f"tipo de série inválido: {meta['kind']}")
        with self.db.lock:          # leitura + inserção atômicas (fontes coletam em paralelo)
            ts = now_iso()
            row = self.db.query("SELECT id FROM market_series WHERE series_key = ?", (series_key,))
            vals = [meta.get(f) for f in SERIES_FIELDS]
            if row:
                sid = row[0]["id"]
                sets = ", ".join(f"{f} = ?" for f in SERIES_FIELDS)
                self.db.execute(f"UPDATE market_series SET {sets}, last_collected = ? WHERE id = ?",
                                (*vals, ts, sid))
                return sid
            sid = self.db.next_id("market_series")
            self.db.execute(
                f"INSERT INTO market_series (id, series_key, {', '.join(SERIES_FIELDS)}, first_collected, last_collected)"
                f" VALUES (?, ?, {', '.join('?' * len(SERIES_FIELDS))}, ?, ?)",
                (sid, series_key, *vals, ts, ts))
            return sid

    def upsert_obs(self, series_id: int, obs: list[tuple[str, float]]) -> dict:
        """Insere ou revisa observações. Retorna contagem de novas/revisadas/iguais."""
        ts = now_iso()
        existing = {r["ref_date"]: r["value"] for r in self.db.query(
            "SELECT ref_date, value FROM market_obs WHERE series_id = ?", (series_id,))}
        new, revised, same = [], [], 0
        for d, v in obs:
            v = float(v)
            if d not in existing:
                new.append((series_id, d, v, ts))
            elif abs(existing[d] - v) > 1e-9 * max(1.0, abs(v)):
                revised.append((v, ts, series_id, d))
            else:
                same += 1
        with self.db.lock:
            if new:
                self.db.con.executemany(
                    "INSERT INTO market_obs (series_id, ref_date, value, collected_at, revision) VALUES (?, ?, ?, ?, 0)", new)
            if revised:
                self.db.con.executemany(
                    "UPDATE market_obs SET value = ?, collected_at = ?, revision = revision + 1 "
                    "WHERE series_id = ? AND ref_date = ?", revised)
            self.db.con.commit()
        return {"novas": len(new), "revisadas": len(revised), "iguais": same}

    def series(self, **filters) -> list[dict]:
        sql = "SELECT s.*, (SELECT COUNT(*) FROM market_obs o WHERE o.series_id = s.id) AS n_obs, " \
              "(SELECT MIN(ref_date) FROM market_obs o WHERE o.series_id = s.id) AS inicio, " \
              "(SELECT MAX(ref_date) FROM market_obs o WHERE o.series_id = s.id) AS fim FROM market_series s WHERE 1=1"
        p = []
        for k, v in filters.items():
            if v is not None:
                sql += f" AND s.{k} = ?"
                p.append(v)
        return self.db.query(sql + " ORDER BY s.id", tuple(p))

    def get_series(self, sid: int) -> dict | None:
        r = self.series(id=sid)
        return r[0] if r else None

    def values(self, sid: int) -> pd.Series:
        rows = self.db.query("SELECT ref_date, value FROM market_obs WHERE series_id = ? ORDER BY ref_date", (sid,))
        if not rows:
            return pd.Series(dtype=float)
        return pd.Series([r["value"] for r in rows], index=[r["ref_date"] for r in rows], dtype=float)

    def obs_detail(self, sid: int) -> list[dict]:
        return self.db.query("SELECT ref_date, value, collected_at, revision FROM market_obs "
                             "WHERE series_id = ? ORDER BY ref_date", (sid,))

    # ------------------------------------------------------------------ produtos
    def upsert_product(self, key: str, **f):
        row = self.db.query("SELECT product_key FROM products WHERE product_key = ?", (key,))
        cols = ("name_pt", "name_en", "name_zh", "category", "origin", "hs_codes", "norm_tokens")
        if row:
            sets = [(c, f[c]) for c in cols if f.get(c) is not None]
            if sets:
                self.db.execute(f"UPDATE products SET {', '.join(c + ' = ?' for c, _ in sets)} WHERE product_key = ?",
                                (*[v for _, v in sets], key))
        else:
            self.db.execute(
                f"INSERT INTO products (product_key, {', '.join(cols)}, discovered_at) VALUES (?, {', '.join('?' * len(cols))}, ?)",
                (key, *[f.get(c) for c in cols], now_iso()))

    def products(self) -> list[dict]:
        return self.db.query("SELECT * FROM products ORDER BY category, product_key")

    # ------------------------------------------------------------------ status das fontes
    def set_source_status(self, source: str, state: str, message: str = "", success: bool = False,
                          validated: bool | None = None):
        ts = now_iso()
        cur = self.db.query("SELECT * FROM source_status WHERE source = ?", (source,))
        stats = self.db.query(
            "SELECT COUNT(*) AS n, MIN(o.ref_date) AS a, MAX(o.ref_date) AS b FROM market_obs o "
            "JOIN market_series s ON s.id = o.series_id WHERE s.source = ?", (source,))[0]
        try:
            cs = self.db.query("SELECT COUNT(*) AS n, MIN(published_at) AS a, MAX(published_at) AS b "
                               "FROM content_items WHERE source = ?", (source,))[0]
        except Exception:  # noqa: BLE001 — banco anterior à migração v3
            cs = {"n": 0}
        if cs["n"]:
            stats = {"n": stats["n"] + cs["n"], "a": min(x for x in (stats["a"], cs["a"]) if x) if (stats["a"] or cs["a"]) else None,
                     "b": max(x for x in (stats["b"], cs["b"]) if x) if (stats["b"] or cs["b"]) else None}
        if validated and not stats["n"]:
            # a API respondeu, mas nenhum registro foi gravado: não há evidência de coleta → não validada
            validated, state = False, "sem dados"
            message = (message + "; " if message else "") + "a fonte respondeu, mas nenhum registro foi gravado ainda"
        if cur:
            c = cur[0]
            self.db.execute(
                "UPDATE source_status SET state = ?, message = ?, last_attempt = ?, last_success = ?, validated = ?,"
                " records = ?, coverage_start = ?, coverage_end = ?, failures = ? WHERE source = ?",
                (state, message, ts, ts if success else c["last_success"],
                 int(validated if validated is not None else c["validated"]), stats["n"], stats["a"], stats["b"],
                 0 if success else c["failures"] + (1 if state == "falhou" else 0), source))
        else:
            self.db.execute(
                "INSERT INTO source_status (source, state, message, last_attempt, last_success, validated, records,"
                " coverage_start, coverage_end, failures) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source, state, message, ts, ts if success else None, int(bool(validated)), stats["n"],
                 stats["a"], stats["b"], 1 if state == "falhou" else 0))

    def source_status(self) -> dict:
        return {r["source"]: r for r in self.db.query("SELECT * FROM source_status")}

    # ------------------------------------------------------------------ resultados de análise
    def save_result(self, name: str, payload):
        self.db.execute("INSERT INTO analysis_results (name, created_at, payload) VALUES (?, ?, ?) "
                        "ON CONFLICT(name) DO UPDATE SET created_at = excluded.created_at, payload = excluded.payload",
                        (name, now_iso(), json.dumps(payload, ensure_ascii=False)))

    def load_result(self, name: str):
        r = self.db.query("SELECT created_at, payload FROM analysis_results WHERE name = ?", (name,))
        if not r:
            return None
        out = json.loads(r[0]["payload"])
        if isinstance(out, dict):
            out["_gerado_em"] = r[0]["created_at"]
        return out
