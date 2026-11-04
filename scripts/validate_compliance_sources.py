"""Validação REAL das fontes oficiais da Conformidade de Importação (executada no GitHub Actions).

1. Tabela NCM oficial (Portal Único) → carrega, valida códigos conhecidos e grava o instantâneo dados_oficiais/ncm.json.
2. Dados abertos de produtos homologados da Anatel → carrega e consulta.
3. URLs oficiais da base regulatória → hash do conteúdo (registra o que leu e o que falhou).
4. Página de retorno OAuth do Mercado Livre publicada no GitHub Pages (se já ativada).
Resultado em JSON e Markdown, distinguindo sucesso real de falha (sem simulação).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from gpi.compliance import certs as C        # noqa: E402
from gpi.compliance import updater as U      # noqa: E402
from gpi.compliance.knowledge import KnowledgeBase   # noqa: E402
from gpi.compliance.ncm import NcmTable, OFFICIAL_URL   # noqa: E402
from gpi.connectors.http import HttpClient, HttpConfig  # noqa: E402
from gpi.db import Database                  # noqa: E402


def step(name, fn, out):
    t = time.perf_counter()
    try:
        r = fn()
        out.append({"etapa": name, "ok": True, "segundos": round(time.perf_counter() - t, 1), "resultado": r})
    except Exception as e:  # noqa: BLE001
        out.append({"etapa": name, "ok": False, "segundos": round(time.perf_counter() - t, 1), "erro": str(e)[:400]})
    print(json.dumps(out[-1], ensure_ascii=False, default=str)[:600], flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", required=True)
    ap.add_argument("--ncm-snapshot", default="")
    a = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp())
    db = Database(tmp / "v.sqlite")
    kb = KnowledgeBase(db, tmp)
    ncm = NcmTable(db)
    http = HttpClient(tmp / "cache", HttpConfig(timeout=120, connect_timeout=30, cache_ttl=0, min_interval=0.5))
    out = []

    def ncm_real():
        r = ncm.update_official(http)
        checks = {c: ncm.validate(c).get("estado") for c in ("8517.62.77", "8504.40.10", "9503.00.99", "8301.40.00")}
        if a.ncm_snapshot:
            raw = http.request_json(OFFICIAL_URL, _binary=True, ttl=0, _max_bytes=40 * 1024 * 1024, timeout=120)["_bytes"]
            Path(a.ncm_snapshot).parent.mkdir(parents=True, exist_ok=True)
            Path(a.ncm_snapshot).write_bytes(raw)
        return {**r, **ncm.meta(), "validacoes": checks, "candidatos_carregador": [c["codigo"] for c in ncm.candidates("carregador acumuladores")[:3]]}
    step("Tabela NCM oficial (Portal Único)", ncm_real, out)

    def anatel_real():
        r = C.update_anatel(db, http)
        q = C.anatel_lookup(db, modelo="ESP32-WROOM-32E")
        return {**r, "consulta_ESP32-WROOM-32E": [(x["numero"], x["fabricante"], x["modelo"], x["correspondencia"]) for x in q["resultados"][:3]]}
    step("Dados abertos da Anatel (produtos homologados)", anatel_real, out)

    step("URLs oficiais da base regulatória", lambda: {k: v for k, v in U.check_online(db, kb, http).items() if k != "id"}, out)

    def pages():
        url = "https://samuelseveriano.github.io/GPI/oauth/mercadolivre/"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "GPI-CI"}), timeout=30) as r:   # noqa: S310
            body = r.read().decode("utf-8", "replace")
        return {"url": url, "http": 200, "contem_relay": "relay.js" in body}
    step("Página HTTPS de retorno do Mercado Livre (GitHub Pages)", pages, out)

    verified = U.export_pack(kb, time.strftime("%Y.%m.%d"))
    (Path(a.saida).parent / "GPI-Base-Regulatoria-verificada.zip").write_bytes(verified)
    Path(a.saida).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = ["# Validação real das fontes da Conformidade de Importação", "", "| Etapa | Resultado | Tempo (s) | Detalhe |", "|---|---|---|---|"]
    for s in out:
        det = s.get("erro") or json.dumps(s.get("resultado"), ensure_ascii=False, default=str)[:300]
        md.append(f"| {s['etapa']} | {'OK' if s['ok'] else 'FALHOU'} | {s['segundos']} | {det.replace('|', '/')} |")
    Path(a.saida).with_suffix(".md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    main()
