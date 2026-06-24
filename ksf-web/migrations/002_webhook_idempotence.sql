-- 002_webhook_idempotence.sql
-- Empêche la création de doublons de webhooks (même name+url)
-- suite à un double-clic ou un retry de POST /api/webhooks.

CREATE UNIQUE INDEX IF NOT EXISTS idx_webhook_unique_name_url
    ON webhook_endpoints (name, url);
