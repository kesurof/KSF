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
  `/config`, `/settings/webhooks`, `/security` (onglets overview/crowdsec/appsec/trusted-ips),
  `/diagnostics` (onglets status/config/routes/data), `/maintenance`
- **POST** : install/update/restart/start/stop/disable/remove/rebuild d'app ;
  create/verify/restore/prune/delete backup ; cancel job ;
  CRUD webhooks ; ban/unban/flush/restart CrowdSec ; toggle AppSec ;
  apply trusted-ips ; system restart/update ; clean-data ; doctor
- **SSE** : `/jobs/{id}/stream` (subprocess output) ;
  `/containers/{id}/logs/stream` (logs Docker live)
- **JSON** : `/api/dashboard/summary`, `/api/audit/export`, `/api/audit/{id}`,
  `/api/config/preview`, `/api/config/commit`, `/api/jobs/list`,
  `/api/status`, `/api/config-view`, `/api/routes`, `/api/data/list`,
  `/api/security/crowdsec/decisions`, `/api/security/trusted-ips`,
  `/api/locks`
- **Health** : `/health` (DB + Docker status, JSON, 200/503)

## Architecture & Décisions

**Frontend** : Jinja2 + htmx 1.x (server-rendered, pas de SPA). JS vanilla
minimal (kebab menu, colorisation syntaxique via highlight.js 11.x).

**Backend** : FastAPI + SQLite (aiosqlite, mode WAL) + cryptographie Fernet
pour les secrets au repos.

**Communication ksf-web ↔ plateforme** :
- **Subprocess `ksf.sh` / `app.sh`** via whitelist (`ALLOWED_COMMANDS` dans
  `app/ksf_commands.py`) pour les commandes de coordination (render Traefik,
  OAuth2, CrowdSec, trusted-ips, backups, etc.)
- **Docker API direct** via `docker.from_env()` pour les opérations container
  atomiques (start/stop/restart, list, logs).
- **HTTP via `httpx`** pour les webhooks sortants (avec rate-limit,
  HMAC-SHA256, SSRF blocking, DNS rebinding mitigation).

### Décision : pas d'API tierce (etcd / Consul / Portainer / etc.)

ksf-web n'introduit pas de service tiers (etcd, Consul, Portainer, Vault, etc.)
pour gérer la configuration ou l'état. Les raisons :

1. **Les scripts bash restent la source de vérité** : `ksf.sh` et `app.sh`
   coordonnent déjà Traefik, OAuth2, CrowdSec, les backups. Un service tiers
   serait un troisième système à synchroniser, augmentant la complexité
   sans rien apporter.
2. **Subprocess = debuggable et fiable** : `subprocess.run()` avec capture
   stdout/stderr, returncode, timeout. Pas de dépendance réseau supplémentaire,
   pas de race conditions sur des API REST, pas de service à démarrer/arrêter.
3. **SQLite couvre l'état local de ksf-web** : la base stocke uniquement
   l'état propre à ksf-web (jobs, audit, config_versions, webhooks, notifications).
   L'état de la plateforme (containers, routes Traefik, OAuth2 config) reste
   dans les fichiers et le daemon Docker.

**Conséquence** : si tu as besoin d'un 2e client (CLI, mobile, intégration
externe), investis dans l'OpenAPI (déjà généré gratuitement par FastAPI sur
les routes `/api/*`) au lieu d'introduire un service tiers. Ne casse pas
l'architecture pour résoudre un problème qui n'existe pas encore.

### Sécurité : rate-limit (déplacé sur Traefik)

Le rate-limit applicatif a été retiré de ksf-web (doublon avec Traefik).
Config Traefik équivalente (à mettre sur le routeur ksf-web) :

```yaml
# /etc/traefik/dynamic/middlewares/ksf-web-ratelimit.yml
http:
  middlewares:
    ksf-web-ratelimit:
      rateLimit:
        average: 100
        burst: 200
        period: 1m
```

Si tu utilises un autre reverse-proxy (nginx, caddy), applique la même
politique côté proxy.

## Debug

```bash
# Logs
docker logs ksf-web -f

# Inspection DB
docker exec -it ksf-web sqlite3 /var/lib/ksf-web/state.db
sqlite> .tables
sqlite> SELECT * FROM jobs ORDER BY id DESC LIMIT 5;
sqlite> SELECT id, actor, action, target, correlation_id FROM audit_log ORDER BY id DESC LIMIT 10;

# Replay SSE (curl)
curl -N -H "Cookie: ksf_csrf=..." http://ksf.example.com/jobs/<id>/stream
```

