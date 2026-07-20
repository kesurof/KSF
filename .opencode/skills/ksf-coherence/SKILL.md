---
name: ksf-coherence
description: Use when reviewing a KSF change before delivery, commit, or pull request to compare acceptance criteria, code, templates, tests, runtime safety, skills, and documentation.
---

# KSF Coherence

Inspect the diff and untracked files. Compare the requested behavior with the
relevant scripts, templates, rendered runtime files, tests, README, AGENTS.md,
skills, and documentation.

- Check script boundaries and the repository/runtime separation.
- Check app instances, routes, environment files, permissions, host ports, and
  dry-run behavior when applicable.
- Check rendered Compose files rather than template text alone.
- Check user-facing flags and commands against CLI help and README.
- For webui work, check Python dependencies, templates, API behavior, UI states,
  and host ownership requirements.
- For a release metadata change, run `make check-release` when feasible.
- Report only commands actually run, `SKIP` outputs, unexecuted opt-in controls
  and residual risks in `docs/checklists/release.md`.
