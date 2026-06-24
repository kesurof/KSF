# ============================================================
# KSF — Cloudflare DNS helper
# ============================================================
#
# Objectif :
# - créer automatiquement une entrée DNS à l'installation d'une app
# - supprimer automatiquement l'entrée DNS à la suppression d'une app
#
# Configuration attendue dans :
#   ~/serverbox/config/ksf.env
#
# Variables attendues :
#   DOMAIN=example.com
#   DEFAULT_DOMAIN=example.com  # interne, automatiquement égal à DOMAIN
#   DOMAINS=example.com,example.net
#   CF_API_EMAIL=...
#   CF_API_KEY=...
#   SERVER_PUBLIC_IP=...
#
# Variables optionnelles :
#   DNS_AUTO_CREATE=true
#   DNS_PROVIDER=cloudflare
#   DNS_RECORD_TTL=1
#   DNS_RECORD_PROXIED=true
#
# Fonctions publiques :
#   dns_ensure_record "app.example.com"
#   dns_delete_record "app.example.com"
# ============================================================

KSF_ENV="${BASE_DIR:-${HOME}/serverbox}/config/ksf.env"

DNS_PROVIDER="${DNS_PROVIDER:-cloudflare}"
DNS_AUTO_CREATE="${DNS_AUTO_CREATE:-false}"
DNS_RECORD_TYPE="${DNS_RECORD_TYPE:-A}"
DNS_RECORD_TTL="${DNS_RECORD_TTL:-1}"
DNS_RECORD_PROXIED="${DNS_RECORD_PROXIED:-true}"

# ------------------------------------------------------------
# Fallback logs si le fichier est utilisé hors contexte KSF
# ------------------------------------------------------------

if ! command -v info >/dev/null 2>&1; then
  info() {
    echo "[INFO] $*"
  }
fi

if ! command -v ok >/dev/null 2>&1; then
  ok() {
    echo "[OK] $*"
  }
fi

if ! command -v warn >/dev/null 2>&1; then
  warn() {
    echo "[WARN] $*" >&2
  }
fi

if ! command -v err >/dev/null 2>&1; then
  err() {
    echo "[ERREUR] $*" >&2
  }
fi

# ------------------------------------------------------------
# Chargement config
# ------------------------------------------------------------

dns_load_config() {
  if [ -f "${KSF_ENV}" ]; then
    # shellcheck disable=SC1090
    source "${KSF_ENV}"
  fi

  DNS_PROVIDER="${DNS_PROVIDER:-cloudflare}"
  DNS_AUTO_CREATE="${DNS_AUTO_CREATE:-false}"
  DNS_RECORD_TYPE="${DNS_RECORD_TYPE:-A}"
  DNS_RECORD_TTL="${DNS_RECORD_TTL:-1}"
  DNS_RECORD_PROXIED="${DNS_RECORD_PROXIED:-true}"
}

dns_is_enabled() {
  dns_load_config

  if [ "${DNS_AUTO_CREATE:-false}" != "true" ]; then
    return 1
  fi

  if [ "${DNS_PROVIDER:-cloudflare}" != "cloudflare" ]; then
    return 1
  fi

  return 0
}

dns_require_tools() {
  if ! command -v curl >/dev/null 2>&1; then
    err "curl est requis pour gérer les DNS Cloudflare."
    return 1
  fi

  if ! command -v jq >/dev/null 2>&1; then
    err "jq est requis pour gérer les DNS Cloudflare."
    err "Installation : sudo apt-get install -y jq"
    return 1
  fi

  return 0
}

dns_require_config() {
  dns_load_config

  if [ -z "$(dns_allowed_domains)" ]; then
    err "DOMAINS ou DOMAIN est absent de ${KSF_ENV}."
    return 1
  fi

  if [ -z "${CF_API_EMAIL:-}" ]; then
    err "CF_API_EMAIL est absent de ${KSF_ENV}."
    return 1
  fi

  if [ -z "${CF_API_KEY:-}" ]; then
    err "CF_API_KEY est absent de ${KSF_ENV}."
    return 1
  fi

  if [ -z "${SERVER_PUBLIC_IP:-}" ]; then
    err "SERVER_PUBLIC_IP est absent de ${KSF_ENV}."
    err "Ajoute par exemple : SERVER_PUBLIC_IP=xx.xx.xx.xx"
    return 1
  fi

  return 0
}

dns_allowed_domains() {
  local configured="${DOMAINS:-${DOMAIN:-}}"
  configured="${configured//[[:space:]]/}"
  printf '%s' "${configured}"
}

