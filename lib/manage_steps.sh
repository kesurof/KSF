# ============================================================
# KSF — Étapes de gestion infrastructure
# ============================================================

TEMPLATE_DIR="${SCRIPT_DIR}/templates"

_manage_format_yaml_inline_list() {
  local value="${1:-}"
  local item
  local rendered=""
  local -a items

  value="${value//[[:space:]]/}"
  value="${value//\"/}"
  value="${value//\'/}"
  IFS=',' read -r -a items <<< "$value"
  for item in "${items[@]}"; do
    [ -n "$item" ] && rendered="${rendered:+${rendered}, }\"${item}\""
  done
  if [ -n "$rendered" ]; then
    printf '[%s]' "$rendered"
  else
    printf '[]'
  fi
}

_manage_setup_paths() {
  INSTALLED_DIR="${BASE_DIR}/config/installed-apps"
  TRAEFIK_DYNAMIC_DIR="${BASE_DIR}/proxy/traefik/dynamic"
  TRAEFIK_DIR="${BASE_DIR}/proxy/traefik"
  OAUTH2_DIR="${BASE_DIR}/proxy/oauth2-proxy"
  CROWDSEC_DIR="${BASE_DIR}/proxy/crowdsec"
}

manage_reset_app_env() {
  unset APP_NAME
  unset APP_INSTANCE
  unset APP_HOST
  unset APP_DOMAIN
  unset APP_SUBDOMAIN
  unset APP_PORT
  unset APP_INTERNAL_PORT
  unset APP_DOCKER_SERVICE
  unset APP_PROTECTED
  unset APP_AUTH
  unset APP_PUBLIC
  unset APP_LOCAL_ONLY
  unset APP_DISABLED
  unset APP_DIR
  unset APP_DATA
  unset APP_PUID
  unset APP_PGID
  unset APP_INSTALLED_AT
  unset APP_MANAGED_NAME
  unset APP_MANAGED_DIR
  unset APP_MANAGED_DATA
}

# ---------- Vérification installation ----------

manage_require_installation() {
  _manage_setup_paths
  local env_file="${BASE_DIR}/config/ksf.env"
  if [ ! -f "$env_file" ]; then
    err "KSF n'est pas installé dans ${BASE_DIR}."
    err "Exécute d'abord : ./deploy.sh"
    exit 1
  fi
  if [ "${DRY_RUN:-false}" != true ]; then
    ksf_env_repair_sourceable_file "$env_file"
  fi
  source "$env_file"
  _manage_setup_paths
  : "${WITH_TRAEFIK:=false}"
  : "${OAUTH2_ENABLED:=false}"
  : "${WITH_CROWDSEC:=false}"
  : "${CROWDSEC_APPSEC_ENABLED:=false}"
  : "${CROWDSEC_APPSEC_LISTEN_ADDR:=0.0.0.0:7422}"
  : "${CROWDSEC_APPSEC_HOST:=crowdsec:7422}"
  : "${CROWDSEC_APPSEC_FAILURE_BLOCK:=true}"
  : "${CROWDSEC_APPSEC_UNREACHABLE_BLOCK:=true}"
  : "${CROWDSEC_APPSEC_COLLECTIONS:=crowdsecurity/appsec-virtual-patching crowdsecurity/appsec-generic-rules}"
  : "${TRAEFIK_TRUSTED_IPS:=}"
  TRAEFIK_TRUSTED_IPS_YAML="$(_manage_format_yaml_inline_list "${TRAEFIK_TRUSTED_IPS}")"
  : "${DNS_AUTO_CREATE:=false}"
  : "${NETWORK_NAME:=proxy}"
  : "${TZ_VALUE:=Europe/Paris}"
  : "${DEFAULT_DOMAIN:=${DOMAIN:-}}"
  DOMAINS="${DOMAINS//[[:space:]]/}"
  if [ -z "$DOMAINS" ]; then
    DOMAINS="${DOMAIN:-}"
  fi
}

# ---------- Status ----------

manage_status() {
  manage_require_installation

  echo "=== KSF Status ==="
  echo "Configuration  : ${BASE_DIR}/config/ksf.env"
  echo "Domaine principal: ${DOMAIN:-non configuré}"
  echo "Domaines autor.: ${DOMAINS:-aucun}"
  echo "DNS automatique: ${DNS_AUTO_CREATE:-false} (${DNS_PROVIDER:-cloudflare})"
  if [ -n "${SERVER_PUBLIC_IP:-}" ]; then
    echo "IP publique    : ${SERVER_PUBLIC_IP}"
  fi
  echo ""

  if [ "${WITH_TRAEFIK}" = true ]; then
    if [ -f "${TRAEFIK_DIR}/docker-compose.yml" ]; then
      ok "Traefik  : configuré, stack présente (${TRAEFIK_HOST:-?})"
    else
      warn "Traefik  : configuré mais stack absente"
    fi
  else
    info "Traefik  : non configuré"
  fi

  if [ "${OAUTH2_ENABLED}" = true ]; then
    if [ -f "${OAUTH2_DIR}/docker-compose.yml" ]; then
      ok "OAuth2 Proxy : configuré, stack présente (${OAUTH2_HOST:-?})"
    else
      warn "OAuth2 Proxy : configuré mais stack absente"
    fi
  else
    info "OAuth2 Proxy : non configuré"
  fi

  if [ "${WITH_CROWDSEC}" = true ]; then
    if [ -f "${CROWDSEC_DIR}/docker-compose.yml" ]; then
      ok "CrowdSec : configuré, stack présente"
      info "AppSec   : $( [ "${CROWDSEC_APPSEC_ENABLED}" = true ] && echo actif || echo inactif )"
    else
      warn "CrowdSec : configuré mais stack absente"
    fi
  else
    info "CrowdSec : non configuré"
  fi

  if [ -f "${INSTALLED_DIR}/dockge.env" ]; then
    ok "Dockge   : installé"
  else
    info "Dockge   : non installé"
  fi
  echo ""

  echo "Apps installées :"
  local found=false
  local state_info stack_state running_count total_count primary_service primary_name primary_state primary_health service_lines service_line service_name container_name service_state service_health
  for f in "${INSTALLED_DIR}"/*.env; do
    [ -f "$f" ] || continue
    found=true
    local installed_key app_label
    installed_key=$(basename "$f" .env)
    manage_reset_app_env
    source "$f"
    if [ -z "${APP_DOCKER_SERVICE:-}" ] && [ -f "${TEMPLATE_DIR}/apps/${APP_NAME}/app.env" ]; then
      APP_DOCKER_SERVICE="$({ APP_DOCKER_SERVICE=""; source "${TEMPLATE_DIR}/apps/${APP_NAME}/app.env" >/dev/null 2>&1; printf '%s' "${APP_DOCKER_SERVICE:-}"; })"
    fi
    local auth_label="public"
    [ "${APP_AUTH:-false}" = true ] && auth_label="protégé"
    state_info="$(ksf_stack_state_info "${APP_DIR:-${BASE_DIR}/apps/${APP_NAME}}" "${APP_DOCKER_SERVICE:-}")"
    IFS='|' read -r stack_state running_count total_count primary_service primary_name primary_state primary_health <<< "$state_info"
    app_label="${APP_INSTANCE:-$installed_key}"
    if [ "${APP_LOCAL_ONLY:-false}" = true ]; then
      info "  ${app_label}  (local, ${auth_label}, état: $(ksf_stack_state_label "$stack_state"))"
    elif [ -n "${APP_HOST:-}" ]; then
      info "  ${app_label}  (${APP_HOST}, ${auth_label}, état: $(ksf_stack_state_label "$stack_state"))"
    else
      info "  ${app_label}  (${auth_label}, état: $(ksf_stack_state_label "$stack_state"))"
    fi
    service_lines="$(ksf_stack_service_lines "${APP_DIR:-${BASE_DIR}/apps/${APP_NAME}}")"
    if [ -n "$service_lines" ]; then
      while IFS= read -r service_line || [ -n "$service_line" ]; do
        [ -n "$service_line" ] || continue
        IFS='|' read -r service_name container_name service_state service_health <<< "$service_line"
        if [ -n "$service_health" ]; then
          info "    ${service_name}: ${service_state} (${service_health})"
        else
          info "    ${service_name}: ${service_state}"
        fi
      done <<< "$service_lines"
    fi
  done
  if [ "$found" = false ]; then
    warn "  Aucune app installée."
  fi
  echo ""

  if command -v docker >/dev/null 2>&1; then
    echo "Containers :"
    local names=""
    names="$names${TRAEFIK_HOST:+ traefik}"
    names="$names${OAUTH2_HOST:+ oauth2-proxy}"
    [ "${WITH_CROWDSEC}" = true ] && names="$names crowdsec"
    for name in $names; do
      local status_line
      status_line=$(docker ps --filter "name=${name}$" --format "{{.Names}}\t{{.Status}}" 2>/dev/null || true)
      if [ -n "$status_line" ]; then
        ok "  ${status_line}"
      else
        warn "  ${name} : arrêté ou absent"
      fi
    done
    echo ""
    echo "Stacks apps :"
    found=false
    for f in "${INSTALLED_DIR}"/*.env; do
      [ -f "$f" ] || continue
      found=true
      local installed_key app_label
      installed_key=$(basename "$f" .env)
      manage_reset_app_env
      source "$f"
      if [ -z "${APP_DOCKER_SERVICE:-}" ] && [ -f "${TEMPLATE_DIR}/apps/${APP_NAME}/app.env" ]; then
        APP_DOCKER_SERVICE="$({ APP_DOCKER_SERVICE=""; source "${TEMPLATE_DIR}/apps/${APP_NAME}/app.env" >/dev/null 2>&1; printf '%s' "${APP_DOCKER_SERVICE:-}"; })"
      fi
      app_label="${APP_INSTANCE:-$installed_key}"
      state_info="$(ksf_stack_state_info "${APP_DIR:-${BASE_DIR}/apps/${APP_NAME}}" "${APP_DOCKER_SERVICE:-}")"
      IFS='|' read -r stack_state running_count total_count primary_service primary_name primary_state primary_health <<< "$state_info"
      if [ -n "$primary_name" ]; then
        info "  ${app_label} : $(ksf_stack_state_label "$stack_state") (${running_count}/${total_count}, ${primary_name}${primary_health:+, ${primary_health}})"
      else
        info "  ${app_label} : $(ksf_stack_state_label "$stack_state") (${running_count}/${total_count})"
      fi
      service_lines="$(ksf_stack_service_lines "${APP_DIR:-${BASE_DIR}/apps/${APP_NAME}}")"
      if [ -n "$service_lines" ]; then
        while IFS= read -r service_line || [ -n "$service_line" ]; do
          [ -n "$service_line" ] || continue
          IFS='|' read -r service_name container_name service_state service_health <<< "$service_line"
          if [ -n "$service_health" ]; then
            info "    ${service_name}: ${service_state} (${service_health})"
          else
            info "    ${service_name}: ${service_state}"
          fi
        done <<< "$service_lines"
      fi
    done
    if [ "$found" = false ]; then
      warn "  Aucune app installée."
    fi
  else
    warn "Docker inaccessible, skip status containers."
  fi
}

_manage_disabled_app_matches_stack() {
  local stack_name="$1"
  local app_dir="$2"
  local disabled_dir="${INSTALLED_DIR}/disabled"
  local env_file line disabled_instance disabled_stack_dir

  [ -d "$disabled_dir" ] || return 1

  for env_file in "${disabled_dir}"/*.env.disabled; do
    [ -f "$env_file" ] || continue
    line=$(
      APP_INSTANCE=""
      APP_DIR=""
      source "$env_file" >/dev/null 2>&1
      printf '%s|%s\n' "${APP_INSTANCE:-}" "${APP_DIR:-}"
    )
    IFS='|' read -r disabled_instance disabled_stack_dir <<< "$line"
    if [ "$disabled_instance" = "$stack_name" ] || [ "$disabled_stack_dir" = "$app_dir" ]; then
      return 0
    fi
  done

  return 1
}

# ---------- Config ----------

_manage_mask_value() {
  local key="$1"
  local value="$2"
  case "$key" in
    *SECRET*|*KEY*|*TOKEN*|*PASSWORD*)
      echo "******" ;;
    OAUTH2_CLIENT_SECRET|OAUTH2_COOKIE_SECRET|CF_API_KEY)
      echo "******" ;;
    *)
      echo "$value" ;;
  esac
}

manage_config() {
  manage_require_installation
  local env_file="${BASE_DIR}/config/ksf.env"
  echo "Configuration : ${env_file}"
  echo ""
  local key value
  while IFS='=' read -r key value || [ -n "${key}" ]; do
    case "$key" in
      ''|\#*) continue ;;
    esac
    value="$(_manage_mask_value "$key" "$value")"
    printf "  %-35s = %s\n" "$key" "$value"
  done < "$env_file"
}

# ---------- Routes ----------

_manage_route_has_oauth2() {
  grep -q 'oauth2-chain' "$1" 2>/dev/null
}

_manage_route_has_crowdsec() {
  grep -q 'security-chain\|crowdsec' "$1" 2>/dev/null
}

_manage_route_has_placeholder() {
  grep -Eq '\$\{|__[A-Z0-9_]+__' "$1" 2>/dev/null
}

_manage_file_has_placeholder() {
  grep -Eq '\$\{|__[A-Z0-9_]+__' "$1" 2>/dev/null
}

_manage_route_extract_host() {
  local rule_line
  rule_line=$(grep "rule:" "$1" 2>/dev/null || true)
  if [ -n "$rule_line" ]; then
    echo "$rule_line" | sed -n 's/.*Host(`\([^`]*\)`).*/\1/p'
  fi
}

