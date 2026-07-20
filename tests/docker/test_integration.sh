#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

command -v docker >/dev/null || { printf 'ECHEC: Docker est requis.\n' >&2; exit 1; }
docker compose version >/dev/null || { printf 'ECHEC: Docker Compose est requis.\n' >&2; exit 1; }
docker info >/dev/null || { printf 'ECHEC: Le daemon Docker est inaccessible.\n' >&2; exit 1; }

# The render/configuration matrix is daemon-free. This explicit opt-in target
# confirms that Compose can run a disposable local lifecycle when Docker exists.
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ksf-docker-integration.XXXXXX")"
trap 'docker compose -f "${TMP_DIR}/docker-compose.yml" down --volumes --remove-orphans >/dev/null 2>&1 || true; rm -rf "${TMP_DIR}"' EXIT
cat >"${TMP_DIR}/docker-compose.yml" <<'EOF'
services:
  smoke:
    image: alpine:3.21
    command: ["sh", "-c", "true"]
EOF
docker compose -f "${TMP_DIR}/docker-compose.yml" up --abort-on-container-exit --exit-code-from smoke
docker compose -f "${TMP_DIR}/docker-compose.yml" down --volumes --remove-orphans
printf 'OK: integration Docker Compose opt-in\n'
