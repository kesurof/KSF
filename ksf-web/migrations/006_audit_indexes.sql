-- 006_audit_indexes.sql — Index manquants sur audit_log.actor (et target)
-- Le filtre `actor` a été ajouté à /audit et /api/audit/export sans index,
-- ce qui provoque un full table scan sur les exports de 10000 lignes.

CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target);
