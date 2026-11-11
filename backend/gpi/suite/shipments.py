"""Shipment Intelligence — embarques individuais DOCUMENTADOS e investigação de empresas (importadores/exportadores).

Três modalidades (nenhuma inventa relações):
A. Registros externos autorizados — não há API pública gratuita de todos os conhecimentos de embarque (B/L) dos EUA:
   os manifestos da CBP (AMS) são liberados a terceiros apenas como dados em lote/licença (pedido formal/FOIA ou
   revendedores). Por isso o GPI só consulta o provedor opcional já existente (ImportYeti, pago, desligado por padrão).
B. Importação documental — CSV/XLSX (suppliers.import_shipments) e, aqui, PDFs/textos com B/L, manifestos ou registros
   comerciais obtidos legitimamente pelo usuário (texto extraído localmente, campos por rótulo).
C. Fontes comerciais opcionais — adaptadores do tipo ImportYeti (créditos pagos, autorização explícita).

Estatísticas agregadas (Comex Stat, Census, Comtrade) NUNCA são atribuídas a uma empresa."""
from __future__ import annotations

import io
import math
import re
from collections import Counter, defaultdict

from . import store as S
from . import suppliers as SP

NO_DATA = "Não há registros de embarques individuais disponíveis nas fontes conectadas."
EXTRA_COLS = {"port_lading": "TEXT", "carrier": "TEXT", "cargo_type": "TEXT", "manufacturer": "TEXT", "vessel": "TEXT"}
LABELS = {  # rótulos usuais de B/L e manifestos (inglês/português/espanhol) → campo
    "doc_id": r"(?:bill of lading|b/?l)\s*(?:no\.?|number|n[ºo°])|conhecimento(?: de embarque)?\s*(?:n[ºo°.]*)?|bol\s*(?:no\.?|#)",
    "exporter_name": r"shipper(?:/exporter)?|exporter|exportador|embarcador",
    "importer_name": r"consignee|importer|importador|consignat[áa]rio",
    "consignee": r"notify(?: party)?|notificar",
    "port_lading": r"port of (?:loading|lading)|porto de (?:embarque|carregamento)|puerto de embarque",
    "port": r"port of (?:discharge|unlading)|porto de (?:descarga|destino|chegada)|puerto de descarga",
    "date": r"(?:shipped on board|on board|arrival|shipment|ship(?:ping)?)\s*date|data (?:de )?(?:embarque|chegada)|fecha de embarque",
    "origin_country": r"country of origin|pa[íi]s de origem|origin",
    "destination_country": r"country of destination|pa[íi]s de destino|destination",
    "carrier": r"carrier|transportadora|armador|shipping line",
    "vessel": r"vessel(?:/voyage)?|navio",
    "description": r"description of (?:goods|packages and goods)|goods description|descri[çc][ãa]o (?:da mercadoria|das mercadorias)|commodity",
    "quantity": r"(?:no\.? of |number of )?(?:packages|pieces|quantity|qty)|quantidade|volumes",
    "weight_kg": r"gross weight|net weight|peso (?:bruto|l[íi]quido)|weight",
    "containers": r"container(?:s)?(?: no\.?)?|cont[êe]iner(?:es)?",
    "hs_code": r"hs(?: code)?|hts(?:us)?|ncm|tariff",
    "cargo_type": r"(?:type of )?(?:cargo|service) type|tipo de carga|fcl|lcl",
    "manufacturer": r"manufacturer|fabricante",
}
_LINE = {k: re.compile(rf"^\s*(?:{v})\s*[:#\-]\s*(.+)$", re.I) for k, v in LABELS.items()}


def ensure(db):
    S.ensure(db)
    cols = {r["name"] for r in db.query("PRAGMA table_info(trade_shipments)")}
    for c, t in EXTRA_COLS.items():
        if c not in cols:
            db.execute(f"ALTER TABLE trade_shipments ADD COLUMN {c} {t}")


# ------------------------------------------------------------------------------------------- importação documental (B)
def pdf_text(raw: bytes, max_pages: int = 60) -> str:
    if raw[:5] != b"%PDF-":
        raise ValueError("arquivo não é um PDF")
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(raw))
    if r.is_encrypted:
        raise ValueError("PDF protegido por senha não é lido")
    txt = "\n".join((p.extract_text() or "") for p in r.pages[:max_pages])
    if len(txt.strip()) < 20:
        raise ValueError("PDF sem texto extraível (digitalizado como imagem) — exporte em CSV/XLSX ou use um PDF textual")
    return txt


