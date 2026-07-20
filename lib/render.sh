# ============================================================
# KSF — Rendu de templates
# ============================================================

RENDER_VARS=(
  BASE_DIR
  NETWORK_NAME
  TZ_VALUE
  ACME_EMAIL
  DOMAIN
  DEFAULT_DOMAIN
  DOMAINS
  CF_API_EMAIL
  CF_API_KEY
  SERVER_PUBLIC_IP
  DNS_AUTO_CREATE
  DNS_PROVIDER
  DNS_RECORD_TTL
  DNS_RECORD_PROXIED
  WITH_CROWDSEC
  CROWDSEC_APPSEC_ENABLED
  CROWDSEC_APPSEC_LISTEN_ADDR
  CROWDSEC_APPSEC_HOST
  CROWDSEC_APPSEC_FAILURE_BLOCK
  CROWDSEC_APPSEC_UNREACHABLE_BLOCK
  CROWDSEC_APPSEC_COLLECTIONS
  CROWDSEC_COLLECTIONS
  TRAEFIK_HOST
  OAUTH2_HOST
  OAUTH2_CLIENT_ID
  OAUTH2_CLIENT_SECRET
  OAUTH2_ALLOWED_EMAILS
  OAUTH2_COOKIE_SECRET
  OAUTH2_GITHUB_USER
  OAUTH2_AUTH_MODE
  OAUTH2_SCOPE
  OAUTH2_EMAIL_DOMAINS
  OAUTH2_AUTHENTICATED_EMAILS_FILE
  CROWDSEC_BOUNCER_KEY
  TRAEFIK_TRUSTED_IPS
  TRAEFIK_PUBLIC_MIDDLEWARES_BLOCK
  TRAEFIK_OAUTH2_CHAIN_MIDDLEWARES
  TRAEFIK_TRUSTED_IPS_YAML
  CROWDSEC_APPSEC_VOLUME_BLOCK
  CROWDSEC_APPSEC_PLUGIN_BLOCK
  APP_NAME
  APP_INSTANCE
  APP_HOST
  APP_PORT
  APP_HOST_PORT
  APP_PORTS_BLOCK
  APP_PROTECTED
  APP_PUBLIC
  APP_PUID
  APP_PGID
  KSF_REPO_DIR
  DOCKER_GID
  DOCKER_GROUP_ADD_BLOCK
)

RENDER_OPTIONAL_VARS=(
  SERVER_PUBLIC_IP
  DNS_AUTO_CREATE
  DNS_PROVIDER
  DNS_RECORD_TTL
  DNS_RECORD_PROXIED
  OAUTH2_EMAIL_DOMAINS
  OAUTH2_AUTHENTICATED_EMAILS_FILE
  OAUTH2_GITHUB_USER
  CROWDSEC_BOUNCER_KEY
  CROWDSEC_APPSEC_COLLECTIONS
  CROWDSEC_COLLECTIONS
  TRAEFIK_TRUSTED_IPS
  TRAEFIK_PUBLIC_MIDDLEWARES_BLOCK
  TRAEFIK_TRUSTED_IPS_YAML
  CROWDSEC_APPSEC_VOLUME_BLOCK
  CROWDSEC_APPSEC_PLUGIN_BLOCK
  DOCKER_GID
  DOCKER_GROUP_ADD_BLOCK
  APP_HOST_PORT
  APP_PORTS_BLOCK
)

render_unique_words() {
  local words="$*"
  local word item existing
  local rendered=""

  for word in $words; do
    existing=false
    for item in $rendered; do
      if [ "$item" = "$word" ]; then
        existing=true
        break
      fi
    done
    [ "$existing" = false ] && rendered="${rendered:+${rendered} }${word}"
  done

  printf '%s' "$rendered"
}

