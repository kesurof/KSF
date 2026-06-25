# ============================================================
# KSF — Étapes de gestion des applications
# ============================================================

APP_TEMPLATE_DIR="${SCRIPT_DIR}/templates/apps"
INSTALLED_DIR="${BASE_DIR}/config/installed-apps"
: "${KSF_REPO_DIR:=${SCRIPT_DIR}}"

if [ -f "${SCRIPT_DIR}/lib/dns_cloudflare.sh" ]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/lib/dns_cloudflare.sh"
fi

app_dns_ensure_record() {
  if [ "${APP_LOCAL_ONLY}" = true ]; then
    return 0
  fi
  if [ -z "${APP_HOST:-}" ]; then
    return 0
  fi
  if ! declare -F dns_ensure_record >/dev/null 2>&1; then
    return 0
  fi

  if ! dns_ensure_record "${APP_HOST}"; then
    err "Échec de la création DNS pour ${APP_HOST}."
    exit 1
  fi
}

app_dns_delete_record() {
  local host="${1:-}"
  local local_only="${2:-}"

  if [ -z "${host}" ]; then
    return 0
  fi
  if [ "${local_only}" = true ]; then
    return 0
  fi
  if ! declare -F dns_delete_record >/dev/null 2>&1; then
    return 0
  fi

  if ! dns_delete_record "${host}"; then
    warn "Suppression DNS échouée pour ${host}. Suppression locale poursuivie."
  fi
}

app_allowed_domains() {
  local configured="${DOMAINS:-${DOMAIN:-}}"
  configured="${configured//[[:space:]]/}"
  printf '%s' "${configured}"
}

app_validate_domain_allowed() {
  local domain="${1:-}"
  local configured remaining candidate

  domain="${domain//[[:space:]]/}"
  configured="$(app_allowed_domains)"

  if [ -z "${domain}" ]; then
    err "Domaine applicatif vide."
    return 1
  fi
  if [ -z "${configured}" ]; then
    err "Aucun domaine autorisé. Configure DOMAINS ou DOMAIN dans ${KSF_ENV}."
    return 1
  fi

  remaining="${configured},"
  while [ -n "${remaining}" ]; do
    candidate="${remaining%%,*}"
    remaining="${remaining#*,}"
    [ -n "${candidate}" ] || continue
    if [ "${domain}" = "${candidate}" ]; then
      return 0
    fi
  done

  err "Domaine non autorisé pour cette app : ${domain}. Domaines autorisés : ${configured}"
  return 1
}

app_domain_from_host() {
  local host="${1:-}"
  local configured remaining candidate matched=""

  host="${host//[[:space:]]/}"
  configured="$(app_allowed_domains)"

  if [ -z "${host}" ]; then
    err "Hostname applicatif vide."
    return 1
  fi
  if [ -z "${configured}" ]; then
    err "Aucun domaine autorisé. Configure DOMAINS ou DOMAIN dans ${KSF_ENV}."
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

  err "Hostname non autorisé pour cette app : ${host}. Domaines autorisés : ${configured}"
  return 1
}

