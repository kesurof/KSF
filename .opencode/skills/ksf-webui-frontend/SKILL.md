---
name: ksf-webui-frontend
description: Use when editing templates/apps/webui FastAPI, Jinja2, HTMX, Alpine.js, Tailwind CSS, styles, forms, navigation, modals, or responsive UI behavior.
---

# KSF Web UI Frontend

Read `docs/webui/ui-ux.md` and `docs/checklists/ui-review.md` first.

- The server owns business state. HTMX requests and replaces server-rendered
  fragments. Alpine owns only local, ephemeral interaction state.
- Use the Tailwind design tokens and compiled stylesheet for new styles. Migrate
  legacy classes incrementally without changing unrelated screens.
- Validate at mobile and desktop sizes. Interactive targets need at least 44 px.
- Every dynamic surface handles loading, empty, error, success, and long data.
- Preserve visible focus, labels, keyboard navigation, contrast, dark mode, and
  reduced-motion behavior.
- Destructive actions require explicit confirmation and must not focus the
  dangerous action by default.
