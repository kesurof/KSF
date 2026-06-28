---
name: ksf-validation
description: Use when a KSF change is ready to verify, especially after script edits, Compose template changes, route/render changes, dry-run updates, or app domain/subdomain workflow changes. Covers `bash -n`, `docker compose config`, dry-run expectations, and the smallest useful validation path.
---

# KSF Validation

Use this skill near the end of a change to select the smallest correct validation set.

## Validation ladder

1. If Bash scripts changed, run:

```bash
bash -n bootstrap.sh deploy.sh app.sh ksf.sh lib/*.sh
```

2. If an app Compose template changed, render it with test variables, then run `docker compose config` on the rendered file.

3. If platform rendering changed, render into `/tmp/ksf-test` and validate the generated Compose files.

4. If dry-run behavior changed, verify no files are written under `${BASE_DIR}` during the dry-run scenario.

5. If app access flow changed, verify at least one interactive or scripted path for:

- app install asking for domain/subdomain when not provided
- app configure changing only domain and/or subdomain
- regenerated route and persisted app env staying aligned

## Dry-run expectations

- `deploy.sh --dry-run` must not create files under `${BASE_DIR}`.
- `app.sh install <app> --dry-run` must not create stacks, routes, or installed-app entries.
- Dry-run output should be prefixed with `[DRY-RUN]`.

## Reporting

When validation could not be run, state exactly what remains unverified.