def _parse_num(t: str) -> float:
    t = t.strip(".,")
    if "," in t and "." in t:
        t = t.replace(",", "") if t.rfind(".") > t.rfind(",") else t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", t) else t.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    return float(t)


def parse_documents(text: str) -> list[dict]:
    """Texto de B/L ou manifesto → registros. Um documento novo começa a cada número de B/L (ou bloco separado por linha
    de traços / quebra de página). Só campos com RÓTULO explícito são preenchidos — nada é deduzido."""
    blocks = re.split(r"\n\s*(?:-{5,}|={5,}|\f)\s*\n|\f", text)
    out = []
    for blk in blocks:
        cur, last = {}, None
        for line in blk.splitlines():
            hit = False
            for k, rx in _LINE.items():
                m = rx.match(line)
                if m:
                    val = m.group(1).strip()
                    if k == "doc_id" and cur.get("doc_id"):          # novo B/L dentro do mesmo bloco
                        out.append(cur)
                        cur = {}
                    if k not in cur:
                        cur[k] = val
                    last, hit = k, True
                    break
            if not hit and last == "description" and line.strip() and len(cur.get("description", "")) < 600:
                cur["description"] += " " + line.strip()             # descrição em várias linhas
            elif not hit:
                last = None
        if cur:
            out.append(cur)
    for r in out:
        if r.get("weight_kg"):
            m = re.search(r"([\d.,]+)\s*(kgs?|kg|lbs?|t)\b", r["weight_kg"], re.I)
            if m:
                v = _parse_num(m.group(1))
                u = m.group(2).lower()
                r["weight_kg"] = round(v * (0.45359237 if u.startswith("lb") else 1000 if u == "t" else 1), 2)
            else:
                r["weight_kg"] = None
        if r.get("quantity"):
            m = re.search(r"([\d.,]+)\s*([A-Za-zÀ-ú]+)?", r["quantity"])
            r["quantity"], r["unit"] = (_parse_num(m.group(1)), (m.group(2) or None)) if m else (None, None)
        if r.get("hs_code"):
            r["hs_code"] = re.sub(r"[^\d.]", "", r["hs_code"])[:13] or None
    return [r for r in out if (r.get("exporter_name") or r.get("importer_name")) and (r.get("description") or r.get("doc_id"))]


def import_document(db, raw: bytes, filename: str, source: str | None = None) -> dict:
    """PDF textual ou .txt com B/L/manifestos → trade_shipments (mesma deduplicação e cadastro de empresas do CSV/XLSX)."""
    ensure(db)
    if raw[:5] == b"%PDF-":
        text = pdf_text(raw)
    else:
        if b"\x00" in raw[:4096]:
            raise ValueError("arquivo binário não suportado (use PDF textual, TXT, CSV ou XLSX)")
        text = raw.decode("utf-8", "replace")
    recs = parse_documents(text)
    src = source or f"documento de embarque do usuário ({filename[:80]})"
    rep = SP.add_shipments(db, recs, src)
    _store_extra(db, recs, src)
    rep.update({"documentos_reconhecidos": len(recs), "fonte": src,
                "campos_por_documento": [sorted(k for k, v in r.items() if v) for r in recs[:20]],
                "aviso": "Campos lidos somente de rótulos explícitos do documento; confira os registros importados."})
    return rep


def _store_extra(db, recs, src):
    for r in recs:
        extra = {c: r.get(c) for c in EXTRA_COLS if r.get(c)}
        if not extra:
            continue
        fp = SP.fingerprint(src, {**r, "date": SP._date(r["date"]) if r.get("date") else None,
                                  "quantity": SP._num(r.get("quantity")), "weight_kg": SP._num(r.get("weight_kg"))})
        sets = ", ".join(f"{c} = COALESCE({c}, ?)" for c in extra)
        db.execute(f"UPDATE trade_shipments SET {sets} WHERE fingerprint = ?", (*extra.values(), fp))


