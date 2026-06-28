#!/usr/bin/env bash
# ============================================================
# KSF - Menu interactif dynamique
# Orchestre les commandes existantes via ksf.sh / app.sh
# ============================================================

MENU_SELECTED_APP=""
MENU_SELECTED_TEMPLATE=""
MENU_LAST_COMMAND_RC=0
MENU_INSTALLATION_PRESENT=false
MENU_DOCKER_AVAILABLE=false
MENU_WITH_TRAEFIK=false
MENU_WITH_OAUTH2=false
MENU_WITH_CROWDSEC=false
MENU_WITH_APPSEC=false
MENU_TRAEFIK_DIR=""
MENU_OAUTH2_DIR=""
MENU_CROWDSEC_DIR=""
MENU_INSTALLED_DIR=""
MENU_APP_TEMPLATE_DIR="${SCRIPT_DIR}/templates/apps"
MENU_DOMAIN=""

_menu_app_display_name() {
  if [ "${MENU_APP_INSTANCE:-}" != "${MENU_APP_TEMPLATE:-}" ] && [ -n "${MENU_APP_TEMPLATE:-}" ]; then
    printf '%s [%s]' "${MENU_APP_INSTANCE}" "${MENU_APP_TEMPLATE}"
  else
    printf '%s' "${MENU_APP_INSTANCE}"
  fi
}

_menu_app_oauth_label() {
  if [ "${MENU_APP_LOCAL_ONLY:-false}" = true ]; then
    printf '%s' "n/a"
  elif [ "${MENU_APP_PROTECTED:-true}" = true ]; then
    printf '%s' "on"
  else
    printf '%s' "off"
  fi
}

_menu_pause() {
  echo ""
  read -rp "Appuie sur Entree pour revenir au menu..." _
}

_menu_confirm() {
  local message="$1"

  if [ "${AUTO_YES:-false}" = true ]; then
    return 0
  fi

  echo ""
  echo -n "${message} (oui/non) : "
  local answer
  read -r answer
  case "$answer" in
    o|O|oui|Oui|OUI|y|Y|yes|Yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

_menu_ksf() {
  local -a args

  args=("$@" "--base-dir" "$BASE_DIR")
  [ "${DRY_RUN:-false}" = true ] && args+=("--dry-run")
  [ "${AUTO_YES:-false}" = true ] && args+=("--yes")

  if bash "${SCRIPT_DIR}/ksf.sh" "${args[@]}"; then
    MENU_LAST_COMMAND_RC=0
  else
    MENU_LAST_COMMAND_RC=$?
    warn "La commande ksf a termine avec le code ${MENU_LAST_COMMAND_RC}. Retour au menu."
  fi

  return 0
}

_menu_app() {
  local -a args
  local -a env_args
  local rc

  args=("$@" "--base-dir" "$BASE_DIR")
  [ "${DRY_RUN:-false}" = true ] && args+=("--dry-run")
  [ "${AUTO_YES:-false}" = true ] && args+=("--yes")
  env_args=()
  [ "${MENU_APP_INSTALL_FORCE:-false}" = true ] && env_args+=("APP_INSTALL_FORCE=true")
  [ "${MENU_APP_REMOVE_SKIP_CONFIRM:-false}" = true ] && env_args+=("APP_REMOVE_SKIP_CONFIRM=true")
  [ -n "${MENU_APP_REMOVE_DELETE_DATA:-}" ] && env_args+=("APP_REMOVE_DELETE_DATA=${MENU_APP_REMOVE_DELETE_DATA}")

  if [ "${#env_args[@]}" -gt 0 ]; then
    env "${env_args[@]}" bash "${SCRIPT_DIR}/app.sh" "${args[@]}"
  else
    bash "${SCRIPT_DIR}/app.sh" "${args[@]}"
  fi
  rc=$?

  if [ "$rc" -eq 0 ]; then
    MENU_LAST_COMMAND_RC=0
  else
    MENU_LAST_COMMAND_RC=$rc
    warn "La commande app a termine avec le code ${MENU_LAST_COMMAND_RC}. Retour au menu."
  fi

  return 0
}

_menu_cli_path_contains() {
  local dir="$1"
  local IFS=':'
  local p
  for p in $PATH; do
    [ "$p" = "$dir" ] && return 0
  done
  return 1
}

_menu_setup_paths() {
  MENU_INSTALLED_DIR="${BASE_DIR}/config/installed-apps"
  MENU_TRAEFIK_DIR="${BASE_DIR}/proxy/traefik"
  MENU_OAUTH2_DIR="${BASE_DIR}/proxy/oauth2-proxy"
  MENU_CROWDSEC_DIR="${BASE_DIR}/proxy/crowdsec"
}

_menu_refresh_context() {
  local env_file="${BASE_DIR}/config/ksf.env"
  local saved_base_dir="$BASE_DIR"

  MENU_INSTALLATION_PRESENT=false
  MENU_WITH_TRAEFIK=false
  MENU_WITH_OAUTH2=false
  MENU_WITH_CROWDSEC=false
  MENU_WITH_APPSEC=false
  MENU_DOCKER_AVAILABLE=false
  MENU_DOMAIN=""

  _menu_setup_paths

  if [ -f "$env_file" ]; then
    MENU_INSTALLATION_PRESENT=true
    if [ "${DRY_RUN:-false}" != true ]; then
      ksf_env_repair_sourceable_file "$env_file"
    fi
    source "$env_file"
    BASE_DIR="$saved_base_dir"
    _menu_setup_paths
    MENU_DOMAIN="${DOMAIN:-}"
    [ "${WITH_TRAEFIK:-false}" = true ] && MENU_WITH_TRAEFIK=true
    [ "${OAUTH2_ENABLED:-false}" = true ] && MENU_WITH_OAUTH2=true
    [ "${WITH_CROWDSEC:-false}" = true ] && MENU_WITH_CROWDSEC=true
    [ "${CROWDSEC_APPSEC_ENABLED:-false}" = true ] && MENU_WITH_APPSEC=true
  fi

  if command -v docker >/dev/null 2>&1 && docker ps >/dev/null 2>&1; then
    MENU_DOCKER_AVAILABLE=true
  fi
}

_menu_container_state() {
  local name="$1"
  local state health

  if [ "$MENU_DOCKER_AVAILABLE" != true ]; then
    printf '%s' "docker indisponible"
    return 0
  fi

  if ! docker inspect "$name" >/dev/null 2>&1; then
    printf '%s' "absent"
    return 0
  fi

  state=$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || printf 'unknown')
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null || printf 'unknown')

  if [ "$health" != "none" ] && [ -n "$health" ]; then
    printf '%s (%s)' "$state" "$health"
  else
    printf '%s' "$state"
  fi
}

