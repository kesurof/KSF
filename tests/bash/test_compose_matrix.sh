#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ksf-compose-matrix.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

fail() {
  printf 'ECHEC: %s\n' "$*" >&2
  exit 1
}

assert_no_ksf_placeholders() {
  local file="$1" var
  for var in "${RENDER_VARS[@]}"; do
    if grep -qF "\${${var}}" "$file" || grep -qF "__${var}__" "$file"; then
      fail "Placeholder KSF residuel (${var}) dans ${file}."
    fi
  done
}

assert_contains() {
  grep -qF "$2" "$1" || fail "'$2' absent de $1."
}

# shellcheck disable=SC1091
source "${ROOT_DIR}/lib/common.sh"
# shellcheck disable=SC1091
source "${ROOT_DIR}/lib/render.sh"

SCRIPT_DIR="${ROOT_DIR}"
BASE_DIR="${TMP_DIR}/runtime"
NETWORK_NAME=proxy
TZ_VALUE=Europe/Paris
ACME_EMAIL=admin@example.com
DOMAIN=example.com
DEFAULT_DOMAIN=example.com
DOMAINS=example.com,example.net
CF_API_EMAIL=admin@example.com
CF_API_KEY=test-key
SERVER_PUBLIC_IP=203.0.113.10
DNS_AUTO_CREATE=true
DNS_PROVIDER=cloudflare
DNS_RECORD_TTL=1
DNS_RECORD_PROXIED=true
WITH_CROWDSEC=true
CROWDSEC_APPSEC_ENABLED=true
CROWDSEC_BOUNCER_KEY=test-bouncer
TRAEFIK_HOST=traefik.example.com
OAUTH2_HOST=auth.example.com
OAUTH2_CLIENT_ID=test-id
OAUTH2_CLIENT_SECRET=test-secret
OAUTH2_ALLOWED_EMAILS=admin@example.com
OAUTH2_COOKIE_SECRET=01234567890123456789012345678901
OAUTH2_GITHUB_USER=admin
OAUTH2_AUTH_MODE=github
OAUTH2_ENABLED=true
OAUTH2_SCOPE='user:email'
OAUTH2_EMAIL_DOMAINS='*'
OAUTH2_AUTHENTICATED_EMAILS_FILE=
TRAEFIK_TRUSTED_IPS='["203.0.113.0/24"]'
DOCKER_GID=999

render_template "${ROOT_DIR}/templates/compose/traefik.yml" "${TMP_DIR}/traefik/docker-compose.yml"
render_template "${ROOT_DIR}/templates/compose/oauth2-proxy.yml" "${TMP_DIR}/oauth2/docker-compose.yml"
render_template "${ROOT_DIR}/templates/compose/crowdsec.yml" "${TMP_DIR}/crowdsec/docker-compose.yml"
for template in "${ROOT_DIR}"/templates/traefik/*.yml \
  "${ROOT_DIR}"/templates/crowdsec/*.y* \
  "${ROOT_DIR}/templates/env/ksf.env" \
  "${ROOT_DIR}/templates/oauth2-proxy/sign_in.html"; do
  render_template "${template}" "${TMP_DIR}/platform/$(basename "${template}")"
done

assert_contains "${TMP_DIR}/platform/middleware-oauth2.yml" 'oauth2-chain:'
assert_contains "${TMP_DIR}/platform/middleware-crowdsec.yml" 'security-chain:'
assert_contains "${TMP_DIR}/platform/route-traefik-oauth2.yml" 'oauth2-chain'
assert_contains "${TMP_DIR}/platform/route-oauth2-proxy.yml" 'oauth2-proxy'

for template in "${ROOT_DIR}"/templates/apps/*; do
  [ -d "${template}" ] || continue
  app_name="$(basename "${template}")"
  APP_NAME="${app_name}"
  APP_INSTANCE="${app_name}-test"
  APP_HOST="${app_name}.example.com"
  APP_PORT="$(APP_PORT= APP_INTERNAL_PORT= source "${template}/app.env" && printf '%s' "${APP_PORT:-${APP_INTERNAL_PORT:-}}")"
  APP_HOST_PORT=""
  APP_PROTECTED=true
  APP_PUBLIC=true
  APP_PUID="$(id -u)"
  APP_PGID="$(id -g)"
  render_template "${template}/compose.yml" "${TMP_DIR}/apps/${app_name}/docker-compose.yml"
  # Some templates declare generated secrets through env_file; Compose config
  # needs the file to exist even though the values are not interpolated here.
  : >"${TMP_DIR}/apps/${app_name}/.env"
  render_app_route_from_env "${TMP_DIR}/routes/route-${app_name}.yml"
  assert_contains "${TMP_DIR}/routes/route-${app_name}.yml" 'oauth2-chain'
done

while IFS= read -r -d '' file; do
  assert_no_ksf_placeholders "$file"
done < <(find "${TMP_DIR}" -type f -print0)

if [ "${1:-}" = --docker ]; then
  command -v docker >/dev/null || fail 'Docker est requis pour la validation Compose.'
  docker compose version >/dev/null || fail 'Docker Compose est requis pour la validation Compose.'
  while IFS= read -r -d '' file; do
    case "$file" in
      */docker-compose.yml) docker compose -f "$file" config --quiet ;;
    esac
  done < <(find "${TMP_DIR}" -type f -print0)
fi

printf 'OK: matrice Compose plateforme/apps, routes et middlewares%s\n' "${1:+ avec Docker Compose}"
