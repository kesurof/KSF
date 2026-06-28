---
name: ksf-app-template
description: Use when adding or editing templates/apps/<app>/, app.env, compose.yml, pre_install.sh, or post_install.sh. Covers KSF app template rules, multi-instance safety, and route generation constraints.
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
- Any direct host port should stay bound to `127.0.0.1` unless there is a strong reason otherwise.

## Multi-instance rule

Templates must be safe for `--instance` installs. Use `${APP_INSTANCE}` in names that would otherwise collide, especially:

- `container_name`
- named volumes
- derived host paths when relevant

## Hooks

- `pre_install.sh` and `post_install.sh` are sourced by KSF in a subshell.
- They can use KSF-provided variables such as `BASE_DIR`, `APP_DIR`, `APP_DATA`, `APP_INSTANCE`, `APP_HOST`, `APP_PORT`, `APP_PUID`, `APP_PGID`, and `DRY_RUN`.
- In dry-run, hooks are not executed.

## Validation

After changing a Compose template, validate with `docker compose config` using test variables.

Example:

```bash
BASE_DIR=/tmp/ksf-compose-test NETWORK_NAME=proxy TZ_VALUE=Europe/Paris \
APP_PUID=$(id -u) APP_PGID=$(id -g) APP_INSTANCE=radarr \
docker compose -f templates/apps/radarr/compose.yml config >/dev/null
```
