"""Sonda das fontes regulatórias OFICIAIS (v0.8): verifica o que cada fonte pública oferece de fato.

Somente dados públicos; sem credenciais; sem raspagem de páginas protegidas (apenas downloads/APIs de dados abertos
e verificação de disponibilidade de páginas de consulta). Saída: JSON + resumo em texto.
"""
from __future__ import annotations

import collections
import csv
import io
import json
import sys
import urllib.request
import zipfile

UA = {"User-Agent": "GPI-regulatory-probe/0.8 (validacao de dados abertos)"}
ANATEL_ZIP = "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/certificacao_de_produtos/produtos_certificados.zip"
CANDIDATES = [
    ("inmetro_ckan_registro", "https://dados.gov.br/api/3/action/package_show?id=registro-de-objetos"),
    ("inmetro_ckan_registro2", "https://dados.gov.br/api/3/action/package_show?id=registrodeobjetos"),
    ("inmetro_ckan_prodcert", "https://dados.gov.br/api/3/action/package_show?id=sistemadeconsultaprodcert"),
    ("inmetro_ckan_busca", "https://dados.gov.br/api/3/action/package_search?q=inmetro%20registro&rows=10"),
    ("inmetro_registro_consulta", "http://registro.inmetro.gov.br/consulta/"),
    ("inmetro_prodcert", "http://www.inmetro.gov.br/prodcert/"),
    ("anatel_glossario_dir", "https://www.anatel.gov.br/dadosabertos/PDA/Certificacao/"),
    ("anatel_paineis_dir", "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/certificacao_de_produtos/"),
    ("anatel_sch", "https://sistemas.anatel.gov.br/mosaico/sch/publicView/listarProdutosHomologados.xhtml"),
]


def get(url, limit=400 * 1024 * 1024, timeout=180):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type"), r.read(limit)


def probe_anatel(out):
    try:
        st, ct, raw = get(ANATEL_ZIP)
    except Exception as e:  # noqa: BLE001
        out["anatel_zip"] = {"erro": str(e)[:300]}
        return
    z = zipfile.ZipFile(io.BytesIO(raw))
    info = {"http": st, "bytes": len(raw), "arquivos": z.namelist()[:10], "csv": {}}
    for name in [n for n in z.namelist() if n.lower().endswith(".csv")][:3]:
        data = z.read(name)
        enc = "utf-8-sig" if data[:3] == b"\xef\xbb\xbf" else "utf-8"
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            text, enc = data.decode("latin-1"), "latin-1"
        first = text.split("\n", 1)[0]
        delim = ";" if first.count(";") >= first.count(",") else ","
        rows = csv.reader(io.StringIO(text), delimiter=delim)
        header = next(rows)
        counters = {i: collections.Counter() for i in range(len(header))}
        sample, n = [], 0
        for row in rows:
            n += 1
            if len(sample) < 5 and n % 9973 == 1:
                sample.append(row)
            for i, v in enumerate(row[:len(header)]):
                if len(counters[i]) < 5000:
                    counters[i][v] += 1
        info["csv"][name] = {"encoding": enc, "delimitador": delim, "linhas": n, "colunas": header, "amostra": sample,
                             "valores_frequentes": {header[i]: c.most_common(8) for i, c in counters.items()
                                                    if 1 < len(c) < 5000}}
    out["anatel_zip"] = info


def main(path):
    out = {"fontes": {}}
    probe_anatel(out)
    for k, url in CANDIDATES:
        try:
            st, ct, raw = get(url, limit=200_000, timeout=60)
            body = raw.decode("utf-8", "replace")
            out["fontes"][k] = {"url": url, "http": st, "tipo": ct, "bytes": len(raw), "inicio": body[:3000]}
        except Exception as e:  # noqa: BLE001
            out["fontes"][k] = {"url": url, "erro": str(e)[:300]}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    a = out.get("anatel_zip", {})
    print("ANATEL:", json.dumps({k: v for k, v in a.items() if k != "csv"}, ensure_ascii=False)[:600])
    for name, c in (a.get("csv") or {}).items():
        print("CSV", name, c["linhas"], "linhas;", "colunas:", c["colunas"])
        for col, vals in c["valores_frequentes"].items():
            print("  ", col, "→", vals[:6])
        for s in c["amostra"][:3]:
            print("  amostra:", s)
    for k, v in out["fontes"].items():
        print(k, v.get("http") or v.get("erro"), v.get("tipo"), (v.get("inicio") or "")[:400].replace("\n", " "))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "regulatory_probe.json")
