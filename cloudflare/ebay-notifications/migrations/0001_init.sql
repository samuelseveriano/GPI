-- GPI v0.8.2 — banco D1 "gpi-ebay-notifications-db" (binding DB) do Worker gpi-ebay-notifications.
-- Migração 0001: notificações Marketplace Account Deletion, chaves públicas, nonces, auditoria e limites.
-- Idempotente (IF NOT EXISTS): pode ser aplicada no banco existente sem apagar nada.
--
-- Minimização: só o necessário para localizar os dados no GPI (userId e username). eiasToken NÃO é guardado.
-- Quando o GPI confirma a conclusão, userId e username são apagados; ficam apenas datas e situação.

CREATE TABLE IF NOT EXISTS ebay_notifications (
  notification_id   TEXT PRIMARY KEY,                 -- notification.notificationId (idempotência)
  topic             TEXT NOT NULL,                    -- MARKETPLACE_ACCOUNT_DELETION
  schema_version    TEXT,
  ebay_user_id      TEXT,                             -- apagado em COMPLETED
  ebay_username     TEXT,                             -- apagado em COMPLETED
  event_date        TEXT,                             -- quando o usuário pediu a exclusão no eBay
  publish_date      TEXT,
  publish_attempts  INTEGER,                          -- publishAttemptCount informado pelo eBay
  received_at       TEXT NOT NULL,                    -- primeiro recebimento válido
  last_received_at  TEXT NOT NULL,
  times_received    INTEGER NOT NULL DEFAULT 1,       -- duplicatas recebidas (não alteram a situação)
  validated_at      TEXT,
  status            TEXT NOT NULL CHECK (status IN ('RECEIVED','VALIDATED','PENDING','PROCESSING','COMPLETED','FAILED','RETRY_SCHEDULED')),
  attempts          INTEGER NOT NULL DEFAULT 0,       -- tentativas de processamento pelo GPI
  last_error        TEXT,                             -- sanitizado, sem dados pessoais
  processing_started_at TEXT,
  processed_at      TEXT,
  completed_at      TEXT,
  result            TEXT CHECK (result IS NULL OR result IN ('DELETED','NOT_FOUND','NEEDS_REVIEW','ERROR'))
);
CREATE INDEX IF NOT EXISTS idx_ebay_notifications_status ON ebay_notifications (status, received_at);

CREATE TABLE IF NOT EXISTS ebay_public_keys (           -- cache da Notification API getPublicKey (1 h)
  kid        TEXT PRIMARY KEY,
  pem        TEXT NOT NULL,
  algorithm  TEXT,
  digest     TEXT,
  fetched_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_nonces (                -- proteção contra replay das chamadas do GPI
  nonce TEXT PRIMARY KEY,
  ts    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rate_limits (
  bucket       TEXT PRIMARY KEY,
  count        INTEGER NOT NULL,
  window_start INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (                  -- sem dados pessoais
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  at              TEXT NOT NULL,
  actor           TEXT NOT NULL,                        -- ebay | gpi | cron
  action          TEXT NOT NULL,
  notification_id TEXT,
  detail          TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log (at);

CREATE TABLE IF NOT EXISTS schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES ('0001_init', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