# ------------------------------------------------------------------------------------------- classificação da carga
def classify_cargo(text: str) -> dict:
    """Descrição comercial → produto provável, categoria, características e códigos CANDIDATOS (com confiança)."""
    from ..intel import understanding as U
    from ..products import lexicon as LX
    from ..products import nlp as PN
    from ..products.catalog import NCM_HINT
    from . import naming as NM
    from .trade import EXTRA_SH4
    t = text or ""
    sing = re.sub(r"\b([a-z]{3,})(?:e?s)\b", lambda m: m.group(1) if not m.group(0).endswith("ss") else m.group(0), t.lower())
    u = U.understand(t, "en")
    if not u.get("produto_id"):
        u = U.understand(sing, "en")
    pid = u.get("produto_id")
    head = pid.split("+")[0].split(":")[0] if pid else None
    at = {k: v for k, v in PN.extract_attributes(t).items() if v}
    hs = NCM_HINT.get(head) or EXTRA_SH4.get(head) if head else None
    declared = re.findall(r"\b(\d{4}\.\d{2}(?:\.\d{2,4})?|\d{6,10})\b", t)
    conf = "alta" if u.get("estado") == "confirmada" and at else "média" if pid else "baixa"
    return {"descricao": t[:300], "produto_provavel": NM._from_id(pid.split(":")[0]) if pid else None, "produto_id": pid,
            "categoria": (LX.CONCEPTS.get(head) or (None, None))[1] if head else None, "caracteristicas": at,
            "codigos_candidatos": ([{"codigo": hs, "tipo": "SH4", "confianca": "média", "nota": "posição candidata — validar"}] if hs else []) +
                                  [{"codigo": d, "tipo": "declarado no documento", "confianca": "declarado"} for d in declared[:3]],
            "confianca": conf, "estado": u.get("estado_rotulo") or u.get("estado"),
            "aviso": "Classificação técnica preliminar; código candidato não é classificação fiscal confirmada."}


