# ksf-web — TODO consolidé

> Liste exhaustive de tout ce qui reste à faire après Phases 0, 1, 2.
> Organisé par priorité et par composant. Voir `ROADMAP.md` pour la vision d'ensemble
> et `CHANGELOG.md` (à créer en Phase 4) pour l'historique des versions.

## Légende priorité

| Symbole | Signification | Délai suggéré |
|---|---|---|
| 🔴 **P0** | Correctif sécurité ou bug bloquant production | Semaine 1 |
| 🟠 **P1** | Bug ou dette importante impactant UX/stabilité | Mois 1 |
| 🟡 **P2** | Amélioration qualité ou performance | Mois 2 |
| 🟢 **P3** | Polish, nice-to-have, refactoring | Quand libre |

---

## 🔴 P0 — Sécurité & bugs bloquants

### ✅ P0.1 — FIXED : DB persistence via bind mount (corrigé après analyse)

**Cause racine** : la solution initiale (volume Docker nommé `ksf-web-data:/var/lib/ksf-web`) ne se montait pas dans le conteneur. Diagnostic : on voyait le contenu de l'image (apt, dpkg, etc.) dans `/var/lib/`, pas le contenu du volume. Avec `read_only: true` sur le rootfs, le `chown`/`chmod` dans l'entrypoint échouait (EPERM) parce qu'on touchait au rootfs, pas au volume.

**Solution appliquée** (bind mount au lieu de named volume) :
1. **Compose** : `${KSF_WEB_DATA_HOST_DIR}:/var/lib/ksf-web` (bind mount vers l'hôte)
2. **app.env** : `KSF_WEB_DATA_HOST_DIR=__BASE_DIR__/.ksf-web-data` (rendu par KSF render)
3. **app_install** (`lib/app_steps.sh`) : `mkdir -p` + `chown $APP_PUID:$APP_PGID` + `chmod 700` du dossier hôte AVANT le `docker compose up`
4. **Entrypoint simplifié** : plus de chown/chmod (le bind mount gère les perms), juste un test d'écriture fail-fast
5. **app/config.py** : `KSF_WEB_DATA_DIR=/var/lib/ksf-web` (dans le conteneur), `DB_PATH=$KSF_WEB_DATA_DIR/state.db`
6. **db.py** : `chmod 600` sur le DB au premier create (best-effort)

**Pourquoi bind mount > named volume** :
- Pas de dépendance au Docker volume driver
- Permissions prévisibles sur l'hôte (chownées une fois par deploy)
- Pas de chown dynamique dans l'entrypoint (race conditions possibles)
- Visible et manipulable depuis l'hôte (`ls`, `rm`, etc.)
- Backup trivial : `tar czf backup.tar.gz ~/.ksf-web-data/`

**Tests** : `docker compose config` valide, AST Python OK, entrypoint fail-loud si bind mount absent.

---

### P0.2 — Suppression du `:-1000` default dans le compose (footgun)
**Fichier** : `templates/apps/ksf-web/compose.yml:11`

**Problème** : `user: "${APP_PUID:-1000}:${APP_PGID:-1000}"` — le default `1000` était appliqué silencieusement si `APP_PUID` n'était pas dans l'env (render manuel, shell différent). Pour un user hôte qui n'est PAS 1000 (ex: kesurof=1002), c'est un bug silencieux.

**Solution appliquée** : `user: "${APP_PUID}:${APP_PGID}"` (sans default). Si non set, le render produit `user: ":"` qui est invalide et le `docker compose up` échoue avec une erreur claire.

**Variables obligatoires documentées** dans le commentaire en tête du compose : `APP_PUID`, `APP_PGID`, `DOCKER_GID`, `KSF_REPO_DIR`, `BASE_DIR`, `NETWORK_NAME`, `TZ_VALUE`.

---

### ✅ P0.3 — FIXED : Modal race fix (queue de promises)
**Fichier** : `ksf-web/app/templates/partials/confirm_modal.html`

**Problème** : `b.dataset.confirming = '1'` puis `setTimeout(0)` fragile.

**Solution appliquée** : refonte complète du confirm_modal avec une **queue de promises**. Chaque `openConfirm()` retourne une Promise qui est résolue séquentiellement. Pas de race possible entre clics rapides ou htmx. Les modales s'enchaînent proprement (Étape 1/2 → Étape 2/2).

---

### P0.4 — I7 : Chiffrer les secrets au repos dans SQLite
**Fichiers** : `ksf-web/app/services/webhooks.py`, `migrations/002_encryption.sql`, `requirements.txt`

**Problème** : `webhook_endpoints.secret` et `audit_log.before/after` (peut contenir des secrets ksf.env) sont en clair dans la DB.

**Solution proposée** :
1. Ajouter `cryptography` aux deps (Fernet)
2. `app/crypto.py` : `encrypt(value, key) -> str`, `decrypt(value, key) -> str` avec clé dérivée de `KSF_WEB_SECRET_KEY` via `hkdf`
3. Migration 002 : ajouter colonne `secret_encrypted BLOB`, `before_encrypted BLOB`, `after_encrypted BLOB`
4. Chiffrement transparent dans `webhooks.update`/`audit.log` (détection auto de la colonne)
5. Backfill des valeurs existantes (script one-shot)

**Effort** : 1-2 jours

---

### ✅ P0.7 — FIXED : config_editor.commit regression (écriture du fichier manquante)
**Fichier** : `ksf-web/app/services/config_editor.py`

**Problème détecté** : lors de la séparation preview/commit (P1.5), le nouveau `commit()` avait perdu l'étape `write_atomic(proposed_content)`. L'utilisateur pouvait preview son diff, confirmer, mais ses modifications n'étaient jamais écrites dans ksf.env. Seule la fonction `commit_render()` (ksf.sh render) était appelée — sans modification préalable du fichier, elle re-render l'état existant.

**Solution appliquée** : `commit()` ré-intègre le flow complet :
1. Vérification du token preview/commit
2. Noop si pas de changement
3. Backup de l'état actuel (config_versions)
4. **Écriture atomique** du nouveau contenu (c'était l'étape manquante)
5. Dry-run render (rollback si échec)
6. Commit render (rollback si échec)
7. Sauvegarde post-commit

---

### P0.8 — Atomicité des migrations DB
**Fichier** : `ksf-web/app/db.py:_ensure_schema`

**Problème** : si une migration échoue entre `executescript()` et `INSERT INTO _migrations`, la table est créée mais la migration n'est pas marquée appliquée. Au prochain restart, `executescript()` re-tente avec `CREATE TABLE IF NOT EXISTS` (idempotent), mais l'INSERT peut à nouveau échouer (contrainte FK, etc.) → état corrompu.

**Solution proposée** : utiliser `BEGIN`/`COMMIT` explicites autour de chaque migration. Si quoi que ce soit échoue, `ROLLBACK` et la migration n'est PAS marquée appliquée.

✅ **FIXED** : `db._ensure_schema` utilise maintenant un `BEGIN`/`COMMIT` explicite avec `ROLLBACK` en cas d'exception.

---

### P0.9 — Le dispatch webhook fire-and-forget perd les exceptions
**Fichier** : `ksf-web/app/services/notifications.py`

**Problème** : `asyncio.create_task(webhooks.dispatch(...))` ne capture pas les exceptions. Si le task crash (bug dans le code webhook), l'exception est silencieusement avalée (Python n'affiche un warning que depuis 3.11).

