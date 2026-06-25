-- 008_audit_correlation.sql — Colonne correlation_id sur audit_log
-- Permet de lier une entrée audit aux events du log structuré (request,
-- app.action.start, subprocess.line, app.action.end) pour le même user action.
-- Idempotent.

ALTER TABLE audit_log ADD COLUMN correlation_id TEXT;
CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_log(correlation_id);
