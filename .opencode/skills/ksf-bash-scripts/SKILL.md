---
name: ksf-bash-scripts
description: Use when editing `bootstrap.sh`, `deploy.sh`, `app.sh`, `ksf.sh`, or `lib/*.sh`, especially for install flows, app lifecycle, menu/status logic, dry-run behavior, or domain/subdomain access handling. Covers KSF script boundaries, runtime safety, and required Bash validation.
---

# KSF Bash Scripts

Use this skill when editing KSF shell entrypoints or shared Bash libraries.

## Intent

Keep changes small, safe, and aligned with the script boundaries of the project.

## Responsibilities

- `bootstrap.sh`: system packages, Docker, user, SSH, runtime bootstrap.
- `deploy.sh`: initial platform install, Traefik, OAuth2 Proxy, CrowdSec, base config.
- `app.sh`: application lifecycle only.
- `ksf.sh`: operations on an existing installation only.

Do not move behavior from one script family to another unless the user explicitly asks for a refactor.

## Working rules

- Prefer changing an existing function over introducing a new layer of abstraction.
- Keep runtime writes under `${BASE_DIR}` only.
- Preserve dry-run semantics: no persistent write in `${BASE_DIR}` when `DRY_RUN=true`.
- Reuse existing helpers from `lib/common.sh`, `lib/render.sh`, `lib/app_steps.sh`, `lib/deploy_steps.sh`, `lib/manage_steps.sh`, and `lib/update_steps.sh` before creating new helpers.
- Keep messages user-facing and explicit on missing inputs or invalid states.
- Prefer instance-first user output: show `APP_INSTANCE` as the app identity and keep `APP_NAME` as template metadata.
- For app status and diagnostics, prefer stack-aware signals from `docker compose ps -a` over single-container assumptions.
- When `deploy.sh` detects an existing installation in interactive mode, prefer an explicit choice between forcing the reinstall and cancelling instead of a dead-end error.
- For multi-service apps, prefer a short per-service summary such as `web: healthy` while keeping the full stack state visible.
- For exposed apps, preserve the user flow around `--host`, `--domain`, and `--subdomain`: if these are not provided, the install flow should ask for the domain and subdomain at the right time.
- When changing app access after installation, prefer a focused reconfiguration flow that updates only host/domain/subdomain, route generation, and app DNS state without forcing a full reinstall.

## Checks before finishing

After changing scripts, run:

```bash
bash -n bootstrap.sh deploy.sh app.sh ksf.sh lib/*.sh
```

If the change touches generated output, also run the smallest relevant functional validation.

## Common pitfalls

- Do not install apps from `deploy.sh`.
- Do not modify system setup from `app.sh` or `ksf.sh`.
- Do not make dry-run execute hooks or create installed-app records.
- Do not write secrets with permissive permissions.
