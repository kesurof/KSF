# Roadmap ksf-web v2.0

> Document de référence pour l'évolution de ksf-web.

## Décisions structurantes

| Aspect | Décision |
|---|---|
| Scope cible | v2.0 Gestion+ (stab + features de gestion + job queue + notifications + audit) |
| Modèle d'usage | Single-user (admin = toi, via OAuth2 Proxy déjà en place) |
| Persistance | SQLite local (`${BASE_DIR}/ksf-web/state.db`) + migrations versionnées |
| Real-time | SSE (htmx-sse) pour logs et job progress |
| Job queue | `subprocess.Popen` + SQLite (PID tracking, état persistant) |
| Édition config | Form structuré + dry-run obligatoire + diff visuel + backup auto |
| Notifications | In-app (badge + page + toast) + webhook optionnel (Slack/Discord/ntfy) |
| Audit log | SQLite (queries riches) |
| Auth | OAuth2 Proxy reste l'auth frontale. ksf-web fait confiance à `X-Forwarded-User`/`X-Forwarded-Email`. CSRF par double-submit cookie. |

## Phases

### Phase 0 — Déploiement & cache Cloudflare
**Statut** : en cours

- [ ] Purger le cache Cloudflare actuel (Dashboard → Caching → Configuration → Custom Purge `https://ksf.kesurof.fr/static/*`)
- [ ] Désactiver Development Mode
- [ ] Configurer une Cache Rule Cloudflare : bypass sur `/static/*`
- [ ] Ajouter `cf_purge_cache` dans KSF + hook post-deploy ksf-web
- [ ] Documenter `CF_API_TOKEN` et `CF_ZONE_ID` dans `.env`

**Critère** : un changement de CSS est visible après redeploy, sans hard-refresh navigateur.

### Phase 1 — v1.2 Stab (bloquants et hardening)
**Statut** : à faire

Bugs :
- [ ] Fix permissions backups (montage `:ro` + UID match)
- [ ] Fix formulaire d'install (passer les params au backend)
- [ ] Fix XSS dans `app_install_form` (partial Jinja)

Hardening :
- [ ] CSRF double-submit cookie
- [ ] Modales de confirmation custom (remplace `window.confirm`)
- [ ] Pages 404/500 dans le design system
- [ ] Output non tronqué silencieusement (lien vers log complet)
- [ ] Auto-refresh dashboard via htmx

Nettoyage :
- [ ] Centraliser config dans `app/config.py`
- [ ] Découper `main.py` en `routes/pages.py`, `routes/actions.py`, `routes/api.py`
- [ ] Tests : `tests/test_security.py`, `tests/test_routes.py`

### Phase 2 — v2.0 Core
**Statut** : à faire

Infra :
- [ ] Structure `app/services/` + `app/routes/`
- [ ] Dépendances : `aiosqlite`, `itsdangerous`
- [ ] Migrations SQLite (`migrations/00X_*.sql`)

Features :
- [ ] Job queue (`services/jobs.py`) : subprocess + SQLite + SSE
- [ ] Streaming logs containers (`/containers/{id}/logs/stream` SSE)
- [ ] Backups : delete, download, restore réel, restore progress, prune
- [ ] Édition `ksf.env` : form structuré + dry-run + diff + rollback
- [ ] Event log + audit log + page `/audit` + export
- [ ] Notifications persistantes : badge sidebar, page `/notifications`, toasts
- [ ] Webhooks : CRUD endpoints, dispatch HMAC, retry

Tests :
- [ ] `tests/test_jobs.py`, `tests/test_backups.py`, `tests/test_config_editor.py`
- [ ] `tests/test_csrf.py`, `tests/test_sse.py`

### Phase 3 — v2.0+ Polish
**Statut** : à faire

- [ ] Rate limiting (token bucket par IP)
- [ ] Locks UI sur ops exclusives
- [ ] Page `/settings` (general, webhooks, security, maintenance)
- [ ] Light theme (toggle)
- [ ] Branding unifié (KSF ↔ Serverbox) + favicon
- [ ] Endpoint `/health` pour monitoring externe

### Phase 4 — Release v2.0
**Statut** : à faire

- [ ] Versioning (`APP_VERSION` dans `app.env`)
- [ ] `CHANGELOG.md`
- [ ] Tag Git `v2.0.0`
- [ ] Migration v1.x → v2.0 (DB init, nouvelles env vars)
- [ ] `ksf-web/README.md` (architecture, env, debug)

## Effort total estimé

| Phase | Effort |
|---|---|
| P0 | 0.5 jour |
| P1 | 3-5 jours |
| P2 | 10-15 jours |
| P3 | 3-5 jours |
| P4 | 1-2 jours |
| **Total** | **18-28 jours** |

## Ordre d'exécution

1. **P0 maintenant** (sinon chaque deploy casse l'UI)
2. **P1** avant toute utilisation quotidienne
3. **P2** par sous-priorités (jobs + DB d'abord, puis backups/config/SSE, puis audit/notifs)
4. **P3** en parallèle des derniers sous-priorités de P2
5. **P4** une fois P2 terminé