**Solution appliquée** : `task.add_done_callback(_log_webhook_dispatch_result)` qui log l'exception si le task se termine avec une erreur.

---

### ✅ P0.5 — FIXED : SSRF check dans la route de création webhook
**Fichier** : `ksf-web/app/main.py` (webhook_create, webhook_update)

**Solution appliquée** : appel de `webhooks._is_safe_webhook_target(url, allow_private=False)` avant la création/update. Refuse les URLs pointant vers loopback, private RFC1918, link-local, multicast, AWS metadata service. Retourne 400 avec message explicite.

**Tests** : `http://127.0.0.1/` → BLOCK, `http://169.254.169.254/` → BLOCK, `http://google.com/` → OK.

---

### ✅ P0.6 — FIXED : Permissions DB SQLite (chmod 600)
**Fichier** : `ksf-web/app/db.py:30-39`

**Problème** : Le DB SQLite contient des données sensibles (audit, secrets webhook si chiffrés). Permissions par défaut peuvent être laxistes.

**Solution appliquée** : dans `db.py:get_conn()` après création du fichier :
```python
is_new = not os.path.exists(config.DB_PATH)
_conn = await aiosqlite.connect(config.DB_PATH, isolation_level=None)
if is_new:
    try:
        os.chmod(config.DB_PATH, 0o600)
    except OSError:
        logger.warning("Impossible de chmod 600 sur %s", config.DB_PATH)
```

Le dossier parent est `chown` au bon UID par l'entrypoint `gosu` (cf P0.1).

---

## 🟠 P1 — Bugs & dette importante

### ✅ P1.1 — FIXED : Subprocess sync dans ksf_commands
**Fichier** : `ksf-web/app/ksf_commands.py`

**Problème** : `subprocess.run` synchrone bloque l'event loop.

**Solution appliquée** : `run_command` et `run_app_command` sont maintenant `async`, utilisent `asyncio.to_thread(_run_subprocess_sync, ...)` en interne. L'event loop reste réactif pendant les 30-120s d'une action KSF. Tous les callers (8 routes) ont été mis à jour avec `await`.

---

### ✅ P1.2 — FIXED : docker_client lock + health check
**Fichier** : `ksf-web/app/docker_client.py`

**Solution appliquée** :
- `get_client()` reste sync (utilisé par les helpers bas-niveau)
- `get_client_async()` est la version async avec `asyncio.Lock` + `client.ping()` + reset auto
- Health check via `asyncio.to_thread(client.ping)` pour ne pas bloquer
- Reset + recréation si la connexion est morte (utile si le daemon Docker redémarre)

---

### ✅ P1.3 — FIXED : stderr séparé dans _run_job
**Fichier** : `ksf-web/app/services/jobs.py`

**Solution appliquée** : `stderr=PIPE` séparé, lecture parallèle via `asyncio.gather(read_stream(stdout, ""), read_stream(stderr, "[stderr] "))`. Les events SSE portent maintenant un champ `stream: "stdout" | "stderr"` pour permettre au front de styler différemment.

---

### P1.4 — Notifications : déduplication / throttling
**Fichier** : `ksf-web/app/services/notifications.py`

