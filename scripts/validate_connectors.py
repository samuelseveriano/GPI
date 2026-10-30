"""
Validação REAL dos conectores: executa uma sincronização contra as APIs públicas
(sem credenciais) e grava um relatório JSON com o resultado de cada fonte.
Roda no CI (runner com internet) e pode ser executado manualmente:
    python scripts/validate_connectors.py relatorio.json
Nenhum dado simulado é usado aqui.
"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from gpi.db import Database  # noqa: E402
from gpi.market.sync import SyncManager  # noqa: E402


def main(out: str):
    tmp = Path(tempfile.mkdtemp(prefix="gpi-val-"))
    db = Database(tmp / "v.sqlite")
    # amostra de no máximo 6 requisições por fonte: suficiente para provar a coleta real
    cfg = {"history_start_year": datetime.now().year - 1, "contact": "ci-validacao", "max_jobs_per_source": 6}
    sm = SyncManager(db, tmp, cfg)
    summary = sm.run("validacao-ci")
    st = sm.store.source_status()
    report = {"executado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "fontes": {}}
    for cid, res in summary["fontes"].items():
        s = st.get(cid, {})
        sample = db.query("SELECT s.series_key, s.origin_url, o.ref_date, o.value FROM market_obs o JOIN market_series s "
                          "ON s.id = o.series_id WHERE s.source = ? ORDER BY o.ref_date DESC LIMIT 1", (cid,))
        report["fontes"][cid] = {"estado": s.get("state", res.get("estado")), "validada": bool(s.get("validated")),
                                 "registros": s.get("records", 0), "mensagem": s.get("message"),
                                 "amostra": sample[0] if sample else None}
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in report["fontes"].items():
        print(f"{k:15s} {v['estado']:11s} validada={v['validada']} registros={v['registros']} {v['mensagem'] or ''}"[:200])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "validacao_conectores.json")
