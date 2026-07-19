#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# KSF — Déploiement infrastructure
# Réseau, Traefik, OAuth2 Proxy, CrowdSec
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

# ---------- Valeurs par défaut ----------
BASE_DIR="${BASE_DIR:-${HOME}/serverbox}"
NETWORK_NAME="ksf-proxy"
TZ_VALUE="${TZ:-Europe/Paris}"
WITH_TRAEFIK=false
AUTO_YES=false
FORCE=false
ACME_EMAIL=""
DRY_RUN=false
DOMAIN=""
DEFAULT_DOMAIN=""
DOMAINS=""
CF_API_EMAIL=""
CF_API_KEY=""
SERVER_PUBLIC_IP=""
DNS_AUTO_CREATE=""
DNS_PROVIDER=""
DNS_RECORD_TTL=""
DNS_RECORD_PROXIED=""
TRAEFIK_HOST=""
TRAEFIK_TRUSTED_IPS=""
TRAEFIK_TRUSTED_IPS_YAML="[]"
OAUTH2_ENABLED=false
OAUTH2_CLIENT_ID=""
OAUTH2_CLIENT_SECRET=""
OAUTH2_ALLOWED_EMAILS=""
OAUTH2_GITHUB_USER=""
OAUTH2_AUTH_MODE=""
OAUTH2_SCOPE=""
OAUTH2_EMAIL_DOMAINS=""
OAUTH2_AUTHENTICATED_EMAILS_FILE=""
OAUTH2_HOST=""
OAUTH2_COOKIE_SECRET=""
CROWDSEC_BOUNCER_KEY=""
CROWDSEC_APPSEC_ENABLED=false
CROWDSEC_APPSEC_LISTEN_ADDR="0.0.0.0:7422"
CROWDSEC_APPSEC_HOST="crowdsec:7422"
CROWDSEC_APPSEC_FAILURE_BLOCK=true
CROWDSEC_APPSEC_UNREACHABLE_BLOCK=true
CROWDSEC_APPSEC_COLLECTIONS="crowdsecurity/appsec-virtual-patching crowdsecurity/appsec-generic-rules"
TRAEFIK_START_STATUS="inactif"
OAUTH2_START_STATUS="inactif"
CROWDSEC_START_STATUS="inactif"
CONFIG_LOADED=false
NETWORK_NAME_SET=false
TZ_VALUE_SET=false
WITH_CROWDSEC=false
ACME_EMAIL_SET=false
DOMAIN_SET=false
CF_API_EMAIL_SET=false
CF_API_KEY_SET=false
SERVER_PUBLIC_IP_SET=false
DNS_AUTO_CREATE_SET=false
DNS_PROVIDER_SET=false
TRAEFIK_HOST_SET=false
TRAEFIK_TRUSTED_IPS_SET=false
WITH_TRAEFIK_SET=false
WITH_CROWDSEC_SET=false
CROWDSEC_BOUNCER_KEY_SET=false
CROWDSEC_APPSEC_ENABLED_SET=false
CROWDSEC_APPSEC_LISTEN_ADDR_SET=false
CROWDSEC_APPSEC_HOST_SET=false
CROWDSEC_APPSEC_FAILURE_BLOCK_SET=false
CROWDSEC_APPSEC_UNREACHABLE_BLOCK_SET=false
CROWDSEC_APPSEC_COLLECTIONS_SET=false
OAUTH2_ENABLED_SET=false
OAUTH2_HOST_SET=false
OAUTH2_CLIENT_ID_SET=false
OAUTH2_CLIENT_SECRET_SET=false
OAUTH2_ALLOWED_EMAILS_SET=false
OAUTH2_GITHUB_USER_SET=false
OAUTH2_COOKIE_SECRET_SET=false
WITH_WEBUI=false
TRAEFIK_ONLY_CLI=false

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --base-dir PATH         Répertoire racine (défaut: ~/serverbox)
  --network NAME          Nom du réseau Docker (défaut: ksf-proxy)
  --tz TZ                 Fuseau horaire
  --acme-email EMAIL      Email pour Let's Encrypt (avec --with-traefik)
  --domain DOMAIN         Domaine principal
  --cf-api-email EMAIL    Email du compte Cloudflare (avec --with-traefik)
  --cf-api-key KEY        Clé API globale Cloudflare (avec --with-traefik)
  --server-public-ip IP   IP publique utilisée pour les DNS applicatifs
  --dns-auto-create       Active la création DNS applicative automatique
  --no-dns-auto-create    Désactive la création DNS applicative automatique
  --dns-provider NAME     Fournisseur DNS applicatif (défaut: cloudflare)
  --traefik-host HOST     Hostname Traefik (défaut: traefik.<DOMAIN>)
  --traefik-trusted-ips CIDRS|cloudflare  Proxies CIDR de confiance pour X-Forwarded-For
  --with-traefik          Génère une stack Traefik
  --with-crowdsec         Génère CrowdSec et le middleware Traefik bouncer
  --with-appsec           Active AppSec / WAF (implique --with-crowdsec et --with-traefik)
  --crowdsec-bouncer-key KEY  Clé bouncer Traefik CrowdSec (générée si absente)
  --oauth-client-id ID    GitHub OAuth Client ID
  --oauth-client-secret SEC  GitHub OAuth Client Secret
  --oauth-allowed-email EMAILS  Emails GitHub autorisés, séparés par virgule (recommandé)
  --oauth-github-user USER  Utilisateur GitHub autorisé (mode avancé)
  --oauth-host HOST       Hostname OAuth2 (défaut: oauth2.<DOMAIN>)
  --oauth-cookie-secret SEC  Secret cookie OAuth2 Proxy, 16/24/32 caractères
  --with-webui              Installer le Web UI (webui.<DOMAIN>)
  --dry-run             Affiche les actions sans modifier les fichiers
  --force               Force la réinstallation (attention: écrase les fichiers existants)
  -y, --yes               Répondre oui automatiquement
  -h, --help              Affiche l'aide
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-dir)       BASE_DIR="$2";     shift 2 ;;
    --network)        NETWORK_NAME="$2"; NETWORK_NAME_SET=true; shift 2 ;;
    --tz)             TZ_VALUE="$2"; TZ_VALUE_SET=true; shift 2 ;;
    --acme-email)     ACME_EMAIL="$2"; ACME_EMAIL_SET=true; shift 2 ;;
    --domain)         DOMAIN="$2"; DOMAIN_SET=true; shift 2 ;;
    --cf-api-email)   CF_API_EMAIL="$2"; CF_API_EMAIL_SET=true; shift 2 ;;
    --cf-api-key)     CF_API_KEY="$2"; CF_API_KEY_SET=true; shift 2 ;;
    --server-public-ip) SERVER_PUBLIC_IP="$2"; SERVER_PUBLIC_IP_SET=true; shift 2 ;;
    --dns-auto-create) DNS_AUTO_CREATE=true; DNS_AUTO_CREATE_SET=true; shift ;;
    --no-dns-auto-create) DNS_AUTO_CREATE=false; DNS_AUTO_CREATE_SET=true; shift ;;
    --dns-provider)    DNS_PROVIDER="$2"; DNS_PROVIDER_SET=true; shift 2 ;;
    --traefik-host)   TRAEFIK_HOST="$2"; TRAEFIK_HOST_SET=true; shift 2 ;;
    --traefik-trusted-ips) TRAEFIK_TRUSTED_IPS="$2"; TRAEFIK_TRUSTED_IPS_SET=true; shift 2 ;;
    --with-traefik)   WITH_TRAEFIK=true; WITH_TRAEFIK_SET=true; shift ;;
    --with-crowdsec)  WITH_CROWDSEC=true; WITH_CROWDSEC_SET=true; WITH_TRAEFIK=true; WITH_TRAEFIK_SET=true; shift ;;
    --with-appsec)    CROWDSEC_APPSEC_ENABLED=true; CROWDSEC_APPSEC_ENABLED_SET=true; WITH_CROWDSEC=true; WITH_CROWDSEC_SET=true; WITH_TRAEFIK=true; WITH_TRAEFIK_SET=true; shift ;;
    --crowdsec-bouncer-key) CROWDSEC_BOUNCER_KEY="$2"; CROWDSEC_BOUNCER_KEY_SET=true; WITH_CROWDSEC=true; WITH_CROWDSEC_SET=true; WITH_TRAEFIK=true; WITH_TRAEFIK_SET=true; shift 2 ;;
    --oauth-client-id)    OAUTH2_CLIENT_ID="$2"; OAUTH2_CLIENT_ID_SET=true; OAUTH2_ENABLED=true; OAUTH2_ENABLED_SET=true; shift 2 ;;
    --oauth-client-secret) OAUTH2_CLIENT_SECRET="$2"; OAUTH2_CLIENT_SECRET_SET=true; OAUTH2_ENABLED=true; OAUTH2_ENABLED_SET=true; shift 2 ;;
    --oauth-allowed-email) OAUTH2_ALLOWED_EMAILS="${OAUTH2_ALLOWED_EMAILS:+${OAUTH2_ALLOWED_EMAILS},}$2"; OAUTH2_ALLOWED_EMAILS_SET=true; OAUTH2_ENABLED=true; OAUTH2_ENABLED_SET=true; shift 2 ;;
    --oauth-github-user)  OAUTH2_GITHUB_USER="$2"; OAUTH2_GITHUB_USER_SET=true; OAUTH2_ENABLED=true; OAUTH2_ENABLED_SET=true; shift 2 ;;
    --oauth-host)         OAUTH2_HOST="$2"; OAUTH2_HOST_SET=true; shift 2 ;;
    --oauth-cookie-secret) OAUTH2_COOKIE_SECRET="$2"; OAUTH2_COOKIE_SECRET_SET=true; OAUTH2_ENABLED=true; OAUTH2_ENABLED_SET=true; shift 2 ;;
    --with-webui)     WITH_WEBUI=true;   shift ;;
    --dry-run)        DRY_RUN=true;      shift ;;
    --force)          FORCE=true;        shift ;;
    -y|--yes)         AUTO_YES=true;     shift ;;
    -h|--help)        usage ;;
    *)                echo "Option inconnue: $1"; usage ;;
  esac
