"""
Validação REAL dos conectores: executa uma sincronização contra as APIs públicas (sem credenciais)
e grava um relatório JSON com o resultado de cada fonte. Nenhum dado simulado é usado aqui.
Roda no CI (runner com internet) e pode ser executado manualmente:
    python scripts/validate_connectors.py relatorio.json [--comparar]

--comparar: mede a coleta em condições equivalentes — mesma amostra por fonte, cache vazio em
cada execução, mesmo computador — primeiro sequencial (1 fonte por vez, como na Fase 3) e depois
com fontes em paralelo (Fase 4). O relatório traz o tempo total e por fonte de cada modo.
"""
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from gpi.db import Database  # noqa: E402
from gpi.market.sync import SyncManager  # noqa: E402


def collect(workers: int) -> tuple[dict, float, Database, SyncManager]:
    tmp = Path(tempfile.mkdtemp(prefix=f"gpi-val-{workers}-"))
    db = Database(tmp / "v.sqlite")
    # amostra de no máximo 6 requisições por fonte e rodada: suficiente para provar a coleta real
    cfg = {"history_start_year": datetime.now().year - 1, "contact": "ci-validacao", "max_jobs_per_source": 6,
           "sync_workers": workers}
    from gpi.products.catalog import Catalog
    Catalog(db, cfg).ensure_seeded()          # catálogo de referência: fontes por produto (GDELT, eBay…) têm o que consultar
    sm = SyncManager(db, tmp, cfg)
    t0 = time.monotonic()
    summary = sm.run(f"validacao-ci-{workers}")
    return summary, time.monotonic() - t0, db, sm


def main(out: str, compare: bool, reports_dir: str | None = None):
    runs = {}
    if compare:
        s1, t1, _, _ = collect(1)
        runs["sequencial"] = {"segundos": round(t1, 1), "por_fonte": {k: v.get("segundos") for k, v in s1["fontes"].items()}}
    summary, t, db, sm = collect(4)
    runs["paralelo"] = {"segundos": round(t, 1), "por_fonte": {k: v.get("segundos") for k, v in summary["fontes"].items()}}
    st = sm.store.source_status()
    report = {"executado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "fontes": {},
              "desempenho": runs}
    for cid, res in summary["fontes"].items():
        s = st.get(cid, {})
        sample = db.query("SELECT s.series_key, s.origin_url, o.ref_date, o.value FROM market_obs o JOIN market_series s "
                          "ON s.id = o.series_id WHERE s.source = ? ORDER BY o.ref_date DESC LIMIT 1", (cid,))
        if not sample:
            sample = db.query("SELECT term, country, ref_date, metric, value, product_id, commercial FROM search_observations "
                              "WHERE source = ? ORDER BY commercial DESC, value DESC LIMIT 3", (cid,))
        report["fontes"][cid] = {"estado": s.get("state", res.get("estado")), "validada": bool(s.get("validated")),
                                 "registros": s.get("records", 0), "mensagem": s.get("message"),
                                 "segundos": res.get("segundos"), "amostra": sample or None}
    trends = db.query("SELECT country, COUNT(*) AS termos, SUM(product_id IS NOT NULL) AS com_produto, SUM(commercial) AS comerciais "
                      "FROM search_observations WHERE source = 'google_trends_rss' GROUP BY country")
    report["google_trends"] = trends
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    # resumo primeiro (as anotações do GitHub são truncadas em ~4 KB)
    for mode, r in runs.items():
        print(f"desempenho {mode}: {r['segundos']} s")
    for t_ in trends:
        print(f"google_trends {t_['country']}: {t_['termos']} termos em alta, {t_['com_produto']} com produto, "
              f"{t_['comerciais']} comerciais")
    ok = [k for k, v in report["fontes"].items() if v["validada"]]
    bad = [k for k, v in report["fontes"].items() if v["estado"] == "falhou"]
    print(f"validadas: {', '.join(ok)} | falharam: {', '.join(bad) or 'nenhuma'}")
    if reports_dir:
        real_reports(db, sm, Path(reports_dir))
    for k, v in report["fontes"].items():
        if v["estado"] == "restrita":
            continue
        print(f"{k:18s} {v['estado']:11s} validada={v['validada']} registros={v['registros']} "
              f"{v['segundos'] if v['segundos'] is not None else '-'}s {v['mensagem'] or ''}"[:200])


def real_reports(db, sm, out: Path):
    """v0.6: roda a análise completa sobre os dados REAIS recém-coletados e gera relatórios de exemplo
    (sem dados demonstrativos: não recebem a marca DEMONSTRAÇÃO)."""
    import shutil
    from gpi.market.analysis import make_analyzer
    from gpi.reports.service import ReportService
    t0 = time.monotonic()
    state = {"atual": "", "erros": []}
    res = make_analyzer({"ml_global_enabled": False})(sm.store, state)
    svc = ReportService(db, out.parent / "gpi-relatorios-reais", {})
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for tipo, fmt, f in (("executivo", "pdf", {}), ("executivo", "xlsx", {}), ("radar_global", "xlsx", {}), ("radar_global", "pdf", {}),
                         ("mais_pesquisados", "pdf", {}), ("tendencias_pais", "pdf", {"pais": "BR"}), ("social", "pdf", {})):
        r = svc.generate(tipo, fmt, f)
        p = svc.file(r["id"]) if r["status"] == "gerado" else None
        if p:
            shutil.copy2(p, out / p.name)
        made.append(f"{tipo}.{fmt}:{r['status']}{'(DEMO)' if r['demo'] else ''}")
    series = len((sm.store.load_result("consumer") or {}).get("series", []))
    print(f"relatorios reais: {series} séries de interesse; {', '.join(made)}; análise com erros: {state['erros'][:3]}; "
          f"{time.monotonic() - t0:.0f} s")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rd = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--relatorios=")), None)
    main(args[0] if args else "validacao_conectores.json", "--comparar" in sys.argv, rd)
