---
name: ksf-webui-database
description: Use when changing templates/apps/webui SQLite jobs storage, schema evolution, persistence, backup behavior, or database tests.
---

# KSF Web UI Database

The webui currently uses `aiosqlite` for persistent jobs data under the KSF
runtime. Keep database files host-owned, mode `600`, and outside the image.

- Enable and test constraints when introducing relational data.
- Treat schema changes as compatibility work: define upgrade behavior, test a
  populated database, and preserve a backup path before destructive changes.
- Do not introduce SQLAlchemy or Alembic without a separately approved migration
  plan. The current lightweight schema mechanism must still be tested.