done

if [ "$WITH_TRAEFIK_SET" = true ] && [ "$WITH_CROWDSEC_SET" = false ] && [ "$OAUTH2_ENABLED_SET" = false ]; then
  TRAEFIK_ONLY_CLI=true
fi

validate_execution_allowed() {
  local env_file="${BASE_DIR}/config/ksf.env"
  local choice

  if [ -f "${env_file}" ] && [ "$FORCE" = false ]; then
    err "KSF semble déjà installé (${env_file} présent)."

    if [ "${AUTO_YES}" = true ]; then
      err "Relance avec --force pour régénérer : ./deploy.sh --force"
      exit 1
    fi

    while true; do
      echo ""
      echo "Que voulez-vous faire ?"
      echo "  1) Forcer la réinstallation"
      echo "  2) Annuler"
      echo -n "Choix [2] : "
      read -r choice
      case "${choice:-2}" in
        1)
          FORCE=true
          warn "Réinstallation forcée demandée. La configuration existante sera régénérée."
          return 0
          ;;
        2)
          warn "Installation annulée."
          exit 0
          ;;
        *)
          warn "Choix invalide."
          ;;
      esac
    done
  fi
}

load_existing_deploy_config() {
  local env_file="${BASE_DIR}/config/ksf.env"
  local key value

  [ -f "${env_file}" ] || return 0

  CONFIG_LOADED=true

  while IFS='=' read -r key value || [ -n "${key}" ]; do
    value="$(ksf_env_unquote_value "$value")"
    case "${key}" in
      NETWORK_NAME)
        [ "${NETWORK_NAME_SET}" = false ] && NETWORK_NAME="${value}"
        ;;
      TZ_VALUE)
        [ "${TZ_VALUE_SET}" = false ] && TZ_VALUE="${value}"
        ;;
      DOMAIN)
        [ "${DOMAIN_SET}" = false ] && DOMAIN="${value}"
        ;;
      DEFAULT_DOMAIN)
        [ -z "${DEFAULT_DOMAIN}" ] && DEFAULT_DOMAIN="${value}"
        ;;
      DOMAINS)
        [ -z "${DOMAINS}" ] && DOMAINS="${value}"
        ;;
      CF_API_EMAIL)
        [ "${CF_API_EMAIL_SET}" = false ] && CF_API_EMAIL="${value}"
        ;;
      CF_API_KEY)
        [ "${CF_API_KEY_SET}" = false ] && CF_API_KEY="${value}"
        ;;
      SERVER_PUBLIC_IP)
        [ "${SERVER_PUBLIC_IP_SET}" = false ] && SERVER_PUBLIC_IP="${value}"
        ;;
      DNS_AUTO_CREATE)
        [ "${DNS_AUTO_CREATE_SET}" = false ] && DNS_AUTO_CREATE="${value}"
        ;;
      DNS_PROVIDER)
        [ "${DNS_PROVIDER_SET}" = false ] && DNS_PROVIDER="${value}"
        ;;
      DNS_RECORD_TTL)
        [ -z "${DNS_RECORD_TTL}" ] && DNS_RECORD_TTL="${value}"
        ;;
      DNS_RECORD_PROXIED)
        [ -z "${DNS_RECORD_PROXIED}" ] && DNS_RECORD_PROXIED="${value}"
        ;;
      WITH_TRAEFIK)
        [ "${WITH_TRAEFIK_SET}" = false ] && WITH_TRAEFIK="${value}"
        ;;
      ACME_EMAIL)
        [ "${ACME_EMAIL_SET}" = false ] && ACME_EMAIL="${value}"
        ;;
      TRAEFIK_HOST)
        [ "${TRAEFIK_HOST_SET}" = false ] && TRAEFIK_HOST="${value}"
        ;;
      TRAEFIK_TRUSTED_IPS)
        [ "${TRAEFIK_TRUSTED_IPS_SET}" = false ] && TRAEFIK_TRUSTED_IPS="${value}"
        ;;
      WITH_CROWDSEC)
        if [ "${WITH_CROWDSEC_SET}" = false ] && [ "${TRAEFIK_ONLY_CLI}" = false ]; then
          WITH_CROWDSEC="${value}"
        fi
        ;;
      CROWDSEC_BOUNCER_KEY)
        [ "${CROWDSEC_BOUNCER_KEY_SET}" = false ] && CROWDSEC_BOUNCER_KEY="${value}"
        ;;
      CROWDSEC_APPSEC_ENABLED)
        if [ "${CROWDSEC_APPSEC_ENABLED_SET}" = false ] && [ "${TRAEFIK_ONLY_CLI}" = false ]; then
          CROWDSEC_APPSEC_ENABLED="${value}"
        fi
        ;;
      CROWDSEC_APPSEC_LISTEN_ADDR)
        [ "${CROWDSEC_APPSEC_LISTEN_ADDR_SET}" = false ] && CROWDSEC_APPSEC_LISTEN_ADDR="${value}"
        ;;
      CROWDSEC_APPSEC_HOST)
        [ "${CROWDSEC_APPSEC_HOST_SET}" = false ] && CROWDSEC_APPSEC_HOST="${value}"
        ;;
      CROWDSEC_APPSEC_FAILURE_BLOCK)
        [ "${CROWDSEC_APPSEC_FAILURE_BLOCK_SET}" = false ] && CROWDSEC_APPSEC_FAILURE_BLOCK="${value}"
        ;;
      CROWDSEC_APPSEC_UNREACHABLE_BLOCK)
        [ "${CROWDSEC_APPSEC_UNREACHABLE_BLOCK_SET}" = false ] && CROWDSEC_APPSEC_UNREACHABLE_BLOCK="${value}"
        ;;
      CROWDSEC_APPSEC_COLLECTIONS)
        [ "${CROWDSEC_APPSEC_COLLECTIONS_SET}" = false ] && CROWDSEC_APPSEC_COLLECTIONS="${value}"
        ;;
      OAUTH2_ENABLED)
        if [ "${OAUTH2_ENABLED_SET}" = false ] && [ "${TRAEFIK_ONLY_CLI}" = false ]; then
          OAUTH2_ENABLED="${value}"
        fi
        ;;
      OAUTH2_HOST)
        [ "${OAUTH2_HOST_SET}" = false ] && OAUTH2_HOST="${value}"
        ;;
      OAUTH2_CLIENT_ID)
        [ "${OAUTH2_CLIENT_ID_SET}" = false ] && OAUTH2_CLIENT_ID="${value}"
        ;;
      OAUTH2_CLIENT_SECRET)
        [ "${OAUTH2_CLIENT_SECRET_SET}" = false ] && OAUTH2_CLIENT_SECRET="${value}"
        ;;
      OAUTH2_ALLOWED_EMAILS)
        [ "${OAUTH2_ALLOWED_EMAILS_SET}" = false ] && OAUTH2_ALLOWED_EMAILS="${value}"
        ;;
      OAUTH2_GITHUB_USER)
        [ "${OAUTH2_GITHUB_USER_SET}" = false ] && OAUTH2_GITHUB_USER="${value}"
        ;;
      OAUTH2_AUTH_MODE)
        [ -z "${OAUTH2_AUTH_MODE}" ] && OAUTH2_AUTH_MODE="${value}"
        ;;
      OAUTH2_SCOPE)
        [ -z "${OAUTH2_SCOPE}" ] && OAUTH2_SCOPE="${value}"
        ;;
      OAUTH2_EMAIL_DOMAINS)
        [ -z "${OAUTH2_EMAIL_DOMAINS}" ] && OAUTH2_EMAIL_DOMAINS="${value}"
        ;;
      OAUTH2_AUTHENTICATED_EMAILS_FILE)
        [ -z "${OAUTH2_AUTHENTICATED_EMAILS_FILE}" ] && OAUTH2_AUTHENTICATED_EMAILS_FILE="${value}"
        ;;
      OAUTH2_COOKIE_SECRET)
        [ "${OAUTH2_COOKIE_SECRET_SET}" = false ] && OAUTH2_COOKIE_SECRET="${value}"
        ;;
    esac
  done < "${env_file}"
}

