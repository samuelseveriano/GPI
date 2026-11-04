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
* Concorrência controlada (Fase 4): os conectores são agrupados em etapas (`stage`). Na mesma
  etapa, fontes independentes (hosts diferentes) rodam em paralelo, no máximo `sync_workers`
  ao mesmo tempo; dentro de cada fonte os jobs são sequenciais, respeitando o intervalo mínimo e
  as cotas do provedor. Entre etapas, uma análise rápida atualiza o painel progressivamente.
* Métricas por fonte (tempo, registros/s, jobs) ficam em `source_metrics`.
* v0.6.1 — painel por fonte: cada conector tem estado próprio (aguardando, executando, concluído,
  atualizado, em cache, ignorado, requer autorização, erro, limite de API, cancelado), horários,
  jobs, registros novos/atualizados, tentativas, espera por limite e próxima execução. O progresso
  é calculado sobre tarefas conhecidas (fontes + etapas da análise), nunca por tempo. Fontes sem
  autorização são resolvidas no início e não ficam aguardando. Ordem de início por prioridade
  comercial (consumo → tendências → marketplaces → redes sociais → comércio exterior), com
  paralelismo seguro entre fontes independentes. Cada execução grava um log estruturado (JSONL)
  sem segredos em logs/sync/<execução>.jsonl.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..connectors.base import Batch, FormatError
from ..connectors.http import HttpClient, HttpConfig, SourceError
from ..connectors.registry import all_connectors
from .content_store import ContentStore
from .store import MarketStore, now_iso

log = logging.getLogger("gpi.sync")

PRIORITY = {"google_ads_kp": 1, "ml_trends": 1, "msads_kp": 1,
            "google_trends_rss": 2, "google_trends_bq": 2, "google_trends": 2, "wikimedia": 2, "gdelt": 2, "rss": 2,
            "google_news": 2,
            "ebay": 3, "mercadolivre": 3, "amazon_br": 3, "amazon_us": 3, "shopee": 3, "aliexpress": 3,
            "taobao": 3, "comparadores": 3, "trustpilot": 3,
            "youtube": 4, "tiktok": 4, "instagram": 4, "facebook": 4, "meta_ads": 4, "reddit": 4,
            "comexstat": 5, "comtrade": 5, "bcb_ptax": 5, "ibge_pmc": 5}
PRIORITY_NAMES = {1: "Dados de consumo", 2: "Tendências", 3: "Marketplaces", 4: "Redes sociais", 5: "Comércio exterior"}
STATES = {  # estado → (rótulo, símbolo); o símbolo garante que o estado não dependa só da cor
    "aguardando": ("Aguardando", "…"), "executando": ("Executando", "⟳"), "concluido": ("Concluído", "✓"),
    "atualizado": ("Atualizado — nada novo a coletar", "="), "em_cache": ("Em cache", "◷"), "ignorado": ("Ignorado", "–"),
    "requer_autorizacao": ("Requer autorização", "🔒"), "erro": ("Erro", "✕"), "limite": ("Limite de API", "⏸"),
    "cancelado": ("Cancelado", "⊘")}
DONE = {"concluido", "atualizado", "em_cache", "ignorado", "requer_autorizacao", "erro", "limite", "cancelado"}


