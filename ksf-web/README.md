# ksf-web

Interface d'administration de la plateforme KSF (v2.0).

## Architecture

ksf-web est une app FastAPI/Python 3.12 (SQLite via aiosqlite) qui orchestre
la plateforme KSF :

```
ksf-web/
├── app/
│   ├── main.py              # FastAPI app + middleware + lifespan
│   ├── config.py            # Variables d'env centralisées
│   ├── db.py                # Connexion aiosqlite + migration runner
│   ├── crypto.py            # Chiffrement Fernet (Phase 2)
│   ├── helpers.py           # Utilitaires (validation, format, audit)
│   ├── security.py          # Validation noms
│   ├── utils.py             # utcnow helpers
│   ├── docker_client.py     # SDK Docker (avec cache TTL 3s)
│   ├── ksf_commands.py      # Wrapper ksf.sh / app.sh (whitelist)
│   ├── middleware/
│   │   └── rate_limit.py    # Token bucket par IP
│   ├── routes/              # Blueprints FastAPI
│   │   ├── pages.py         # GET HTML
│   │   ├── actions.py       # POST/DELETE mutations
│   │   ├── api.py           # JSON / partials / fichiers
│   │   └── sse.py           # EventSource streaming
│   ├── services/            # Logique métier
│   │   ├── audit.py         # Audit log (avec chiffrement)
│   │   ├── backups.py       # Delete / download / restore
│   │   ├── config_editor.py # Édition ksf.env (preview/commit token)
│   │   ├── events.py        # In-process pub/sub
│   │   ├── jobs.py          # Job queue (subprocess + SQLite)
│   │   ├── notifications.py # In-app + dispatch webhooks
│   │   └── webhooks.py      # CRUD + HMAC + retry + SSRF blocking
│   ├── templates/           # Jinja2
│   └── static/              # CSS + vendor JS
├── migrations/              # SQL versionné
├── requirements.txt
├── Dockerfile
├── entrypoint.sh
├── README.md
└── CHANGELOG.md
```

## Variables d'environnement

| Variable | Description | Défaut |
|---|---|---|
| `KSF_BASE_DIR` | Racine de la plateforme (`~/serverbox`) | `/serverbox` |
| `KSF_REPO_DIR` | Chemin du repo KSF | `/ksf` |
| `KSF_WEB_DATA_DIR` | Répertoire data dans le conteneur | `/var/lib/ksf-web` |
| `KSF_WEB_DATA_HOST_DIR` | Bind mount hôte | `${BASE_DIR}/.ksf-web-data` |
| `KSF_WEB_ACTIONS_ENABLED` | Active les POST mutations | `true` |
| `KSF_WEB_SECRET_KEY` | Clé Fernet dédiée (optionnelle) | générée et persistée dans `secret.key` |
| `KSF_WEB_COOKIE_SECURE` | Cookie CSRF marqué Secure | `true` |
| `APP_PUID` / `APP_PGID` | UID/GID hôte (bind mount) | posés par `app.sh` |
| `TZ` | Timezone IANA | `Europe/Paris` |
| `PYTHONUNBUFFERED` | Logs Python non bufferisés | `1` |

## Persistance

Bind mount `${KSF_WEB_DATA_HOST_DIR}:/var/lib/ksf-web`.
Dossier hôté créé et chowné par `app.sh install ksf-web` à `${APP_PUID}:${APP_PGID}`
AVANT le `docker compose up`. Avantage sur un volume nommé : permissions prévisibles,
pas de dépendance au Docker volume driver, backup trivial.

## Migrations

Appliquées automatiquement au démarrage par `db.init()`. Idempotent, le runner
utilise `BEGIN`/`COMMIT` explicites autour de chaque migration.

## Sécurité

### CSRF (double-submit cookie)
Middleware `CSRFMiddleware` : cookie `ksf_csrf` posé sur tout GET, vérifié
sur tout POST/DELETE/PUT via header `X-CSRF-Token` ou champ form `csrf_token`.
Signe avec `itsdangerous.URLSafeTimedSerializer` (max 8h).

### Chiffrement repos
Colonnes `*_encrypted BLOB` chiffrées Fernet (cryptography 44.0.0).
- `webhook_endpoints.secret_encrypted`
- `audit_log.before_encrypted` / `after_encrypted`

