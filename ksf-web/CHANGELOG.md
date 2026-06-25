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

## [2.1.0] - 2026-06-25

### Fixed
- **P0 bloquant** : actions sur les apps (install/restart/stop/start/update/remove/rebuild)
  depuis ksf-web échouaient toutes avec « KSF n'est pas installé dans /home/appuser/serverbox ».
  Cause : `app.sh` calcule `BASE_DIR="${HOME}/serverbox"`, mais ksf-web injectait
  `HOME=/home/appuser` dans l'env des subprocess. Corrections (Python + bash) :
  - Ajout explicite de `BASE_DIR` dans `EXEC_ENV` (`ksf_commands.py`) et dans
    l'env du worker jobs (`services/jobs.py`).
  - 4 scripts bash modifiés : `app.sh`, `ksf.sh`, `deploy.sh`, `bootstrap.sh`
    utilisent `BASE_DIR="${BASE_DIR:-${HOME}/serverbox}"` (1 ligne chacun)
    pour respecter le `BASE_DIR` env var.
  - `app.sh` préserve `BASE_DIR`/`NETWORK_NAME`/`TZ_VALUE` après sourcing de
    `ksf.env` (sinon ksf.env les écrase avec les valeurs d'origine du host).
  - `lib/app_steps.sh::app_normalize_loaded` : si `APP_DIR` pointe vers un
    chemin inexistant mais que `${BASE_DIR}/apps/<app>` existe, bascule
    automatiquement. Couvre le cas où `installed-apps/<app>.env` contient
    un ancien chemin de l'hôte mais que la plateforme tourne maintenant
    dans un conteneur avec un bind mount.
  - `HOME=/tmp` (au lieu de `/home/appuser`) dans `EXEC_ENV` : contournement
    du mismatch uid 1000/1002 sur `/home/appuser` (appuser dans l'image vs
    uid réel de l'hôte). Les scripts n'utilisent plus `$HOME` depuis qu'on
    force `BASE_DIR`.
  - `Dockerfile` : installation du binaire `docker` CLI 27.3.1 (statique) +
    plugin `docker compose` v2.32.4. `docker.io` sur Debian 12 ne fournit
    que `dockerd`, pas le CLI. Sans ça, `app.sh restart <app>` échoue avec
    « Docker n'est pas installé ».
- **500 sur les actions d'app** : `helpers.py::run_app_action` utilisait
  `"args"` comme clé dans `extra={...}` du `logger.info("app.action.start")`.
  Or `args` est un attribut réservé de `LogRecord` (positional args du log call),
  ce qui levait `KeyError: "Attempt to overwrite 'args' in LogRecord"` → 500.
  Renommé en `action_args`. Audit des autres `extra={...}` : aucun autre conflit.

### Added
- **Système de logs structuré unifié** (Phase 7) :
  - `app/logging_config.py` : stdlib `logging.config` + `RotatingFileHandler`
    (10 MB × 5) vers `~/serverbox/logs/ksf-web/ksf-web.log` (JSONL), stdout
    conserve un format lisible. Aucune nouvelle dépendance.
  - `correlation_id` (UUID 12 chars) propagé via `contextvars` à tous les
    loggers, posé par `RequestLogMiddleware` et renvoyé dans le header
    `X-Request-Id` de chaque réponse.
  - `TeeSubprocess` : context manager qui tee la sortie d'un subprocess
    vers un fichier brut (compat SSE) + un logger structuré (events
    `subprocess.line` JSONL). Réutilisé par `ksf_commands.run_app_command`
    et `services/jobs._run_job`.
  - Events structurés `app.action.start` / `app.action.end` (logger
    `ksf-web.actions`) et `job.start` / `job.end` (logger `ksf-web.jobs`).
  - `audit_log.correlation_id` (migration 008).
  - **Onglet Logs** dans `/diagnostics?tab=logs` : partial `partials/logs_viewer.html`
    avec filtres (niveau, logger, target, correlation_id), auto-refresh 5 s,
    expand inline sur clic (charge `/api/logs/correlation/{cid}`).
  - 3 nouveaux endpoints : `/api/logs/recent`, `/api/logs/correlation/{cid}`,
    `/api/logs/download`.
  - 5 nouvelles variables d'env : `KSF_WEB_LOG_FORMAT`, `KSF_WEB_LOG_LEVEL`,
    `KSF_WEB_LOG_FILE_MAX_BYTES`, `KSF_WEB_LOG_FILE_BACKUPS`, `KSF_WEB_LOG_RETENTION_DAYS`.
  - Rétention unifiée : `_log_retention()` supprime `actions/*.log`,
    `jobs/*.log`, `ksf-web.log.*` > 30 jours, en plus de la purge des jobs
    > 30 jours en DB.
- **Module middleware** : `app/middleware/{__init__,request_log}.py` (RequestLogMiddleware).
- **Tests** : +14 tests pytest (88 total, vs 74 avant). 8 nouveaux tests
  `/api/logs/*` (recent, filters, correlation, cid invalide, download,
  filename invalide, onglet logs, header `X-Request-Id`). 3 nouveaux modules
  ajoutés aux tests d'import (couvrent les `NameError` runtime non détectés
  par AST seul).

## [1.x] - avant 2026-06

Voir git history.