_menu_service_enabled() {
  local service="$1"

  case "$service" in
    traefik)
      [ "$MENU_WITH_TRAEFIK" = true ] || [ -f "${MENU_TRAEFIK_DIR}/docker-compose.yml" ]
      ;;
    oauth2)
      [ "$MENU_WITH_OAUTH2" = true ] || [ -f "${MENU_OAUTH2_DIR}/docker-compose.yml" ]
      ;;
    crowdsec)
      [ "$MENU_WITH_CROWDSEC" = true ] || [ -f "${MENU_CROWDSEC_DIR}/docker-compose.yml" ]
      ;;
    *)
      return 1
      ;;
  esac
}

_menu_service_stack_dir() {
  case "$1" in
    traefik) printf '%s' "$MENU_TRAEFIK_DIR" ;;
    oauth2) printf '%s' "$MENU_OAUTH2_DIR" ;;
    crowdsec) printf '%s' "$MENU_CROWDSEC_DIR" ;;
    *) return 1 ;;
  esac
}

_menu_service_container_name() {
  case "$1" in
    traefik) printf '%s' "traefik" ;;
    oauth2) printf '%s' "oauth2-proxy" ;;
    crowdsec) printf '%s' "crowdsec" ;;
    *) return 1 ;;
  esac
}

_menu_service_label() {
  case "$1" in
    traefik) printf '%s' "Traefik" ;;
    oauth2) printf '%s' "OAuth2 Proxy" ;;
    crowdsec) printf '%s' "CrowdSec" ;;
    *) printf '%s' "$1" ;;
  esac
}

_menu_service_state() {
  local service="$1"
  local container_name
  local stack_dir

  if ! _menu_service_enabled "$service"; then
    printf '%s' "non configure"
    return 0
  fi

  stack_dir="$(_menu_service_stack_dir "$service")"
  if [ ! -f "${stack_dir}/docker-compose.yml" ]; then
    printf '%s' "stack absente"
    return 0
  fi

  container_name="$(_menu_service_container_name "$service")"
  _menu_container_state "$container_name"
}

_menu_collect_installed_apps() {
  MENU_INSTALLED_APPS=()
  [ -d "$MENU_INSTALLED_DIR" ] || return 0

  local file
  for file in "${MENU_INSTALLED_DIR}"/*.env; do
    [ -f "$file" ] || continue
    MENU_INSTALLED_APPS+=("$(basename "$file" .env)")
  done
}

_menu_collect_available_templates() {
  MENU_AVAILABLE_TEMPLATES=()
  [ -d "$MENU_APP_TEMPLATE_DIR" ] || return 0

  local dir
  for dir in "${MENU_APP_TEMPLATE_DIR}"/*/; do
    [ -d "$dir" ] || continue
    [ -f "${dir}/app.env" ] || continue
    MENU_AVAILABLE_TEMPLATES+=("$(basename "$dir")")
  done
}

_menu_template_description() {
  local template_name="$1"
  local env_file="${MENU_APP_TEMPLATE_DIR}/${template_name}/app.env"

  [ -f "$env_file" ] || {
    printf '%s' "$template_name"
    return 0
  }

  (
    APP_DESCRIPTION=""
    source "$env_file" >/dev/null 2>&1
    printf '%s' "${APP_DESCRIPTION:-${template_name}}"
  )
}

_menu_template_category() {
  local template_name="$1"
  local env_file="${MENU_APP_TEMPLATE_DIR}/${template_name}/app.env"

  [ -f "$env_file" ] || {
    printf '%s' "general"
    return 0
  }

  (
    APP_CATEGORY=""
    source "$env_file" >/dev/null 2>&1
    printf '%s' "${APP_CATEGORY:-general}"
  )
}

_menu_remove_summary() {
  local app_name="$1"
  local delete_data_choice="$2"
  local installed_file="${MENU_INSTALLED_DIR}/${app_name}.env"
  local route_file="${BASE_DIR}/proxy/traefik/dynamic/route-${app_name}.yml"

  echo ""
  echo "Resume suppression :"
  printf '  Instance    : %s\n' "$MENU_APP_INSTANCE"
  printf '  Template    : %s\n' "$MENU_APP_TEMPLATE"
  printf '  Acces       : %s\n' "$(_menu_app_access_label)"
  echo ""
  echo "Sera supprimé :"
  printf '  - Stack     : %s\n' "$MENU_APP_DIR"
  printf '  - Fichier   : %s\n' "$installed_file"
  if [ -f "$route_file" ] || [ -n "${MENU_APP_HOST:-}" ]; then
    printf '  - Route/DNS : %s\n' "${MENU_APP_HOST:-route-${app_name}.yml}"
  fi
  if [ "$delete_data_choice" = true ]; then
    printf '  - Donnees   : %s\n' "$MENU_APP_DATA"
  else
    printf '  - Donnees   : conservees (%s)\n' "$MENU_APP_DATA"
  fi
}

_menu_remove_app_assistant() {
  local remove_choice
  local confirmation

  if ! _menu_pick_installed_app; then
    return 1
  fi

  _menu_load_app_record "$MENU_SELECTED_APP" || return 1

  echo ""
  echo "Suppression de ${MENU_SELECTED_APP} :"
  echo "  1) Supprimer l'app seulement"
  echo "  2) Supprimer l'app et les donnees locales"
  echo "  3) Annuler"
  echo ""
  read -rp "Choix [1-3] : " remove_choice

  case "${remove_choice:-3}" in
    1) MENU_APP_REMOVE_DELETE_DATA=false ;;
    2) MENU_APP_REMOVE_DELETE_DATA=true ;;
    3) return 1 ;;
    *) err "Choix invalide."; return 1 ;;
  esac

  _menu_remove_summary "$MENU_SELECTED_APP" "$MENU_APP_REMOVE_DELETE_DATA"
  echo ""
  echo -n "Tape 'SUPPRESSION' pour confirmer : "
  if ! read -r confirmation || ! ksf_confirmation_is_deletion "$confirmation"; then
    err "Suppression annulée."
    return 1
  fi

  MENU_APP_REMOVE_SKIP_CONFIRM=true
  _menu_app remove "$MENU_SELECTED_APP"
  MENU_APP_REMOVE_SKIP_CONFIRM=false
  MENU_APP_REMOVE_DELETE_DATA=""
  return 0
}