dns_validate_host() {
  local host="${1:-}"
  local configured remaining candidate matched=""

  host="${host//[[:space:]]/}"
  configured="$(dns_allowed_domains)"

  if [ -z "${host}" ]; then
    err "Hostname DNS vide."
    return 1
  fi
  if [ -z "${configured}" ]; then
    err "Aucun domaine DNS autorisé. Configure DOMAINS ou DOMAIN dans ${KSF_ENV}."
    return 1
  fi

  remaining="${configured},"
  while [ -n "${remaining}" ]; do
    candidate="${remaining%%,*}"
    remaining="${remaining#*,}"
    [ -n "${candidate}" ] || continue

    if [ "${host}" = "${candidate}" ]; then
      err "Refus de modifier directement le domaine racine : ${candidate}"
      return 1
    fi

    case "${host}" in
      *".${candidate}")
        if [ "${#candidate}" -gt "${#matched}" ]; then
          matched="${candidate}"
        fi
        ;;
    esac
  done

  if [ -n "${matched}" ]; then
    printf '%s' "${matched}"
    return 0
  fi

  err "Le hostname ${host} ne correspond à aucun domaine autorisé : ${configured}"
  return 1
}

# ------------------------------------------------------------
# API Cloudflare
# ------------------------------------------------------------

dns_cf_api() {
  local method="$1"
  local endpoint="$2"
  local data="${3:-}"

  if [ -n "${data}" ]; then
    curl -sS -X "${method}" "https://api.cloudflare.com/client/v4${endpoint}" \
      -H "X-Auth-Email: ${CF_API_EMAIL}" \
      -H "X-Auth-Key: ${CF_API_KEY}" \
      -H "Content-Type: application/json" \
      --data "${data}"
  else
    curl -sS -X "${method}" "https://api.cloudflare.com/client/v4${endpoint}" \
      -H "X-Auth-Email: ${CF_API_EMAIL}" \
      -H "X-Auth-Key: ${CF_API_KEY}" \
      -H "Content-Type: application/json"
  fi
}

dns_cf_zone_id() {
  local zone_name="$1"
  local response
  response="$(dns_cf_api GET "/zones?name=${zone_name}&status=active")"

  if [ "$(echo "${response}" | jq -r '.success')" != "true" ]; then
    err "Impossible d'interroger Cloudflare pour la zone ${zone_name}."
    echo "${response}" | jq . >&2
    return 1
  fi

  local zone_id
  zone_id="$(echo "${response}" | jq -r '.result[0].id // empty')"

  if [ -z "${zone_id}" ]; then
    err "Zone Cloudflare introuvable : ${zone_name}"
    return 1
  fi

  echo "${zone_id}"
}

dns_cf_find_record_id() {
  local zone_id="$1"
  local host="$2"

  local response
  response="$(dns_cf_api GET "/zones/${zone_id}/dns_records?type=${DNS_RECORD_TYPE}&name=${host}")"

  if [ "$(echo "${response}" | jq -r '.success')" != "true" ]; then
    err "Impossible de rechercher l'entrée DNS : ${host}"
    echo "${response}" | jq . >&2
    return 1
  fi

  echo "${response}" | jq -r '.result[0].id // empty'
}

# ------------------------------------------------------------
# Création / mise à jour
# ------------------------------------------------------------

dns_ensure_record() {
  local host="${1:-}"
  local target_ip="${2:-${SERVER_PUBLIC_IP:-}}"
  local zone_name

  dns_is_enabled || {
    info "DNS automatique désactivé."
    return 0
  }

  zone_name="$(dns_validate_host "${host}")" || return 1
  target_ip="${target_ip:-${SERVER_PUBLIC_IP:-}}"

  if [ "${DRY_RUN:-false}" = "true" ]; then
    warn "[DRY-RUN] Création/mise à jour DNS : ${host} -> ${target_ip:-SERVER_PUBLIC_IP}"
    return 0
  fi

  dns_require_tools || return 1
  dns_require_config || return 1
  target_ip="${target_ip:-${SERVER_PUBLIC_IP:-}}"

  if [ -z "${target_ip}" ]; then
    err "IP cible absente. SERVER_PUBLIC_IP doit être défini dans ${KSF_ENV}."
    return 1
  fi

  local zone_id
  zone_id="$(dns_cf_zone_id "${zone_name}")" || return 1

  local existing_id
  existing_id="$(dns_cf_find_record_id "${zone_id}" "${host}")" || return 1

  DNS_RECORD_TTL="${DNS_RECORD_TTL:-1}"
  DNS_RECORD_PROXIED="${DNS_RECORD_PROXIED:-true}"

  local payload
  payload="$(jq -n \
    --arg type "${DNS_RECORD_TYPE}" \
    --arg name "${host}" \
    --arg content "${target_ip}" \
    --argjson ttl "${DNS_RECORD_TTL}" \
    --argjson proxied "${DNS_RECORD_PROXIED}" \
    '{
      type: $type,
      name: $name,
      content: $content,
      ttl: $ttl,
      proxied: $proxied,
      comment: "KSF automatic app DNS"
    }'
  )"

  if [ -n "${existing_id}" ]; then
    info "Mise à jour DNS : ${host} -> ${target_ip}"

    local response
    response="$(dns_cf_api PUT "/zones/${zone_id}/dns_records/${existing_id}" "${payload}")"

    if [ "$(echo "${response}" | jq -r '.success')" = "true" ]; then
      ok "Entrée DNS mise à jour : ${host}"
      return 0
    fi

    err "Échec mise à jour DNS : ${host}"
    echo "${response}" | jq . >&2
    return 1
  fi

  info "Création DNS : ${host} -> ${target_ip}"

  local response
  response="$(dns_cf_api POST "/zones/${zone_id}/dns_records" "${payload}")"

  if [ "$(echo "${response}" | jq -r '.success')" = "true" ]; then
    ok "Entrée DNS créée : ${host}"
    return 0
  fi

  err "Échec création DNS : ${host}"
  echo "${response}" | jq . >&2
  return 1
}