normalize_domains_value() {
  local value="${1:-}"
  value="${value//[[:space:]]/}"
  value="${value//\"/}"
  value="${value//\'/}"
  printf '%s' "${value}"
}

format_yaml_inline_list() {
  local value="${1:-}"
  local item
  local rendered=""
  local -a items

  value="${value//[[:space:]]/}"
  value="${value//\"/}"
  value="${value//\'/}"
  IFS=',' read -r -a items <<< "$value"
  for item in "${items[@]}"; do
    if [ -n "$item" ]; then
      rendered="${rendered:+${rendered}, }\"${item}\""
    fi
  done
  if [ -n "$rendered" ]; then
    printf '[%s]' "$rendered"
  else
    printf '[]'
  fi
}

normalize_trusted_ips_value() {
  local value="${1:-}"
  local normalized=""
  local item
  local -a items

  value="${value//[[:space:]]/}"
  value="${value//\"/}"
  value="${value//\'/}"
  IFS=',' read -r -a items <<< "$value"
  for item in "${items[@]}"; do
    [ -n "$item" ] && normalized="${normalized:+${normalized},}${item}"
  done
  printf '%s' "$normalized"
}

resolve_trusted_ips_value() {
  local value="${1:-}"

  value="$(normalize_trusted_ips_value "$value")"
  if [ "$value" = "cloudflare" ]; then
    info "Récupération des plages IP Cloudflare officielles pour Traefik..." >&2
    fetch_cloudflare_trusted_ips || exit 1
    return 0
  fi
  printf '%s' "$value"
}

domain_list_contains() {
  local list="${1:-}"
  local domain="${2:-}"
  local item
  local -a items

  [ -n "$domain" ] || return 1
  IFS=',' read -r -a items <<< "$list"
  for item in "${items[@]}"; do
    if [ "$item" = "$domain" ]; then
      return 0
    fi
  done
  return 1
}

detect_server_public_ip() {
  if ! command -v curl >/dev/null 2>&1; then
    return 1
  fi

  curl -fsS --max-time 3 https://api.ipify.org 2>/dev/null || true
}