_menu_print_available_templates() {
  _menu_collect_available_templates

  if [ "${#MENU_AVAILABLE_TEMPLATES[@]}" -eq 0 ]; then
    warn "Aucun template d'app disponible."
    return 0
  fi

  echo "Templates d'apps disponibles :"
  echo "  Template      | Categorie | Description"
  local template_name
  for template_name in "${MENU_AVAILABLE_TEMPLATES[@]}"; do
    printf '  %s\n' "$(printf '%-13s | %-9s | %s' "$template_name" "$(_menu_template_category "$template_name")" "$(_menu_template_description "$template_name")")"
  done
}

_menu_template_value() {
  local template_name="$1"
  local key="$2"
  local env_file="${MENU_APP_TEMPLATE_DIR}/${template_name}/app.env"

  [ -f "$env_file" ] || return 0

  (
    APP_NAME=""
    APP_HOST=""
    APP_DEFAULT_HOST=""
    APP_PROTECTED=""
    APP_PUBLIC=""
    source "$env_file" >/dev/null 2>&1
    case "$key" in
      APP_DEFAULT_HOST)
        printf '%s' "${APP_DEFAULT_HOST:-${APP_HOST:-${template_name}}}"
        ;;
      APP_PROTECTED)
        printf '%s' "${APP_PROTECTED:-true}"
        ;;
      APP_PUBLIC)
        printf '%s' "${APP_PUBLIC:-true}"
        ;;
      *)
        printf '%s' "${!key-}"
        ;;
    esac
  )
}

_menu_allowed_domains() {
  local configured="${DOMAINS:-${DOMAIN:-}}"
  configured="${configured//[[:space:]]/}"
  printf '%s' "$configured"
}

_menu_default_domain() {
  local configured
  configured="$(_menu_allowed_domains)"

  if [ -n "${MENU_DOMAIN:-}" ]; then
    printf '%s' "$MENU_DOMAIN"
    return 0
  fi

  printf '%s' "${configured%%,*}"
}

_menu_domain_allowed() {
  local domain="${1:-}"
  local configured remaining candidate

  configured="$(_menu_allowed_domains)"
  remaining="${configured},"

  while [ -n "$remaining" ]; do
    candidate="${remaining%%,*}"
    remaining="${remaining#*,}"
    [ -n "$candidate" ] || continue
    [ "$domain" = "$candidate" ] && return 0
  done

  return 1
}

_menu_existing_instance_template() {
  local instance_name="$1"
  local env_file="${MENU_INSTALLED_DIR}/${instance_name}.env"

  [ -f "$env_file" ] || return 0

  (
    APP_NAME=""
    source "$env_file" >/dev/null 2>&1
    printf '%s' "${APP_NAME:-${instance_name}}"
  )
}

_menu_install_summary() {
  local action_label="$1"
  local template_name="$2"
  local instance_name="$3"
  local access_label="$4"
  local oauth_label="$5"
  local dns_label="$6"

  echo ""
  echo "Resume :"
  printf '  Action      : %s\n' "$action_label"
  printf '  Template    : %s\n' "$template_name"
  printf '  Instance    : %s\n' "$instance_name"
  printf '  Acces       : %s\n' "$access_label"
  printf '  OAuth2      : %s\n' "$oauth_label"
  printf '  DNS         : %s\n' "$dns_label"
}

_menu_load_app_record() {
  local app_name="$1"
  local env_file="${MENU_INSTALLED_DIR}/${app_name}.env"
  local line

  MENU_APP_TEMPLATE=""
  MENU_APP_INSTANCE="$app_name"
  MENU_APP_HOST=""
  MENU_APP_SUBDOMAIN=""
  MENU_APP_PORT=""
  MENU_APP_DOCKER_SERVICE=""
  MENU_APP_PROTECTED="true"
  MENU_APP_LOCAL_ONLY="false"
  MENU_APP_DISABLED="false"
  MENU_APP_DIR="${BASE_DIR}/apps/${app_name}"
  MENU_APP_DATA="${BASE_DIR}/data/${app_name}"

  [ -f "$env_file" ] || return 1

  line=$(
    APP_NAME=""
    APP_INSTANCE=""
    APP_HOST=""
    APP_SUBDOMAIN=""
    APP_PORT=""
    APP_PROTECTED=""
    APP_AUTH=""
    APP_LOCAL_ONLY=""
    APP_DISABLED=""
    APP_DIR=""
    APP_DATA=""
    source "$env_file" >/dev/null 2>&1
    printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
      "${APP_NAME:-${app_name}}" \
      "${APP_INSTANCE:-${app_name}}" \
      "${APP_HOST:-}" \
      "${APP_SUBDOMAIN:-}" \
      "${APP_PORT:-}" \
      "${APP_DOCKER_SERVICE:-}" \
      "${APP_PROTECTED:-${APP_AUTH:-true}}" \
      "${APP_LOCAL_ONLY:-false}" \
      "${APP_DISABLED:-false}" \
      "${APP_DIR:-${BASE_DIR}/apps/${app_name}}" \
      "${APP_DATA:-${BASE_DIR}/data/${app_name}}"
  )

  IFS='|' read -r MENU_APP_TEMPLATE MENU_APP_INSTANCE MENU_APP_HOST MENU_APP_SUBDOMAIN MENU_APP_PORT MENU_APP_DOCKER_SERVICE MENU_APP_PROTECTED MENU_APP_LOCAL_ONLY MENU_APP_DISABLED MENU_APP_DIR MENU_APP_DATA <<< "$line"

  if [ -z "$MENU_APP_DOCKER_SERVICE" ] && [ -f "${MENU_APP_TEMPLATE_DIR}/${MENU_APP_TEMPLATE}/app.env" ]; then
    MENU_APP_DOCKER_SERVICE="$({ APP_DOCKER_SERVICE=""; source "${MENU_APP_TEMPLATE_DIR}/${MENU_APP_TEMPLATE}/app.env" >/dev/null 2>&1; printf '%s' "${APP_DOCKER_SERVICE:-}"; })"
  fi
}