prepare_render_context() {
  : "${CROWDSEC_APPSEC_ENABLED:=false}"
  : "${CROWDSEC_APPSEC_LISTEN_ADDR:=0.0.0.0:7422}"
  : "${CROWDSEC_APPSEC_HOST:=crowdsec:7422}"
  : "${CROWDSEC_APPSEC_FAILURE_BLOCK:=true}"
  : "${CROWDSEC_APPSEC_UNREACHABLE_BLOCK:=true}"
  : "${CROWDSEC_APPSEC_COLLECTIONS:=crowdsecurity/appsec-virtual-patching crowdsecurity/appsec-generic-rules}"
  : "${DOCKER_GROUP_ADD_BLOCK:=}"

  if [ -n "${DOCKER_GID:-}" ] && [ -z "${DOCKER_GROUP_ADD_BLOCK}" ]; then
    DOCKER_GROUP_ADD_BLOCK="    group_add:
      - \"${DOCKER_GID}\""
  fi

  if [ "${WITH_CROWDSEC:-false}" = true ]; then
    TRAEFIK_PUBLIC_MIDDLEWARES_BLOCK="      middlewares:
        - security-chain"
    TRAEFIK_OAUTH2_CHAIN_MIDDLEWARES="[crowdsec, oauth2-errors, oauth2-auth]"
  else
    TRAEFIK_PUBLIC_MIDDLEWARES_BLOCK=""
    TRAEFIK_OAUTH2_CHAIN_MIDDLEWARES="[oauth2-errors, oauth2-auth]"
  fi
  : "${TRAEFIK_TRUSTED_IPS_YAML:=[]}"

  if [ "${CROWDSEC_APPSEC_ENABLED}" = true ]; then
    CROWDSEC_COLLECTIONS="$(render_unique_words crowdsecurity/traefik ${CROWDSEC_APPSEC_COLLECTIONS})"
    CROWDSEC_APPSEC_VOLUME_BLOCK='      - "./appsec.yaml:/etc/crowdsec/acquis.d/appsec.yaml:ro"
'
    CROWDSEC_APPSEC_PLUGIN_BLOCK="
          crowdsecAppsecEnabled: true
          crowdsecAppsecHost: \"${CROWDSEC_APPSEC_HOST}\"
          crowdsecAppsecFailureBlock: ${CROWDSEC_APPSEC_FAILURE_BLOCK}
          crowdsecAppsecUnreachableBlock: ${CROWDSEC_APPSEC_UNREACHABLE_BLOCK}"
  else
    CROWDSEC_COLLECTIONS="crowdsecurity/traefik"
    CROWDSEC_APPSEC_VOLUME_BLOCK=""
    CROWDSEC_APPSEC_PLUGIN_BLOCK=""
  fi
}

render_traefik_static_template() {
  local template_dir="$1"
  local destination="$2"

  if [ "${WITH_CROWDSEC:-false}" = true ]; then
    render_template "${template_dir}/traefik/traefik-crowdsec.yml" "$destination"
  else
    render_template "${template_dir}/traefik/traefik.yml" "$destination"
  fi
}

is_optional_render_var() {
  local candidate="$1"
  local optional_var

  for optional_var in "${RENDER_OPTIONAL_VARS[@]}"; do
    if [ "$candidate" = "$optional_var" ]; then
      return 0
    fi
  done

  return 1
}

render_template() {
  local template="$1"
  local destination="$2"
  local content var token value shell_token quote_env_values=false

  prepare_render_context
  render_normalize_app_vars "${APP_NAME:-}"

  if [ ! -f "$template" ]; then
    err "Template introuvable : ${template}"
    return 1
  fi

  content="$(<"$template")"
  case "$template" in
    */env/ksf.env)
      quote_env_values=true
      ;;
  esac
  for var in "${RENDER_VARS[@]}"; do
    token="__${var}__"
    shell_token="\${${var}}"
    value="${!var-}"
    if [ "$quote_env_values" = true ]; then
      value="$(ksf_env_quote_value "$value")"
    fi
    if [ -z "$value" ] && ! is_optional_render_var "$var" && { [[ "$content" == *"$token"* ]] || [[ "$content" == *"$shell_token"* ]]; }; then
      warn "Variable ${var} vide pendant le rendu de ${template}"
    fi
    content="${content//${token}/${value}}"
    content="${content//${shell_token}/${value}}"
  done

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Rendu ${template} -> ${destination}"
    return 0
  fi

  mkdir -p "$(dirname "$destination")"
  printf '%s\n' "$content" > "$destination"
  case "$destination" in
    */middleware-crowdsec.yml|*/proxy/crowdsec/docker-compose.yml|*/proxy/crowdsec/appsec.yaml)
      chmod 600 "$destination"
      ;;
  esac
}