_manage_route_classify() {
  local file="$1"
  local filename
  filename=$(basename "$file")

  if [ "$filename" = "route-oauth2-proxy.yml" ]; then
    echo "proxy-oauth2"
    return
  fi

  if _manage_route_has_placeholder "$file"; then
    echo "anomalie-placeholder"
    return
  fi

  _manage_route_has_oauth2 "$file" && echo "protegee" || echo "publique"
}

manage_routes() {
  manage_require_installation

  local dynamic_dir="${TRAEFIK_DYNAMIC_DIR}"
  if [ ! -d "$dynamic_dir" ]; then
    warn "Aucun dossier de routes dynamiques (${dynamic_dir})."
    return 0
  fi

  echo "Routes Traefik (${dynamic_dir}) :"
  echo ""

  local found=false
  for file in "$dynamic_dir"/route-*.yml; do
    [ -f "$file" ] || continue
    found=true
    local filename host classification extra
    filename=$(basename "$file")
    host="$(_manage_route_extract_host "$file")"
    classification="$(_manage_route_classify "$file")"
    extra=""

    local app_name="${filename#route-}"
    app_name="${app_name%.yml}"
    local app_env="${INSTALLED_DIR}/${app_name}.env"

    case "$classification" in
      protegee)
        if [ -f "$app_env" ]; then
          manage_reset_app_env
          source "$app_env"
          render_normalize_app_vars "$app_name"
          if [ "${APP_PROTECTED:-${APP_AUTH:-true}}" != true ]; then
            extra=" (anomalie: APP_PROTECTED=false mais route protégée)"
          fi
        elif [ "$filename" != "route-traefik.yml" ]; then
          extra=" (anomalie: route orpheline)"
        fi
        if [ "${WITH_CROWDSEC}" = true ]; then
          ok "  ${filename}  (protégée, CrowdSec)${extra}  ${host:+→ ${host}}"
        else
          ok "  ${filename}  (protégée)${extra}  ${host:+→ ${host}}"
        fi
        ;;
      publique)
        if [ -f "$app_env" ]; then
          manage_reset_app_env
          source "$app_env"
          render_normalize_app_vars "$app_name"
          if [ "${APP_PROTECTED:-${APP_AUTH:-true}}" = true ]; then
            extra=" (anomalie: APP_PROTECTED=true mais route publique)"
          fi
        elif [ "$filename" != "route-traefik.yml" ]; then
          extra=" (anomalie: route orpheline)"
        fi
        if _manage_route_has_crowdsec "$file"; then
          info "  ${filename}  (publique, CrowdSec)${extra}  ${host:+→ ${host}}"
        else
          info "  ${filename}  (publique)${extra}  ${host:+→ ${host}}"
        fi
        ;;
      proxy-oauth2)
        ok "  ${filename}  (OAuth2 Proxy)  ${host:+→ ${host}}"
        ;;
      anomalie-placeholder)
        err "  ${filename}  (placeholders résiduels)  ${host:+→ ${host}}"
        ;;
    esac
  done

  if [ "$found" = false ]; then
    warn "  Aucune route trouvée."
  fi
}

# ---------- Protect ----------

