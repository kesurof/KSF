#!/usr/bin/env bash
# Baseo pre_install : genere secrets, repertoires de donnees et .env (600).
#
# Variables disponibles (exportees par app_install / app_update / app_rebuild) :
#   APP_NAME, APP_DIR, APP_DATA, APP_PUID, APP_PGID, APP_HOST, APP_PORT,
#   APP_DOMAIN, APP_SUBDOMAIN, APP_TEMPLATE_DIR, BASE_DIR, NETWORK_NAME,
#   TZ_VALUE, DOCKER_GID, DRY_RUN, AUTO_YES
#
# Fichier produit :
#   ${APP_DIR}/.env                 : secrets Baseo + PostgreSQL, monte par
#                                     Compose comme env_file pour les services
#                                     baseo et postgres. BASEO_IMAGE y est
#                                     versionne pour piloter les mises a jour.
#
# Repertoires produits :
#   ${APP_DATA}/files               : photos et documents (monte sur /data)
#   ${APP_DATA}/config              : configuration persistante (monte sur /config)
#
# Idempotence : sur update / rebuild, les secrets existants sont preserves.
# Pour regenerer les secrets, supprimer ${APP_DIR}/.env avant de relancer.
#
# Compte admin initial : en mode interactif (AUTO_YES=false, stdin terminal),
# des questions posent l'adresse email et le mot de passe au deploiement. En
# non-interactif, des valeurs par defaut/aleatoires sont utilisees, surchargeables
# par BASEO_ADMIN_EMAIL et/ou BASEO_ADMIN_PASSWORD dans l'environnement.

set -euo pipefail

ENV_FILE="${APP_DIR}/.env"
DATA_DIR="${APP_DATA}/files"
CONFIG_DIR="${APP_DATA}/config"

# ---------- Repertoires de donnees persistantes ----------
if [ "${DRY_RUN:-false}" = true ]; then
  info "[DRY-RUN] mkdir -p ${DATA_DIR} ${CONFIG_DIR}"
else
  mkdir -p "${DATA_DIR}" "${CONFIG_DIR}"
  chown -R "${APP_PUID}:${APP_PGID}" "${APP_DATA}" 2>/dev/null || \
    warn "chown ${APP_DATA} a echoue (root-only ?). Les conteneurs pourraient ne pas pouvoir ecrire."
fi

# ---------- Generation du .env (idempotente) ----------
# Ce fichier est consomme par les services baseo et postgres avec env_file. Le
# Compose rendu ne depend donc d'aucun placeholder Baseo resolu apres le rendu.
# Si le .env existe deja (cas update/rebuild), ses secrets sont preserves.
umask 077
if [ ! -f "${ENV_FILE}" ]; then
  if [ "${DRY_RUN:-false}" = true ]; then
    info "[DRY-RUN] Generation de ${ENV_FILE} (secrets baseo + PostgreSQL)"
  else
    # Mot de passe PostgreSQL en hex : compatible avec une URL de connexion.
    POSTGRES_PASSWORD="$(openssl rand -hex 16)"
    # Compte admin initial : valeurs par defaut (email admin@<domaine>,
    # mot de passe aleatoire), surchargeables par BASEO_ADMIN_EMAIL /
    # BASEO_ADMIN_PASSWORD dans l'environnement. En mode interactif
    # (AUTO_YES=false et stdin sur un terminal), des questions sont posees au
    # deploiement pour fournir adresse email et mot de passe.
    BASEO_ADMIN_EMAIL_FINAL="admin@${APP_DOMAIN:-example.com}"
    BASEO_ADMIN_PASSWORD_FINAL="$(openssl rand -hex 24)"
    if [ -n "${BASEO_ADMIN_EMAIL:-}" ]; then
      BASEO_ADMIN_EMAIL_FINAL="${BASEO_ADMIN_EMAIL}"
    fi
    if [ -n "${BASEO_ADMIN_PASSWORD:-}" ]; then
      BASEO_ADMIN_PASSWORD_FINAL="${BASEO_ADMIN_PASSWORD}"
    fi

    if [ "${AUTO_YES:-false}" = false ] && [ -t 0 ]; then
      echo ""
      echo "Compte administrateur initial Baseo"
      while true; do
        echo -n "  Adresse email (défaut: ${BASEO_ADMIN_EMAIL_FINAL}) : "
        read -r email_input
        if [ -n "${email_input}" ]; then
          case "${email_input}" in
            *@*) BASEO_ADMIN_EMAIL_FINAL="${email_input}" ; break ;;
            *)   err "Adresse email invalide : ${email_input}" ;;
          esac
        else
          break
        fi
      done
      echo -n "  Mot de passe (vide = générer un mot de passe aléatoire) : "
      read -rs password_input
      echo ""
      if [ -n "${password_input}" ]; then
        BASEO_ADMIN_PASSWORD_FINAL="${password_input}"
      fi
    fi

    if [ -n "${APP_HOST:-}" ]; then
      BASEO_COOKIE_SECURE=true
    else
      BASEO_COOKIE_SECURE=false
    fi

    cat > "${ENV_FILE}" <<EOF
# Genere par templates/apps/baseo/pre_install.sh
# NE PAS COMMITER — contient les secrets PostgreSQL et le compte admin baseo.
BASEO_IMAGE=ghcr.io/kesurof/baseo:1.0.0-rc.2
POSTGRES_DB=baseo
POSTGRES_USER=baseo
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
DATABASE_URL=postgresql://baseo:${POSTGRES_PASSWORD}@postgres:5432/baseo
BASEO_ADMIN_EMAIL=${BASEO_ADMIN_EMAIL_FINAL}
BASEO_ADMIN_PASSWORD=${BASEO_ADMIN_PASSWORD_FINAL}
BASEO_COOKIE_SECURE=${BASEO_COOKIE_SECURE}
BASEO_AUTH_BYPASS=false
SMTP_ENABLED=false
SMTP_HOST=
SMTP_PORT=587
SMTP_FROM=
BASEO_BACKUP_PASSPHRASE=
EOF
    ok "Secrets Baseo generes dans ${ENV_FILE}"
    info "Compte admin initial : ${BASEO_ADMIN_EMAIL_FINAL}"
    info "Le mot de passe admin et les secrets sont dans ${ENV_FILE} (mode 600)."
  fi
else
  info "Secrets Baseo existants preserves (${ENV_FILE})"
fi

# Les secrets d'une instance ne doivent jamais etre lisibles par d'autres
# utilisateurs, y compris lorsqu'ils proviennent d'une installation anterieure.
if [ "${DRY_RUN:-false}" = true ]; then
  info "[DRY-RUN] chmod 600 ${ENV_FILE}"
else
  chmod 600 "${ENV_FILE}"
fi