display_path() {
  local path="$1"

  if [ "$path" = "$HOME" ]; then
    printf '~'
    return 0
  fi
  if [[ "$path" == "$HOME/"* ]]; then
    printf '~/%s' "${path#"$HOME/"}"
    return 0
  fi
  printf '%s' "$path"
}

display_value() {
  local value="${1:-}"
  local fallback="${2:-non renseigné}"

  if [ -n "$value" ]; then
    printf '%s' "$value"
  else
    printf '%s' "$fallback"
  fi
}

display_secret() {
  local value="${1:-}"

  if [ -n "$value" ]; then
    printf 'renseigné (masqué)'
  else
    printf 'non renseigné'
  fi
}

display_secret_auto() {
  local value="${1:-}"

  if [ -n "$value" ]; then
    printf 'renseigné (masqué)'
  else
    printf 'généré automatiquement'
  fi
}

display_presence() {
  local value="${1:-}"

  if [ -n "$value" ]; then
    printf 'renseigné'
  else
    printf 'non renseigné'
  fi
}

display_bool() {
  if [ "${1:-false}" = true ]; then
    printf 'actif'
  else
    printf 'inactif'
  fi
}

is_yes() {
  case "${1:-}" in
    o|O|oui|Oui|OUI|y|Y|yes|Yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

section_title() {
  echo ""
  echo "------------------------------------------------------------"
  echo " $*"
  echo "------------------------------------------------------------"
}

normalize_oauth2_allowed_emails() {
  local raw="${OAUTH2_ALLOWED_EMAILS}"
  local normalized=""
  local email
  local -a email_items

  raw="${raw// /}"
  raw="${raw//$'\t'/}"
  IFS=',' read -r -a email_items <<< "$raw"
  for email in "${email_items[@]}"; do
    if [ -n "$email" ]; then
      normalized="${normalized:+${normalized},}${email}"
    fi
  done

  OAUTH2_ALLOWED_EMAILS="$normalized"
}

display_yes_no() {
  if [ "${1:-false}" = true ]; then
    printf 'oui'
  else
    printf 'non'
  fi
}

ask_text() {
  local var_name="$1"
  local prompt="$2"
  local default_value="${3:-}"
  local current_value="${!var_name:-}"
  local input

  [ -n "$current_value" ] || current_value="$default_value"
  if [ -n "$current_value" ]; then
    echo -n "${prompt} [${current_value}] : "
  else
    echo -n "${prompt} : "
  fi
  read -r input
  if [ "$input" = "-" ]; then
    printf -v "$var_name" '%s' ""
  elif [ -n "$input" ]; then
    printf -v "$var_name" '%s' "$input"
  elif [ -z "${!var_name:-}" ] && [ -n "$default_value" ]; then
    printf -v "$var_name" '%s' "$default_value"
  fi
}

ask_secret() {
  local var_name="$1"
  local prompt="$2"
  local input

  if [ -n "${!var_name:-}" ]; then
    echo -n "${prompt} [renseigné, Entrée conserve] : "
  else
    echo -n "${prompt} : "
  fi
  read -r -s input
  echo ""
  if [ "$input" = "-" ]; then
    printf -v "$var_name" '%s' ""
  elif [ -n "$input" ]; then
    printf -v "$var_name" '%s' "$input"
  fi
}

ask_bool() {
  local var_name="$1"
  local prompt="$2"
  local input
  local current_value="${!var_name:-false}"

  echo -n "${prompt} (oui/non) [$(display_yes_no "$current_value")] : "
  read -r input
  if [ -z "$input" ]; then
    return 0
  fi
  if is_yes "$input"; then
    printf -v "$var_name" '%s' true
  else
    printf -v "$var_name" '%s' false
  fi
}

configure_oauth2_authorization() {
  OAUTH2_AUTH_MODE=""
  OAUTH2_SCOPE=""
  OAUTH2_EMAIL_DOMAINS=""
  OAUTH2_AUTHENTICATED_EMAILS_FILE=""

  if [ "$OAUTH2_ENABLED" != true ]; then
    return 0
  fi

  normalize_oauth2_allowed_emails

  if [ -n "$OAUTH2_ALLOWED_EMAILS" ] && [ -n "$OAUTH2_GITHUB_USER" ]; then
    OAUTH2_AUTH_MODE="conflict"
    return 0
  fi

  if [ -n "$OAUTH2_ALLOWED_EMAILS" ]; then
    OAUTH2_AUTH_MODE="email"
    OAUTH2_SCOPE="user"
    OAUTH2_EMAIL_DOMAINS="*"
    OAUTH2_AUTHENTICATED_EMAILS_FILE="/auth/allowed-emails.txt"
    return 0
  fi

  if [ -n "$OAUTH2_GITHUB_USER" ]; then
    OAUTH2_AUTH_MODE="github-user"
    OAUTH2_SCOPE="user"
  fi
}

prepare_deploy_config() {
  if [ "$DRY_RUN" = true ] && [ "$AUTO_YES" = true ]; then
    [ -n "$DOMAIN" ] || DOMAIN="example.com"
    [ -n "$DOMAINS" ] || DOMAINS="$DOMAIN"
    [ -n "$ACME_EMAIL" ] || ACME_EMAIL="admin@example.com"
    [ -n "$CF_API_EMAIL" ] || CF_API_EMAIL="admin@example.com"
    [ -n "$CF_API_KEY" ] || CF_API_KEY="dry-run-dummy"
  fi
  if [ -z "$DNS_AUTO_CREATE" ]; then
    DNS_AUTO_CREATE=false
  fi
  if [ -z "$DNS_PROVIDER" ]; then
    DNS_PROVIDER=cloudflare
  fi
  # Variable interne conservée pour les apps/templates existants : elle suit toujours DOMAIN.
  if [ -n "$DOMAIN" ]; then
    DEFAULT_DOMAIN="$DOMAIN"
  else
    DEFAULT_DOMAIN=""
  fi
  DEFAULT_DOMAIN="${DEFAULT_DOMAIN//[[:space:]]/}"
  if [ -z "$DOMAINS" ] && [ -n "$DOMAIN" ]; then
    DOMAINS="$DOMAIN"
  fi
  DOMAINS="$(normalize_domains_value "${DOMAINS}")"
  if [ -n "$DOMAIN" ] && ! domain_list_contains "$DOMAINS" "$DOMAIN"; then
    DOMAINS="${DOMAIN}${DOMAINS:+,${DOMAINS}}"
  fi
  if [ -z "$DNS_RECORD_TTL" ]; then
    DNS_RECORD_TTL=1
  fi
  if [ -z "$DNS_RECORD_PROXIED" ]; then
    DNS_RECORD_PROXIED=true
  fi
  if [ "$CROWDSEC_APPSEC_ENABLED" = true ]; then
    WITH_CROWDSEC=true
    WITH_TRAEFIK=true
  fi
  if [ "$WITH_CROWDSEC" = true ] && [ -z "$TRAEFIK_TRUSTED_IPS" ] && [ "$TRAEFIK_TRUSTED_IPS_SET" = false ]; then
    TRAEFIK_TRUSTED_IPS=cloudflare
  fi
  TRAEFIK_TRUSTED_IPS="$(resolve_trusted_ips_value "${TRAEFIK_TRUSTED_IPS}")"
  TRAEFIK_TRUSTED_IPS_YAML="$(format_yaml_inline_list "${TRAEFIK_TRUSTED_IPS}")"
  if [ "$AUTO_YES" = true ] && [ "$DNS_AUTO_CREATE" = true ] && [ -z "$SERVER_PUBLIC_IP" ]; then
    SERVER_PUBLIC_IP="$(detect_server_public_ip)"
  fi
  if [ -n "$DOMAIN" ]; then
    if [ -z "$TRAEFIK_HOST" ] && [ "$WITH_TRAEFIK" = true ]; then
      TRAEFIK_HOST="traefik.${DOMAIN}"
    fi
    if [ -z "$OAUTH2_HOST" ] && [ "$OAUTH2_ENABLED" = true ]; then
      OAUTH2_HOST="oauth2.${DOMAIN}"
    fi
  fi
  configure_oauth2_authorization
}

prompt_deploy_questions() {
  local detected_ip=""
  local default_domains=""
  local default_traefik_host=""
  local default_oauth2_host=""

  echo ""
  echo "Entrée conserve la valeur proposée. Saisir '-' vide une valeur."

  section_title "1. Mode d'exécution"
  ask_bool DRY_RUN "Exécuter en dry-run"

  section_title "2. Chemins et base système"
  ask_text BASE_DIR "Runtime utilisateur"
  ask_text NETWORK_NAME "Réseau Docker"

  section_title "3. Domaine et DNS"
  ask_text DOMAIN "Domaine principal (ex: example.com)"
  default_domains="${DOMAINS:-${DOMAIN}}"
  ask_text DOMAINS "Domaines autorisés pour les apps, séparés par virgules" "${default_domains}"
  ask_bool DNS_AUTO_CREATE "Créer automatiquement les DNS applicatifs Cloudflare"
  if [ "${DNS_AUTO_CREATE:-false}" = true ] && [ -z "$SERVER_PUBLIC_IP" ]; then
    detected_ip="$(detect_server_public_ip)"
  fi
  ask_text SERVER_PUBLIC_IP "IP publique serveur" "${detected_ip}"
  ask_text CF_API_EMAIL "Email Cloudflare"
  ask_secret CF_API_KEY "Clé API globale Cloudflare"

  section_title "4. Traefik"
  ask_bool WITH_TRAEFIK "Activer Traefik"
  if [ "$WITH_TRAEFIK" = true ]; then
    [ -n "$DOMAIN" ] && default_traefik_host="traefik.${DOMAIN}"
    ask_text TRAEFIK_HOST "Hostname Traefik" "${default_traefik_host}"
    ask_text ACME_EMAIL "Email Let's Encrypt"
    ask_bool WITH_CROWDSEC "Activer CrowdSec pour Traefik"
    if [ "$WITH_CROWDSEC" = true ]; then
      WITH_TRAEFIK=true
      ask_bool CROWDSEC_APPSEC_ENABLED "Activer AppSec / WAF"
      if [ -z "$TRAEFIK_TRUSTED_IPS" ] && [ "$TRAEFIK_TRUSTED_IPS_SET" = false ]; then
        echo "Trusted IPs Traefik : Cloudflare officiel sera appliqué automatiquement."
      else
        echo "Trusted IPs Traefik : $(display_value "${TRAEFIK_TRUSTED_IPS}" "aucune")"
      fi
    else
      ask_text TRAEFIK_TRUSTED_IPS "CIDR proxies de confiance Traefik (vide, cloudflare, ou liste CIDR)"
    fi
  fi

  section_title "5. OAuth2 GitHub"
  ask_bool OAUTH2_ENABLED "Activer OAuth2 Proxy"
  if [ "$OAUTH2_ENABLED" = true ]; then
    [ -n "$DOMAIN" ] && default_oauth2_host="oauth2.${DOMAIN}"
    ask_text OAUTH2_HOST "Hostname OAuth2" "${default_oauth2_host}"
    ask_text OAUTH2_CLIENT_ID "GitHub OAuth Client ID"
    ask_secret OAUTH2_CLIENT_SECRET "GitHub OAuth Client Secret"
    ask_text OAUTH2_ALLOWED_EMAILS "Emails GitHub autorisés, séparés par virgule"
  fi

  section_title "6. CrowdSec"
  echo "CrowdSec est configuré dans la section Traefik."
}

show_deploy_plan() {
  echo ""
  echo "============================================================"
  echo " Résumé avant exécution"
  echo "============================================================"
  echo "Mode                 : $([ "$DRY_RUN" = true ] && echo "simulation (dry-run)" || echo "installation réelle")"
  echo "Runtime              : $(display_path "${BASE_DIR}")"
  echo "Config               : $(display_path "${BASE_DIR}/config/ksf.env")"
  echo "Réseau Docker        : ${NETWORK_NAME}"
  echo "Domaine principal    : $(display_value "${DOMAIN}")"
  echo "Domaines autorisés   : $(display_value "${DOMAINS}")"
  echo "DNS automatique      : $(display_bool "${DNS_AUTO_CREATE}")"
  echo "IP publique DNS      : $(display_value "${SERVER_PUBLIC_IP}")"
  echo "Cloudflare email     : $(display_value "${CF_API_EMAIL}")"
  echo "Cloudflare API key   : $(display_secret "${CF_API_KEY}")"
  echo "Traefik              : $(display_bool "${WITH_TRAEFIK}")"
  echo "Host Traefik         : $(display_value "${TRAEFIK_HOST}")"
  echo "Trusted IPs Traefik  : $(display_value "${TRAEFIK_TRUSTED_IPS}" "aucune")"
  echo "Let's Encrypt email  : $(display_value "${ACME_EMAIL}")"
  echo "CrowdSec             : $(display_bool "${WITH_CROWDSEC}")"
  if [ "${WITH_CROWDSEC}" = true ]; then
    echo "CrowdSec bouncer key : $(display_secret_auto "${CROWDSEC_BOUNCER_KEY}")"
    echo "AppSec / WAF         : $(display_bool "${CROWDSEC_APPSEC_ENABLED}")"
    echo "AppSec host          : ${CROWDSEC_APPSEC_HOST}"
    echo "AppSec failure block : ${CROWDSEC_APPSEC_FAILURE_BLOCK}"
    echo "AppSec unreach block : ${CROWDSEC_APPSEC_UNREACHABLE_BLOCK}"
    echo "AppSec collections   : ${CROWDSEC_APPSEC_COLLECTIONS}"
  else
    echo "CrowdSec bouncer key : $(display_secret "${CROWDSEC_BOUNCER_KEY}")"
    echo "AppSec / WAF         : inactif"
  fi
  echo "OAuth2 Proxy         : $(display_bool "${OAUTH2_ENABLED}")"
  echo "Host OAuth2 Proxy    : $(display_value "${OAUTH2_HOST}")"
  echo "Web UI               : $(display_bool "${WITH_WEBUI}")"
  echo "OAuth2 client ID     : $(display_presence "${OAUTH2_CLIENT_ID}")"
  echo "OAuth2 secret        : $(display_secret "${OAUTH2_CLIENT_SECRET}")"
  if [ "$OAUTH2_AUTH_MODE" = "email" ]; then
    echo "OAuth2 emails        : ${OAUTH2_ALLOWED_EMAILS}"
  elif [ "$OAUTH2_AUTH_MODE" = "github-user" ]; then
    echo "OAuth2 GitHub user   : ${OAUTH2_GITHUB_USER}"
  elif [ "$OAUTH2_AUTH_MODE" = "conflict" ]; then
    echo "OAuth2 autorisation  : conflit email/utilisateur"
  fi
  echo ""
  echo "Actions prévues :"
  if [ "$DRY_RUN" = true ]; then
    echo "  [DRY-RUN] Simuler la configuration et les stacks sans écrire dans le runtime"
    [ "$WITH_TRAEFIK" = true ] && echo "  [DRY-RUN] Simuler le démarrage de Traefik"
    [ "$WITH_CROWDSEC" = true ] && echo "  [DRY-RUN] Simuler le démarrage de CrowdSec"
    [ "$OAUTH2_ENABLED" = true ] && echo "  [DRY-RUN] Simuler le démarrage de OAuth2 Proxy"
  else
    echo "  Générer la configuration et les stacks"
    [ "$WITH_TRAEFIK" = true ] && echo "  Démarrer Traefik automatiquement"
    [ "$WITH_CROWDSEC" = true ] && echo "  Démarrer CrowdSec automatiquement"
    [ "$OAUTH2_ENABLED" = true ] && echo "  Démarrer OAuth2 Proxy automatiquement après Traefik"
  fi
  return 0
}

prompt_final_choice() {
  local choice

  while true; do
    echo ""
    echo "Que voulez-vous faire ?"
    if [ "$DRY_RUN" = true ]; then
      echo "  1) Lancer la simulation"
    else
      echo "  1) Lancer l'installation"
    fi
    echo "  2) Modifier la configuration"
    echo "  3) Annuler"
    echo -n "Choix [3] : "
    read -r choice
    case "${choice:-3}" in
      1) return 0 ;;
      2) return 2 ;;
      3) warn "Installation annulée avant écriture des fichiers."; exit 0 ;;
      *) warn "Choix invalide." ;;
    esac
  done
}

