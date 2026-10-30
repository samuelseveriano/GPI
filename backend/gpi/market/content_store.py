"""Armazenamento de itens de conteúdo (vídeos, posts, comentários, artigos) e cotas de API."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .store import now_iso


class ContentStore:
    def __init__(self, db):
        self.db = db

    def upsert(self, source: str, rows: list[dict], keep_product: bool = False) -> dict:
        ts = now_iso()
        new = upd = 0
        with self.db.lock:
            for r in rows:
                if not r.get("item_id") or not r.get("url"):
                    continue
                exists = self.db.con.execute("SELECT product_key FROM content_items WHERE source = ? AND item_id = ?",
                                             (source, r["item_id"])).fetchone()
                m = json.dumps(r.get("metrics"), ensure_ascii=False) if r.get("metrics") is not None else None
                if exists:
                    pk = exists[0] if keep_product or not r.get("product_key") else r.get("product_key")
                    self.db.con.execute(
                        "UPDATE content_items SET title = ?, text = ?, metrics = COALESCE(?, metrics), refreshed_at = ?,"
                        " product_key = ? WHERE source = ? AND item_id = ?",
                        (r.get("title"), r.get("text"), m, ts, pk, source, r["item_id"]))
                    upd += 1
                else:
                    self.db.con.execute(
                        "INSERT INTO content_items (source, item_id, kind, title, text, url, author, published_at, lang,"
                        " category, product_key, query, metrics, collected_at, refreshed_at) VALUES"
                        " (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (source, r["item_id"], r.get("kind", "item"), r.get("title"), r.get("text"), r["url"],
                         r.get("author"), r.get("published_at"), r.get("lang"), r.get("category"),
                         r.get("product_key"), r.get("query"), m, ts, ts))
                    new += 1
            self.db.con.commit()
        return {"novos": new, "atualizados": upd}

    def ids_to_refresh(self, source: str, days: int) -> list[str]:
        cut = (datetime.now().astimezone() - timedelta(days=days)).isoformat(timespec="seconds")
        return [r["item_id"] for r in self.db.query(
            "SELECT item_id FROM content_items WHERE source = ? AND refreshed_at < ?", (source, cut))]

    def purge(self, source: str, days: int) -> int:
        cut = (datetime.now().astimezone() - timedelta(days=days)).isoformat(timespec="seconds")
        n = self.db.query("SELECT COUNT(*) AS n FROM content_items WHERE source = ? AND refreshed_at < ?",
                          (source, cut))[0]["n"]
        self.db.execute("DELETE FROM content_items WHERE source = ? AND refreshed_at < ?", (source, cut))
        return n

    def quota_used(self, provider: str, day: str) -> int:
        r = self.db.query("SELECT units FROM api_quota WHERE provider = ? AND day = ?", (provider, day))
        return int(r[0]["units"]) if r else 0

    def quota_add(self, provider: str, day: str, units: int):
        self.db.execute("INSERT INTO api_quota (provider, day, units) VALUES (?, ?, ?) ON CONFLICT(provider, day) "
                        "DO UPDATE SET units = units + excluded.units", (provider, day, units))

    def items(self, source: str | None = None, product_key: str | None = None, limit: int = 500,
              exclude_sources=(), label: str | None = None) -> list[dict]:
        sql, p = "SELECT * FROM content_items WHERE 1=1", []
        if source:
            sql += " AND source = ?"; p.append(source)
        if product_key:
            sql += " AND product_key = ?"; p.append(product_key)
        if label:
            sql += " AND sentiment_label = ?"; p.append(label)
        for s in exclude_sources:
            sql += " AND source <> ?"; p.append(s)
        sql += " ORDER BY published_at DESC LIMIT ?"
        p.append(limit)
        rows = self.db.query(sql, tuple(p))
        for r in rows:
            for k in ("metrics", "aspects"):
                r[k] = json.loads(r[k]) if r.get(k) else None
        return rows

    def count(self, source: str) -> dict:
        return self.db.query("SELECT COUNT(*) AS n, MIN(published_at) AS a, MAX(published_at) AS b FROM content_items "
                             "WHERE source = ?", (source,))[0]