# ------------------------------------------------------------------------------------------- investigação por empresa
def investigate_company(db, name: str, country: str | None = None) -> dict:
    """Cenário B: identidade → embarques documentados → exportadores → mercadorias → categorias → evolução → evidências."""
    ensure(db)
    q = (name or "").strip()[:200]
    norm = S.norm_company(q)
    if not norm:
        return {"erro": "informe o nome da empresa"}
    cands = SP.search_companies(db, q, None, None, 50)
    exact, similar = [], []
    for c in cands:
        sim = max(SP.similarity(q, c.get("legal_name") or ""), c.get("correspondencia") or 0)
        als = {r["norm"] for r in db.query("SELECT norm FROM company_aliases WHERE company_id = ?", (c["company_id"],))}
        if S.norm_company(c.get("legal_name") or "") == norm or norm in als:
            exact.append({**c, "similaridade": 1.0, "evidencia_identidade": "nome normalizado idêntico (ou alias cadastrado)"})
        elif sim >= 0.6:
            similar.append({**c, "similaridade": round(sim, 2), "evidencia_identidade": "nome parecido — NÃO unido; revise no cadastro"})
    if country:
        exact = [c for c in exact if not c.get("country") or SP._iso(c["country"]) == SP._iso(country)] or exact
    ids = [c["company_id"] for c in exact]
    ships = []
    if ids:
        ph = ",".join("?" * len(ids))
        ships = db.query(f"SELECT * FROM trade_shipments WHERE importer_id IN ({ph}) OR exporter_id IN ({ph}) ORDER BY date",
                         tuple(ids) + tuple(ids))
    base = {"consulta": q, "nome_normalizado": norm, "correspondencias": exact, "nomes_parecidos_nao_unidos": similar[:10],
            "fontes_consultadas": _sources(db)}
    if not ships:
        return {**base, "embarques": [], "resultado": NO_DATA,
                "limitacoes": [NO_DATA, "Estatísticas agregadas (Comex Stat, Census, Comtrade) não identificam empresas e não foram "
                               "atribuídas a esta empresa.", "Para ampliar a cobertura: importe B/L/manifestos (PDF, CSV, XLSX) "
                               "obtidos legitimamente ou habilite um provedor licenciado."]}
    role = {"importador": sum(1 for s in ships if s["importer_id"] in ids), "exportador": sum(1 for s in ships if s["exporter_id"] in ids)}
    partners = Counter()
    for s in ships:
        other = s["exporter_name"] if s["importer_id"] in ids else s["importer_name"]
        if other:
            partners[other] += 1
    tot = sum(partners.values()) or 1
    hhi = round(sum((v / tot) ** 2 for v in partners.values()), 3)
    cls = [classify_cargo(s["description"] or "") for s in ships]
    cats = Counter(c["categoria"] or "não classificada" for c in cls)
    prods = Counter(c["produto_provavel"] for c in cls if c["produto_provavel"])
    by_month = defaultdict(lambda: {"embarques": 0, "kg": 0.0})
    for s in ships:
        k = (s["date"] or "sem data")[:7]
        by_month[k]["embarques"] += 1
        by_month[k]["kg"] += s["weight_kg"] or 0
    periods = sorted(k for k in by_month if k != "sem data")
    evol = None
    if len(periods) >= 2:
        half = len(periods) // 2
        a = sum(by_month[p]["embarques"] for p in periods[:half])
        b = sum(by_month[p]["embarques"] for p in periods[half:])
        evol = {"primeira_metade": a, "segunda_metade": b, "periodo": f"{periods[0]} a {periods[-1]}",
                "nota": "contagem de embarques DOCUMENTADOS importados no GPI — não é o total de embarques da empresa"}
    srcs = Counter(s["source"] for s in ships)
    rows = []
    for s, c in zip(ships, cls):
        rows.append({k: s.get(k) for k in ("id", "doc_id", "date", "exporter_name", "importer_name", "origin_country",
                                             "destination_country", "port_lading", "port", "carrier", "description", "quantity",
                                             "unit", "weight_kg", "hs_code", "source")} | {"classificacao": c})
    conf = "alta" if len(srcs) >= 2 or any(s.get("doc_id") for s in ships) else "média"
    return {**base, "resultado": f"{len(ships)} embarque(s) documentado(s) encontrado(s).", "papel": role,
            "embarques": rows[-500:], "fornecedores_observados" if role["importador"] >= role["exportador"] else "clientes_observados":
            [{"empresa": k, "embarques": v, "participacao_pct": round(100 * v / tot, 1)} for k, v in partners.most_common(20)],
            "concentracao_parceiros_hhi": hhi, "categorias": [{"categoria": k, "embarques": v} for k, v in cats.most_common()],
            "produtos_provaveis": [{"produto": k, "embarques": v} for k, v in prods.most_common(15)],
            "paises_origem": Counter(s["origin_country"] for s in ships if s["origin_country"]).most_common(10),
            "portos": Counter(s["port"] for s in ships if s["port"]).most_common(10),
            "portos_embarque": Counter(s.get("port_lading") for s in ships if s.get("port_lading")).most_common(10),
            "evolucao_mensal": [{"mes": k, **v} for k, v in sorted(by_month.items())], "evolucao": evol,
            "evidencias": [{"fonte": k, "embarques": v} for k, v in srcs.items()], "confianca": conf,
            "limitacoes": ["Somente embarques documentados presentes no GPI (arquivos do usuário e provedores autorizados).",
                           "Fabricante só é informado quando declarado no documento; exportador ≠ fabricante.",
                           "Embarques não indicam vendas, capacidade produtiva nem exclusividade."]}


def _sources(db) -> list[dict]:
    rows = db.query("SELECT source, COUNT(*) AS n, MAX(imported_at) AS ultima FROM trade_shipments GROUP BY source")
    out = [{"fonte": r["source"], "modalidade": "B. importação documental" if "usuário" in r["source"] else "C. provedor opcional"
            if "ImportYeti" in r["source"] else "registro", "registros": r["n"], "ultima": r["ultima"]} for r in rows]
    out.append({"fonte": "CBP / manifestos de carga dos EUA", "modalidade": "A. registros externos",
                "registros": 0, "estado": "Sem API pública gratuita por empresa — dados por licença/pedido formal; importe os arquivos obtidos"})
    return out


def overview(db) -> dict:
    ensure(db)
    n = db.query("SELECT COUNT(*) AS n, COUNT(DISTINCT importer_id) AS imp, COUNT(DISTINCT exporter_id) AS exp, MIN(date) AS i, "
                 "MAX(date) AS f FROM trade_shipments")[0]
    top = db.query("SELECT importer_name AS empresa, COUNT(*) AS embarques FROM trade_shipments WHERE importer_name IS NOT NULL "
                   "GROUP BY importer_id ORDER BY embarques DESC LIMIT 10")
    return {"embarques": n["n"], "importadores": n["imp"], "exportadores": n["exp"], "periodo": [n["i"], n["f"]],
            "principais_importadores": top, "fontes": _sources(db), "vazio": None if n["n"] else NO_DATA}