_menu_app_access_label() {
  if [ "$MENU_APP_LOCAL_ONLY" = true ]; then
    printf '%s' "local-only"
  elif [ "$MENU_APP_DISABLED" = true ]; then
    printf '%s' "disabled"
  elif [ -n "$MENU_APP_HOST" ]; then
    printf '%s' "$MENU_APP_HOST"
  else
    printf '%s' "not-exposed"
  fi
}

_menu_apps_running_count() {
  local count=0
  local app_name

  for app_name in "${MENU_INSTALLED_APPS[@]}"; do
    _menu_load_app_record "$app_name"
    if [ "$(_menu_app_running_count "$app_name")" -gt 0 ]; then
      count=$((count + 1))
    fi
  done

  printf '%s' "$count"
}

_menu_app_state_info() {
  local app_name="$1"

  _menu_load_app_record "$app_name" || {
    printf 'unknown|0|0||||\n'
    return 0
  }

  ksf_stack_state_info "$MENU_APP_DIR" "$MENU_APP_DOCKER_SERVICE"
}

_menu_app_state_label() {
  local app_name="$1"
  local state_info stack_state running_count total_count primary_service primary_name primary_state primary_health

  state_info="$(_menu_app_state_info "$app_name")"
  IFS='|' read -r stack_state running_count total_count primary_service primary_name primary_state primary_health <<< "$state_info"
  ksf_stack_state_label "$stack_state"
}

_menu_app_running_count() {
  local app_name="$1"
  local state_info stack_state running_count total_count primary_service primary_name primary_state primary_health

  state_info="$(_menu_app_state_info "$app_name")"
  IFS='|' read -r stack_state running_count total_count primary_service primary_name primary_state primary_health <<< "$state_info"
  printf '%s' "$running_count"
}

_menu_header() {
  _menu_refresh_context
  _menu_collect_installed_apps

  local installed_count="${#MENU_INSTALLED_APPS[@]}"
  local running_count=0
  local stopped_count=0
  local docker_label="indisponible"

  if [ "$MENU_DOCKER_AVAILABLE" = true ]; then
    docker_label="OK"
    running_count=$(_menu_apps_running_count)
    stopped_count=$((installed_count - running_count))
  else
    stopped_count="$installed_count"
  fi

  echo ""
  echo "============================================================"
  echo " KSF - Menu serveur"
  echo "============================================================"
  printf ' Base dir     : %s\n' "$BASE_DIR"
  if [ "$MENU_INSTALLATION_PRESENT" = true ]; then
    printf ' Installation : oui'
    [ -n "$MENU_DOMAIN" ] && printf ' (%s)' "$MENU_DOMAIN"
    printf '\n'
  else
    printf ' Installation : non detectee\n'
  fi
  printf ' Docker       : %s\n' "$docker_label"
  printf ' Infra        : Traefik=%s | OAuth2=%s | CrowdSec=%s\n' \
    "$(_menu_service_state traefik)" \
    "$(_menu_service_state oauth2)" \
    "$(_menu_service_state crowdsec)"
  if [ "$MENU_DOCKER_AVAILABLE" = true ]; then
    printf ' Apps         : %s installee(s), %s active(s), %s inactive(s)\n' "$installed_count" "$running_count" "$stopped_count"
  else
    printf ' Apps         : %s installee(s)\n' "$installed_count"
  fi
  echo ""
}

_menu_installation_required() {
  _menu_refresh_context
  if [ "$MENU_INSTALLATION_PRESENT" = true ]; then
    return 0
  fi

  err "Aucune installation KSF detectee dans ${BASE_DIR}."
  err "Lance d'abord ./deploy.sh ou precise --base-dir vers une installation existante."
  return 1
}

_menu_print_installed_apps() {
  _menu_refresh_context
  _menu_collect_installed_apps

  if [ "${#MENU_INSTALLED_APPS[@]}" -eq 0 ]; then
    warn "Aucune app installee."
    return 0
  fi

  echo "Apps installees :"
  echo "  Instance      | Etat          | Acces              | OAuth2"
  local app_name state_info stack_state running_count total_count primary_service primary_name primary_state primary_health
  for app_name in "${MENU_INSTALLED_APPS[@]}"; do
    _menu_load_app_record "$app_name"
    state_info="$(_menu_app_state_info "$app_name")"
    IFS='|' read -r stack_state running_count total_count primary_service primary_name primary_state primary_health <<< "$state_info"
    printf '  %s\n' "$(printf '%-13s | %-13s | %-18s | %s' "$(_menu_app_display_name)" "$(ksf_stack_state_label "$stack_state")" "$(_menu_app_access_label)" "$(_menu_app_oauth_label)")"
  done
}

_menu_pick_installed_app() {
  _menu_refresh_context
  _menu_collect_installed_apps
  MENU_SELECTED_APP=""

  if [ "${#MENU_INSTALLED_APPS[@]}" -eq 0 ]; then
    err "Aucune app installee."
    return 1
  fi

  echo ""
  echo "Apps installees :"
  echo "  # | Instance      | Etat          | Acces              | OAuth2"
  local i=1 app_name
  for app_name in "${MENU_INSTALLED_APPS[@]}"; do
    _menu_load_app_record "$app_name"
    printf '  %s\n' "$(printf '%-2s | %-13s | %-13s | %-18s | %s' "$i" "$(_menu_app_display_name)" "$(_menu_app_state_label "$app_name")" "$(_menu_app_access_label)" "$(_menu_app_oauth_label)")"
    i=$((i + 1))
  done
  echo ""

  local num
  read -rp "Numero de l'app (0 pour annuler) : " num
  if [ "$num" = "0" ] || [ -z "$num" ]; then
    return 1
  fi
  if ! [[ "$num" =~ ^[0-9]+$ ]] || [ "$num" -lt 1 ] || [ "$num" -gt "${#MENU_INSTALLED_APPS[@]}" ]; then
    err "Choix invalide."
    return 1
  fi

  MENU_SELECTED_APP="${MENU_INSTALLED_APPS[$((num - 1))]}"
  return 0
}

