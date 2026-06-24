-- 007_drop_notif_dedup.sql — Suppression de la déduplication des notifications
-- Simplification : on garde la table `notifications` (déclencheur de webhooks)
-- mais on retire les colonnes dédup + index. L'UI notifications est aussi retirée
-- (item 7 du plan de simplification).

DROP INDEX IF EXISTS idx_notif_dedup;
DROP INDEX IF EXISTS idx_notif_dedup_created;

ALTER TABLE notifications DROP COLUMN dedup_key;
ALTER TABLE notifications DROP COLUMN repeat_count;
