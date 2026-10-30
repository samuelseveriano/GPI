"""
Gerenciador de sincronização autônoma.

  ABRIR → SINCRONIZAR → DESCOBRIR → ANALISAR → PREVER → CLASSIFICAR → EXIBIR

* Jobs idempotentes: cada coleta tem uma chave (ex.: "comexstat:china:2024").
  Períodos fechados não são coletados de novo; períodos recentes são revisitados
  semanalmente. Observações são gravadas por (série, data) — repetir um job não
  duplica dados (apenas registra revisões).
* Retomada: jobs que estavam "em execução" quando o programa fechou voltam para a
  fila na próxima abertura.
* Falhas: um conector com erro não interrompe os demais; o job é reagendado com
  espera crescente (1 h, 2 h, 4 h … até 24 h).
* Não bloqueia a interface: roda em uma thread; os dados anteriores continuam
  disponíveis e os resultados de análise só são substituídos ao final, após validação.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..connectors.base import Batch, FormatError
from ..connectors.http import HttpClient, HttpConfig, SourceError
from ..connectors.registry import all_connectors
from .content_store import ContentStore
from .store import MarketStore, now_iso

log = logging.getLogger("gpi.sync")


@dataclass
class SyncContext:
    http: HttpClient
    store: MarketStore
    cfg: dict
    today: date
    content: ContentStore | None = None
    creds: object = None


def validate_batch(b: Batch):
    if not b.obs:
        raise FormatError(f"série {b.series_key} sem observações")
    for d, v in b.obs:
        try:
            date.fromisoformat(d)
        except (TypeError, ValueError):
            raise FormatError(f"data inválida '{d}' em {b.series_key}")
        if v is None or not math.isfinite(float(v)):
            raise FormatError(f"valor não numérico em {b.series_key} ({d})")


class SyncManager:
    def __init__(self, db, data_dir, cfg: dict | None = None, connectors=None, http: HttpClient | None = None,
                 analyzer=None, today_fn=None, creds=None):
        self.db = db
        self.store = MarketStore(db)
        self.content = ContentStore(db)
        if creds is None:
            from ..integrations.credentials import CredentialStore
            creds = CredentialStore(data_dir)
        self.creds = creds
        self.cfg = cfg or {}
        hc = HttpConfig(proxy=self.cfg.get("proxy"), ca_bundle=self.cfg.get("ca_bundle"),
                        contact=self.cfg.get("contact"))
        self.http = http or HttpClient(data_dir / "cache", hc)
        self.connectors = connectors if connectors is not None else all_connectors()
        self.analyzer = analyzer
        self.today_fn = today_fn or date.today
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self.state = {"rodando": False, "fase": "ocioso", "atual": "", "feitos": 0, "total": 0,
                      "erros": [], "inicio": None, "fim": None}

    # ------------------------------------------------------------------ jobs
    def _job_row(self, key):
        r = self.db.query("SELECT * FROM sync_jobs WHERE job_key = ?", (key,))
        return r[0] if r else None

    def _is_due(self, job, now: datetime) -> bool:
        row = self._job_row(job.key)
        if row is None or row["state"] in ("pending", "running"):
            return True
        if row["state"] == "failed":
            return not row["next_try"] or datetime.fromisoformat(row["next_try"]) <= now
        if row["state"] == "done":
            return bool(row["refresh_after"]) and datetime.fromisoformat(row["refresh_after"]) <= now
        return True

    def _set_job(self, job, state, error=None, connector=""):
        now = datetime.now().astimezone()
        row = self._job_row(job.key)
        attempts = (row["attempts"] if row else 0) + (1 if state == "failed" else 0)
        if state == "done":
            attempts = 0
        next_try = (now + timedelta(hours=min(24, 2 ** max(0, attempts - 1)))).isoformat(timespec="seconds") \
            if state == "failed" else None
        refresh = (now + timedelta(days=job.refresh_days)).isoformat(timespec="seconds") \
            if state == "done" and job.refresh_days is not None else None
        self.db.execute(
            "INSERT INTO sync_jobs (job_key, source, params, state, attempts, last_error, next_try, refresh_after,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(job_key) DO UPDATE SET state=excluded.state,"
            " attempts=excluded.attempts, last_error=excluded.last_error, next_try=excluded.next_try,"
            " refresh_after=COALESCE(excluded.refresh_after, sync_jobs.refresh_after), updated_at=excluded.updated_at",
            (job.key, connector, json.dumps(job.params, ensure_ascii=False), state, attempts, error, next_try,
             refresh, now.isoformat(timespec="seconds")))

    def recover(self):
        """Jobs interrompidos (programa fechado no meio da coleta) voltam para a fila."""
        n = self.db.query("SELECT COUNT(*) AS n FROM sync_jobs WHERE state = 'running'")[0]["n"]
        self.db.execute("UPDATE sync_jobs SET state = 'pending' WHERE state = 'running'")
        self.db.execute("UPDATE sync_runs SET state = 'interrompida', finished_at = ? WHERE state = 'rodando'",
                        (now_iso(),))
        return n

    # ------------------------------------------------------------------ execução
    def context(self) -> SyncContext:
        return SyncContext(self.http, self.store, self.cfg, self.today_fn(), self.content, self.creds)

    def run(self, trigger="manual", only: list[str] | None = None) -> dict:
        with self._lock:
            if self.state["rodando"]:
                return {"erro": "sincronização já em andamento"}
            self.state.update(rodando=True, fase="preparando", atual="", feitos=0, total=0, erros=[],
                              inicio=now_iso(), fim=None)
        self.http.cancel_event.clear()
        rid = self.db.next_id("sync_runs")
        self.db.execute("INSERT INTO sync_runs (id, started_at, trigger, state) VALUES (?, ?, ?, 'rodando')",
                        (rid, now_iso(), trigger))
        summary = {"fontes": {}, "retomados": self.recover()}
        try:
            ctx = self.context()
            self.state["fase"] = "coletando"
            for c in self.connectors:
                if self.http.cancel_event.is_set():
                    break
                if only and c.id not in only:
                    continue
                summary["fontes"][c.id] = self._run_connector(c, ctx)
            if self.analyzer and not self.http.cancel_event.is_set() and not only:
                self.state.update(fase="analisando", atual="descoberta, previsões, clusters e ranking")
                summary["analise"] = self.analyzer(self.store, self.state)
            failed = [k for k, v in summary["fontes"].items() if v.get("estado") == "falhou"]
            if self.http.cancel_event.is_set():
                final = "cancelada"
            else:
                # 'parcial' não conta como semana concluída: o agendador tenta de novo a cada hora,
                # respeitando a espera crescente de cada job (1 h, 2 h, 4 h … 24 h)
                final = "parcial" if failed else "concluida"
        except Exception as e:  # noqa: BLE001 — a sincronização nunca derruba o aplicativo
            log.exception("falha na sincronização")
            summary["erro_fatal"] = str(e)
            self.state["erros"].append(f"erro interno: {e}")
            final = "falhou"
        self.db.execute("UPDATE sync_runs SET finished_at = ?, state = ?, summary = ? WHERE id = ?",
                        (now_iso(), final, json.dumps(summary, ensure_ascii=False, default=str), rid))
        self.state.update(rodando=False, fase=final, atual="", fim=now_iso())
        return summary

    def _run_connector(self, c, ctx) -> dict:
        res = {"jobs_ok": 0, "jobs_falhos": 0, "novas": 0, "revisadas": 0, "ultimo_erro": None}
        if not c.available(ctx):
            self.store.set_source_status(c.id, "restrita", c.restricted_reason or "")
            res["estado"] = "restrita"
            return res
        now = datetime.now().astimezone()
        seen = set()
        for _round in range(3):                       # planos dependentes (ex.: títulos → visualizações)
            try:
                jobs = [j for j in c.plan(ctx) if j.key not in seen and self._is_due(j, now)]
            except Exception as e:  # noqa: BLE001
                res["ultimo_erro"] = f"planejamento: {e}"
                break
            if not jobs:
                break
            jobs.sort(key=lambda j: j.priority)
            cap = (self.cfg or {}).get("max_jobs_per_source")   # usado só na validação rápida do CI
            if cap:
                seen.update(j.key for j in jobs[int(cap):])   # pulados nesta amostra; não voltam na próxima rodada
                jobs = jobs[:int(cap)]
            self.state["total"] += len(jobs)
            for j in jobs:
                if self.http.cancel_event.is_set():
                    break
                seen.add(j.key)
                self.state["atual"] = f"{c.name}: {j.key}"
                self._set_job(j, "running", connector=c.id)
                try:
                    batches, products = c.run(j, ctx)
                    for b in batches:
                        validate_batch(b)
                    for p in products:
                        self.store.upsert_product(p.key, **p.fields)
                    for b in batches:
                        sid = self.store.upsert_series(b.series_key, b.meta)
                        r = self.store.upsert_obs(sid, b.obs)
                        res["novas"] += r["novas"]
                        res["revisadas"] += r["revisadas"]
                    self._set_job(j, "done", connector=c.id)
                    res["jobs_ok"] += 1
                except SourceError as e:
                    if e.status == 404 and getattr(j, "not_found_ok", True) and ":langlinks:" in j.key:
                        # conceito sem artigo correspondente: não é falha da fonte
                        self._set_job(j, "done", str(e), c.id)
                        res.setdefault("nao_encontrados", []).append(str(e))
                        continue
                    if e.kind == "cancelada":
                        self._set_job(j, "pending", connector=c.id)
                        break
                    if e.kind == "limite" and "diário" in str(e):
                        # cota própria do GPI esgotada: não é falha da fonte; continua no dia seguinte
                        self._set_job(j, "failed", str(e), c.id)
                        res["cota"] = str(e)
                        break
                    self._set_job(j, "failed", str(e), c.id)
                    res["jobs_falhos"] += 1
                    res["ultimo_erro"] = str(e)
                    self.state["erros"].append(f"{c.name}: {e}")
                    if e.kind in ("tls", "restrita", "bloqueada") or (e.kind == "rede" and res["jobs_ok"] == 0
                                                          and res["jobs_falhos"] >= 2):
                        break                         # problema de acesso: não insiste nos demais jobs agora
                except Exception as e:  # noqa: BLE001
                    log.error("erro inesperado em %s: %s", j.key, traceback.format_exc())
                    self._set_job(j, "failed", f"erro interno: {e}", c.id)
                    res["jobs_falhos"] += 1
                    res["ultimo_erro"] = f"erro interno: {e}"
                finally:
                    self.state["feitos"] += 1
            else:
                continue
            break
        if res["jobs_ok"]:
            msg = f"{res['novas']} novas observações, {res['revisadas']} revisadas"
            if res.get("cota"):
                msg += f"; {res['cota']}"
            if res["jobs_falhos"]:
                msg += f"; {res['jobs_falhos']} coleta(s) com falha: {res['ultimo_erro']}"
            self.store.set_source_status(c.id, "funcional", msg, success=True, validated=True)
            res["estado"] = "funcional"
        elif res["jobs_falhos"] or res["ultimo_erro"]:
            self.store.set_source_status(c.id, "falhou", res["ultimo_erro"] or "falha")
            res["estado"] = "falhou"
        else:
            st = self.store.source_status().get(c.id)
            if st is None:
                self.store.set_source_status(c.id, "aguardando", "aguardando dados de outras fontes")
            elif st["validated"]:
                self.store.set_source_status(c.id, "funcional", "em dia (nada a coletar nesta execução)",
                                             success=True)
            res["estado"] = "em dia"
        return res

    # ------------------------------------------------------------------ thread e agenda
    def start(self, trigger="abertura", only: list[str] | None = None):
        if self.state["rodando"]:
            return False
        self._thread = threading.Thread(target=self.run, args=(trigger, only), daemon=True, name="gpi-sync")
        self._thread.start()
        return True

    def cancel(self):
        self.http.cancel_event.set()

    def last_success(self):
        r = self.db.query("SELECT finished_at FROM sync_runs WHERE state = 'concluida' ORDER BY id DESC LIMIT 1")
        return r[0]["finished_at"] if r else None

    def due(self) -> bool:
        """Devida se nunca concluiu, se mudou a semana ISO ou se passaram 7 dias."""
        last = self.last_success()
        if not last:
            return True
        lt = datetime.fromisoformat(last)
        now = datetime.now().astimezone()
        return (now - lt) >= timedelta(days=7) or lt.isocalendar()[:2] != now.isocalendar()[:2]

    def start_scheduler(self, check_every_s: float = 3600):
        def loop():
            if self.cfg.get("auto_sync", True) and self.due():
                self.run("abertura")
            while not self._stop.wait(check_every_s):
                if self.cfg.get("auto_sync", True) and self.due() and not self.state["rodando"]:
                    self.run("semanal")
        t = threading.Thread(target=loop, daemon=True, name="gpi-scheduler")
        t.start()
        return t

    def stop(self):
        self._stop.set()
        self.cancel()