**Problème** : Un job qui échoue en boucle (ex: cron de monitoring qui crashe toutes les 5min) spamme les notifications. Pas de dédup.

**Solution** :
1. Ajouter colonne `dedup_key TEXT` (hash de `kind + target + error_signature`)
2. Index unique partiel sur `(dedup_key) WHERE created_at > datetime('now', '-1 day')`
3. Si une notif existe déjà dans la fenêtre, incrémenter un compteur `repeat_count` au lieu de créer

**Effort** : 1 jour

---

### ✅ P1.8 — FIXED : webhook dispatch parallèle + non bloquant
**Fichier** : `ksf-web/app/services/webhooks.py`

**Problème** : `dispatch()` itérait séquentiellement sur les endpoints (`await _send_with_retry` en boucle). 5 webhooks × 30s = 2.5 min pour 1 notification. De plus, `_send_with_retry` utilisait `urllib.request.urlopen` sync qui bloque l'event loop 10s par attempt.

**Solution appliquée** :
- `dispatch()` utilise `asyncio.gather(*[_send_with_retry(...) for ep in matching], return_exceptions=True)` — parallèle + isolation d'erreurs
- `_send_with_retry` utilise `await asyncio.to_thread(urllib.request.urlopen, ...)` pour ne pas bloquer l'event loop
- `resp.close()` ajouté pour libérer les ressources

---

### ✅ P1.9 — FIXED : line numbers stdout/stderr non uniques
**Fichier** : `ksf-web/app/services/jobs.py`

**Problème** : `read_stream(stdout)` et `read_stream(stderr)` avaient chacun leur propre compteur `line_count` qui démarrait à 0. Le frontend voyait `n: 1, 2, ...` pour stdout ET `n: 1, 2, ...` pour stderr → numéros dupliqués.

**Solution appliquée** : compteur `counter` partagé entre les deux streams, protégé par `asyncio.Lock` (parce que `asyncio.gather` exécute en parallèle). Numérotation unique et monotone.

---

### ✅ P1.10 — FIXED : magic string pour cancel
**Fichier** : `ksf-web/app/services/jobs.py`

**Problème** : `"(cancelled by user)"` était une magic string répétée dans `cancel()` et `_run_job()`.

**Solution appliquée** : constante `CANCEL_MARKER` au top du module.

---

### ✅ P1.5 — FIXED : config_editor commit token (preview/commit binding)
**Fichier** : `ksf-web/app/services/config_editor.py`, `ksf-web/app/templates/config.html`

**Problème** : un caller malveillant peut soumettre n'importe quel contenu dans `/api/config/commit`.

**Solution appliquée** : à chaque `preview()` réussi, un **token HMAC-SHA256 signé** est généré, liant nonce + expiry + longueur du contenu. Le `commit()` exige ce token, le re-vérifie, et refuse si le contenu ou le timing ne match pas. Expire après 5 min. Impossible de commit un contenu qui n'a pas été preview.

---

### ✅ P1.6 — FIXED : webhook_create idempotence
**Fichiers** : `migrations/002_webhook_idempotence.sql`, `webhooks.py`, `main.py`

**Solution appliquée** :
1. Migration 002 : `CREATE UNIQUE INDEX idx_webhook_unique_name_url ON webhook_endpoints (name, url)`
2. `webhooks.create()` capture `aiosqlite.IntegrityError` → lève `ValueError`
3. Route `webhook_create` capture `ValueError` → 409 Conflict

---

### ✅ P1.7 — FIXED : validation actor
**Fichier** : `ksf-web/app/main.py:_client_actor`

**Solution appliquée** :
```python
user = user.strip()[:64]
user = "".join(c for c in user if c.isprintable())
```
Défense en profondeur contre un attaquant contrôlant l'header X-Forwarded-User.

---

## 🟡 P2 — Qualité & performance

### P2.1 — Cache `list_containers` avec TTL court
**Fichier** : `ksf-web/app/docker_client.py:67-108`

**Problème** : Le dashboard fait un appel Docker API toutes les 15s. 4-5 widgets × 15s = ~20 calls/min.

**Solution** : cache `@functools.lru_cache(maxsize=1)` avec invalidation toutes les 3s via un timestamp stocké dans une variable globale.

**Effort** : 0.5 jour

---

### P2.2 — Q1 : Dédup logique dashboard ↔ dashboard_summary
**Fichier** : `ksf-web/app/main.py:217-269` vs `356-401`

**Problème** : code dupliqué entre `dashboard` (full HTML) et `_dashboard_summary` (partial).

**Solution** : extraire en helper `_render_dashboard(request, partial=False)`. Le endpoint `/` appelle `partial=False`, l'API summary appelle `partial=True`.

**Effort** : 0.5 jour

---

### ✅ P2.3 — FIXED : 5 copies de _utcnow() → app/utils.py
**Fichiers** : nouveau `app/utils.py` + 4 services refactorés

**Solution appliquée** : `app/utils.py` expose `utcnow_str()` (format ISO-like) et `utcnow_dt()` (datetime tz-aware). Les 4 services (`audit`, `jobs`, `notifications`, `webhooks`) font `from app.utils import utcnow_str as _utcnow` pour garder leurs call sites inchangés.

---

### P2.4 — Q4 : Focus trap dans modale
**Fichier** : `ksf-web/app/templates/partials/confirm_modal.html`