prompt_invalid_config_choice() {
  local choice

  while true; do
    echo ""
    echo "La configuration est invalide. Que voulez-vous faire ?"
    echo "  1) Modifier la configuration"
    echo "  2) Annuler"
    echo -n "Choix [1] : "
    read -r choice
    case "${choice:-1}" in
      1) return 0 ;;
      2) warn "Installation annulée avant écriture des fichiers."; exit 0 ;;
      *) warn "Choix invalide." ;;
    esac
  done
}

run_interactive_flow() {
  prompt_deploy_questions
  while true; do
    prepare_deploy_config
    show_deploy_plan
    if prompt_final_choice; then
      if validate_deploy_config 2>&1; then
        break
      fi
      prompt_invalid_config_choice
    fi
    prompt_deploy_questions
  done
}

generate_oauth2_cookie_secret() {
  if [ "$OAUTH2_ENABLED" = true ] && [ -z "$OAUTH2_COOKIE_SECRET" ]; then
    if ! command -v openssl >/dev/null 2>&1; then
      err "openssl est requis pour générer --oauth-cookie-secret."
      exit 1
    fi
    OAUTH2_COOKIE_SECRET=$(openssl rand -hex 16)
  fi
}

generate_crowdsec_bouncer_key() {
  if [ "$WITH_CROWDSEC" = true ] && [ -z "$CROWDSEC_BOUNCER_KEY" ]; then
    if ! command -v openssl >/dev/null 2>&1; then
      err "openssl est requis pour générer --crowdsec-bouncer-key."
      exit 1
    fi
    CROWDSEC_BOUNCER_KEY=$(openssl rand -hex 32)
  fi
}

