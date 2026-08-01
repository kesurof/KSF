#!/usr/bin/env bash
# Speedtest Tracker pre_install : genere APP_KEY et APP_URL.
#
# Variables disponibles (exportees par app_install / app_update / app_rebuild) :
#   APP_NAME, APP_DIR, APP_DATA, APP_PUID, APP_PGID, APP_HOST, APP_PORT,
#   APP_HOST_PORT, APP_TEMPLATE_DIR, BASE_DIR, NETWORK_NAME, TZ_VALUE,
#   DOCKER_GID, DRY_RUN, AUTO_YES
#
# Fichier produit :
#   ${APP_DIR}/.env                 : APP_KEY + APP_URL, monte par Compose
#                                     en env_file pour cette instance
#
# Idempotence : sur update / rebuild / reinstallation, la APP_KEY existante
# est preservee (changer la cle rendrait illisibles les valeurs chiffrees en
# base). APP_URL est regeneree a partir de la configuration d'acces courante.

set -euo pipefail

ENV_FILE="${APP_DIR}/.env"

APP_KEY=""
if [ -f "${ENV_FILE}" ]; then
  APP_KEY="$(sed -n 's/^APP_KEY=//p' "${ENV_FILE}" | head -n1 || true)"
fi

if [ -z "${APP_KEY}" ]; then
  if [ "${DRY_RUN:-false}" = true ]; then
    info "[DRY-RUN] Generation d'une nouvelle APP_KEY"
  else
    APP_KEY="base64:$(openssl rand -base64 32 2>/dev/null | tr -d '\n')"
  fi
else
  info "APP_KEY existante preservee."
fi

if [ "${DRY_RUN:-false}" = true ]; then
  info "[DRY-RUN] Rendu de ${ENV_FILE} (APP_URL depuis ${APP_HOST:-local})"
else
  if [ -n "${APP_HOST:-}" ]; then
    APP_URL="https://${APP_HOST}"
  elif [ -n "${APP_HOST_PORT:-}" ]; then
    APP_URL="http://127.0.0.1:${APP_HOST_PORT}"
  else
    APP_URL="http://127.0.0.1:${APP_PORT:-80}"
  fi

  umask 077
  cat > "${ENV_FILE}" <<EOF
# Genere par templates/apps/speedtest-tracker/pre_install.sh
# NE PAS COMMITER — contient la cle de chiffrement de l'instance.
APP_KEY=${APP_KEY}
APP_URL=${APP_URL}
EOF
  chmod 600 "${ENV_FILE}"
  ok "Secrets Speedtest Tracker generes dans ${ENV_FILE}"
fi
