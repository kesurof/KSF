# ============================================================
# KSF — Étapes update système
# ============================================================

# ---------- Update système ----------

manage_update_usage_error() {
  local service="${1:-}"
  if [ -n "$service" ]; then
    err "Service update inconnu : ${service}"
  fi
  err "Valeurs acceptées : crowdsec, traefik, oauth2, all"
  err "Usage : ./ksf.sh update <crowdsec|traefik|oauth2|all>"
  exit 1
}

manage_update_require_docker() {
  if [ "${DRY_RUN:-false}" = true ]; then
    return 0
  fi
  if ! command -v docker >/dev/null 2>&1; then
    err "Docker n'est pas installé ou inaccessible."
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    err "Docker Compose n'est pas disponible."
    exit 1
  fi
}

manage_update_resolve_service() {
  local service="$1"

  case "$service" in
    crowdsec)
      UPDATE_SERVICE_ID="crowdsec"
      UPDATE_SERVICE_LABEL="CrowdSec"
      UPDATE_COMPOSE_DIR="${CROWDSEC_DIR}"
      UPDATE_COMPOSE_FILE="${CROWDSEC_DIR}/docker-compose.yml"
      UPDATE_COMPOSE_SERVICE="crowdsec"
      UPDATE_CONTAINER="crowdsec"
      ;;
    traefik)
      UPDATE_SERVICE_ID="traefik"
      UPDATE_SERVICE_LABEL="Traefik"
      UPDATE_COMPOSE_DIR="${TRAEFIK_DIR}"
      UPDATE_COMPOSE_FILE="${TRAEFIK_DIR}/docker-compose.yml"
      UPDATE_COMPOSE_SERVICE="traefik"
      UPDATE_CONTAINER="traefik"
      ;;
    oauth2)
      UPDATE_SERVICE_ID="oauth2"
      UPDATE_SERVICE_LABEL="OAuth2 Proxy"
      UPDATE_COMPOSE_DIR="${OAUTH2_DIR}"
      UPDATE_COMPOSE_FILE="${OAUTH2_DIR}/docker-compose.yml"
      UPDATE_COMPOSE_SERVICE="oauth2-proxy"
      UPDATE_CONTAINER="oauth2-proxy"
      ;;
    *)
      manage_update_usage_error "$service"
      ;;
  esac
}

manage_update_service_present() {
  local service="$1"
  case "$service" in
    crowdsec) [ "${WITH_CROWDSEC:-false}" = true ] && [ -f "${CROWDSEC_DIR}/docker-compose.yml" ] ;;
    traefik) [ "${WITH_TRAEFIK:-false}" = true ] && [ -f "${TRAEFIK_DIR}/docker-compose.yml" ] ;;
    oauth2) [ "${OAUTH2_ENABLED:-false}" = true ] && [ -f "${OAUTH2_DIR}/docker-compose.yml" ] ;;
    *) return 1 ;;
  esac
}

manage_update_require_service() {
  local service="$1"
  manage_update_resolve_service "$service"
  if ! manage_update_service_present "$service"; then
    err "Stack ${UPDATE_SERVICE_LABEL} absente ou non activée : ${UPDATE_COMPOSE_FILE}"
    err "Services acceptés : crowdsec, traefik, oauth2, all"
    exit 1
  fi
}

manage_update_target_image() {
  local compose_file="$1"
  local compose_service="$2"

  awk -v service="${compose_service}" '
    $0 ~ "^[[:space:]]{2}" service ":[[:space:]]*$" { in_service=1; next }
    in_service && $0 ~ "^[[:space:]]{2}[A-Za-z0-9_-]+:[[:space:]]*$" { exit }
    in_service && $1 == "image:" { print $2; exit }
  ' "$compose_file" | tr -d '"' || true
}

manage_update_current_image() {
  local container="$1"

  if ! command -v docker >/dev/null 2>&1; then
    printf 'indisponible'
    return 0
  fi
  docker inspect "$container" --format '{{.Config.Image}}' 2>/dev/null || printf 'indisponible'
}

manage_update_status_line() {
  local container="$1"

  if [ "${DRY_RUN:-false}" = true ]; then
    printf 'prévu (dry-run)'
    return 0
  fi
  if docker inspect "$container" --format '{{.State.Running}}' 2>/dev/null | grep -q '^true$'; then
    printf 'actif'
  else
    printf 'arrêté ou absent'
  fi
}

manage_update_print_summary() {
  local requested="$1"
  shift
  local services=("$@")
  local service target current

  echo "=== Résumé update système KSF ==="
  echo "Service concerné       : ${requested}"
  if [ "${DRY_RUN:-false}" = true ]; then
    echo "Doctor après update    : prévu (dry-run)"
  else
    echo "Doctor après update    : prévu"
  fi
  echo ""
  for service in "${services[@]}"; do
    manage_update_resolve_service "$service"
    target=$(manage_update_target_image "$UPDATE_COMPOSE_FILE" "$UPDATE_COMPOSE_SERVICE")
    current=$(manage_update_current_image "$UPDATE_CONTAINER")
    echo "${UPDATE_SERVICE_LABEL} :"
    echo "  Compose              : ${UPDATE_COMPOSE_FILE}"
    echo "  Image actuelle       : ${current:-indisponible}"
    echo "  Image cible compose  : ${target:-indisponible}"
  done
  echo ""
}

manage_update_confirm() {
  [ "${DRY_RUN:-false}" = true ] && return 0
  [ "${AUTO_YES:-false}" = true ] && return 0

  echo -n "Confirmer la mise à jour ? Tape 'UPDATE' pour continuer : "
  local confirmation
  if ! read -r confirmation || [ "$confirmation" != "UPDATE" ]; then
    err "Update annulé."
    exit 1
  fi
}