validate_deploy_config() {
  if [ -z "$DOMAIN" ]; then
    err "Le domaine principal est requis."
    return 1
  fi
  if [ -z "$DOMAINS" ]; then
    err "La liste des domaines autorisés ne peut pas être vide."
    return 1
  fi

  if [ "$WITH_TRAEFIK" = false ] && [ "$OAUTH2_ENABLED" = false ] && [ "$WITH_CROWDSEC" = false ]; then
    err "Aucune stack sélectionnée. Utilise --with-traefik, --with-crowdsec ou les options OAuth2."
    return 1
  fi

  if [ "$WITH_CROWDSEC" = true ] && [ "$WITH_TRAEFIK" = false ]; then
    err "CrowdSec nécessite --with-traefik pour générer le middleware Traefik."
    return 1
  fi

  if [ "$CROWDSEC_APPSEC_ENABLED" = true ] && { [ "$WITH_CROWDSEC" != true ] || [ "$WITH_TRAEFIK" != true ]; }; then
    err "AppSec / WAF nécessite CrowdSec et Traefik."
    return 1
  fi

  if [ "$WITH_TRAEFIK" = true ]; then
    if [ -z "$ACME_EMAIL" ]; then
      err "--acme-email est requis avec --with-traefik."
      return 1
    fi
    if [ -z "$TRAEFIK_HOST" ]; then
      err "--domain ou --traefik-host est requis avec --with-traefik."
      return 1
    fi
    if [ -z "$CF_API_EMAIL" ] || [ -z "$CF_API_KEY" ]; then
      err "--cf-api-email et --cf-api-key sont requis avec --with-traefik pour le DNS challenge Cloudflare."
      return 1
    fi
    if [ "$WITH_CROWDSEC" = true ] && [ -z "$TRAEFIK_TRUSTED_IPS" ]; then
      err "CrowdSec nécessite des trusted IPs Traefik sûres. Utilise --traefik-trusted-ips cloudflare ou une liste CIDR explicite."
      return 1
    fi
  fi

  if [ "$OAUTH2_ENABLED" = true ]; then
    if [ "$WITH_TRAEFIK" = false ]; then
      err "OAuth2 Proxy nécessite --with-traefik pour générer le middleware Traefik."
      return 1
    fi
    if [ -z "$OAUTH2_CLIENT_ID" ] || [ -z "$OAUTH2_CLIENT_SECRET" ]; then
      err "OAuth2 nécessite --oauth-client-id et --oauth-client-secret."
      return 1
    fi
    if [ "$OAUTH2_AUTH_MODE" = "conflict" ]; then
      err "OAuth2 accepte un seul mode d'autorisation : --oauth-allowed-email ou --oauth-github-user."
      return 1
    fi
    if [ -z "$OAUTH2_AUTH_MODE" ]; then
      err "OAuth2 nécessite --oauth-allowed-email (recommandé) ou --oauth-github-user (mode avancé)."
      return 1
    fi
    if [ "$OAUTH2_AUTH_MODE" = "email" ]; then
      local local_email_list
      local local_email

      local_email_list="${OAUTH2_ALLOWED_EMAILS},"
      while [ -n "$local_email_list" ]; do
        local_email="${local_email_list%%,*}"
        local_email_list="${local_email_list#*,}"
        if [[ "$local_email" != *@* ]]; then
          err "Adresse email OAuth2 invalide : ${local_email}"
          return 1
        fi
      done
    fi
    if [ -z "$OAUTH2_HOST" ]; then
      err "--domain ou --oauth-host est requis avec OAuth2 Proxy."
      return 1
    fi
    if [ -z "$DOMAIN" ]; then
      err "--domain est requis avec OAuth2 Proxy pour définir le domaine du cookie."
      return 1
    fi
  fi

  return 0
}