Clé : `KSF_WEB_SECRET_KEY` env var (base64) ou générée à la volée et persistée
dans `${KSF_WEB_DATA_DIR}/secret.key` (chmod 600). Backfill au démarrage
des colonnes legacy en clair (`idempotent`).

### Rollback Phase 2 (chiffrement)
```bash
docker stop ksf-web
cp ~/.serverbox/.ksf-web-data/state.db{,.pre-encryption-backup}
# Si problème :
cp ~/.serverbox/.ksf-web-data/state.db.pre-encryption-backup \
   ~/.serverbox/.ksf-web-data/state.db
docker exec -i ksf-web sqlite3 /var/lib/ksf-web/state.db \
  "DELETE FROM _migrations WHERE version=4"
docker start ksf-web
```

### OAuth2 Proxy
ksf-web fait confiance aux en-têtes `X-Forwarded-User` et `X-Forwarded-Email`
posés par OAuth2 Proxy devant Traefik. `_client_actor()` normalise (strip,
max 64 chars, printable only).

### SSRF blocking
`webhooks._is_safe_webhook_target()` refuse les targets privées/loopback/link-local
lors de la création/update d'un endpoint.

## Routes

- **GET** : `/`, `/containers`, `/apps`, `/backups`, `/jobs`, `/audit`,
  `/notifications`, `/config`, `/settings/webhooks`, `/security`, `/status`,
  `/routes`, `/data`, `/maintenance`, `/security/crowdsec`, `/security/appsec`,
  `/security/trusted-ips`
- **POST** : install/update/restart/start/stop/disable/remove/rebuild d'app ;
  create/verify/restore/prune/delete backup ; cancel job ; mark read notif ;
  CRUD webhooks ; ban/unban/flush/restart CrowdSec ; toggle AppSec ;
  apply trusted-ips ; system restart/update ; clean-data ; doctor
- **SSE** : `/jobs/{id}/stream` (subprocess output) ;
  `/containers/{id}/logs/stream` (logs Docker live)
- **JSON** : `/api/dashboard/summary`, `/api/audit/export`, `/api/audit/{id}`,
  `/api/config/preview`, `/api/config/commit`, `/api/jobs/list`,
  `/api/notifications/unread-count`, `/api/notifications/list`,
  `/api/status`, `/api/config-view`, `/api/routes`, `/api/data/list`,
  `/api/security/crowdsec/decisions`, `/api/security/trusted-ips`,
  `/api/locks`
- **Health** : `/health` (DB + Docker status, JSON, 200/503)

## Debug

```bash
# Logs
docker logs ksf-web -f

# Inspection DB
docker exec -it ksf-web sqlite3 /var/lib/ksf-web/state.db
sqlite> .tables
sqlite> SELECT * FROM jobs ORDER BY id DESC LIMIT 5;
sqlite> SELECT id, actor, action, target FROM audit_log ORDER BY id DESC LIMIT 10;

# Replay SSE (curl)
curl -N -H "Cookie: ksf_csrf=..." http://ksf.example.com/jobs/<id>/stream
```

## Procédure de mise à jour

```bash
# Pull nouveau code
cd /path/to/KSF && git pull

# Rebuild image
./app.sh rebuild ksf-web

# Les nouvelles migrations s'appliquent au démarrage
# Vérifier que le container est healthy
docker logs ksf-web | tail -20
curl -fsS http://ksf.example.com/health
```

## Limitations connues

- **Single-user** : pas de gestion multi-utilisateurs, fait confiance à OAuth2 Proxy.
- **EventBus in-memory** : pub/sub entre producers et consumers SSE reste dans
  le process. Si ksf-web redémarre pendant un job, les subscribers SSE doivent
  se reconnecter.
- **Rate limit in-memory** : perdu au restart du conteneur. Acceptable single-user.
- **Bind mount** : pas de réplication native, sauvegarder `${KSF_WEB_DATA_HOST_DIR}`.

## Liens

- `../ksf.sh` : orchestration plateforme
- `../app.sh` : cycle de vie des apps
- `../lib/manage_steps.sh` : fonctions ksf.sh disponibles
- `../AGENTS.md` : conventions KSF
- `../ksf-web/TODO.md` : backlog historique
- `../ksf-web/ROADMAP.md` : vision stratégique
