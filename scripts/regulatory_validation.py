"""Validação regulatória com DADOS REAIS (v0.8, Gate 7) — roda no CI, sem credenciais.

1. Baixa o arquivo oficial de dados abertos da Anatel e carrega pelo MESMO código do aplicativo.
2. Executa consultas de referência e verifica as classificações: exata, provável (outro fabricante), semelhante,
   não encontrado, situação suspensa/cancelada, pesquisa de empresas por produto (carregador, fone, smartwatch).
3. Todo resultado precisa ser rastreável (número + fonte oficial). Nenhum dado é inventado.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from gpi.db import Database  # noqa: E402
from gpi.regulatory import registry as R  # noqa: E402
from gpi.regulatory.api import search_all  # noqa: E402


def main(out: str):
    rep = {"executado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "verificacoes": []}

    def check(nome, ok, **kw):
        rep["verificacoes"].append({"verificacao": nome, "ok": bool(ok), **kw})
        print(("OK   " if ok else "FALHA"), nome, json.dumps(kw, ensure_ascii=False)[:300])

    t0 = time.time()
    req = urllib.request.Request(R.ANATEL_URL, headers={"User-Agent": "GPI-validacao/0.8"})
    raw = urllib.request.urlopen(req, timeout=300).read()
    db = Database(Path(tempfile.mkdtemp()) / "reg.sqlite")
    info = R.load_anatel_zip_v2(db, raw, R.ANATEL_URL)
    rep["anatel"] = {"bytes": len(raw), "registros": info["registros"], "colunas": info["colunas_reconhecidas"],
                     "segundos_download_e_carga": round(time.time() - t0, 1)}
    check("Arquivo oficial da Anatel carregado", info["registros"] > 100000 and len(info["colunas_reconhecidas"]) >= 16, **rep["anatel"])
    sit = db.query("SELECT situacao_requerimento AS s, COUNT(*) AS n FROM anatel_registros GROUP BY 1 ORDER BY 2 DESC")
    rep["situacoes"] = {r["s"]: r["n"] for r in sit}
    # referência real conhecida (amostra pública do próprio arquivo, lida pela sonda): Nikon DW092
    t = time.time()
    r = search_all(db, {"modelo": "DW092", "fabricante": "Nikon", "orgao": "Anatel"})
    ms = round((time.time() - t) * 1000)
    top = (r["resultados"] or [{}])[0]
    check("Referência real: modelo DW092 (Nikon) com correspondência exata", top.get("correspondencia") == R.EXACT
          and top.get("registro") and top.get("fonte_url"), registro=top.get("registro"), titular=top.get("empresa"),
          fabricante=top.get("fabricante"), situacao=top.get("situacao"), ms=ms)
    r2 = search_all(db, {"modelo": "DW092", "fabricante": "Samsung", "orgao": "Anatel"})
    check("Mesmo modelo, outro fabricante → não é exata", r2["resultados"] and r2["resultados"][0]["correspondencia"] != R.EXACT,
          classificacao=(r2["resultados"] or [{}])[0].get("correspondencia"))
    r3 = search_all(db, {"modelo": "GPI-INEXISTENTE-000", "orgao": "Anatel"})
    check("Modelo inexistente → sem correspondência confirmada", not r3["resultados"])
    susp = [x for x in r["resultados"] if not x["vigente"]]
    check("Situação suspensa/cancelada não é apresentada como vigente",
          all(x["situacao"] != "Homologação Emitida" for x in susp), suspensos=len(susp))
    exemplos = {}
    for prod, q in (("carregador de celular", {"tipo": "carregador para telefone celular", "de": "2025-01-01"}),
                    ("fone de ouvido bluetooth", {"produto": "fone", "tipo": "radiação restrita", "de": "2025-01-01"}),
                    ("smartwatch", {"produto": "smartwatch", "de": "2025-01-01"}),
                    ("fechadura inteligente", {"produto": "fechadura", "de": "2024-01-01"})):
        t = time.time()
        res = search_all(db, {**q, "orgao": "Anatel"})
        emp = res["empresas"]
        exemplos[prod] = {"registros": len(res["resultados"]), "ms": round((time.time() - t) * 1000),
                          "situacoes": dict(Counter(x["situacao"] for x in res["resultados"])),
                          "titulares_top": emp["titulares"][:5], "fabricantes_top": emp["fabricantes"][:5],
                          "exemplo": {k: (res["resultados"] or [{}])[0].get(k) for k in
                                      ("registro", "data", "empresa", "cnpj", "fabricante", "pais_fabricante", "modelo",
                                       "nome_comercial", "situacao", "correspondencia_rotulo", "fonte_url")}}
        ok = all(x["registro"] and x["fonte_url"] and x["correspondencia"] in (R.EXACT, R.PROBABLE, R.SIMILAR) for x in res["resultados"])
        check(f"Pesquisa de empresas: {prod} (rastreável até o registro oficial)", ok and res["resultados"],
              registros=len(res["resultados"]), titulares=len(emp["titulares"]), fabricantes=len(emp["fabricantes"]))
    rep["exemplos"] = exemplos
    rep["inmetro"] = {"estado": "não validado com dados reais",
                      "motivo": "API do portal dados.gov.br exige token (HTTP 401 na sonda); consulta pública é formulário HTML (não raspado)."}
    Path(out).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("situacoes:", json.dumps(rep["situacoes"], ensure_ascii=False))
    for k, v in exemplos.items():
        print("exemplo", k, json.dumps(v["exemplo"], ensure_ascii=False)[:500])
        print("  titulares", json.dumps(v["titulares_top"][:3], ensure_ascii=False)[:500])
    if not all(c["ok"] for c in rep["verificacoes"]):
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "regulatory_validation.json")