manage_protect() {
  manage_require_installation
  local dry_run_prefix=""
  [ "${DRY_RUN:-false}" = true ] && dry_run_prefix="[DRY-RUN] "

  if [ "${OAUTH2_ENABLED}" != true ]; then
    err "OAuth2 Proxy n'est pas activé dans la configuration."
    err "Protection impossible sans OAuth2 Proxy."
    exit 1
  fi

  local middleware_tpl="${TEMPLATE_DIR}/traefik/middleware-oauth2.yml"
  if [ ! -f "$middleware_tpl" ]; then
    err "Template middleware OAuth2 introuvable : ${middleware_tpl}"
    exit 1
  fi

  echo "${dry_run_prefix}Régénération du middleware OAuth2 Proxy..."
  render_oauth2_middleware_template "$middleware_tpl" "${TRAEFIK_DYNAMIC_DIR}/middleware-oauth2.yml"

  if [ "${WITH_CROWDSEC}" = true ]; then
    echo "${dry_run_prefix}Régénération du middleware CrowdSec..."
    render_template "${TEMPLATE_DIR}/traefik/middleware-crowdsec.yml" "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml"
  fi

  if [ "${WITH_TRAEFIK}" = true ]; then
    local route_traefik_tpl="${TEMPLATE_DIR}/traefik/route-traefik-oauth2.yml"
    if [ -f "$route_traefik_tpl" ]; then
      echo "${dry_run_prefix}Protection de la route Traefik..."
      render_traefik_route_template "$route_traefik_tpl" "${TRAEFIK_DYNAMIC_DIR}/route-traefik.yml"
    fi
  fi

  local count=0
  for f in "${INSTALLED_DIR}"/*.env; do
    [ -f "$f" ] || continue
    local installed_key
    installed_key=$(basename "$f" .env)
    manage_reset_app_env
    source "$f"
    render_normalize_app_vars "$installed_key"
    if [ "${APP_PROTECTED:-${APP_AUTH:-true}}" = true ] && [ "${APP_LOCAL_ONLY:-false}" != true ] && [ "${APP_DISABLED:-false}" != true ]; then
      echo "${dry_run_prefix}Protection de la route ${APP_INSTANCE:-$installed_key}..."
      render_app_route_from_env "${TRAEFIK_DYNAMIC_DIR}/route-${APP_INSTANCE:-$installed_key}.yml"
      ((count++)) || true
    fi
  done

  if [ "$count" -eq 0 ]; then
    info "Aucune application à protéger."
  else
    ok "${count} application(s) protégée(s)."
  fi

  ok "Les routes suivantes ne sont pas modifiées : route-oauth2-proxy.yml"
}

# ---------- Render ----------

manage_render() {
  manage_require_installation
  local dry_run_prefix=""
  [ "${DRY_RUN:-false}" = true ] && dry_run_prefix="[DRY-RUN] "

  info "Régénération de la configuration Traefik..."

  run mkdir -p "${TRAEFIK_DYNAMIC_DIR}"

  if [ "${WITH_TRAEFIK}" = true ]; then
    echo "${dry_run_prefix}Rendu de traefik.yml (configuration statique)..."
    render_traefik_static_template "${TEMPLATE_DIR}" "${TRAEFIK_DIR}/traefik.yml"

    echo "${dry_run_prefix}Rendu de tls.yml..."
    render_template "${TEMPLATE_DIR}/traefik/tls.yml" "${TRAEFIK_DYNAMIC_DIR}/tls.yml"

    if [ "${OAUTH2_ENABLED}" = true ]; then
      echo "${dry_run_prefix}Rendu de route-traefik.yml (avec OAuth2 Proxy)..."
      render_traefik_route_template "${TEMPLATE_DIR}/traefik/route-traefik-oauth2.yml" "${TRAEFIK_DYNAMIC_DIR}/route-traefik.yml"
    else
      echo "${dry_run_prefix}Rendu de route-traefik.yml (sans OAuth2 Proxy)..."
      render_traefik_route_template "${TEMPLATE_DIR}/traefik/route-traefik.yml" "${TRAEFIK_DYNAMIC_DIR}/route-traefik.yml"
    fi
  fi

  if [ "${WITH_CROWDSEC}" = true ]; then
    run mkdir -p "${CROWDSEC_DIR}" "${CROWDSEC_DIR}/config" "${CROWDSEC_DIR}/data"
    echo "${dry_run_prefix}Rendu de la stack CrowdSec..."
    render_template "${TEMPLATE_DIR}/compose/crowdsec.yml" "${CROWDSEC_DIR}/docker-compose.yml"
    render_template "${TEMPLATE_DIR}/crowdsec/acquis.yml" "${CROWDSEC_DIR}/acquis.yml"
    render_template "${TEMPLATE_DIR}/crowdsec/profiles.yaml" "${CROWDSEC_DIR}/profiles.yaml"
    if [ "${CROWDSEC_APPSEC_ENABLED}" = true ]; then
      echo "${dry_run_prefix}Rendu de appsec.yaml..."
      render_template "${TEMPLATE_DIR}/crowdsec/appsec.yaml" "${CROWDSEC_DIR}/appsec.yaml"
    elif [ -f "${CROWDSEC_DIR}/appsec.yaml" ]; then
      if [ "${DRY_RUN:-false}" = true ]; then
        warn "[DRY-RUN] Suppression de ${CROWDSEC_DIR}/appsec.yaml"
      else
        rm -f "${CROWDSEC_DIR}/appsec.yaml"
      fi
    fi
    echo "${dry_run_prefix}Rendu de middleware-crowdsec.yml..."
    render_template "${TEMPLATE_DIR}/traefik/middleware-crowdsec.yml" "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml"
  elif [ -f "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml" ]; then
    if [ "${DRY_RUN:-false}" = true ]; then
      warn "[DRY-RUN] Suppression de ${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml"
    else
      rm -f "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml"
    fi
  fi

  if [ "${OAUTH2_ENABLED}" = true ]; then
    run mkdir -p "${OAUTH2_DIR}"
    echo "${dry_run_prefix}Rendu de la stack OAuth2 Proxy..."
    render_oauth2_compose_runtime "${OAUTH2_DIR}/docker-compose.yml"

    echo "${dry_run_prefix}Rendu de middleware-oauth2.yml..."
    render_oauth2_middleware_template "${TEMPLATE_DIR}/traefik/middleware-oauth2.yml" "${TRAEFIK_DYNAMIC_DIR}/middleware-oauth2.yml"

    echo "${dry_run_prefix}Rendu de route-oauth2-proxy.yml..."
    render_template "${TEMPLATE_DIR}/traefik/route-oauth2-proxy.yml" "${TRAEFIK_DYNAMIC_DIR}/route-oauth2-proxy.yml"
  fi

  local count=0
  for f in "${INSTALLED_DIR}"/*.env; do
    [ -f "$f" ] || continue
    local installed_key
    installed_key=$(basename "$f" .env)
    manage_reset_app_env
    source "$f"
    render_normalize_app_vars "$installed_key"
    local route_id="${APP_INSTANCE:-$installed_key}"
    local route_dest="${TRAEFIK_DYNAMIC_DIR}/route-${route_id}.yml"
    if [ "${APP_LOCAL_ONLY:-false}" = true ] || [ "${APP_DISABLED:-false}" = true ] || [ "${APP_PUBLIC:-true}" != true ]; then
      if [ -f "$route_dest" ]; then
        if [ "${DRY_RUN:-false}" = true ]; then
          warn "[DRY-RUN] Suppression de ${route_dest}"
        else
          rm -f "$route_dest"
        fi
      fi
      continue
    fi
    if [ "${APP_PROTECTED:-${APP_AUTH:-true}}" = true ]; then
      echo "${dry_run_prefix}Rendu de route-${route_id}.yml (protégée)..."
    else
      echo "${dry_run_prefix}Rendu de route-${route_id}.yml (publique)..."
    fi
    render_app_route_from_env "$route_dest"
    ((count++)) || true
  done

  for file in "${TRAEFIK_DYNAMIC_DIR}"/route-*.yml; do
    [ -f "$file" ] || continue
    local filename app_name
    filename=$(basename "$file")
    case "$filename" in
      route-traefik.yml|route-oauth2-proxy.yml)
        continue
        ;;
    esac
    app_name="${filename#route-}"
    app_name="${app_name%.yml}"
    if [ ! -f "${INSTALLED_DIR}/${app_name}.env" ]; then
      if [ "${DRY_RUN:-false}" = true ]; then
        warn "[DRY-RUN] Suppression de ${file}"
      else
        rm -f "$file"
      fi
    fi
  done

  ok "${count} route(s) d'application régénérée(s)."
  ok "Rendu terminé. La configuration générée est à jour ; relance ./ksf.sh restart pour appliquer la configuration statique Traefik."
}

# ---------- Restart ----------

manage_wait_crowdsec_ready() {
  local attempt

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Vérification disponibilité CrowdSec avant Traefik"
    return 0
  fi

  info "Vérification de la disponibilité CrowdSec..."
  for attempt in {1..30}; do
    if (cd "${CROWDSEC_DIR}" && docker compose exec -T crowdsec cscli lapi status >/dev/null 2>&1); then
      ok "CrowdSec est prêt."
      return 0
    fi
    sleep 2
  done

  err "CrowdSec n'est pas disponible après redémarrage. Traefik ne sera pas redémarré avec le middleware CrowdSec."
  err "Commande de dépannage : cd ${CROWDSEC_DIR} && docker compose logs crowdsec"
  exit 1
}

manage_restart() {
  manage_require_installation

  if [ "${DRY_RUN:-false}" != true ]; then
    if ! command -v docker >/dev/null 2>&1; then
      err "Docker n'est pas installé ou inaccessible."
      exit 1
    fi
    if ! docker compose version >/dev/null 2>&1; then
      err "Docker Compose n'est pas disponible."
      exit 1
    fi
  fi

  local restarted=false

  if [ "${WITH_CROWDSEC}" = true ] && [ -f "${CROWDSEC_DIR}/docker-compose.yml" ]; then
    if [ "${DRY_RUN:-false}" = true ]; then
      warn "[DRY-RUN] Redémarrage CrowdSec prévu : cd ${CROWDSEC_DIR} && docker compose restart"
    else
      info "Redémarrage de CrowdSec..."
      if ! (cd "${CROWDSEC_DIR}" && docker compose restart); then
        err "Échec du redémarrage de CrowdSec."
        exit 1
      fi
      manage_wait_crowdsec_ready
    fi
    restarted=true
  fi

  if [ -f "${TRAEFIK_DIR}/docker-compose.yml" ]; then
    if [ "${DRY_RUN:-false}" = true ]; then
      warn "[DRY-RUN] Redémarrage Traefik prévu : cd ${TRAEFIK_DIR} && docker compose restart"
    else
      info "Redémarrage de Traefik..."
      (cd "${TRAEFIK_DIR}" && docker compose restart) || warn "Échec du redémarrage de Traefik."
    fi
    restarted=true
  fi

  if [ "${OAUTH2_ENABLED}" = true ] && [ -f "${OAUTH2_DIR}/docker-compose.yml" ]; then
    if [ "${DRY_RUN:-false}" = true ]; then
      warn "[DRY-RUN] Redémarrage OAuth2 Proxy prévu : cd ${OAUTH2_DIR} && docker compose restart"
    else
      info "Redémarrage de OAuth2 Proxy..."
      (cd "${OAUTH2_DIR}" && docker compose restart) || warn "Échec du redémarrage de OAuth2 Proxy."
    fi
    restarted=true
  fi

  if [ "$restarted" = false ]; then
    warn "Aucune stack d'infrastructure à redémarrer."
  else
    if [ "${DRY_RUN:-false}" = true ]; then
      ok "Redémarrage : prévu (dry-run)"
    else
      ok "Redémarrage terminé."
    fi
  fi
}

# ---------- Clean data ----------

_manage_validate_clean_app_name() {
  local app_name="${1:-}"

  case "$app_name" in
    ''|'.'|'..'|*..*|*/*|*\\*)
      err "Nom d'application invalide ou chemin suspect : ${app_name:-<vide>}"
      exit 1
      ;;
  esac
}

