---
name: ksf-webui-database
description: Use when changing templates/apps/webui SQLite jobs storage, schema evolution, persistence, backup behavior, or database tests.
---

# KSF Web UI Database

The webui uses `aiosqlite` for persistent jobs data under
`${BASE_DIR}/data/webui/jobs.db` (override with `KSF_WEBUI_DB_PATH`). Keep the
database, WAL/SHM sidecars and backups host-owned, mode `600`, and outside the
image; keep its directory mode `700`.

- Enable and test constraints when introducing relational data.
- Treat schema changes as compatibility work: define upgrade behavior, test a
  populated database, and preserve a SQLite online backup before destructive
  changes. Migrations are tracked by `schema_migrations` and run with `BEGIN
  IMMEDIATE`.
- On a destructive migration, document the backup filename and restoration:
  stop Web UI, preserve the faulty database, restore the backup, remove obsolete
  WAL/SHM sidecars, then restore host ownership and mode.
- Preserve WAL, five-second busy timeout, foreign keys, integrity checks, job
  retention and the unique active-job-per-target constraint unless an approved
  migration changes them.
- Do not introduce SQLAlchemy or Alembic without a separately approved migration
  plan. The current lightweight schema mechanism must still be tested.
