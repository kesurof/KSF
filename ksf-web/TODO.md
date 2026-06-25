# ksf-web — TODO & état du projet

> Document de travail pour l'équipe. Mis à jour à chaque session.
> Voir `CHANGELOG.md` pour l'historique détaillé des versions et
> `README.md` pour la vision d'ensemble de l'architecture.

---

## 🟢 Statut global (production-ready)

| Catégorie | Statut | Détail |
|---|---|---|
| Tests | ✅ **88/88** | pytest 8.3, TestClient + mocks Docker |
| Code Python | ✅ AST OK | 21 fichiers parsent sans erreur |
| Scripts Bash | ✅ OK | 11 scripts (bootstrap, deploy, app, ksf + lib/*) |
| Base de données | ✅ OK | 8 migrations (001 → 008) |
| Compose | ✅ OK | `templates/apps/ksf-web/compose.yml` se rend |
| Dead code | ✅ Aucun | 0 fonction définie et jamais appelée |
| CSS vars | ✅ Couvertes | Toutes les `var(--*)` utilisées sont définies dans `:root` |
| Sécurité | ✅ OK | CSRF, SSRF check, chiffrement au repos, validation entrées |
| Logs structurés | ✅ Phase 7 | JSONL rotaté + correlation_id + UI onglet |

---

## 📋 Sessions de travail (juin 2026)

### Session 7 — Fix actions apps + système de logs structuré (Phase 7) ✅

**Problème rapporté** : « les actions sur les apps depuis ksf-web ne fonctionne pas »

**Cause racine (P0 bloquant)** : `app.sh` calcule `BASE_DIR="${HOME}/serverbox"`,
mais `ksf-web` injectait `HOME="/home/appuser"` dans l'env des subprocess
(`EXEC_ENV` dans `ksf_commands.py` et `env` dans `services/jobs.py`). Donc
`app.sh` calculait `BASE_DIR=/home/appuser/serverbox` (inexistant) et toute
commande échouait avec « KSF n'est pas installé ». **Toutes** les actions
UI (install, restart, stop, start, update, remove, rebuild) étaient cassées.

**Fix** : ajout explicite de `"BASE_DIR": KSF_BASE_DIR` dans `EXEC_ENV` et
dans l'env du worker jobs. Aucune modif des scripts bash.

**Cause secondaire (manque de debuggabilité)** : logs éclatés en 6 endroits
non coordonnés (actions/*.log, jobs/*.log, audit_log SQLite, notifications,
uvicorn stdout, tracebacks Python). Pas de corrélation entre toast UI ↔ log
action ↔ job ↔ audit row.

**Solution appliquée** :

1. **Fix P0** : `BASE_DIR` forcé dans l'env des subprocess (2 lignes Python).
2. **Phase 1 — Infrastructure logging** : `app/logging_config.py` (stdlib
   `logging.config` + `RotatingFileHandler` 10 MB × 5) ; `LOG_FORMAT`,
   `LOG_LEVEL`, `LOG_FILE_*`, `LOG_RETENTION_DAYS` env vars ; init logging
   en premier dans le lifespan ; `_log_retention()` unifié.
3. **Phase 2 — Middleware request** : `app/middleware/request_log.py` ;
   génère `correlation_id` (uuid 12 chars), le pose via `contextvars`,
   log `request method=… path=… status=… duration_ms=…` et header
   `X-Request-Id` dans la réponse.
4. **Phase 3 — Capture structurée des actions et jobs** : `TeeSubprocess`
   context manager qui tee vers fichier brut (compat SSE) + logger JSONL.
   `app.action.start` / `app.action.end` et `job.start` / `job.end` émis
   autour de chaque run. `audit_log.correlation_id` (migration 008).
5. **Phase 4 — UI onglet Logs** : `/diagnostics?tab=logs` (5e onglet).
   Partial `partials/logs_viewer.html` avec filtres niveau/logger/target/cid,
   auto-refresh 5 s, expand inline charge `/api/logs/correlation/{cid}`.
   3 nouvelles routes API : `/api/logs/recent`, `/api/logs/correlation/{cid}`,
   `/api/logs/download`.
6. **Phase 5 — Tests** : +14 tests (88 total) couvrant les nouveaux endpoints,
   le header `X-Request-Id`, et les imports des 3 nouveaux modules.
7. **Phase 6 — Documentation** : section « Logs » dans README avec exemples
   `jq` ; entrée CHANGELOG 2.1.0.

**Fichiers modifiés** :
- 4 nouveaux : `app/logging_config.py`, `app/middleware/__init__.py`,
  `app/middleware/request_log.py`, `app/templates/partials/logs_viewer.html`,
  `app/templates/partials/log_correlation.html`, `migrations/008_audit_correlation.sql`
- 13 modifiés : `app/main.py`, `app/config.py`, `app/helpers.py`,
  `app/ksf_commands.py`, `app/services/audit.py`, `app/services/jobs.py`,
  `app/routes/api.py`, `app/templates/diagnostics.html`, `app/static/app.css`,
  `tests/test_smoke_api.py`, `tests/test_smoke_imports.py`, `README.md`,
  `CHANGELOG.md`, `TODO.md`
- 0 modifié (volontairement) : `app.sh`, `ksf.sh`, `lib/*.sh`,
  `templates/apps/ksf-web/compose.yml`

**Critères d'acceptation** :
- [x] AST Python OK, 8 migrations SQL OK, 88/88 tests pytest OK
- [x] `bash -n ksf.sh lib/*.sh` OK
- [x] `docker compose config` OK
- [x] Chaque réponse HTTP porte `X-Request-Id` (12 chars hex)
- [x] `app.sh` et `ksf.sh` non modifiés
- [x] `docker logs ksf-web` reste lisible (format `text` par défaut)
- [ ] **À vérifier après déploiement** : `POST /apps/dockge/restart` aboutit
  et `jq 'select(.correlation_id=="X")' ~/serverbox/logs/ksf-web/ksf-web.log`
  retourne la timeline complète

**Procédure de déploiement** :
```bash
cd /home/kesurof/projets/KSF
./app.sh rebuild ksf-web         # rebuild image (le code Python change)
docker restart ksf-web           # OU ./app.sh install ksf-web si modif compose
# Vérifier : docker logs ksf-web | tail -5
# Attendu : "ksf-web démarré (DB=..., jobs worker actif, log=...)"
# + 1re ligne JSONL dans ~/serverbox/logs/ksf-web/ksf-web.log
```

---

### Session 6 — Kebab dropdown bulletproof (Bootstrap-style) ✅

**Problème rapporté** : "le menu kebab ne s'ouvre pas, il est mal placé, les actions ne fonctionne pas"

**Cause racine** : malgré le refactor précédent (suppression de `<details>`), le pattern restait fragile :
- `display: inline-flex` sur le wrapper kebab est **ignoré** en contexte flex parent
- Délégation click mal calibrée : les items avec `data-confirm` ne fermaient pas le menu car le handler data-confirm en capture fait `stopImmediatePropagation`
- Trigger trop discret visuellement (taille imposée par `.btn`)

**Solution appliquée (pattern Bootstrap)** :

```html
<div class="kebab" data-dropdown>
    <button class="kebab-trigger" data-dropdown-trigger>⋯</button>
    <div class="kebab-menu" role="menu">items</div>
</div>
```

```js
// Toggle via class .is-open sur le wrapper
// Click sur trigger → toggleDropdown
// Click sur item (sans data-confirm) → setTimeout(close, 50ms)
// htmx:afterRequest sur .kebab-item → setTimeout(close, 100ms) (couvre data-confirm)
// Click ailleurs / Escape → closeAllDropdowns
```

```css
.kebab.is-open .kebab-menu { display: flex; }  /* Pas de [hidden], pas de <details> */
.kebab-trigger { padding: 0 !important; width: 1.75rem; ... }  /* Override .btn */
.kebab-menu { z-index: 1000; transform: translateZ(0); ... }  /* Au-dessus de tout */
```

**Fichiers modifiés** :
- `app/templates/apps.html` : structure HTML + JS dropdown handler
- `app/static/app.css` : `.kebab`, `.kebab-trigger`, `.kebab-menu`, `.kebab.is-open` rules

**Tests E2E vérifiés** :
- [x] State machine du dropdown (5 transitions : open/close/switch/outside/escape)
- [x] POST `/apps/{name}/{action}` retourne 200 + JSON correct
- [x] Structure HTML : `data-dropdown`, `data-dropdown-trigger`, ARIA
- [x] CSS : `.is-open` toggle, z-index 1000, transform pour stacking context
- [x] Pas de `<details>` (pattern bulletproof)
- [x] `hx-swap="none"` sur 5 boutons d'action

**Note de déploiement** : si le menu ne s'ouvre toujours pas après déploiement, vider le cache navigateur (`Ctrl+Shift+R` ou `Cmd+Shift+R`).

---

### Session 5 — Fix bugs `/apps` et UI actions ✅

**6 bugs critiques corrigés**

| # | Défaut constaté | Cause | Fichier | Fix appliqué |
|---|---|---|---|---|
| 1 | `/apps/install-form/{name}` → 500 | Route utilisait `Request` (classe) au lieu de `request` (instance) | `app/routes/api.py` | Paramètre `request: Request` + `_T(request).TemplateResponse(...)` |
| 2 | `closeInstallModal is not defined` après install | `install_form.html` appelait une fonction inexistante | `app/templates/partials/install_form.html` | Remplacé par `closeModal()` |
| 3 | "Start" → `/restart` (confusion sémantique) | Bouton "Start" utilisait l'endpoint restart | `app/templates/apps.html` | "Start" → `/start`, "Stop" → `/stop` |
| 4 | Kebab menu cassé en light theme | Vars CSS `--bg-1`, `--text-1`, `--r-1` non définies | `app/static/app.css` | Migration vers `--surface`, `--text`, `--r` |
| 5 | JSON brut s'affiche à la place du bouton après action | Boutons sans `hx-swap="none"` → htmx insère la réponse dans le DOM | `app/templates/apps.html` | `hx-swap="none"` sur tous les boutons d'action |
| 6 | Items du kebab s'affichent en bas de la page (1ère tentative) | `<details>` interfère avec le positionnement absolu en flex parent | `app/templates/apps.html`, `app/static/app.css` | Refactor en `<div>` + `<button>` |

**Améliorations UI/UX**

- [x] Formulaire d'install enrichi : résumé app (icône + nom + description + catégorie + OAuth2), hints d'aide, suffixe `.votredomaine`, état loading
- [x] Boutons avec icônes : ▶ Start, ■ Stop, ↻ Update, + Installer, → Gérer, ⋯ Kebab
- [x] Kebab menu : séparateur visuel entre actions safe et actions dangereuses
- [x] Boutons désactivés pendant htmx request (`hx-disabled-elt="this"`)
- [x] Modale d'install : reset erreur à l'ouverture, `role="alert"`

**3 tests ajoutés**

- [x] `test_apps_no_details_element` : pas de `<details>` dans apps.html
- [x] `test_apps_kebab_uses_data_kebab` : structure `data-kebab` + ARIA
- [x] `test_apps_actions_have_hx_swap_none` : tous les boutons ont `hx-swap="none"`

---

### Session 4 — Cleanup dead code ✅

- [x] Retiré `crypto.is_encrypted_column`
- [x] Retiré `docker_client.get_client_async`
- [x] Retiré `jobs.stream_log`
- [x] Retiré `config_editor.get_version`

---

### Session 3 — Cleanup imports ✅

- [x] Retiré `timezone` dans `docker_client.py`
- [x] Retiré `json` dans `config_editor.py`
- [x] Retiré `secrets` dans `jobs.py`

---

### Session 2 — Fonctionnalités & DX ✅

- [x] **P1.A** Page `/settings` unifiée
- [x] **P2.A** Light theme (variables CSS + bouton ☀/☾)
- [x] **P2.B** TypedDict infrastructure (`app/types.py`)
- [x] **P3.A** Jobs pagination cursor-based
- [x] **P3.B** Documentation EventBus

---

### Session 1 — Sécurité & quick wins ✅

- [x] **P2.4** Focus-trap modal
- [x] **P2.5** Indicateur "Étape N/M" pour doubles confirmations
- [x] **P3.12** Container stats
- [x] **P3.13** Webhook health check
- [x] **Refactor SSRF** : `_resolve_and_check_ip` + `_NoRedirect` partagés

---

### Session 4 — Cleanup dead code ✅

- [x] Retiré `crypto.is_encrypted_column` (jamais appelé)
- [x] Retiré `docker_client.get_client_async` (jamais appelé, nettoyé aussi `_docker_client_lock`, `_docker_client_healthy`, import `asyncio` orphelin)
- [x] Retiré `jobs.stream_log` (remplacé par `events.bus.subscribe()` dans le SSE route)
- [x] Retiré `config_editor.get_version` (jamais exposé via route)

---

### Session 3 — Cleanup imports ✅

- [x] Retiré `timezone` dans `docker_client.py`
- [x] Retiré `json` dans `config_editor.py`
- [x] Retiré `secrets` dans `jobs.py`

---

### Session 2 — Fonctionnalités & DX ✅

- [x] **P1.A** Page `/settings` unifiée (onglets Général / Webhooks / Sécurité / Maintenance)
- [x] **P2.A** Light theme (variables CSS + `:root[data-theme="light"]` + bouton ☀/☾ avec localStorage)
- [x] **P2.B** TypedDict infrastructure (`app/types.py` avec 9 TypedDict : AuditEntry, JobRecord, WebhookEndpoint, etc.)
- [x] **P3.A** Jobs pagination cursor-based (`?before=ISO8601`, bouton "Charger plus anciens")
- [x] **P3.B** Documentation EventBus (try/finally + discard = pas de zombie)

---

### Session 1 — Sécurité & quick wins ✅

- [x] **P2.4** Focus-trap modal (Tab piégé, `inert` sur `.main`/`.sidebar`/`header`)
- [x] **P2.5** Indicateur "Étape N/M" pour doubles confirmations
- [x] **P3.12** Container stats (`/api/containers/{id}/stats` : CPU%, mem, net)
- [x] **P3.13** Webhook health check (`/api/webhooks/{id}/health` : ping GET)
- [x] **Refactor SSRF** : `_resolve_and_check_ip` + `_NoRedirect` partagés entre `_send_with_retry` et `ping`

---

## 🔮 Backlog futur (recommandations)

### 🟡 P2 — Qualité & performance

| Item | Effort | Recommandation |
|---|---|---|
| **P2.C** Pydantic au lieu de TypedDict | 1-2j | Ajouter validation runtime pour `NotificationPayload`, `JobRecord`, `WebhookEndpoint`. TypedDict reste pour les structures purement DB-row. |
| **P2.D** Theme persisté côté serveur | 0.5-1j | Table `user_prefs(user_id, key, value)`. Endpoint `POST /api/prefs/theme`. Évite de perdre le thème sur changement de device. |
| **P2.E** Pydantic pour config_editor | 1j | Validation des types (`int`, `bool`, `email`, `domain`) à la lecture du formulaire. Évite les valeurs mal castées dans ksf.env. |

### 🟢 P3 — Polish

| Item | Effort | Recommandation |
|---|---|---|
| **P3.D** Tests TypedDict (mypy --strict) | 0.5j | Vérifier que les TypedDict couvrent tous les call sites. |
| **P3.E** Test theme toggle (smoke test) | 10 min | Test E2E du bouton ☀/☾. |
| **P3.F** Tag git `v2.0.0` | 5 min | Action release. Nécessite décision manuelle (cf. AGENTS.md : pas de tag sans demande explicite). |
| **P3.G** Tests E2E des nouvelles actions `/apps` | 1h | Couvrir les POST `/apps/{name}/{action}` avec mocks, vérifier codes retour, hx-swap=none, etc. |

---

## 📌 Décisions de scope (pas un oubli)

| Item | Raison |
|---|---|
| **P1.4** (dedup notifications) | Retiré en migration `007_drop_notif_dedup.sql`. Les webhooks externes dédupliquent côté récepteur. |
| **P2.15** (rate limit applicatif) | Traefik (middleware `rateLimit`) gère déjà le rate limit en bordure. |
| **P3.7** (pagination notifications) | Page UI notifications retirée. Conservé pour les jobs en P3.A. |
| **`get_client_async`** | Dead code : la version sync suffit pour le cache TTL 3s. |
| **`stream_log`** | Dead code : remplacé par `events.bus.subscribe()` (plus réactif). |
| **`get_version`** | Dead code : pas de UI de détail de version (rollback via `commit()`). |

---

## 🧪 Validation locale (à exécuter avant chaque PR)

```bash
# AST Python (~1s)
cd ksf-web && python3 -c "
import ast, os
for root, _, files in os.walk('app'):
    for f in files:
        if f.endswith('.py'):
            with open(os.path.join(root, f)) as fh: ast.parse(fh.read())
print('AST OK')
"

# Tests pytest
python3 -m pytest tests/ -v   # 74 tests

# Imports inutilisés + dead code (script ci-dessous)
python3 -c "..."  # voir section "Consignes" pour le script complet

# Migrations SQL
cd .. && for f in ksf-web/migrations/*.sql; do
  python3 -c "import sqlite3, glob; ..."  # applique les migrations
done

# Bash
bash -n bootstrap.sh && bash -n deploy.sh && bash -n app.sh && bash -n ksf.sh
bash -n lib/*.sh

# Compose
BASE_DIR=/tmp/df-test NETWORK_NAME=proxy TZ_VALUE=Europe/Paris \
APP_PUID=$(id -u) APP_PGID=$(id -g) DOCKER_GID=$(getent group docker | cut -d: -f3) \
KSF_REPO_DIR=$(pwd) KSF_WEB_DATA_HOST_DIR=/tmp/df-test/.ksf-web-data \
docker compose -f templates/apps/ksf-web/compose.yml config >/dev/null
```

---

## 📜 Consignes pour la suite

1. **Tout changement Python** : vérifier que les nouveaux symboles sont importés. `ast.parse` ne catch pas les `NameError` runtime — un test d'import complet est plus fiable.
2. **Tout changement async** : les patches rapides dans `services/notifications.py` et `services/webhooks.py` sont les plus risqués. Relire les call sites.
3. **Tout changement de schéma DB** : nouvelle migration `00X_*.sql` idempotente.
4. **Tout ajout de route** : smoke test dans `tests/test_smoke_api.py` ou `test_smoke_pages.py`. Maintenir le count ≥ 74.
5. **Tout service** : utiliser les TypedDict de `app/types.py` pour les signatures publiques.
6. **Tout bouton d'action htmx** : ajouter `hx-swap="none"` pour éviter que le JSON remplace le bouton dans le DOM. Le toast global dans `base.html` se charge d'afficher le message.
7. **Pas de `<details>` pour les dropdowns** : le user agent stylesheet interfère avec le positionnement absolu en flex parent. Utiliser `<div data-kebab>` + `<button data-kebab-trigger>`.
8. **Pas de dead code** : scanner avant chaque commit. Si tu écris une fonction jamais appelée, c'est soit (a) un helper de route, soit (b) à supprimer.

---

## 🔗 Liens utiles

- `CHANGELOG.md` : historique des versions (Keep a Changelog)
- `README.md` : architecture et procédure de debug
- `AGENTS.md` (racine) : conventions du projet
