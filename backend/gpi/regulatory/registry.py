"""Registros oficiais e pesquisa de empresas (v0.8, seções 16–20, Gate 7).

ANATEL — dados abertos oficiais "Produtos Homologados" (ZIP/CSV, ~190 mil linhas). Colunas confirmadas no arquivo real
(sonda no CI em 04/11/2026): Data da Homologação; Número de Homologação; Nome do Solicitante; CNPJ do Solicitante;
Certificado de Conformidade Técnica; Data do Certificado; Data de Validade do Certificado; Código/Situação do Certificado;
Código/Situação do Requerimento; Nome do Fabricante; Modelo; Nome Comercial; Categoria do Produto; Tipo do Produto;
IC_ANTENA; IC_ATIVO; País do Fabricante; CodUIT; CodISO.

INMETRO — a API do portal dados.gov.br exige token e a consulta pública (registro.inmetro.gov.br) é um formulário
HTML: NÃO é raspada. O GPI aceita (a) o arquivo oficial baixado pelo usuário e (b) a consulta manual assistida com
registro da evidência.

Correspondência (sempre em relação ao que o usuário informou):
* EXATA     — modelo técnico normalizado idêntico E fabricante/marca informados compatíveis (ou não informados)
* PROVÁVEL  — modelo idêntico com fabricante diferente/indeterminado, ou modelo informado contido no registrado (≥ 6 caracteres)
* SEMELHANTE — mesmo tipo de produto/nome comercial, modelo diferente
* SEM CORRESPONDÊNCIA CONFIRMADA — nada acima
A existência de registro semelhante NÃO comprova dispensa de certificação, direito de uso do certificado, autorização de
comercialização, dispensa de LPCO/anuência nem validade para outro modelo.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime

ANATEL_URL = "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/certificacao_de_produtos/produtos_certificados.zip"
ANATEL_CONSULTA = "https://sistemas.anatel.gov.br/mosaico/sch/publicView/listarProdutosHomologados.xhtml"
INMETRO_CONSULTA = "http://registro.inmetro.gov.br/consulta/"
INMETRO_PRODCERT = "http://www.inmetro.gov.br/prodcert/"
INMETRO_DADOS = "https://dados.gov.br/dados/conjuntosdados/registrodeobjetos"

EXACT, PROBABLE, SIMILAR, NONE = "exata", "provavel", "semelhante", "sem_correspondencia"
MATCH_LABEL = {EXACT: "CORRESPONDÊNCIA EXATA", PROBABLE: "CORRESPONDÊNCIA PROVÁVEL", SIMILAR: "PRODUTO SEMELHANTE",
               NONE: "SEM CORRESPONDÊNCIA CONFIRMADA"}
LIMITS = ["A existência de registro semelhante não comprova dispensa de certificação.",
          "Um certificado/homologação de terceiro não dá direito de uso a outro importador.",
          "Registro não equivale a autorização de comercialização, dispensa de LPCO ou de anuência.",
          "Homologação de um modelo não vale para outro modelo, mesmo parecido.",
          "Confirme sempre na consulta oficial do órgão antes de qualquer decisão."]

# significado documentado de cada campo (seção 18 — "não confundir")
FIELD_DOC = {
    "numero_homologacao": "Número do certificado de homologação emitido pela Anatel para o requerente.",
    "solicitante": "Requerente da homologação na Anatel — titular do certificado de homologação. NÃO é necessariamente o fabricante.",
    "cnpj_solicitante": "CNPJ público do requerente/titular, como publicado pela Anatel.",
    "certificado": "Certificado de Conformidade Técnica emitido por Organismo de Certificação Designado (OCD) — etapa anterior à homologação.",
    "situacao_certificado": "Situação do Certificado de Conformidade Técnica (ex.: Preenchimento Concluído, Suspenso, Cancelado).",
    "situacao_requerimento": "Situação da homologação (ex.: Homologação Emitida, Suspensa, Cancelada, Em Análise).",
    "fabricante": "Fabricante declarado no requerimento.",
    "pais_fabricante": "País do fabricante declarado.",
    "modelo": "Modelo técnico homologado (a homologação vale para este modelo).",
    "nome_comercial": "Nome comercial declarado (pode incluir marca).",
    "tipo_produto": "Tipo de produto segundo a Anatel.",
    "categoria": "Categoria do produto informada pela Anatel (1 a 4), conforme o regulamento de avaliação da conformidade.",
    "registro_inmetro": "Registro de Objeto no Inmetro: autorização de uso do Selo de Identificação da Conformidade, concedida ao "
                        "fornecedor detentor do registro para o objeto registrado.",
    "certificado_inmetro": "Certificado de conformidade emitido por Organismo de Certificação de Produto (OCP) acreditado pelo Inmetro.",
    "organismo": "Organismo certificador (OCP/OCD). É um papel distinto de fabricante e de titular.",
}
ROLES = {"titular": "Titular/requerente da homologação ou detentor do registro", "fabricante": "Fabricante declarado",
         "organismo": "Organismo certificador", "representante": "Representante", "solicitante": "Solicitante"}

ANATEL_COLS = {
    "data_homologacao": "data da homologacao", "numero_homologacao": "numero de homologacao", "solicitante": "nome do solicitante",
    "cnpj_solicitante": "cnpj do solicitante", "certificado": "certificado de conformidade tecnica",
    "data_certificado": "data do certificado de conformidade tecnica", "validade_certificado": "data de validade do certificado",
    "situacao_certificado": "situacao do certificado", "situacao_requerimento": "situacao do requerimento",
    "fabricante": "nome do fabricante", "modelo": "modelo", "nome_comercial": "nome comercial", "categoria": "categoria do produto",
    "tipo_produto": "tipo do produto", "antena": "ic_antena", "ativo": "ic_ativo", "pais_fabricante": "pais do fabricante"}


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9_]+", " ", s)).strip()


def model_key(s) -> str:
    return re.sub(r"[^a-z0-9]", "", norm(s))


def _date(s: str | None) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _cols(header: list[str], spec: dict) -> dict:
    hn = [norm(h) for h in header]
    out = {}
    for field, name in spec.items():
        if name in hn:
            out[field] = hn.index(name)
    return out


# ------------------------------------------------------------------------------------------------- Anatel
def load_anatel_csv(db, text_stream, origem: str) -> dict:
    reader = csv.reader(text_stream, delimiter=";")
    header = next(reader)
    cols = _cols(header, ANATEL_COLS)
    if "modelo" not in cols or "numero_homologacao" not in cols:
        raise ValueError("CSV sem as colunas oficiais 'Modelo' e 'Número de Homologação'")
    n, batch = 0, []
    db.execute("DELETE FROM anatel_registros")
    for row in reader:
        if not row:
            continue
        g = lambda f: (row[cols[f]].strip() if f in cols and cols[f] < len(row) else None)  # noqa: E731
        batch.append((g("numero_homologacao"), _date(g("data_homologacao")), g("solicitante"), g("cnpj_solicitante"), g("certificado"),
                      _date(g("data_certificado")), _date(g("validade_certificado")), g("situacao_certificado"),
                      g("situacao_requerimento"), g("fabricante"), g("pais_fabricante"), g("modelo"), model_key(g("modelo")),
                      g("nome_comercial"), g("categoria"), g("tipo_produto"), g("antena"), g("ativo")))
        if len(batch) >= 5000:
            db.executemany("INSERT INTO anatel_registros VALUES (" + ",".join("?" * 18) + ")", batch)
            n += len(batch)
            batch = []
    if batch:
        db.executemany("INSERT INTO anatel_registros VALUES (" + ",".join("?" * 18) + ")", batch)
        n += len(batch)
    db.execute("INSERT OR REPLACE INTO ncm_meta VALUES ('anatel_v2_registros', ?)", (str(n),))
    db.execute("INSERT OR REPLACE INTO ncm_meta VALUES ('anatel_v2_carregada_em', ?)", (datetime.now().isoformat(timespec="seconds"),))
    db.execute("INSERT OR REPLACE INTO ncm_meta VALUES ('anatel_v2_fonte', ?)", (origem,))
    return {"registros": n, "colunas_reconhecidas": sorted(cols)}


def load_anatel_zip_v2(db, raw: bytes, origem: str) -> dict:
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = [x for x in z.namelist() if x.lower().endswith(".csv") and ".." not in x and not x.startswith("/")]
    if not names:
        raise ValueError("ZIP sem CSV")
    data = z.read(names[0])
    enc = "utf-8-sig" if data[:3] == b"\xef\xbb\xbf" else "utf-8"
    try:
        text = data.decode(enc)
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    with db.transaction():
        return load_anatel_csv(db, io.StringIO(text, newline=""), origem)


def anatel_status(db) -> dict:
    m = {r["k"]: r["v"] for r in db.query("SELECT k, v FROM ncm_meta WHERE k LIKE 'anatel_v2_%'")}
    return {"carregada": bool(m.get("anatel_v2_registros")), "registros": int(m.get("anatel_v2_registros") or 0),
            "carregada_em": m.get("anatel_v2_carregada_em"), "fonte": m.get("anatel_v2_fonte"), "url_oficial": ANATEL_URL,
            "consulta_oficial": ANATEL_CONSULTA}


def classify(row: dict, q: dict) -> tuple[str, str]:
    mk = model_key(q.get("modelo"))
    rk = row.get("modelo_chave") or model_key(row.get("modelo"))
    maker = norm(q.get("fabricante") or q.get("marca"))
    reg_maker = norm(" ".join(x or "" for x in (row.get("fabricante"), row.get("nome_comercial"), row.get("solicitante"),
                                                 row.get("razao_social"), row.get("marca"))))
    maker_ok = not maker or maker.split()[0] in reg_maker
    if mk and rk == mk:
        if maker_ok:
            return EXACT, "modelo técnico idêntico" + (" e fabricante/marca compatível" if maker else " (fabricante não informado na pesquisa)")
        return PROBABLE, "modelo idêntico, mas fabricante/marca registrado é diferente do informado"
    if mk and len(mk) >= 6 and mk in rk:
        return PROBABLE, "modelo informado contido no modelo registrado — confirmar variação de modelo"
    if mk:
        return SIMILAR, "modelo diferente; mesmo tipo de produto ou fabricante"
    return SIMILAR, "registro relacionado ao produto/empresa pesquisado (sem modelo informado)"


def search_anatel(db, q: dict, limit: int = 200) -> dict:
    st = anatel_status(db)
    out = {"orgao": "Anatel", "fonte": "Dados abertos da Anatel — Produtos Homologados", "fonte_url": ANATEL_URL,
           "consulta_oficial": ANATEL_CONSULTA, "base": st, "resultados": [], "limitacoes": LIMITS}
    if not st["carregada"]:
        out["mensagem"] = "Base oficial da Anatel não carregada: use 'Atualizar dados oficiais' (download do arquivo aberto) ou a consulta oficial."
        out["estado_fonte"] = "indisponivel"
        return out
    where, params = [], []
    mk = model_key(q.get("modelo"))
    if mk:
        where.append("modelo_chave LIKE ?")
        params.append(f"%{mk[:40]}%")
    if (q.get("numero") or "").strip():
        where.append("(replace(numero_homologacao, '-', '') LIKE ? OR certificado LIKE ?)")
        num = re.sub(r"[\s\-]", "", q["numero"].strip())
        params += [f"%{num}%", f"%{q['numero'].strip()}%"]
    keyed = bool(mk or (q.get("numero") or "").strip())
    for f, col in (("fabricante", "fabricante"), ("titular", "solicitante"), ("marca", "nome_comercial"), ("tipo", "tipo_produto")):
        if f in ("fabricante", "marca") and keyed:
            continue        # com modelo/número, fabricante e marca CLASSIFICAM (exata × provável), não escondem registros
        if (q.get(f) or "").strip():
            where.append(f"lower({col}) LIKE ?")
            params.append(f"%{q[f].strip().lower()[:60]}%")
    if (q.get("cnpj") or "").strip():
        where.append("cnpj_solicitante = ?")
        params.append(re.sub(r"\D", "", q["cnpj"]))
    if (q.get("produto") or "").strip():
        terms = [t for t in norm(q["produto"]).split() if len(t) >= 3][:3]
        for t in terms:
            where.append("(lower(nome_comercial) LIKE ? OR lower(tipo_produto) LIKE ?)")
            params += [f"%{t}%", f"%{t}%"]
    if q.get("situacao"):
        where.append("situacao_requerimento = ?")
        params.append(q["situacao"])
    if q.get("de"):
        where.append("data_homologacao >= ?")
        params.append(q["de"])
    if q.get("ate"):
        where.append("data_homologacao <= ?")
        params.append(q["ate"])
    if q.get("categoria"):
        where.append("categoria = ?")
        params.append(str(q["categoria"]))
    if not where:
        out["mensagem"] = "Informe produto, marca, modelo, fabricante, titular, CNPJ, número, tipo ou período."
        return out
    rows = db.query(f"SELECT * FROM anatel_registros WHERE {' AND '.join(where)} ORDER BY data_homologacao DESC LIMIT ?",
                    tuple(params) + (limit,))
    res = []
    for r in rows:
        c, why = classify(r, q)
        res.append({"orgao": "Anatel", "registro": r["numero_homologacao"], "data": r["data_homologacao"],
                    "empresa": r["solicitante"], "cnpj": r["cnpj_solicitante"], "papel": "titular",
                    "papel_rotulo": ROLES["titular"], "fabricante": r["fabricante"], "pais_fabricante": r["pais_fabricante"],
                    "marca": None, "nome_comercial": r["nome_comercial"], "modelo": r["modelo"], "tipo_produto": r["tipo_produto"],
                    "categoria": r["categoria"], "certificado": r["certificado"], "validade_certificado": r["validade_certificado"],
                    "situacao": r["situacao_requerimento"], "situacao_certificado": r["situacao_certificado"],
                    "vigente": r["situacao_requerimento"] == "Homologação Emitida",
                    "correspondencia": c, "correspondencia_rotulo": MATCH_LABEL[c], "motivo_correspondencia": why,
                    "fonte": "Anatel — dados abertos", "fonte_url": ANATEL_CONSULTA,
                    "id_registro": f"anatel:{r['numero_homologacao']}:{r['modelo_chave']}"})
    order = {EXACT: 0, PROBABLE: 1, SIMILAR: 2}
    res.sort(key=lambda x: (order[x["correspondencia"]], not x["vigente"], -(int((x["data"] or "0000")[:4]) if x["data"] else 0)))
    out["resultados"] = res
    out["total"] = len(res)
    out["resumo"] = {MATCH_LABEL[k]: sum(1 for x in res if x["correspondencia"] == k) for k in (EXACT, PROBABLE, SIMILAR)}
    if not res:
        out["resumo"] = {MATCH_LABEL[NONE]: 1}
        out["mensagem"] = "Nenhum registro encontrado na base oficial carregada: SEM CORRESPONDÊNCIA CONFIRMADA (confirme na consulta oficial)."
    return out


# ------------------------------------------------------------------------------------------------- Inmetro
INMETRO_COLS = {  # cabeçalhos aceitos (normalizados) → campo
    "numero_registro": ["numero do registro", "numero registro", "registro", "n do registro", "nr registro"],
    "razao_social": ["razao social", "empresa", "fornecedor", "nome empresarial", "detentor do registro"],
    "cnpj": ["cnpj", "cnpj do fornecedor", "cnpj da empresa"],
    "fabricante": ["fabricante", "nome do fabricante"],
    "marca": ["marca", "marca modelo"],
    "modelo": ["modelo", "modelos", "familia modelo"],
    "objeto": ["objeto", "produto", "descricao do objeto", "descricao do produto"],
    "certificado": ["certificado", "numero do certificado", "n do certificado", "atestado"],
    "organismo": ["ocp", "organismo", "organismo certificador", "organismo de certificacao"],
    "programa": ["programa", "portaria", "programa de avaliacao da conformidade", "rac"],
    "situacao": ["situacao", "status"],
    "data_registro": ["data do registro", "data de concessao", "data concessao", "data"],
    "validade": ["validade", "data de validade", "vencimento"],
}


def load_inmetro_file(db, raw: bytes, filename: str) -> dict:
    """Arquivo oficial baixado pelo usuário (CSV ; ou ,). Colunas reconhecidas por nome; as demais ficam em 'extra'."""
    text = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    first = text.split("\n", 1)[0]
    delim = ";" if first.count(";") >= first.count(",") else ","
    rd = csv.reader(io.StringIO(text, newline=""), delimiter=delim)
    header = next(rd)
    hn = [norm(h) for h in header]
    cols = {}
    for f, names in INMETRO_COLS.items():
        for nm in names:
            if nm in hn and hn.index(nm) not in cols.values():
                cols[f] = hn.index(nm)
                break
    if not ({"numero_registro", "certificado"} & set(cols)) or not ({"modelo", "objeto"} & set(cols)):
        raise ValueError("arquivo sem colunas reconhecíveis de registro/certificado e modelo/objeto — confira se é o arquivo oficial")
    import json
    n = 0
    with db.transaction():
        db.execute("DELETE FROM inmetro_registros")
        for row in rd:
            if not row:
                continue
            g = lambda f: (row[cols[f]].strip() if f in cols and cols[f] < len(row) else None)  # noqa: E731
            extra = {header[i]: row[i] for i in range(min(len(row), len(header))) if i not in cols.values() and row[i]}
            db.execute("INSERT INTO inmetro_registros VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (g("numero_registro"), g("razao_social"), re.sub(r"\D", "", g("cnpj") or "") or None, g("fabricante"), g("marca"),
                        g("modelo"), model_key(g("modelo")), g("objeto"), g("certificado"), g("organismo"), g("programa"), g("situacao"),
                        _date(g("data_registro")) or g("data_registro"), _date(g("validade")) or g("validade"),
                        json.dumps(extra, ensure_ascii=False)[:2000] if extra else None))
            n += 1
        for k, v in (("inmetro_registros", str(n)), ("inmetro_carregada_em", datetime.now().isoformat(timespec="seconds")),
                     ("inmetro_arquivo", filename[:200])):
            db.execute("INSERT OR REPLACE INTO ncm_meta VALUES (?, ?)", (k, v))
    return {"registros": n, "colunas_reconhecidas": sorted(cols), "colunas_ignoradas": [h for i, h in enumerate(header) if i not in cols.values()]}


def inmetro_status(db) -> dict:
    m = {r["k"]: r["v"] for r in db.query("SELECT k, v FROM ncm_meta WHERE k LIKE 'inmetro_%'")}
    return {"carregada": bool(m.get("inmetro_registros")), "registros": int(m.get("inmetro_registros") or 0),
            "carregada_em": m.get("inmetro_carregada_em"), "arquivo": m.get("inmetro_arquivo"),
            "consulta_oficial": INMETRO_CONSULTA, "prodcert": INMETRO_PRODCERT, "dados_abertos": INMETRO_DADOS,
            "nota": "O portal de dados abertos exige token e a consulta pública é um formulário: o GPI não automatiza a consulta. "
                    "Baixe o arquivo oficial e importe-o aqui, ou registre a consulta manual."}


def search_inmetro(db, q: dict, limit: int = 200) -> dict:
    st = inmetro_status(db)
    out = {"orgao": "Inmetro", "fonte": "Arquivo oficial do Inmetro importado pelo usuário", "base": st, "resultados": [],
           "consulta_oficial": INMETRO_CONSULTA, "limitacoes": LIMITS}
    if not st["carregada"]:
        out["estado_fonte"] = "indisponivel"
        out["mensagem"] = "Nenhum arquivo oficial do Inmetro importado. Use a consulta oficial e registre o resultado (consulta assistida)."
        return out
    where, params = [], []
    mk = model_key(q.get("modelo"))
    if mk:
        where.append("modelo_chave LIKE ?")
        params.append(f"%{mk[:40]}%")
    keyed = bool(mk or (q.get("numero") or "").strip() or (q.get("certificado") or "").strip())
    for f, col in (("numero", "numero_registro"), ("certificado", "certificado"), ("marca", "marca"), ("fabricante", "fabricante"),
                   ("titular", "razao_social"), ("produto", "objeto"), ("programa", "programa")):
        if f in ("fabricante", "marca") and keyed:
            continue
        if (q.get(f) or "").strip():
            where.append(f"lower({col}) LIKE ?")
            params.append(f"%{q[f].strip().lower()[:60]}%")
    if (q.get("cnpj") or "").strip():
        where.append("cnpj = ?")
        params.append(re.sub(r"\D", "", q["cnpj"]))
    if not where:
        out["mensagem"] = "Informe produto, marca, modelo, empresa, CNPJ, registro, certificado ou programa."
        return out
    rows = db.query(f"SELECT * FROM inmetro_registros WHERE {' AND '.join(where)} LIMIT ?", tuple(params) + (limit,))
    for r in rows:
        c, why = classify(r, q)
        out["resultados"].append({
            "orgao": "Inmetro", "registro": r["numero_registro"], "data": r["data_registro"], "empresa": r["razao_social"],
            "cnpj": r["cnpj"], "papel": "titular", "papel_rotulo": ROLES["titular"], "fabricante": r["fabricante"], "marca": r["marca"],
            "modelo": r["modelo"], "nome_comercial": r["objeto"], "tipo_produto": r["objeto"], "certificado": r["certificado"],
            "organismo": r["organismo"], "programa": r["programa"], "situacao": r["situacao"], "validade_certificado": r["validade"],
            "vigente": None if not r["situacao"] else norm(r["situacao"]) in ("ativo", "vigente", "valido", "concedido"),
            "correspondencia": c, "correspondencia_rotulo": MATCH_LABEL[c], "motivo_correspondencia": why,
            "fonte": "Inmetro — arquivo oficial importado", "fonte_url": INMETRO_CONSULTA,
            "id_registro": f"inmetro:{r['numero_registro'] or r['certificado']}:{r['modelo_chave']}"})
    out["total"] = len(out["resultados"])
    if not rows:
        out["mensagem"] = "Nenhum registro no arquivo importado: SEM CORRESPONDÊNCIA CONFIRMADA (confirme na consulta oficial)."
    return out


# ------------------------------------------------------------------------------------------------- empresas (seção 19)
def companies(results: list[dict]) -> dict:
    """Tabela Empresa | Papel | Fabricante | Marca | Modelo | Registro | Situação | Correspondência | Fonte, e agregações.
    Contagem de registros NÃO é participação de mercado; empresas encontradas não têm, presumidamente, interesse em fornecer."""
    rows = []
    for r in results:
        rows.append({"empresa": r["empresa"], "cnpj": r.get("cnpj"), "papel": r["papel_rotulo"], "fabricante": r.get("fabricante"),
                     "marca": r.get("marca") or "não informado pela fonte", "modelo": r.get("modelo"), "registro": r.get("registro"),
                     "situacao": r.get("situacao"), "correspondencia": r["correspondencia_rotulo"], "fonte": r["fonte"],
                     "orgao": r["orgao"], "id_registro": r["id_registro"]})
        if r.get("fabricante") and norm(r["fabricante"]) != norm(r.get("empresa")):
            rows.append({"empresa": r["fabricante"], "cnpj": None, "papel": ROLES["fabricante"], "fabricante": r["fabricante"],
                         "marca": r.get("marca") or "não informado pela fonte", "modelo": r.get("modelo"), "registro": r.get("registro"),
                         "situacao": r.get("situacao"), "correspondencia": r["correspondencia_rotulo"], "fonte": r["fonte"],
                         "orgao": r["orgao"], "id_registro": r["id_registro"]})
        if r.get("organismo"):
            rows.append({"empresa": r["organismo"], "cnpj": None, "papel": ROLES["organismo"], "fabricante": r.get("fabricante"),
                         "marca": r.get("marca") or "não informado pela fonte", "modelo": r.get("modelo"), "registro": r.get("registro"),
                         "situacao": r.get("situacao"), "correspondencia": r["correspondencia_rotulo"], "fonte": r["fonte"],
                         "orgao": r["orgao"], "id_registro": r["id_registro"]})
    titulares = defaultdict(lambda: {"registros": 0, "situacoes": Counter(), "modelos": set(), "cnpj": None})
    fabricantes = defaultdict(lambda: {"registros": 0, "paises": Counter(), "titulares": set()})
    for r in results:
        t = titulares[r["empresa"] or "—"]
        t["registros"] += 1
        t["situacoes"][r.get("situacao") or "—"] += 1
        t["modelos"].add(r.get("modelo"))
        t["cnpj"] = t["cnpj"] or r.get("cnpj")
        if r.get("fabricante"):
            f = fabricantes[r["fabricante"]]
            f["registros"] += 1
            f["paises"][r.get("pais_fabricante") or "—"] += 1
            f["titulares"].add(r["empresa"])
    return {"tabela": rows,
            "titulares": sorted([{"empresa": k, "cnpj": v["cnpj"], "registros": v["registros"], "modelos": len(v["modelos"]),
                                  "situacoes": dict(v["situacoes"])} for k, v in titulares.items()], key=lambda x: -x["registros"])[:50],
            "fabricantes": sorted([{"fabricante": k, "registros": v["registros"], "paises": dict(v["paises"]),
                                    "titulares_distintos": len(v["titulares"])} for k, v in fabricantes.items()],
                                  key=lambda x: -x["registros"])[:50],
            "situacoes": dict(Counter(r.get("situacao") or "—" for r in results)),
            "avisos": ["Quantidade de registros não é participação de mercado.",
                       "Empresas encontradas não têm, necessariamente, interesse em fornecer.",
                       "Titular, fabricante e organismo certificador são papéis diferentes."]}


# ------------------------------------------------------------------------------------------------- comparação (seção 20)
WIRELESS = re.compile(r"\b(bluetooth|wi ?fi|wifi|zigbee|nfc|lora|rf|radio|wireless|sem fio)\b")


def compare(spec: dict, record: dict) -> dict:
    """Compara especificações informadas com UM registro oficial. Nunca afirma equivalência técnica: o resultado é o
    tipo de correspondência documental + o que coincide, difere ou falta."""
    same, diff, missing = [], [], []

    def chk(nome, a, b, eq=None):
        if not a:
            return
        if not b:
            missing.append({"caracteristica": nome, "informado": a, "registro": None, "nota": "não consta no registro oficial"})
            return
        ok = eq(a, b) if eq else norm(a) == norm(b)
        (same if ok else diff).append({"caracteristica": nome, "informado": a, "registro": b})
    chk("Modelo", spec.get("modelo"), record.get("modelo"), lambda a, b: model_key(a) == model_key(b))
    chk("Fabricante", spec.get("fabricante"), record.get("fabricante"), lambda a, b: norm(a).split()[0] in norm(b))
    chk("Marca", spec.get("marca"), record.get("marca") or record.get("nome_comercial"), lambda a, b: norm(a).split()[0] in norm(b))
    chk("Certificado informado pelo fornecedor", spec.get("certificado"), record.get("certificado") or record.get("registro"),
        lambda a, b: re.sub(r"\W", "", a).lower() == re.sub(r"\W", "", b).lower())
    if spec.get("comunicacao_sem_fio") or spec.get("tecnologia"):
        tech = " ".join(filter(None, [spec.get("comunicacao_sem_fio"), spec.get("tecnologia")]))
        reg_t = norm(" ".join(filter(None, [record.get("tipo_produto"), record.get("nome_comercial")])))
        if WIRELESS.search(norm(tech)):
            rad = "radiacao restrita" in reg_t or "transceptor" in reg_t or WIRELESS.search(reg_t)
            (same if rad else diff).append({"caracteristica": "Comunicação sem fio", "informado": tech,
                                            "registro": record.get("tipo_produto")})
    for k, nome in (("potencia", "Potência"), ("tensao", "Tensão"), ("frequencia", "Frequência"), ("componentes", "Componentes")):
        if spec.get(k):
            missing.append({"caracteristica": nome, "informado": spec[k], "registro": None,
                            "nota": "os dados abertos não publicam esta característica — confirmar no certificado/relatório de ensaio"})
    c, why = classify(record, spec)
    if diff and c == EXACT:
        c, why = PROBABLE, "modelo idêntico, mas há características divergentes"
    return {"tipo_correspondencia": c, "rotulo": MATCH_LABEL[c], "motivo": why, "coincidentes": same, "diferentes": diff,
            "faltantes": missing, "fonte": record.get("fonte") or record.get("orgao"), "registro": record.get("registro"),
            "id_registro": record.get("id_registro"),
            "conclusao": ("Correspondência documental do modelo — NÃO é declaração de equivalência técnica. Confirme o certificado "
                          "e o escopo no sistema oficial." if c == EXACT else
                          "Não há evidência suficiente para afirmar que o produto informado é o mesmo do registro."),
            "limitacoes": LIMITS}
