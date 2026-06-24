-- 005_notif_dedup.sql — Déduplication des notifications répétitives
-- Quand un job échoue en boucle (monitoring, cron, etc.), on évite le spam.
-- Une notif avec le même `dedup_key` dans la fenêtre glissante 1 jour
-- incrémente `repeat_count` au lieu de créer une nouvelle ligne.
--
-- IMPORTANT : l'index unique ne peut PAS utiliser datetime() dans son
-- WHERE (SQLite interdit les fonctions non-déterministes dans un index).
-- Le filtre de fenêtre 1 jour est appliqué côté code (notifications.create
-- SELECT ... WHERE created_at > datetime('now', '-1 day')) ET par un job
-- de prune périodique (_prune_old_deduped_notifications dans main.py)
-- qui supprime les entrées > 1 jour. Sans ce prune, l'index accumule
-- des entrées dupliquées pour toujours.

ALTER TABLE notifications ADD COLUMN dedup_key TEXT;
ALTER TABLE notifications ADD COLUMN repeat_count INTEGER DEFAULT 0;

-- Index sur dedup_key (filtre par 1 jour géré côté code + prune périodique).
CREATE UNIQUE INDEX IF NOT EXISTS idx_notif_dedup
    ON notifications(dedup_key)
    WHERE dedup_key IS NOT NULL;

-- Index séparé sur (dedup_key, created_at) pour les SELECT de la fenêtre
-- 1 jour (notifications.create vérifie d'abord l'existence avant INSERT).
CREATE INDEX IF NOT EXISTS idx_notif_dedup_created
    ON notifications(dedup_key, created_at);