render_traefik_route_template() {
  local template="$1"
  local destination="$2"

  render_template "$template" "$destination"
}

render_normalize_app_vars() {
  local fallback_name="${1:-}"
  local template_env=""

  : "${APP_NAME:=${fallback_name}}"
  : "${APP_INSTANCE:=${fallback_name:-${APP_NAME}}}"
  : "${APP_PUBLIC:=true}"
  : "${APP_DISABLED:=false}"

  if [ -n "${APP_NAME:-}" ]; then
    template_env="${SCRIPT_DIR}/templates/apps/${APP_NAME}/app.env"
  fi

  if [ -z "${APP_PORT:-}" ] && [ -n "${APP_INTERNAL_PORT:-}" ]; then
    APP_PORT="${APP_INTERNAL_PORT}"
  fi
  if [ -z "${APP_PORT:-}" ] && [ -f "$template_env" ]; then
    APP_PORT="$( ( APP_PORT=""; APP_INTERNAL_PORT=""; source "$template_env"; printf '%s' "${APP_PORT:-${APP_INTERNAL_PORT:-}}" ) 2>/dev/null )"
  fi
  : "${APP_HOST_PORT:=}"
  if [ -n "${APP_HOST_PORT}" ]; then
    APP_PORTS_BLOCK="ports:
      - \"127.0.0.1:${APP_HOST_PORT}:${APP_PORT}\""
  else
    APP_PORTS_BLOCK=""
  fi
  if [ -z "${APP_PROTECTED:-}" ]; then
    APP_PROTECTED="${APP_AUTH:-true}"
  fi
  : "${APP_DOCKER_SERVICE:=${APP_NAME}}"
  APP_AUTH="${APP_PROTECTED}"
}

render_app_route_from_env() {
  local destination="$1"
  local protected="${APP_PROTECTED:-${APP_AUTH:-true}}"
  local middlewares_block=""

  prepare_render_context
  render_normalize_app_vars "${APP_NAME:-}"

  # Pour le multi-instance, l'identité unique de la route (router + service
  # Traefik, nom du fichier de route) est APP_INSTANCE. Le nom de service
  # Docker en upstream reste le service name du compose (APP_NAME) puisque
  # c'est le réseau Docker qui fait la résolution.
  local route_id="${APP_INSTANCE:-${APP_NAME}}"
  local upstream_service="${APP_DOCKER_SERVICE:-${APP_NAME}}"

  if [ -z "${APP_NAME:-}" ]; then
    err "APP_NAME manquant pour la génération de route applicative."
    return 1
  fi
  if [ -z "${APP_HOST:-}" ]; then
    err "APP_HOST manquant pour la génération de route applicative : ${APP_NAME}"
    return 1
  fi
  if [ -z "${APP_PORT:-}" ]; then
    err "APP_PORT manquant pour la génération de route applicative : ${APP_NAME}"
    return 1
  fi

  case "$protected" in
    true)
      if [ "${OAUTH2_ENABLED:-false}" != true ]; then
        err "OAuth2 Proxy n'est pas configuré pour protéger ${APP_NAME}."
        return 1
      fi
      middlewares_block="      middlewares:
        - oauth2-chain"
      ;;
    false)
      middlewares_block="${TRAEFIK_PUBLIC_MIDDLEWARES_BLOCK}"
      ;;
    *)
      err "APP_PROTECTED doit valoir true ou false pour ${APP_NAME}."
      return 1
      ;;
  esac

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Rendu route applicative ${route_id} -> ${destination}"
    return 0
  fi

  mkdir -p "$(dirname "$destination")"
  {
    printf 'http:\n'
    printf '  routers:\n'
    printf '    %s:\n' "$route_id"
    printf '      rule: "Host(`%s`)"\n' "$APP_HOST"
    printf '      entryPoints:\n'
    printf '        - websecure\n'
    printf '      service: %s\n' "$route_id"
    if [ -n "$middlewares_block" ]; then
      printf '%s\n' "$middlewares_block"
    fi
    printf '      tls:\n'
    printf '        certResolver: letsencrypt\n'
    printf '  services:\n'
    printf '    %s:\n' "$route_id"
    printf '      loadBalancer:\n'
    printf '        servers:\n'
    printf '          - url: http://%s:%s\n' "$upstream_service" "$APP_PORT"
  } > "$destination"
}

