---
name: ksf-testing
description: Use when planning or running KSF tests for Bash scripts, template rendering, Docker Compose, webui Python code, UI behavior, or a regression fix.
---

# KSF Testing

Choose the least costly evidence that proves the changed behavior.

- Bash changes: run `bash -n bootstrap.sh deploy.sh app.sh ksf.sh lib/*.sh`.
- Template or routing changes: render with neutral values and run `docker compose config`.
- Generation changes: use a temporary base directory and verify generated files.
- Dry-run changes: verify that `${BASE_DIR}` receives no persistent write.
- Webui changes: run its Python tests; test rendered HTML or browser behavior when
  a user interaction changed.
- Bug fixes add a regression test where practical. Tests must not need a live
  server, real DNS provider, or production Docker daemon.

State the commands run and what remains unverified.
