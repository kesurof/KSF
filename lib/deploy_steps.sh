# ============================================================
# KSF — Étapes de déploiement infrastructure
# ============================================================

TEMPLATE_DIR="${SCRIPT_DIR}/templates"

step_env() {
  ENV_FILE="${BASE_DIR}/.env"
  info "Génération du fichier ${ENV_FILE}..."
  render_template "${TEMPLATE_DIR}/env/ksf.env" "${ENV_FILE}"
  if [ "${DRY_RUN:-false}" = false ]; then
    chmod 600 "${ENV_FILE}"
  fi
  ok "Fichier .env prêt."
}

step_network() {
  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Vérification/création du réseau Docker : ${NETWORK_NAME}"
    return 0
  fi

  if command -v docker >/dev/null 2>&1; then
    if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
      ok "Réseau Docker déjà présent : ${NETWORK_NAME}"
    else
      info "Création du réseau Docker : ${NETWORK_NAME}"
      run docker network create "${NETWORK_NAME}"
      ok "Réseau Docker créé."
    fi
  fi
}

step_dirs() {
  info "Création de l'arborescence dans ${BASE_DIR}..."
  run mkdir -p \
    "${BASE_DIR}" \
    "${BASE_DIR}/proxy" \
    "${BASE_DIR}/apps" \
    "${BASE_DIR}/data" \
    "${BASE_DIR}/stacks" \
    "${BASE_DIR}/logs" \
    "${BASE_DIR}/config" \
    "${BASE_DIR}/config/installed-apps"
  run chown "${TARGET_USER:-$USER}:${TARGET_USER:-$USER}" "${BASE_DIR}" \
    "${BASE_DIR}/proxy" \
    "${BASE_DIR}/apps" \
    "${BASE_DIR}/data" \
    "${BASE_DIR}/stacks" \
    "${BASE_DIR}/logs" \
    "${BASE_DIR}/config" \
    "${BASE_DIR}/config/installed-apps" 2>/dev/null || true
  run chmod 750 "${BASE_DIR}/logs"
  ok "Arborescence prête."
}

step_traefik() {
  if [ "${WITH_TRAEFIK}" != true ]; then
    return 0
  fi

  TRAEFIK_DIR="${BASE_DIR}/proxy/traefik"
  run mkdir -p "${TRAEFIK_DIR}/dynamic" "${TRAEFIK_DIR}/acme" "${TRAEFIK_DIR}/logs"

  render_template "${TEMPLATE_DIR}/compose/traefik.yml" "${TRAEFIK_DIR}/docker-compose.yml"
  render_traefik_static_template "${TEMPLATE_DIR}" "${TRAEFIK_DIR}/traefik.yml"
  render_template "${TEMPLATE_DIR}/traefik/tls.yml" "${TRAEFIK_DIR}/dynamic/tls.yml"
  if [ "${OAUTH2_ENABLED}" = true ]; then
    render_traefik_route_template "${TEMPLATE_DIR}/traefik/route-traefik-oauth2.yml" "${TRAEFIK_DIR}/dynamic/route-traefik.yml"
  else
    render_traefik_route_template "${TEMPLATE_DIR}/traefik/route-traefik.yml" "${TRAEFIK_DIR}/dynamic/route-traefik.yml"
  fi

  run touch "${TRAEFIK_DIR}/acme/acme.json"
  run chmod 600 "${TRAEFIK_DIR}/acme/acme.json"
  run touch "${TRAEFIK_DIR}/logs/access.log"
  ok "Stack Traefik générée dans ${TRAEFIK_DIR}"
}

