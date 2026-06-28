---
name: ksf-app-template
description: Use when adding or editing `templates/apps/<app>/`, `app.env`, `compose.yml`, `pre_install.sh`, or `post_install.sh`, especially for multi-instance apps, multi-service Compose templates, `APP_DOCKER_SERVICE`, or app access/domain behavior. Covers KSF app template rules, route generation constraints, and instance safety.
---

# KSF App Template

Use this skill when creating or modifying an installable application template.

## Required shape

Each app template lives in:

```text
templates/apps/<app>/
  app.env
  compose.yml
```

Optional hooks:

```text
templates/apps/<app>/
  pre_install.sh
  post_install.sh
```

## Rules

- Keep a single `compose.yml` per app template.
- Use `${VARIABLE}` placeholders only.
- Assume routes are generated from `app.env`; do not add app-specific `route.yml` files.
- Default to protected apps unless `APP_PROTECTED=false` is explicitly intended.
- Put persistent data under `${BASE_DIR}/data/<instance>`.
- Generated stacks live under `${BASE_DIR}/apps/<instance>`.
- Generated installed-app metadata lives under `${BASE_DIR}/config/installed-apps/<instance>.env`.
- `APP_PORT` is the internal Docker port used by Traefik and by app-to-app communication.
- `APP_HOST_PORT` is the optional host-published local port bound on `127.0.0.1`.
- Any direct host port should stay bound to `127.0.0.1` unless there is a strong reason otherwise.
- Exposed apps should not publish a host port by default; a local host bind must be an explicit choice.

## Multi-instance rule

Templates must be safe for `--instance` installs. Use `${APP_INSTANCE}` in names and paths that would otherwise collide, especially:

- `container_name`
- named volumes
- derived host paths when relevant
- bind-mounted data paths under `${BASE_DIR}/data/${APP_INSTANCE}` when the app stores instance-local state

## Instance-first model

- `APP_INSTANCE` is the runtime identity shown to users and used by KSF for stacks, routes, and installed-app records.
- `APP_NAME` remains the template name only.
- For apps with several services in one `compose.yml`, declare `APP_DOCKER_SERVICE` in `app.env` when one service is the main upstream exposed by Traefik.
- Assume KSF diagnostics will inspect the full stack with `docker compose ps -a`, not a single hardcoded container name.
- Keep service names readable in diagnostics so KSF can render concise summaries like `web: healthy` or `db: healthy`.
- Keep app host/domain behavior compatible with KSF's access flow: exposed apps should work whether the user provides `--host`, `--domain` + `--subdomain`, or answers the interactive questions during install/configure.
- Do not preserve the old pattern where `APP_PORT` also implied a host-published port; templates must use the `APP_PORT` / `APP_HOST_PORT` split.

## Hooks

- `pre_install.sh` and `post_install.sh` are sourced by KSF in a subshell.
- They can use KSF-provided variables such as `BASE_DIR`, `APP_DIR`, `APP_DATA`, `APP_INSTANCE`, `APP_HOST`, `APP_PORT`, `APP_PUID`, `APP_PGID`, and `DRY_RUN`.
- In dry-run, hooks are not executed.

## Validation

After changing a Compose template, render it with test variables first, then validate the rendered file with `docker compose config`.

Example:

```bash
tmpdir=$(mktemp -d /tmp/ksf-compose-test.XXXXXX)
source ./lib/common.sh
source ./lib/render.sh

APP_NAME=radarr APP_INSTANCE=radarr APP_PORT=7878 APP_HOST_PORT=17878 \
BASE_DIR=/tmp/ksf-compose-test NETWORK_NAME=proxy TZ_VALUE=Europe/Paris \
APP_PUID=$(id -u) APP_PGID=$(id -g) \
render_template templates/apps/radarr/compose.yml "$tmpdir/docker-compose.yml"

docker compose -f "$tmpdir/docker-compose.yml" config >/dev/null
```