manage_update_compose_pull() {
  local dir="$1"

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${dir} && docker compose pull"
    return 0
  fi
  (cd "$dir" && docker compose pull) || {
    err "Échec docker compose pull : ${dir}"
    exit 1
  }
}

manage_update_compose_up() {
  local dir="$1"

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${dir} && docker compose up -d --force-recreate"
    return 0
  fi
  info "Recréation du conteneur pour appliquer la configuration..."
  (cd "$dir" && docker compose up -d --force-recreate) || {
    err "Échec docker compose up -d --force-recreate : ${dir}"
    exit 1
  }
}

manage_update_verify_container() {
  local container="$1"

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Vérification conteneur actif : ${container}"
    return 0
  fi
  if docker inspect "$container" --format '{{.State.Running}}' 2>/dev/null | grep -q '^true$'; then
    ok "Conteneur actif : ${container}"
    return 0
  fi
  err "Conteneur arrêté ou absent après update : ${container}"
  exit 1
}

manage_update_check_appsec_if_needed() {
  if [ "${CROWDSEC_APPSEC_ENABLED:-false}" != true ]; then
    return 0
  fi
  info "Vérification AppSec / WAF après update..."
  manage_crowdsec_appsec_status
}

manage_update_one_service() {
  local service="$1"

  manage_update_require_service "$service"
  if [ "${DRY_RUN:-false}" = true ]; then
    info "Pull ${UPDATE_SERVICE_LABEL} prévu (dry-run)..."
  else
    info "Pull ${UPDATE_SERVICE_LABEL}..."
  fi
  manage_update_compose_pull "$UPDATE_COMPOSE_DIR"
  [ "${DRY_RUN:-false}" = true ] || UPDATE_PULL_DONE=true

  if [ "${DRY_RUN:-false}" = true ]; then
    info "Recréation ${UPDATE_SERVICE_LABEL} prévue (dry-run)..."
  else
    info "Recréation ${UPDATE_SERVICE_LABEL}..."
  fi
  manage_update_compose_up "$UPDATE_COMPOSE_DIR"
  [ "${DRY_RUN:-false}" = true ] || UPDATE_RECREATED_SERVICES+=("${UPDATE_SERVICE_LABEL}")

  if [ "$service" = "crowdsec" ]; then
    manage_wait_crowdsec_ready
  fi
  manage_update_verify_container "$UPDATE_CONTAINER"
  if [ "$service" = "crowdsec" ]; then
    manage_update_check_appsec_if_needed
  fi
}

manage_update_run_doctor() {
  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] ./ksf.sh doctor"
    UPDATE_DOCTOR_STATUS="prévu (dry-run)"
    return 0
  fi

  local output status
  set +e
  output=$(manage_doctor 2>&1)
  status=$?
  set -e
  printf '%s\n' "$output"
  if [ "$status" -ne 0 ]; then
    UPDATE_DOCTOR_STATUS="ERR"
  elif printf '%s\n' "$output" | grep -q 'Diagnostic terminé : aucun problème détecté'; then
    UPDATE_DOCTOR_STATUS="OK"
  else
    UPDATE_DOCTOR_STATUS="WARN"
  fi
}

manage_update_print_final_summary() {
  local services=("$@")
  local service status

  echo ""
  echo "=== Résumé final update KSF ==="
  if [ "${DRY_RUN:-false}" = true ]; then
    echo "Pull                 : prévu (dry-run)"
    echo "Recréation          : prévu (dry-run)"
  else
    echo "Pull                 : $( [ "${UPDATE_PULL_DONE:-false}" = true ] && echo oui || echo non )"
    echo "Recréation          : ${UPDATE_RECREATED_SERVICES[*]:-non}"
  fi
  echo "Statut final         :"
  for service in "${services[@]}"; do
    manage_update_resolve_service "$service"
    status=$(manage_update_status_line "$UPDATE_CONTAINER")
    echo "  ${UPDATE_SERVICE_LABEL}: ${status}"
  done
  echo "Doctor               : ${UPDATE_DOCTOR_STATUS:-non lancé}"
}

manage_update() {
  local requested="${1:-}"
  local services=()
  local service

  [ -n "$requested" ] || manage_update_usage_error
  case "$requested" in
    crowdsec|traefik|oauth2|all) ;;
    *) manage_update_usage_error "$requested" ;;
  esac

  manage_require_installation
  manage_update_require_docker

  case "$requested" in
    crowdsec|traefik|oauth2) services=("$requested") ;;
    all)
      for service in crowdsec traefik oauth2; do
        if manage_update_service_present "$service"; then
          services+=("$service")
        else
          manage_update_resolve_service "$service"
          warn "${UPDATE_SERVICE_LABEL} non activé ou stack absente, ignoré dans update all."
        fi
      done
      ;;
  esac

  if [ "${#services[@]}" -eq 0 ]; then
    err "Aucune stack système disponible pour update."
    exit 1
  fi
  if [ "$requested" != "all" ]; then
    manage_update_require_service "$requested"
  fi

  UPDATE_PULL_DONE=false
  UPDATE_RECREATED_SERVICES=()
  UPDATE_DOCTOR_STATUS=""

  manage_update_print_summary "$requested" "${services[@]}"
  manage_update_confirm

  for service in "${services[@]}"; do
    manage_update_one_service "$service"
  done

  manage_update_run_doctor
  manage_update_print_final_summary "${services[@]}"
}
