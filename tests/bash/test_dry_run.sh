#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ksf-dry-run.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

fail() {
  printf 'ECHEC: %s\n' "$*" >&2
  exit 1
}

assert_no_runtime_write() {
  [ ! -e "$1" ] || fail "Le dry-run a ecrit dans ${1}."
}

bootstrap_base="${TMP_DIR}/bootstrap-runtime"
bootstrap_output="${TMP_DIR}/bootstrap.out"
bootstrap_bin="${TMP_DIR}/bootstrap-bin"
mkdir -p "${bootstrap_bin}"
cat >"${bootstrap_bin}/sudo" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "${bootstrap_bin}/sudo"
PATH="${bootstrap_bin}:${PATH}" "${ROOT_DIR}/bootstrap.sh" --base-dir "${bootstrap_base}" \
  --skip-system --skip-docker --dry-run --yes >"${bootstrap_output}" 2>&1
assert_no_runtime_write "${bootstrap_base}"
grep -q '\[DRY-RUN\]' "${bootstrap_output}" || fail 'Le plan bootstrap dry-run est absent.'

deploy_base="${TMP_DIR}/deploy-runtime"
deploy_output="${TMP_DIR}/deploy.out"
"${ROOT_DIR}/deploy.sh" --base-dir "${deploy_base}" --with-traefik \
  --domain example.com --acme-email admin@example.com \
  --cf-api-email admin@example.com --cf-api-key test-key --dry-run --yes \
  >"${deploy_output}" 2>&1
assert_no_runtime_write "${deploy_base}"
grep -q '\[DRY-RUN\]' "${deploy_output}" || fail 'Le plan deploy dry-run est absent.'

app_base="${TMP_DIR}/app-runtime"
app_output="${TMP_DIR}/app.out"
"${ROOT_DIR}/app.sh" install radarr --base-dir "${app_base}" --local-only \
  --host-port 17878 --dry-run --yes >"${app_output}" 2>&1
assert_no_runtime_write "${app_base}"
grep -q '\[DRY-RUN\]' "${app_output}" || fail 'Le plan app dry-run est absent.'

printf 'OK: dry-run sans ecriture couvert sans Docker\n'