**Problème** : Tab peut sortir de la modale. Pas d'inert sur le main.

**Solution** : mini focus-trap + `inert` sur `.main` quand modale ouverte.

**Effort** : 0.5 jour

---

### P2.5 — Q6 : UX de la double confirmation
**Fichier** : `ksf-web/app/templates/partials/confirm_modal.html` + `base.html`

**Problème** : pour `data-confirm2`, deux modales s'enchaînent, c'est confus.

**Solution** : indicateur "Étape 1/2" dans le titre, ou deux modales empilées avec backdrop séparé.

**Effort** : 0.5 jour

---

### P2.6 — Q7 : Audit log : lazy-load before/after
**Fichier** : `ksf-web/app/services/audit.py:42-65`, `ksf-web/app/main.py:839-845`

**Problème** : la page `/audit` charge tous les `before`/`after` JSON même quand non affichés.

**Solution** : `SELECT id, created_at, actor, action, target, job_id FROM audit_log` dans la liste. Endpoint `/api/audit/{id}` qui renvoie le full entry avec before/after.

**Effort** : 0.5 jour

---

### ✅ P2.7 — FIXED : config_versions lazy-load content
**Fichier** : `ksf-web/app/services/config_editor.py`

**Solution appliquée** : `list_versions()` ne SELECT plus `content`. Retourne `id`, `actor`, `reason`, `created_at`, `size`. Le contenu complet reste accessible via `get_version(version_id)`.

---

### P2.8 — Q10 : Webhook dispatch en parallèle
**Fichier** : `ksf-web/app/services/webhooks.py:88-101`

**Problème** : 5 webhooks × 30s séquentiel = 2.5 min pour 1 notification.

**Solution** : `await asyncio.gather(*[_send_with_retry(ep, p) for ep in matching])`.

**Effort** : 10 min

---

### ✅ P2.9 — FIXED : Webhook dispatch fire-and-forget
**Fichier** : `ksf-web/app/services/notifications.py`

**Solution appliquée** : `asyncio.create_task(webhooks.dispatch(...))` au lieu de l'await. L'UI ne bloque plus sur les webhooks lents. Fallback synchrone si pas de loop active (rare). Callback `add_done_callback` pour capturer les exceptions silencieuses (P1.8).

---

### ✅ P2.25 — FIXED : EventBus silently drops messages on queue full
**Fichier** : `ksf-web/app/services/events.py`

**Problème** : `q.put_nowait(payload)` raises `QueueFull` qui était silencieusement ignoré (`except QueueFull: pass`). Les subscribers avec un consumer lent perdaient des events sans aucune trace.

**Solution appliquée** : `logger.warning(...)` quand un message est dropped, avec channel/event/queue_size/maxsize pour le diagnostic.

---

### ✅ P2.26 — FIXED : config_editor._serialize ne quote pas les valeurs
**Fichier** : `ksf-web/app/services/config_editor.py`

**Problème** : `DOMAIN=value with spaces` produit une ligne .env non-quotée que bash parse mal. Aussi, les valeurs avec `\n` corrompaient le fichier.

**Solution appliquée** :
- Rejet des valeurs contenant `\n` ou `\r` (raise ValueError)
- Auto-quote avec double-quotes si la valeur contient espace, tab ou guillemet
- Escape des guillemets internes par `\\"`

---

### ✅ P2.27 — FIXED : webhook URL validation incomplète
**Fichier** : `ksf-web/app/services/webhooks.py:_is_safe_webhook_target`

**Problème** : checkait scheme + IP privée, mais pas la structure de l'URL. `https://` tout seul ou `https:///path` passait.

**Solution appliquée** : ajout check `parsed.netloc` non-vide (rejette les URLs sans host).

---

### ✅ P2.28 — FIXED : config_editor._run_render sans HOME
**Fichier** : `ksf-web/app/services/config_editor.py`

**Problème** : l'env passé à ksf.sh n'avait pas HOME défini, contrairement à `ksf_commands.EXEC_ENV` qui le set. Bash commands qui dépendent de HOME (curl avec ~/.curlrc, ssh) échouaient silencieusement.

**Solution appliquée** : `env={..., "HOME": "/home/appuser"}` dans `_run_render`.

---

### ✅ P2.29 — FIXED : audit.log accepte des payloads géants
**Fichier** : `ksf-web/app/services/audit.py`

**Problème** : un `before`/`after` contenant un dump de 50Ko (ex: ksf.env complet) fait grossir la DB sans limite. Aussi, `str(obj)` sur un objet complexe produit un output illisible et énorme.

**Solution appliquée** :
- Constante `_MAX_BEFORE_AFTER_BYTES = 8192`
- Troncature avec marqueur `"... [truncated, original N bytes]"`
- Log warning si on fallback à `str()` (JSON serialization failed)

---

### ✅ P2.30 — FIXED : dead code dans backups.py
**Fichier** : `ksf-web/app/services/backups.py`

**Problème** : `backup_file_size()` et `list_for_restore()` étaient définis mais jamais appelés (dead code).

**Solution appliquée** : supprimés.

---

### ✅ P1.8/P1.9/P1.10 — FIXED : voir sections P1 ci-dessus
(webhook dispatch parallèle + non bloquant via `asyncio.gather` + `asyncio.to_thread`, line numbers stdout/stderr uniques, magic string remplacé par `CANCEL_MARKER`)