_manage_clean_data_target() {
  local app_name="$1"
  local base="${BASE_DIR%/}"
  [ -n "$base" ] || base="/"
  printf '%s/data/%s' "$base" "$app_name"
}

_manage_validate_clean_target() {
  local target="$1"
  local base="${BASE_DIR%/}"
  [ -n "$base" ] || base="/"

  if [ "$target" = "/" ] || [ "$target" = "$HOME" ] || [ "$target" = "$base" ] || [ "$target" = "${base}/data" ]; then
    err "Refus de supprimer un chemin dangereux : ${target}"
    exit 1
  fi

  case "$target" in
    "${base}/data/"*) ;;
    *)
      err "Refus de supprimer un chemin hors de ${base}/data : ${target}"
      exit 1
      ;;
  esac
}

manage_clean_data() {
  local app_name="${1:-}"
  manage_require_installation

  local data_root="${BASE_DIR}/data"
  if [ -z "$app_name" ]; then
    if [ ! -d "$data_root" ]; then
      warn "Dossier de données absent : ${data_root}"
      return 0
    fi

    info "Dossiers de données dans ${data_root} :"
    local found=false
    for dir in "$data_root"/*; do
      [ -d "$dir" ] || continue
      found=true
      local name status
      name=$(basename "$dir")
      if [ -f "${INSTALLED_DIR}/${name}.env" ]; then
        status="installée"
      else
        status="orpheline"
      fi
      info "  ${name}  (${status})  ${dir}"
    done
    if [ "$found" = false ]; then
      warn "Aucun dossier de données trouvé."
    fi
    return 0
  fi

  _manage_validate_clean_app_name "$app_name"
  local target
  target="$(_manage_clean_data_target "$app_name")"
  _manage_validate_clean_target "$target"

  if [ ! -d "$target" ]; then
    warn "Aucun dossier de données à supprimer pour ${app_name} : ${target}"
    return 0
  fi

  local installed=false
  if [ -f "${INSTALLED_DIR}/${app_name}.env" ]; then
    installed=true
  fi

  if [ "${DRY_RUN:-false}" = true ]; then
    if [ "$installed" = true ]; then
      warn "[DRY-RUN] ${app_name} est encore installée. Suppression des données nécessiterait une confirmation explicite."
    fi
    warn "[DRY-RUN] rm -rf -- ${target}"
    return 0
  fi

  echo "Dossier ciblé : ${target}"
  if [ "$installed" = true ]; then
    warn "L'app ${app_name} est encore installée. Cette suppression peut casser l'application."
    echo -n "Tape 'SUPPRIMER ${app_name}' pour confirmer : "
    local confirmation
    if ! read -r confirmation || [ "$confirmation" != "SUPPRIMER ${app_name}" ]; then
      err "Confirmation invalide. Suppression annulée."
      exit 1
    fi
  else
    echo -n "Tape '${app_name}' pour confirmer la suppression des données : "
    local confirmation
    if ! read -r confirmation || [ "$confirmation" != "$app_name" ]; then
      err "Confirmation invalide. Suppression annulée."
      exit 1
    fi
  fi

  rm -rf -- "$target"
  ok "Données supprimées : ${target}"
}

# ---------- CrowdSec ----------

manage_crowdsec_require() {
  manage_require_installation

  if [ "${WITH_CROWDSEC}" != true ]; then
    err "CrowdSec n'est pas activé dans ${BASE_DIR}/config/ksf.env."
    exit 1
  fi
  if [ ! -f "${CROWDSEC_DIR}/docker-compose.yml" ]; then
    err "Stack CrowdSec absente : ${CROWDSEC_DIR}/docker-compose.yml"
    exit 1
  fi
}

manage_crowdsec_cscli() {
  local display_command="$1"
  shift

  manage_crowdsec_require

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${CROWDSEC_DIR} && docker compose exec -T crowdsec cscli ${display_command}"
    return 0
  fi
  (cd "${CROWDSEC_DIR}" && docker compose exec -T crowdsec cscli "$@")
}

manage_crowdsec_status() {
  manage_crowdsec_require

  echo "=== CrowdSec ==="
  echo "Stack   : ${CROWDSEC_DIR}"
  echo "Config  : ${CROWDSEC_DIR}/config"
  echo "Data    : ${CROWDSEC_DIR}/data"
  echo "Logs    : ${TRAEFIK_DIR}/logs/access.log"
  echo ""

  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker inaccessible, état container indisponible."
    return 0
  fi

  (cd "${CROWDSEC_DIR}" && docker compose ps) || warn "Impossible de lire l'état Compose de CrowdSec."
}

manage_crowdsec_logs() {
  manage_crowdsec_require

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${CROWDSEC_DIR} && docker compose logs --tail=200 crowdsec"
    return 0
  fi
  (cd "${CROWDSEC_DIR}" && docker compose logs --tail=200 crowdsec) || err "Impossible de lire les logs CrowdSec."
}

manage_crowdsec_decisions() {
  manage_crowdsec_cscli "decisions list" decisions list || { err "Impossible de lire les décisions CrowdSec."; exit 1; }
}

manage_crowdsec_alerts() {
  manage_crowdsec_cscli "alerts list" alerts list || { err "Impossible de lire les alertes CrowdSec."; exit 1; }
}

manage_crowdsec_metrics() {
  manage_crowdsec_cscli "metrics" metrics || { err "Impossible de lire les métriques CrowdSec."; exit 1; }
}

manage_crowdsec_bouncers() {
  manage_crowdsec_cscli "bouncers list" bouncers list || { err "Impossible de lire les bouncers CrowdSec."; exit 1; }
}

manage_crowdsec_ban() {
  local ip="${1:-}"
  local duration="${2:-4h}"

  if [ -z "$ip" ]; then
    err "IP manquante. Usage : ./ksf.sh crowdsec ban <ip> [duration]"
    exit 1
  fi
  manage_crowdsec_cscli "decisions add --ip ${ip} -d ${duration}" decisions add --ip "$ip" -d "$duration" || { err "Impossible d'ajouter la décision CrowdSec."; exit 1; }
}

manage_crowdsec_unban() {
  local ip="${1:-}"

  if [ -z "$ip" ]; then
    err "IP manquante. Usage : ./ksf.sh crowdsec unban <ip>"
    exit 1
  fi
  manage_crowdsec_cscli "decisions delete --ip ${ip}" decisions delete --ip "$ip" || { err "Impossible de supprimer la décision CrowdSec."; exit 1; }
}

manage_crowdsec_flush_decisions() {
  warn "Cette commande supprime toutes les décisions CrowdSec actives."
  manage_crowdsec_cscli "decisions delete --all" decisions delete --all || { err "Impossible de supprimer toutes les décisions CrowdSec."; exit 1; }
}

manage_crowdsec_extract_enroll_token() {
  local input="${1:-}"
  local token

  input="${input//$'\r'/}"
  input="${input//$'\n'/ }"
  token="${input##* }"
  printf '%s' "$token"
}

manage_crowdsec_enroll() {
  local enroll_input="${1:-}"
  local token

  token="$(manage_crowdsec_extract_enroll_token "$enroll_input")"
  if [ -z "$token" ]; then
    err "Token d'enrôlement manquant. Usage : ./ksf.sh crowdsec enroll <token-ou-commande>"
    exit 1
  fi
  manage_crowdsec_cscli "console enroll <token masqué>" console enroll "$token" || { err "Impossible d'enrôler CrowdSec dans la Console."; exit 1; }
}

manage_crowdsec_console_status() {
  manage_crowdsec_cscli "console status" console status || { err "Impossible de lire le statut Console CrowdSec."; exit 1; }
}

manage_crowdsec_appsec_collections_declared() {
  local collections="${CROWDSEC_APPSEC_COLLECTIONS:-}"
  local collection rendered=""

  for collection in $collections; do
    case " $rendered " in
      *" $collection "*) ;;
      *) rendered="${rendered:+${rendered} }${collection}" ;;
    esac
  done
  printf '%s' "$rendered"
}

manage_crowdsec_appsec_install_collections() {
  local collection installed

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Installation/vérification collections AppSec : $(manage_crowdsec_appsec_collections_declared)"
    return 0
  fi

  if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    warn "Docker Compose indisponible, les collections AppSec seront déclarées via COLLECTIONS au prochain démarrage."
    return 0
  fi
  if ! docker ps --filter "name=crowdsec$" --format "{{.Names}}" 2>/dev/null | grep -q "crowdsec"; then
    warn "Container CrowdSec arrêté ou absent, les collections AppSec seront déclarées via COLLECTIONS au prochain démarrage."
    return 0
  fi

  for collection in $(manage_crowdsec_appsec_collections_declared); do
    installed=false
    if (cd "${CROWDSEC_DIR}" && docker compose exec -T crowdsec cscli collections list 2>/dev/null) | grep -q "$collection"; then
      installed=true
    fi
    if [ "$installed" = true ]; then
      ok "Collection AppSec déjà présente : ${collection}"
    else
      info "Installation collection AppSec : ${collection}"
      (cd "${CROWDSEC_DIR}" && docker compose exec -T crowdsec cscli collections install "$collection") || {
        err "Impossible d'installer la collection AppSec : ${collection}"
        exit 1
      }
    fi
  done
}

manage_crowdsec_appsec_restart_crowdsec() {
  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${CROWDSEC_DIR} && docker compose up -d --force-recreate"
    warn "[DRY-RUN] Vérification disponibilité CrowdSec"
    return 0
  fi
  info "Recréation de CrowdSec pour appliquer la configuration AppSec..."
  (cd "${CROWDSEC_DIR}" && docker compose up -d --force-recreate) || { err "Échec du redémarrage de CrowdSec."; exit 1; }
  manage_wait_crowdsec_ready
}

manage_crowdsec_appsec_restart_traefik() {
  if [ ! -f "${TRAEFIK_DIR}/docker-compose.yml" ]; then
    warn "Stack Traefik absente, redémarrage ignoré."
    return 0
  fi
  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${TRAEFIK_DIR} && docker compose up -d --force-recreate"
    return 0
  fi
  info "Recréation de Traefik pour appliquer la configuration AppSec..."
  (cd "${TRAEFIK_DIR}" && docker compose up -d --force-recreate) || { err "Échec du redémarrage de Traefik."; exit 1; }
}

manage_crowdsec_appsec_status() {
  manage_crowdsec_require

  echo "=== AppSec / WAF ==="
  echo "Config ksf.env       : ${CROWDSEC_APPSEC_ENABLED}"
  echo "AppSec listen addr   : ${CROWDSEC_APPSEC_LISTEN_ADDR}"
  echo "AppSec host Traefik  : ${CROWDSEC_APPSEC_HOST}"
  echo "Failure block        : ${CROWDSEC_APPSEC_FAILURE_BLOCK}"
  echo "Unreachable block    : ${CROWDSEC_APPSEC_UNREACHABLE_BLOCK}"
  echo "Collections attendues: $(manage_crowdsec_appsec_collections_declared)"
  echo ""

  if [ -f "${CROWDSEC_DIR}/appsec.yaml" ]; then
    ok "appsec.yaml présent : ${CROWDSEC_DIR}/appsec.yaml"
  else
    warn "appsec.yaml absent"
  fi

  if [ -f "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml" ] && grep -q 'crowdsecAppsecEnabled: true' "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml" 2>/dev/null; then
    ok "Middleware Traefik AppSec actif"
  else
    warn "Middleware Traefik AppSec inactif ou absent"
  fi

  if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    warn "Docker Compose indisponible, statut runtime AppSec non vérifié."
    return 0
  fi

  if docker ps --filter "name=crowdsec$" --format "{{.Names}}" 2>/dev/null | grep -q "crowdsec"; then
    if (cd "${CROWDSEC_DIR}" && docker compose exec -T crowdsec sh -c 'ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null || true') | grep -q ':7422'; then
      ok "CrowdSec écoute sur 7422 dans le conteneur"
    else
      warn "Écoute 7422 non vérifiée dans le conteneur CrowdSec"
    fi
    (cd "${CROWDSEC_DIR}" && docker compose exec -T crowdsec cscli collections list 2>/dev/null | grep -E 'appsec|virtual-patching|generic-rules') || warn "Collections AppSec installées non détectées."
  else
    warn "Container CrowdSec arrêté ou absent"
  fi
}

manage_crowdsec_appsec_enable() {
  manage_crowdsec_require

  manage_update_ksf_env_value "CROWDSEC_APPSEC_ENABLED" "true"
  CROWDSEC_APPSEC_ENABLED=true
  manage_update_ksf_env_value "CROWDSEC_APPSEC_LISTEN_ADDR" "${CROWDSEC_APPSEC_LISTEN_ADDR}"
  manage_update_ksf_env_value "CROWDSEC_APPSEC_HOST" "${CROWDSEC_APPSEC_HOST}"
  manage_update_ksf_env_value "CROWDSEC_APPSEC_FAILURE_BLOCK" "${CROWDSEC_APPSEC_FAILURE_BLOCK}"
  manage_update_ksf_env_value "CROWDSEC_APPSEC_UNREACHABLE_BLOCK" "${CROWDSEC_APPSEC_UNREACHABLE_BLOCK}"
  manage_update_ksf_env_value "CROWDSEC_APPSEC_COLLECTIONS" "${CROWDSEC_APPSEC_COLLECTIONS}"

  manage_render
  manage_require_installation
  CROWDSEC_APPSEC_ENABLED=true
  manage_crowdsec_appsec_install_collections
  manage_crowdsec_appsec_restart_crowdsec
  manage_crowdsec_appsec_restart_traefik

  echo ""
  ok "AppSec / WAF activé."
  echo "  AppSec host       : ${CROWDSEC_APPSEC_HOST}"
  echo "  Failure block     : ${CROWDSEC_APPSEC_FAILURE_BLOCK}"
  echo "  Unreachable block : ${CROWDSEC_APPSEC_UNREACHABLE_BLOCK}"
  echo "  Collections       : $(manage_crowdsec_appsec_collections_declared)"
}

manage_crowdsec_appsec_disable() {
  manage_crowdsec_require

  manage_update_ksf_env_value "CROWDSEC_APPSEC_ENABLED" "false"
  CROWDSEC_APPSEC_ENABLED=false
  manage_render
  manage_require_installation
  CROWDSEC_APPSEC_ENABLED=false
  manage_crowdsec_appsec_restart_crowdsec
  manage_crowdsec_appsec_restart_traefik

  ok "AppSec / WAF désactivé. CrowdSec log-based reste actif."
}

manage_crowdsec_appsec_metrics() {
  manage_crowdsec_require

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${CROWDSEC_DIR} && docker compose exec -T crowdsec cscli metrics show appsec"
    return 0
  fi

  local output=""
  output=$(cd "${CROWDSEC_DIR}" && docker compose exec -T crowdsec cscli metrics show appsec 2>/dev/null || true)
  if [ -z "$output" ]; then
    warn "Aucune métrique AppSec disponible pour l'instant. Lancez un test ou attendez du trafic."
    return 0
  fi
  printf '%s\n' "$output"
}

manage_crowdsec_appsec_detect_test_host() {
  local f

  if [ -n "${TRAEFIK_HOST:-}" ]; then
    printf '%s' "${TRAEFIK_HOST}"
    return 0
  fi
  for f in "${INSTALLED_DIR}"/*.env; do
    [ -f "$f" ] || continue
    APP_HOST=""
    APP_LOCAL_ONLY=false
    source "$f"
    if [ "${APP_LOCAL_ONLY:-false}" != true ] && [ -n "${APP_HOST:-}" ]; then
      printf '%s' "${APP_HOST}"
      return 0
    fi
  done
  return 1
}

manage_crowdsec_appsec_test() {
  manage_crowdsec_require

  local host url status
  if ! host="$(manage_crowdsec_appsec_detect_test_host)" || [ -z "$host" ]; then
    warn "Aucune URL testable détectée. Lancez manuellement : curl -I https://<host>/.env"
    return 0
  fi
  url="https://${host}/.env"

  if ! command -v curl >/dev/null 2>&1; then
    warn "curl indisponible. Lancez manuellement : curl -I ${url}"
    return 0
  fi
  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] curl -k -I --max-time 10 ${url}"
    return 0
  fi

  info "Test AppSec contrôlé : ${url}"
  status=$(curl -k -I --max-time 10 -o /dev/null -s -w '%{http_code}' "$url" || true)
  if [ "$status" = "403" ]; then
    ok "AppSec bloque correctement le test (${status})."
  else
    warn "Résultat inattendu : HTTP ${status:-indisponible}. Attendu : 403 si AppSec bloque correctement."
    warn "Commande manuelle : curl -I ${url}"
  fi
}

manage_crowdsec_appsec() {
  local subcommand="${1:-status}"

  case "$subcommand" in
    status) manage_crowdsec_appsec_status ;;
    enable) manage_crowdsec_appsec_enable ;;
    disable) manage_crowdsec_appsec_disable ;;
    metrics) manage_crowdsec_appsec_metrics ;;
    test) manage_crowdsec_appsec_test ;;
    *)
      err "Commande AppSec / WAF inconnue : ${subcommand:-<vide>}"
      err "Commandes disponibles : status, enable, disable, metrics, test"
      exit 1
      ;;
  esac
}

manage_crowdsec_restart() {
  manage_crowdsec_require

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${CROWDSEC_DIR} && docker compose restart"
    return 0
  fi
  (cd "${CROWDSEC_DIR}" && docker compose restart) || err "Échec du redémarrage de CrowdSec."
  ok "CrowdSec redémarré."
}

manage_crowdsec() {
  local subcommand="${1:-}"
  local arg="${2:-}"
  local duration="${3:-}"

  case "$subcommand" in
    status) manage_crowdsec_status ;;
    logs) manage_crowdsec_logs ;;
    decisions) manage_crowdsec_decisions ;;
    alerts) manage_crowdsec_alerts ;;
    metrics) manage_crowdsec_metrics ;;
    bouncers) manage_crowdsec_bouncers ;;
    ban) manage_crowdsec_ban "$arg" "$duration" ;;
    unban) manage_crowdsec_unban "$arg" ;;
    flush-decisions) manage_crowdsec_flush_decisions ;;
    enroll) manage_crowdsec_enroll "$arg" ;;
    console-status) manage_crowdsec_console_status ;;
    appsec) manage_crowdsec_appsec "$arg" ;;
    restart) manage_crowdsec_restart ;;
    *)
      err "Commande CrowdSec inconnue : ${subcommand:-<vide>}"
      err "Commandes disponibles : status, logs, decisions, alerts, metrics, bouncers, ban, unban, flush-decisions, enroll, console-status, restart, appsec"
      exit 1
      ;;
  esac
}

# ---------- Trusted IPs ----------

manage_trusted_ips_cloudflare() {
  local source_url
  local joined

  source_url="$(cloudflare_ips_source_url)"
  joined="$(fetch_cloudflare_trusted_ips)" || exit 1

  echo "Source officielle : ${source_url}"
  echo "Endpoints utilisés : https://www.cloudflare.com/ips-v4 et https://www.cloudflare.com/ips-v6"
  echo ""
  echo "TRAEFIK_TRUSTED_IPS=${joined}"
  echo ""
  echo "Après mise à jour de ksf.env : ./ksf.sh render puis ./ksf.sh restart"
}

manage_update_ksf_env_value() {
  local key="$1"
  local value="$2"
  local env_file="${BASE_DIR}/config/ksf.env"
  local tmp_file="${env_file}.tmp"
  local line found=false

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Mise à jour ${key} dans ${env_file}"
    return 0
  fi

  if [ ! -f "$env_file" ]; then
    err "Configuration absente : ${env_file}"
    exit 1
  fi

  : > "$tmp_file"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "${key}="*)
        printf '%s=%s\n' "$key" "$(ksf_env_quote_value "$value")" >> "$tmp_file"
        found=true
        ;;
      *)
        printf '%s\n' "$line" >> "$tmp_file"
        ;;
    esac
  done < "$env_file"
  if [ "$found" = false ]; then
    printf '%s=%s\n' "$key" "$(ksf_env_quote_value "$value")" >> "$tmp_file"
  fi
  mv "$tmp_file" "$env_file"
  chmod 600 "$env_file"
}

manage_restart_traefik_only() {
  if ! command -v docker >/dev/null 2>&1; then
    err "Docker n'est pas installé ou inaccessible."
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    err "Docker Compose n'est pas disponible."
    exit 1
  fi
  if [ ! -f "${TRAEFIK_DIR}/docker-compose.yml" ]; then
    err "Stack Traefik absente : ${TRAEFIK_DIR}/docker-compose.yml"
    exit 1
  fi

  if [ "${WITH_CROWDSEC}" = true ] && [ -f "${CROWDSEC_DIR}/docker-compose.yml" ]; then
    manage_wait_crowdsec_ready
  fi

  info "Recréation de Traefik pour appliquer la configuration..."
  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${TRAEFIK_DIR} && docker compose up -d --force-recreate"
    return 0
  fi
  if ! (cd "${TRAEFIK_DIR}" && docker compose up -d --force-recreate); then
    err "Échec du redémarrage de Traefik."
    exit 1
  fi
  ok "Traefik recréé."
}

manage_trusted_ips_apply_cloudflare() {
  local source_url
  local trusted_ips

  manage_require_installation
  if [ "${WITH_TRAEFIK}" != true ]; then
    err "Traefik n'est pas activé dans ${BASE_DIR}/config/ksf.env."
    exit 1
  fi

  source_url="$(cloudflare_ips_source_url)"
  info "Récupération des plages IP Cloudflare officielles..."
  trusted_ips="$(fetch_cloudflare_trusted_ips)" || exit 1

  manage_update_ksf_env_value "TRAEFIK_TRUSTED_IPS" "$trusted_ips"
  TRAEFIK_TRUSTED_IPS="$trusted_ips"
  TRAEFIK_TRUSTED_IPS_YAML="$(_manage_format_yaml_inline_list "${TRAEFIK_TRUSTED_IPS}")"
  ok "TRAEFIK_TRUSTED_IPS mis à jour depuis ${source_url}."

  manage_render
  manage_require_installation
  manage_restart_traefik_only

  echo ""
  echo "Résumé trusted IPs :"
  echo "  Source           : ${source_url}"
  echo "  Config           : ${BASE_DIR}/config/ksf.env"
  echo "  Traefik statique : ${TRAEFIK_DIR}/traefik.yml"
  echo "  CIDR             : $(printf '%s' "$trusted_ips" | tr ',' ' ' | wc -w) entrée(s)"
}

manage_trusted_ips() {
  local subcommand="${1:-}"
  local provider="${2:-}"

  case "$subcommand" in
    cloudflare) manage_trusted_ips_cloudflare ;;
    apply)
      case "$provider" in
        cloudflare) manage_trusted_ips_apply_cloudflare ;;
        *)
          err "Fournisseur trusted-ips inconnu : ${provider:-<vide>}"
          err "Commandes disponibles : apply cloudflare"
          exit 1
          ;;
      esac
      ;;
    *)
      err "Commande trusted-ips inconnue : ${subcommand:-<vide>}"
      err "Commandes disponibles : cloudflare, apply cloudflare"
      exit 1
      ;;
  esac
}

# ---------- Doctor ----------

_manage_check() {
  local status="$1"
  local label="$2"
  local detail="${3:-}"
  local msg="${label}"
  [ -n "$detail" ] && msg="${msg} — ${detail}"
  case "$status" in
    ok)   ok "  ✓ ${msg}" ;;
    warn) warn "  ⚠ ${msg}" ;;
    err)  err "  ✗ ${msg}" ;;
  esac
}

manage_doctor() {
  manage_require_installation

  local errors=0
  local warnings=0

  echo "=== KSF Diagnostic ==="
  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Doctor : diagnostic en lecture seule, aucune modification prévue."
  fi
  echo ""

  # 1. Configuration présente et lisible
  local env_file="${BASE_DIR}/config/ksf.env"
  if [ -f "$env_file" ] && [ -r "$env_file" ]; then
    _manage_check ok "Configuration présente" "${env_file}"
  else
    _manage_check err "Configuration absente ou illisible" "${env_file}"
    ((errors++)) || true
  fi

  # 2. Permissions
  if [ -f "$env_file" ]; then
    local perms
    perms=$(stat -c "%a" "$env_file" 2>/dev/null || stat -f "%Lp" "$env_file" 2>/dev/null || echo "?")
    if [ "$perms" = "600" ]; then
      _manage_check ok "Permissions config" "600"
    else
      _manage_check warn "Permissions config" "${perms} (recommandé: 600)"
      ((warnings++)) || true
    fi
  fi

  # 3. Répertoires attendus
  local dirs_ok=true
  for d in "${BASE_DIR}/proxy" "${BASE_DIR}/apps" "${BASE_DIR}/data" "${BASE_DIR}/config/installed-apps" "${BASE_DIR}/logs"; do
    if [ ! -d "$d" ]; then
      _manage_check err "Répertoire manquant" "$d"
      ((errors++)) || true
      dirs_ok=false
    fi
  done
  [ "$dirs_ok" = true ] && _manage_check ok "Répertoires" "Arborescence présente"

  # 4. Stacks infrastructure
  if [ "${WITH_TRAEFIK}" = true ]; then
    if [ -f "${TRAEFIK_DIR}/docker-compose.yml" ]; then
      _manage_check ok "Stack Traefik" "docker-compose.yml présent"
      if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        if (cd "${TRAEFIK_DIR}" && docker compose config >/dev/null 2>&1); then
          _manage_check ok "Compose Traefik" "docker compose config valide"
        else
          _manage_check err "Compose Traefik" "docker compose config échoue"
          ((errors++)) || true
        fi
      else
        _manage_check warn "Compose Traefik" "Docker Compose indisponible"
        ((warnings++)) || true
      fi
    else
      _manage_check err "Stack Traefik" "docker-compose.yml absent"
      ((errors++)) || true
    fi
  fi
  if [ "${OAUTH2_ENABLED}" = true ]; then
    if [ -f "${OAUTH2_DIR}/docker-compose.yml" ]; then
      _manage_check ok "Stack OAuth2 Proxy" "docker-compose.yml présent"
      if [ -f "${OAUTH2_DIR}/templates/sign_in.html" ]; then
        _manage_check ok "Template OAuth2 Proxy" "templates/sign_in.html présent"
      else
        _manage_check warn "Template OAuth2 Proxy" "templates/sign_in.html absent (lancer: ./ksf.sh render)"
        ((warnings++)) || true
      fi
      if grep -q -- '--custom-templates-dir=/etc/oauth2-proxy/templates' "${OAUTH2_DIR}/docker-compose.yml" 2>/dev/null; then
        _manage_check ok "Option OAuth2 templates" "custom-templates-dir configuré"
      else
        _manage_check warn "Option OAuth2 templates" "--custom-templates-dir absent"
        ((warnings++)) || true
      fi
      if grep -q './templates:/etc/oauth2-proxy/templates:ro' "${OAUTH2_DIR}/docker-compose.yml" 2>/dev/null; then
        _manage_check ok "Montage OAuth2 templates" "./templates:/etc/oauth2-proxy/templates:ro"
      else
        _manage_check warn "Montage OAuth2 templates" "montage templates absent"
        ((warnings++)) || true
      fi
    else
      _manage_check err "Stack OAuth2 Proxy" "docker-compose.yml absent"
      ((errors++)) || true
    fi
  fi
  if [ "${WITH_CROWDSEC}" = true ]; then
    if [ -f "${CROWDSEC_DIR}/docker-compose.yml" ]; then
      _manage_check ok "Stack CrowdSec" "docker-compose.yml présent"
      if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        if (cd "${CROWDSEC_DIR}" && docker compose config >/dev/null 2>&1); then
          _manage_check ok "Compose CrowdSec" "docker compose config valide"
        else
          _manage_check err "Compose CrowdSec" "docker compose config échoue"
          ((errors++)) || true
        fi
      else
        _manage_check warn "Compose CrowdSec" "Docker Compose indisponible"
        ((warnings++)) || true
      fi
    else
      _manage_check err "Stack CrowdSec" "docker-compose.yml absent"
      ((errors++)) || true
    fi
  fi

  # 5. Docker
  if command -v docker >/dev/null 2>&1; then
    if docker ps >/dev/null 2>&1; then
      _manage_check ok "Docker" "Daemon accessible"

      # 5a. Réseau
      if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
        _manage_check ok "Réseau Docker" "${NETWORK_NAME} présent"
      else
        _manage_check warn "Réseau Docker" "${NETWORK_NAME} absent"
        ((warnings++)) || true
      fi

      # 5b. Containers Traefik
      if [ "${WITH_TRAEFIK}" = true ] && [ -f "${TRAEFIK_DIR}/docker-compose.yml" ]; then
        if docker ps --filter "name=traefik$" --format "{{.Names}}" 2>/dev/null | grep -q "traefik"; then
          _manage_check ok "Container Traefik" "Actif"
        else
          _manage_check warn "Container Traefik" "Arrêté ou absent (lancer: ./ksf.sh restart)"
          ((warnings++)) || true
        fi
      fi

      # 5c. Containers OAuth2
      if [ "${OAUTH2_ENABLED}" = true ] && [ -f "${OAUTH2_DIR}/docker-compose.yml" ]; then
        if docker ps --filter "name=oauth2-proxy$" --format "{{.Names}}" 2>/dev/null | grep -q "oauth2-proxy"; then
          _manage_check ok "Container OAuth2 Proxy" "Actif"
        else
          _manage_check warn "Container OAuth2 Proxy" "Arrêté ou absent"
          ((warnings++)) || true
        fi
      fi

      # 5d. Container CrowdSec et réseau partagé
      if [ "${WITH_CROWDSEC}" = true ] && [ -f "${CROWDSEC_DIR}/docker-compose.yml" ]; then
        if docker ps --filter "name=crowdsec$" --format "{{.Names}}" 2>/dev/null | grep -q "crowdsec"; then
          _manage_check ok "Container CrowdSec" "Actif"
          if docker inspect crowdsec --format '{{json .NetworkSettings.Networks}}' 2>/dev/null | grep -q "\"${NETWORK_NAME}\""; then
            _manage_check ok "Réseau CrowdSec" "Connecté à ${NETWORK_NAME}"
          else
            _manage_check err "Réseau CrowdSec" "Non connecté à ${NETWORK_NAME}"
            ((errors++)) || true
          fi
        else
          _manage_check warn "Container CrowdSec" "Arrêté ou absent"
          ((warnings++)) || true
        fi
      fi
    else
      _manage_check warn "Docker" "Installé mais inaccessible pour cet utilisateur"
      ((warnings++)) || true
    fi
  else
    _manage_check warn "Docker" "Non installé ou absent du PATH"
    ((warnings++)) || true
  fi

  # 6. Middleware OAuth2 Proxy
  if [ "${OAUTH2_ENABLED}" = true ]; then
    if [ -f "${TRAEFIK_DYNAMIC_DIR}/middleware-oauth2.yml" ]; then
      _manage_check ok "Middleware OAuth2 Proxy" "Présent"
    else
      _manage_check err "Middleware OAuth2 Proxy" "Absent (lancer: ./ksf.sh render)"
      ((errors++)) || true
    fi
  fi
  if [ "${WITH_CROWDSEC}" = true ]; then
    if [ -f "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml" ]; then
      _manage_check ok "Middleware CrowdSec" "Présent"
      if grep -q 'plugin:' "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml" 2>/dev/null && grep -q '^[[:space:]]*bouncer:' "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml" 2>/dev/null; then
        _manage_check ok "Plugin dynamique CrowdSec" "plugin.bouncer"
      else
        _manage_check err "Plugin dynamique CrowdSec" "plugin.bouncer absent"
        ((errors++)) || true
      fi
      if grep -q 'crowdsecMode: "stream"' "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml" 2>/dev/null; then
        _manage_check ok "Mode CrowdSec" "stream"
      else
        _manage_check err "Mode CrowdSec" "stream absent"
        ((errors++)) || true
      fi
    else
      _manage_check err "Middleware CrowdSec" "Absent (lancer: ./ksf.sh render)"
      ((errors++)) || true
    fi
    if [ -f "${TRAEFIK_DIR}/traefik.yml" ]; then
      if grep -q '^[[:space:]]*bouncer:' "${TRAEFIK_DIR}/traefik.yml" 2>/dev/null; then
        _manage_check ok "Plugin statique Traefik" "experimental.plugins.bouncer"
      else
        _manage_check err "Plugin statique Traefik" "experimental.plugins.bouncer absent"
        ((errors++)) || true
      fi
      if grep -q '^accessLog:' "${TRAEFIK_DIR}/traefik.yml" 2>/dev/null && grep -q 'filePath: /logs/access.log' "${TRAEFIK_DIR}/traefik.yml" 2>/dev/null; then
        _manage_check ok "Access log statique" "Configuré dans traefik.yml"
      else
        _manage_check err "Access log statique" "Absent de traefik.yml"
        ((errors++)) || true
      fi
    else
      _manage_check err "Config Traefik" "traefik.yml absent"
      ((errors++)) || true
    fi
    if [ -f "${TRAEFIK_DIR}/logs/access.log" ]; then
      if [ -r "${TRAEFIK_DIR}/logs/access.log" ]; then
        _manage_check ok "Access log Traefik" "Présent et lisible"
      else
        _manage_check err "Access log Traefik" "Présent mais illisible"
        ((errors++)) || true
      fi
    else
      _manage_check err "Access log Traefik" "Absent (${TRAEFIK_DIR}/logs/access.log)"
      ((errors++)) || true
    fi
    if [ -f "${CROWDSEC_DIR}/acquis.yml" ] && grep -q '/var/log/traefik/access.log' "${CROWDSEC_DIR}/acquis.yml" 2>/dev/null; then
      _manage_check ok "Acquisition CrowdSec" "Traefik access.log configuré"
    else
      _manage_check err "Acquisition CrowdSec" "acquis.yml absent ou incomplet"
      ((errors++)) || true
    fi
    if [ -n "${CROWDSEC_BOUNCER_KEY:-}" ]; then
      _manage_check ok "Clé bouncer CrowdSec" "Présente dans ksf.env local"
    else
      _manage_check err "Clé bouncer CrowdSec" "Absente de ksf.env"
      ((errors++)) || true
    fi
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && docker ps --filter "name=crowdsec$" --format "{{.Names}}" 2>/dev/null | grep -q "crowdsec"; then
      local crowdsec_console_status
      if crowdsec_console_status=$(cd "${CROWDSEC_DIR}" && docker compose exec -T crowdsec cscli console status 2>/dev/null); then
        if printf '%s' "$crowdsec_console_status" | grep -Eiq 'not enrolled|not registered|disabled'; then
          _manage_check warn "Console CrowdSec" "Instance non enrôlée"
          ((warnings++)) || true
        else
          _manage_check ok "Console CrowdSec" "cscli console status OK"
        fi
      else
        _manage_check warn "Console CrowdSec" "Non configurée ou statut indisponible"
        ((warnings++)) || true
      fi
    else
      _manage_check warn "Console CrowdSec" "Statut non vérifié (conteneur CrowdSec indisponible)"
      ((warnings++)) || true
    fi
    if [ "${DNS_RECORD_PROXIED:-false}" = true ] && [ -z "${TRAEFIK_TRUSTED_IPS:-}" ]; then
      _manage_check warn "IP réelle Cloudflare" "TRAEFIK_TRUSTED_IPS absent, CrowdSec peut bannir les IP Cloudflare"
      ((warnings++)) || true
    elif [ -n "${TRAEFIK_TRUSTED_IPS:-}" ]; then
      _manage_check ok "Trusted IPs Traefik" "${TRAEFIK_TRUSTED_IPS}"
    fi

    if [ "${CROWDSEC_APPSEC_ENABLED:-false}" != true ]; then
      _manage_check ok "AppSec / WAF" "inactif"
    else
      if [ -f "${CROWDSEC_DIR}/appsec.yaml" ]; then
        if grep -q 'crowdsecurity/appsec-default' "${CROWDSEC_DIR}/appsec.yaml" 2>/dev/null && grep -q 'source: appsec' "${CROWDSEC_DIR}/appsec.yaml" 2>/dev/null && grep -q "listen_addr: ${CROWDSEC_APPSEC_LISTEN_ADDR}" "${CROWDSEC_DIR}/appsec.yaml" 2>/dev/null; then
          _manage_check ok "AppSec / WAF acquisition" "appsec.yaml présent"
        else
          _manage_check err "AppSec / WAF acquisition" "appsec.yaml incomplet"
          ((errors++)) || true
        fi
      else
        _manage_check err "AppSec / WAF acquisition" "appsec.yaml absent"
        ((errors++)) || true
      fi

      if [ -f "${CROWDSEC_DIR}/docker-compose.yml" ]; then
        if grep -q './appsec.yaml:/etc/crowdsec/acquis.d/appsec.yaml:ro' "${CROWDSEC_DIR}/docker-compose.yml" 2>/dev/null; then
          _manage_check ok "Montage AppSec" "/etc/crowdsec/acquis.d/appsec.yaml:ro"
        else
          _manage_check err "Montage AppSec" "Absent du compose CrowdSec"
          ((errors++)) || true
        fi
        if grep -Eq '^[[:space:]]*-[[:space:]]*"?([0-9.]+:)?7422:7422' "${CROWDSEC_DIR}/docker-compose.yml" 2>/dev/null; then
          _manage_check err "Port AppSec public" "7422 publié sur l'hôte"
          ((errors++)) || true
        else
          _manage_check ok "Port AppSec public" "7422 non publié sur l'hôte"
        fi
        local missing_collection=false
        local collection
        for collection in $(manage_crowdsec_appsec_collections_declared); do
          if ! grep -q "$collection" "${CROWDSEC_DIR}/docker-compose.yml" 2>/dev/null; then
            missing_collection=true
          fi
        done
        if [ "$missing_collection" = false ]; then
          _manage_check ok "Collections AppSec déclarées" "$(manage_crowdsec_appsec_collections_declared)"
        else
          _manage_check warn "Collections AppSec déclarées" "compose CrowdSec incomplet"
          ((warnings++)) || true
        fi
      fi

      if [ -f "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml" ]; then
        if grep -q 'crowdsecAppsecEnabled: true' "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml" 2>/dev/null && grep -q "crowdsecAppsecHost: \"${CROWDSEC_APPSEC_HOST}\"" "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml" 2>/dev/null; then
          _manage_check ok "Middleware AppSec Traefik" "${CROWDSEC_APPSEC_HOST}"
        else
          _manage_check err "Middleware AppSec Traefik" "crowdsecAppsecEnabled/Host absent"
          ((errors++)) || true
        fi
      fi

      if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && docker ps --filter "name=crowdsec$" --format "{{.Names}}" 2>/dev/null | grep -q "crowdsec"; then
        if (cd "${CROWDSEC_DIR}" && docker compose exec -T crowdsec cscli metrics show appsec >/dev/null 2>&1); then
          _manage_check ok "Métriques AppSec" "cscli metrics show appsec exécutable"
        else
          _manage_check warn "Métriques AppSec" "Commande indisponible ou aucune métrique"
          ((warnings++)) || true
        fi
        local missing_installed=false
        for collection in $(manage_crowdsec_appsec_collections_declared); do
          if ! (cd "${CROWDSEC_DIR}" && docker compose exec -T crowdsec cscli collections list 2>/dev/null) | grep -q "$collection"; then
            missing_installed=true
          fi
        done
        if [ "$missing_installed" = false ]; then
          _manage_check ok "Collections AppSec installées" "Présentes dans CrowdSec"
        else
          _manage_check warn "Collections AppSec installées" "Non vérifiées ou absentes dans CrowdSec"
          ((warnings++)) || true
        fi
      elif command -v docker >/dev/null 2>&1 && docker ps >/dev/null 2>&1; then
        _manage_check warn "Runtime AppSec" "Container CrowdSec indisponible"
        ((warnings++)) || true
      fi

      if command -v docker >/dev/null 2>&1 && docker ps --filter "name=traefik$" --format "{{.Names}}" 2>/dev/null | grep -q "traefik"; then
        if docker exec traefik sh -c 'command -v nc >/dev/null 2>&1 && nc -z -w 3 crowdsec 7422' >/dev/null 2>&1; then
          _manage_check ok "Port AppSec interne" "Traefik joint crowdsec:7422"
        else
          _manage_check warn "Port AppSec interne" "Test réseau non vérifié depuis Traefik"
          ((warnings++)) || true
        fi
      fi
    fi
  fi

  if [ "${WITH_TRAEFIK}" = true ] && [ -f "${TRAEFIK_DIR}/traefik.yml" ]; then
    local trusted_ips_count
    trusted_ips_count=$(grep -F -c "trustedIPs: ${TRAEFIK_TRUSTED_IPS_YAML}" "${TRAEFIK_DIR}/traefik.yml" 2>/dev/null || true)
    if [ "${trusted_ips_count:-0}" -ge 2 ]; then
      _manage_check ok "Trusted IPs rendues" "${TRAEFIK_TRUSTED_IPS:-aucune}"
    else
      _manage_check err "Trusted IPs rendues" "traefik.yml ne correspond pas à TRAEFIK_TRUSTED_IPS=${TRAEFIK_TRUSTED_IPS:-<vide>}"
      ((errors++)) || true
    fi
  fi

  # 7. Routes
  if [ -d "${TRAEFIK_DYNAMIC_DIR}" ]; then
    local route_issues=false
    for file in "${TRAEFIK_DYNAMIC_DIR}"/route-*.yml; do
      [ -f "$file" ] || continue
      if _manage_file_has_placeholder "$file"; then
        _manage_check err "Route avec placeholders" "$(basename "$file")"
        ((errors++)) || true
        route_issues=true
      fi
    done
    [ "$route_issues" = false ] && _manage_check ok "Routes" "Aucun placeholder résiduel"
  fi

  if [ -d "${TRAEFIK_DIR}" ]; then
    local generated_issues=false
    for file in "${TRAEFIK_DIR}"/*.yml "${TRAEFIK_DYNAMIC_DIR}"/*.yml; do
      [ -f "$file" ] || continue
      if _manage_file_has_placeholder "$file"; then
        _manage_check err "Fichier avec placeholders" "${file#${BASE_DIR}/}"
        ((errors++)) || true
        generated_issues=true
      fi
    done
    [ "$generated_issues" = false ] && _manage_check ok "Fichiers Traefik" "Aucun placeholder résiduel"
  fi

  # 8. Apps installées
  local app_count=0
  for f in "${INSTALLED_DIR}"/*.env; do
    [ -f "$f" ] || continue
    ((app_count++)) || true
    local installed_key
    installed_key=$(basename "$f" .env)
    manage_reset_app_env
    source "$f"
    render_normalize_app_vars "$installed_key"
    local app_dir="${APP_DIR:-${BASE_DIR}/apps/${APP_NAME}}"
    local compose_file="${app_dir}/docker-compose.yml"
    local route_id="${APP_INSTANCE:-$installed_key}"
    local route_file="${TRAEFIK_DYNAMIC_DIR}/route-${route_id}.yml"
    local route_expected=false

    local app_label="${APP_INSTANCE:-$installed_key}"
    if [ ! -d "$app_dir" ]; then
      _manage_check warn "App ${app_label}" "Dossier stack absent"
      ((warnings++)) || true
    fi
    if [ ! -f "$compose_file" ]; then
      _manage_check err "App ${app_label}" "compose.yml absent"
      ((errors++)) || true
    fi
    if [ "${WITH_TRAEFIK:-false}" = true ] && [ "${APP_LOCAL_ONLY:-false}" != true ] && [ "${APP_DISABLED:-false}" != true ] && [ "${APP_PUBLIC:-true}" = true ]; then
      route_expected=true
    fi
    if [ "$route_expected" = true ]; then
      if [ ! -f "$route_file" ]; then
        _manage_check err "Route app ${route_id}" "route manquante : ${route_file#${BASE_DIR}/}"
        ((errors++)) || true
      else
        local route_classification
        route_classification="$(_manage_route_classify "$route_file")"
        if [ "${APP_PROTECTED:-${APP_AUTH:-true}}" = true ] && [ "$route_classification" != "protegee" ]; then
          _manage_check err "Route app ${route_id}" "APP_PROTECTED=true mais route non protégée"
          ((errors++)) || true
        fi
        if [ "${APP_PROTECTED:-${APP_AUTH:-true}}" = false ] && [ "$route_classification" = "protegee" ]; then
          _manage_check warn "Route app ${route_id}" "APP_PROTECTED=false mais route protégée"
          ((warnings++)) || true
        fi
        if [ "$route_classification" = "publique" ] && ! grep -Eq '^(APP_PROTECTED|APP_AUTH)=false$' "$f" 2>/dev/null; then
          _manage_check err "Route app ${route_id}" "exposition publique sans APP_PROTECTED=false explicite"
          ((errors++)) || true
        fi
      fi
    elif [ -f "$route_file" ] && { [ "${APP_LOCAL_ONLY:-false}" = true ] || [ "${APP_DISABLED:-false}" = true ] || [ "${APP_PUBLIC:-true}" != true ]; }; then
      _manage_check warn "Route app ${route_id}" "route présente malgré app non exposée"
      ((warnings++)) || true
    fi
  done

  for app_dir in "${BASE_DIR}/apps"/*; do
    [ -d "$app_dir" ] || continue
    local stack_name
    stack_name=$(basename "$app_dir")
    if [ -f "${app_dir}/docker-compose.yml" ] && [ ! -f "${INSTALLED_DIR}/${stack_name}.env" ]; then
      if _manage_disabled_app_matches_stack "$stack_name" "$app_dir"; then
        _manage_check warn "App ${stack_name}" "stack legacy/desactivee presente dans installed-apps/disabled"
        ((warnings++)) || true
      else
        _manage_check err "App ${stack_name}" "app.env d'installation absent"
        ((errors++)) || true
      fi
    fi
  done

  if [ "$app_count" -gt 0 ]; then
    _manage_check ok "Apps installées" "${app_count} app(s)"
  else
    info "  Aucune app installée."
  fi

  # 9. DNS automatique
  if [ "${DNS_AUTO_CREATE:-false}" = true ]; then
    if [ -z "${SERVER_PUBLIC_IP:-}" ]; then
      _manage_check warn "DNS auto" "SERVER_PUBLIC_IP absent"
      ((warnings++)) || true
    else
      _manage_check ok "DNS auto" "Configuré (${DNS_PROVIDER:-cloudflare}, IP: ${SERVER_PUBLIC_IP})"
    fi
  fi

  # 10. Fichiers orphelins
  if [ -d "${TRAEFIK_DYNAMIC_DIR}" ]; then
    local orphan_count=0
    for file in "${TRAEFIK_DYNAMIC_DIR}"/route-*.yml; do
      [ -f "$file" ] || continue
      local filename
      filename=$(basename "$file")
      [ "$filename" = "route-oauth2-proxy.yml" ] || [ "$filename" = "route-traefik.yml" ] || [ "$filename" = "tls.yml" ] && continue
      local app_name="${filename#route-}"
      app_name="${app_name%.yml}"
      if [ ! -f "${INSTALLED_DIR}/${app_name}.env" ]; then
        _manage_check warn "Route orpheline" "${filename} (app ${app_name} non installée)"
        ((orphan_count++)) || true
        ((warnings++)) || true
      fi
    done
    [ "$orphan_count" -eq 0 ] && _manage_check ok "Fichiers" "Aucune route orpheline"
  fi

  echo ""
  local total_issues=$((errors + warnings))
  if [ "$total_issues" -eq 0 ]; then
    ok "Diagnostic terminé : aucun problème détecté."
  else
    warn "Diagnostic terminé : ${errors} erreur(s), ${warnings} avertissement(s)."
    [ "$errors" -gt 0 ] && info "→ ./ksf.sh render  peut corriger les fichiers dynamiques."
  fi

  return "$errors"
}
