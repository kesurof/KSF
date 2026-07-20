#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ksf-routes-dns.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT

fail() {
  printf 'ECHEC: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  grep -qF "$2" "$1" || fail "'$2' absent de $1."
}

# Cloudflare remains fully mocked: public helpers must select the expected API
# operation without contacting a provider or requiring curl/jq.
BASE_DIR="${TMP_DIR}/dns"
mkdir -p "${BASE_DIR}/config"
cat >"${BASE_DIR}/config/ksf.env" <<'EOF'
DOMAINS=example.com,example.net
CF_API_EMAIL=admin@example.com
CF_API_KEY=test-key
SERVER_PUBLIC_IP=203.0.113.10
DNS_AUTO_CREATE=true
DNS_PROVIDER=cloudflare
EOF
# shellcheck disable=SC1091
source "${ROOT_DIR}/lib/dns_cloudflare.sh"
info() { :; }
ok() { :; }
warn() { :; }
err() { :; }
dns_require_tools() { return 0; }
dns_cf_zone_id() { printf 'zone-%s' "$1"; }
dns_cf_find_record_id() {
  if [ "$2" = existing.example.com ]; then
    printf 'record-1'
  else
    printf ''
  fi
}
dns_cf_api() { printf '%s|%s|%s\n' "$1" "$2" "${3:-}" >>"${TMP_DIR}/cloudflare.log"; printf '%s' '{"success":true}'; }
jq() {
  local last="${!#}"
  if [ "${last}" = .success ]; then
    printf '%s' true
  else
    printf '%s' '{"type":"A"}'
  fi
}

dns_ensure_record films.example.com
dns_ensure_record existing.example.com
dns_delete_record existing.example.com
assert_contains "${TMP_DIR}/cloudflare.log" 'POST|/zones/zone-example.com/dns_records|'
assert_contains "${TMP_DIR}/cloudflare.log" 'PUT|/zones/zone-example.com/dns_records/record-1|'
assert_contains "${TMP_DIR}/cloudflare.log" 'DELETE|/zones/zone-example.com/dns_records/record-1|'
if dns_ensure_record example.com >/dev/null 2>&1; then
  fail 'Le domaine racine ne doit pas etre modifie par le helper DNS.'
fi

# The CLI lifecycle is exercised without a Docker daemon. The fake client
# records Compose actions while the real scripts generate and remove files.
FAKE_BIN="${TMP_DIR}/bin"
mkdir -p "${FAKE_BIN}"
cat >"${FAKE_BIN}/docker" <<EOF
#!/usr/bin/env sh
printf '%s\n' "\$*" >>"${TMP_DIR}/docker.log"
if [ "\$1" = compose ] && [ "\$2" = version ]; then exit 0; fi
exit 0
EOF
chmod +x "${FAKE_BIN}/docker"

RUNTIME="${TMP_DIR}/runtime"
mkdir -p "${RUNTIME}/config/installed-apps" "${RUNTIME}/proxy/traefik/dynamic"
cat >"${RUNTIME}/config/ksf.env" <<'EOF'
WITH_TRAEFIK=true
OAUTH2_ENABLED=true
WITH_CROWDSEC=false
DOMAIN=example.com
DEFAULT_DOMAIN=example.com
DOMAINS=example.com
NETWORK_NAME=proxy
TZ_VALUE=Europe/Paris
DNS_AUTO_CREATE=false
EOF

PATH="${FAKE_BIN}:${PATH}" "${ROOT_DIR}/app.sh" install radarr --base-dir "${RUNTIME}" --subdomain films --no-auth --yes
ROUTE="${RUNTIME}/proxy/traefik/dynamic/route-radarr.yml"
[ -f "${ROUTE}" ] || fail 'La route applicative doit etre creee a l installation.'
assert_contains "${ROUTE}" 'Host(`films.example.com`)'
assert_contains "${ROUTE}" 'url: http://radarr:7878'

PATH="${FAKE_BIN}:${PATH}" "${ROOT_DIR}/app.sh" start radarr --base-dir "${RUNTIME}" --yes
PATH="${FAKE_BIN}:${PATH}" "${ROOT_DIR}/app.sh" stop radarr --base-dir "${RUNTIME}" --yes
PATH="${FAKE_BIN}:${PATH}" "${ROOT_DIR}/app.sh" restart radarr --base-dir "${RUNTIME}" --yes

PATH="${FAKE_BIN}:${PATH}" "${ROOT_DIR}/app.sh" configure radarr --base-dir "${RUNTIME}" --subdomain cinema --yes
assert_contains "${ROUTE}" 'Host(`cinema.example.com`)'

PATH="${FAKE_BIN}:${PATH}" "${ROOT_DIR}/app.sh" disable radarr --base-dir "${RUNTIME}" --yes
[ ! -e "${ROUTE}" ] || fail 'La route doit etre supprimee lors de la desactivation.'
[ -f "${RUNTIME}/config/installed-apps/radarr.env" ] || fail 'L enregistrement doit etre conserve lors de la desactivation.'

PATH="${FAKE_BIN}:${PATH}" "${ROOT_DIR}/app.sh" install radarr --base-dir "${RUNTIME}" \
  --subdomain cinema --no-auth --force --yes
[ -f "${ROUTE}" ] || fail 'La route doit etre restauree lors de la reactivation forcee.'
assert_contains "${RUNTIME}/config/installed-apps/radarr.env" 'APP_DISABLED=false'

mkdir -p "${RUNTIME}/data/radarr"
PATH="${FAKE_BIN}:${PATH}" "${ROOT_DIR}/app.sh" remove radarr --base-dir "${RUNTIME}" --yes
[ ! -e "${RUNTIME}/config/installed-apps/radarr.env" ] || fail 'L enregistrement doit etre supprime lors du remove.'
[ -d "${RUNTIME}/data/radarr" ] || fail 'Les donnees doivent etre preservees par defaut.'
assert_contains "${TMP_DIR}/docker.log" 'compose up -d --force-recreate'
assert_contains "${TMP_DIR}/docker.log" 'compose stop'
assert_contains "${TMP_DIR}/docker.log" 'compose restart'
assert_contains "${TMP_DIR}/docker.log" 'compose down'

printf 'OK: routes, DNS Cloudflare simule et lifecycle applicatif\n'
