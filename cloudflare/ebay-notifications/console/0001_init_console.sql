CREATE TABLE IF NOT EXISTS ebay_notifications ( notification_id TEXT PRIMARY KEY, topic TEXT NOT NULL, schema_version TEXT, ebay_user_id TEXT, ebay_username TEXT, event_date TEXT, publish_date TEXT, publish_attempts INTEGER, received_at TEXT NOT NULL, last_received_at TEXT NOT NULL, times_received INTEGER NOT NULL DEFAULT 1, validated_at TEXT, status TEXT NOT NULL CHECK (status IN ('RECEIVED','VALIDATED','PENDING','PROCESSING','COMPLETED','FAILED','RETRY_SCHEDULED')), attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, processing_started_at TEXT, processed_at TEXT, completed_at TEXT, result TEXT CHECK (result IS NULL OR result IN ('DELETED','NOT_FOUND','NEEDS_REVIEW','ERROR')) );
CREATE INDEX IF NOT EXISTS idx_ebay_notifications_status ON ebay_notifications (status, received_at);
CREATE TABLE IF NOT EXISTS ebay_public_keys ( kid TEXT PRIMARY KEY, pem TEXT NOT NULL, algorithm TEXT, digest TEXT, fetched_at INTEGER NOT NULL );
CREATE TABLE IF NOT EXISTS sync_nonces ( nonce TEXT PRIMARY KEY, ts INTEGER NOT NULL );
CREATE TABLE IF NOT EXISTS rate_limits ( bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, window_start INTEGER NOT NULL );
CREATE TABLE IF NOT EXISTS audit_log ( id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, notification_id TEXT, detail TEXT );
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log (at);
CREATE TABLE IF NOT EXISTS schema_migrations ( version TEXT PRIMARY KEY, applied_at TEXT NOT NULL );
INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES ('0001_init', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