# ------------------------------------------------------------
# Suppression
# ------------------------------------------------------------

dns_delete_record() {
  local host="${1:-}"
  local zone_name

  dns_is_enabled || {
    info "DNS automatique désactivé."
    return 0
  }

  zone_name="$(dns_validate_host "${host}")" || return 1

  if [ "${DRY_RUN:-false}" = "true" ]; then
    warn "[DRY-RUN] Suppression DNS : ${host}"
    return 0
  fi

  dns_require_tools || return 1
  dns_require_config || return 1

  local zone_id
  zone_id="$(dns_cf_zone_id "${zone_name}")" || return 1

  local existing_id
  existing_id="$(dns_cf_find_record_id "${zone_id}" "${host}")" || return 1

  if [ -z "${existing_id}" ]; then
    warn "Aucune entrée DNS à supprimer pour : ${host}"
    return 0
  fi

  info "Suppression DNS : ${host}"

  local response
  response="$(dns_cf_api DELETE "/zones/${zone_id}/dns_records/${existing_id}")"

  if [ "$(echo "${response}" | jq -r '.success')" = "true" ]; then
    ok "Entrée DNS supprimée : ${host}"
    return 0
  fi

  err "Échec suppression DNS : ${host}"
  echo "${response}" | jq . >&2
  return 1
}

# ============================================================
# Cloudflare cache purge (Phase 0)
# ============================================================
#
# Purge ciblée de fichiers du cache edge après un déploiement.
# Échoue silencieusement (avec un warn) si les credentials manquent.
# Utilise CF_API_TOKEN (recommandé) ou fallback CF_API_KEY + CF_API_EMAIL.
#
# Variables attendues dans ${KSF_ENV} :
#   CF_ZONE_ID=...            # obligatoire pour purger par API
#   CF_API_TOKEN=...          # recommandé (scope: zone cache purge)
#   CF_API_KEY=...            # legacy fallback
#   CF_API_EMAIL=...          # legacy fallback (avec CF_API_KEY)
#   CF_PURGE_PATHS="/static/app.css ..."   # défaut ci-dessous
#   CF_CACHE_PURGE_ON_DEPLOY=true          # opt-in
#   DOMAIN=example.com                     # pour construire les URLs

cf_purge_cache() {
  local paths="${1:-${CF_PURGE_PATHS:-/static/app.css /static/vendor/htmx.min.js /static/vendor/htmx-sse.js}}"
  local domain="${DOMAIN:-${DOMAINS%%,*}}"
  domain="${domain//[[:space:]]/}"

  if [ "${CF_CACHE_PURGE_ON_DEPLOY:-false}" != "true" ]; then
    return 0
  fi
  if [ -z "${CF_ZONE_ID:-}" ]; then
    warn "CF_ZONE_ID absent, purge cache ignorée."
    return 0
  fi
  if [ -z "${paths}" ]; then
    warn "CF_PURGE_PATHS vide, purge cache ignorée."
    return 0
  fi
  if [ -z "${domain}" ]; then
    warn "DOMAIN absent, purge cache ignorée."
    return 0
  fi

  local payload="{\"files\":["
  local first=true
  local p
  for p in ${paths}; do
    if [ "${first}" = true ]; then
      first=false
    else
      payload="${payload},"
    fi
    payload="${payload}\"https://${domain}${p}\""
  done
  payload="${payload}]}"

  local response
  if [ -n "${CF_API_TOKEN:-}" ]; then
    response="$(curl -sS -X POST "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/purge_cache" \
      -H "Authorization: Bearer ${CF_API_TOKEN}" \
      -H "Content-Type: application/json" \
      --data "${payload}")" || {
      warn "curl a échoué vers l'API Cloudflare, purge cache ignorée."
      return 0
    }
  elif [ -n "${CF_API_KEY:-}" ] && [ -n "${CF_API_EMAIL:-}" ]; then
    response="$(curl -sS -X POST "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/purge_cache" \
      -H "X-Auth-Email: ${CF_API_EMAIL}" \
      -H "X-Auth-Key: ${CF_API_KEY}" \
      -H "Content-Type: application/json" \
      --data "${payload}")" || {
      warn "curl a échoué vers l'API Cloudflare, purge cache ignorée."
      return 0
    }
  else
    warn "CF_API_TOKEN (ou CF_API_KEY + CF_API_EMAIL) absent, purge cache ignorée."
    return 0
  fi

  if printf '%s' "${response}" | grep -q '"success":true'; then
    ok "Cache Cloudflare purgé : ${paths}"
    return 0
  fi
  warn "Échec purge cache Cloudflare : ${response}"
  return 0
}