validate_execution_allowed
load_existing_deploy_config
if [ "$CONFIG_LOADED" = true ]; then
  echo "Configuration existante chargée comme valeurs par défaut"
fi

# ---------- Vérification environnement ----------
if [ -n "${DOCKER_API_VERSION:-}" ]; then
  echo ""
  echo -e "\033[1;33m[WARN]\033[0m DOCKER_API_VERSION=${DOCKER_API_VERSION} peut causer des erreurs avec Traefik."
  echo -e "\033[1;33m[WARN]\033[0m La variable est ignorée pendant ce déploiement. Exécute aussi : unset DOCKER_API_VERSION"
  echo ""
  unset DOCKER_API_VERSION
fi

if [ "$AUTO_YES" = false ]; then
  run_interactive_flow
else
  prepare_deploy_config
  show_deploy_plan
fi

validate_deploy_config
generate_oauth2_cookie_secret
generate_crowdsec_bouncer_key

# ---------- Journalisation ----------
if [ "$DRY_RUN" = true ]; then
  LOG_DIR="/tmp/ksf"
  mkdir -p "${LOG_DIR}"
  LOG_FILE="${LOG_DIR}/ksf-deploy-$(date +%Y%m%d-%H%M%S).log"
else
  mkdir -p "${BASE_DIR}/logs" "${BASE_DIR}/config/installed-apps"
  LOG_FILE="${BASE_DIR}/logs/deploy-$(date +%Y%m%d-%H%M%S).log"
fi
exec > >(tee -a "$LOG_FILE") 2>&1

source "${SCRIPT_DIR}/lib/render.sh"
source "${SCRIPT_DIR}/lib/deploy_steps.sh"

# ---------- Sauvegarde de la config ----------
KSF_ENV="${BASE_DIR}/config/ksf.env"
if [ "$DRY_RUN" = false ]; then
  : > "${KSF_ENV}"
  ksf_env_write_var "${KSF_ENV}" BASE_DIR "${BASE_DIR}"
  ksf_env_write_var "${KSF_ENV}" NETWORK_NAME "${NETWORK_NAME}"
  ksf_env_write_var "${KSF_ENV}" TZ_VALUE "${TZ_VALUE}"
  ksf_env_write_var "${KSF_ENV}" DOMAIN "${DOMAIN}"
  ksf_env_write_var "${KSF_ENV}" DEFAULT_DOMAIN "${DEFAULT_DOMAIN}"
  ksf_env_write_var "${KSF_ENV}" DOMAINS "${DOMAINS}"
  ksf_env_write_var "${KSF_ENV}" CF_API_EMAIL "${CF_API_EMAIL}"
  ksf_env_write_var "${KSF_ENV}" CF_API_KEY "${CF_API_KEY}"
  ksf_env_write_var "${KSF_ENV}" SERVER_PUBLIC_IP "${SERVER_PUBLIC_IP}"
  ksf_env_write_var "${KSF_ENV}" DNS_AUTO_CREATE "${DNS_AUTO_CREATE}"
  ksf_env_write_var "${KSF_ENV}" DNS_PROVIDER "${DNS_PROVIDER}"
  ksf_env_write_var "${KSF_ENV}" DNS_RECORD_TTL "${DNS_RECORD_TTL}"
  ksf_env_write_var "${KSF_ENV}" DNS_RECORD_PROXIED "${DNS_RECORD_PROXIED}"
  ksf_env_write_var "${KSF_ENV}" WITH_TRAEFIK "${WITH_TRAEFIK}"
  ksf_env_write_var "${KSF_ENV}" TRAEFIK_TRUSTED_IPS "${TRAEFIK_TRUSTED_IPS}"
  ksf_env_write_var "${KSF_ENV}" WITH_CROWDSEC "${WITH_CROWDSEC}"
  ksf_env_write_var "${KSF_ENV}" CROWDSEC_BOUNCER_KEY "${CROWDSEC_BOUNCER_KEY}"
  ksf_env_write_var "${KSF_ENV}" CROWDSEC_APPSEC_ENABLED "${CROWDSEC_APPSEC_ENABLED}"
  ksf_env_write_var "${KSF_ENV}" CROWDSEC_APPSEC_LISTEN_ADDR "${CROWDSEC_APPSEC_LISTEN_ADDR}"
  ksf_env_write_var "${KSF_ENV}" CROWDSEC_APPSEC_HOST "${CROWDSEC_APPSEC_HOST}"
  ksf_env_write_var "${KSF_ENV}" CROWDSEC_APPSEC_FAILURE_BLOCK "${CROWDSEC_APPSEC_FAILURE_BLOCK}"
  ksf_env_write_var "${KSF_ENV}" CROWDSEC_APPSEC_UNREACHABLE_BLOCK "${CROWDSEC_APPSEC_UNREACHABLE_BLOCK}"
  ksf_env_write_var "${KSF_ENV}" CROWDSEC_APPSEC_COLLECTIONS "${CROWDSEC_APPSEC_COLLECTIONS}"
  ksf_env_write_var "${KSF_ENV}" OAUTH2_ENABLED "${OAUTH2_ENABLED}"
  ksf_env_write_var "${KSF_ENV}" ACME_EMAIL "${ACME_EMAIL}"
  ksf_env_write_var "${KSF_ENV}" TRAEFIK_HOST "${TRAEFIK_HOST}"
  ksf_env_write_var "${KSF_ENV}" OAUTH2_HOST "${OAUTH2_HOST}"
  ksf_env_write_var "${KSF_ENV}" OAUTH2_CLIENT_ID "${OAUTH2_CLIENT_ID}"
  ksf_env_write_var "${KSF_ENV}" OAUTH2_CLIENT_SECRET "${OAUTH2_CLIENT_SECRET}"
  ksf_env_write_var "${KSF_ENV}" OAUTH2_ALLOWED_EMAILS "${OAUTH2_ALLOWED_EMAILS}"
  ksf_env_write_var "${KSF_ENV}" OAUTH2_GITHUB_USER "${OAUTH2_GITHUB_USER}"
  ksf_env_write_var "${KSF_ENV}" OAUTH2_AUTH_MODE "${OAUTH2_AUTH_MODE}"
  ksf_env_write_var "${KSF_ENV}" OAUTH2_SCOPE "${OAUTH2_SCOPE}"
  ksf_env_write_var "${KSF_ENV}" OAUTH2_EMAIL_DOMAINS "${OAUTH2_EMAIL_DOMAINS}"
  ksf_env_write_var "${KSF_ENV}" OAUTH2_AUTHENTICATED_EMAILS_FILE "${OAUTH2_AUTHENTICATED_EMAILS_FILE}"
  ksf_env_write_var "${KSF_ENV}" OAUTH2_COOKIE_SECRET "${OAUTH2_COOKIE_SECRET}"
  ksf_env_write_var "${KSF_ENV}" WITH_WEBUI "${WITH_WEBUI}"
  chmod 600 "${KSF_ENV}"
  ok "Configuration sauvegardée dans ${KSF_ENV}"
