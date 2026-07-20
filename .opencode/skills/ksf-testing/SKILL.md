---
name: ksf-testing
description: Use when planning or running KSF tests for Bash scripts, template rendering, Docker Compose, webui Python code, UI behavior, or a regression fix.
---

# KSF Testing

Choose the least costly evidence that proves the changed behavior. The offline
baseline is `make validate`; `make check-release` adds only the SemVer and
changelog consistency check. Neither command runs Docker, Web UI, audit, or
browser controls.

The Bash baseline includes validators, zero-write dry-runs, `install-cli`, app
lifecycle/routes/DNS and app-install rollback coverage, plus the static Compose
matrix.

- Bash changes: run `bash -n bootstrap.sh deploy.sh app.sh ksf.sh lib/*.sh`.
- Template or routing changes: render with neutral values and run `docker compose config`.
- Generation changes: use a temporary base directory and verify generated files.
- Dry-run changes: verify that `${BASE_DIR}` receives no persistent write.
- Webui changes: run its Python tests; test rendered HTML or browser behavior when
  a user interaction changed.
- Webui baseline after dependencies are installed: `make -C templates/apps/webui verify`.
- Browser controls: `make -C templates/apps/webui ui-install-browser` then
  `make -C templates/apps/webui test-ui`.
- Docker/Compose controls: `make check-compose` or `make test-docker` when their
  relevant prerequisites are available.
- Bug fixes add a regression test where practical. Tests must not need a live
  server, real DNS provider, or production Docker daemon.

State the commands run, any `SKIP` output, and what remains unverified in the
release checklist.
