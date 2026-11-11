"""Esquema compartilhado da suíte (criação idempotente; nenhuma tabela existente é alterada ou apagada).

Reaproveita: catalog_products/product_aliases (catálogo), market_listings (anúncios e histórico de preços),
search_observations (palavras-chave observadas), market_series (comércio exterior), suppliers (cadastro antigo,
copiado para companies sem apagar), anatel/inmetro_registros (relações regulatórias documentadas), investigations."""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS companies (
        company_id INTEGER PRIMARY KEY AUTOINCREMENT, legal_name TEXT NOT NULL, display_name TEXT, norm_name TEXT NOT NULL,
        country TEXT, city TEXT, address TEXT, website TEXT, company_type TEXT NOT NULL DEFAULT 'desconhecido',
        business_categories TEXT, product_families TEXT, contact TEXT, notes TEXT, source TEXT NOT NULL,
        verification_status TEXT NOT NULL DEFAULT 'não verificado', legacy_supplier_id INTEGER UNIQUE, last_updated TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_companies_norm ON companies(norm_name, country)",
    """CREATE TABLE IF NOT EXISTS company_aliases (company_id INTEGER NOT NULL, alias TEXT NOT NULL, norm TEXT NOT NULL, source TEXT,
        PRIMARY KEY (company_id, norm))""",
    """CREATE TABLE IF NOT EXISTS company_merge_review (id INTEGER PRIMARY KEY AUTOINCREMENT, a_id INTEGER, b_id INTEGER,
        score REAL, motivos TEXT, estado TEXT NOT NULL DEFAULT 'pendente', decidido_em TEXT, UNIQUE (a_id, b_id))""",
    """CREATE TABLE IF NOT EXISTS supplier_products (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL,
        product_id TEXT, family TEXT, description TEXT, relation TEXT NOT NULL, evidence TEXT, source TEXT NOT NULL,
        created_at TEXT NOT NULL, UNIQUE (company_id, product_id, family, relation, source))""",
    """CREATE TABLE IF NOT EXISTS trade_shipments (id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL UNIQUE,
        doc_id TEXT, source TEXT NOT NULL, exporter_id INTEGER, importer_id INTEGER, exporter_name TEXT, importer_name TEXT,
        consignee TEXT, origin_country TEXT, destination_country TEXT, port TEXT, date TEXT, description TEXT, quantity REAL,
        unit TEXT, weight_kg REAL, containers TEXT, hs_code TEXT, source_url TEXT, raw TEXT, imported_at TEXT NOT NULL,
        duplicates INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS idx_ship_exp ON trade_shipments(exporter_id, date)",
    """CREATE TABLE IF NOT EXISTS trade_relationships (id INTEGER PRIMARY KEY AUTOINCREMENT, a_id INTEGER NOT NULL, b_id INTEGER NOT NULL,
        rel_type TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL, evidence TEXT, period_start TEXT, period_end TEXT,
        confidence TEXT NOT NULL, n_records INTEGER NOT NULL DEFAULT 1, UNIQUE (a_id, b_id, rel_type, source))""",
    """CREATE TABLE IF NOT EXISTS supplier_evaluations (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL,
        dimensao TEXT NOT NULL, campo TEXT NOT NULL, valor TEXT, tipo TEXT NOT NULL, fonte TEXT, documento TEXT, criado_em TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS product_images (image_id INTEGER PRIMARY KEY AUTOINCREMENT, sha256 TEXT NOT NULL, phash TEXT,
        dhash TEXT, ahash TEXT, color TEXT, width INTEGER, height INTEGER, label TEXT, product_id TEXT, family TEXT, source TEXT NOT NULL,
        stored_path TEXT, embedding BLOB, created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_img_sha ON product_images(sha256)",
    """CREATE TABLE IF NOT EXISTS research_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, query TEXT NOT NULL,
        params TEXT, status TEXT NOT NULL, steps TEXT, result TEXT, product_id TEXT, created_at TEXT NOT NULL, finished_at TEXT,
        saved INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS research_evidence (evidence_id TEXT PRIMARY KEY, research_id INTEGER, entity_type TEXT NOT NULL,
        entity_id TEXT, source TEXT NOT NULL, source_record_id TEXT, indicator TEXT NOT NULL, value TEXT, unit TEXT, country TEXT,
        period_start TEXT, period_end TEXT, collected_at TEXT, source_url TEXT, source_capability TEXT, confidence TEXT,
        quality_status TEXT, usage_restrictions TEXT, origin TEXT NOT NULL DEFAULT 'REAL')""",
    """CREATE TABLE IF NOT EXISTS monitored (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, ref TEXT NOT NULL, label TEXT,
        created_at TEXT NOT NULL, last_checked TEXT, last_snapshot TEXT, notes TEXT, params TEXT, UNIQUE (kind, ref))""",
    """CREATE TABLE IF NOT EXISTS import_scenarios (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, product_id TEXT, company_id INTEGER,
        params TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS provider_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, endpoint TEXT,
        cost REAL NOT NULL DEFAULT 0, credits_remaining REAL, at TEXT NOT NULL, ok INTEGER NOT NULL, detail TEXT)""",
]

LEGAL = re.compile(r"\b(co|company|corp|corporation|inc|incorporated|ltd|limited|llc|plc|gmbh|sa|s\.a|ltda|eireli|me|epp|"
                   r"industrial|industry|industries|international|intl|trading|technology|technologies|tech|electronic|electronics|"
                   r"manufacturing|mfg|group|holdings?|import|export|imp|exp|e|and|&|of|the|cia|comercio|comercial|industria)\b")
ZH_LEGAL = re.compile(r"(有限公司|有限责任公司|股份有限公司|公司|集团|科技|电子|实业|贸易|进出口)")
TYPES = ["fabricante", "trading company", "exportador", "importador", "distribuidor", "fornecedor", "transportador", "desconhecido"]


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def ensure(db):
    for s in SCHEMA:
        db.execute(s)
    # coluna acrescentada na revisão do PR #18 (bancos criados pela 1ª versão da suíte): só ADD COLUMN, sem perda
    if "params" not in {r["name"] for r in db.query("PRAGMA table_info(monitored)")}:
        db.execute("ALTER TABLE monitored ADD COLUMN params TEXT")
    _migrate_legacy_suppliers(db)


def norm_company(name: str) -> str:
    """Normalização para COMPARAR nomes (nunca para fundir automaticamente)."""
    t = ZH_LEGAL.sub(" ", name or "")
    t = "".join(c for c in unicodedata.normalize("NFKD", t.lower()) if not unicodedata.combining(c))
    t = re.sub(r"\bs\.\s?a\.?(?=\s|$)", " sa ", t)
    t = re.sub(r"[^\w\s&]", " ", t)
    t = LEGAL.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def _migrate_legacy_suppliers(db):
    """Cópia (não move) do cadastro antigo `suppliers` para o cadastro canônico — o antigo continua funcionando."""
    try:
        rows = db.query("SELECT s.* FROM suppliers s LEFT JOIN companies c ON c.legacy_supplier_id = s.id WHERE c.company_id IS NULL")
    except Exception:  # noqa: BLE001
        return
    for r in rows:
        db.execute("INSERT INTO companies (legal_name, display_name, norm_name, country, city, address, website, company_type, "
                   "business_categories, product_families, contact, notes, source, verification_status, legacy_supplier_id, last_updated) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, 'fornecedor', NULL, ?, ?, ?, ?, 'informado pelo usuário', ?, ?)",
                   (r["nome"], r.get("nome_local") or r["nome"], norm_company(r["nome"]), r.get("pais"), r.get("cidade"), r.get("provincia"),
                    r.get("site"), json.dumps([p.strip() for p in (r.get("produtos") or "").split(",") if p.strip()], ensure_ascii=False),
                    r.get("contato"), r.get("observacoes"), r.get("fonte") or "cadastro anterior", r["id"], now()))


def evidence_id(source: str, record: str, indicator: str, entity: str) -> str:
    return hashlib.sha1(f"{source}|{record}|{indicator}|{entity}".encode()).hexdigest()[:24]


def add_evidence(db, research_id: int | None, ev: dict) -> str:
    """Registro rastreável. A MESMA observação (fonte + registro + indicador + entidade) é gravada uma vez só, mesmo que
    alimente várias dimensões da avaliação — evita contar a mesma evidência como independente."""
    eid = evidence_id(ev["source"], str(ev.get("source_record_id") or ""), ev["indicator"], str(ev.get("entity_id") or ""))
    db.execute("INSERT INTO research_evidence (evidence_id, research_id, entity_type, entity_id, source, source_record_id, indicator, value, "
               "unit, country, period_start, period_end, collected_at, source_url, source_capability, confidence, quality_status, "
               "usage_restrictions, origin) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
               "ON CONFLICT(evidence_id) DO UPDATE SET research_id = excluded.research_id, value = excluded.value, "
               "collected_at = excluded.collected_at",
               (eid, research_id, ev["entity_type"], ev.get("entity_id"), ev["source"], ev.get("source_record_id"), ev["indicator"],
                None if ev.get("value") is None else str(ev["value"]), ev.get("unit"), ev.get("country"), ev.get("period_start"),
                ev.get("period_end"), ev.get("collected_at") or now(), ev.get("source_url"), ev.get("source_capability"),
                ev.get("confidence"), ev.get("quality_status") or "validada", ev.get("usage_restrictions"), ev.get("origin") or "REAL"))
    return eid


def settings(store) -> dict:
    base = {"pais_padrao": "BR", "idioma": "pt", "periodo_meses": 12, "modo": "rapida", "usar_cache": True,
            "imagens_local": True, "modelos_opcionais": False, "sem_custos": True, "orcamento_creditos": 0,
            "aprovar_creditos": True, "max_consultas_simultaneas": 2}
    # orçamento só vale quando o modo sem custos externos está DESLIGADO (verificado em cada consulta paga)
    try:
        s = store.load_result("suite:config") or {}
    except Exception:  # noqa: BLE001
        s = {}
    base.update({k: v for k, v in s.items() if k in base})
    return base


def save_settings(store, new: dict) -> dict:
    cur = settings(store)
    for k, v in (new or {}).items():
        if k not in cur:
            continue
        if isinstance(cur[k], bool):
            v = bool(v)
        elif isinstance(cur[k], int) and not isinstance(cur[k], bool):
            try:
                v = max(0, int(float(v)))
            except (TypeError, ValueError):
                continue
        else:
            v = str(v)[:40]
        cur[k] = v
    if cur["periodo_meses"] not in (3, 6, 12, 24):
        cur["periodo_meses"] = 12
    if cur["modo"] not in ("rapida", "completa"):
        cur["modo"] = "rapida"
    store.save_result("suite:config", cur)
    return cur
