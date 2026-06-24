-- 004_encryption.sql — Chiffrement Fernet des secrets au repos
-- Ajoute des colonnes `*_encrypted BLOB` à côté des colonnes en clair existantes.
-- Le backfill est géré par l'application (idempotent, au démarrage), pas ici
-- parce qu'on n'a pas accès à la Fernet key en SQL.

ALTER TABLE webhook_endpoints ADD COLUMN secret_encrypted BLOB;

ALTER TABLE audit_log ADD COLUMN before_encrypted BLOB;
ALTER TABLE audit_log ADD COLUMN after_encrypted BLOB;