## Logs (Phase 7 — système de logs unifié)

ksf-web émet 2 types de logs :

1. **stdout (text)** : pour `docker logs` — lisible directement.
2. **fichier `~/serverbox/logs/ksf-web/ksf-web.log` (JSONL)** : un event par ligne,
   rotaté automatiquement (10 MB × 5 backups). Vue UI : `/diagnostics?tab=logs`.

Chaque event porte un `correlation_id` (UUID 12 chars, posé par `RequestLogMiddleware`
et propagé via `contextvars` à tous les handlers de log). Toutes les events d'une
même action partagent le même `correlation_id` : request → app.action.start →
subprocess.line* → app.action.end → audit.

Chaque réponse HTTP porte un header `X-Request-Id` (12 chars) qui est le
`correlation_id` de la requête.

### Exemples `jq` (sur le fichier JSONL)

```bash
# Toutes les erreurs des 30 derniers jours
jq -c 'select(.level=="ERROR")' ~/serverbox/logs/ksf-web/ksf-web.log

# Timeline complète d'une action (clic UI → résultat)
CID=$(curl -sI -H "Cookie: ksf_csrf=…" https://ksf.example.com/apps/dockge/restart | awk '/X-Request-Id/ {print $2}' | tr -d '\r')
jq -c --arg cid "$CID" 'select(.correlation_id == $cid)' ~/serverbox/logs/ksf-web/ksf-web.log

# Toutes les actions sur dockge aujourd'hui
jq -c 'select(.target=="dockge" and .ts | startswith("2026-06-25"))' ~/serverbox/logs/ksf-web/ksf-web.log

# Compter les erreurs par logger
jq -r 'select(.level=="ERROR") | .logger' ~/serverbox/logs/ksf-web/ksf-web.log | sort | uniq -c
```

### Configuration

| Variable env | Défaut | Effet |
|---|---|---|
| `KSF_WEB_LOG_FORMAT` | `text` | `text` (lisible stdout) ou `json` (structured) |
| `KSF_WEB_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `KSF_WEB_LOG_FILE_MAX_BYTES` | `10485760` | 10 MB par fichier avant rotation |
| `KSF_WEB_LOG_FILE_BACKUPS` | `5` | Nombre de rotations conservées |
| `KSF_WEB_LOG_RETENTION_DAYS` | `30` | Purge des `.log` orphelins et rotations au démarrage |

### Endpoints

- `GET /api/logs/recent?level=INFO&level=ERROR&logger=ksf-web.actions&target=dockge&correlation_id=…&limit=200` :
  partial HTML pour l'UI onglet Logs. Auto-refresh 5 s.
- `GET /api/logs/correlation/{cid}` : partial HTML (par défaut) ou JSON (`?format=json`)
  avec tous les events d'un `correlation_id` + l'event `audit_log` lié.
- `GET /api/logs/download?file=ksf-web.log` (ou `ksf-web.log.1`, etc.) : fichier brut.

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
- **Bind mount** : pas de réplication native, sauvegarder `${KSF_WEB_DATA_HOST_DIR}`.

## Tests

```bash
# Setup (dev only)
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# Smoke tests E2E (TestClient + mocks Docker/ksf)
pytest -v ksf-web/tests/
```

Les tests E2E vérifient que :
- Tous les modules Python s'importent sans `NameError` / `ImportError`
- Les 14 pages canoniques (`/`, `/containers`, `/apps`, `/backups`, `/jobs`,
  `/audit`, `/settings/webhooks`, `/config`, `/security`, `/security?tab=*`,
  `/diagnostics`, `/diagnostics?tab=*`, `/maintenance`) retournent 200
- Les 6 URLs legacy (`/security/crowdsec`, `/security/appsec`,
  `/security/trusted-ips`, `/status`, `/routes`, `/data`) redirigent en 307
- Les 11 endpoints API critiques (`/api/dashboard/summary`, `/api/jobs/list`,
  `/api/audit/export`, `/api/locks`, `/api/status`, `/api/routes`, etc.)
  retournent 200
- Le health endpoint `/health` répond avec la structure JSON attendue

## Liens

- `../ksf.sh` : orchestration plateforme
- `../app.sh` : cycle de vie des apps
- `../lib/manage_steps.sh` : fonctions ksf.sh disponibles
- `../AGENTS.md` : conventions KSF
- `../ksf-web/TODO.md` : backlog historique
- `../ksf-web/ROADMAP.md` : vision stratégique
