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

webui_base="${TMP_DIR}/webui-runtime"
webui_output="${TMP_DIR}/webui.out"
if "${ROOT_DIR}/deploy.sh" --base-dir "${webui_base}" --with-traefik \
  --with-webui --domain example.com --acme-email admin@example.com \
  --cf-api-email admin@example.com --cf-api-key test-key --dry-run --yes \
  >"${webui_output}" 2>&1; then
  fail '--with-webui sans OAuth2 devrait echouer.'
fi
assert_no_runtime_write "${webui_base}"
grep -q -- '--with-webui nécessite OAuth2 Proxy' "${webui_output}" || fail 'Le prérequis OAuth2 du Web UI est absent.'

fake_bin="${TMP_DIR}/fake-bin"
mkdir -p "${fake_bin}"
cat >"${fake_bin}/docker" <<'EOF'
#!/bin/sh
exit 0
EOF
cat >"${fake_bin}/bash" <<EOF
#!/bin/bash
if [ "\${1:-}" = "${ROOT_DIR}/app.sh" ]; then
  exit 42
fi
exec /bin/bash "\$@"
EOF
chmod +x "${fake_bin}/docker" "${fake_bin}/bash"

partial_base="${TMP_DIR}/partial-runtime"
partial_output="${TMP_DIR}/partial.out"
if PATH="${fake_bin}:${PATH}" /bin/bash "${ROOT_DIR}/deploy.sh" \
  --base-dir "${partial_base}" --with-traefik --with-webui \
  --domain example.com --acme-email admin@example.com \
  --cf-api-email admin@example.com --cf-api-key test-key \
  --oauth-client-id id --oauth-client-secret secret \
  --oauth-allowed-email admin@example.com --yes >"${partial_output}" 2>&1; then
  fail 'Une installation Web UI déléguée en échec devrait retourner un code non nul.'
fi
[ -f "${partial_base}/proxy/traefik/docker-compose.yml" ] || fail "L'infrastructure Traefik n'a pas été générée."
grep -q 'Déploiement plateforme partiel' "${partial_output}" || fail "Le déploiement partiel n'est pas journalisé."

app_base="${TMP_DIR}/app-runtime"
app_output="${TMP_DIR}/app.out"
"${ROOT_DIR}/app.sh" install radarr --base-dir "${app_base}" --local-only \
  --host-port 17878 --dry-run --yes >"${app_output}" 2>&1
assert_no_runtime_write "${app_base}"
grep -q '\[DRY-RUN\]' "${app_output}" || fail 'Le plan app dry-run est absent.'

printf 'OK: dry-run sans ecriture et echec Web UI partiel couvert sans Docker\n'
