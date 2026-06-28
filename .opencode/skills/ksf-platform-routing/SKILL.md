---
name: ksf-platform-routing
description: Use when changing Traefik, OAuth2 Proxy, CrowdSec, AppSec, `templates/compose/`, `templates/traefik/`, `templates/oauth2-proxy/`, or platform render logic, especially router/middleware generation, trusted IPs, or platform security flows. Covers platform-only boundaries and security expectations.
---

# KSF Platform Routing

Use this skill when changing platform networking, reverse proxying, authentication, or security rendering.

## Scope

Relevant areas:

- `deploy.sh`
- `ksf.sh`
- `lib/deploy_steps.sh`
- `lib/manage_steps.sh`
- `lib/render.sh`
- `templates/compose/`
- `templates/traefik/`
- `templates/oauth2-proxy/`
- `templates/crowdsec/`

## Platform boundaries

- Traefik, OAuth2 Proxy, CrowdSec, AppSec, trusted IPs, and their rendering are platform concerns.
- They must not be modeled as installable apps under `templates/apps/`.
- `deploy.sh` installs or regenerates the initial platform.
- `ksf.sh` operates on an existing platform.

## Security rules

- OAuth2 Proxy stays optional at platform level and per app.
- If an app requests OAuth2 while the platform is not configured for it, KSF must fail explicitly.
- Keep Docker socket exposure minimal; prefer read-only when possible.
- Preserve trusted IP handling for proxied environments such as Cloudflare.
- Avoid public direct access to admin UIs unless intentionally local-only or protected behind Traefik.

## Rendering expectations

- Generated files must not retain unresolved placeholders.
- Keep Traefik middlewares separate from routes and separate from Compose files.
- Preserve route generation conventions used by app installation.

## Validation

When rendering behavior changes, test in a neutral temporary runtime.

Minimum scenario:

```bash
./deploy.sh --base-dir /tmp/ksf-test \
  --with-traefik \
  --domain example.com \
  --acme-email admin@example.com \
  --oauth-client-id id \
  --oauth-client-secret secret \
  --oauth-github-user monuser \
  -y
```

Then validate the rendered Compose files with `docker compose config`.
