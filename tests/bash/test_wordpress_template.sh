#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ksf-wordpress-template.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

fail() {
  printf 'ECHEC: %s\n' "$*" >&2
  exit 1
}

source "${ROOT_DIR}/lib/common.sh"
source "${ROOT_DIR}/lib/render.sh"

render_instance() {
  local instance="$1"

  APP_NAME=wordpress
  APP_INSTANCE="${instance}"
  APP_DIR="${TMP_DIR}/apps/${instance}"
  APP_DATA="${TMP_DIR}/data/${instance}"
  APP_PUID="$(id -u)"
  APP_PGID="$(id -g)"
  APP_TEMPLATE_DIR="${ROOT_DIR}/templates/apps/wordpress"
  BASE_DIR="${TMP_DIR}"
  NETWORK_NAME=proxy
  TZ_VALUE=Europe/Paris
  APP_PORT=80
  APP_HOST_PORT=
  DRY_RUN=false
  SCRIPT_DIR="${ROOT_DIR}"

  mkdir -p "${APP_DIR}" "${APP_DATA}"
  source "${APP_TEMPLATE_DIR}/pre_install.sh"
  render_template "${APP_TEMPLATE_DIR}/compose.yml" "${APP_DIR}/docker-compose.yml"

  [ "$(stat -c '%a' "${APP_DIR}/.env")" = 600 ] || fail "Permissions incorrectes pour ${instance}/.env"
  ! grep -q '\${WORDPRESS_[A-Z_]*}' "${APP_DIR}/docker-compose.yml" || fail "Placeholder WordPress residuel pour ${instance}"
  ! grep -q '\${[A-Z_][A-Z_]*}' "${APP_DIR}/docker-compose.yml" || fail "Placeholder KSF residuel pour ${instance}"
  grep -q "${TMP_DIR}/data/${instance}" "${APP_DIR}/docker-compose.yml" || fail "Donnees non isolees pour ${instance}"
  docker compose -f "${APP_DIR}/docker-compose.yml" config --quiet
}

command -v docker >/dev/null || fail 'Docker est requis pour ce test.'
docker compose version >/dev/null || fail 'Docker Compose est requis pour ce test.'

render_instance blog
render_instance shop

cmp -s "${TMP_DIR}/apps/blog/.env" "${TMP_DIR}/apps/shop/.env" && fail 'Secrets identiques entre instances.'
printf 'OK: deux rendus WordPress isoles, sans placeholders et avec secrets 600\n'
