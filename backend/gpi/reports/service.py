"""
Centro de Relatórios: geração, histórico, reprodução, exclusão e relatório semanal automático.

* Arquivos ficam em <pasta de dados>/relatorios/AAAA/ e NUNCA são sobrescritos: cada geração tem
  nome único (tipo, data/hora e identificador da execução).
* Junto de cada arquivo fica um snapshot (JSON compactado) dos dados usados. "Gerar novamente"
  pode reproduzir exatamente o documento a partir do snapshot ou gerar com os dados atuais.
* Excluir exige confirmação explícita; o registro permanece no histórico (status 'excluido') para
  auditoria, mas os arquivos são apagados.
* Relatório semanal automático: desligado por padrão. Quando ligado, é gerado depois de uma
  sincronização concluída; se o GPI estava fechado, a tarefa pendente roda na próxima abertura.
  Nada é enviado para fora do computador.
* Tokens e credenciais nunca entram nos dados do relatório (somente análises e observações).
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import re
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from . import data as D

log = logging.getLogger("gpi.reports")
_lock = threading.Lock()
SECRET_KEYS = re.compile(r"(token|secret|senha|password|api_key|client_secret|refresh)", re.I)


def _scrub(o):
    """Defesa extra: remove qualquer chave com cara de credencial antes de gravar snapshot/relatório."""
    if isinstance(o, dict):
        return {k: ("[removido]" if isinstance(k, str) and SECRET_KEYS.search(k) else _scrub(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [_scrub(x) for x in o]
    if isinstance(o, tuple):
        return [_scrub(x) for x in o]
    return o


def write_csv(ds: dict, path: Path):
    t = D.main_table(ds)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    if ds.get("demo"):
        w.writerow(["DEMONSTRAÇÃO — dados sintéticos ou de teste", ds.get("demo_motivo")])
    w.writerow([ds["titulo"]])
    w.writerow(["Filtros", ds["meta"]["filtros_texto"]])
    w.writerow(["Gerado em", ds["meta"]["gerado_em"], "Execução", ds["meta"]["run_id"], "Natureza", t["natureza"]])
    w.writerow([])
    w.writerow([c["rotulo"] for c in t["colunas"]])
    for r in t["linhas"]:
        line = []
        for c in t["colunas"]:
            v = r.get(c["id"])
            if v is None:
                v = ""
            elif isinstance(v, float):
                v = f"{v:.6g}".replace(".", ",")
            else:
                v = str(v)
                if v.startswith(("=", "+", "-", "@", "\t", "\r")):
                    v = "'" + v                       # OWASP: neutraliza fórmulas em CSV
            line.append(v)
        w.writerow(line)
    path.write_text("﻿" + buf.getvalue(), encoding="utf-8")


class ReportService:
    def __init__(self, db, data_dir: Path, cfg: dict):
        self.db, self.cfg = db, cfg
        self.dir = Path(data_dir) / "relatorios"
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- tipos e filtros
    def types(self) -> list[dict]:
        last = {r["tipo"]: r for r in self.db.query(
            "SELECT tipo, MAX(created_at) AS quando FROM reports WHERE status = 'gerado' GROUP BY tipo")}
        return [{"id": k, "nome": v["nome"], "descricao": v["descricao"], "formatos": D.FORMATS, "grupo": v["grupo"],
                 "exige_produto": bool(v.get("exige_produto")), "exige_analise": bool(v.get("exige_analise")), "ultima_geracao": (last.get(k) or {}).get("quando")}
                for k, v in D.TYPES.items()]

    def filter_options(self) -> dict:
        from ..market.store import MarketStore
        from ..products.trends import SOURCE_NAMES
        cons = MarketStore(self.db).load_result("consumer") or {}
        series = cons.get("series", [])
        prods = sorted({(s["product_id"], s.get("nome") or s["product_id"]) for s in series}, key=lambda x: x[1])
        if not prods:
            prods = [(r["product_id"], r["canonical"]) for r in self.db.query(
                "SELECT product_id, canonical FROM catalog_products WHERE level = 'produto' ORDER BY canonical LIMIT 500")]
        return {"paises": [{"id": k, "nome": v} for k, v in D.COUNTRY_LABEL.items()],
                "categorias": sorted({s.get("categoria") for s in series if s.get("categoria")}),
                "produtos": [{"id": a, "nome": b} for a, b in prods],
                "fontes": [{"id": s, "nome": SOURCE_NAMES.get(s, s)} for s in sorted({s["source"] for s in series})],
                "periodos": [{"id": 3, "nome": "últimos 3 meses"}, {"id": 6, "nome": "últimos 6 meses"},
                             {"id": 12, "nome": "últimos 12 meses"}, {"id": 24, "nome": "últimos 24 meses"}]}

    # ---------------------------------------------------------------- geração
    def _paths(self, tipo: str, fmt: str, run_id: str) -> tuple[Path, Path]:
        now = datetime.now()
        d = self.dir / f"{now:%Y}"
        d.mkdir(parents=True, exist_ok=True)
        base = f"GPI_{tipo}_{now:%Y%m%d-%H%M%S}_{run_id[:8]}"
        p, i = d / f"{base}.{fmt}", 2
        while p.exists():                                # nunca sobrescreve
            p, i = d / f"{base}_{i}.{fmt}", i + 1
        return p, p.with_name(p.stem + ".snapshot.json.gz")

    def render(self, ds: dict, fmt: str, path: Path) -> dict:
        extra = {}
        if fmt == "xlsx":
            from .xlsx import write
            write(ds, path)
        elif fmt == "pdf":
            from .pdf import write
            extra = write(ds, path) or {}
        elif fmt == "csv":
            write_csv(ds, path)
        else:
            raise ValueError("formato inválido (use xlsx, pdf ou csv)")
        return extra

    def generate(self, tipo: str, fmt: str, filtros: dict | None = None, origem: str = "manual",
                 snapshot: dict | None = None, origem_id: int | None = None, today: date | None = None) -> dict:
        if fmt not in D.FORMATS:
            raise ValueError("formato inválido (use xlsx, pdf ou csv)")
        run_id = uuid.uuid4().hex
        with _lock:
            if snapshot is not None:
                ds = snapshot
                ds["meta"] = {**ds["meta"], "reproduzido_de": ds["meta"]["run_id"], "run_id": run_id,
                              "gerado_em": datetime.now().isoformat(timespec="seconds")}
            else:
                ds = D.build(self.db, tipo, filtros, self.cfg, today, run_id)
            ds = _scrub(ds)
            path, snap = self._paths(tipo, fmt, run_id)
            f = D.Filters(ds["meta"]["filtros"])
            rec = {"run_id": run_id, "tipo": tipo, "formato": fmt, "titulo": ds["titulo"], "filtros": json.dumps(ds["meta"]["filtros"], ensure_ascii=False),
                   "periodo": f"últimos {f.periodo_meses} meses" if f.periodo_meses else "todo o histórico", "pais": f.pais or "todos",
                   "created_at": datetime.now().isoformat(timespec="seconds"), "versao_software": ds["meta"]["versao_software"],
                   "versao_dados": ds["meta"]["versao_dados"], "modelos": json.dumps(ds["meta"]["modelos"], ensure_ascii=False),
                   "fontes": json.dumps(ds["meta"]["fontes"], ensure_ascii=False),
                   "parametros": json.dumps({**ds["meta"]["parametros"], "criterios_ranking": ds["meta"]["criterios_ranking"]}, ensure_ascii=False),
                   "demo": int(bool(ds.get("demo"))), "origem": origem, "origem_id": origem_id,
                   "visto": 0 if origem == "automatico" else 1}
            try:
                extra = self.render(ds, fmt, path)
                with gzip.open(snap, "wt", encoding="utf-8") as fh:
                    json.dump(ds, fh, ensure_ascii=False, default=str)
                rec.update(path=str(path), snapshot_path=str(snap), size=path.stat().st_size, status="gerado", erro=None)
                if extra:
                    rec["parametros"] = json.dumps({**json.loads(rec["parametros"]), **extra}, ensure_ascii=False)
            except Exception as e:  # noqa: BLE001 — registra a falha no histórico
                log.exception("falha ao gerar relatório %s/%s", tipo, fmt)
                for p in (path, snap):
                    if p.exists():
                        p.unlink()
                rec.update(path=None, snapshot_path=None, size=None, status="erro", erro=str(e)[:500])
            cols = ", ".join(rec)
            cur = self.db.execute(f"INSERT INTO reports ({cols}) VALUES ({', '.join('?' * len(rec))})", tuple(rec.values()))
            rec["id"] = cur.lastrowid
        return self.get(rec["id"])

    # ---------------------------------------------------------------- histórico
    def _row(self, r: dict) -> dict:
        out = dict(r)
        for k in ("filtros", "modelos", "fontes", "parametros"):
            try:
                out[k] = json.loads(r[k]) if r.get(k) else None
            except ValueError:
                pass
        out["arquivo"] = Path(r["path"]).name if r.get("path") else None
        out["tipo_nome"] = D.TYPES.get(r["tipo"], {}).get("nome", r["tipo"])
        out["disponivel"] = bool(r.get("path")) and Path(r["path"]).exists()
        out.pop("path", None)
        out.pop("snapshot_path", None)
        return out

    def get(self, rid: int) -> dict | None:
        r = self.db.query("SELECT * FROM reports WHERE id = ?", (rid,))
        return self._row(r[0]) if r else None

    def history(self, tipo: str | None = None, limit: int = 300) -> list[dict]:
        q, p = "SELECT * FROM reports", []
        if tipo:
            q += " WHERE tipo = ?"
            p.append(tipo)
        q += " ORDER BY id DESC LIMIT ?"
        p.append(limit)
        return [self._row(r) for r in self.db.query(q, p)]

    def file(self, rid: int) -> Path | None:
        r = self.db.query("SELECT path, status FROM reports WHERE id = ?", (rid,))
        if not r or r[0]["status"] != "gerado" or not r[0]["path"]:
            return None
        p = Path(r[0]["path"]).resolve()
        if self.dir.resolve() not in p.parents or not p.exists():     # só arquivos da pasta de relatórios
            return None
        return p

    def regenerate(self, rid: int, modo: str = "snapshot") -> dict:
        r = self.db.query("SELECT * FROM reports WHERE id = ?", (rid,))
        if not r:
            raise KeyError("relatório não encontrado")
        r = r[0]
        if modo == "snapshot":
            sp = r.get("snapshot_path")
            if not sp or not Path(sp).exists():
                raise ValueError("snapshot indisponível para este relatório: use 'gerar com dados atuais'")
            with gzip.open(sp, "rt", encoding="utf-8") as fh:
                snap = json.load(fh)
            snap["secoes"] = [tuple(x) for x in snap["secoes"]]
            return self.generate(r["tipo"], r["formato"], None, "reproducao", snapshot=snap, origem_id=rid)
        return self.generate(r["tipo"], r["formato"], json.loads(r["filtros"] or "{}"), "manual", origem_id=rid)

    def delete(self, rid: int, confirmar: bool) -> dict:
        if not confirmar:
            raise PermissionError("confirmação necessária para excluir o relatório")
        r = self.db.query("SELECT path, snapshot_path FROM reports WHERE id = ?", (rid,))
        if not r:
            raise KeyError("relatório não encontrado")
        for k in ("path", "snapshot_path"):
            if r[0][k]:
                p = Path(r[0][k]).resolve()
                if self.dir.resolve() in p.parents and p.exists():
                    p.unlink()
        self.db.execute("UPDATE reports SET status = 'excluido', path = NULL, snapshot_path = NULL WHERE id = ?", (rid,))
        return self.get(rid)

    # ---------------------------------------------------------------- notificações e relatório semanal
    def notifications(self) -> list[dict]:
        return [self._row(r) for r in self.db.query(
            "SELECT * FROM reports WHERE origem = 'automatico' AND visto = 0 ORDER BY id DESC LIMIT 10")]

    def mark_seen(self):
        self.db.execute("UPDATE reports SET visto = 1 WHERE visto = 0")

    def weekly_pending(self) -> bool:
        if not self.cfg.get("auto_report_weekly", False):
            return False
        last_sync = self.db.query("SELECT finished_at FROM sync_runs WHERE state = 'concluida' ORDER BY id DESC LIMIT 1")
        if not last_sync or not last_sync[0]["finished_at"]:
            return False
        last = self.db.query("SELECT created_at FROM reports WHERE origem = 'automatico' AND status = 'gerado' ORDER BY id DESC LIMIT 1")
        if not last:
            return True
        lt = datetime.fromisoformat(last[0]["created_at"])
        return last_sync[0]["finished_at"] > last[0]["created_at"] and datetime.now() - lt >= timedelta(days=6, hours=12)

    def run_weekly(self) -> dict | None:
        """Gera o relatório executivo semanal (PDF e Excel) quando a opção está ligada e há sincronização nova."""
        if not self.weekly_pending():
            return None
        out = [self.generate("executivo", fmt, {}, "automatico") for fmt in ("pdf", "xlsx")]
        log.info("relatório semanal automático gerado: %s", [o.get("arquivo") for o in out])
        return {"gerados": [o["id"] for o in out]}