---

### P2.31 — Encore plus de code mort à nettoyer
**Fichiers** : `services/audit.py:list_entries` charge `before`/`after` complets (P2.6 lazy-load pas appliqué)

**Problème** : la TODO mentionne lazy-load before/after pour `/audit` mais ce n'est pas implémenté. La route `audit_export` charge les 10000 entrées complètes.

**Solution** : modifier `audit.list_entries` pour ne pas sélectionner `before`/`after` par défaut, ajouter un endpoint `/api/audit/{id}` qui renvoie le full entry.

**Effort** : 0.5 jour

---

### P2.32 — `webhooks.dispatch` ne loggue pas les erreurs
**Fichier** : `ksf-web/app/services/webhooks.py:_send_with_retry`

**Problème** : quand un webhook échoue, on log un warning à chaque attempt mais on ne loggue jamais la cause finale avec contexte (nom, URL, dernière exception). Difficile à debug.

**Solution** : capturer la dernière exception dans la variable et la logger en `error` au final.

**Effort** : 10 min

---

### P2.33 — `notifications.list_all` ne filtre pas par catégorie
**Fichier** : `ksf-web/app/services/notifications.py`

**Problème** : impossible de lister uniquement les notifications d'une catégorie (ex: `backup`, `security`). L'UI ne peut pas filtrer.

**Solution** : ajouter paramètre `category: str | None = None` à `list_all`.

**Effort** : 5 min

---

### P2.34 — `notifications.mark_all_read` ne loggue pas
**Fichier** : `ksf-web/app/services/notifications.py`

**Problème** : pas de log quand l'user marque tout comme lu, alors que c'est une action notable côté audit.

**Solution** : log `logger.info("User marked all notifications as read (N)")`.

**Effort** : 2 min

---

### P2.35 — `webhooks._send_with_retry` n'a pas de timeout adaptatif
**Fichier** : `ksf-web/app/services/webhooks.py:_send_with_retry`

**Problème** : timeout fixe 10s. Pour des webhooks internes rapides (<100ms), on perd 9.9s à attendre un timeout inutile. Pour des webhooks lents, 10s est trop court.

**Solution** : timeout adaptatif basé sur le p95 historique (nécessite tracking). Pour l'instant, juste ajouter un `await asyncio.wait_for(..., timeout=10)` au lieu de `to_thread` avec timeout param.

**Effort** : 0.5 jour

---

### P2.36 — `events.sse_format` n'encode pas les multi-lignes proprement
**Fichier** : `ksf-web/app/services/events.py:sse_format`

**Problème** : si `data` est un dict avec une string contenant `\n`, chaque ligne doit être préfixée par `data: ` selon la spec SSE. Le code le fait mais pour les strings JSON qui contiennent des newlines, ça peut casser l'encodage SSE côté client.

**Solution** : utiliser `json.dumps(data, default=str, ensure_ascii=False)` qui escape les newlines. Tester avec des payloads contenant des newlines.

**Effort** : 15 min

---

### P2.37 — Le lifespan dans main.py n'est pas auto-injecté correctement
**Fichier** : `ksf-web/app/main.py:25`

**Problème** : `app = FastAPI(..., lifespan=lifespan)` est appelé AVANT que `lifespan` soit défini (l.28). Python évalue les arguments au moment de l'appel, donc `lifespan` est résolu via lookup dans le scope du module au moment où `FastAPI.__init__` est appelé. Ça fonctionne grâce à la lazy lookup, mais c'est fragile et le linter va rouspéter.

**Solution** : définir `lifespan` AVANT `app = FastAPI(...)`.

**Effort** : 1 min

---

### P2.38 — `_action_result` log_path non sanitisé
**Fichier** : `ksf-web/app/main.py`

**Problème** : `log_path=log_path or None` où `log_path` vient de `_save_full_output(prefix, output)`. Si `prefix` contient un `/`, le log est écrit dans un sous-dossier (ce qui est intentionnel pour `install-ksf-web`), mais si `prefix` contient `..`, on pourrait écrire hors de LOG_DIR.

**Solution** : valider `prefix` (rejeter `/`, `..`, caractères spéciaux) dans `_save_full_output`.

**Effort** : 5 min

---

### P2.39 — `csrf_signer` global non testé
**Fichier** : `ksf-web/app/main.py:46`

**Problème** : `_csrf_signer = URLSafeTimedSerializer(config.CSRF_SECRET, salt=config.CSRF_SALT)`. Si `config.CSRF_SECRET` change (rotation), tous les cookies existants deviennent invalides → tous les users doivent se re-loguer. Pas de mécanisme de rotation.

**Solution** : supporter une liste de salts/keys, essayer le premier puis les autres. Ou avoir un TTL court + auto-refresh du cookie.

**Effort** : 0.5 jour

---

### P2.40 — `_client_actor` ne valide pas l'email
**Fichier** : `ksf-web/app/main.py:_client_actor`

**Problème** : `X-Forwarded-Email` est utilisé sans validation que c'est bien un email. Un attaquant contrôlant l'header peut injecter n'importe quoi.

**Solution** : si le user est `email@domain`, valider le format. Sinon, fallback sur `X-Forwarded-User`.

**Effort** : 5 min