app_list_available() {
  info "Apps disponibles :"
  for dir in "${APP_TEMPLATE_DIR}"/*/; do
    [ -d "$dir" ] || continue
    [ -f "${dir}/app.env" ] || continue
    local name desc
    name=$(basename "$dir")
    desc=$(source "${dir}/app.env" && echo "${APP_DESCRIPTION:-${name}}")
    info "  ${name}  -  ${desc}"
  done
}

app_list_installed() {
  info "Apps installées :"
  local found=false
  for f in "${INSTALLED_DIR}"/*.env; do
    [ -f "$f" ] || continue
    found=true
    local instance template_name
    instance=$(basename "$f" .env)
    template_name=$(APP_INSTANCE="${instance}" source "$f" >/dev/null 2>&1 && printf '%s' "${APP_NAME:-${instance}}")
    if [ "${template_name}" != "${instance}" ]; then
      info "  ${instance}  (template : ${template_name})"
    else
      info "  ${instance}"
    fi
  done
  if [ "$found" = false ]; then
    warn "Aucune app installée."
  fi
}

app_template_value() {
  local app_name="$1"
  local key="$2"
  local env_file="${APP_TEMPLATE_DIR}/${app_name}/app.env"

  [ -f "$env_file" ] || return 0
  (
    APP_NAME=""
    APP_HOST=""
    APP_DOMAIN=""
    APP_PORT=""
    APP_INTERNAL_PORT=""
    APP_PROTECTED=""
    APP_PUBLIC=""
    APP_DESCRIPTION=""
    APP_CATEGORY=""
    APP_DEFAULT_HOST=""
    source "$env_file"
    case "$key" in
      APP_PORT) printf '%s' "${APP_PORT:-${APP_INTERNAL_PORT:-}}" ;;
      APP_HOST) printf '%s' "${APP_HOST:-${APP_DEFAULT_HOST:-}}" ;;
      *) printf '%s' "${!key-}" ;;
    esac
  )
}

app_normalize_loaded() {
  local app_name="$1"

  # app_name est l'instance (CLI arg) pour les commandes status/update/etc.
  # Le nom de template est dans APP_NAME (chargé depuis l'env file).
  local app_template_name="${APP_NAME:-${app_name}}"
  local app_instance_name="${APP_INSTANCE:-${app_name}}"

  render_normalize_app_vars "$app_template_name"
  if [ -z "${APP_PORT:-}" ]; then
    APP_PORT="$(app_template_value "$app_template_name" APP_PORT)"
  fi
  if [ -z "${APP_HOST:-}" ]; then
    APP_HOST="$(app_template_value "$app_template_name" APP_HOST)"
  fi
  : "${APP_DIR:=${BASE_DIR}/apps/${app_instance_name}}"
  # Fallback : si APP_DIR pointe vers un chemin inexistant mais qu'un chemin
  # équivalent sous BASE_DIR existe (cas typique : APP_DIR est l'ancien chemin
  # de l'hôte et la plateforme tourne maintenant dans un conteneur avec un
  # bind mount), on bascule pour que docker compose trouve la stack.
  if [ ! -d "${APP_DIR}" ] && [ -d "${BASE_DIR}/apps/${app_instance_name}" ]; then
    warn "APP_DIR ${APP_DIR} introuvable, bascule vers ${BASE_DIR}/apps/${app_instance_name}"
    APP_DIR="${BASE_DIR}/apps/${app_instance_name}"
  fi
  : "${APP_DATA:=${BASE_DIR}/data/${app_instance_name}}"
  : "${APP_PUID:=$(id -u)}"
  : "${APP_PGID:=$(id -g)}"
  : "${APP_INSTALLED_AT:=}"
  : "${APP_DISABLED:=false}"
  : "${APP_INSTANCE:=${app_instance_name}}"

  APP_MANAGED_NAME="${app_instance_name}"
  APP_MANAGED_DIR="${APP_DIR}"
  APP_MANAGED_DATA="${APP_DATA}"
}

app_write_env_file() {
  local destination="$1"
  local app_name="$2"
  local app_dir="$3"
  local app_data="$4"
  local installed_at="${APP_INSTALLED_AT:-$(date -Iseconds)}"

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Enregistrement de ${destination}"
    return 0
  fi

  : > "$destination"
  ksf_env_write_var "$destination" APP_NAME "$app_name"
  ksf_env_write_var "$destination" APP_INSTANCE "${APP_INSTANCE:-${app_name}}"
  ksf_env_write_var "$destination" APP_HOST "${APP_HOST:-}"
  ksf_env_write_var "$destination" APP_DOMAIN "${APP_DOMAIN:-}"
  ksf_env_write_var "$destination" APP_SUBDOMAIN "${APP_SUBDOMAIN:-}"
  ksf_env_write_var "$destination" APP_PORT "${APP_PORT:-}"
  ksf_env_write_var "$destination" APP_PROTECTED "${APP_PROTECTED:-true}"
  ksf_env_write_var "$destination" APP_AUTH "${APP_PROTECTED:-true}"
  ksf_env_write_var "$destination" APP_PUBLIC "${APP_PUBLIC:-true}"
  ksf_env_write_var "$destination" APP_LOCAL_ONLY "${APP_LOCAL_ONLY:-false}"
  ksf_env_write_var "$destination" APP_DISABLED "${APP_DISABLED:-false}"
  ksf_env_write_var "$destination" APP_DIR "$app_dir"
  ksf_env_write_var "$destination" APP_DATA "$app_data"
  ksf_env_write_var "$destination" APP_PUID "${APP_PUID}"
  ksf_env_write_var "$destination" APP_PGID "${APP_PGID}"
  ksf_env_write_var "$destination" APP_INSTALLED_AT "$installed_at"
  chmod 600 "$destination"
}

app_update_env_value() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  local tmp_file="${env_file}.tmp"
  local line found=false

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Mise à jour ${key} dans ${env_file}"
    return 0
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

app_confirm_action() {
  local action="$1"
  local app_name="$2"

  [ "${DRY_RUN:-false}" = true ] && return 0
  [ "${AUTO_YES:-false}" = true ] && return 0

  echo -n "Confirmer ${action} de ${app_name} ? Tape '${app_name}' pour continuer : "
  local confirmation
  if ! read -r confirmation || [ "$confirmation" != "$app_name" ]; then
    err "Action annulée."
    exit 1
  fi
}

app_create_backup_before() {
  local action="$1"

  if ! declare -F backup_create >/dev/null 2>&1; then
    err "Module backup indisponible : backup automatique impossible avant ${action}."
    exit 1
  fi
  info "Backup automatique avant ${action}..."
  backup_create
}

app_require_installed() {
  local app_name="$1"

  if [ ! -f "${INSTALLED_DIR}/${app_name}.env" ]; then
    err "L'app ${app_name} n'est pas installée."
    exit 1
  fi

  source "${INSTALLED_DIR}/${app_name}.env"
  app_normalize_loaded "$app_name"

  if [ ! -d "${APP_MANAGED_DIR}" ]; then
    err "Dossier de stack absent pour ${app_name} : ${APP_MANAGED_DIR}"
    exit 1
  fi
  if [ ! -f "${APP_MANAGED_DIR}/docker-compose.yml" ]; then
    err "Fichier Compose absent pour ${app_name} : ${APP_MANAGED_DIR}/docker-compose.yml"
    exit 1
  fi
}

app_require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    err "Docker n'est pas installé ou absent du PATH."
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    err "Docker Compose n'est pas disponible."
    exit 1
  fi
}

_compose_has_build() {
  local compose_file="$1"
  [ -f "$compose_file" ] || return 1
  grep -qE '^\s*build:' "$compose_file" 2>/dev/null
}

app_compose_run() {
  local app_name="$1"
  local action="$2"
  local command_label="$3"

  app_require_installed "$app_name"

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${APP_MANAGED_DIR} && docker compose ${command_label}"
    return 0
  fi

  app_require_docker
  info "${action} de ${APP_MANAGED_NAME}..."
  if ! (cd "${APP_MANAGED_DIR}" && docker compose ${command_label}); then
    err "Échec de l'action '${command_label}' pour ${APP_MANAGED_NAME}."
    exit 1
  fi
}

app_status() {
  local app_name="$1"
  app_require_installed "$app_name"

  echo "=== App ${APP_MANAGED_NAME} ==="
  echo "Stack      : ${APP_MANAGED_DIR}"
  echo "Données    : ${APP_MANAGED_DATA}"
  if [ "${APP_LOCAL_ONLY:-false}" = true ]; then
    echo "Accès      : local-only"
  elif [ "${APP_DISABLED:-false}" = true ]; then
    echo "Accès      : désactivé"
  elif [ -n "${APP_HOST:-}" ]; then
    echo "Accès      : https://${APP_HOST}"
  else
    echo "Accès      : non exposé"
  fi
  echo "OAuth2 Proxy: ${APP_PROTECTED:-${APP_AUTH:-true}}"
  echo ""

  if ! command -v docker >/dev/null 2>&1 || ! docker ps >/dev/null 2>&1; then
    warn "Docker est inaccessible, état container indisponible."
    return 0
  fi

  if docker inspect "${APP_MANAGED_NAME}" >/dev/null 2>&1; then
    local state health
    state=$(docker inspect -f '{{.State.Status}}' "${APP_MANAGED_NAME}" 2>/dev/null || echo "unknown")
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${APP_MANAGED_NAME}" 2>/dev/null || echo "unknown")
    ok "Container   : ${APP_MANAGED_NAME} (${state}, health: ${health})"
  else
    warn "Container   : ${APP_MANAGED_NAME} absent"
  fi

  echo ""
  info "Docker Compose :"
  (cd "${APP_MANAGED_DIR}" && docker compose ps) || warn "Impossible de lire l'état Compose de ${APP_MANAGED_NAME}."
}

app_start() {
  app_compose_run "$1" "Démarrage" "up -d"
  if [ "${DRY_RUN:-false}" = true ]; then
    ok "Simulation de démarrage de ${APP_MANAGED_NAME} terminée."
  else
    ok "App ${APP_MANAGED_NAME} démarrée."
  fi
}

app_stop() {
  app_compose_run "$1" "Arrêt" "stop"
  if [ "${DRY_RUN:-false}" = true ]; then
    ok "Simulation d'arrêt de ${APP_MANAGED_NAME} terminée."
  else
    ok "App ${APP_MANAGED_NAME} arrêtée."
  fi
}

app_restart() {
  app_compose_run "$1" "Redémarrage" "restart"
  if [ "${DRY_RUN:-false}" = true ]; then
    ok "Simulation de redémarrage de ${APP_MANAGED_NAME} terminée."
  else
    ok "App ${APP_MANAGED_NAME} redémarrée."
  fi
}

app_update() {
  local app_name="$1"
  local app_template_dir="${APP_TEMPLATE_DIR}/${app_name}"

  app_require_installed "$app_name"
  # app_require_installed charge l'env file et fait app_normalize_loaded.
  # APP_NAME est maintenant le nom de template (pas l'instance). On résout
  # le bon template_dir pour le multi-instance.
  app_template_dir="${APP_TEMPLATE_DIR}/${APP_NAME:-${app_name}}"
  if [ ! -f "${app_template_dir}/compose.yml" ]; then
    err "Template Compose absent pour ${APP_NAME:-${app_name}} : ${app_template_dir}/compose.yml"
    exit 1
  fi

  app_confirm_action "la mise à jour" "$app_name"
  app_create_backup_before "update ${app_name}"

  app_resolve_docker_gid
  : "${APP_PUID:=$(id -u)}"
  : "${APP_PGID:=$(id -g)}"
  # Cas spécifique ksf-web : régénérer le .env pour docker compose
  if [ "${APP_NAME}" = "ksf-web" ]; then
    KSF_WEB_DATA_HOST_DIR="${BASE_DIR}/.ksf-web-data"
    if [ -d "${KSF_WEB_DATA_HOST_DIR}" ]; then
      chown "${APP_PUID}:${APP_PGID}" "${KSF_WEB_DATA_HOST_DIR}" 2>/dev/null || true
      chmod 700 "${KSF_WEB_DATA_HOST_DIR}"
    fi
    # Si KSF_WEB_SECRET_KEY est set dans le shell, on la persiste ici aussi
    # (sinon perte de clé de chiffrement au prochain up). Le user peut aussi
    # l'éditer manuellement dans ${APP_MANAGED_DIR}/.env après install.
    cat > "${APP_MANAGED_DIR}/.env" <<EOF
KSF_WEB_DATA_HOST_DIR=${BASE_DIR}/.ksf-web-data
APP_PUID=${APP_PUID}
APP_PGID=${APP_PGID}
KSF_WEB_SECRET_KEY=${KSF_WEB_SECRET_KEY:-}
EOF
    chmod 600 "${APP_MANAGED_DIR}/.env"
  fi
  render_template "${app_template_dir}/compose.yml" "${APP_MANAGED_DIR}/docker-compose.yml"
  app_write_env_file "${APP_MANAGED_DIR}/app.env" "${APP_NAME}" "$APP_MANAGED_DIR" "$APP_MANAGED_DATA"
  app_write_env_file "${INSTALLED_DIR}/${app_name}.env" "${APP_NAME}" "$APP_MANAGED_DIR" "$APP_MANAGED_DATA"

  # Hook pre_install : régénère secrets, configs, .env (idempotent).
  app_run_hook "pre_install" "${app_template_dir}/pre_install.sh" "$app_name"

  if [ "${APP_LOCAL_ONLY:-false}" != true ] && [ "${APP_DISABLED:-false}" != true ] && [ "${APP_PUBLIC:-true}" = true ] && [ -n "${APP_HOST:-}" ]; then
    render_app_route_from_env "${BASE_DIR}/proxy/traefik/dynamic/route-${app_name}.yml"
  fi

  if [ "${DRY_RUN:-false}" = true ]; then
    if _compose_has_build "${APP_MANAGED_DIR}/docker-compose.yml"; then
      warn "[DRY-RUN] Build local detecte : reconstruction de l'image avant recreation."
      warn "[DRY-RUN] cd ${APP_MANAGED_DIR} && docker compose up -d --build --force-recreate"
    else
      warn "[DRY-RUN] cd ${APP_MANAGED_DIR} && docker compose pull"
      warn "[DRY-RUN] cd ${APP_MANAGED_DIR} && docker compose up -d --force-recreate"
    fi
    app_run_hook "post_install" "${app_template_dir}/post_install.sh" "$app_name"
    ok "Simulation de mise a jour de ${APP_MANAGED_NAME} terminee."
    return 0
  fi

  app_require_docker

  if _compose_has_build "${APP_MANAGED_DIR}/docker-compose.yml"; then
    info "Build local detecte : reconstruction de l'image avant recreation..."
    (cd "${APP_MANAGED_DIR}" && docker compose up -d --build --force-recreate) || { err "Echec docker compose up -d --build --force-recreate pour ${APP_MANAGED_NAME}."; exit 1; }
  else
    info "Pull ${APP_MANAGED_NAME}..."
    (cd "${APP_MANAGED_DIR}" && docker compose pull) || { err "Echec docker compose pull pour ${APP_MANAGED_NAME}."; exit 1; }
    info "Recreation de ${APP_MANAGED_NAME} pour appliquer la configuration..."
    (cd "${APP_MANAGED_DIR}" && docker compose up -d --force-recreate) || { err "Echec docker compose up -d --force-recreate pour ${APP_MANAGED_NAME}."; exit 1; }
  fi

  ok "App ${APP_MANAGED_NAME} mise a jour."

  # Hook post_install : reconfiguration post-update.
  app_run_hook "post_install" "${app_template_dir}/post_install.sh" "$app_name"

  if [ "${APP_NAME}" = "ksf-web" ] && declare -F cf_purge_cache >/dev/null 2>&1; then
    cf_purge_cache
  fi
}

app_rebuild() {
  local app_name="$1"
  local app_template_dir="${APP_TEMPLATE_DIR}/${app_name}"

  app_require_installed "$app_name"
  # app_require_installed charge l'env file : APP_NAME = template.
  app_template_dir="${APP_TEMPLATE_DIR}/${APP_NAME:-${app_name}}"
  if [ ! -f "${app_template_dir}/compose.yml" ]; then
    err "Template Compose absent pour ${APP_NAME:-${app_name}} : ${app_template_dir}/compose.yml"
    exit 1
  fi

  if ! _compose_has_build "${APP_MANAGED_DIR}/docker-compose.yml"; then
    warn "Pas de build local pour ${app_name} — mise à jour classique."
    app_update "$app_name"
    return $?
  fi

  app_confirm_action "la reconstruction (sans cache)" "$app_name"
  app_create_backup_before "rebuild ${app_name}"

  app_resolve_docker_gid
  : "${APP_PUID:=$(id -u)}"
  : "${APP_PGID:=$(id -g)}"
  # Cas spécifique ksf-web : régénérer le .env pour docker compose
  if [ "${APP_NAME}" = "ksf-web" ]; then
    KSF_WEB_DATA_HOST_DIR="${BASE_DIR}/.ksf-web-data"
    if [ -d "${KSF_WEB_DATA_HOST_DIR}" ]; then
      chown "${APP_PUID}:${APP_PGID}" "${KSF_WEB_DATA_HOST_DIR}" 2>/dev/null || true
      chmod 700 "${KSF_WEB_DATA_HOST_DIR}"
    fi
    # Si KSF_WEB_SECRET_KEY est set dans le shell, on la persiste ici aussi
    # (sinon perte de clé de chiffrement au prochain up). Le user peut aussi
    # l'éditer manuellement dans ${APP_MANAGED_DIR}/.env après install.
    cat > "${APP_MANAGED_DIR}/.env" <<EOF
KSF_WEB_DATA_HOST_DIR=${BASE_DIR}/.ksf-web-data
APP_PUID=${APP_PUID}
APP_PGID=${APP_PGID}
KSF_WEB_SECRET_KEY=${KSF_WEB_SECRET_KEY:-}
EOF
    chmod 600 "${APP_MANAGED_DIR}/.env"
  fi
  render_template "${app_template_dir}/compose.yml" "${APP_MANAGED_DIR}/docker-compose.yml"
  app_write_env_file "${APP_MANAGED_DIR}/app.env" "${APP_NAME}" "$APP_MANAGED_DIR" "$APP_MANAGED_DATA"
  app_write_env_file "${INSTALLED_DIR}/${app_name}.env" "${APP_NAME}" "$APP_MANAGED_DIR" "$APP_MANAGED_DATA"

  # Hook pre_install : régénère secrets, configs, .env (idempotent).
  app_run_hook "pre_install" "${app_template_dir}/pre_install.sh" "$app_name"

  if [ "${APP_LOCAL_ONLY:-false}" != true ] && [ "${APP_DISABLED:-false}" != true ] && [ "${APP_PUBLIC:-true}" = true ] && [ -n "${APP_HOST:-}" ]; then
    render_app_route_from_env "${BASE_DIR}/proxy/traefik/dynamic/route-${app_name}.yml"
  fi

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${APP_MANAGED_DIR} && docker compose build --no-cache && docker compose up -d --force-recreate"
    app_run_hook "post_install" "${app_template_dir}/post_install.sh" "$app_name"
    ok "Simulation de reconstruction de ${APP_MANAGED_NAME} terminee."
    return 0
  fi

  app_require_docker

  info "Reconstruction sans cache de ${APP_MANAGED_NAME}..."
  (cd "${APP_MANAGED_DIR}" && docker compose build --no-cache) || { err "Echec docker compose build --no-cache pour ${APP_MANAGED_NAME}."; exit 1; }
  info "Recreation de ${APP_MANAGED_NAME}..."
  (cd "${APP_MANAGED_DIR}" && docker compose up -d --force-recreate) || { err "Echec docker compose up -d --force-recreate pour ${APP_MANAGED_NAME}."; exit 1; }

  ok "App ${APP_MANAGED_NAME} reconstruite."

  # Hook post_install : reconfiguration post-rebuild.
  app_run_hook "post_install" "${app_template_dir}/post_install.sh" "$app_name"

  if [ "${APP_NAME}" = "ksf-web" ] && declare -F cf_purge_cache >/dev/null 2>&1; then
    cf_purge_cache
  fi
}

app_disable() {
  local app_name="$1"
  local route_file="${BASE_DIR}/proxy/traefik/dynamic/route-${app_name}.yml"

  app_require_installed "$app_name"
  app_confirm_action "la désactivation" "$app_name"

  if [ -d "${APP_MANAGED_DIR}" ]; then
    if [ "${DRY_RUN:-false}" = true ]; then
      warn "[DRY-RUN] cd ${APP_MANAGED_DIR} && docker compose down"
    else
      app_require_docker
      info "Désactivation de ${APP_MANAGED_NAME}..."
      if ! (cd "${APP_MANAGED_DIR}" && docker compose down); then
        warn "docker compose down a échoué pour ${APP_MANAGED_NAME}. Désactivation locale poursuivie."
      fi
    fi
  fi

  if [ -f "$route_file" ]; then
    run rm -f "$route_file"
    ok "Route Traefik supprimée."
  elif [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] Route Traefik absente ou déjà supprimée : ${route_file}"
  fi

  app_update_env_value "${INSTALLED_DIR}/${app_name}.env" APP_DISABLED true
  if [ -f "${APP_MANAGED_DIR}/app.env" ]; then
    app_update_env_value "${APP_MANAGED_DIR}/app.env" APP_DISABLED true
  fi

  if [ "${DRY_RUN:-false}" = true ]; then
    ok "Simulation de désactivation de ${APP_MANAGED_NAME} terminée."
  else
    ok "App ${APP_MANAGED_NAME} désactivée."
  fi
}

app_logs() {
  local app_name="$1"
  app_require_installed "$app_name"

  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] cd ${APP_MANAGED_DIR} && docker compose logs --tail=200"
    return 0
  fi

  app_require_docker
  info "Logs de ${APP_MANAGED_NAME} (200 dernières lignes) :"
  if ! (cd "${APP_MANAGED_DIR}" && docker compose logs --tail=200); then
    err "Impossible de lire les logs de ${APP_MANAGED_NAME}."
    exit 1
  fi
}

resolve_app_host() {
  local app_name="$1"
  local subdomain="${APP_SUBDOMAIN_OVERRIDE:-${APP_DEFAULT_HOST}}"

  if [ -n "${APP_HOST_OVERRIDE}" ]; then
    APP_HOST="${APP_HOST_OVERRIDE}"
    APP_DOMAIN="$(app_domain_from_host "${APP_HOST}")" || exit 1
    APP_SUBDOMAIN="${APP_HOST%.${APP_DOMAIN}}"
    return 0
  fi

  APP_DOMAIN="${APP_DOMAIN_OVERRIDE:-${DEFAULT_DOMAIN:-${DOMAIN:-}}}"

  if [ -z "${APP_DOMAIN}" ]; then
    if [ "${AUTO_YES}" = true ]; then
      err "--domain est requis en mode automatique pour exposer ${app_name}."
      exit 1
    fi
    echo -n "Domaine principal pour ${app_name} (ex: example.com) : "
    read -r APP_DOMAIN
  fi

  app_validate_domain_allowed "${APP_DOMAIN}" || exit 1

  if [ "${AUTO_YES}" = false ] && [ -z "${APP_SUBDOMAIN_OVERRIDE}" ]; then
    echo -n "Sous-domaine pour ${app_name} (défaut: ${APP_DEFAULT_HOST}) : "
    read -r subdomain_input
    subdomain="${subdomain_input:-${APP_DEFAULT_HOST}}"
  fi

  APP_SUBDOMAIN="${subdomain}"
  APP_HOST="${APP_SUBDOMAIN}.${APP_DOMAIN}"
}

resolve_app_auth() {
  local app_name="$1"
  APP_PROTECTED="${APP_PROTECTED:-true}"

  if [ "${APP_AUTH_CHOICE}" = "true" ]; then
    APP_PROTECTED=true
  elif [ "${APP_AUTH_CHOICE}" = "false" ]; then
    APP_PROTECTED=false
  elif [ "${OAUTH2_ENABLED:-false}" = true ]; then
    if [ "${AUTO_YES}" = false ]; then
      echo -n "Protéger l'accès à ${app_name} avec OAuth2 Proxy ? (oui/non) [oui] : "
      read -r auth_input
      if [ "$auth_input" = "non" ]; then
        APP_PROTECTED=false
      fi
    else
      APP_PROTECTED=true
    fi
  fi

  APP_AUTH="${APP_PROTECTED}"

  if [ "${APP_PROTECTED}" = true ] && [ "${OAUTH2_ENABLED:-false}" != true ]; then
    err "OAuth2 Proxy n'est pas configuré. Relance deploy.sh avec OAuth2 Proxy ou utilise --no-auth."
    exit 1
  fi
}

app_resolve_docker_gid() {
  if [ -n "${DOCKER_GID:-}" ]; then
    return 0
  fi
  DOCKER_GID="$(getent group docker 2>/dev/null | cut -d: -f3 || true)"
  if [ -z "${DOCKER_GID}" ]; then
    warn "Groupe docker introuvable sur l'hôte. L'accès au socket Docker pourrait échouer pour les apps qui le nécessitent."
  fi
}

# Exécute un hook (pre_install.sh / post_install.sh) d'une app si présent.
#
# Le hook est sourcé (et non exécuté) dans un sous-shell, ce qui permet :
#   - d'accéder aux variables KSF déjà chargées (APP_DIR, APP_DATA, BASE_DIR, ...)
#   - d'exporter de nouvelles variables / écrire des fichiers qui seront
#     utilisés par la suite du flux (ex : ${app_dir}/.env pour docker compose)
#
# Variables exposées au hook :
#   APP_NAME, APP_DIR, APP_DATA, APP_PUID, APP_PGID, APP_HOST, APP_PORT,
#   APP_DOMAIN, APP_TEMPLATE_DIR, BASE_DIR, NETWORK_NAME, TZ_VALUE, DOCKER_GID,
#   DRY_RUN, AUTO_YES
#
# Conventions :
#   templates/apps/<app>/pre_install.sh   : optionnel, exécuté avant render+up
#   templates/apps/<app>/post_install.sh  : optionnel, exécuté après up réussi
app_run_hook() {
  local hook_name="$1"
  local hook_path="$2"
  local app_name="$3"

  if [ ! -f "$hook_path" ]; then
    return 0
  fi
  if [ ! -r "$hook_path" ]; then
    err "Hook ${hook_name} illisible : ${hook_path}"
    exit 1
  fi

  info "Hook ${hook_name} de ${app_name}..."
  if [ "${DRY_RUN:-false}" = true ]; then
    warn "[DRY-RUN] source ${hook_path}"
    return 0
  fi

  if ! ( source "$hook_path" ); then
    err "Échec du hook ${hook_name} pour ${app_name} (voir logs ci-dessus)."
    exit 1
  fi
}

app_install() {
  local app_name="$1"
  local app_instance="${APP_INSTANCE_OVERRIDE:-${app_name}}"
  local app_template_dir="${APP_TEMPLATE_DIR}/${app_name}"

  if [ ! -d "${app_template_dir}" ]; then
    err "App inconnue : ${app_name}"
    app_list_available
    exit 1
  fi

  if [ -f "${INSTALLED_DIR}/${app_instance}.env" ]; then
    err "L'instance '${app_instance}' est déjà installée (template : ${app_name})."
    err "Pour une autre instance, utilise --instance <nom>."
    exit 1
  fi

  source "${app_template_dir}/app.env"
  APP_DEFAULT_HOST="${APP_DEFAULT_HOST:-${APP_HOST:-${APP_NAME:-${app_instance}}}}"
  APP_PORT="${APP_PORT_OVERRIDE:-${APP_PORT:-${APP_INTERNAL_PORT:-}}}"
  APP_PROTECTED="${APP_PROTECTED:-true}"
  APP_PUBLIC="${APP_PUBLIC:-true}"
  APP_INSTANCE="${app_instance}"

  APP_HOST=""
  APP_DOMAIN=""
  APP_SUBDOMAIN=""
  APP_AUTH="${APP_PROTECTED}"
  APP_DISABLED=false
  APP_PUID="$(id -u)"
  APP_PGID="$(id -g)"
  local app_dir="${BASE_DIR}/apps/${app_instance}"
  local app_data="${BASE_DIR}/data/${app_instance}"

  if [ "${APP_LOCAL_ONLY}" = false ] && [ "${WITH_TRAEFIK:-false}" = true ]; then
    resolve_app_host "${app_instance}"
    resolve_app_auth "${app_instance}"
  else
    info "${app_instance} sera accessible en local sur 127.0.0.1:${APP_PORT} si son compose expose ce port."
  fi

  run mkdir -p "${INSTALLED_DIR}" "${app_dir}" "${app_data}"
  app_resolve_docker_gid
  : "${APP_PUID:=$(id -u)}"
  : "${APP_PGID:=$(id -g)}"

  # Cas spécifique ksf-web : bind mount pour la persistance DB.
  # On crée et chown le dossier hôte AVANT le `docker compose up` pour que
  # le conteneur (qui démarre sous l'UID hôte) puisse écrire dedans.
  #
  # NB : KSF_WEB_DATA_HOST_DIR vient directement de ${BASE_DIR} ici, pas de
  # l'app.env (qui contient un token KSF __BASE_DIR__ non encore rendu à ce stade).
  if [ "$app_name" = "ksf-web" ]; then
    KSF_WEB_DATA_HOST_DIR="${BASE_DIR}/.ksf-web-data"
    if ! mkdir -p "${KSF_WEB_DATA_HOST_DIR}" 2>/dev/null; then
      err "Impossible de créer ${KSF_WEB_DATA_HOST_DIR}. Vérifier les permissions de ${BASE_DIR}."
      exit 1
    fi
    chown "${APP_PUID}:${APP_PGID}" "${KSF_WEB_DATA_HOST_DIR}" 2>/dev/null || {
      warn "chown ${KSF_WEB_DATA_HOST_DIR} a échoué. Le conteneur risque de ne pas pouvoir écrire."
    }
    chmod 700 "${KSF_WEB_DATA_HOST_DIR}"
    # Écrire un .env dans le dossier du compose pour que docker compose
    # auto-charge les vars. On utilise ${BASE_DIR} directement (substitué par bash)
    # et pas la variable shell (qui pourrait contenir un token KSF non rendu).
    #
    # Si KSF_WEB_SECRET_KEY est set dans le shell de l'user au moment de
    # l'install, on la persiste dans le .env de l'app pour que les futurs
    # `up` la passent au conteneur (sinon, perte de clé de chiffrement au
    # prochain reboot/rebuild).
    cat > "${app_dir}/.env" <<EOF
KSF_WEB_DATA_HOST_DIR=${BASE_DIR}/.ksf-web-data
APP_PUID=${APP_PUID}
APP_PGID=${APP_PGID}
KSF_WEB_SECRET_KEY=${KSF_WEB_SECRET_KEY:-}
EOF
    chmod 600 "${app_dir}/.env"
  fi

  render_template "${app_template_dir}/compose.yml" "${app_dir}/docker-compose.yml"
  app_write_env_file "${app_dir}/app.env" "$app_name" "$app_dir" "$app_data"
  ok "Stack ${app_instance} générée dans ${app_dir}"

  if [ "${APP_LOCAL_ONLY}" = false ] && [ "${WITH_TRAEFIK:-false}" = true ] && [ -n "${APP_HOST}" ] && [ "${APP_PUBLIC}" = true ]; then
    local dynamic_dir="${BASE_DIR}/proxy/traefik/dynamic"
    run mkdir -p "${dynamic_dir}"
    render_app_route_from_env "${dynamic_dir}/route-${app_instance}.yml"
    ok "Route Traefik générée pour ${app_instance} (${APP_HOST})"
  fi

  app_dns_ensure_record

  app_write_env_file "${INSTALLED_DIR}/${app_instance}.env" "$app_name" "$app_dir" "$app_data"

  # Hook pre_install : permet à l'app de générer des secrets, fichiers de
  # config, .env, etc. AVANT le démarrage de la stack. Le hook est sourcé
  # (donc peut set des variables / écrire des fichiers utilisés par la suite).
  app_run_hook "pre_install" "${app_template_dir}/pre_install.sh" "$app_instance"

  if [ "${DRY_RUN:-false}" = true ]; then
    if _compose_has_build "${app_dir}/docker-compose.yml"; then
      warn "[DRY-RUN] Build local detecte : reconstruction de l'image."
      warn "[DRY-RUN] cd ${app_dir} && docker compose up -d --build --force-recreate"
    else
      warn "[DRY-RUN] cd ${app_dir} && docker compose up -d --force-recreate"
    fi
    app_run_hook "post_install" "${app_template_dir}/post_install.sh" "$app_instance"
    ok "Simulation d'installation de ${app_instance} terminee."
  else
    info "Demarrage de ${app_instance}..."
    local up_cmd="docker compose up -d --force-recreate"
    if _compose_has_build "${app_dir}/docker-compose.yml"; then
      up_cmd="docker compose up -d --build --force-recreate"
    fi
    if ! (cd "${app_dir}" && ${up_cmd}); then
      err "Echec du demarrage de ${app_instance}. Stack generee dans ${app_dir}."
      exit 1
    fi
    ok "App ${app_instance} installée et demarree."

    # Hook post_install : configuration post-démarrage (ex : activation de
    # plugins, configuration WP, etc.). Ne s'exécute que si le up a réussi.
    app_run_hook "post_install" "${app_template_dir}/post_install.sh" "$app_instance"
  fi
}

app_remove() {
  local app_name="$1"
  local APP_LOCAL_ONLY=""

  if [ ! -f "${INSTALLED_DIR}/${app_name}.env" ]; then
    err "L'app ${app_name} n'est pas installée."
    exit 1
  fi

  source "${INSTALLED_DIR}/${app_name}.env"
  app_normalize_loaded "$app_name"
  local app_dir="${APP_DIR:-${BASE_DIR}/apps/${app_name}}"
  local route_file="${BASE_DIR}/proxy/traefik/dynamic/route-${app_name}.yml"
  local app_host="${APP_HOST:-}"
  local app_local_only="${APP_LOCAL_ONLY:-}"

  app_confirm_action "la suppression" "$app_name"
  app_create_backup_before "remove ${app_name}"

  if [ -d "${app_dir}" ]; then
    if [ "${DRY_RUN:-false}" = true ]; then
      warn "[DRY-RUN] cd ${app_dir} && docker compose down"
    else
      info "Arrêt de ${app_name}..."
      if ! (cd "${app_dir}" && docker compose down); then
        warn "docker compose down a échoué pour ${app_name}. Suppression des fichiers poursuivie."
      fi
    fi
  fi

  if [ -f "$route_file" ]; then
    run rm -f "$route_file"
    ok "Route Traefik supprimée."
  fi

  app_dns_delete_record "${app_host}" "${app_local_only}"

  if [ -d "${app_dir}" ]; then
    run rm -rf "${app_dir}"
    ok "Stack supprimée."
  fi

  run rm -f "${INSTALLED_DIR}/${app_name}.env"
  ok "Enregistrement supprimé."
  warn "→ Les données dans ${APP_DATA:-${BASE_DIR}/data/${app_name}} ont été préservées."
}