_menu_pick_available_template() {
  _menu_collect_available_templates
  MENU_SELECTED_TEMPLATE=""

  if [ "${#MENU_AVAILABLE_TEMPLATES[@]}" -eq 0 ]; then
    err "Aucun template d'app disponible."
    return 1
  fi

  echo ""
  echo "Templates d'apps disponibles :"
  local i=1 template_name
  for template_name in "${MENU_AVAILABLE_TEMPLATES[@]}"; do
    printf '  %s) %s - %s\n' "$i" "$template_name" "$(_menu_template_description "$template_name")"
    i=$((i + 1))
  done
  echo ""

  local num
  read -rp "Numero du template (0 pour annuler) : " num
  if [ "$num" = "0" ] || [ -z "$num" ]; then
    return 1
  fi
  if ! [[ "$num" =~ ^[0-9]+$ ]] || [ "$num" -lt 1 ] || [ "$num" -gt "${#MENU_AVAILABLE_TEMPLATES[@]}" ]; then
    err "Choix invalide."
    return 1
  fi

  MENU_SELECTED_TEMPLATE="${MENU_AVAILABLE_TEMPLATES[$((num - 1))]}"
  return 0
}

_menu_install_app_assistant() {
  local template_name
  local instance_name
  local app_instance
  local access_mode
  local domain
  local default_domain
  local allowed_domains
  local -a allowed_domain_items
  local allowed_domain_count=0
  local subdomain
  local default_subdomain
  local host
  local auth_choice
  local action_label
  local access_label
  local oauth_label
  local dns_label
  local existing_template
  local template_default_protected
  local template_public
  local force_reinstall=false
  local -a args

  if ! _menu_installation_required; then
    return 1
  fi
  if ! _menu_pick_available_template; then
    return 1
  fi

  template_name="$MENU_SELECTED_TEMPLATE"
  app_instance="$template_name"
  default_subdomain="$(_menu_template_value "$template_name" APP_DEFAULT_HOST)"
  template_default_protected="$(_menu_template_value "$template_name" APP_PROTECTED)"
  template_public="$(_menu_template_value "$template_name" APP_PUBLIC)"
  args=()

  echo ""
  read -rp "Nom d'instance (optionnel, vide = template) : " instance_name
  if [ -n "$instance_name" ]; then
    app_instance="$instance_name"
  fi

  existing_template="$(_menu_existing_instance_template "$app_instance")"
  if [ -n "$existing_template" ] && [ "$existing_template" != "$template_name" ]; then
    err "L'instance ${app_instance} existe deja avec le template ${existing_template}."
    err "Choisis un autre nom d'instance ou supprime l'app existante d'abord."
    return 1
  fi
  if [ -n "$existing_template" ]; then
    action_label="reinstaller"
    force_reinstall=true
  else
    action_label="installer"
  fi

  args+=("--instance" "$app_instance")

  if [ "$template_public" != true ] || [ "$MENU_WITH_TRAEFIK" != true ]; then
    access_mode="local-only"
    if [ "$MENU_WITH_TRAEFIK" != true ]; then
      info "Traefik n'est pas configure: installation en mode local-only."
    else
      info "Le template ${template_name} n'est pas expose publiquement: installation en mode local-only."
    fi
  else
    allowed_domains="$(_menu_allowed_domains)"
    default_domain="$(_menu_default_domain)"
    if [ -z "$allowed_domains" ] || [ -z "$default_domain" ]; then
      err "Aucun domaine applicatif autorise. Configure DOMAIN ou DOMAINS dans ksf.env."
      return 1
    fi
    IFS=',' read -r -a allowed_domain_items <<< "$allowed_domains"
    allowed_domain_count="${#allowed_domain_items[@]}"

    echo ""
    echo "Mode d'acces :"
    printf '  1) Sous-domaine sur %s\n' "$default_domain"
    if [ "$allowed_domain_count" -gt 1 ]; then
      echo "  2) Sous-domaine sur un autre domaine"
      echo "  3) Host complet"
      echo "  4) Local-only"
      echo ""
      read -rp "Choix [1-4] : " access_mode
    else
      echo "  2) Host complet"
      echo "  3) Local-only"
      echo ""
      read -rp "Choix [1-3] : " access_mode
    fi
  fi

  case "$access_mode" in
    1|"")
      domain="$default_domain"
      echo ""
      read -rp "Sous-domaine [${default_subdomain}] : " subdomain
      subdomain="${subdomain:-${default_subdomain}}"
      host="${subdomain}.${domain}"
      args+=("--domain" "$domain" "--subdomain" "$subdomain")
      access_label="https://${host}"
      ;;
    2)
      if [ "$allowed_domain_count" -gt 1 ]; then
        echo ""
        echo "Domaines autorises : ${allowed_domains}"
        read -rp "Domaine [${default_domain}] : " domain
        domain="${domain:-${default_domain}}"
        if ! _menu_domain_allowed "$domain"; then
          err "Domaine non autorise : ${domain}."
          return 1
        fi
        read -rp "Sous-domaine [${default_subdomain}] : " subdomain
        subdomain="${subdomain:-${default_subdomain}}"
        host="${subdomain}.${domain}"
        args+=("--domain" "$domain" "--subdomain" "$subdomain")
        access_label="https://${host}"
      else
        echo ""
        read -rp "Host complet (ex: app.example.com) : " host
        if [ -z "$host" ]; then
          err "Host requis."
          return 1
        fi
        args+=("--host" "$host")
        access_label="https://${host}"
      fi
      ;;
    3)
      if [ "$allowed_domain_count" -gt 1 ]; then
        echo ""
        read -rp "Host complet (ex: app.example.com) : " host
        if [ -z "$host" ]; then
          err "Host requis."
          return 1
        fi
        args+=("--host" "$host")
        access_label="https://${host}"
      else
        args+=("--local-only")
        access_label="local-only"
      fi
      ;;
    4)
      if [ "$allowed_domain_count" -gt 1 ]; then
        args+=("--local-only")
        access_label="local-only"
      else
        err "Choix invalide."
        return 1
      fi
      ;;
    *)
      err "Choix invalide."
      return 1
      ;;
  esac

  if [ "$access_label" != "local-only" ] && [ "$MENU_WITH_OAUTH2" = true ]; then
    echo ""
    echo "Protection OAuth2 Proxy :"
    echo "  1) Oui (recommande)"
    echo "  2) Non"
    echo ""
    if [ "$template_default_protected" = true ]; then
      read -rp "Choix [1-2, defaut 1] : " auth_choice
    else
      read -rp "Choix [1-2, defaut 2] : " auth_choice
    fi
    case "$auth_choice" in
      1) args+=("--auth"); oauth_label="oui" ;;
      2) args+=("--no-auth"); oauth_label="non" ;;
      "")
        if [ "$template_default_protected" = true ]; then
          args+=("--auth")
          oauth_label="oui"
        else
          args+=("--no-auth")
          oauth_label="non"
        fi
        ;;
      *) err "Choix invalide."; return 1 ;;
    esac
  elif [ "$access_label" != "local-only" ]; then
    args+=("--no-auth")
    oauth_label="non (OAuth2 non configure)"
  else
    oauth_label="n/a (local-only)"
  fi

  if [ "$access_label" != "local-only" ]; then
    if [ "${DNS_AUTO_CREATE:-false}" = true ]; then
      dns_label="mise a jour automatique"
    else
      dns_label="desactive"
    fi
  else
    dns_label="n/a (local-only)"
  fi

  _menu_install_summary "$action_label" "$template_name" "$app_instance" "$access_label" "$oauth_label" "$dns_label"

  args+=("--yes")

  if _menu_confirm "${action_label^} ${app_instance} ?"; then
    MENU_APP_INSTALL_FORCE="$force_reinstall"
    _menu_app install "$template_name" "${args[@]}"
    MENU_APP_INSTALL_FORCE=false
  fi
}

