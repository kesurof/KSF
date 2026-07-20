#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ksf-app-rollback.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

fail() {
  printf 'ECHEC: %s\n' "$*" >&2
  exit 1
}

assert_preserved() {
  local runtime="$1"

  cmp "${runtime}/apps/radarr/docker-compose.yml" "${runtime}/expected-compose" || fail 'Le Compose precedent n a pas ete restaure.'
  cmp "${runtime}/apps/radarr/app.env" "${runtime}/expected-app-env" || fail 'Le fichier app.env precedent n a pas ete restaure.'
  cmp "${runtime}/config/installed-apps/radarr.env" "${runtime}/expected-installed-env" || fail 'L enregistrement precedent n a pas ete restaure.'
  [ "$(<"${runtime}/proxy/traefik/dynamic/route-radarr.yml")" = 'previous route' ] || fail 'La route precedente n a pas ete restauree.'
  [ "$(<"${runtime}/data/radarr/keep")" = 'persistent data' ] || fail 'Les donnees existantes ont ete modifiees.'
}

seed_runtime() {
  local runtime="$1"

  mkdir -p "${runtime}/apps/radarr" "${runtime}/config/installed-apps" \
    "${runtime}/proxy/traefik/dynamic" "${runtime}/data/radarr"
  cat >"${runtime}/config/ksf.env" <<'EOF'
WITH_TRAEFIK=true
OAUTH2_ENABLED=false
DOMAIN=example.com
DEFAULT_DOMAIN=example.com
DOMAINS=example.com
NETWORK_NAME=proxy
TZ_VALUE=Europe/Paris
DNS_AUTO_CREATE=false
EOF
  printf '%s\n' 'previous compose' >"${runtime}/apps/radarr/docker-compose.yml"
  printf '%s\n' 'previous app env' >"${runtime}/apps/radarr/app.env"
  cat >"${runtime}/config/installed-apps/radarr.env" <<EOF
APP_NAME=radarr
APP_INSTANCE=radarr
APP_DIR=${runtime}/apps/radarr
APP_DATA=${runtime}/data/radarr
APP_HOST=old.example.com
APP_DOMAIN=example.com
APP_SUBDOMAIN=old
APP_PORT=7878
APP_PROTECTED=false
APP_LOCAL_ONLY=false
EOF
  printf '%s\n' 'previous route' >"${runtime}/proxy/traefik/dynamic/route-radarr.yml"
  printf '%s\n' 'persistent data' >"${runtime}/data/radarr/keep"
  cp "${runtime}/apps/radarr/docker-compose.yml" "${runtime}/expected-compose"
  cp "${runtime}/apps/radarr/app.env" "${runtime}/expected-app-env"
  cp "${runtime}/config/installed-apps/radarr.env" "${runtime}/expected-installed-env"
}

SUITE_DIR="${TMP_DIR}/suite"
cp -a "${ROOT_DIR}" "${SUITE_DIR}"
FAKE_BIN="${TMP_DIR}/bin"
mkdir -p "${FAKE_BIN}"
cat >"${FAKE_BIN}/docker" <<'EOF'
#!/usr/bin/env sh
if [ "$1" = compose ] && [ "$2" = up ] && [ "${COMPOSE_FAIL:-false}" = true ]; then
  exit 1
fi
exit 0
EOF
chmod +x "${FAKE_BIN}/docker"

run_failure_case() {
  local name="$1"
  local runtime="${TMP_DIR}/${name}"
  local output="${TMP_DIR}/${name}.out"

  seed_runtime "${runtime}"
  if [ "${name}" = dns ]; then
    cat >>"${runtime}/config/ksf.env" <<'EOF'
DNS_AUTO_CREATE=true
SERVER_PUBLIC_IP=203.0.113.10
CF_API_EMAIL=admin@example.com
CF_API_KEY=test-key
EOF
  fi
  if PATH="${FAKE_BIN}:${PATH}" APP_INSTALL_FORCE=true "$@" "${SUITE_DIR}/app.sh" install radarr \
    --base-dir "${runtime}" --domain example.com --subdomain films --no-auth --yes >"${output}" 2>&1; then
    fail "Le scenario ${name} devrait echouer."
  fi
  assert_preserved "${runtime}"
}

# A failing pre-install hook occurs after generated files are written.
printf '%s\n' false >"${SUITE_DIR}/templates/apps/radarr/pre_install.sh"
run_failure_case hook env
rm -f "${SUITE_DIR}/templates/apps/radarr/pre_install.sh"

# A Compose startup failure must restore the prior stack before returning.
run_failure_case compose env COMPOSE_FAIL=true

# DNS errors happen after the new route was rendered.
cat >"${FAKE_BIN}/curl" <<'EOF'
#!/usr/bin/env sh
printf '%s' '{"success":false}'
EOF
cat >"${FAKE_BIN}/jq" <<'EOF'
#!/usr/bin/env sh
printf '%s' false
EOF
chmod +x "${FAKE_BIN}/curl" "${FAKE_BIN}/jq"
run_failure_case dns env
rm -f "${FAKE_BIN}/curl" "${FAKE_BIN}/jq"

# Make the route destination impossible to create after the app stack changed.
seed_runtime "${TMP_DIR}/render"
rm -rf "${TMP_DIR}/render/proxy/traefik/dynamic"
printf '%s\n' blocked >"${TMP_DIR}/render/proxy/traefik/dynamic"
if PATH="${FAKE_BIN}:${PATH}" "${SUITE_DIR}/app.sh" install radarr \
  --base-dir "${TMP_DIR}/render" --domain example.com --subdomain films --no-auth --force --yes >"${TMP_DIR}/render.out" 2>&1; then
  fail 'Le scenario render devrait echouer.'
fi
cmp "${TMP_DIR}/render/apps/radarr/docker-compose.yml" "${TMP_DIR}/render/expected-compose" || fail 'Le Compose precedent n a pas ete restaure apres erreur de rendu.'
[ "$(<"${TMP_DIR}/render/data/radarr/keep")" = 'persistent data' ] || fail 'Les donnees ont ete modifiees apres erreur de rendu.'

printf 'OK: rollback render, DNS, hook et Compose sans suppression des donnees\n'
