#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT_DIR}/lib/common.sh"

fail() {
  printf 'ECHEC: %s\n' "$*" >&2
  exit 1
}

assert_valid() {
  local validator="$1"
  shift
  "$validator" "$@" || fail "${validator} devrait accepter '$*'."
}

assert_invalid() {
  local validator="$1"
  shift
  if "$validator" "$@"; then
    fail "${validator} devrait refuser '$*'."
  fi
}

assert_valid ksf_port_is_valid 1
assert_valid ksf_port_is_valid 65535
assert_invalid ksf_port_is_valid 0
assert_invalid ksf_port_is_valid 65536
assert_invalid ksf_port_is_valid 80/tcp

assert_valid ksf_instance_is_valid radarr_2
assert_invalid ksf_instance_is_valid Radarr
assert_invalid ksf_instance_is_valid ../radarr

assert_valid ksf_domain_is_valid example.com
assert_invalid ksf_domain_is_valid localhost
assert_invalid ksf_domain_is_valid example..com
assert_valid ksf_subdomain_is_valid films-2026
assert_invalid ksf_subdomain_is_valid films.example
assert_valid ksf_host_is_valid films.example.com
assert_invalid ksf_host_is_valid Films.example.com

assert_valid ksf_path_is_safe /tmp/ksf
assert_invalid ksf_path_is_safe /tmp/../ksf
assert_valid ksf_derived_path_is_valid /tmp/ksf /tmp/ksf/apps/radarr
assert_invalid ksf_derived_path_is_valid /tmp/ksf /tmp/other/apps/radarr

invalid_base="$(mktemp -d "${TMPDIR:-/tmp}/ksf-invalid-port.XXXXXX")"
rmdir "${invalid_base}"
if "${ROOT_DIR}/app.sh" install radarr --port 80/tcp --base-dir "${invalid_base}" --yes >/dev/null 2>&1; then
  fail 'app.sh devrait refuser un port invalide avant installation.'
fi
[ ! -e "${invalid_base}" ] || fail 'Un argument invalide a provoque une ecriture runtime.'
if "${ROOT_DIR}/deploy.sh" --domain >/dev/null 2>&1; then
  fail 'deploy.sh devrait refuser une option sans valeur.'
fi

printf 'OK: validateurs Bash\n'