---

### P2.41 — `webhooks.list_all` ne filtre pas par `enabled`
**Fichier** : `ksf-web/app/services/webhooks.py:list_all`

**Problème** : la page `/settings/webhooks` liste TOUS les webhooks, y compris désactivés. C'est intentionnel pour la gestion, mais la page devient confuse avec beaucoup d'entrées.

**Solution** : ajouter query param `?enabled_only=true` ou afficher un toggle "Show disabled".

**Effort** : 15 min

---

### P2.42 — `webhooks.test` ne capture pas la réponse
**Fichier** : `ksf-web/app/main.py:webhook_test`

**Problème** : le test fire un webhook mais ne renvoie pas la réponse (status, body). L'user ne sait pas si son webhook est OK ou KO.

**Solution** : retourner `{success, status, body, latency_ms}`.

**Effort** : 15 min

---

### P2.43 — `events.subscribe` ne nettoie pas les subscribers zombies
**Fichier** : `ksf-web/app/services/events.py:EventBus.subscribe`

**Problème** : si un consumer SSE crash (exception, timeout réseau) sans cleanup, sa queue reste dans `_subscribers` indéfiniment. Avec 100 connexions abortées, 100 queues orphelines.

**Solution** : 
- Heartbeat côté consumer (ping toutes les 30s)
- Timeout côté publisher : si `put_nowait` échoue après 5s, supprime le subscriber
- Ou utiliser un TTL sur les subscribers

**Effort** : 1 jour

---

### P2.44 — `db._ensure_schema` ignore les migrations avec version non-int
**Fichier** : `ksf-web/app/db.py`

**Problème** : si quelqu'un commit un fichier `foo_bar.sql` (sans préfixe numérique), il est silencieusement ignoré. Pas de warning.

**Solution** : logger un warning pour les fichiers qui ne matchent pas le pattern `^[0-9]+_.*\.sql$`.

**Effort** : 5 min

---

### P2.45 — `webhooks` URL n'est pas normalisée
**Fichier** : `ksf-web/app/services/webhooks.py:create/update`

**Problème** : `https://example.com/path` et `https://example.com/path/` sont considérés différents. `https://EXAMPLE.com` est différent de `https://example.com`. Le unique constraint ne match pas.

**Solution** : normaliser l'URL (lowercase host, strip trailing slash sauf si path vide) avant stockage.

**Effort** : 15 min

---

### P2.46 — `notifications.create` ne loggue pas le niveau
**Fichier** : `ksf-web/app/services/notifications.py:create`

**Problème** : pas de log quand une notif est créée. Difficile à tracer en cas de bug (ex: webhooks ne partent pas).

**Solution** : `logger.info("Notification %s created (level=%s category=%s)", nid, level, category)`.

**Effort** : 2 min

---

### P2.47 — `webhooks.create` n'a pas de validation de longueur
**Fichier** : `ksf-web/app/services/webhooks.py:create`

**Problème** : un user peut créer un webhook avec un nom de 1Mo. Pas de limite.

**Solution** : valider `len(name) <= 100` et `len(url) <= 2048`.

**Effort** : 5 min

---

### P2.48 — Le template `partials/dashboard_summary.html` n'a pas d'erreur fallback
**Fichier** : `ksf-web/app/templates/partials/dashboard_summary.html`

**Problème** : si `/api/dashboard/summary` crash (e.g., DB lock), le partial HTML ne s'affiche pas et le dashboard est cassé.

**Solution** : wrap le partial dans un try/except côté serveur qui renvoie un message d'erreur formaté au lieu d'un 500.

**Effort** : 15 min

---

### P2.49 — `webhooks._send_with_retry` n'a pas de circuit breaker
**Fichier** : `ksf-web/app/services/webhooks.py`

**Problème** : si un endpoint webhook est down, on lui envoie 3 retries × 10s = 30s de délai pour CHAQUE notification. Multiplié par les notifications auto de jobs, ça peut geler le système.

**Solution** : circuit breaker simple : si un webhook a échoué N fois récemment, skip temporairement (1h par ex). Reset si succès.

**Effort** : 1 jour

---

### P2.50 — `notifications.create` n'enforce pas une limite de taille
**Fichier** : `ksf-web/app/services/notifications.py`

