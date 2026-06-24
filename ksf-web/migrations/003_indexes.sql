-- 003_indexes.sql
-- Index pour filtrer l'audit par job_id (utilisé par la page /jobs et les exports).

CREATE INDEX IF NOT EXISTS idx_audit_log_job_id
    ON audit_log (job_id)
    WHERE job_id IS NOT NULL;

-- Index composite pour les requêtes typiques de la page /audit
-- (filtrage par action ou target + tri par date).
CREATE INDEX IF NOT EXISTS idx_audit_log_created_action
    ON audit_log (created_at DESC, action);