write_oauth2_allowed_emails_file() {
  if [ "${OAUTH2_AUTH_MODE}" != "email" ]; then
    return 0
  fi

  local allowed_emails_file="${OAUTH2_DIR}/allowed-emails.txt"
  local email_list="${OAUTH2_ALLOWED_EMAILS},"
  local email

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Génération de ${allowed_emails_file}"
    return 0
  fi

  if [ -d "${allowed_emails_file}" ]; then
    err "${allowed_emails_file} existe comme dossier. Supprime ce dossier ou choisis un autre répertoire de déploiement."
    exit 1
  fi

  chmod 755 "${OAUTH2_DIR}"
  : > "${allowed_emails_file}"
  while [ -n "$email_list" ]; do
    email="${email_list%%,*}"
    email_list="${email_list#*,}"
    if [ -n "$email" ]; then
      printf '%s\n' "$email" >> "${allowed_emails_file}"
    fi
  done
  chmod 644 "${allowed_emails_file}"

  if [ ! -f "${allowed_emails_file}" ]; then
    err "Fichier OAuth2 introuvable après génération : ${allowed_emails_file}"
    exit 1
  fi
  if [ ! -s "${allowed_emails_file}" ]; then
    err "Fichier OAuth2 vide : ${allowed_emails_file}. Utilise --oauth-allowed-email avec au moins une adresse email."
    exit 1
  fi
  if [ ! -r "${allowed_emails_file}" ]; then
    err "Fichier OAuth2 illisible : ${allowed_emails_file}"
    exit 1
  fi
}

