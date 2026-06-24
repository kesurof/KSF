# Changelog

Tous les changements notables de ksf-web sont documentés ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
et ce projet adhère au [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-XX-XX

### Added
- **Refactor structurel** : `main.py` (1071 lignes) découpé en blueprints
  `app/routes/{pages,actions,api,sse}.py` + `app/helpers.py` + `app/middleware/`.
  76 routes uniques, aucune duplication.
- **Schéma `ksf.env` typé** (P0 bloquant) : 22 champs documentés
  (DOMAIN, ACME_EMAIL, WITH_CROWDSEC, CROWDSEC_APPSEC_*, OAUTH_*, TRAEFIK_*,
  etc.) répartis en 4 sections (Platform, Traefik, OAuth2, CrowdSec).
  Validation `required_if` (ex: `OAUTH_CLIENT_ID` requis si `WITH_OAUTH2=true`).
- **Chiffrement Fernet au repos** (P0 sécurité) : colonnes `*_encrypted BLOB`
  pour `webhook_endpoints.secret`, `audit_log.before/after`. Clé dédiée via
  `KSF_WEB_SECRET_KEY` ou auto-générée dans `${KSF_WEB_DATA_DIR}/secret.key`
  (chmod 600). Backfill au démarrage, idempotent.
- **`GET /health`** : JSON `{status, db, docker, version}`, 200/503.
- **Rate limiting** : token bucket in-memory par IP. GET 100/min, POST safe
  30/min, POST destructifs 5/5min, SSE 5 concurrent. Headers `X-RateLimit-*`.
- **Cache `list_containers` TTL 3s** (P2.1) : invalidé par mutations Docker.
- **Lazy-load audit** : `GET /api/audit/{id}` charge before/after à la demande.
- **Dedup notifications** : `dedup_key` + `repeat_count`, fenêtre 1h, unique
  index partiel 1 jour.
- **Rétention jobs 30 jours** : suppression auto des anciens jobs + .log
  au démarrage du lifespan.
- **Filtre `actor` dans `/audit`** : nouveau champ dans le formulaire.
- **Câblage des commandes ksf.sh manquantes** :
  - Page `/security/crowdsec` : ban/unban IP, flush décisions, restart service.
  - Page `/security/appsec` : toggle AppSec / WAF avec config live.
  - Page `/security/trusted-ips` : appliquer CIDR Cloudflare + restart Traefik.
  - Page `/maintenance` : restart plateforme + update ciblé (crowdsec|traefik|oauth2|all).
  - Page `/status` : output de `ksf.sh status` + `ksf.sh config`.
  - Page `/routes` : analyse des routes Traefik dynamiques (auto-refresh 30s).
  - Page `/data` : liste des apps avec données préservées + suppression.
  - Bouton "Rebuild" sur chaque app card.
- **Favicon SVG inline** (data URI) dans `base.html`.
- **Cache-Control `no-cache`** middleware pour les pages HTML (mitige le besoin
  Cloudflare bypass pendant le dev).
- **Feedback erreur dans la modale d'install** : l'erreur reste affichée dans
  la modale plutôt que juste un toast.
- **Endpoint `/api/locks`** : liste les `lock_key` actifs pour la UI.

### Changed
- `app/main.py` : -925 lignes, décomposé en 6 modules.
- `app/services/audit.py` : chiffrement transparent `before`/`after`.
- `app/services/webhooks.py` : chiffrement `secret`, backfill legacy.
- `app/ksf_commands.py` : support `extra_args` paramétrés (ban IP, duration,
  service name, app name) avec validation stricte.
- `app/services/jobs.py` : 12 nouveaux `JOB_KINDS` (system.restart,
  system.update_service, ksf.trusted_ips_apply, ksf.appsec_toggle, etc.).
- `app/services/notifications.py` : paramètre `dedup_key` optionnel, increment
  `repeat_count` au lieu de INSERT si dédup match.
- `app/docker_client.py` : cache TTL 3s sur `list_containers`, invalidé par
  start/stop/restart.
- `templates/apps/ksf-web/compose.yml` : ajout `KSF_WEB_SECRET_KEY` env var.
- Sidebar `base.html` : nouvelles entrées (CrowdSec, AppSec, Trusted IPs,
  État global, Routes, Données, Maintenance).
- Branding unifié : "KSF" partout (au lieu de "ksf/Serverbox/KSF").

### Fixed
- **P0 : `NameError: name 'SCHEMA' is not defined`** sur `GET /config` :
  la constante `SCHEMA` n'était pas définie dans `config_editor.py`. Tout
  le workflow de preview/commit ksf.env était cassé.
- **Dead code** : suppression de `webhook backfill script` redondant.

### Security
- Secrets webhook chiffrés en DB (HMAC, URL targets).
- Audit log before/after chiffrés (peut contenir `OAUTH_CLIENT_SECRET` lors
  d'éditions de config).
- Rollback documenté pour la migration 004 (chiffrement) en cas de problème.
- SSRF blocking maintenu sur création/update de webhook.
- CSRF middleware inchangé (double-submit cookie).
- Rate limiting pour mitiger brute-force / abuse.

## [1.x] - avant 2026-06

Voir git history.
