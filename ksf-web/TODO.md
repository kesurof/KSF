# ksf-web — TODO & état du projet

> Document de travail pour l'équipe. Mis à jour à chaque session.
> Voir `CHANGELOG.md` pour l'historique détaillé des versions et
> `README.md` pour la vision d'ensemble de l'architecture.

---

## 🟢 Statut global (production-ready)

| Catégorie | Statut | Détail |
|---|---|---|
| Tests | ✅ **74/74** | pytest 8.3, TestClient + mocks Docker |
| Code Python | ✅ AST OK | 18 fichiers parsent sans erreur |
| Scripts Bash | ✅ OK | 11 scripts (bootstrap, deploy, app, ksf + lib/*) |
| Base de données | ✅ OK | 7 migrations (001 → 007) |
| Compose | ✅ OK | `templates/apps/ksf-web/compose.yml` se rend |
| Dead code | ✅ Aucun | 0 fonction définie et jamais appelée |
| CSS vars | ✅ Couvertes | Toutes les `var(--*)` utilisées sont définies dans `:root` |
| Sécurité | ✅ OK | CSRF, SSRF check, chiffrement au repos, validation entrées |

---

## 📋 Sessions de travail (juin 2026)

### Session 5 — Fix bugs `/apps` et UI actions ✅

**6 bugs critiques corrigés**

| # | Défaut constaté | Cause | Fichier | Fix appliqué |
|---|---|---|---|---|
| 1 | `/apps/install-form/{name}` → 500 | Route utilisait `Request` (classe) au lieu de `request` (instance) | `app/routes/api.py` | Paramètre `request: Request` + `_T(request).TemplateResponse(...)` |
| 2 | `closeInstallModal is not defined` après install | `install_form.html` appelait une fonction inexistante | `app/templates/partials/install_form.html` | Remplacé par `closeModal()` |
| 3 | "Start" → `/restart` (confusion sémantique) | Bouton "Start" utilisait l'endpoint restart | `app/templates/apps.html` | "Start" → `/start`, "Stop" → `/stop` |
| 4 | Kebab menu cassé en light theme | Vars CSS `--bg-1`, `--text-1`, `--r-1` non définies | `app/static/app.css` | Migration vers `--surface`, `--text`, `--r` |
| 5 | JSON brut s'affiche à la place du bouton après action | Boutons sans `hx-swap="none"` → htmx insère la réponse dans le DOM | `app/templates/apps.html` | `hx-swap="none"` sur tous les boutons d'action |
| 6 | Items du kebab s'affichent en bas de la page | `<details>` interfère avec le positionnement absolu en flex parent | `app/templates/apps.html`, `app/static/app.css` | Refactor en `<div data-kebab>` + `<button data-kebab-trigger>` + menu `hidden` |

**Améliorations UI/UX**

- [x] Formulaire d'install enrichi : résumé app (icône + nom + description + catégorie + OAuth2), hints d'aide, suffixe `.votredomaine`, état loading (spinner + disabled)
- [x] Boutons avec icônes : ▶ Start, ■ Stop, ↻ Update, + Installer, → Gérer, ⋯ Kebab
- [x] Kebab menu : séparateur visuel entre actions safe et actions dangereuses
- [x] Kebab menu : auto-close sur clic externe / Escape / item click
- [x] Kebab menu : ARIA complet (`role="menu"`, `role="menuitem"`, `aria-haspopup="menu"`, `aria-expanded`)
- [x] Boutons désactivés pendant htmx request (`hx-disabled-elt="this"`)
- [x] Modale d'install : reset erreur à l'ouverture, `role="alert"`, focus sur close

**3 tests ajoutés**

- [x] `test_apps_no_details_element` : pas de `<details>` dans apps.html
- [x] `test_apps_kebab_uses_data_kebab` : structure `data-kebab` + ARIA
- [x] `test_apps_actions_have_hx_swap_none` : tous les boutons ont `hx-swap="none"`

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
