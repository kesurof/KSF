#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# KSF — Gestion de l'infrastructure existante
# Menu interactif, status, config, routes, render, restart, protect, doctor, clean-data, update, CrowdSec, trusted IPs
# ============================================================

_ksf_resolve_script_dir() {
  local source="$0"
  while [ -L "$source" ]; do
    local dir
    dir="$(cd -P "$(dirname "$source")" && pwd)"
    source="$(readlink "$source")"
    [[ "$source" != /* ]] && source="${dir}/${source}"
  done
  cd -P "$(dirname "$source")" && pwd
}

SCRIPT_DIR="$(_ksf_resolve_script_dir)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/render.sh"

BASE_DIR="${BASE_DIR:-${HOME}/serverbox}"
COMMAND=""
CLEAN_DATA_APP=""
UPDATE_SERVICE=""
CROWDSEC_COMMAND=""
CROWDSEC_ARG=""
CROWDSEC_DURATION=""
TRUSTED_IPS_COMMAND=""
TRUSTED_IPS_PROVIDER=""
DRY_RUN=false
AUTO_YES=false

usage() {
  cat <<EOF
Usage: $0 <command> [options]

Commandes :

  Menu :
  menu                  Afficher le menu interactif (par défaut sans argument)

  Diagnostic :
  status                Afficher l'état global (Traefik, OAuth2 Proxy, apps)
  config                Afficher la configuration locale (secrets masqués)
  routes                Analyser les routes Traefik dynamiques
  doctor                Diagnostic global de la plateforme

  Rendu / redémarrage :
  protect               Appliquer OAuth2 Proxy aux routes protégées
  render                Régénérer les fichiers dynamiques Traefik
  restart               Relancer Traefik, OAuth2 Proxy et CrowdSec

  Update :
  update <service>      Mettre à jour une stack système (crowdsec, traefik, oauth2, all)

  CrowdSec / AppSec :
  crowdsec <commande>   Gérer CrowdSec (status, logs, decisions, alerts, metrics, bouncers, ban, unban, flush-decisions, enroll, console-status, restart, appsec)

  Trusted IPs :
  trusted-ips cloudflare  Afficher les CIDR Cloudflare prêts pour TRAEFIK_TRUSTED_IPS
  trusted-ips apply cloudflare  Appliquer les CIDR Cloudflare et redémarrer Traefik

  Clean-data :
  clean-data [app]      Lister ou supprimer les données conservées

  CLI :
  install-cli           Installer / réparer la commande globale ksf
  uninstall-cli         Supprimer la commande globale ksf

Options :
  --base-dir PATH       Répertoire racine (défaut: ~/serverbox)
  --dry-run             Affiche les actions sans modifier les fichiers
  -y, --yes             Mode automatique
  -h, --help            Affiche l'aide

Exemples :
  $0 status
  $0 doctor
  $0 render --dry-run
  $0 restart
  $0 update crowdsec
  $0 update traefik
  $0 update oauth2
  $0 update all --dry-run
  $0 crowdsec status
  $0 crowdsec ban 1.2.3.4 10m
  $0 crowdsec appsec status
  $0 trusted-ips cloudflare
  $0 trusted-ips apply cloudflare
  $0 clean-data
  $0 clean-data radarr
  $0 install-cli
  $0 uninstall-cli
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  if [ -n "$COMMAND" ]; then
    case "$COMMAND" in
      crowdsec)
        case "$1" in
          --base-dir|--dry-run|-y|--yes|-h|--help) ;;
          *)
            if [ -z "$CROWDSEC_COMMAND" ]; then
              CROWDSEC_COMMAND="$1"
              shift
              continue
            fi
            if [ -z "$CROWDSEC_ARG" ]; then
              case "$CROWDSEC_COMMAND" in
                ban|unban|enroll|appsec)
                  CROWDSEC_ARG="$1"
                  shift
                  continue
                  ;;
              esac
            fi
            if [ -z "$CROWDSEC_DURATION" ] && [ "$CROWDSEC_COMMAND" = "ban" ]; then
              CROWDSEC_DURATION="$1"
              shift
              continue
            fi
            if [ "$CROWDSEC_COMMAND" = "enroll" ]; then
              CROWDSEC_ARG="${CROWDSEC_ARG} $1"
              shift
              continue
            fi
            ;;
        esac
        ;;
      trusted-ips)
        case "$1" in
          --base-dir|--dry-run|-y|--yes|-h|--help) ;;
          *)
            if [ -z "$TRUSTED_IPS_COMMAND" ]; then
              TRUSTED_IPS_COMMAND="$1"
              shift
              continue
            fi
            if [ "$TRUSTED_IPS_COMMAND" = "apply" ] && [ -z "$TRUSTED_IPS_PROVIDER" ]; then
              TRUSTED_IPS_PROVIDER="$1"
              shift
              continue
            fi
            ;;
        esac
        ;;
      clean-data)
        case "$1" in
          --base-dir|--dry-run|-y|--yes|-h|--help) ;;
          *)
            if [ -z "$CLEAN_DATA_APP" ]; then
              CLEAN_DATA_APP="$1"
              shift
              continue
            fi
            ;;
        esac
        ;;
      update)
        case "$1" in
          --base-dir|--dry-run|-y|--yes|-h|--help) ;;
          *)
            if [ -z "$UPDATE_SERVICE" ]; then
              UPDATE_SERVICE="$1"
              shift
              continue
            fi
            ;;
        esac
        ;;
    esac
  fi

  case "$1" in
    menu|status|config|routes|protect|render|restart|doctor|clean-data|update|crowdsec|trusted-ips|install-cli|uninstall-cli)
      if [ -n "$COMMAND" ]; then
        err "Commande déjà définie : ${COMMAND}"
        exit 1
      fi
      COMMAND="$1"
      shift
      ;;
    --base-dir)
      ksf_require_option_value "$1" "$#" || exit 1
      BASE_DIR="$2"
      shift 2
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
      if [ "$COMMAND" = "clean-data" ] && [ -z "$CLEAN_DATA_APP" ]; then
        CLEAN_DATA_APP="$1"
        shift
      elif [ "$COMMAND" = "crowdsec" ] && [ -z "$CROWDSEC_COMMAND" ]; then
        CROWDSEC_COMMAND="$1"
        shift
      elif [ "$COMMAND" = "crowdsec" ] && [ -z "$CROWDSEC_ARG" ]; then
        case "$CROWDSEC_COMMAND" in
          ban|unban|enroll|appsec)
            CROWDSEC_ARG="$1"
            shift
            ;;
          *)
            err "Argument inconnu : $1"
            usage
            ;;
        esac
      elif [ "$COMMAND" = "crowdsec" ] && [ -z "$CROWDSEC_DURATION" ] && [ "$CROWDSEC_COMMAND" = "ban" ]; then
        CROWDSEC_DURATION="$1"
        shift
      elif [ "$COMMAND" = "update" ] && [ -z "$UPDATE_SERVICE" ]; then
        UPDATE_SERVICE="$1"
        shift
      else
        err "Argument inconnu : $1"
        usage
      fi
      ;;
  esac
done

if [ -z "$COMMAND" ]; then
  source "${SCRIPT_DIR}/lib/menu.sh"
  menu_main
  exit 0
fi

source "${SCRIPT_DIR}/lib/manage_steps.sh"
source "${SCRIPT_DIR}/lib/update_steps.sh"

# ---------- Install / uninstall CLI ----------

manage_install_cli() {
  local link_path="${HOME}/.local/bin/ksf"
  local target="${SCRIPT_DIR}/ksf.sh"
  local bin_dir
  bin_dir="$(dirname "$link_path")"

  info "Installation de la commande globale ksf..."
  info "Cible : ${target}"
  info "Lien  : ${link_path}"

  if [ ! -f "$target" ]; then
    err "Script ksf.sh introuvable : ${target}"
    exit 1
  fi

  run mkdir -p "$bin_dir"

  if [ ! -x "$target" ]; then
    info "Rendre ksf.sh exécutable..."
    run chmod +x "$target"
  fi

  if [ -L "$link_path" ]; then
    local current_target
    current_target="$(readlink -f "$link_path" 2>/dev/null || true)"
    local real_target
    real_target="$(readlink -f "$target" 2>/dev/null || true)"
    if [ "$current_target" = "$real_target" ]; then
      ok "Le lien existe déjà et pointe vers le bon fichier."
    else
      warn "Le lien existe mais pointe vers : ${current_target}"
      if [ "${AUTO_YES:-false}" = true ] || _manage_cli_confirm "Remplacer le lien existant ?"; then
        run rm -f "$link_path"
        run ln -s "$target" "$link_path"
        ok "Lien mis à jour."
      else
        info "Installation annulée."
        return 0
      fi
    fi
  elif [ -e "$link_path" ]; then
    warn "${link_path} existe mais n'est pas un lien symbolique."
    if [ "${AUTO_YES:-false}" = true ] || _manage_cli_confirm "Remplacer ce fichier par un lien vers ksf.sh ?"; then
      run rm -f "$link_path"
      run ln -s "$target" "$link_path"
      ok "Fichier remplacé par un lien."
    else
      info "Installation annulée."
      return 0
    fi
  else
    run ln -s "$target" "$link_path"
    ok "Lien créé."
  fi

  echo ""
  ok "Commande ksf installée : ${link_path}"

  _manage_cli_ensure_path_block

  export PATH="${HOME}/.local/bin:${PATH}"

  echo ""
  ok "Installation terminée. La commande sera disponible après rechargement du shell ou reconnexion SSH."
  info "Pour une disponibilité immédiate :"
  echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
}

manage_uninstall_cli() {
  local link_path="${HOME}/.local/bin/ksf"

  info "Désinstallation de la commande globale ksf..."

  if [ -L "$link_path" ]; then
    local target
    target="$(readlink -f "$link_path" 2>/dev/null || true)"
    info "Lien trouvé : ${link_path} → ${target}"
    if [ "${AUTO_YES:-false}" = true ] || _manage_cli_confirm "Supprimer ce lien ?"; then
      run rm -f "$link_path"
      ok "Lien supprimé : ${link_path}"
    else
      info "Désinstallation annulée."
    fi
  elif [ -e "$link_path" ]; then
    warn "${link_path} existe mais n'est pas un lien symbolique."
    if [ "${AUTO_YES:-false}" = true ] || _manage_cli_confirm "Supprimer ce fichier ksf non lié ?"; then
      run rm -f "$link_path"
      ok "Fichier supprimé : ${link_path}"
    else
      warn "Aucune suppression effectuée pour éviter tout dommage."
    fi
  else
    ok "Aucun lien ksf trouvé dans ~/.local/bin/."
  fi
}

_manage_cli_confirm() {
  local message="${1:-Continuer ?}"
  echo ""
  echo -n "${message} (oui/non) : "
  local answer
  read -r answer
  case "$answer" in
    o|O|oui|Oui|OUI|y|Y|yes|Yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

_manage_cli_has_path_block() {
  local file="$1"
  [ -f "$file" ] && grep -qF "# KSF CLI" "$file" 2>/dev/null
}

_manage_cli_ensure_path_block() {
  local profile="${HOME}/.profile"
  local bashrc="${HOME}/.bashrc"

  if _manage_cli_has_path_block "$profile"; then
    info "Bloc KSF déjà présent dans ${profile}."
  else
    if [ ! -f "$profile" ]; then
      info "Création de ${profile}..."
      run touch "$profile"
    fi
    info "Ajout du bloc PATH dans ${profile}..."
    if [ "${DRY_RUN:-false}" = true ]; then
      warn "[DRY-RUN] Ajout du bloc PATH dans ${profile}"
    else
    {
      echo ""
      echo "# KSF CLI"
      echo "export PATH=\"\$HOME/.local/bin:\$PATH\""
    } >> "$profile"
    fi
    ok "Bloc ajouté dans ${profile}."
  fi

  if _manage_cli_has_path_block "$bashrc"; then
    info "Bloc KSF déjà présent dans ${bashrc}."
  else
    if [ ! -f "$bashrc" ]; then
      info "Création de ${bashrc}..."
      run touch "$bashrc"
    fi
    info "Ajout du bloc PATH dans ${bashrc}..."
    if [ "${DRY_RUN:-false}" = true ]; then
      warn "[DRY-RUN] Ajout du bloc PATH dans ${bashrc}"
    else
    {
      echo ""
      echo "# KSF CLI"
      echo "export PATH=\"\$HOME/.local/bin:\$PATH\""
    } >> "$bashrc"
    fi
    ok "Bloc ajouté dans ${bashrc}."
  fi
}

_manage_cli_path_contains() {
  local dir="$1"
  local IFS=':'
  local p
  for p in $PATH; do
    [ "$p" = "$dir" ] && return 0
  done
  return 1
}

case "$COMMAND" in
  menu)
    source "${SCRIPT_DIR}/lib/menu.sh"
    menu_main
    ;;
  status)
    manage_status
    ;;
  config)
    manage_config
    ;;
  routes)
    manage_routes
    ;;
  protect)
    manage_protect
    ;;
  render)
    manage_render
    ;;
  restart)
    manage_restart
    ;;
  doctor)
    manage_doctor
    ;;
  clean-data)
    manage_clean_data "${CLEAN_DATA_APP}"
    ;;
  update)
    manage_update "${UPDATE_SERVICE}"
    ;;
  crowdsec)
    manage_crowdsec "${CROWDSEC_COMMAND}" "${CROWDSEC_ARG}" "${CROWDSEC_DURATION}"
    ;;
  trusted-ips)
    manage_trusted_ips "${TRUSTED_IPS_COMMAND}" "${TRUSTED_IPS_PROVIDER}"
    ;;
  install-cli)
    manage_install_cli
    ;;
  uninstall-cli)
    manage_uninstall_cli
    ;;
esac
