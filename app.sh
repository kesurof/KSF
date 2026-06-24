#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# KSF — Gestion des applications
# Install / update / restart / disable / remove / status / logs / list
# ============================================================

_app_resolve_script_dir() {
  local source="$0"
  while [ -L "$source" ]; do
    local dir
    dir="$(cd -P "$(dirname "$source")" && pwd)"
    source="$(readlink "$source")"
    [[ "$source" != /* ]] && source="${dir}/${source}"
  done
  cd -P "$(dirname "$source")" && pwd
}

SCRIPT_DIR="$(_app_resolve_script_dir)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/render.sh"

BASE_DIR="${HOME}/serverbox"
AUTO_YES=false
DRY_RUN=false
COMMAND=""
APP_NAME=""
APP_HOST_OVERRIDE=""
APP_SUBDOMAIN_OVERRIDE=""
APP_DOMAIN_OVERRIDE=""
APP_PORT_OVERRIDE=""
APP_AUTH_CHOICE="ask"
APP_LOCAL_ONLY=false

usage() {
  cat <<EOF
Usage: $0 <command> [app] [options]

Commands:
  list                  Liste les apps disponibles
  installed             Liste les apps installées
  install <app>         Installe une app
  status <app>          Affiche l'état Docker d'une app installée
  update <app>          Met à jour une app (build incrémental)
  rebuild <app>         Reconstruit l'image sans cache puis recrée le container
  start <app>           Démarre une app installée
  stop <app>            Arrête une app installée sans suppression
  restart <app>         Redémarre une app installée
  disable <app>         Désactive une app sans supprimer ses données
  logs <app>            Affiche les logs Docker Compose d'une app
  remove <app>          Supprime une app (données préservées)

Options:
  --base-dir PATH       Répertoire racine (défaut: ~/serverbox)
  --domain DOMAIN       Domaine principal pour cette app
  --subdomain NAME      Sous-domaine de l'app (défaut: nom de l'app)
  --host HOST           Hostname complet de l'app
  --port PORT           Port de l'app (override le port du template)
  --auth                Protège l'app avec OAuth2 Proxy (si OAuth2 Proxy est configuré)
  --no-auth             N'applique pas OAuth2 à cette app
  --local-only          Ne génère pas de route Traefik
  --dry-run             Affiche les actions sans modifier les fichiers
  -y, --yes             Répondre oui automatiquement
  -h, --help            Affiche l'aide

Exemples:
  $0 list
  $0 install radarr
  $0 install radarr --subdomain films --auth
  $0 install radarr --host radarr.example.com --no-auth
  $0 status radarr
  $0 update radarr --dry-run
  $0 logs radarr
  $0 restart radarr
  $0 disable radarr --dry-run
  $0 remove radarr
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    list|installed|install|status|update|rebuild|start|stop|restart|disable|logs|remove)
      if [ -n "$COMMAND" ]; then
        err "Commande déjà définie : ${COMMAND}"
        exit 1
      fi
      COMMAND="$1"
      shift
      ;;
    --base-dir)
      BASE_DIR="$2"
      shift 2
      ;;
    --domain)
      APP_DOMAIN_OVERRIDE="$2"
      shift 2
      ;;
    --subdomain)
      APP_SUBDOMAIN_OVERRIDE="$2"
      shift 2
      ;;
    --host)
      APP_HOST_OVERRIDE="$2"
      shift 2
      ;;
    --port)
      APP_PORT_OVERRIDE="$2"
      shift 2
      ;;
    --auth)
      APP_AUTH_CHOICE="true"
      shift
      ;;
    --no-auth)
      APP_AUTH_CHOICE="false"
      shift
      ;;
    --local-only)
      APP_LOCAL_ONLY=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -y|--yes)
      AUTO_YES=true
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      if { [ "$COMMAND" = "install" ] || [ "$COMMAND" = "status" ] || [ "$COMMAND" = "update" ] || [ "$COMMAND" = "rebuild" ] || [ "$COMMAND" = "start" ] || [ "$COMMAND" = "stop" ] || [ "$COMMAND" = "restart" ] || [ "$COMMAND" = "disable" ] || [ "$COMMAND" = "logs" ] || [ "$COMMAND" = "remove" ]; } && [ -z "$APP_NAME" ]; then
        APP_NAME="$1"
        shift
      else
        err "Argument inconnu : $1"
        usage
      fi
      ;;
  esac
done

if [ -z "$COMMAND" ]; then
  usage
fi

KSF_ENV="${BASE_DIR}/config/ksf.env"
if [ -f "$KSF_ENV" ]; then
  source "$KSF_ENV"
fi

source "${SCRIPT_DIR}/lib/app_steps.sh"
source "${SCRIPT_DIR}/lib/backup_steps.sh"

case "${COMMAND}" in
  list)
    app_list_available
    ;;
  installed)
    app_list_installed
    ;;
  install)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'application requis."
      exit 1
    fi
    app_install "$APP_NAME"
    ;;
  status)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'application requis."
      exit 1
    fi
    app_status "$APP_NAME"
    ;;
  update)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'application requis."
      exit 1
    fi
    app_update "$APP_NAME"
    ;;
  rebuild)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'application requis."
      exit 1
    fi
    app_rebuild "$APP_NAME"
    ;;
  start)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'application requis."
      exit 1
    fi
    app_start "$APP_NAME"
    ;;
  stop)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'application requis."
      exit 1
    fi
    app_stop "$APP_NAME"
    ;;
  restart)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'application requis."
      exit 1
    fi
    app_restart "$APP_NAME"
    ;;
  disable)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'application requis."
      exit 1
    fi
    app_disable "$APP_NAME"
    ;;
  logs)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'application requis."
      exit 1
    fi
    app_logs "$APP_NAME"
    ;;
  remove)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'application requis."
      exit 1
    fi
    app_remove "$APP_NAME"
    ;;
esac
