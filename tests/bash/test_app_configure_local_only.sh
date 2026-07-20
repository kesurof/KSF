#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ksf-app-configure.XXXXXX")"
trap 'rm -rf "${RUNTIME_DIR}"' EXIT

fail() {
  printf 'ECHEC: %s\n' "$*" >&2
  exit 1
}

mkdir -p "${RUNTIME_DIR}/apps/radarr" "${RUNTIME_DIR}/config/installed-apps" \
  "${RUNTIME_DIR}/proxy/traefik/dynamic" "${RUNTIME_DIR}/data/radarr"
cat >"${RUNTIME_DIR}/config/ksf.env" <<'EOF'
WITH_TRAEFIK=true
DOMAIN=example.com
DEFAULT_DOMAIN=example.com
DOMAINS=example.com
NETWORK_NAME=proxy
TZ_VALUE=Europe/Paris
DNS_AUTO_CREATE=false
EOF
cp "${ROOT_DIR}/templates/apps/radarr/compose.yml" "${RUNTIME_DIR}/apps/radarr/docker-compose.yml"
cat >"${RUNTIME_DIR}/config/installed-apps/radarr.env" <<EOF
APP_NAME=radarr
APP_INSTANCE=radarr
APP_DIR=${RUNTIME_DIR}/apps/radarr
APP_DATA=${RUNTIME_DIR}/data/radarr
APP_HOST=films.example.com
APP_DOMAIN=example.com
APP_SUBDOMAIN=films
APP_PORT=7878
APP_HOST_PORT=17878
APP_DOCKER_SERVICE=radarr
APP_PROTECTED=false
APP_PUBLIC=true
APP_LOCAL_ONLY=false
APP_DISABLED=false
APP_PUID=$(id -u)
APP_PGID=$(id -g)
EOF
printf '%s\n' 'previous route' >"${RUNTIME_DIR}/proxy/traefik/dynamic/route-radarr.yml"

"${ROOT_DIR}/app.sh" configure radarr --base-dir "${RUNTIME_DIR}" --local-only --yes

env_file="${RUNTIME_DIR}/config/installed-apps/radarr.env"
grep -qx 'APP_LOCAL_ONLY=true' "${env_file}" || fail 'Le mode local-only n est pas enregistre.'
grep -qx 'APP_HOST_PORT=17878' "${env_file}" || fail 'Le port local existant n est pas preserve.'
grep -qx 'APP_HOST=""' "${env_file}" || fail 'Le hostname public n est pas supprime.'
grep -qx 'APP_DOMAIN=""' "${env_file}" || fail 'Le domaine public n est pas supprime.'
grep -qx 'APP_SUBDOMAIN=""' "${env_file}" || fail 'Le sous-domaine public n est pas supprime.'
[ ! -e "${RUNTIME_DIR}/proxy/traefik/dynamic/route-radarr.yml" ] || fail 'La route Traefik n est pas supprimee.'

printf 'OK: configure --local-only preserve le port local et retire l acces public\n'