**Problème** : un job peut générer un `body` de 1Mo (par ex: dump d'erreur). La DB grossit.

**Solution** : tronquer le body à 4Ko, ajouter marqueur `[truncated]`.

**Effort** : 5 min

---

### P2.10 — Q13 : `urllib.request.urlopen` synchrone
**Fichier** : `ksf-web/app/services/webhooks.py:104-126`

**Problème** : bloque l'event loop 10s par attempt.

**Solution** : `await asyncio.to_thread(urllib.request.urlopen, ...)` ou utiliser `httpx.AsyncClient` (déjà populaire dans l'écosystème FastAPI).

**Effort** : 0.5 jour

---

### P2.11 — Dashboards multiples qui rechargent en cascade
**Fichiers** : `dashboard.html`, `partials/dashboard_summary.html`, `partials/jobs_list.html`, `partials/notifications_list.html`, `container_detail.html`

**Problème** : chaque page a son propre `hx-trigger="every Ns"`. Si l'user ouvre 5 onglets, c'est 5× le trafic.

**Solution** : introduire un EventBus côté client (`window.dispatchEvent`) pour synchroniser les états. Le SSE `/api/notifications/unread-count` peut aussi servir d'horloge commune.

**Effort** : 1-2 jours

---

### P2.12 — Phase 3 — Page `/settings` complète
**Fichiers** : `templates/settings.html` (nouveau), `services/config_editor.py`

**Contenu** :
- `/settings/general` : timezone, langue UI, nom de la plateforme
- `/settings/webhooks` : déjà fait
- `/settings/security` : rotation du CSRF secret, session timeout
- `/settings/maintenance` : accès rapide à doctor, render, restart système

**Effort** : 2-3 jours

---

### P2.13 — Phase 3 — Light theme
**Fichiers** : `static/app.css`, `templates/base.html`

**Solution** : override `:root[data-theme="light"]` avec tokens clairs. Toggle dans settings.

**Effort** : 1-2 jours

---

### P2.14 — Phase 3 — Endpoint `/health`
**Fichier** : `ksf-web/app/main.py`

**Solution** : `GET /health` → 200 si DB lisible + Docker joignable, 503 sinon. Réponse JSON : `{"db": "ok", "docker": "ok", "version": "x.y.z"}`. Pour monitoring externe (UptimeRobot, etc.).

**Effort** : 0.5 jour

---

### P2.15 — Phase 3 — Rate limiting
**Fichiers** : `main.py` (middleware), `services/rate_limit.py` (nouveau)

**Limites** :
- GET : 100 req/min par IP
- POST non-sensibles : 30 req/min
- POST destructifs (install/remove) : 5 req/5min
- SSE : 5 connexions concurrentes par IP
- Headers `X-RateLimit-*` standards

**Backend** : token bucket en mémoire (simple) ou Redis si multi-instance.

**Effort** : 1-2 jours

---

## 🟢 P3 — Polish & refactoring

### P3.1 — Phase 3 — Branding unifié (KSF ↔ Serverbox)
**Fichier** : `ksf-web/app/templates/base.html:28-34`

**Problème** : "ksf" dans la brand-icon, "Serverbox" dans le titre, "KSF" dans le footer.

**Solution** : choisir une seule marque (suggestion : "KSF" partout, "Serverbox" comme sous-titre "votre serveur auto-hébergé"). Ajouter favicon SVG.

**Effort** : 0.5 jour

---

### P3.2 — Refactor `main.py` en blueprints
**Fichier** : `ksf-web/app/main.py` (1030 lignes)

**Solution** :
- `routes/pages.py` (GET HTML)
- `routes/actions.py` (POST mutations)
- `routes/api.py` (JSON / partials)
- `routes/sse.py` (EventSource)
- `app.state` pour les singletons (DB, jobs, etc.)

**Effort** : 2-3 jours

---

### P3.3 — Tests automatisés
**Fichiers** : `ksf-web/tests/` (nouveau dossier)

**Couverture minimale** :
- `test_csrf.py` : cookie set, GET, POST, POST sans token, POST token invalide
- `test_jobs.py` : enqueue, lifecycle, lock, recovery, cancel
- `test_config_editor.py` : validation, atomic write, dry-run, rollback
- `test_webhooks.py` : HMAC, retry, SSRF blocking
- `test_audit.py` : log + list + export
- `test_backups.py` : safe_path (path traversal, symlinks)
- `test_sse.py` : reconnect avec Last-Event-ID

**Outils** : `pytest` + `pytest-asyncio` + `httpx.AsyncClient` (TestClient de FastAPI).

**Effort** : 3-5 jours

---

### P3.4 — Documentation README ksf-web
**Fichier** : `ksf-web/README.md` (nouveau)

**Contenu** :
- Architecture (services, DB, SSE, jobs)
- Variables d'env
- Procédure de mise à jour
- Procédure de debug (logs, DB inspection, replay SSE)
- Modèle de sécurité (CSRF, OAuth2 Proxy, X-Forwarded-User)
- Limitations connues (single-user, in-memory EventBus, etc.)

**Effort** : 1 jour

---

### P3.5 — `CHANGELOG.md`
**Fichier** : `ksf-web/CHANGELOG.md` (nouveau)

**Format** : Keep a Changelog. Sections `Added`, `Changed`, `Fixed`, `Security` par version.

**Effort** : 0.5 jour (1 fois, à maintenir ensuite)

---

### ✅ P3.6 — FIXED : index audit_log.job_id
**Fichier** : `migrations/003_indexes.sql`

**Solution appliquée** : 2 index ajoutés :
- `idx_audit_log_job_id` (partiel WHERE job_id IS NOT NULL) pour les requêtes par job
- `idx_audit_log_created_action` (composite created_at DESC, action) pour la page /audit

---

### P3.7 — Pagination des notifications
**Fichier** : `ksf-web/app/services/notifications.py:57-69`

**Problème** : `list_all(limit=100)` retourne max 100. Pas de pagination.

**Solution** : cursor-based sur `created_at` + `id`, avec un endpoint `/api/notifications?before=X&limit=N`.

**Effort** : 0.5 jour

---

### ✅ P3.8 — FIXED : FastAPI lifespan natif
**Fichier** : `ksf-web/app/main.py`

**Solution appliquée** : `app = FastAPI(title=..., lifespan=lifespan)` au lieu de `app.router.lifespan_context = lifespan`. Style moderne recommandé par FastAPI 0.115+.

---

### P3.9 — Lock UI sur ops exclusives
**Fichiers** : `ksf-web/app/services/jobs.py`, templates

**Solution** : endpoint `GET /api/locks` qui renvoie les `lock_key` actifs. UI : boutons désactivés + tooltip "Une opération est en cours sur cette cible".

**Effort** : 0.5 jour

---

### P3.10 — Expiration des logs de jobs
**Fichier** : `migrations/003_log_retention.sql` (nouveau), `services/jobs.py`

**Problème** : les logs de jobs s'accumulent indéfiniment dans `${BASE_DIR}/logs/ksf-web/jobs/`.

**Solution** : cron-like retention : `DELETE FROM jobs WHERE created_at < datetime('now', '-30 days')` + supprimer les fichiers .log correspondants. Cron via `apscheduler` ou simple check au démarrage.

**Effort** : 1 jour

---

### P3.11 — TypedDict / Pydantic models pour les services
**Fichiers** : tous les `services/*.py`

**Solution** : remplacer les `dict[str, Any]` par des TypedDict ou Pydantic. Meilleure type safety, validation auto dans FastAPI.

**Effort** : 2-3 jours (refactor profond)

---

### P3.12 — Container resource monitoring (CPU/RAM/disk)
**Fichiers** : `docker_client.py`, dashboard

**Solution** : utiliser `container.stats(stream=False)` pour récupérer CPU%, memory usage, network I/O. Affichage en temps réel dans la rack.

**Effort** : 1-2 jours

---

### P3.13 — Webhook health checks périodiques
**Fichiers** : `services/webhooks.py`, cron

**Solution** : tester périodiquement les webhooks (ping avec un payload factice), marquer `healthy` ou `unhealthy`, alerter dans l'UI.

**Effort** : 1 jour

---

### P3.14 — Phase 4 — Tags Git et versioning
**Solution** : `git tag v2.0.0` après stabilisation, `git tag v2.1.0` après chaque release, CHANGELOG mis à jour.

**Effort** : continu

---

## Résumé par effort

| Catégorie | Items actifs | Items faits | Effort restant |
|---|---|---|---|
| 🔴 P0 | 1 (P0.4 chiffrement) | 7 (P0.1, P0.2, P0.3, P0.5, P0.6, P0.7, P0.8, P0.9) | ~2 jours |
| 🟠 P1 | 1 (P1.4 dedup notifs) | 9 (P1.1, P1.2, P1.3, P1.5, P1.6, P1.7, P1.8, P1.9, P1.10) | ~1 jour |
| 🟡 P2 | 32 | 9 (P2.3, P2.7, P2.9, P2.25, P2.26, P2.27, P2.28, P2.29, P2.30) | ~25 jours |
| 🟢 P3 | 12 | 2 (P3.6, P3.8) | ~18 jours |
| **Total** | **46 actifs** | **27 faits** | **~46 jours** |

## Liens utiles

- `ROADMAP.md` : vision stratégique
- `AGENTS.md` : conventions du projet
- Sessions précédentes :
  - Phase 0 + 1 + 2 (architecture complète)
  - Debug déploiement (6 bugs en cascade résolus)
  - Code review (40 findings, 14 fixés en Phase 2)
  - Application du plan TODO (12 items cette session)
  - **Review post-implementation** (10 nouveaux findings P1/P2 ajoutés à cette review)

## Review post-implementation (juin 2026)

Cette review a détecté plusieurs problèmes dans les changements récents :

**🔴 Critique (P0)** :
- **P0.7** : regression dans `config_editor.commit` — l'écriture du fichier ksf.env était manquante ! Corrigé.

**🟠 Important (P1)** :
- **P1.8** : fire-and-forget perdait les exceptions silencieusement. Corrigé.
- **P1.9** : webhook dispatch séquentiel et bloquant. Corrigé (parallèle + non bloquant).
- **P1.10** : magic string pour cancel. Corrigé (constante `CANCEL_MARKER`).

**🟡 Qualité (P2)** :
- P2.25 à P2.30 : corrigés (EventBus drops, config_editor quoting, webhook URL validation, HOME dans env, audit truncation, dead code).
- P2.31 à P2.50 : 19 nouveaux findings identifiés, à traiter dans les prochaines sessions.

---

## Leçon apprise (review du 24 juin 2026)

**Contexte** : après une longue session de refactoring où j'ai ajouté du code async dans `notifications.py` et `webhooks.py`, j'ai oublié d'ajouter `import asyncio` dans les deux fichiers. Le container a crashé au démarrage avec `NameError: name 'asyncio' is not defined`.

**Cause** : j'ai patché trop vite, sans re-vérifier que tous les symboles utilisés étaient importés. Mon analyse statique précédente ne couvrait que les annotations de type, pas les usages runtime.

**Fix appliqué** :
- `notifications.py` : `import asyncio` ajouté (ligne 8)
- `webhooks.py` : `import asyncio` ajouté (ligne 2)
- AGENTS.md enrichi avec une section "Validation ksf-web (Python)" qui inclut un check d'imports.

**Engagement pour la suite** : avant chaque modification async, je dois vérifier explicitement que les nouveaux symboles utilisés sont importés. Pas de patchs rapides sans analyse d'impact.
