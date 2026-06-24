-- 001_initial.sql — KSF Web v2.0 base schema
-- All tables use TEXT for timestamps (ISO 8601 UTC) and INTEGER for booleans (0/1).

CREATE TABLE IF NOT EXISTS _migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);

-- ── Jobs : exécution longue (backup, update, restore, etc.) ────────

CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    command       TEXT NOT NULL,
    args          TEXT,
    status        TEXT NOT NULL CHECK (status IN ('queued','running','success','failed','cancelled','interrupted')),
    pid           INTEGER,
    exit_code     INTEGER,
    output_path   TEXT,
    output_size   INTEGER DEFAULT 0,
    progress_current INTEGER,
    progress_total   INTEGER,
    lock_key      TEXT,
    error         TEXT,
    created_at    TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    triggered_by  TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_lock ON jobs(lock_key) WHERE lock_key IS NOT NULL;

-- ── Notifications : in-app events ─────────────────────────────────

CREATE TABLE IF NOT EXISTS notifications (
    id          TEXT PRIMARY KEY,
    level       TEXT NOT NULL CHECK (level IN ('info','warn','error','critical')),
    category    TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT,
    link        TEXT,
    read_at     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notif_unread ON notifications(read_at, created_at);
CREATE INDEX IF NOT EXISTS idx_notif_created ON notifications(created_at);

-- ── Audit log : traçabilité des actions utilisateur/système ──────

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT,
    before      TEXT,
    after       TEXT,
    job_id      TEXT,
    ip          TEXT,
    ua          TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target);

-- ── Config versions : historique de ksf.env ──────────────────────

CREATE TABLE IF NOT EXISTS config_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL,
    content     TEXT NOT NULL,
    actor       TEXT NOT NULL,
    reason      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_configver_created ON config_versions(created_at);

-- ── Webhook endpoints : delivery des notifications ───────────────

CREATE TABLE IF NOT EXISTS webhook_endpoints (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    secret      TEXT,
    events      TEXT NOT NULL,
    enabled     INTEGER DEFAULT 1,
    created_at  TEXT NOT NULL
);
