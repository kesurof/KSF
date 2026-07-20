---
name: ksf-architecture
description: Use when designing a KSF feature that spans bootstrap, deploy, apps, operations, templates, routes, or the runtime filesystem.
---

# KSF Architecture

The Git repository contains scripts and templates. The host runtime under
`${BASE_DIR}` contains generated stacks, configuration, secrets, logs, and data.
Do not blur those responsibilities.

- `bootstrap.sh`: host and Docker preparation only.
- `deploy.sh`: initial platform infrastructure only, except the documented
  `--with-webui` administration-interface exception.
- `app.sh`: lifecycle of installable application instances.
- `ksf.sh`: operate and diagnose an existing installation.

Load the specialized KSF skill for the subsystem being changed. Prefer a small
change in the owning layer to cross-layer compatibility code.