prune_empty_oauth2_env_lines() {
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

insert_oauth2_allowed_emails_volume() {
  if [ "${OAUTH2_AUTH_MODE}" != "email" ]; then
    return 0
  fi

  local compose_file="$1"
  local tmp_file="${compose_file}.tmp"
  local line
  local inserted=false

  : > "${tmp_file}"
  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$inserted" = false ] && [ "$line" = "networks:" ]; then
      printf '    volumes:\n' >> "${tmp_file}"
      printf '      - "./allowed-emails.txt:/auth/allowed-emails.txt:ro"\n' >> "${tmp_file}"
      printf '\n' >> "${tmp_file}"
      inserted=true
    fi
    printf '%s\n' "$line" >> "${tmp_file}"
  done < "${compose_file}"
  mv "${tmp_file}" "${compose_file}"
}

step_oauth2() {
  if [ "${OAUTH2_ENABLED}" != true ]; then
    return 0
  fi

  OAUTH2_DIR="${BASE_DIR}/proxy/oauth2-proxy"
  TRAEFIK_DYNAMIC_DIR="${BASE_DIR}/proxy/traefik/dynamic"
  run mkdir -p "${OAUTH2_DIR}" "${TRAEFIK_DYNAMIC_DIR}"

  local oauth2_compose_file="${OAUTH2_DIR}/docker-compose.yml"

  render_oauth2_compose_runtime "${oauth2_compose_file}"
  write_oauth2_allowed_emails_file
  render_oauth2_middleware_template "${TEMPLATE_DIR}/traefik/middleware-oauth2.yml" "${TRAEFIK_DYNAMIC_DIR}/middleware-oauth2.yml"
  render_template "${TEMPLATE_DIR}/traefik/route-oauth2-proxy.yml" "${TRAEFIK_DYNAMIC_DIR}/route-oauth2-proxy.yml"

  ok "Stack OAuth2 Proxy générée dans ${OAUTH2_DIR}"
}

step_crowdsec() {
  if [ "${WITH_CROWDSEC:-false}" != true ]; then
    return 0
  fi

  CROWDSEC_DIR="${BASE_DIR}/proxy/crowdsec"
  TRAEFIK_DIR="${BASE_DIR}/proxy/traefik"
  TRAEFIK_DYNAMIC_DIR="${BASE_DIR}/proxy/traefik/dynamic"

  run mkdir -p \
    "${CROWDSEC_DIR}" \
    "${CROWDSEC_DIR}/config" \
    "${CROWDSEC_DIR}/data" \
    "${TRAEFIK_DIR}/logs" \
    "${TRAEFIK_DYNAMIC_DIR}"

  render_template "${TEMPLATE_DIR}/compose/crowdsec.yml" "${CROWDSEC_DIR}/docker-compose.yml"
  render_template "${TEMPLATE_DIR}/crowdsec/acquis.yml" "${CROWDSEC_DIR}/acquis.yml"
  if [ "${CROWDSEC_APPSEC_ENABLED:-false}" = true ]; then
    render_template "${TEMPLATE_DIR}/crowdsec/appsec.yaml" "${CROWDSEC_DIR}/appsec.yaml"
  elif [ -f "${CROWDSEC_DIR}/appsec.yaml" ]; then
    if [ "${DRY_RUN:-false}" = true ]; then
      warn "[DRY-RUN] Suppression de ${CROWDSEC_DIR}/appsec.yaml"
    else
      rm -f "${CROWDSEC_DIR}/appsec.yaml"
    fi
  fi
  render_template "${TEMPLATE_DIR}/crowdsec/profiles.yaml" "${CROWDSEC_DIR}/profiles.yaml"
  render_template "${TEMPLATE_DIR}/traefik/middleware-crowdsec.yml" "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml"

  if [ "${DRY_RUN:-false}" = false ]; then
    chmod 700 "${CROWDSEC_DIR}/config" "${CROWDSEC_DIR}/data"
    chmod 600 "${CROWDSEC_DIR}/docker-compose.yml"
    [ -f "${CROWDSEC_DIR}/appsec.yaml" ] && chmod 600 "${CROWDSEC_DIR}/appsec.yaml"
    chmod 600 "${TRAEFIK_DYNAMIC_DIR}/middleware-crowdsec.yml"
  fi

  ok "Stack CrowdSec générée dans ${CROWDSEC_DIR}"
}

start_compose_stack() {
  local stack_name="$1"
  local stack_dir="$2"

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${stack_dir} && docker compose up -d"
    return 0
  fi

  if [ ! -f "${stack_dir}/docker-compose.yml" ]; then
    err "Stack ${stack_name} introuvable : ${stack_dir}/docker-compose.yml"
    exit 1
  fi

  if ! command -v docker >/dev/null 2>&1; then
    err "Docker est requis pour démarrer ${stack_name}."
    exit 1
  fi

  if ! docker compose version >/dev/null 2>&1; then
    err "Docker Compose est requis pour démarrer ${stack_name}."
    exit 1
  fi

  info "Démarrage de ${stack_name}..."
  if ! (cd "${stack_dir}" && docker compose up -d); then
    err "Échec du démarrage de ${stack_name}. Commande de dépannage : cd ${stack_dir} && docker compose up -d"
    exit 1
  fi
  ok "${stack_name} démarré."
}

wait_crowdsec_ready() {
  local stack_dir="$1"
  local attempt

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Vérification disponibilité CrowdSec avant Traefik"
    return 0
  fi

  info "Vérification de la disponibilité CrowdSec..."
  for attempt in {1..30}; do
    if (cd "${stack_dir}" && docker compose exec -T crowdsec cscli lapi status >/dev/null 2>&1); then
      ok "CrowdSec est prêt."
      return 0
    fi
    sleep 2
  done

  err "CrowdSec n'est pas disponible après démarrage. Traefik ne sera pas lancé avec le middleware CrowdSec."
  err "Commande de dépannage : cd ${stack_dir} && docker compose logs crowdsec"
  exit 1
}

step_start_infrastructure() {
  if [ "${WITH_CROWDSEC:-false}" = true ]; then
    CROWDSEC_DIR="${BASE_DIR}/proxy/crowdsec"
    if [ "${DRY_RUN:-false}" = true ]; then
      CROWDSEC_START_STATUS="prévu (dry-run)"
    else
      CROWDSEC_START_STATUS="en attente"
    fi
    start_compose_stack "CrowdSec" "${CROWDSEC_DIR}"
    wait_crowdsec_ready "${CROWDSEC_DIR}"
    if [ "${DRY_RUN:-false}" = false ]; then
      CROWDSEC_START_STATUS="OK"
    fi
  fi

  if [ "${WITH_TRAEFIK}" = true ]; then
    TRAEFIK_DIR="${BASE_DIR}/proxy/traefik"
    if [ "${DRY_RUN:-false}" = true ]; then
      TRAEFIK_START_STATUS="prévu (dry-run)"
    else
      TRAEFIK_START_STATUS="en attente"
    fi
    start_compose_stack "Traefik" "${TRAEFIK_DIR}"
    if [ "${DRY_RUN:-false}" = false ]; then
      TRAEFIK_START_STATUS="OK"
    fi
  fi

  if [ "${OAUTH2_ENABLED}" = true ]; then
    OAUTH2_DIR="${BASE_DIR}/proxy/oauth2-proxy"
    if [ "${DRY_RUN:-false}" = true ]; then
      OAUTH2_START_STATUS="prévu (dry-run)"
    else
      OAUTH2_START_STATUS="en attente"
    fi
    start_compose_stack "OAuth2 Proxy" "${OAUTH2_DIR}"
    if [ "${DRY_RUN:-false}" = false ]; then
      OAUTH2_START_STATUS="OK"
    fi
  fi
}
