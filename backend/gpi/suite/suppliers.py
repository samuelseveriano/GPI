"""Supplier Intelligence — cadastro canônico de empresas, aliases, normalização, detecção de duplicidades com revisão
manual (NUNCA fusão automática), importação CSV/XLSX validada, embarques com deduplicação, rede de relações com fonte e
grau de comprovação, descoberta de fornecedores por produto, avaliação (documental × declarado × usuário) e correspondência
preliminar produto↔fornecedor.

Fontes gratuitas de relações DOCUMENTADAS: registros Anatel/Inmetro já carregados no GPI (fabricante ↔ titular brasileiro)
e arquivos de embarques que o próprio usuário importa. O Comex Stat é agregado: nunca cria relação nominal entre empresas.
Embarques não indicam capacidade produtiva, unidades vendidas nem exclusividade."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from . import store as S

REL_STATUS = {"documentado": "comprovado por registro de fonte (embarque, homologação, certificado)",
              "declarado": "informado pela própria empresa ou por terceiro, sem documento",
              "inferido": "deduzido pelo GPI a partir de indícios (mesmo site, mesmo endereço) — precisa de verificação",
              "incerto": "indício fraco ou fonte com identificação ambígua"}
EVAL_TYPES = {"documental": "Evidência documental", "declarado": "Informação declarada pelo fornecedor",
              "avaliação": "Avaliação do usuário"}
EVAL_DIMS = ["identificação", "capacidade declarada", "certificações", "qualidade", "comercial", "logística", "comunicação", "riscos"]
COMPANY_FIELDS = {"legal_name": ["legal_name", "razao_social", "razão social", "nome", "empresa", "company", "name", "supplier", "fornecedor"],
                  "display_name": ["display_name", "nome_fantasia", "nome fantasia", "nome_local", "nome local", "local_name"],
                  "country": ["country", "pais", "país"], "city": ["city", "cidade"], "address": ["address", "endereco", "endereço", "provincia", "província"],
                  "website": ["website", "site", "url"], "company_type": ["company_type", "tipo", "type"],
                  "business_categories": ["categorias", "categories", "business_categories"],
                  "product_families": ["produtos", "products", "product_families", "familias", "famílias"],
                  "contact": ["contato", "contact", "email", "telefone"], "notes": ["observacoes", "observações", "notes", "notas"],
                  "aliases": ["aliases", "outros_nomes", "outros nomes", "aka"]}
SHIP_FIELDS = {"doc_id": ["bol", "bill_of_lading", "documento", "doc_id", "bl", "conhecimento"],
               "exporter_name": ["exporter", "exportador", "shipper", "supplier", "fornecedor"],
               "importer_name": ["importer", "importador", "buyer", "comprador", "consignee", "consignee_name", "consignatario", "consignatário"],
               "consignee": ["notify", "notify_party", "notificar"],
               "origin_country": ["origin", "origem", "pais_origem", "país de origem", "origin_country", "country_of_origin"],
               "destination_country": ["destination", "destino", "pais_destino", "destination_country"],
               "port": ["port", "porto", "port_of_unlading", "porto_descarga"], "date": ["date", "data", "arrival_date", "data_chegada"],
               "description": ["description", "descricao", "descrição", "product", "produto", "goods"],
               "quantity": ["quantity", "quantidade", "qty"], "unit": ["unit", "unidade"], "weight_kg": ["weight", "peso", "weight_kg", "peso_kg"],
               "containers": ["container", "containers", "conteiner", "contêiner"], "hs_code": ["hs", "hs_code", "ncm", "sh", "hts"],
               "source_url": ["url", "link", "source_url"]}
MAX_ROWS = 50_000


def _now():
    return S.now()


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    m = re.match(r"^(?:https?://)?(?:www\.)?([^/:?#]+)", url.strip().lower())
    return m.group(1) if m else None


def similarity(a: str, b: str) -> float:
    na, nb = S.norm_company(a), S.norm_company(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / len(ta | tb) if ta | tb else 0
    return round(max(SequenceMatcher(None, na, nb).ratio(), jac), 3)


# --------------------------------------------------------------------------------------------- cadastro
def _row(db, cid):
    r = db.query("SELECT * FROM companies WHERE company_id = ?", (cid,))
    if not r:
        return None
    c = r[0]
    for k in ("business_categories", "product_families"):
        try:
            c[k] = json.loads(c[k] or "[]")
        except ValueError:
            c[k] = [x.strip() for x in str(c[k]).split(",") if x.strip()]
    c["aliases"] = [a["alias"] for a in db.query("SELECT alias FROM company_aliases WHERE company_id = ?", (cid,))]
    return c


def _list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip()[:120] for x in v if str(x).strip()][:50]
    return [x.strip()[:120] for x in re.split(r"[;,|]", str(v)) if x.strip()][:50]


def upsert_company(db, d: dict, source: str) -> dict:
    """Cria a empresa. Nome normalizado IGUAL no mesmo país → mesma empresa (só completa campos vazios). Nome parecido →
    nova empresa + item na fila de revisão de duplicidades (o usuário decide)."""
    S.ensure(db)
    name = str(d.get("legal_name") or "").strip()[:200]
    if not name:
        raise ValueError("nome da empresa é obrigatório")
    country = _iso(d.get("country"))
    ctype = str(d.get("company_type") or "desconhecido").strip().lower()
    if ctype not in S.TYPES:
        ctype = "desconhecido"
    norm = S.norm_company(name) or name.lower()
    # mesmo nome normalizado: mesmo país, ou um dos lados sem país (registro sem país não cria empresa nova)
    ex = db.query("SELECT company_id, country FROM companies WHERE norm_name = ? AND verification_status NOT LIKE 'mesclada%' "
                  "AND (? IS NULL OR country IS NULL OR country = ?) ORDER BY (country = ?) DESC, company_id LIMIT 1",
                  (norm, country, country, country))
    fields = {"display_name": str(d.get("display_name") or "")[:200] or None, "city": str(d.get("city") or "")[:120] or None,
              "address": str(d.get("address") or "")[:300] or None, "website": str(d.get("website") or "")[:300] or None,
              "contact": str(d.get("contact") or "")[:300] or None, "notes": str(d.get("notes") or "")[:2000] or None}
    cats, fams = _list(d.get("business_categories")), _list(d.get("product_families"))
    if ex:
        cid = ex[0]["company_id"]
        cur = _row(db, cid)
        sets = {k: v for k, v in fields.items() if v and not cur.get(k)}
        if country and not cur.get("country"):
            sets["country"] = country
        if ctype != "desconhecido" and cur["company_type"] == "desconhecido":
            sets["company_type"] = ctype
        sets["product_families"] = json.dumps(sorted(set(cur["product_families"]) | set(fams)), ensure_ascii=False)
        sets["business_categories"] = json.dumps(sorted(set(cur["business_categories"]) | set(cats)), ensure_ascii=False)
        sets["last_updated"] = _now()
        db.execute("UPDATE companies SET " + ", ".join(f"{k} = ?" for k in sets) + " WHERE company_id = ?", (*sets.values(), cid))
        created = False
    else:
        cur = db.execute("INSERT INTO companies (legal_name, display_name, norm_name, country, city, address, website, company_type, "
                         "business_categories, product_families, contact, notes, source, verification_status, last_updated) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (name, fields["display_name"] or name, norm, country, fields["city"], fields["address"], fields["website"], ctype,
                          json.dumps(cats, ensure_ascii=False), json.dumps(fams, ensure_ascii=False), fields["contact"], fields["notes"],
                          source[:120], str(d.get("verification_status") or "não verificado")[:60], _now()))
        cid = cur.lastrowid
        created = True
    for a in [name, *(_list(d.get("aliases")))]:
        db.execute("INSERT OR IGNORE INTO company_aliases (company_id, alias, norm, source) VALUES (?, ?, ?, ?)",
                   (cid, a[:200], S.norm_company(a) or a.lower(), source[:120]))
    if created:
        _queue_duplicates(db, cid)
    return {"company_id": cid, "criada": created}


def _queue_duplicates(db, cid: int, threshold: float = 0.82):
    me = _row(db, cid)
    dom = _domain(me.get("website"))
    for o in db.query("SELECT company_id, legal_name, country, website FROM companies WHERE company_id != ? "
                      "AND verification_status NOT LIKE 'mesclada%'", (cid,)):
        s = similarity(me["legal_name"], o["legal_name"])
        why = []
        if s >= threshold:
            why.append(f"nomes parecidos (similaridade {s:.2f})")
        if dom and dom == _domain(o["website"]):
            why.append(f"mesmo site ({dom})")
            s = max(s, 0.9)
        if not why:
            continue
        if me.get("country") and o.get("country") and me["country"] != o["country"]:
            why.append("ATENÇÃO: países diferentes")
        a, b = sorted((cid, o["company_id"]))
        db.execute("INSERT OR IGNORE INTO company_merge_review (a_id, b_id, score, motivos) VALUES (?, ?, ?, ?)",
                   (a, b, s, json.dumps(why, ensure_ascii=False)))


def search_companies(db, q: str = "", ctype: str | None = None, country: str | None = None, limit: int = 200) -> list[dict]:
    S.ensure(db)
    rows = db.query("SELECT company_id, legal_name, display_name, country, city, company_type, product_families, source, "
                    "verification_status, last_updated FROM companies WHERE verification_status NOT LIKE 'mesclada%'")
    out = []
    qn = S.norm_company(q) if q else ""
    alias = defaultdict(list)
    for a in db.query("SELECT company_id, norm FROM company_aliases"):
        alias[a["company_id"]].append(a["norm"])
    for r in rows:
        if ctype and r["company_type"] != ctype:
            continue
        if country and (r["country"] or "") != country.upper():
            continue
        score = 1.0
        if qn:
            cands = [S.norm_company(r["legal_name"]), *alias[r["company_id"]], (r["product_families"] or "").lower()]
            score = max((1.0 if qn in c else SequenceMatcher(None, qn, c).ratio()) for c in cands if c) if any(cands) else 0
            if score < 0.6:
                continue
        r["product_families"] = json.loads(r["product_families"] or "[]")
        r["correspondencia"] = round(score, 2)
        out.append(r)
    out.sort(key=lambda x: (-x["correspondencia"], x["legal_name"].lower()))
    return out[:limit]


def merge_queue(db, state: str = "pendente") -> list[dict]:
    S.ensure(db)
    rows = db.query("SELECT * FROM company_merge_review WHERE estado = ? ORDER BY score DESC LIMIT 500", (state,))
    for r in rows:
        r["motivos"] = json.loads(r["motivos"] or "[]")
        r["a"], r["b"] = _row(db, r["a_id"]), _row(db, r["b_id"])
    return [r for r in rows if r["a"] and r["b"]]


def decide_merge(db, rid: int, decision: str) -> dict:
    """'mesclar' = decisão HUMANA: aliases, produtos, embarques, relações e avaliações passam para A; B é marcada como
    mesclada (não é apagada). 'distintas' = as duas continuam separadas e o par não volta para a fila."""
    S.ensure(db)
    r = db.query("SELECT * FROM company_merge_review WHERE id = ?", (rid,))
    if not r:
        raise KeyError("item não encontrado")
    a, b = r[0]["a_id"], r[0]["b_id"]
    if decision == "mesclar":
        with db.transaction():
            db.execute("INSERT OR IGNORE INTO company_aliases (company_id, alias, norm, source) "
                       "SELECT ?, alias, norm, source FROM company_aliases WHERE company_id = ?", (a, b))
            db.execute("UPDATE OR IGNORE supplier_products SET company_id = ? WHERE company_id = ?", (a, b))
            db.execute("UPDATE trade_shipments SET exporter_id = ? WHERE exporter_id = ?", (a, b))
            db.execute("UPDATE trade_shipments SET importer_id = ? WHERE importer_id = ?", (a, b))
            db.execute("UPDATE OR IGNORE trade_relationships SET a_id = ? WHERE a_id = ?", (a, b))
            db.execute("UPDATE OR IGNORE trade_relationships SET b_id = ? WHERE b_id = ?", (a, b))
            db.execute("UPDATE supplier_evaluations SET company_id = ? WHERE company_id = ?", (a, b))
            db.execute("UPDATE companies SET verification_status = ?, last_updated = ? WHERE company_id = ?", (f"mesclada em {a}", _now(), b))
            db.execute("UPDATE company_merge_review SET estado = 'mesclada', decidido_em = ? WHERE id = ?", (_now(), rid))
    elif decision == "distintas":
        db.execute("UPDATE company_merge_review SET estado = 'distintas', decidido_em = ? WHERE id = ?", (_now(), rid))
    else:
        raise ValueError("decisão deve ser 'mesclar' ou 'distintas'")
    return {"ok": True, "decisao": decision}


# --------------------------------------------------------------------------------------------- importação de arquivos
def read_table(raw: bytes, filename: str) -> list[dict]:
    """CSV ou XLSX, validado pelo CONTEÚDO. XLSX com macros é recusado; fórmulas são lidas como valores (nada é executado)."""
    if not raw:
        raise ValueError("arquivo vazio")
    if raw[:4] == b"PK\x03\x04":
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as e:
            raise ValueError("planilha corrompida") from e
        names = zf.namelist()
        if "xl/workbook.xml" not in names:
            raise ValueError("arquivo ZIP não é uma planilha XLSX")
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise ValueError("planilha com macros recusada (salve como .xlsx sem macros)")
        if sum(i.file_size for i in zf.infolist()) > 200 * 1024 * 1024:
            raise ValueError("planilha descompactada grande demais")
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header = [str(h or "").strip() for h in next(it, [])]
        rows = []
        for i, vals in enumerate(it):
            if i >= MAX_ROWS:
                break
            if vals and any(v not in (None, "") for v in vals):
                rows.append({header[j]: ("" if v is None else str(v)) for j, v in enumerate(vals) if j < len(header) and header[j]})
        wb.close()
        return rows
    if b"\x00" in raw[:4096]:
        raise ValueError("arquivo binário não reconhecido (envie CSV ou XLSX)")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for i, r in enumerate(csv.DictReader(io.StringIO(text), dialect=dialect)):
        if i >= MAX_ROWS:
            break
        rows.append({str(k or "").strip(): (v or "").strip() for k, v in r.items() if k})
    return rows


def _map(row: dict, spec: dict) -> dict:
    low = {re.sub(r"\s+", " ", k.strip().lower()): v for k, v in row.items()}
    out = {}
    for f, names in spec.items():
        for n in names:
            if n in low and str(low[n]).strip():
                out[f] = str(low[n]).strip()
                break
    return out


def _clean_text(v: str) -> str:
    v = str(v or "").strip()
    return v.lstrip("=+-@\t\r") if v[:1] in "=+-@\t\r" and not re.match(r"^-?\d", v) else v


def import_companies(db, raw: bytes, filename: str, source: str | None = None) -> dict:
    rows = read_table(raw, filename)
    rep = {"linhas": len(rows), "criadas": 0, "atualizadas": 0, "rejeitadas": [], "fonte": source or f"arquivo do usuário ({filename[:80]})"}
    with db.transaction():
        for i, r in enumerate(rows, 2):
            m = {k: _clean_text(v) for k, v in _map(r, COMPANY_FIELDS).items()}
            if not m.get("legal_name"):
                rep["rejeitadas"].append({"linha": i, "motivo": "sem nome da empresa"})
                continue
            res = upsert_company(db, m, rep["fonte"])
            rep["criadas" if res["criada"] else "atualizadas"] += 1
    rep["rejeitadas"] = rep["rejeitadas"][:200]
    rep["revisao_duplicidades"] = len(merge_queue(db))
    return rep


def _num(v):
    if v in (None, ""):
        return None
    t = re.sub(r"[^\d,.\-]", "", str(v))
    if t.count(",") and t.count("."):
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif t.count(","):
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _date(v):
    from datetime import datetime
    s = str(v or "").strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], f).date().isoformat()
        except ValueError:
            continue
    return None


def fingerprint(source: str, s: dict) -> str:
    if s.get("doc_id"):
        key = f"{source}|doc|{s['doc_id'].strip().upper()}"
    else:
        key = "|".join(str(x or "").strip().lower() for x in (source, S.norm_company(s.get("exporter_name") or ""),
                                                              S.norm_company(s.get("importer_name") or ""), s.get("date"),
                                                              re.sub(r"\s+", " ", (s.get("description") or "").lower())[:200],
                                                              s.get("quantity"), s.get("weight_kg")))
    return hashlib.sha1(key.encode()).hexdigest()


def add_shipments(db, items: list[dict], source: str) -> dict:
    """Grava embarques com deduplicação (mesmo documento, ou mesma combinação exportador/importador/data/descrição/peso).
    Exportador e importador viram empresas do cadastro (mesmo nome normalizado = mesma empresa; parecido = fila de revisão)."""
    S.ensure(db)
    rep = {"novos": 0, "duplicados": 0, "rejeitados": [], "relacoes": 0}
    with db.transaction():
        for i, s in enumerate(items, 2):
            s = {k: _clean_text(v) if isinstance(v, str) else v for k, v in s.items()}
            if not (s.get("exporter_name") or s.get("importer_name")) or not (s.get("description") or s.get("doc_id")):
                rep["rejeitados"].append({"linha": i, "motivo": "faltam empresa (exportador/importador) e descrição ou documento"})
                continue
            s["date"] = _date(s.get("date")) if s.get("date") else None
            s["quantity"], s["weight_kg"] = _num(s.get("quantity")), _num(s.get("weight_kg"))
            fp = fingerprint(source, s)
            if db.query("SELECT 1 FROM trade_shipments WHERE fingerprint = ?", (fp,)):
                db.execute("UPDATE trade_shipments SET duplicates = duplicates + 1 WHERE fingerprint = ?", (fp,))
                rep["duplicados"] += 1
                continue
            exp = upsert_company(db, {"legal_name": s["exporter_name"], "country": s.get("origin_country"), "company_type": "exportador"},
                                 source)["company_id"] if s.get("exporter_name") else None
            imp = upsert_company(db, {"legal_name": s["importer_name"], "country": s.get("destination_country"), "company_type": "importador"},
                                 source)["company_id"] if s.get("importer_name") else None
            db.execute("INSERT INTO trade_shipments (fingerprint, doc_id, source, exporter_id, importer_id, exporter_name, importer_name, consignee, "
                       "origin_country, destination_country, port, date, description, quantity, unit, weight_kg, containers, hs_code, source_url, raw, "
                       "imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (fp, s.get("doc_id"), source[:120], exp, imp, s.get("exporter_name"), s.get("importer_name"), s.get("consignee"),
                        s.get("origin_country"), s.get("destination_country"), s.get("port"), s["date"], (s.get("description") or "")[:1000],
                        s["quantity"], s.get("unit"), s["weight_kg"], s.get("containers"), s.get("hs_code"), s.get("source_url"),
                        json.dumps({k: v for k, v in s.items() if k not in ("raw",)}, ensure_ascii=False, default=str)[:4000], _now()))
            rep["novos"] += 1
            if exp and imp:
                _relate_from_shipments(db, exp, imp, source)
                rep["relacoes"] += 1
    rep["rejeitados"] = rep["rejeitados"][:200]
    return rep


def import_shipments(db, raw: bytes, filename: str, source: str | None = None) -> dict:
    rows = read_table(raw, filename)
    src = source or f"arquivo de embarques do usuário ({filename[:80]})"
    rep = add_shipments(db, [_map(r, SHIP_FIELDS) for r in rows], src)
    rep.update({"linhas": len(rows), "fonte": src})
    return rep


def _relate_from_shipments(db, a, b, source):
    st = db.query("SELECT COUNT(*) AS n, MIN(date) AS i, MAX(date) AS f FROM trade_shipments WHERE exporter_id = ? AND importer_id = ? "
                  "AND source = ?", (a, b, source))[0]
    conf = "alta" if st["n"] >= 3 else "média" if st["n"] >= 2 else "baixa"
    db.execute("INSERT INTO trade_relationships (a_id, b_id, rel_type, status, source, evidence, period_start, period_end, confidence, n_records) "
               "VALUES (?, ?, 'exportou para', 'documentado', ?, ?, ?, ?, ?, ?) ON CONFLICT(a_id, b_id, rel_type, source) DO UPDATE SET "
               "n_records = excluded.n_records, period_start = excluded.period_start, period_end = excluded.period_end, "
               "confidence = excluded.confidence, evidence = excluded.evidence",
               (a, b, source, f"{st['n']} embarque(s) registrado(s) na fonte", st["i"], st["f"], conf, st["n"]))


def add_relationship(db, a: int, b: int, rel_type: str, status: str, source: str, evidence: str | None = None,
                     period_start: str | None = None, period_end: str | None = None, confidence: str | None = None) -> dict:
    S.ensure(db)
    if status not in REL_STATUS:
        raise ValueError("status deve ser: " + ", ".join(REL_STATUS))
    if status == "documentado" and not evidence:
        raise ValueError("relação documentada exige a evidência (documento, registro, embarque)")
    if not (_row(db, a) and _row(db, b)) or a == b:
        raise ValueError("empresas inválidas")
    conf = confidence or {"documentado": "alta", "declarado": "média", "inferido": "baixa", "incerto": "baixa"}[status]
    db.execute("INSERT INTO trade_relationships (a_id, b_id, rel_type, status, source, evidence, period_start, period_end, confidence) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(a_id, b_id, rel_type, source) DO UPDATE SET status = excluded.status, "
               "evidence = excluded.evidence, confidence = excluded.confidence",
               (a, b, rel_type[:80], status, source[:120], (evidence or "")[:1000] or None, period_start, period_end, conf))
    return {"ok": True}


def sync_regulatory_relations(db, limit: int = 20000) -> dict:
    """Relações DOCUMENTADAS gratuitas: fabricante (país informado) ↔ titular brasileiro nos registros Anatel/Inmetro já
    carregados. Papel: 'fabricante declarado no registro de'; não indica exclusividade, volume nem relação comercial ativa."""
    S.ensure(db)
    n = 0
    try:
        an = db.query("SELECT fabricante, pais_fabricante, solicitante, cnpj_solicitante, numero_homologacao, data_homologacao, tipo_produto "
                      "FROM anatel_registros WHERE fabricante IS NOT NULL AND solicitante IS NOT NULL LIMIT ?", (limit,))
    except Exception:  # noqa: BLE001
        an = []
    try:
        im = db.query("SELECT fabricante, razao_social, cnpj, numero_registro, data_registro, objeto FROM inmetro_registros "
                      "WHERE fabricante IS NOT NULL AND razao_social IS NOT NULL LIMIT ?", (limit,))
    except Exception:  # noqa: BLE001
        im = []
    pairs = defaultdict(lambda: {"n": 0, "regs": [], "dates": [], "prods": Counter(), "pais": None})
    for r in an:
        if S.norm_company(r["fabricante"]) == S.norm_company(r["solicitante"]):
            continue
        k = ("Anatel", r["fabricante"].strip(), r["solicitante"].strip())
        p = pairs[k]
        p["n"] += 1
        p["regs"].append(r["numero_homologacao"])
        p["dates"].append(r["data_homologacao"])
        p["prods"][r["tipo_produto"] or "—"] += 1
        p["pais"] = r["pais_fabricante"] or p["pais"]
    for r in im:
        if S.norm_company(r["fabricante"]) == S.norm_company(r["razao_social"]):
            continue
        k = ("Inmetro", r["fabricante"].strip(), r["razao_social"].strip())
        p = pairs[k]
        p["n"] += 1
        p["regs"].append(r["numero_registro"])
        p["dates"].append(r["data_registro"])
        p["prods"][(r["objeto"] or "—")[:60]] += 1
    with db.transaction():
        for (org, fab, tit), p in pairs.items():
            src = f"registros {org}"
            a = upsert_company(db, {"legal_name": fab, "country": _iso(p["pais"]), "company_type": "fabricante",
                                    "product_families": [k for k, _ in p["prods"].most_common(5)]}, src)["company_id"]
            b = upsert_company(db, {"legal_name": tit, "country": "BR", "company_type": "importador"}, src)["company_id"]
            ds = sorted(d for d in p["dates"] if d)
            db.execute("INSERT INTO trade_relationships (a_id, b_id, rel_type, status, source, evidence, period_start, period_end, confidence, "
                       "n_records) VALUES (?, ?, 'fabricante em registro do titular', 'documentado', ?, ?, ?, ?, ?, ?) "
                       "ON CONFLICT(a_id, b_id, rel_type, source) DO UPDATE SET n_records = excluded.n_records, evidence = excluded.evidence, "
                       "period_start = excluded.period_start, period_end = excluded.period_end",
                       (a, b, src, f"{p['n']} registro(s): " + ", ".join(str(x) for x in p["regs"][:5] if x), ds[0] if ds else None,
                        ds[-1] if ds else None, "alta" if p["n"] >= 2 else "média", p["n"]))
            for fam, _ in p["prods"].most_common(3):
                db.execute("INSERT OR IGNORE INTO supplier_products (company_id, product_id, family, description, relation, evidence, source, created_at) "
                           "VALUES (?, NULL, ?, NULL, 'fabricante declarado em registro', ?, ?, ?)", (a, fam, f"{org}", src, _now()))
            n += 1
    return {"relacoes": n, "anatel_registros_lidos": len(an), "inmetro_registros_lidos": len(im),
            "nota": "Fabricante e titular aparecem no mesmo registro regulatório. Não comprova exclusividade, volume, preço nem "
                    "relação comercial vigente."}


ISO = {"china": "CN", "brasil": "BR", "brazil": "BR", "estados unidos": "US", "eua": "US", "usa": "US", "taiwan": "TW", "vietna": "VN",
       "vietnã": "VN", "vietnam": "VN", "india": "IN", "índia": "IN", "coreia do sul": "KR", "japao": "JP", "japão": "JP", "hong kong": "HK",
       "tailandia": "TH", "tailândia": "TH", "malasia": "MY", "malásia": "MY", "indonesia": "ID", "indonésia": "ID", "mexico": "MX", "méxico": "MX"}


def _iso(p):
    if not p:
        return None
    t = str(p).strip()
    return t.upper() if len(t) == 2 else ISO.get(t.lower(), t[:40].upper())


# --------------------------------------------------------------------------------------------- rede, perfil, cobertura
def network(db, cid: int, depth: int = 2) -> dict:
    S.ensure(db)
    seen, frontier, edges = {cid}, {cid}, {}
    for _ in range(max(1, min(depth, 3))):
        nxt = set()
        for n in frontier:
            for r in db.query("SELECT * FROM trade_relationships WHERE a_id = ? OR b_id = ?", (n, n)):
                edges[r["id"]] = r
                for m in (r["a_id"], r["b_id"]):
                    if m not in seen:
                        nxt.add(m)
        seen |= nxt
        frontier = nxt
        if len(seen) > 300:
            break
    nodes = [c for c in (_row(db, n) for n in seen) if c]
    return {"centro": cid, "nos": [{"id": c["company_id"], "nome": c["display_name"] or c["legal_name"], "pais": c["country"],
                                     "tipo": c["company_type"], "fonte": c["source"]} for c in nodes],
            "arestas": [{"de": e["a_id"], "para": e["b_id"], "tipo": e["rel_type"], "status": e["status"], "fonte": e["source"],
                         "evidencia": e["evidence"], "periodo": [e["period_start"], e["period_end"]], "confianca": e["confidence"],
                         "registros": e["n_records"]} for e in edges.values()],
            "legenda": REL_STATUS,
            "avisos": ["Cada ligação mostra a fonte, o tipo e o grau de comprovação.",
                       "Embarques não indicam capacidade produtiva, unidades vendidas nem exclusividade.",
                       "O Comex Stat é agregado por NCM/país e nunca gera relações entre empresas."]}


def profile(db, cid: int) -> dict:
    c = _row(db, cid)
    if not c:
        raise KeyError("empresa não encontrada")
    ships = db.query("SELECT * FROM trade_shipments WHERE exporter_id = ? OR importer_id = ? ORDER BY date DESC LIMIT 200", (cid, cid))
    for s in ships:
        s.pop("raw", None)
    prods = db.query("SELECT * FROM supplier_products WHERE company_id = ?", (cid,))
    evals = db.query("SELECT * FROM supplier_evaluations WHERE company_id = ? ORDER BY criado_em DESC", (cid,))
    by = defaultdict(lambda: defaultdict(list))
    for e in evals:
        by[e["dimensao"]][e["tipo"]].append(e)
    return {"empresa": c, "embarques": ships, "cobertura_embarques": coverage(db, cid), "produtos": prods,
            "avaliacao": {d: {EVAL_TYPES.get(t, t): v for t, v in m.items()} for d, m in by.items()},
            "rede": network(db, cid, 1), "monitorada": bool(db.query("SELECT 1 FROM monitored WHERE kind = 'fornecedor' AND ref = ?", (str(cid),))),
            "regras": ["Informações declaradas pelo fornecedor não são verificadas pelo GPI.",
                       "Tipo de empresa 'desconhecido' até haver evidência (o GPI não presume que exportador seja fabricante)."]}


def coverage(db, cid: int | None = None) -> dict:
    w = " WHERE exporter_id = ? OR importer_id = ?" if cid else ""
    p = (cid, cid) if cid else ()
    rows = db.query("SELECT source, COUNT(*) AS n, MIN(date) AS inicio, MAX(date) AS fim, SUM(duplicates) AS dup, "
                    "GROUP_CONCAT(DISTINCT destination_country) AS destinos FROM trade_shipments" + w + " GROUP BY source", p)
    return {"por_fonte": rows, "total": sum(r["n"] for r in rows),
            "limitacoes": ["Cobertura limitada às fontes importadas: países sem registros públicos de embarques (ex.: Brasil) não aparecem.",
                           "Registros sem nome de empresa (ex.: consignatário oculto) não podem ser atribuídos.",
                           "Quantidade de embarques não é capacidade produtiva nem volume de vendas."]}


def evaluate(db, cid: int, dim: str, campo: str, valor: str, tipo: str, fonte: str | None = None, documento: str | None = None) -> dict:
    S.ensure(db)
    if tipo not in EVAL_TYPES:
        raise ValueError("tipo deve ser: " + ", ".join(EVAL_TYPES))
    if tipo == "documental" and not documento:
        raise ValueError("evidência documental exige a referência do documento")
    if not _row(db, cid):
        raise KeyError("empresa não encontrada")
    db.execute("INSERT INTO supplier_evaluations (company_id, dimensao, campo, valor, tipo, fonte, documento, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
               (cid, dim[:60], campo[:120], str(valor)[:2000], tipo, (fonte or "")[:200] or None, (documento or "")[:300] or None, _now()))
    return {"ok": True}


def link_product(db, cid: int, product_id: str | None, family: str | None, relation: str, source: str, evidence: str | None = None) -> dict:
    S.ensure(db)
    db.execute("INSERT OR IGNORE INTO supplier_products (company_id, product_id, family, description, relation, evidence, source, created_at) "
               "VALUES (?, ?, ?, NULL, ?, ?, ?, ?)", (cid, product_id, family, relation[:80], (evidence or "")[:500] or None, source[:120], _now()))
    return {"ok": True}


# --------------------------------------------------------------------------------------------- descoberta e correspondência
def _terms(text: str) -> list[str]:
    from ..products import nlp
    t = nlp._norm(text or "")
    stop = {"de", "da", "do", "para", "com", "the", "for", "and", "with", "e", "em", "a", "o"}
    return [w for w in t.split() if len(w) >= 3 and w not in stop]


def term_groups(db, query: str, family: str | None = None, product_id: str | None = None) -> list[list[str]]:
    """Grupos de termos equivalentes: a consulta original + nomes do catálogo em pt/en (o mesmo produto escrito em outro
    idioma) mantendo os atributos numéricos da consulta (ex.: 65w). Usado só para ENCONTRAR registros, nunca para criá-los."""
    orig = _terms(query)
    groups = [orig] if orig else []
    ids = [x for x in (product_id, (product_id or "").split(":")[0] or None, family) if x]
    if not ids:
        try:
            from ..intel import understanding as U
            u = U.understand(query, None)
            ids = [x for x in (u.get("produto_id"), (u.get("produto_id") or "").split(":")[0] or None) if x]
        except Exception:  # noqa: BLE001
            ids = []
    nums = [t for t in orig if re.match(r"^\d", t)]
    if ids:
        for r in db.query("SELECT name_pt, name_en FROM catalog_products WHERE product_id IN (%s)" % ",".join("?" * len(ids)), tuple(ids)):
            for n in (r["name_pt"], r["name_en"]):
                g = _terms(n or "")
                if g:
                    g = g + [x for x in nums if x not in g]
                    if g not in groups:
                        groups.append(g)
    return groups


def _hits(text: str, groups: list[list[str]]) -> bool:
    t = (text or "").lower()
    for g in groups:
        need = max(1, -(-len(g) * 3 // 5))
        if sum(1 for w in g if w in t) >= need:
            return True
    return False


def discover(db, query: str, family: str | None = None, product_id: str | None = None, limit: int = 50) -> dict:
    """Fornecedores CANDIDATOS somente a partir de registros existentes: cadastro do usuário, vínculos produto↔empresa,
    descrições de embarques importados e fabricantes em registros Anatel/Inmetro. Nenhum fornecedor é inventado."""
    S.ensure(db)
    terms = _terms(query)
    found: dict[int, dict] = {}

    def add(cid, motivo, fonte, peso):
        c = _row(db, cid)
        if not c or c["verification_status"].startswith("mesclada"):
            return
        f = found.setdefault(cid, {"company_id": cid, "empresa": c["display_name"] or c["legal_name"], "pais": c["country"],
                                   "tipo": c["company_type"], "motivos": [], "fontes": set(), "pontos": 0.0})
        f["motivos"].append(motivo)
        f["fontes"].add(fonte)
        f["pontos"] += peso
    for r in db.query("SELECT * FROM supplier_products"):
        hit = (product_id and r["product_id"] == product_id) or (family and r["family"] and family.lower() in r["family"].lower()) or \
              (terms and r["family"] and all(t in r["family"].lower() for t in terms[:2]))
        if hit:
            add(r["company_id"], f"vínculo '{r['relation']}' com {r['product_id'] or r['family']}", r["source"], 3.0)
    groups = term_groups(db, query, family, product_id)
    for c in db.query("SELECT company_id, product_families, business_categories FROM companies WHERE verification_status NOT LIKE 'mesclada%'"):
        txt = ((c["product_families"] or "") + " " + (c["business_categories"] or "")).lower()
        if groups and _hits(txt, groups):
            add(c["company_id"], "famílias/categorias do cadastro contêm os termos pesquisados", "cadastro", 1.5)
    if terms:
        allt = sorted({w for g in groups for w in g})[:12]
        like = " OR ".join("LOWER(description) LIKE ?" for _ in allt)
        per = defaultdict(lambda: {"n": 0, "ult": None})
        for s in db.query(f"SELECT exporter_id, description, date FROM trade_shipments WHERE exporter_id IS NOT NULL AND ({like}) LIMIT 20000",
                          tuple(f"%{t}%" for t in allt)):
            if _hits(s["description"], groups):
                p = per[s["exporter_id"]]
                p["n"] += 1
                p["ult"] = max(p["ult"] or "", s["date"] or "") or None
        for eid, p in sorted(per.items(), key=lambda kv: -kv[1]["n"])[:100]:
            add(eid, f"{p['n']} embarque(s) com descrição compatível (último {p['ult'] or 'sem data'})", "embarques importados",
                1.0 + min(2.0, p["n"] / 5))
        try:
            from ..regulatory import registry as R
            an = R.search_anatel(db, {"produto": query}, limit=200)["resultados"]
        except Exception:  # noqa: BLE001
            an = []
        fabs = Counter(r.get("fabricante") for r in an if r.get("fabricante"))
        for fab, n in fabs.most_common(30):
            m = db.query("SELECT company_id FROM companies WHERE norm_name = ? LIMIT 1", (S.norm_company(fab),))
            if m:
                add(m[0]["company_id"], f"fabricante em {n} homologação(ões) Anatel com produto compatível", "registros Anatel", 2.0)
            else:
                found[-len(found) - 1] = {"company_id": None, "empresa": fab, "pais": next((r.get("pais_fabricante") for r in an if r.get("fabricante") == fab), None),
                                          "tipo": "fabricante (registro)", "motivos": [f"fabricante em {n} homologação(ões) Anatel (ainda não cadastrado)"],
                                          "fontes": {"registros Anatel"}, "pontos": 2.0}
    out = []
    for f in found.values():
        f["fontes"] = sorted(f["fontes"])
        f["confianca"] = "média" if f["pontos"] >= 3 and len(f["fontes"]) >= 2 else "baixa"
        out.append(f)
    out.sort(key=lambda x: -x["pontos"])
    return {"consulta": query, "termos": terms, "grupos_de_termos": groups if terms else [], "candidatos": out[:limit],
            "aviso": "Candidatos para investigação, não fornecedores confirmados. Presença em registro ou embarque não indica "
                     "interesse em fornecer, capacidade, preço nem qualidade.",
            "vazio": None if out else "Nenhum registro compatível no cadastro, nos embarques importados ou nos registros regulatórios "
                                      "carregados. Importe planilhas de fornecedores/embarques ou carregue as bases Anatel/Inmetro."}


def match_product(db, cid: int, product_id: str | None, family: str | None, query: str | None) -> dict:
    """Correspondência PRELIMINAR produto↔fornecedor com motivos. Não é confirmação de que fabrica o produto."""
    c = _row(db, cid)
    if not c:
        raise KeyError("empresa não encontrada")
    why, pts = [], 0
    links = db.query("SELECT relation, source FROM supplier_products WHERE company_id = ? AND (product_id = ? OR family = ?)",
                     (cid, product_id or "", family or ""))
    for lk in links:
        why.append(f"vínculo registrado: {lk['relation']} ({lk['source']})")
        pts += 3
    terms = _terms(query or family or product_id or "")
    if terms:
        fams = " ".join(c["product_families"] + c["business_categories"]).lower()
        hit = [t for t in terms if t in fams]
        if hit:
            why.append("cadastro menciona: " + ", ".join(hit))
            pts += 1
        groups = term_groups(db, query or family or product_id or "", family, product_id)
        n = sum(1 for r in db.query("SELECT description FROM trade_shipments WHERE exporter_id = ?", (cid,)) if _hits(r["description"], groups))
        if n:
            why.append(f"{n} embarque(s) com descrição compatível")
            pts += 2 if n >= 3 else 1
    docs = db.query("SELECT COUNT(*) AS n FROM supplier_evaluations WHERE company_id = ? AND tipo = 'documental'", (cid,))[0]["n"]
    if docs:
        why.append(f"{docs} evidência(s) documental(is) registradas")
        pts += 1
    conf = "alta" if pts >= 5 else "média" if pts >= 3 else "baixa" if pts else "sem evidência"
    return {"company_id": cid, "empresa": c["legal_name"], "produto": product_id or family or query, "confianca": conf, "motivos": why or
            ["nenhum registro liga esta empresa ao produto"], "pontos": pts, "natureza": "correspondência preliminar — exige verificação"}
