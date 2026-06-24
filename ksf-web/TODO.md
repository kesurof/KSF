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

### P0.1 — I2 : Fix race dans le modal de confirmation
**Fichier** : `ksf-web/app/templates/base.html:199-223`

**Problème** : le mécanisme `b.dataset.confirming = '1'` puis `setTimeout(0)` pour clear est fragile. Si htmx traite l'event de manière asynchrone, le flag peut être cleared trop tôt.

**Solution proposée** :
```javascript
// Approche par queue de promises
var pending = [];
function confirmDialog(opts) {
    return new Promise(function (resolve) {
        pending.push({ resolve: resolve, opts: opts });
        if (pending.length === 1) showNextModal();
    });
}
function showNextModal() {
    if (pending.length === 0) return;
    var item = pending[0];
    // ... show modal, on resolve: pending.shift(); showNextModal();
}
```
**Effort** : 0.5 jour

---

### P0.2 — I7 : Chiffrer les secrets au repos dans SQLite
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

### P0.3 — Intégrer le check SSRF dans la route de création webhook
**Fichier** : `ksf-web/app/main.py:920-924`

**Problème** : `_is_safe_webhook_target` est défini dans `webhooks.py` mais pas encore appelé dans la route.

**Solution** :
```python
@app.post("/api/webhooks")
async def webhook_create(request: Request):
    body = await request.json()
    # ...
    ok, err = webhooks._is_safe_webhook_target(url, allow_private=False)
    if not ok:
        raise HTTPException(status_code=400, detail=f"URL refusée : {err}")
    # ...
```
Idem pour `webhook_update` quand l'URL est modifiée.

**Effort** : 5 min

---

### P0.4 — Permissions DB SQLite (chmod 600)
**Fichier** : `ksf-web/Dockerfile` ou `ksf-web/app/db.py`

**Problème** : Le DB SQLite contient des données sensibles (audit, secrets webhook si chiffrés). Permissions par défaut peuvent être laxistes.

**Solution** : dans `db.py:get_conn()` après création du fichier :
```python
import os
if _conn is None:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    new_file = not os.path.exists(config.DB_PATH)
    _conn = await aiosqlite.connect(config.DB_PATH, isolation_level=None)
    if new_file:
        os.chmod(config.DB_PATH, 0o600)
```
Idem pour le dossier parent : `os.chmod(dir, 0o700)`.

**Effort** : 10 min

---

## 🟠 P1 — Bugs & dette importante

### P1.1 — Subprocess sync dans `ksf_commands.run_command` / `run_app_command`
**Fichier** : `ksf-web/app/ksf_commands.py:44-87`

**Problème** : `subprocess.run` synchrone bloque l'event loop pendant l'exécution. Toutes les actions `app.sh install/update/remove/restart/...` peuvent bloquer l'UI 30-120s.

**Solution** : convertir en `await asyncio.to_thread(subprocess.run, ...)`. Refactor minimal, API inchangée.

**Effort** : 0.5 jour

---

### P1.2 — `docker_client.get_client` global sans lock
**Fichier** : `ksf-web/app/docker_client.py:19-30`

**Problème** : Le global `_docker_client` peut être recréé en double lors d'appels concurrents. Pas de reset si la connexion est perdue (impossible de récupérer sans restart du conteneur).

**Solution** :
1. Ajouter un `asyncio.Lock` autour de l'init
2. Ajouter un health check périodique (`client.ping()`)
3. En cas d'échec, reset du global et re-init

**Effort** : 0.5 jour

---

### P1.3 — I8 : Capturer stderr séparément dans `_run_job`
**Fichier** : `ksf-web/app/services/jobs.py:259-295`

**Problème** : `stderr=STDOUT` perd la distinction. Les erreurs du subprocess sont mélangées avec stdout.

**Solution** :
```python
stdout, stderr = proc.stdout, proc.stderr
async def read_stream(stream, prefix):
    while True:
        chunk = await stream.read(4096)
        if not chunk: return
        # Préfixer les lignes stderr avec [stderr]
        ...

await asyncio.gather(read_stream(stdout, ""), read_stream(stderr, "[stderr] "))
```

**Effort** : 0.5 jour

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

### P1.5 — Validation de la cohérence du `proposed_content` dans config_editor.commit
**Fichier** : `ksf-web/app/main.py:980-987`, `ksf-web/app/services/config_editor.py:267-273`

**Problème** : Un caller peut soumettre n'importe quel contenu JSON comme `proposed`. Pas de lien avec le preview précédent.

**Solution** : générer un token signé dans `preview()`, le retourner au client, l'exiger dans `commit()`.

**Effort** : 0.5 jour

---

