#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# KSF — Bootstrap
# Infrastructure : Docker, utilisateur, SSH, système
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

# ---------- Valeurs par défaut ----------
BASE_DIR="${BASE_DIR:-${HOME}/serverbox}"
TZ_VALUE="${TZ:-Europe/Paris}"
SKIP_SYSTEM=false
SKIP_DOCKER=false
AUTO_YES=false
CREATE_USER=""
SSH_KEY=""
SSH_HARDENING=false
DRY_RUN=false
BASE_DIR_SET=false
CREATE_RUNTIME_DIRS=true

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --base-dir PATH     Répertoire racine (défaut: ~/serverbox)
  --tz TZ             Fuseau horaire
  --skip-system       Saute la mise à jour APT/paquets
  --skip-docker       Saute l'installation de Docker
  --create-user USER  Crée un utilisateur système et l'ajoute au groupe sudo
  --ssh-key KEY       Clé publique SSH à installer (avec --create-user)
  --ssh-hardening     Désactive l'authentification SSH par mot de passe
  -y, --yes           Répondre oui automatiquement
  -h, --help          Affiche cette aide
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-dir)    BASE_DIR="$2"; BASE_DIR_SET=true; shift 2 ;;
    --tz)          TZ_VALUE="$2";     shift 2 ;;
    --skip-system) SKIP_SYSTEM=true;  shift ;;
    --skip-docker) SKIP_DOCKER=true;  shift ;;
    --create-user) CREATE_USER="$2";  shift 2 ;;
    --ssh-key)     SSH_KEY="$2";      shift 2 ;;
    --ssh-hardening) SSH_HARDENING=true; shift ;;
    -y|--yes)      AUTO_YES=true;     shift ;;
    -h|--help)     usage ;;
    *)             echo "Option inconnue: $1"; usage ;;
  esac
done

# ---------- Sécurité ----------
if [ "${EUID}" -eq 0 ]; then
  echo -e "\033[1;31m[ERREUR]\033[0m Ne lance pas ce script en root."
  exit 1
fi
if ! command -v sudo >/dev/null 2>&1; then
  echo -e "\033[1;31m[ERREUR]\033[0m sudo est requis."
  exit 1
fi
if [ -n "$SSH_KEY" ] && [ -z "$CREATE_USER" ]; then
  echo -e "\033[1;31m[ERREUR]\033[0m --ssh-key nécessite --create-user."
  exit 1
fi

PKG_MGR=$(detect_pkg_mgr)

# ---------- Dry-run ----------
if [ "$AUTO_YES" = false ]; then
  echo ""
  echo -n "Activer le mode dry-run (aucune modification) ? (oui/non) [non] : "
  read -r DRY_RUN_CONFIRM
  if [ "$DRY_RUN_CONFIRM" = "oui" ]; then
    DRY_RUN=true
  fi
fi

# ---------- Questions interactives ----------
if [ "$AUTO_YES" = false ]; then
  if [ -z "$CREATE_USER" ]; then
    echo ""
    echo -n "Créer un utilisateur système ? (oui/non) [non] : "
    read -r CREATE_USER_CONFIRM
    if [ "$CREATE_USER_CONFIRM" = "oui" ]; then
      echo -n "Nom d'utilisateur : "
      read -r CREATE_USER
    fi
  fi

  if [ -n "$CREATE_USER" ] && [ -z "$SSH_KEY" ]; then
    echo -n "Ajouter une clé SSH pour ${CREATE_USER} ? (oui/non) [non] : "
    read -r SSH_KEY_CONFIRM
    if [ "$SSH_KEY_CONFIRM" = "oui" ]; then
      echo -n "Colle ta clé publique SSH : "
      read -r SSH_KEY
    fi
  fi

  if [ "$SSH_HARDENING" = false ]; then
    echo -n "Désactiver l'authentification SSH par mot de passe ? (oui/non) [non] : "
    read -r SSH_HARDENING_CONFIRM
    if [ "$SSH_HARDENING_CONFIRM" = "oui" ]; then
      SSH_HARDENING=true
    fi
  fi

  if [ "$SSH_HARDENING" = true ] && [ -z "$SSH_KEY" ] && [ -z "$(ssh-add -l 2>/dev/null)" ]; then
    echo "Aucune clé SSH détectée."
    echo -n "Désactiver le mot de passe peut te verrouiller hors du serveur. Continuer ? (oui/non) [non] : "
    read -r HARDENING_CONFIRM
    if [ "$HARDENING_CONFIRM" != "oui" ]; then
      SSH_HARDENING=false
    fi
  fi

  echo ""
fi

TARGET_USER="${CREATE_USER:-$USER}"
if [ -n "$CREATE_USER" ] && [ "$BASE_DIR_SET" = false ]; then
  CREATE_RUNTIME_DIRS=false
fi

# ---------- Journalisation ----------
if [ "$CREATE_RUNTIME_DIRS" = false ]; then
  LOG_FILE="/tmp/ksf-bootstrap-$(date +%Y%m%d-%H%M%S).log"
else
  LOG_FILE="${BASE_DIR}/logs/bootstrap-$(date +%Y%m%d-%H%M%S).log"
  if [ "$TARGET_USER" != "$USER" ]; then
    sudo mkdir -p "${BASE_DIR}/logs"
    sudo chmod 1777 "${BASE_DIR}/logs"
  else
    mkdir -p "${BASE_DIR}/logs"
  fi
fi
exec > >(tee -a "$LOG_FILE") 2>&1

source "${SCRIPT_DIR}/lib/steps.sh"

# ---------- Exécution ----------
info "=== KSF Bootstrap ==="
info "Distribution : ${PKG_MGR} | Base : ${BASE_DIR}"

step_system
step_docker_install
step_user
step_ssh_hardening
if [ "$CREATE_RUNTIME_DIRS" = true ]; then
  step_dirs
else
  info "Arborescence runtime ignorée pendant la création utilisateur. Elle sera créée dans \${HOME}/serverbox après reconnexion et lancement de ./deploy.sh."
fi
step_docker_group

if [ -n "$CREATE_USER" ]; then
  info ""
  info "═══════════════════════════════════════════════════"
  info " Bootstrap terminé"
  info " Étape suivante :"
  info "   1. Déconnecte-toi (exit)"
  info "   2. Reconnecte-toi en SSH en tant que ${CREATE_USER}"
  info "   3. git clone https://github.com/kesurof/ksf.git"
  info "   4. cd ksf"
  info "   5. ./deploy.sh"
  info "═══════════════════════════════════════════════════"
else
  info "Bootstrap terminé. Lance maintenant : ./deploy.sh"
fi
