#!/usr/bin/env bash
# WordPress pre_install : genere secrets + configs optimises.
#
# Variables disponibles (exportees par app_install / app_update / app_rebuild) :
#   APP_NAME, APP_DIR, APP_DATA, APP_PUID, APP_PGID, APP_HOST, APP_PORT,
#   APP_TEMPLATE_DIR, BASE_DIR, NETWORK_NAME, TZ_VALUE, DOCKER_GID,
#   DRY_RUN, AUTO_YES
#
# Fichiers produits :
#   ${APP_DIR}/.env                 : DB_PASSWORD, DB_ROOT_PASSWORD, AUTH_KEY/SALT
#                                     (consomme par docker compose via ${WORDPRESS_*})
#   ${APP_DATA}/config/php.ini      : config PHP montee read-only dans le conteneur
#   ${APP_DATA}/config/opcache.ini  : config OPcache montee read-only
#
# Idempotence : sur update / rebuild, les secrets existants sont preservees.
# Pour regenerer les secrets, supprimer ${APP_DIR}/.env avant de relancer.

set -euo pipefail

ENV_FILE="${APP_DIR}/.env"
CONFIG_DIR="${APP_DATA}/config"

# ---------- Generation du .env (idempotente) ----------
# Si le .env existe deja (cas update/rebuild), on le preserve tel quel.
# Sinon on genere des secrets frais.
if [ ! -f "${ENV_FILE}" ]; then
  if [ "${DRY_RUN:-false}" = true ]; then
    info "[DRY-RUN] Generation de ${ENV_FILE} (DB + salts aleatoires)"
  else
    : "${WORDPRESS_DB_NAME:=wordpress}"
    : "${WORDPRESS_DB_USER:=wordpress}"
    WORDPRESS_DB_PASSWORD="$(openssl rand -base64 24 | tr -d '\n')"
    WORDPRESS_CACHE_KEY_SALT="$(openssl rand -hex 16)"

    # WordPress AUTH_KEY / SECURE_AUTH_KEY / etc. — fortement recommande pour
    # la securite des cookies. Regeneres a chaque install frais.
    WORDPRESS_AUTH_KEY="$(openssl rand -base64 48 | tr -d '\n')"
    WORDPRESS_SECURE_AUTH_KEY="$(openssl rand -base64 48 | tr -d '\n')"
    WORDPRESS_LOGGED_IN_KEY="$(openssl rand -base64 48 | tr -d '\n')"
    WORDPRESS_NONCE_KEY="$(openssl rand -base64 48 | tr -d '\n')"
    WORDPRESS_AUTH_SALT="$(openssl rand -base64 48 | tr -d '\n')"
    WORDPRESS_SECURE_AUTH_SALT="$(openssl rand -base64 48 | tr -d '\n')"
    WORDPRESS_LOGGED_IN_SALT="$(openssl rand -base64 48 | tr -d '\n')"
    WORDPRESS_NONCE_SALT="$(openssl rand -base64 48 | tr -d '\n')"

    cat > "${ENV_FILE}" <<EOF
# Genere par templates/apps/wordpress/pre_install.sh
# NE PAS COMMITER — contient les secrets de la DB et les salts WP.
WORDPRESS_DB_NAME=${WORDPRESS_DB_NAME}
WORDPRESS_DB_USER=${WORDPRESS_DB_USER}
WORDPRESS_DB_PASSWORD=${WORDPRESS_DB_PASSWORD}
WORDPRESS_TABLE_PREFIX=wp_

# Cache key prefix (genere aleatoirement pour eviter les collisions si plusieurs
# WP partagent la meme instance Redis — pas le cas ici mais bonne pratique).
WORDPRESS_CACHE_KEY_SALT=${WORDPRESS_CACHE_KEY_SALT}

# WordPress security salts
WORDPRESS_AUTH_KEY=${WORDPRESS_AUTH_KEY}
WORDPRESS_SECURE_AUTH_KEY=${WORDPRESS_SECURE_AUTH_KEY}
WORDPRESS_LOGGED_IN_KEY=${WORDPRESS_LOGGED_IN_KEY}
WORDPRESS_NONCE_KEY=${WORDPRESS_NONCE_KEY}
WORDPRESS_AUTH_SALT=${WORDPRESS_AUTH_SALT}
WORDPRESS_SECURE_AUTH_SALT=${WORDPRESS_SECURE_AUTH_SALT}
WORDPRESS_LOGGED_IN_SALT=${WORDPRESS_LOGGED_IN_SALT}
WORDPRESS_NONCE_SALT=${WORDPRESS_NONCE_SALT}
EOF
    chmod 600 "${ENV_FILE}"
    ok "Secrets WordPress generes dans ${ENV_FILE}"
  fi
else
  info "Secrets WordPress existants preserves (${ENV_FILE})"
fi

# ---------- Generation des configs PHP (a chaque update) ----------
# php.ini, opcache.ini, nginx.conf sont templates KSF (utilisent __BASE_DIR__,
# __APP_INSTANCE__, __TZ_VALUE__, etc.) → on les rend via render_template a
# chaque update pour rester en sync avec le repo KSF.
if [ "${DRY_RUN:-false}" = true ]; then
  info "[DRY-RUN] Rendu de ${APP_TEMPLATE_DIR}/config/{php.ini,opcache.ini,nginx.conf}"
  info "[DRY-RUN] mkdir -p ${CONFIG_DIR}"
else
  mkdir -p "${CONFIG_DIR}"
  render_template "${APP_TEMPLATE_DIR}/config/php.ini" "${CONFIG_DIR}/php.ini"
  render_template "${APP_TEMPLATE_DIR}/config/opcache.ini" "${CONFIG_DIR}/opcache.ini"
  render_template "${APP_TEMPLATE_DIR}/config/nginx.conf" "${CONFIG_DIR}/nginx.conf"
  chown -R "${APP_PUID}:${APP_PGID}" "${CONFIG_DIR}" 2>/dev/null || true
  ok "Configs (php + nginx) generees dans ${CONFIG_DIR}"
fi
