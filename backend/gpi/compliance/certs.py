"""Consulta de homologações e certificados (seção 14).

* Anatel: dados abertos oficiais de produtos homologados (ZIP/CSV) carregados localmente por ação do usuário ou
  arquivo entregue pela TI → consulta por número, fabricante e modelo, sem raspagem. Também gera o link de
  consulta manual assistida no sistema oficial.
* Inmetro: sem API pública conhecida → consulta manual assistida (Banco de Registro e Prodcert) com registro da
  evidência informada pelo usuário.
* Correspondência: só "modelo exato" (normalizado) é tratado como possível comprovação; modelos semelhantes,
  outra marca ou outro fabricante são apresentados como NÃO comprovação para o produto analisado.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
import zipfile
from datetime import datetime

ANATEL_OPEN_DATA = "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/certificacao_de_produtos/produtos_certificados.zip"
ANATEL_MANUAL = "https://sistemas.anatel.gov.br/mosaico/sch/publicView/listarProdutosHomologados.xhtml"
INMETRO_REGISTRO = "http://registro.inmetro.gov.br/consulta"
INMETRO_PRODCERT = "http://www.inmetro.gov.br/prodcert"
MAX_ZIP = 300 * 1024 * 1024


def _h(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def model_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _h(s))


COLS = {
    "numero": [("homologa", "n"), ("numero", "homolog"), ("certificado", "homolog")],
    "fabricante": [("fabricante",)],
    "modelo": [("modelo",)],
    "nome_comercial": [("nome", "comercial"), ("comercial",)],
    "tipo_produto": [("tipo", "produto"), ("tipo",)],
    "data_homologacao": [("data", "homolog")],
    "situacao": [("situacao",)],
    "solicitante": [("solicitante",)],
}


def map_headers(headers: list[str]) -> dict[str, int]:
    hn = [_h(x) for x in headers]
    out = {}
    for field, opts in COLS.items():
        for need in opts:
            idx = next((i for i, h in enumerate(hn) if all(n in h.split() or n in h for n in need) and i not in out.values()), None)
            if idx is not None:
                out[field] = idx
                break
    if "modelo" not in out or "fabricante" not in out:
        raise ValueError("CSV da Anatel sem colunas de fabricante/modelo reconhecíveis")
    return out


def load_anatel_zip(db, raw: bytes, origem: str) -> dict:
    if len(raw) > MAX_ZIP:
        raise ValueError("arquivo maior que o limite")
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = [n for n in z.namelist() if n.lower().endswith(".csv") and not n.startswith(("/", "..")) and ".." not in n]
    if not names:
        raise ValueError("ZIP da Anatel sem arquivo CSV")
    n_rows = 0
    with db.transaction():
        db.execute("DELETE FROM anatel_homologacoes")
        for name in names[:3]:
            with z.open(name) as fh:
                head = fh.read(4096)
            enc = "utf-8-sig" if head.startswith(b"\xef\xbb\xbf") or _is_utf8(head) else "latin-1"
            with z.open(name) as fh:
                text = io.TextIOWrapper(fh, encoding=enc, errors="replace", newline="")
                sample = text.readline()
                delim = ";" if sample.count(";") >= sample.count(",") else ","
                reader = csv.reader(io.StringIO(sample), delimiter=delim)
                headers = next(reader)
                cols = map_headers(headers)
                batch = []
                for row in csv.reader(text, delimiter=delim):
                    if not row:
                        continue
                    g = lambda f: (row[cols[f]].strip() if f in cols and cols[f] < len(row) else None)  # noqa: E731
                    batch.append((g("numero"), g("fabricante"), g("modelo"), g("nome_comercial"), g("tipo_produto"),
                                  g("data_homologacao"), g("situacao"), g("solicitante"), None))
                    if len(batch) >= 5000:
                        db.executemany("INSERT INTO anatel_homologacoes VALUES (?,?,?,?,?,?,?,?,?)", batch)
                        n_rows += len(batch)
                        batch = []
                if batch:
                    db.executemany("INSERT INTO anatel_homologacoes VALUES (?,?,?,?,?,?,?,?,?)", batch)
                    n_rows += len(batch)
        meta = {"anatel_fonte": origem, "anatel_carregada_em": datetime.now().isoformat(timespec="seconds"),
                "anatel_sha256": hashlib.sha256(raw).hexdigest(), "anatel_registros": str(n_rows)}
        for k, v in meta.items():
            db.execute("INSERT OR REPLACE INTO ncm_meta VALUES (?, ?)", (k, v))
    return {"registros": n_rows, "sha256": meta["anatel_sha256"]}


def _is_utf8(b: bytes) -> bool:
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def update_anatel(db, http) -> dict:
    r = http.request_json(ANATEL_OPEN_DATA, _binary=True, ttl=0, _max_bytes=MAX_ZIP, timeout=300,
                          headers={"Accept": "application/zip, */*"})
    raw = r["_bytes"]
    return load_anatel_zip(db, raw, ANATEL_OPEN_DATA)


def anatel_meta(db) -> dict:
    m = {r["k"]: r["v"] for r in db.query("SELECT k, v FROM ncm_meta WHERE k LIKE 'anatel_%'")}
    return {"carregada": bool(m.get("anatel_registros")), "registros": int(m.get("anatel_registros") or 0),
            "fonte": m.get("anatel_fonte"), "carregada_em": m.get("anatel_carregada_em"), "sha256": m.get("anatel_sha256"),
            "url_oficial": ANATEL_OPEN_DATA, "consulta_manual": ANATEL_MANUAL}


def anatel_lookup(db, numero: str = "", fabricante: str = "", modelo: str = "", limit: int = 30) -> dict:
    """Consulta local. Classifica cada linha como 'modelo_exato' ou 'semelhante' — semelhante NUNCA comprova."""
    meta = anatel_meta(db)
    res = {"fonte": "dados abertos da Anatel" if meta["carregada"] else None, "base": meta, "resultados": [],
           "consulta_manual": ANATEL_MANUAL,
           "aviso": "Homologação de produto semelhante, de outra marca ou de outro modelo NÃO vale para o produto analisado."}
    if not meta["carregada"]:
        res["mensagem"] = "Dados abertos da Anatel não carregados: use 'Atualizar dados da Anatel' ou a consulta manual."
        return res
    where, params = [], []
    if numero.strip():
        where.append("replace(replace(numero, '-', ''), ' ', '') LIKE ?")
        params.append("%" + re.sub(r"[\s\-]", "", numero.strip()) + "%")
    mk = model_key(modelo)
    if mk:
        where.append("lower(replace(replace(replace(modelo, '-', ''), ' ', ''), '/', '')) LIKE ?")
        params.append(f"%{mk[:40]}%")
    if fabricante.strip() and not where:
        where.append("lower(fabricante) LIKE ?")
        params.append(f"%{_h(fabricante)[:40]}%")
    if not where:
        res["mensagem"] = "Informe número de homologação, modelo ou fabricante."
        return res
    rows = db.query(f"SELECT * FROM anatel_homologacoes WHERE {' AND '.join(where)} LIMIT 300", tuple(params))
    fk = _h(fabricante)
    out = []
    for r in rows:
        exact_model = bool(mk) and model_key(r.get("modelo") or "") == mk
        same_maker = bool(fk) and fk.split()[0] in _h(r.get("fabricante") or "")
        if numero.strip() and not mk:
            corr = "numero_informado"
        elif exact_model and (same_maker or not fk):
            corr = "modelo_exato"
        else:
            corr = "semelhante"
        out.append({**{k: r.get(k) for k in ("numero", "fabricante", "modelo", "nome_comercial", "tipo_produto",
                                             "data_homologacao", "situacao", "solicitante")},
                    "correspondencia": corr,
                    "nota": {"modelo_exato": "modelo técnico idêntico ao informado — conferir fabricante, situação e documentação pública",
                             "numero_informado": "registro encontrado pelo número — conferir se o modelo corresponde ao produto",
                             "semelhante": "NÃO comprova a homologação do produto analisado (modelo/fabricante diferente)"}[corr]})
    out.sort(key=lambda x: {"modelo_exato": 0, "numero_informado": 1, "semelhante": 2}[x["correspondencia"]])
    res["resultados"] = out[:limit]
    res["total"] = len(out)
    return res


def manual_links(marca: str = "", modelo: str = "") -> list[dict]:
    return [
        {"orgao": "Anatel", "nome": "Consulta pública de produtos homologados (SCH)", "url": ANATEL_MANUAL,
         "como": f"Pesquise pelo modelo técnico exato{(' “' + modelo + '”') if modelo else ''} e confira fabricante, situação e certificado."},
        {"orgao": "Inmetro", "nome": "Banco de Registro do Inmetro", "url": INMETRO_REGISTRO,
         "como": f"Pesquise por produto/marca{(' “' + marca + '”') if marca else ''}, empresa ou número do registro; confira o modelo exato."},
        {"orgao": "Inmetro", "nome": "Prodcert — certificados, produtos e empresas", "url": INMETRO_PRODCERT,
         "como": "Consulte as abas Certificados, Produtos ou Empresas; o certificado deve abranger o modelo exato."},
    ]


def record_check(db, analysis_id, orgao: str, consulta: dict, resultado: str, evidencia: str, por: str) -> int:
    if orgao not in ("Anatel", "Inmetro"):
        raise ValueError("órgão inválido")
    if resultado not in ("encontrado_modelo_exato", "encontrado_semelhante", "nao_encontrado", "inconclusivo"):
        raise ValueError("resultado inválido")
    cur = db.execute("INSERT INTO compliance_cert_checks (analysis_id, orgao, consulta, resultado, evidencia, verificado_por, criado_em) "
                     "VALUES (?,?,?,?,?,?,?)", (analysis_id, orgao, json.dumps(consulta, ensure_ascii=False)[:2000], resultado,
                                                 (evidencia or "")[:2000], por[:40], datetime.now().isoformat(timespec="seconds")))
    return int(cur.lastrowid)
