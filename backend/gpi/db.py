"""
Camada de persistência local.

Usa DuckDB quando o pacote está disponível (recomendado na especificação) e
SQLite (biblioteca padrão do Python, zero dependências) como alternativa.
O SQL foi escrito no subconjunto comum aos dois motores.
Migrações são versionadas na tabela schema_version.
"""
from __future__ import annotations

import shutil
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

try:  # pragma: no cover - depende do ambiente
    import duckdb  # type: ignore
    ENGINE = "duckdb"
except ImportError:
    import sqlite3
    ENGINE = "sqlite"

MIGRATIONS = [
    # v1 — estrutura inicial
    [
        """CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            is_demo INTEGER NOT NULL DEFAULT 0,
            imported_at TEXT NOT NULL,
            rows_ok INTEGER NOT NULL,
            rows_rejected INTEGER NOT NULL,
            columns_map TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS sales (
            import_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            sku TEXT NOT NULL,
            product TEXT,
            category TEXT,
            quantity DOUBLE NOT NULL,
            unit_price DOUBLE
        )""",
        "CREATE INDEX IF NOT EXISTS idx_sales_sku_date ON sales(sku, date)",
        """CREATE TABLE IF NOT EXISTS forecast_runs (
            id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            sku TEXT NOT NULL,
            freq TEXT NOT NULL,
            horizon INTEGER NOT NULL,
            model TEXT NOT NULL,
            payload TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS app_log (
            ts TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
        )""",
    ],
    # v2 — inteligência de mercado autônoma (Fase 2)
    [
        # Uma série = um indicador de uma fonte para um produto/país (proveniência completa)
        """CREATE TABLE IF NOT EXISTS market_series (
            id INTEGER PRIMARY KEY,
            series_key TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            indicator TEXT NOT NULL,
            kind TEXT NOT NULL,
            product_key TEXT,
            product_name TEXT,
            category TEXT,
            country TEXT,
            unit TEXT,
            currency TEXT,
            freq TEXT NOT NULL,
            origin_url TEXT,
            method TEXT,
            reliability TEXT,
            first_collected TEXT,
            last_collected TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS market_obs (
            series_id INTEGER NOT NULL,
            ref_date TEXT NOT NULL,
            value DOUBLE NOT NULL,
            collected_at TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (series_id, ref_date)
        )""",
        """CREATE TABLE IF NOT EXISTS source_status (
            source TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            message TEXT,
            last_attempt TEXT,
            last_success TEXT,
            validated INTEGER NOT NULL DEFAULT 0,
            records INTEGER NOT NULL DEFAULT 0,
            coverage_start TEXT,
            coverage_end TEXT,
            failures INTEGER NOT NULL DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS sync_jobs (
            job_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            params TEXT NOT NULL,
            state TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            next_try TEXT,
            refresh_after TEXT,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            trigger TEXT NOT NULL,
            state TEXT NOT NULL,
            summary TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS products (
            product_key TEXT PRIMARY KEY,
            name_pt TEXT, name_en TEXT, name_zh TEXT,
            category TEXT,
            origin TEXT NOT NULL,
            hs_codes TEXT,
            discovered_at TEXT NOT NULL,
            norm_tokens TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS auto_forecasts (
            id INTEGER PRIMARY KEY,
            series_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            data_hash TEXT NOT NULL,
            forecast_type TEXT NOT NULL,
            model TEXT,
            status TEXT NOT NULL,
            payload TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_af_series ON auto_forecasts(series_id, id)",
        """CREATE TABLE IF NOT EXISTS analysis_results (
            name TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )""",
    ],
    # v3 — conteúdo (YouTube, Reddit, RSS, notícias) e cotas de API (Fase 3)
    [
        """CREATE TABLE IF NOT EXISTS content_items (
            source TEXT NOT NULL,
            item_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT,
            text TEXT,
            url TEXT,
            author TEXT,
            published_at TEXT,
            lang TEXT,
            category TEXT,
            product_key TEXT,
            query TEXT,
            metrics TEXT,
            collected_at TEXT NOT NULL,
            refreshed_at TEXT NOT NULL,
            sentiment DOUBLE,
            sentiment_label TEXT,
            aspects TEXT,
            target TEXT,
            PRIMARY KEY (source, item_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_content_prod ON content_items(product_key, source)",
        """CREATE TABLE IF NOT EXISTS api_quota (
            provider TEXT NOT NULL, day TEXT NOT NULL, units INTEGER NOT NULL,
            PRIMARY KEY (provider, day)
        )""",
    ],
    # v4 — catálogo canônico de produtos e inteligência de consumo (Fase 4). Só cria tabelas novas:
    # nenhum dado das fases anteriores é alterado ou apagado.
    [
        """CREATE TABLE IF NOT EXISTS catalog_products (
            product_id TEXT PRIMARY KEY,          -- ex.: carregador-usb-c (família) ou carregador-usb-c:65w (variante)
            canonical TEXT NOT NULL,
            name_pt TEXT, name_en TEXT, name_zh TEXT,
            category TEXT NOT NULL,
            family TEXT NOT NULL,
            level TEXT NOT NULL,                  -- produto | variante
            parent_id TEXT,
            attributes TEXT,                      -- JSON
            ncm_hint TEXT,                        -- SH4 apenas quando há fundamento técnico
            wiki_en TEXT,
            origin TEXT NOT NULL,                 -- semente | descoberto
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            evidence INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS idx_cat_family ON catalog_products(family)",
        """CREATE TABLE IF NOT EXISTS product_aliases (
            alias_norm TEXT NOT NULL,
            product_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            lang TEXT NOT NULL,
            PRIMARY KEY (alias_norm, product_id)
        )""",
        """CREATE TABLE IF NOT EXISTS search_observations (
            source TEXT NOT NULL,                 -- google_trends_rss | google_ads_kp | wikimedia | ...
            country TEXT NOT NULL,                -- ISO 3166-1 (BR, US, CN) ou 'GLOBAL:<idioma>'
            region TEXT NOT NULL DEFAULT '',      -- ISO 3166-2 quando a fonte fornece; vazio = país inteiro
            term TEXT NOT NULL,
            ref_date TEXT NOT NULL,
            period TEXT NOT NULL,                 -- dia | semana | mes
            metric TEXT NOT NULL,                 -- trafego_faixa | volume_mensal_aprox | interesse_relativo | visualizacoes
            value DOUBLE NOT NULL,
            value_high DOUBLE,                    -- limite superior quando a fonte informa faixa
            unit TEXT NOT NULL,
            lang TEXT,
            product_id TEXT,
            intent TEXT,
            commercial INTEGER NOT NULL DEFAULT 0,
            url TEXT,
            extra TEXT,
            collected_at TEXT NOT NULL,
            PRIMARY KEY (source, country, region, term, ref_date, metric)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_sobs_prod ON search_observations(product_id, country, metric, ref_date)",
        """CREATE TABLE IF NOT EXISTS discovery_candidates (
            term_norm TEXT PRIMARY KEY,
            term TEXT NOT NULL,
            lang TEXT,
            head TEXT,
            family_hint TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            occurrences INTEGER NOT NULL DEFAULT 0,
            sources TEXT,                         -- JSON {fonte: n}
            countries TEXT,                       -- JSON {país: n}
            intents TEXT,                         -- JSON {intenção: n}
            product_id TEXT,
            status TEXT NOT NULL DEFAULT 'candidato'   -- candidato | promovido | ignorado
        )""",
        """CREATE TABLE IF NOT EXISTS source_metrics (
            run_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            started_at TEXT NOT NULL,
            seconds DOUBLE NOT NULL,
            jobs_ok INTEGER, jobs_failed INTEGER,
            records INTEGER, records_per_s DOUBLE,
            state TEXT,
            PRIMARY KEY (run_id, source)
        )""",
    ],
    # v5 — anúncios de marketplaces (concorrência), registro de modelos e eventos de mudança (v0.5)
    [
        """CREATE TABLE IF NOT EXISTS market_listings (
            source TEXT NOT NULL, item_id TEXT NOT NULL, day TEXT NOT NULL,
            product_id TEXT, query TEXT, title TEXT, brand TEXT, model TEXT, category TEXT,
            price DOUBLE, currency TEXT, original_price DOUBLE, country TEXT, seller TEXT,
            condition TEXT, url TEXT, extra TEXT, collected_at TEXT NOT NULL,
            PRIMARY KEY (source, item_id, day)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_listings_prod ON market_listings(product_id, day)",
        """CREATE TABLE IF NOT EXISTS model_registry (
            model_id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL,
            data_hash TEXT, params TEXT, metrics TEXT, path TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS drift_events (
            series_id TEXT NOT NULL, detector TEXT NOT NULL, ref_date TEXT NOT NULL, direction TEXT,
            detail TEXT, created_at TEXT NOT NULL, PRIMARY KEY (series_id, detector, ref_date)
        )""",
    ],
    # v6 — Centro de Relatórios e inteligência de redes sociais (v0.6). Só tabelas novas.
    [
        """CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL,                 -- identificador da execução (auditoria/reprodução)
            tipo TEXT NOT NULL, formato TEXT NOT NULL, titulo TEXT,
            filtros TEXT, periodo TEXT, pais TEXT,
            created_at TEXT NOT NULL,
            path TEXT, snapshot_path TEXT, size INTEGER,
            status TEXT NOT NULL,                 -- gerado | erro | excluido
            erro TEXT,
            versao_software TEXT, versao_dados TEXT, modelos TEXT, fontes TEXT, parametros TEXT,
            demo INTEGER NOT NULL DEFAULT 0,
            origem TEXT NOT NULL DEFAULT 'manual', -- manual | pagina | automatico | reproducao
            origem_id INTEGER,                    -- relatório reproduzido (quando houver)
            visto INTEGER NOT NULL DEFAULT 1      -- relatórios automáticos começam como não vistos (notificação)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_reports_tipo ON reports(tipo, created_at)",
        """CREATE TABLE IF NOT EXISTS social_observations (
            platform TEXT NOT NULL,               -- tiktok | instagram | facebook | meta_ads | youtube | reddit
            country TEXT NOT NULL,                -- ISO 3166-1, ou 'CONTA' quando a API não informa o país
            item_type TEXT NOT NULL,              -- hashtag | palavra_chave | pagina | anuncios | videos
            item TEXT NOT NULL,                   -- hashtag, palavra-chave ou consulta
            ref_date TEXT NOT NULL,
            period TEXT NOT NULL,                 -- dia | 7d | 30d | 120d | mes
            metric TEXT NOT NULL,                 -- posicao | visualizacoes | publicacoes | curtidas | comentarios | ...
            value DOUBLE NOT NULL,
            unit TEXT NOT NULL,
            product_id TEXT, intent TEXT, commercial INTEGER NOT NULL DEFAULT 0,
            url TEXT, extra TEXT,
            collected_at TEXT NOT NULL,
            retain_until TEXT,                    -- prazo de retenção definido pela política da fonte
            PRIMARY KEY (platform, country, item_type, item, ref_date, period, metric)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_social_prod ON social_observations(product_id, platform, metric, ref_date)",
        """CREATE TABLE IF NOT EXISTS social_quota (
            platform TEXT NOT NULL, item TEXT NOT NULL, first_used TEXT NOT NULL,
            PRIMARY KEY (platform, item)
        )""",
    ],
    # 7 — v0.7: fontes retiradas das integrações ativas. Migração NÃO destrutiva: nenhum dado é apagado;
    # jobs pendentes dessas fontes deixam de ser executados e o estado passa a "removida".
    [
        """CREATE TABLE IF NOT EXISTS removed_sources (
            source TEXT PRIMARY KEY, nome TEXT NOT NULL, motivo TEXT NOT NULL, versao TEXT NOT NULL,
            removida_em TEXT NOT NULL)""",
        "INSERT OR IGNORE INTO removed_sources VALUES ('reclame_aqui', 'Reclame Aqui', 'sem API pública', '0.7', DATE('now'))",
        "INSERT OR IGNORE INTO removed_sources VALUES ('baidu_index', 'Baidu Index', 'sem API pública', '0.7', DATE('now'))",
        "INSERT OR IGNORE INTO removed_sources VALUES ('ocean_engine', 'Ocean Engine / Douyin', 'sem API aberta', '0.7', DATE('now'))",
        "INSERT OR IGNORE INTO removed_sources VALUES ('alibaba', 'Alibaba.com', 'exige app key aprovada', '0.7', DATE('now'))",
        "INSERT OR IGNORE INTO removed_sources VALUES ('alibaba_insights', 'Alibaba / 1688', 'ferramenta paga', '0.7', DATE('now'))",
        "INSERT OR IGNORE INTO removed_sources VALUES ('jd_com', 'JD.com', 'exige empresa registrada na China', '0.7', DATE('now'))",
        "UPDATE sync_jobs SET state = 'removida' WHERE source IN (SELECT source FROM removed_sources) AND state IN ('pending', 'failed', 'running')",
        "UPDATE source_status SET state = 'removida', message = 'fonte descontinuada no GPI v0.7 (dados históricos preservados)' WHERE source IN (SELECT source FROM removed_sources)",
    ],
    # 8 — v0.7: Conformidade de Importação (base regulatória, NCM, homologações, análises, fornecedores, IA local)
    [
        """CREATE TABLE IF NOT EXISTS compliance_docs (
            id TEXT PRIMARY KEY, orgao TEXT NOT NULL, tipo TEXT, numero TEXT, titulo TEXT NOT NULL,
            data_publicacao TEXT, vigencia_inicio TEXT, situacao TEXT NOT NULL, ultima_verificacao TEXT,
            url_oficial TEXT, versao INTEGER NOT NULL DEFAULT 1, hash_sha256 TEXT, status_atualizacao TEXT,
            meta TEXT NOT NULL,                   -- JSON completo do documento (tags, fontes, conflito...)
            texto TEXT NOT NULL, origem TEXT NOT NULL, atualizado_em TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS compliance_doc_history (
            id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL, versao INTEGER NOT NULL, hash_sha256 TEXT,
            situacao TEXT, meta TEXT NOT NULL, texto TEXT NOT NULL, substituido_em TEXT NOT NULL, motivo TEXT)""",
        """CREATE TABLE IF NOT EXISTS compliance_updates (
            id INTEGER PRIMARY KEY, iniciado_em TEXT NOT NULL, concluido_em TEXT, origem TEXT NOT NULL,
            novos INTEGER DEFAULT 0, alterados INTEGER DEFAULT 0, revogados INTEGER DEFAULT 0, falhas INTEGER DEFAULT 0,
            detalhes TEXT)""",
        """CREATE TABLE IF NOT EXISTS compliance_analyses (
            id INTEGER PRIMARY KEY, criado_em TEXT NOT NULL, produto TEXT NOT NULL, product_id TEXT,
            entrada TEXT NOT NULL, resultado TEXT NOT NULL, base_versao TEXT, modo TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_comp_an_prod ON compliance_analyses(product_id, criado_em)",
        """CREATE TABLE IF NOT EXISTS compliance_attachments (
            id INTEGER PRIMARY KEY, analysis_id INTEGER, nome TEXT NOT NULL, tipo TEXT NOT NULL, tamanho INTEGER NOT NULL,
            sha256 TEXT NOT NULL, caminho TEXT NOT NULL, texto_extraido TEXT, criado_em TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS ncm_table (
            codigo TEXT PRIMARY KEY, descricao TEXT NOT NULL, data_inicio TEXT, data_fim TEXT, ato TEXT)""",
        """CREATE TABLE IF NOT EXISTS ncm_meta (k TEXT PRIMARY KEY, v TEXT)""",
        """CREATE TABLE IF NOT EXISTS anatel_homologacoes (
            numero TEXT, fabricante TEXT, modelo TEXT, nome_comercial TEXT, tipo_produto TEXT,
            data_homologacao TEXT, situacao TEXT, solicitante TEXT, extra TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_anatel_num ON anatel_homologacoes(numero)",
        "CREATE INDEX IF NOT EXISTS idx_anatel_mod ON anatel_homologacoes(modelo)",
        """CREATE TABLE IF NOT EXISTS compliance_cert_checks (
            id INTEGER PRIMARY KEY, analysis_id INTEGER, orgao TEXT NOT NULL, consulta TEXT NOT NULL,
            resultado TEXT NOT NULL, evidencia TEXT, verificado_por TEXT NOT NULL, criado_em TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY, nome TEXT NOT NULL, nome_local TEXT, pais TEXT NOT NULL DEFAULT 'CN', cidade TEXT,
            provincia TEXT, site TEXT, contato TEXT, produtos TEXT, certificacoes TEXT, observacoes TEXT,
            fonte TEXT NOT NULL DEFAULT 'informado pelo usuário', criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL)""",
    ],
]


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._tx = threading.local()
        if ENGINE == "duckdb":  # pragma: no cover
            self.con = duckdb.connect(str(self.path))
        else:
            self.con = sqlite3.connect(str(self.path), check_same_thread=False)
            self.con.execute("PRAGMA journal_mode=WAL")
            self.con.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    # -- utilitários -------------------------------------------------------- #
    def execute(self, sql: str, params=()):
        with self.lock:
            cur = self.con.execute(sql, params)
            if not getattr(self._tx, "depth", 0):
                self.con.commit()
            return cur

    def executemany(self, sql: str, rows):
        with self.lock:
            cur = self.con.executemany(sql, rows)
            if not getattr(self._tx, "depth", 0):
                self.con.commit()
            return cur

    @contextmanager
    def transaction(self):
        """Agrupa várias gravações num único commit (no Windows cada commit cria e apaga o diário do
        SQLite, que o antivírus inspeciona — milhares de commits pequenos ficam muito lentos)."""
        with self.lock:
            self._tx.depth = getattr(self._tx, "depth", 0) + 1
            try:
                yield self
            except Exception:
                self._tx.depth -= 1
                if self._tx.depth == 0:
                    self.con.rollback()
                raise
            else:
                self._tx.depth -= 1
                if self._tx.depth == 0:
                    self.con.commit()

    def query(self, sql: str, params=()) -> list[dict]:
        with self.lock:
            cur = self.con.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def query_df(self, sql: str, params=()) -> pd.DataFrame:
        rows = self.query(sql, params)
        return pd.DataFrame(rows)

    def next_id(self, table: str) -> int:
        r = self.query(f"SELECT COALESCE(MAX(id), 0) + 1 AS n FROM {table}")
        return int(r[0]["n"])

    # -- migrações ---------------------------------------------------------- #
    def migrate(self):
        with self.lock:
            self.con.execute("CREATE TABLE IF NOT EXISTS schema_version (v INTEGER NOT NULL)")
            r = self.con.execute("SELECT MAX(v) FROM schema_version").fetchone()
            current = r[0] or 0
            self.pre_migration_backup = None
            if 0 < current < len(MIGRATIONS) and ENGINE == "sqlite":
                # v0.7.1: cópia consistente do banco ANTES de qualquer migração (nada é apagado)
                try:
                    dest = self.path.parent / "backups" / f"gpi_antes_migracao_v{current}_para_v{len(MIGRATIONS)}_{datetime.now():%Y%m%d_%H%M%S}.sqlite"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    b = sqlite3.connect(str(dest))
                    self.con.backup(b)
                    b.close()
                    self.pre_migration_backup = dest
                except Exception:  # noqa: BLE001 — sem espaço/permissão: a migração (não destrutiva) segue
                    pass
            for i, stmts in enumerate(MIGRATIONS, start=1):
                if i <= current:
                    continue
                for s in stmts:
                    self.con.execute(s)
                self.con.execute("INSERT INTO schema_version VALUES (?)", (i,))
            self.con.commit()

    def schema_version(self) -> int:
        return int(self.query("SELECT MAX(v) AS v FROM schema_version")[0]["v"] or 0)

    def insert_sales(self, import_id: int, df: pd.DataFrame):
        rows = [
            (import_id, r.date, r.sku, r.product, r.category, float(r.quantity),
             None if pd.isna(r.unit_price) else float(r.unit_price))
            for r in df.itertuples(index=False)
        ]
        with self.lock:
            self.con.executemany(
                "INSERT INTO sales (import_id, date, sku, product, category, quantity, unit_price)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            self.con.commit()

    def delete_import(self, import_id: int):
        with self.lock:
            self.con.execute("DELETE FROM sales WHERE import_id = ?", (import_id,))
            self.con.execute("DELETE FROM imports WHERE id = ?", (import_id,))
            self.con.commit()

    def backup(self, backup_dir: Path) -> Path:
        backup_dir.mkdir(parents=True, exist_ok=True)
        dest = backup_dir / f"gpi_{datetime.now():%Y%m%d_%H%M%S}{self.path.suffix}"
        with self.lock:
            if ENGINE == "sqlite":
                b = sqlite3.connect(str(dest))
                self.con.backup(b)
                b.close()
            else:  # pragma: no cover
                self.con.execute("CHECKPOINT")
                shutil.copy2(self.path, dest)
        return dest

    def integrity(self) -> dict:
        """v0.7.1: verificação de integridade (somente leitura) e contagem real por tabela."""
        with self.lock:
            ok = [r[0] for r in self.con.execute("PRAGMA integrity_check").fetchall()]
            fk = self.con.execute("PRAGMA foreign_key_check").fetchall()
            tables = [r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE "
                                                     "'sqlite_%' AND name NOT LIKE 'compliance_fts%' ORDER BY name")]
            counts = {t: self.con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
            orphans = self.con.execute("SELECT COUNT(*) FROM market_obs o LEFT JOIN market_series s ON s.id = o.series_id "
                                       "WHERE s.id IS NULL").fetchone()[0]
            jm = self.con.execute("PRAGMA journal_mode").fetchone()[0]
        return {"integridade": ok[0] if len(ok) == 1 else ok[:20], "ok": ok == ["ok"] and not fk and not orphans,
                "chaves_estrangeiras_invalidas": len(fk), "observacoes_orfas": orphans, "journal_mode": jm,
                "versao_esquema": self.schema_version(), "tabelas": counts, "arquivo": self.path.name}

    def close(self):
        with self.lock:
            self.con.close()
