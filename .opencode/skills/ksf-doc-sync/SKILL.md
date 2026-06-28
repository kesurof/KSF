---
name: ksf-doc-sync
description: Use when changing user-facing commands, flags, install/configure workflows, app access behavior, architecture rules, `README.md`, or `AGENTS.md`. Covers keeping CLI help, docs, and agent instructions aligned with real KSF behavior.
---

# KSF Doc Sync

Use this skill when a change affects project documentation or agent guidance.

## Keep aligned

- CLI help in `bootstrap.sh`, `deploy.sh`, `app.sh`, `ksf.sh`
- `README.md`
- `AGENTS.md`

## Update rules

- If a new command, flag, or workflow is exposed to users, update the README and the relevant CLI help.
- If architecture or responsibility boundaries change, update `AGENTS.md`.
- If a template becomes part of the default documented offering, document it in the README.
- Avoid duplicating large volumes of behavior text when a shorter rule plus examples is enough.
- If the app access workflow changes, keep installation prompts, `configure`-style reconfiguration flows, and domain/subdomain examples aligned across help text, README, and `AGENTS.md`.

## Review checklist

- No contradiction between README and `AGENTS.md`
- No contradiction between CLI help and actual supported flags
- Examples use generic public values such as `example.com`, `admin`, and `monuser`
