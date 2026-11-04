"""v0.7.1 — correção do sincronizador (caso real do Mercado Livre: API respondia 50 termos, mas o painel mostrava
0 requisições, 0 registros e "Atualizado"). Respostas SIMULADAS no formato da API oficial."""
from __future__ import annotations

import time

from test_v05 import Creds

from gpi.connectors.http import SourceError
from gpi.connectors.sources5 import MercadoLivreTrends
from gpi.connectors.restricted import MercadoLivre
from gpi.db import Database
from gpi.market.sync import SyncManager

TERMS = [{"keyword": f"termo {i}", "url": f"https://lista.mercadolivre.com.br/termo-{i}"} for i in range(1, 51)]


class MLHttp:
    """Mesma interface do HttpClient; conta requisições reais (sem cache) e simula falhas."""

    def __init__(self, fail=None):
        self.fail, self.calls = fail, 0
        import threading
        self.cancel_event = threading.Event()
        self.cache = {}

    def request_json(self, url, method="GET", body=None, headers=None, ttl=None, form=None, **kw):
        if ttl and url in self.cache:
            return self.cache[url]
        self.calls += 1
        if self.fail:
            raise self.fail
        assert headers["Authorization"].startswith("Bearer ")
        out = list(TERMS)
        if ttl:
            self.cache[url] = out
        return out


def _sm(tmp_path, http, conns=None):
    db = Database(tmp_path / "s.sqlite")
    creds = Creds({"mercadolivre": {"access_token": "APP_USR-x", "refresh_token": "TG-r", "expires_at": str(time.time() + 9999),
                                    "client_id": "1", "client_secret": "s"}})
    sm = SyncManager(db, tmp_path, {"sync_workers": 1}, connectors=conns or [MercadoLivreTrends()], http=http, creds=creds)
    return sm, db


def test_first_collection_persists_and_counts_50_terms(tmp_path):
    http = MLHttp()
    sm, db = _sm(tmp_path, http)
    sm.run("manual", ["ml_trends"])
    f = sm.snapshot()["fontes"]["ml_trends"]
    n = db.query("SELECT COUNT(*) AS n FROM search_observations WHERE source = 'ml_trends'")[0]["n"]
    assert http.calls == 1 and n == 50
    assert f["estado"] == "concluido" and f["novos"] == 50                          # contabilizado (antes: 0)
    st = sm.store.source_status()["ml_trends"]
    assert st["state"] == "funcional" and st["last_success"] and st["records"] == 50
    # segunda execução no mesmo dia, automática: aí sim "atualizado" (houve coleta bem-sucedida)
    sm.run("abertura")
    assert sm.snapshot()["fontes"]["ml_trends"]["estado"] == "atualizado" and http.calls == 1


def test_previous_failure_is_not_shown_as_updated_and_manual_refresh_recovers(tmp_path):
    http = MLHttp(fail=SourceError("acesso negado (HTTP 403)", "http", status=403))
    sm, db = _sm(tmp_path, http)
    sm.run("abertura")
    assert sm.snapshot()["fontes"]["ml_trends"]["estado"] == "erro" and http.calls == 1
    sm.run("abertura")                                     # dentro do backoff: não repete a requisição...
    f = sm.snapshot()["fontes"]["ml_trends"]
    assert http.calls == 1
    assert f["estado"] == "pendente" and "403" in f["motivo"]                      # ...mas NÃO diz "Atualizado"
    http.fail = None
    sm.run("manual", ["ml_trends"], manual=True)           # botão Sincronizar / Atualizar fonte
    f = sm.snapshot()["fontes"]["ml_trends"]
    assert http.calls == 2 and f["estado"] == "concluido" and f["novos"] == 50
    assert db.query("SELECT COUNT(*) AS n FROM search_observations WHERE source = 'ml_trends'")[0]["n"] == 50


def test_done_job_without_any_success_is_due_again(tmp_path):
    """Base vazia não é "atualizada": um job marcado como concluído sem coleta gravada volta a rodar."""
    http = MLHttp()
    sm, db = _sm(tmp_path, http)
    today = sm.today_fn().isoformat()
    db.execute("INSERT INTO sync_jobs (job_key, source, params, state, attempts, updated_at) VALUES (?, 'ml_trends', '{}', "
               "'done', 0, ?)", (f"ml_trends:{today}", today))
    sm.run("abertura")
    assert http.calls == 1 and sm.snapshot()["fontes"]["ml_trends"]["novos"] == 50


def test_manual_refresh_repeats_cheap_source_without_duplicating(tmp_path):
    http = MLHttp()
    sm, db = _sm(tmp_path, http, [MercadoLivreTrends(), MercadoLivre()])
    sm.run("manual", ["ml_trends", "mercadolivre"])
    assert http.calls == 1                                  # as duas fontes usam a mesma resposta (cache de 1 h)
    http.cache.clear()
    TERMS[0]["keyword"] = "termo novo"
    try:
        sm.run("manual", ["ml_trends"], manual=True)
        f = sm.snapshot()["fontes"]["ml_trends"]
        assert http.calls == 2 and f["novos"] == 1 and f["estado"] == "concluido"          # só o termo novo é novo
        assert db.query("SELECT COUNT(*) AS n FROM search_observations WHERE source = 'ml_trends'")[0]["n"] == 51
    finally:
        TERMS[0]["keyword"] = "termo 1"


def test_persistence_after_reopen(tmp_path):
    http = MLHttp()
    sm, db = _sm(tmp_path, http)
    sm.run("manual", ["ml_trends"])
    db.close()
    db2 = Database(tmp_path / "s.sqlite")
    assert db2.query("SELECT COUNT(*) AS n FROM search_observations WHERE source = 'ml_trends'")[0]["n"] == 50
    db2.close()


def test_backup_before_migration_and_integrity(tmp_path):
    import sqlite3
    from gpi.db import MIGRATIONS
    p = tmp_path / "old.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE schema_version (v INTEGER NOT NULL)")
    for i, stmts in enumerate(MIGRATIONS[:5], start=1):
        for s in stmts:
            con.execute(s)
        con.execute("INSERT INTO schema_version VALUES (?)", (i,))
    con.commit()
    con.close()
    db = Database(p)
    assert db.pre_migration_backup and db.pre_migration_backup.exists() and "v5_para" in db.pre_migration_backup.name
    r = db.integrity()
    assert r["ok"] and r["integridade"] == "ok" and r["versao_esquema"] == len(MIGRATIONS) and "search_observations" in r["tabelas"]
    db.close()
    db2 = Database(p)                                   # já migrado: sem nova cópia
    assert db2.pre_migration_backup is None
    db2.close()


def test_source_audit_matrix(tmp_path):
    from gpi.market.audit import audit, markdown
    http = MLHttp()
    sm, db = _sm(tmp_path, http)
    sm.run("manual", ["ml_trends"])
    a = audit(db, sm.store, sm.creds, {}, sm.connectors)
    r = {x["fonte"]: x for x in a["fontes"]}["ml_trends"]
    assert r["E_persistencia"]["registros"] == 50 and r["C_coleta"]["ultima_coleta_ok"]
    assert r["A_configuracao"]["exige_autenticacao"] and r["A_configuracao"]["credenciais_configuradas"]
    assert r["fase"] in ("funcional", "dados_armazenados") and "| Mercado Livre" in markdown(a)