_menu_stack_logs() {
  local stack_dir="$1"
  local service_name="$2"

  if [ ! -f "${stack_dir}/docker-compose.yml" ]; then
    warn "Stack absente : ${stack_dir}/docker-compose.yml"
    return 0
  fi

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${stack_dir} && docker compose logs --tail=200 ${service_name}"
    return 0
  fi

  (cd "$stack_dir" && docker compose logs --tail=200 "$service_name") || warn "Impossible de lire les logs ${service_name}."
}

_menu_stack_status() {
  local stack_dir="$1"

  if [ ! -f "${stack_dir}/docker-compose.yml" ]; then
    warn "Stack absente : ${stack_dir}/docker-compose.yml"
    return 0
  fi

  (cd "$stack_dir" && docker compose ps) || warn "Impossible de lire l'etat Compose de ${stack_dir}."
}

_menu_stack_restart() {
  local stack_dir="$1"
  local label="$2"

  if [ ! -f "${stack_dir}/docker-compose.yml" ]; then
    warn "Stack absente : ${stack_dir}/docker-compose.yml"
    return 0
  fi

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${stack_dir} && docker compose restart"
    return 0
  fi

  info "Redemarrage de ${label}..."
  (cd "$stack_dir" && docker compose restart) || warn "Echec du redemarrage de ${label}."
}

_menu_show_service_status() {
  local service="$1"

  case "$service" in
    traefik)
      _menu_stack_status "$MENU_TRAEFIK_DIR"
      ;;
    oauth2)
      _menu_stack_status "$MENU_OAUTH2_DIR"
      ;;
    crowdsec)
      _menu_ksf crowdsec status
      ;;
  esac
}

_menu_show_service_logs() {
  local service="$1"

  case "$service" in
    traefik)
      _menu_stack_logs "$MENU_TRAEFIK_DIR" "traefik"
      ;;
    oauth2)
      _menu_stack_logs "$MENU_OAUTH2_DIR" "oauth2-proxy"
      ;;
    crowdsec)
      _menu_ksf crowdsec logs
      ;;
  esac
}

_menu_restart_service() {
  local service="$1"

  case "$service" in
    traefik)
      _menu_stack_restart "$MENU_TRAEFIK_DIR" "Traefik"
      ;;
    oauth2)
      _menu_stack_restart "$MENU_OAUTH2_DIR" "OAuth2 Proxy"
      ;;
    crowdsec)
      _menu_ksf crowdsec restart
      ;;
  esac
}

_menu_update_service() {
  local service="$1"
  case "$service" in
    traefik|oauth2|crowdsec)
      _menu_ksf update "$service"
      ;;
  esac
}

_menu_overview() {
  while true; do
    local action_ran=false
    _menu_header
    echo "=== Vue d'ensemble ==="
    echo ""
    echo "  1) Status complet"
    echo "  2) Doctor"
    echo "  3) Routes"
    echo "  4) Configuration"
    echo "  5) Redemarrer l'infrastructure"
    echo "  6) Retour"
    echo ""

    local choice
    read -rp "Choix [1-6] : " choice
    case "$choice" in
      1) _menu_ksf status; action_ran=true ;;
      2) _menu_ksf doctor; action_ran=true ;;
      3) _menu_ksf routes; action_ran=true ;;
      4) _menu_ksf config; action_ran=true ;;
      5)
        if _menu_confirm "Redemarrer Traefik, OAuth2 Proxy et CrowdSec si presents ?"; then
          _menu_ksf restart
          action_ran=true
        fi
        ;;
      6) return ;;
      *) err "Choix invalide." ;;
    esac
    [ "$action_ran" = true ] && _menu_pause
  done
}