render_oauth2_middleware_template() {
  local template="$1"
  local destination="$2"

  render_template "$template" "$destination"
}

render_oauth2_prune_empty_env_lines() {
  local compose_file="$1"
  local tmp_file="${compose_file}.tmp"
  local line

  : > "${tmp_file}"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '      - "OAUTH2_PROXY_EMAIL_DOMAINS="'|'      - "OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE="'|'      - "OAUTH2_PROXY_GITHUB_USERS="')
        continue
        ;;
    esac
    printf '%s\n' "$line" >> "${tmp_file}"
  done < "${compose_file}"
  mv "${tmp_file}" "${compose_file}"
}

render_oauth2_insert_allowed_emails_volume() {
  if [ "${OAUTH2_AUTH_MODE:-}" != "email" ]; then
    return 0
  fi

  local compose_file="$1"
  local tmp_file="${compose_file}.tmp"
  local line
  local inserted=false

  : > "${tmp_file}"
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s\n' "$line" >> "${tmp_file}"
    if [ "$inserted" = false ] && [ "$line" = '      - "./templates:/etc/oauth2-proxy/templates:ro"' ]; then
      printf '      - "./allowed-emails.txt:/auth/allowed-emails.txt:ro"\n' >> "${tmp_file}"
      inserted=true
    fi
  done < "${compose_file}"

  if [ "$inserted" = false ]; then
    : > "${tmp_file}"
    while IFS= read -r line || [ -n "$line" ]; do
      if [ "$inserted" = false ] && [ "$line" = "networks:" ]; then
        printf '    volumes:\n' >> "${tmp_file}"
        printf '      - "./templates:/etc/oauth2-proxy/templates:ro"\n' >> "${tmp_file}"
        printf '      - "./allowed-emails.txt:/auth/allowed-emails.txt:ro"\n' >> "${tmp_file}"
        printf '\n' >> "${tmp_file}"
        inserted=true
      fi
      printf '%s\n' "$line" >> "${tmp_file}"
    done < "${compose_file}"
  fi

  mv "${tmp_file}" "${compose_file}"
}

render_oauth2_custom_templates() {
  local source_template="${SCRIPT_DIR}/templates/oauth2-proxy/sign_in.html"
  local destination_dir="${OAUTH2_DIR}/templates"

  if [ ! -f "$source_template" ]; then
    err "Template OAuth2 Proxy introuvable : ${source_template}"
    exit 1
  fi

  run mkdir -p "$destination_dir"
  render_template "$source_template" "${destination_dir}/sign_in.html"
}

render_oauth2_compose_runtime() {
  local compose_file="$1"

  render_template "${TEMPLATE_DIR}/compose/oauth2-proxy.yml" "$compose_file"
  if [ "${DRY_RUN:-false}" = false ]; then
    render_oauth2_prune_empty_env_lines "$compose_file"
    render_oauth2_insert_allowed_emails_volume "$compose_file"
  fi
  render_oauth2_custom_templates
}