### P1.6 — `webhook_create` n'a pas d'idempotence
**Fichier** : `ksf-web/app/services/webhooks.py:54-63`

**Problème** : deux POSTs créent deux webhooks. Pas de contrainte d'unicité.

**Solution** : contrainte unique sur `(name, url)` dans la migration 003 + gestion `IntegrityError` → 409.

**Effort** : 0.5 jour

---

### P1.7 — Validation `actor` dans audit (longueur, format)
**Fichier** : `ksf-web/app/main.py:176-181`

**Problème** : Si un attaquant contrôle l'header `X-Forwarded-User` (peu probable derrière OAuth2 Proxy, mais bon principe de défense en profondeur), il peut injecter des caractères arbitraires dans l'audit.

**Solution** : normaliser dans `_client_actor` :
```python
def _client_actor(request: Request) -> str:
    user = request.headers.get("x-forwarded-user") or request.headers.get("x-forwarded-email")
    if user:
        user = user.strip()[:64]
    return user or "admin"
```

**Effort** : 5 min

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

### P2.3 — Q3 : 5 copies de `_utcnow()` → `app/utils.py`
**Fichiers** : `config_editor.py:45`, `audit.py:12`, `jobs.py:50`, `notifications.py:21`, `main.py:108`

**Problème** : même fonction 5 fois.

**Solution** : `app/utils.py` avec `utcnow_str()` et `utcnow_dt()`.

**Effort** : 15 min

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

### P2.7 — Q8 : config_versions : lazy-load content
**Fichier** : `ksf-web/app/services/config_editor.py:156-165`

**Problème** : la page `/config` charge le contenu complet de chaque version.

**Solution** : `SELECT id, actor, reason, created_at, length(content) as size` (déjà fait !), supprimer le `content` de la liste. Endpoint `/api/config/version/{id}` pour le contenu complet.

**Effort** : 15 min

---

### P2.8 — Q10 : Webhook dispatch en parallèle
**Fichier** : `ksf-web/app/services/webhooks.py:88-101`

**Problème** : 5 webhooks × 30s séquentiel = 2.5 min pour 1 notification.

**Solution** : `await asyncio.gather(*[_send_with_retry(ep, p) for ep in matching])`.

**Effort** : 10 min

---

### P2.9 — Q11 : Webhook dispatch en fire-and-forget
**Fichier** : `ksf-web/app/services/notifications.py:48-52`

**Problème** : `webhooks.dispatch` est synchrone dans `notifications.create`. Bloque la réponse user.

**Solution** : `asyncio.create_task(webhooks.dispatch(...))`.

**Effort** : 10 min

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

### P3.6 — `index` sur `audit_log.job_id`
**Fichier** : `migrations/002_indexes.sql`

**Solution** : `CREATE INDEX IF NOT EXISTS idx_audit_job ON audit_log(job_id);`

**Effort** : 2 min

---

### P3.7 — Pagination des notifications
**Fichier** : `ksf-web/app/services/notifications.py:57-69`

**Problème** : `list_all(limit=100)` retourne max 100. Pas de pagination.

**Solution** : cursor-based sur `created_at` + `id`, avec un endpoint `/api/notifications?before=X&limit=N`.

**Effort** : 0.5 jour

---

### P3.8 — Migration vers FastAPI lifespan natif
**Fichier** : `ksf-web/app/main.py:24-39`

**Problème** : `app.router.lifespan_context = lifespan` est l'ancien style.

**Solution** : `app = FastAPI(lifespan=lifespan, ...)`.

**Effort** : 2 min

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

| Catégorie | Items | Effort total |
|---|---|---|
| 🔴 P0 | 4 | ~3 jours |
| 🟠 P1 | 7 | ~5 jours |
| 🟡 P2 | 15 | ~17 jours |
| 🟢 P3 | 14 | ~20 jours |
| **Total** | **40** | **~45 jours** |

## Ordre d'exécution suggéré

1. **P0.1, P0.3, P0.4** (1 jour) : quick wins sécurité avant deploy
2. **P0.2** (2 jours) : chiffrement secrets (nécessite migration soignée)
3. **P1.1, P1.7** (1 jour) : élimine le blocking event loop
4. **P1.2, P1.3** (1 jour) : robustesse runtime
5. **P1.4, P1.5, P1.6** (2 jours) : cohérence des données
6. **Phase 3 features** (P2.12, P2.13, P2.14, P2.15) : 5 jours
7. **P3.x** (refactoring + tests + doc) : continu, par petites touches

## Liens utiles

- `ROADMAP.md` : vision stratégique
- Code review (session précédente) : 40 findings, 14 fixés, 26 à traiter
- `AGENTS.md` : conventions du projet
