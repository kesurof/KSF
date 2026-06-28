#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# KSF — Gestion des applications
# Install / update / restart / disable / remove / status / logs / list / configure
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

BASE_DIR="${BASE_DIR:-${HOME}/serverbox}"
: "${NETWORK_NAME:=ksf-proxy}"
: "${TZ_VALUE:=${TZ:-Europe/Paris}}"
AUTO_YES=false
DRY_RUN=false
COMMAND=""
APP_NAME=""
APP_HOST_OVERRIDE=""
APP_SUBDOMAIN_OVERRIDE=""
APP_DOMAIN_OVERRIDE=""
APP_PORT_OVERRIDE=""
APP_HOST_PORT_OVERRIDE=""
APP_NO_HOST_PORT_OVERRIDE=false
APP_INSTANCE_OVERRIDE=""
APP_AUTH_CHOICE="ask"
APP_LOCAL_ONLY=false

usage() {
  cat <<EOF
Usage: $0 <command> [template|instance] [options]

Commands:
  list                  Liste les templates d'apps disponibles
  installed             Liste les apps installées
  install <template>    Installe une app depuis un template
  status <instance>     Affiche l'état Docker d'une app installée
  update <instance>     Met à jour une app installée (build incrémental)
  configure <instance>  Modifie l'accès d'une app installée (host, domaine, sous-domaine, port hôte local)
  rebuild <instance>    Reconstruit l'image d'une app installée sans cache puis recrée le container
  start <instance>      Démarre une app installée
  stop <instance>       Arrête une app installée sans suppression
  restart <instance>    Redémarre une app installée
  disable <instance>    Désactive une app installée sans supprimer ses données
  logs <instance>       Affiche les logs Docker Compose d'une app installée
  remove <instance>     Supprime une app installée puis propose de supprimer les données locales conservées

Options:
  --base-dir PATH       Répertoire racine (défaut: ~/serverbox)
  --domain DOMAIN       Domaine principal pour cette instance
  --subdomain NAME      Sous-domaine de l'instance (défaut: nom de l'instance)
  --host HOST           Hostname complet de l'instance
  --port PORT           Port interne Docker de l'instance (override le port du template)
  --host-port PORT      Port publié sur 127.0.0.1 pour l'accès local hôte
  --no-host-port        Supprime la publication locale sur l'hôte
  --instance NAME       Nom d'instance (permet d'installer plusieurs fois le même template)
  --auth                Protège cette instance avec OAuth2 Proxy (si OAuth2 Proxy est configuré)
  --no-auth             N'applique pas OAuth2 à cette instance
  --local-only          Ne génère pas de route Traefik
  --dry-run             Affiche les actions sans modifier les fichiers
  -y, --yes             Répondre oui automatiquement
  -h, --help            Affiche l'aide

Exemples:
  $0 list
  $0 install radarr
  $0 install radarr --subdomain films --auth
  $0 install radarr --subdomain films --host-port 17878 --auth
  $0 install radarr --host radarr.example.com --no-auth
  $0 install wordpress --subdomain blog --instance blog
  $0 install wordpress --subdomain shop --instance shop
  $0 status radarr
  $0 update radarr --dry-run
  $0 configure blog --subdomain articles
  $0 configure blog --domain example.net
  $0 configure blog --host blog.example.net
  $0 logs radarr
  $0 restart radarr
  $0 disable radarr --dry-run
  $0 remove radarr
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    list|installed|install|status|update|configure|rebuild|start|stop|restart|disable|logs|remove)
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
    --host-port)
      APP_HOST_PORT_OVERRIDE="$2"
      APP_NO_HOST_PORT_OVERRIDE=false
      shift 2
      ;;
    --no-host-port)
      APP_HOST_PORT_OVERRIDE=""
      APP_NO_HOST_PORT_OVERRIDE=true
      shift
      ;;
    --instance)
      APP_INSTANCE_OVERRIDE="$2"
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
      if { [ "$COMMAND" = "install" ] || [ "$COMMAND" = "status" ] || [ "$COMMAND" = "update" ] || [ "$COMMAND" = "configure" ] || [ "$COMMAND" = "rebuild" ] || [ "$COMMAND" = "start" ] || [ "$COMMAND" = "stop" ] || [ "$COMMAND" = "restart" ] || [ "$COMMAND" = "disable" ] || [ "$COMMAND" = "logs" ] || [ "$COMMAND" = "remove" ]; } && [ -z "$APP_NAME" ]; then
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
  # Préserve BASE_DIR (et autres variables contrôlées par l'appelant) si elles
  # sont déjà set : ksf.env peut contenir une valeur différente si la plateforme
  # a été installée ailleurs. L'env var / --base-dir reste source de vérité.
  __ksf_saved_BASE_DIR="$BASE_DIR"
  __ksf_saved_NETWORK_NAME="$NETWORK_NAME"
  __ksf_saved_TZ_VALUE="$TZ_VALUE"
  source "$KSF_ENV"
  BASE_DIR="${__ksf_saved_BASE_DIR:-$BASE_DIR}"
  NETWORK_NAME="${__ksf_saved_NETWORK_NAME:-$NETWORK_NAME}"
  TZ_VALUE="${__ksf_saved_TZ_VALUE:-$TZ_VALUE}"
  unset __ksf_saved_BASE_DIR __ksf_saved_NETWORK_NAME __ksf_saved_TZ_VALUE
fi

source "${SCRIPT_DIR}/lib/app_steps.sh"

case "${COMMAND}" in
  list)
    app_list_available
    ;;
  installed)
    app_list_installed
    ;;
  install)
    if [ -z "$APP_NAME" ]; then
      err "Nom de template requis."
      exit 1
    fi
    app_install "$APP_NAME"
    ;;
  status)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'instance requis."
      exit 1
    fi
    app_status "$APP_NAME"
    ;;
  update)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'instance requis."
      exit 1
    fi
    app_update "$APP_NAME"
    ;;
  configure)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'instance requis."
      exit 1
    fi
    app_configure "$APP_NAME"
    ;;
  rebuild)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'instance requis."
      exit 1
    fi
    app_rebuild "$APP_NAME"
    ;;
  start)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'instance requis."
      exit 1
    fi
    app_start "$APP_NAME"
    ;;
  stop)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'instance requis."
      exit 1
    fi
    app_stop "$APP_NAME"
    ;;
  restart)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'instance requis."
      exit 1
    fi
    app_restart "$APP_NAME"
    ;;
  disable)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'instance requis."
      exit 1
    fi
    app_disable "$APP_NAME"
    ;;
  logs)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'instance requis."
      exit 1
    fi
    app_logs "$APP_NAME"
    ;;
  remove)
    if [ -z "$APP_NAME" ]; then
      err "Nom d'instance requis."
      exit 1
    fi
    app_remove "$APP_NAME"
    ;;
esac