else
  warn "[DRY-RUN] Sauvegarde de ${KSF_ENV}"
fi

# ---------- Exécution ----------
info "=== KSF Déploiement ==="
info "Base : ${BASE_DIR} | Réseau : ${NETWORK_NAME}"
if [ "$WITH_TRAEFIK" = true ]; then
  info "Traefik : ${TRAEFIK_HOST} (${ACME_EMAIL})"
fi
if [ "$OAUTH2_ENABLED" = true ]; then
  info "OAuth2 Proxy: ${OAUTH2_HOST}"
  if [ "$OAUTH2_AUTH_MODE" = "email" ]; then
    info "OAuth2 autorisation : emails GitHub (${OAUTH2_ALLOWED_EMAILS})"
  fi
  if [ "$OAUTH2_AUTH_MODE" = "github-user" ]; then
    warn "OAuth2 autorisation : username GitHub avancé avec OAUTH2_PROXY_GITHUB_USERS. Le mode email recommandé limite l'accès applicatif via allowed-emails.txt."
  fi
fi
if [ "$WITH_CROWDSEC" = true ]; then
  info "CrowdSec: activé pour Traefik"
  if [ "$CROWDSEC_APPSEC_ENABLED" = true ]; then
    info "AppSec / WAF: activé (${CROWDSEC_APPSEC_HOST})"
  fi
fi

step_dirs
step_env
step_network
step_traefik
step_crowdsec
step_oauth2
step_start_infrastructure

# Installation du Web UI si demandée
if [ "$WITH_WEBUI" = true ]; then
  if [ "$DRY_RUN" = true ]; then
    warn "[DRY-RUN] Installation du Web UI : ./app.sh install webui --base-dir ${BASE_DIR} --subdomain webui --auth -y"
  else
    info "Installation du Web UI..."
    AUTO_YES=true \
    bash "${SCRIPT_DIR}/app.sh" install webui \
      --base-dir "${BASE_DIR}" \
      --subdomain webui \
      --auth \
      -y || warn "Échec de l'installation du Web UI."
  fi
fi

echo ""
echo "============================================================"
if [ "$DRY_RUN" = true ]; then
  echo " Simulation terminée : aucune modification appliquée."
else
  echo " Déploiement terminé"
fi
echo "============================================================"
echo ""
echo "Runtime          : $(display_path "${BASE_DIR}")"
echo "Config           : $(display_path "${KSF_ENV}")"
echo "Log              : ${LOG_FILE}"
echo "Réseau Docker    : ${NETWORK_NAME}"
echo "Domaine principal: $(display_value "${DOMAIN}")"
echo "Domaines autor.  : $(display_value "${DOMAINS}")"
echo "DNS automatique  : $(display_bool "${DNS_AUTO_CREATE}")"
echo "IP publique DNS  : $(display_value "${SERVER_PUBLIC_IP}")"
echo ""
echo "Traefik          : $(display_bool "${WITH_TRAEFIK}")"
echo "Host Traefik     : $(display_value "${TRAEFIK_HOST}")"
echo "Trusted IPs      : $(display_value "${TRAEFIK_TRUSTED_IPS}" "aucune")"
echo "CrowdSec         : $(display_bool "${WITH_CROWDSEC}")"
if [ "${WITH_CROWDSEC}" = true ]; then
  echo "AppSec / WAF    : $(display_bool "${CROWDSEC_APPSEC_ENABLED}")"
  echo "AppSec host      : ${CROWDSEC_APPSEC_HOST}"
  echo "AppSec failure block : ${CROWDSEC_APPSEC_FAILURE_BLOCK}"
  echo "AppSec unreachable block : ${CROWDSEC_APPSEC_UNREACHABLE_BLOCK}"
  echo "AppSec collections : ${CROWDSEC_APPSEC_COLLECTIONS}"
else
  echo "AppSec / WAF    : inactif"
fi
echo "OAuth2 Proxy     : $(display_bool "${OAUTH2_ENABLED}")"
echo "Host OAuth2 Proxy: $(display_value "${OAUTH2_HOST}")"
if [ "$OAUTH2_AUTH_MODE" = "email" ]; then
  echo "OAuth2 emails    : ${OAUTH2_ALLOWED_EMAILS}"
fi
echo ""
echo "Containers démarrés :"
echo "  Traefik      : ${TRAEFIK_START_STATUS}"
echo "  CrowdSec     : ${CROWDSEC_START_STATUS}"
echo "  OAuth2 Proxy : ${OAUTH2_START_STATUS}"
echo ""
if [ "$DRY_RUN" = true ]; then
  echo "Pour appliquer réellement : ./deploy.sh --force"
else
  echo "Prochaines commandes utiles :"
  if [ "$OAUTH2_ENABLED" = true ]; then
    echo "  Configurer l'URL callback GitHub : https://${OAUTH2_HOST}/oauth2/callback"
  fi
  echo "  Vérifier l'installation : ./ksf.sh doctor"
  echo "  Lister les apps : ./app.sh list"
  echo "  Installer une app : ./app.sh install <app>"
fi
echo ""
echo "Prérequis : les DNS des hostnames doivent pointer vers ce serveur."
echo "Pour Let's Encrypt DNS-01, la clé API Cloudflare doit pouvoir éditer la zone DNS du domaine."
echo ""
