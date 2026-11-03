"""v0.7 — retirada das fontes inviáveis sem perder histórico."""
from __future__ import annotations

import sqlite3

from test_api_integration import Srv

from gpi.connectors.registry import REMOVED_SOURCES, all_connectors, removed_label
from gpi.db import MIGRATIONS, Database
from gpi.integrations.registry import PROVIDERS

GONE = {"reclame_aqui", "baidu_index", "ocean_engine", "alibaba", "alibaba_insights", "jd_com"}


def _old_db(path):
    """Banco no esquema 6 (v0.6.1) com dados das fontes que serão retiradas."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE schema_version (v INTEGER NOT NULL)")
    for i, stmts in enumerate(MIGRATIONS[:6], start=1):
        for s in stmts:
            con.execute(s)
        con.execute("INSERT INTO schema_version VALUES (?)", (i,))
    con.execute("INSERT INTO search_observations (source, country, term, ref_date, period, metric, value, unit, collected_at)"
                " VALUES ('baidu_index', 'CN', '空气炸锅', '2026-01-05', 'semana', 'interesse_relativo', 80, 'indice', '2026-01-06')")
    con.execute("INSERT INTO search_observations (source, country, term, ref_date, period, metric, value, unit, collected_at)"
                " VALUES ('google_trends_rss', 'BR', 'air fryer', '2026-01-05', 'dia', 'trafego_faixa', 2000, 'buscas', '2026-01-06')")
    con.execute("INSERT INTO source_status (source, state, records) VALUES ('baidu_index', 'restrita', 1)")
    con.execute("INSERT INTO source_status (source, state, records) VALUES ('reclame_aqui', 'falhou', 0)")
    con.execute("INSERT INTO sync_jobs (job_key, source, params, state, updated_at) VALUES ('jd:1', 'jd_com', '{}', 'pending', '2026-01-01')")
    con.execute("INSERT INTO catalog_products (product_id, name, category, created_at, updated_at) VALUES "
                "('air_fryer', 'Air fryer', 'Casa', '2026-01-01', '2026-01-01')") if _has_cols(con) else None
    con.commit()
    con.close()


def _has_cols(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(catalog_products)")}
    return {"product_id", "name", "category", "created_at", "updated_at"} <= cols


def test_registry_and_ui_without_removed_sources():
    ids = {c.id for c in all_connectors()}
    assert not ids & GONE
    provs = {p["id"] for p in PROVIDERS}
    assert "china_search" not in provs and "reclame_aqui" not in provs
    conect = {c for p in PROVIDERS for c in p.get("conectores", [])}
    assert not conect & GONE
    assert set(REMOVED_SOURCES) == GONE and "descontinuada" in removed_label("jd_com")


def test_migration_is_non_destructive(tmp_path):
    path = tmp_path / "gpi.sqlite"
    _old_db(path)
    db = Database(path)
    assert db.schema_version() == len(MIGRATIONS)
    n = db.query("SELECT COUNT(*) AS n FROM search_observations")[0]["n"]
    assert n == 2                                                 # histórico preservado (inclusive Baidu)
    st = {r["source"]: r["state"] for r in db.query("SELECT source, state FROM source_status")}
    assert st["baidu_index"] == "removida" and st["reclame_aqui"] == "removida"
    assert db.query("SELECT state FROM sync_jobs WHERE source = 'jd_com'")[0]["state"] == "removida"
    db.close()


def test_api_lists_removed_with_history_and_failed_excludes_them(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _old_db(data / "gpi.sqlite")
    s = Srv(data)
    try:
        code, r = s.req("/api/sources/removed")
        assert code == 200
        by = {f["id"]: f for f in r["fontes"]}
        assert by["baidu_index"]["registros_historicos"] == 1 and by["jd_com"]["estado"] == "removida"
        code, integ = s.req("/api/integrations")
        assert code == 200 and not {p["id"] for p in integ} & {"china_search", "reclame_aqui"}
        assert "reclame_aqui" not in s.app.state.sync.failed_sources()
        code, panel = s.req("/api/sync/panel")
        assert code == 200
        txt = str(panel)
        assert "baidu_index" not in txt and "jd_com" not in txt
        code, _ = s.req("/api/status")
        assert code == 200
    finally:
        s.stop()


def test_plan_creates_no_jobs_for_removed(tmp_path):
    s = Srv(tmp_path / "data")
    try:
        sync = s.app.state.sync
        assert not {c.id for c in sync.connectors} & GONE
    finally:
        s.stop()