_menu_app_details() {
  local app_name="$1"
  local state_info stack_state running_count total_count primary_service primary_name primary_state primary_health
  local start_stop_label

  while true; do
    local action_ran=false
    _menu_header
    _menu_load_app_record "$app_name" || {
      err "Impossible de charger ${app_name}."
      _menu_pause
      return 1
    }

    state_info="$(_menu_app_state_info "$app_name")"
    IFS='|' read -r stack_state running_count total_count primary_service primary_name primary_state primary_health <<< "$state_info"
    if [ "$running_count" -gt 0 ]; then
      start_stop_label="Arreter"
    else
      start_stop_label="Demarrer"
    fi

    echo "=== App ${app_name} ==="
    printf 'Instance    : %s\n' "$MENU_APP_INSTANCE"
    printf 'Template    : %s\n' "$MENU_APP_TEMPLATE"
    printf 'Acces       : %s\n' "$(_menu_app_access_label)"
    printf 'OAuth2      : %s\n' "$(_menu_app_oauth_label)"
    printf 'Etat        : %s (%s/%s service(s) running)\n' "$(ksf_stack_state_label "$stack_state")" "$running_count" "$total_count"
    if [ -n "$primary_name" ]; then
      printf 'Service cle : %s -> %s (%s%s)\n' "$primary_service" "$primary_name" "$primary_state" "${primary_health:+, ${primary_health}}"
    fi
    printf 'Stack       : %s\n' "$MENU_APP_DIR"
    printf 'Donnees     : %s\n' "$MENU_APP_DATA"
    echo ""
    echo "  1) Status detaille"
    printf '  2) %s\n' "$start_stop_label"
    echo "  3) Redemarrer"
    echo "  4) Logs"
    echo "  5) Mettre a jour"
    echo "  6) Modifier domaine / sous-domaine"
    echo "  7) Rebuild"
    echo "  8) Desactiver"
    echo "  9) Supprimer"
    echo " 10) Retour"
    echo ""

    local choice
    read -rp "Choix [1-10] : " choice
    case "$choice" in
      1)
        _menu_app status "$app_name"
        action_ran=true
        ;;
      2)
        if [ "$start_stop_label" = "Arreter" ]; then
          _menu_app stop "$app_name"
        else
          _menu_app start "$app_name"
        fi
        action_ran=true
        ;;
      3)
        _menu_app restart "$app_name"
        action_ran=true
        ;;
      4)
        _menu_app logs "$app_name"
        action_ran=true
        ;;
      5)
        _menu_app update "$app_name"
        action_ran=true
        ;;
      6)
        _menu_app configure "$app_name"
        action_ran=true
        ;;
      7)
        _menu_app rebuild "$app_name"
        action_ran=true
        ;;
      8)
        if _menu_confirm "Desactiver ${app_name} ?"; then
          _menu_app disable "$app_name"
          action_ran=true
        fi
        ;;
      9)
        if _menu_confirm "Supprimer ${app_name} ? Les donnees seront conservees."; then
          _menu_app remove "$app_name"
          return 0
        fi
        ;;
      10)
        return 0
        ;;
      *) err "Choix invalide." ;;
    esac
    [ "$action_ran" = true ] && _menu_pause
  done
}

_menu_apps() {
  while true; do
    local action_ran=false
    _menu_header
    echo "=== Applications ==="
    echo ""
    _menu_print_installed_apps
    echo ""
    echo "  1) Installer une app depuis un template"
    echo "  2) Gerer une app installee"
    echo "  3) Supprimer une app"
    echo "  4) Voir le catalogue des templates"
    echo "  5) Relister les apps installees"
    echo "  6) Retour"
    echo ""

    local choice
    read -rp "Choix [1-6] : " choice
    case "$choice" in
      1)
        _menu_install_app_assistant
        ;;
      2)
        if _menu_pick_installed_app; then
          _menu_app_details "$MENU_SELECTED_APP"
        fi
        ;;
      3)
        _menu_remove_app_assistant && action_ran=true
        ;;
      4)
        echo ""
        _menu_print_available_templates
        action_ran=true
        ;;
      5)
        echo ""
        _menu_print_installed_apps
        action_ran=true
        ;;
      6)
        return
        ;;
      *) err "Choix invalide." ;;
    esac
    [ "$action_ran" = true ] && _menu_pause
  done
}

_menu_service_menu() {
  local service="$1"
  local label

  label="$(_menu_service_label "$service")"

  while true; do
    local action_ran=false
    _menu_header
    echo "=== ${label} ==="
    printf 'Etat : %s\n' "$(_menu_service_state "$service")"
    if [ "$service" = "crowdsec" ] && [ "$MENU_WITH_APPSEC" = true ]; then
      echo "AppSec : actif"
    fi
    echo ""
    echo "  1) Status"
    echo "  2) Logs"
    echo "  3) Redemarrer"
    echo "  4) Update"
    echo "  5) Retour"
    echo ""

    local choice
    read -rp "Choix [1-5] : " choice
    case "$choice" in
      1) _menu_show_service_status "$service"; action_ran=true ;;
      2) _menu_show_service_logs "$service"; action_ran=true ;;
      3)
        _menu_restart_service "$service"
        action_ran=true
        ;;
      4)
        _menu_update_service "$service"
        action_ran=true
        ;;
      5) return ;;
      *) err "Choix invalide." ;;
    esac
    [ "$action_ran" = true ] && _menu_pause
  done
}

_menu_infrastructure() {
  while true; do
    _menu_header
    echo "=== Infrastructure ==="
    echo ""

    local choices=()
    local index=1

    if _menu_service_enabled traefik; then
      printf '  %s) Traefik [%s]\n' "$index" "$(_menu_service_state traefik)"
      choices[$index]="traefik"
      index=$((index + 1))
    fi
    if _menu_service_enabled oauth2; then
      printf '  %s) OAuth2 Proxy [%s]\n' "$index" "$(_menu_service_state oauth2)"
      choices[$index]="oauth2"
      index=$((index + 1))
    fi
    if _menu_service_enabled crowdsec; then
      printf '  %s) CrowdSec [%s]\n' "$index" "$(_menu_service_state crowdsec)"
      choices[$index]="crowdsec"
      index=$((index + 1))
    fi

    local render_index="$index"
    local restart_index=$((index + 1))
    local back_index=$((index + 2))

    printf '  %s) Regenerer les routes (render)\n' "$render_index"
    printf "  %s) Redemarrer toute l'infrastructure\n" "$restart_index"
    printf '  %s) Retour\n' "$back_index"
    echo ""

    local choice
    read -rp "Choix : " choice

    if [ "$choice" = "$render_index" ]; then
      _menu_ksf render
      _menu_pause
      continue
    fi
    if [ "$choice" = "$restart_index" ]; then
      if _menu_confirm "Redemarrer toute l'infrastructure ?"; then
        _menu_ksf restart
        _menu_pause
      fi
      continue
    fi
    if [ "$choice" = "$back_index" ]; then
      return
    fi

    if [[ "$choice" =~ ^[0-9]+$ ]] && [ -n "${choices[$choice]:-}" ]; then
      _menu_service_menu "${choices[$choice]}"
    else
      err "Choix invalide."
    fi
  done
}

