#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ksf-compose-templates.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

fail() {
  printf 'ECHEC: %s\n' "$*" >&2
  exit 1
}

command -v docker >/dev/null || fail 'Docker est requis pour ce test.'
docker compose version >/dev/null || fail 'Docker Compose est requis pour ce test.'

if grep -R -Eq '^[[:space:]]*image:[[:space:]]+[^[:space:]]+:latest([[:space:]]|$)' \
  "${ROOT_DIR}/templates" --include='*.yml' --include='*.yaml'; then
  fail 'Une image Compose utilise encore le tag latest.'
fi

source "${ROOT_DIR}/lib/common.sh"
source "${ROOT_DIR}/lib/render.sh"

SCRIPT_DIR="${ROOT_DIR}"
BASE_DIR="${TMP_DIR}"
NETWORK_NAME=proxy
TZ_VALUE=Europe/Paris
ACME_EMAIL=admin@example.com
DOMAIN=example.com
CF_API_EMAIL=admin@example.com
CF_API_KEY=test-key
OAUTH2_SCOPE='openid profile email'
OAUTH2_CLIENT_ID=id
OAUTH2_CLIENT_SECRET=secret
OAUTH2_COOKIE_SECRET=0123456789abcdef0123456789abcdef
OAUTH2_HOST=auth.example.com
OAUTH2_EMAIL_DOMAINS='*'
OAUTH2_AUTHENTICATED_EMAILS_FILE=
OAUTH2_GITHUB_USER=monuser
CROWDSEC_COLLECTIONS=crowdsecurity/traefik
CROWDSEC_BOUNCER_KEY=test-key
WITH_CROWDSEC=false
CROWDSEC_APPSEC_ENABLED=false
APP_PUID="$(id -u)"
APP_PGID="$(id -g)"
DRY_RUN=false

render_and_validate() {
  local template="$1"
  local output="$2"

  render_template "${ROOT_DIR}/${template}" "${output}"
  docker compose -f "${output}" config --quiet
}

render_and_validate templates/compose/traefik.yml "${TMP_DIR}/traefik/docker-compose.yml"
render_and_validate templates/compose/oauth2-proxy.yml "${TMP_DIR}/oauth2-proxy/docker-compose.yml"
render_and_validate templates/compose/crowdsec.yml "${TMP_DIR}/crowdsec/docker-compose.yml"

for app in dockge radarr wordpress; do
  APP_NAME="${app}"
  APP_INSTANCE="${app}"
  APP_TEMPLATE_DIR="${ROOT_DIR}/templates/apps/${app}"
  APP_DIR="${TMP_DIR}/apps/${app}"
  APP_DATA="${TMP_DIR}/data/${app}"
  APP_HOST="${app}.example.com"
  APP_PORT="$( ( APP_PORT=; source "${ROOT_DIR}/templates/apps/${app}/app.env"; printf '%s' "${APP_PORT}" ) )"
  APP_HOST_PORT=
  APP_PORTS_BLOCK=
  DOCKER_GROUP_ADD_BLOCK=
  mkdir -p "${APP_DIR}" "${APP_DATA}"
  if [ "${app}" = wordpress ]; then
    source "${APP_TEMPLATE_DIR}/pre_install.sh"
  fi
  render_and_validate "templates/apps/${app}/compose.yml" "${TMP_DIR}/apps/${app}/docker-compose.yml"
done

printf 'OK: tous les Compose rendus sont valides et aucune image latest ne reste.\n'
