# ksf-web — État du projet

> Le projet est stabilisé. Cette session a corrigé plusieurs bugs critiques
> sur la page `/apps` (install form cassé, action UI non optimisée).
> Voir `CHANGELOG.md` pour l'historique détaillé des versions et
> `README.md` pour la vision d'ensemble de l'architecture.

## Statut

**Production-ready.** 71/71 tests passent, AST Python OK sur 18 fichiers,
11 scripts shell valident, 7 migrations SQL s'appliquent, le compose
template se rend correctement.

```
✓ BASH   — 11 scripts (bootstrap, deploy, app, ksf + lib/*)
✓ AST    — 18 fichiers Python
✓ SQL    — 7 migrations (001 → 007)
✓ COMPOSE — templates/apps/ksf-web/compose.yml
✓ PYTEST — 71 tests (smoke api + smoke imports + smoke pages)
✓ E2E    — page /apps complète (catalogue, install form, kebab, actions)
✓ DEAD CODE — 0 fonction définie et jamais appelée
✓ CSS VARS — toutes les variables utilisées sont définies dans :root
```

---

## Livré dans cette session (juin 2026)

### Bugs critiques corrigés sur `/apps`

| Bug | Cause | Impact | Fichiers |
|---|---|---|---|
| **`/apps/install-form/{name}` 500** | Route utilisait `Request` (la classe) au lieu de `request` (l'instance) dans `_T(Request).TemplateResponse(...)` et `"request": Request` | Le formulaire d'install était **complètement cassé** : impossible d'installer une app depuis l'UI | `app/routes/api.py` |
| **`closeInstallModal` undefined** | `install_form.html` appelait `closeInstallModal()` mais la fonction n'existait pas (le modal apps.html utilise `closeModal()`) | **JS error** après install → la modale ne se fermait pas | `app/templates/partials/install_form.html` |
| **Start utilisait `/restart`** | Quand `app.status != 'running'`, le bouton "Start" appelait `/restart` (confusant : "Redémarrer" n'est pas "Démarrer") | UX confuse : le user voyait "Démarrer X ?" puis "Redémarrage lancé" | `app/templates/apps.html` |
| **CSS vars `var(--bg-1)`, `var(--text-1)`, `var(--r-1)`** | Anciennes références non migrées (fallback via `var(--bg-3, var(--bg-2))` cassé) | Kebab menu visuellement cassé en light theme (bg transparent) | `app/static/app.css` |

### Améliorations UI/UX

| Amélioration | Description |
|---|---|
| **Formulaire d'install enrichi** | Résumé de l'app en haut (icône + nom + description + catégorie + accessibilité OAuth2), hints d'aide sous chaque champ, suffixe `.votredomaine` sur le champ subdomain, état loading sur le bouton submit (spinner + disabled) |
| **Boutons avec icônes** | ▶ Start, ■ Stop, ↻ Update, + Installer, → Gérer, ⋯ Kebab — meilleure lisibilité |
| **Kebab menu** : séparateur visuel entre actions safe (Redémarrer/Reconstruire) et actions dangereuses (Désactiver/Supprimer) |
| **Kebab menu** : auto-close sur clic externe ET sur activation d'un item |
| **Kebab menu** : `role="menu"`, `role="menuitem"`, `role="separator"` pour l'accessibilité |
| **Boutons désactivés pendant htmx request** : `hx-disabled-elt="this"` empêche les doubles-clics |
| **Modale d'install** : reset de l'erreur à l'ouverture (pas d'erreur résiduelle d'un précédent essai échoué) |
| **Erreur install** : `role="alert"` pour l'accessibilité (lecture par screen reader) |
| **Modale d'install** : focus sur le bouton close à l'ouverture |

### Tests ajoutés (6)

- `test_apps_page_renders` : page /apps contient `openModal`/`closeModal`, n'utilise pas `closeInstallModal`
- `test_install_form_returns_valid_html` : bug fix Request vs request
- `test_install_form_unknown_app_rejected` : sécurité (path traversal)
- `test_apps_action_endpoints_registered` : tous les endpoints présents
- `test_apps_kebab_menu_has_separator_and_aria` : accessibilité du kebab
- `test_apps_install_button_uses_plus_icon` : icône + sur le bouton install

---

## Sessions précédentes (juin 2026)

| Item | Fichiers | Description |
|---|---|---|
| **Dead code** `crypto.is_encrypted_column` | `app/crypto.py` | Fonction définie mais jamais appelée. Retirée. |
| **Dead code** `docker_client.get_client_async` | `app/docker_client.py` | Version async du client Docker, définie mais jamais appelée par les routes. Retirée (+ nettoyage des vars `_docker_client_lock` et `_docker_client_healthy` qui n'avaient plus de raison d'être, + retrait de l'import `asyncio` qui devenait orphelin). |
| **Dead code** `jobs.stream_log` | `app/services/jobs.py` | Helper de streaming log non utilisé (le SSE route utilise `events.bus.subscribe` à la place). Retiré. |
| **Dead code** `config_editor.get_version` | `app/services/config_editor.py` | Helper de lazy-load mentionné en docstring mais jamais appelé par une route. Retiré. |
| **Vérification qualité** | (analyse statique) | Scan AST exhaustif : 0 bare except, 0 mutable default, 0 import inutilisé, 0 fonction morte (hors callbacks framework). |
| **E2E 10 checks** | (validation) | Vérification E2E de 10 scénarios clés (settings pages, theme toggle, container stats, webhook health, jobs pagination, health endpoint, locks, dashboard, modal JS). Tous OK. |

---

## Sessions précédentes (juin 2026)

### Session 1 — Sécurité & quick wins
- **P2.4** Focus-trap modal (Tab piégé dans la modale, inert sur .main/.sidebar/header)
- **P2.5** Indicateur "Étape N/M" pour doubles confirmations
- **P3.12** Container stats (CPU%, mem, net) via Docker SDK
- **P3.13** Webhook health check (GET ping)
- **Review** : SSRF duplication extraite (`_resolve_and_check_ip` + `_NoRedirect` partagés entre `_send_with_retry` et `ping`)

### Session 2 — Fonctionnalités & DX
- **P1.A** Page `/settings` unifiée (onglets Général / Webhooks / Sécurité / Maintenance)
- **P2.A** Light theme (variables CSS + override `:root[data-theme="light"]`, bouton ☀/☾ avec localStorage)
- **P2.B** TypedDict infrastructure (`app/types.py` avec 9 TypedDict)
- **P3.A** Jobs pagination cursor-based (`?before=ISO8601`, bouton "Charger plus anciens")
- **P3.B** Documentation EventBus (try/finally + discard = pas de zombie)

### Session 3 — Cleanup imports
- `timezone` dans `docker_client.py`
- `json` dans `config_editor.py`
- `secrets` dans `jobs.py`
- Vérification exhaustive : 0 import mort

### Session 4 — Cleanup dead code
- 4 fonctions définies et jamais appelées retirées
- Vérification exhaustive : 0 dead code (hors framework callbacks)

### Session 5 (actuelle) — Fix bugs `/apps` et UI actions

Voir section "Livré dans cette session" ci-dessus. 4 bugs critiques corrigés
(route install cassée, JS undefined, Start vs Restart, CSS vars cassées),
UI des actions optimisée (icônes, séparateurs, accessibilité ARIA, loading
states), 6 tests ajoutés.

---

## Backlog futur

| Priorité | Item | Effort |
|---|---|---|
| 🟡 P2.C | Pydantic au lieu de TypedDict (validation runtime) | 1-2j |
| 🟡 P2.D | Theme persisté côté serveur (table `user_prefs`) | 0.5-1j |
| 🟢 P3.D | Tests TypedDict (mypy --strict) | 0.5j |
| 🟢 P3.E | Test theme toggle (smoke test) | 10 min |
| 🟢 P3.F | Tag git `v2.0.0` (release ops) | 5 min |

---

## Décisions de scope documentées

| Item | Raison |
|---|---|
| **P1.4** (dedup notifications) | Retiré en migration `007_drop_notif_dedup.sql`. Les webhooks externes dédupliquent côté récepteur. |
| **P2.15** (rate limit applicatif) | Traefik (middleware `rateLimit`) gère déjà le rate limit en bordure. Doublon retiré. |
| **P3.7** (pagination notifications) | Plus de UI notifications (page retirée). Conservé pour les jobs en P3.A. |
| **`get_client_async`** | Dead code : la version sync `get_client()` suffit pour le cache TTL 3s actuel. Le health check est géré par `_docker_client_healthy` ré-évalué à chaque mutation. |
| **`stream_log`** | Dead code : remplacé par `events.bus.subscribe()` dans le SSE route, qui est plus réactif (events temps réel) et découplé du filesystem. |
| **`get_version`** | Dead code : la UI affiche l'historique mais n'ouvre pas le détail d'une version (les commits de ksf.env sont déjà rollback-able via `commit()` qui restore depuis la version de backup). |

---

## Validation locale (à exécuter avant chaque PR)

```bash
# AST Python
cd ksf-web && python3 -c "
import ast, os
for root, _, files in os.walk('app'):
    for f in files:
        if f.endswith('.py'):
            with open(os.path.join(root, f)) as fh: ast.parse(fh.read())
print('AST OK')
"

# Tests pytest
python3 -m pytest tests/ -v   # 65 tests

# Vérifier l'absence d'imports inutilisés ET de dead code
python3 -c "
import ast, os, re
all_src = {}
for root, _, files in os.walk('app'):
    for f in files:
        if not f.endswith('.py'): continue
        p = os.path.join(root, f)
        with open(p) as fh: all_src[p] = fh.read()

# Imports inutilisés
for p, src in all_src.items():
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == '__future__': continue
            for n in node.names:
                name = n.asname or n.name
                if src.count(name) < 2: print(f'UNUSED IMPORT: {p}: {name}')
        elif isinstance(node, ast.Import):
            for n in node.names:
                name = (n.asname or n.name).split('.')[0]
                if src.count(name) < 2: print(f'UNUSED IMPORT: {p}: {name}')

# Fonctions mortes (hors framework callbacks)
for p, src in all_src.items():
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            if name.startswith('_') or name in ('__init__','lifespan',
                'not_found_handler','server_error_handler','redirect_request'):
                continue
            calls = sum(len(re.findall(r'\\b' + re.escape(name) + r'\\s*\\(', s))
                        for s in all_src.values())
            if calls <= 1:
                # Check route
                line_starts = src.split(chr(10))
                func_line = next((i for i,l in enumerate(line_starts) if f'def {name}(' in l), -1)
                if func_line >= 0:
                    prev = line_starts[max(0, func_line-4):func_line]
                    if not any('@router' in pl for pl in prev):
                        print(f'POSSIBLE DEAD: {p}: {name}')
print('Done')
"

# Migrations SQL
cd .. && for f in ksf-web/migrations/*.sql; do
  python3 -c "
import sqlite3, glob
conn = sqlite3.connect(':memory:')
for prev in sorted(glob.glob('ksf-web/migrations/*.sql')):
    if prev <= '$f': conn.executescript(open(prev).read())
print('OK $f')
"
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

## Consignes pour la suite

1. **Avant tout changement Python** : vérifier que tous les nouveaux symboles sont importés. `ast.parse` ne catch PAS les `NameError` runtime — un test d'import complet (`python3 -c "from app.main import app"`) est plus fiable.
2. **Avant tout changement async** : les patches rapides dans `services/notifications.py` et `services/webhooks.py` sont les plus risqués (cf. leçon du 24 juin). Relire les call sites.
3. **Avant tout changement de schéma DB** : nouvelle migration `00X_*.sql` qui s'applique via le runner idempotent. Jamais de `ALTER TABLE` non couvert par `_filter_already_applied_alter`.
4. **Avant tout ajout de route** : ajouter un smoke test dans `tests/test_smoke_api.py` ou `test_smoke_pages.py`. Maintenir le count ≥ 65.
5. **Si tu touches à un service** : utiliser les TypedDict de `app/types.py` pour les nouvelles signatures publiques.
6. **Pas de dead code** : avant chaque commit, lancer le scan de validation ci-dessus. Si tu écris une fonction qui n'est appelée nulle part, c'est soit (a) un helper de route, soit (b) du code à supprimer.

## Liens utiles

- `CHANGELOG.md` : historique des versions (Keep a Changelog)
- `README.md` : architecture et procédure de debug
- `AGENTS.md` (racine) : conventions du projet