@dataclass
class SyncContext:
    http: HttpClient
    store: MarketStore
    cfg: dict
    today: date
    content: ContentStore | None = None
    creds: object = None
    force: bool = False                 # "Atualizar agora": planos manuais limitados (respeitam cotas)


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
                      "erros": [], "inicio": None, "fim": None, "ativos": [], "fontes": {}, "versao": 0,
                      "etapas_total": 0, "etapas_feitas": 0}
        self.data_dir = data_dir
        self.run_id = None
        self._logf = None
        if hasattr(self.http, "on_event"):
            self.http.on_event = self._on_http_event
        self.quick_analyzer = None        # análise leve entre etapas (painel progressivo)

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

    # ------------------------------------------------------------------ painel por fonte
    def _src(self, cid) -> dict:
        return self.state["fontes"].setdefault(cid, {})

    def _upd(self, cid, **kw):
        with self._lock:
            self._src(cid).update(kw)
            self.state["versao"] += 1

    def _on_http_event(self, ev: dict):
        src = ev.get("fonte")
        if self._logf:
            try:
                self._log({"tipo": "requisicao", **{k: v for k, v in ev.items() if k != "run"}})
            except Exception:  # noqa: BLE001
                pass
        if not src or src not in self.state["fontes"]:
            return
        with self._lock:
            f = self._src(src)
            if ev.get("status") == "cache":
                f["cache"] = f.get("cache", 0) + 1
            elif ev.get("espera"):
                f["tentativas"] = f.get("tentativas", 0) + 1
                f["espera_s"] = round(f.get("espera_s", 0) + ev["espera"], 1)
                if "429" in str(ev.get("motivo", "")) or "limit" in str(ev.get("motivo", "")).lower():
                    f["estado"] = "limite"
                    f["motivo"] = "aguardando limite de requisições da API"
            else:
                f["requisicoes"] = f.get("requisicoes", 0) + 1
                if ev.get("erro"):
                    f["erros_http"] = f.get("erros_http", 0) + 1
                elif f.get("estado") == "limite":
                    f["estado"], f["motivo"] = "executando", None
            self.state["versao"] += 1

    def _log(self, obj: dict):
        if not self._logf:
            return
        from ..connectors.http import redact
        line = redact(json.dumps({"ts": now_iso(), **obj}, ensure_ascii=False, default=str))
        with self._lock:
            self._logf.write(line + "\n")
            self._logf.flush()

    def _next_due(self, cid) -> str | None:
        r = self.db.query("SELECT MIN(COALESCE(next_try, refresh_after)) AS n FROM sync_jobs WHERE source = ? AND "
                          "(next_try IS NOT NULL OR refresh_after IS NOT NULL)", (cid,))
        return r[0]["n"] if r else None

    def snapshot(self) -> dict:
        """Estado atual (para a barra superior, o painel e os eventos em tempo real)."""
        with self._lock:
            fontes = {k: dict(v) for k, v in self.state["fontes"].items()}
            st = {k: v for k, v in self.state.items() if k != "fontes"}
        tasks = len(fontes) + (1 if st.get("etapas_total") else 0)
        done_frac = 0.0
        cnt = {"concluidas": 0, "executando": 0, "aguardando": 0, "falhas": 0, "sem_autorizacao": 0}
        for f in fontes.values():
            e = f.get("estado")
            if e in DONE:
                done_frac += 1
                if e in ("erro", "limite"):
                    cnt["falhas"] += 1
                elif e == "requer_autorizacao":
                    cnt["sem_autorizacao"] += 1
                else:
                    cnt["concluidas"] += 1
            elif e in ("executando",):
                cnt["executando"] += 1
                if f.get("jobs_total"):
                    done_frac += min(0.99, f.get("jobs_feitos", 0) / f["jobs_total"])
            else:
                cnt["aguardando"] += 1
        if st.get("etapas_total"):
            done_frac += min(1.0, st.get("etapas_feitas", 0) / st["etapas_total"])
        rodando = st.get("rodando")
        indeterminado = rodando and tasks == 0
        pct = None if indeterminado else (round(100 * done_frac / tasks) if tasks else (100 if not rodando else 0))
        if rodando and pct == 100:
            pct = 99 if st.get("fase") != "concluida" else 100
        fase = st.get("fase")
        if not rodando and fase in ("parcial",) or (not rodando and cnt["falhas"] and fase == "concluida"):
            titulo = "Sincronização concluída com restrições"
        elif not rodando and fase == "concluida":
            titulo = "Sincronização concluída"
        elif not rodando and fase == "cancelada":
            titulo = "Sincronização cancelada"
        elif not rodando and fase == "falhou":
            titulo = "Sincronização interrompida por erro interno"
        elif rodando:
            titulo = {"preparando": "Preparando sincronização", "coletando": "Coletando dados",
                      "analisando": "Analisando dados coletados"}.get(fase, "Sincronizando")
        else:
            titulo = "Sem sincronização em andamento"
        resumo = (f"{cnt['concluidas']} de {len(fontes)} fontes concluídas — {cnt['executando']} em execução — "
                  f"{cnt['aguardando']} aguardando" + (f" — {cnt['falhas']} com falha" if cnt["falhas"] else "")
                  + (f" — {cnt['sem_autorizacao']} sem autorização" if cnt["sem_autorizacao"] else "")) if fontes else ""
        for k, f in fontes.items():
            lab = STATES.get(f.get("estado"), (f.get("estado"), ""))
            f["rotulo"], f["simbolo"] = lab
        return {**st, "execucao": self.run_id, "percentual": pct, "indeterminado": bool(indeterminado), "titulo": titulo,
                "resumo": resumo, "contagem": cnt, "fontes": fontes, "estados": STATES,
                "prioridades": PRIORITY_NAMES}

    def run(self, trigger="manual", only: list[str] | None = None, force: bool = False) -> dict:
        with self._lock:
            if self.state["rodando"]:
                return {"erro": "sincronização já em andamento"}
            self.state.update(rodando=True, fase="preparando", atual="", feitos=0, total=0, erros=[],
                              inicio=now_iso(), fim=None, fontes={}, etapas_total=0, etapas_feitas=0)
            self.state["versao"] += 1
        self.http.cancel_event.clear()
        rid = self.db.next_id("sync_runs")
        self.run_id = rid
        self.db.execute("INSERT INTO sync_runs (id, started_at, trigger, state) VALUES (?, ?, ?, 'rodando')",
                        (rid, now_iso(), trigger))
        try:
            d = os.path.join(str(self.data_dir), "logs", "sync")
            os.makedirs(d, exist_ok=True)
            self._logf = open(os.path.join(d, f"{rid:05d}.jsonl"), "a", encoding="utf-8")
        except Exception:  # noqa: BLE001 — sem log estruturado não impede a coleta
            self._logf = None
        self._log({"tipo": "inicio", "execucao": rid, "gatilho": trigger, "fontes": only or "todas", "forcado": force})
        summary = {"fontes": {}, "retomados": self.recover()}
        try:
            ctx = self.context()
            ctx.force = force
            if hasattr(self.http, "reset_breakers"):
                self.http.reset_breakers()
            if hasattr(self.http, "source_stats"):
                self.http.source_stats.clear()
            t_all = time.monotonic()
            todo = [c for c in self.connectors if not only or c.id in only]
            ok_todo = []
            for c in sorted(todo, key=lambda c: (PRIORITY.get(c.id, 3), c.order)):
                base = {"nome": c.name, "prioridade": PRIORITY.get(c.id, 3),
                        "grupo": PRIORITY_NAMES[PRIORITY.get(c.id, 3)], "etapa": getattr(c, "stage", 1),
                        "ultima_ok": (self.store.source_status().get(c.id) or {}).get("last_success")}
                try:
                    avail = c.available(ctx)
                except Exception:  # noqa: BLE001
                    avail = False
                if not avail:                       # resolvida já no início: não fica "aguardando"
                    self.store.set_source_status(c.id, "restrita", c.restricted_reason or "")
                    self._upd(c.id, **base, estado="requer_autorizacao", motivo=c.restricted_reason or "não configurada")
                    summary["fontes"][c.id] = {"estado": "restrita", "jobs_ok": 0, "jobs_falhos": 0, "novas": 0, "revisadas": 0,
                                               "ultimo_erro": None, "segundos": 0.0}
                    continue
                self._upd(c.id, **base, estado="aguardando", motivo=None)
                ok_todo.append(c)
            if self.analyzer and not only:
                self.state["etapas_total"] = int(getattr(self.analyzer, "steps", 12))
            self.state["fase"] = "coletando"
            todo = ok_todo
            stages = sorted({getattr(c, "stage", 1) for c in todo})
            workers = max(1, int(self.cfg.get("sync_workers", 4)))
            for st in stages:
                if self.http.cancel_event.is_set():
                    break
                group = sorted([c for c in todo if getattr(c, "stage", 1) == st], key=lambda c: (PRIORITY.get(c.id, 3), c.order))
                if workers == 1 or len(group) == 1:
                    for c in group:
                        if self.http.cancel_event.is_set():
                            break
                        summary["fontes"][c.id] = self._timed(c, ctx, rid)
                else:
                    with ThreadPoolExecutor(max_workers=min(workers, len(group)), thread_name_prefix="gpi-src") as ex:
                        futs = {c.id: ex.submit(self._timed, c, ctx, rid) for c in group}
                        for cid, f in futs.items():
                            summary["fontes"][cid] = f.result()
                if self.quick_analyzer and st != stages[-1] and not only and not self.http.cancel_event.is_set():
                    try:
                        self.state["atual"] = "atualizando painel com os dados já coletados"
                        self.quick_analyzer(self.store, self.state)
                    except Exception:  # noqa: BLE001
                        log.exception("análise rápida falhou (a sincronização continua)")
            summary["desempenho"] = {"coleta_segundos": round(time.monotonic() - t_all, 2),
                                     "trabalhadores": workers,
                                     "hosts": getattr(self.http, "host_stats", {})}
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
        with self._lock:
            for cid, f in self.state["fontes"].items():
                if f.get("estado") in ("aguardando", "executando"):
                    f["estado"] = "cancelado" if self.http.cancel_event.is_set() else "ignorado"
        if final == "concluida" and any(f.get("estado") in ("erro", "limite") for f in self.state["fontes"].values()):
            final = "parcial"
        summary["painel"] = self.snapshot()["fontes"]
        self.db.execute("UPDATE sync_runs SET finished_at = ?, state = ?, summary = ? WHERE id = ?",
                        (now_iso(), final, json.dumps(summary, ensure_ascii=False, default=str), rid))
        self.state.update(rodando=False, fase=final, atual="", fim=now_iso())
        self.state["etapas_feitas"] = self.state.get("etapas_total", 0)
        self.state["versao"] += 1
        self._log({"tipo": "fim", "execucao": rid, "estado": final,
                   "fontes": {k: v.get("estado") for k, v in self.state["fontes"].items()}})
        if self._logf:
            self._logf.close()
            self._logf = None
        if hasattr(self.http, "transport"):
            self.http.transport.close()
        return summary

    def _timed(self, c, ctx, rid) -> dict:
        t0, started = time.monotonic(), now_iso()
        with self._lock:
            self.state["ativos"] = self.state.get("ativos", []) + [c.name]
        if hasattr(self.http, "ctx_local"):
            self.http.ctx_local.cur = {"fonte": c.id, "execucao": rid}
        q0 = self._quota(c.id)
        self._upd(c.id, estado="executando", inicio=started, jobs_total=0, jobs_feitos=0, novos=0, atualizados=0)
        self._log({"tipo": "fonte_inicio", "fonte": c.id})
        try:
            res = self._run_connector(c, ctx)
        except Exception as e:  # noqa: BLE001 — uma fonte nunca derruba as demais
            log.exception("conector %s falhou", c.id)
            res = {"estado": "falhou", "ultimo_erro": f"erro interno: {e}", "jobs_ok": 0, "jobs_falhos": 1,
                   "novas": 0, "revisadas": 0}
            self.store.set_source_status(c.id, "falhou", res["ultimo_erro"])
        finally:
            with self._lock:
                self.state["ativos"] = [n for n in self.state.get("ativos", []) if n != c.name]
        secs = time.monotonic() - t0
        recs = int(res.get("novas", 0)) + int(res.get("revisadas", 0)) + int(res.get("itens", 0))
        res["segundos"] = round(secs, 2)
        if hasattr(self.http, "ctx_local"):
            self.http.ctx_local.cur = None
        ss = (getattr(self.http, "source_stats", {}) or {}).get(c.id, {})
        e = res.get("estado")
        cancelled = self.http.cancel_event.is_set() and e != "funcional"
        if cancelled:
            estado, motivo = "cancelado", "sincronização cancelada pelo usuário"
        elif e == "funcional":
            only_cache = ss.get("requisicoes", 0) == 0 and ss.get("cache", 0) > 0
            estado = "em_cache" if only_cache else "concluido"
            motivo = "respostas reaproveitadas do cache local (dentro da validade)" if only_cache else None
        elif e == "em dia" and (self.store.source_status().get(c.id) or {}).get("state") == "aguardando":
            estado, motivo = "ignorado", "aguardando dados de outra fonte (dependência) — nada a planejar nesta execução"
        elif e == "em dia":
            estado, motivo = "atualizado", "dados considerados atualizados pela política de sincronização desta fonte"
        elif e == "restrita":
            estado, motivo = "requer_autorizacao", None
        elif e == "falhou":
            err = str(res.get("ultimo_erro") or "")
            estado = "limite" if ("429" in err or "limite" in err.lower() or res.get("cota") or res.get("limite")) else "erro"
            motivo = err[:300]
        else:
            estado, motivo = "concluido", None
        q1 = self._quota(c.id)
        self._upd(c.id, estado=estado, motivo=motivo, fim=now_iso(), segundos=round(secs, 2),
                  jobs_ok=res.get("jobs_ok", 0), jobs_falhos=res.get("jobs_falhos", 0), novos=res.get("novas", 0),
                  atualizados=res.get("revisadas", 0), cota_unidades=(q1 - q0) if q1 is not None and q0 is not None else None,
                  tentativas=ss.get("retentativas", 0) or self._src(c.id).get("tentativas", 0),
                  espera_s=round(ss.get("espera_s", 0), 1) or self._src(c.id).get("espera_s", 0),
                  proxima=self._next_due(c.id), ultima_ok=(self.store.source_status().get(c.id) or {}).get("last_success"),
                  registros_armazenados=(self.store.source_status().get(c.id) or {}).get("records"))
        self._log({"tipo": "fonte_fim", "fonte": c.id, "estado": estado, "segundos": round(secs, 2),
                   "jobs_ok": res.get("jobs_ok", 0), "jobs_falhos": res.get("jobs_falhos", 0), "novos": res.get("novas", 0),
                   "atualizados": res.get("revisadas", 0), "erro": motivo if estado in ("erro", "limite") else None})
        try:
            self.db.execute("INSERT OR REPLACE INTO source_metrics (run_id, source, started_at, seconds, jobs_ok,"
                            " jobs_failed, records, records_per_s, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (rid, c.id, started, secs, res.get("jobs_ok", 0), res.get("jobs_falhos", 0), recs,
                             recs / secs if secs > 0 else None, res.get("estado")))
        except Exception:  # noqa: BLE001 — banco anterior à v4 (testes antigos)
            pass
        return res

    def _quota(self, cid):
        try:
            r = self.db.query("SELECT COALESCE(SUM(units), 0) AS u FROM api_quota WHERE provider = ? AND day = ?",
                              (cid, date.today().isoformat()))
            return int(r[0]["u"])
        except Exception:  # noqa: BLE001
            return None

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
            if c.id in self.state["fontes"]:
                self._upd(c.id, jobs_total=self._src(c.id).get("jobs_total", 0) + len(jobs))
            for j in jobs:
                if self.http.cancel_event.is_set():
                    break
                seen.add(j.key)
                self.state["atual"] = f"{c.name}: {j.key}"
                if hasattr(self.http, "ctx_local") and getattr(self.http.ctx_local, "cur", None):
                    self.http.ctx_local.cur["job"] = j.key
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
                    if e.kind == "limite" and "adiada" in str(e):
                        res["limite"] = True
                        break                         # limite do servidor: não insiste; os jobs voltam na próxima execução
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
                    if c.id in self.state["fontes"]:
                        self._upd(c.id, jobs_feitos=self._src(c.id).get("jobs_feitos", 0) + 1,
                                  novos=res["novas"], atualizados=res["revisadas"])
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
    def start(self, trigger="abertura", only: list[str] | None = None, force: bool = False):
        if self.state["rodando"]:
            return False
        self._thread = threading.Thread(target=self.run, args=(trigger, only, force), daemon=True, name="gpi-sync")
        self._thread.start()
        return True

    def failed_sources(self) -> list[str]:
        return [k for k, v in self.store.source_status().items() if v.get("state") == "falhou"]

    def retry_failed(self) -> dict:
        """Tenta de novo só as fontes com falha, liberando a espera dos jobs que falharam (sem afetar as demais)."""
        ids = self.failed_sources()
        if not ids:
            return {"iniciada": False, "fontes": [], "mensagem": "nenhuma fonte com falha"}
        for cid in ids:
            self.db.execute("UPDATE sync_jobs SET next_try = NULL WHERE source = ? AND state = 'failed'", (cid,))
        return {"iniciada": self.start("retentativa", ids), "fontes": ids}

    def history(self, limit: int = 30) -> list[dict]:
        out = []
        for r in self.db.query("SELECT id, started_at, finished_at, trigger, state, summary FROM sync_runs ORDER BY id DESC LIMIT ?",
                               (limit,)):
            try:
                sm = json.loads(r["summary"] or "{}")
            except ValueError:
                sm = {}
            painel = sm.get("painel") or {}
            fontes = {k: {"estado": v.get("estado"), "segundos": v.get("segundos"), "novos": v.get("novos"),
                          "motivo": v.get("motivo")} for k, v in painel.items()} or \
                     {k: {"estado": v.get("estado"), "segundos": v.get("segundos"), "novos": v.get("novas")} for k, v in (sm.get("fontes") or {}).items()}
            out.append({"id": r["id"], "inicio": r["started_at"], "fim": r["finished_at"], "gatilho": r["trigger"],
                        "estado": r["state"], "rotulo": {"concluida": "Concluída", "parcial": "Concluída com restrições",
                                                         "cancelada": "Cancelada", "falhou": "Falhou", "rodando": "Em andamento",
                                                         "interrompida": "Interrompida"}.get(r["state"], r["state"]),
                        "segundos_coleta": (sm.get("desempenho") or {}).get("coleta_segundos"), "fontes": fontes})
        return out

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