_menu_security() {
  while true; do
    local action_ran=false
    _menu_header
    echo "=== Securite ==="
    echo ""
    if [ "$MENU_WITH_CROWDSEC" != true ]; then
      warn "CrowdSec n'est pas active dans cette installation."
    fi
    echo "  1) Alerts CrowdSec"
    echo "  2) Metrics CrowdSec"
    echo "  3) Bouncers CrowdSec"
    echo "  4) Status AppSec / WAF"
    echo "  5) Trusted IPs Cloudflare"
    echo "  6) Appliquer trusted IPs Cloudflare"
    echo "  7) Retour"
    echo ""

    local choice
    read -rp "Choix [1-7] : " choice
    case "$choice" in
      1) _menu_ksf crowdsec alerts; action_ran=true ;;
      2) _menu_ksf crowdsec metrics; action_ran=true ;;
      3) _menu_ksf crowdsec bouncers; action_ran=true ;;
      4) _menu_ksf crowdsec appsec status; action_ran=true ;;
      5) _menu_ksf trusted-ips cloudflare; action_ran=true ;;
      6)
        if _menu_confirm "Appliquer les CIDR Cloudflare dans ksf.env et redemarrer Traefik ?"; then
          _menu_ksf trusted-ips apply cloudflare
          action_ran=true
        fi
        ;;
      7) return ;;
      *) err "Choix invalide." ;;
    esac
    [ "$action_ran" = true ] && _menu_pause
  done
}

_menu_logs() {
  while true; do
    local action_ran=false
    _menu_header
    echo "=== Logs ==="
    echo ""
    echo "  1) Logs Traefik"
    echo "  2) Logs OAuth2 Proxy"
    echo "  3) Logs CrowdSec"
    echo "  4) Logs d'une app installee"
    echo "  5) Retour"
    echo ""

    local choice
    read -rp "Choix [1-5] : " choice
    case "$choice" in
      1) _menu_show_service_logs traefik; action_ran=true ;;
      2) _menu_show_service_logs oauth2; action_ran=true ;;
      3) _menu_show_service_logs crowdsec; action_ran=true ;;
      4)
        if _menu_pick_installed_app; then
          _menu_app logs "$MENU_SELECTED_APP"
          action_ran=true
        fi
        ;;
      5) return ;;
      *) err "Choix invalide." ;;
    esac
    [ "$action_ran" = true ] && _menu_pause
  done
}

_menu_maintenance() {
  while true; do
    local action_ran=false
    _menu_header
    echo "=== Maintenance ==="
    echo ""
    echo "  1) Lister les dossiers data"
    echo "  2) Nettoyer les donnees d'une app"
    echo "  3) Installer / reparer la commande globale ksf"
    echo "  4) Desinstaller la commande globale ksf"
    echo "  5) Verifier la commande globale ksf"
    echo "  6) Retour"
    echo ""

    local choice
    read -rp "Choix [1-6] : " choice
    case "$choice" in
      1)
        _menu_ksf clean-data
        action_ran=true
        ;;
      2)
        if _menu_pick_installed_app; then
          if _menu_confirm "Supprimer les donnees de ${MENU_SELECTED_APP} ?"; then
            _menu_ksf clean-data "$MENU_SELECTED_APP"
            action_ran=true
          fi
        fi
        ;;
      3)
        _menu_ksf install-cli
        action_ran=true
        ;;
      4)
        if _menu_confirm "Desinstaller la commande globale ksf ?"; then
          _menu_ksf uninstall-cli
          action_ran=true
        fi
        ;;
      5)
        action_ran=true
        echo ""
        echo "=== Verification de la commande ksf ==="
        echo ""
        local link_path="${HOME}/.local/bin/ksf"
        local bin_dir
        bin_dir="$(dirname "$link_path")"

        if [ -L "$link_path" ]; then
          local link_target
          link_target="$(readlink -f "$link_path" 2>/dev/null || true)"
          ok "Lien present   : ${link_path}"
          info "Cible du lien  : ${link_target}"
          if [ -x "$link_target" ] || [ -x "$link_path" ]; then
            ok "Executable     : oui"
          else
            warn "Executable     : non"
          fi
        elif [ -e "$link_path" ]; then
          warn "Lien present   : ${link_path} (pas un lien symbolique)"
        else
          warn "Lien absent    : ${link_path}"
        fi

        echo ""
        if _menu_cli_path_contains "$bin_dir" 2>/dev/null; then
          ok "~/.local/bin dans PATH actuel : oui"
        else
          warn "~/.local/bin dans PATH actuel : non"
        fi

        if [ -f "${HOME}/.profile" ] && grep -qF "# KSF CLI" "${HOME}/.profile" 2>/dev/null; then
          ok "Bloc KSF dans ~/.profile      : oui"
        else
          warn "Bloc KSF dans ~/.profile      : non"
        fi

        if [ -f "${HOME}/.bashrc" ] && grep -qF "# KSF CLI" "${HOME}/.bashrc" 2>/dev/null; then
          ok "Bloc KSF dans ~/.bashrc       : oui"
        else
          warn "Bloc KSF dans ~/.bashrc       : non"
        fi

        echo ""
        if command -v ksf >/dev/null 2>&1; then
          ok "command -v ksf -> $(command -v ksf)"
          if ksf --help >/dev/null 2>&1; then
            ok "Execution reelle de ksf       : OK"
          else
            warn "Execution reelle de ksf       : echec"
            echo "  Lance : ./ksf.sh install-cli"
          fi
        else
          warn "command -v ksf -> introuvable"
          echo "  Apres installation, reconnecte-toi en SSH ou lance :"
          echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
        ;;
      6)
        return
        ;;
      *) err "Choix invalide." ;;
    esac
    [ "$action_ran" = true ] && _menu_pause
  done
}

menu_main() {
  while true; do
    _menu_header
    echo "  1) Vue d'ensemble"
    echo "  2) Applications"
    echo "  3) Infrastructure"
    echo "  4) Securite"
    echo "  5) Logs"
    echo "  6) Maintenance"
    echo "  7) Quitter"
    echo ""

    local choice
    read -rp "Choix [1-7] : " choice
    case "$choice" in
      1) _menu_overview ;;
      2) _menu_apps ;;
      3) _menu_infrastructure ;;
      4) _menu_security ;;
      5) _menu_logs ;;
      6) _menu_maintenance ;;
      7) echo "Au revoir !"; exit 0 ;;
      *) err "Choix invalide." ;;
    esac
  done
}
