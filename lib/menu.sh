#!/usr/bin/env bash
# ============================================================
# KSF — Menu interactif
# Appelle les commandes existantes via ksf.sh / app.sh
# ============================================================

_menu_pause() {
  echo ""
  read -rp "Appuie sur Entrée pour revenir au menu..." _
}

_menu_confirm() {
  local message="$1"
  echo ""
  echo -n "${message} (oui/non) : "
  local answer
  read -r answer
  case "$answer" in
    o|O|oui|Oui|OUI|y|Y|yes|Yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

_menu_header() {
  echo ""
  echo "========================================"
  echo "  KSF — Menu interactif"
  echo "========================================"
  echo ""
}

_menu_ksf() {
  bash "${SCRIPT_DIR}/ksf.sh" "$@"
}

_menu_app() {
  bash "${SCRIPT_DIR}/app.sh" "$@"
}

_menu_cli_path_contains() {
  local dir="$1"
  local IFS=':'
  local p
  for p in $PATH; do
    [ "$p" = "$dir" ] && return 0
  done
  return 1
}

_menu_pick_installed_app() {
  local apps=()
  local env_dir="${BASE_DIR}/config/installed-apps"
  if [ ! -d "$env_dir" ]; then
    err "Aucune app installée (dossier absent)."
    return 1
  fi
  local f
  for f in "${env_dir}"/*.env; do
    [ -f "$f" ] || continue
    apps+=("$(basename "$f" .env)")
  done
  if [ "${#apps[@]}" -eq 0 ]; then
    err "Aucune app installée."
    return 1
  fi
  echo ""
  echo "Apps installées :"
  local i=1
  for app in "${apps[@]}"; do
    echo "  ${i}) ${app}"
    ((i++))
  done
  echo ""
  local num
  read -rp "Numéro de l'app (0 pour annuler) : " num
  if [ "$num" = "0" ] || [ -z "$num" ]; then
    return 1
  fi
  if ! [[ "$num" =~ ^[0-9]+$ ]] || [ "$num" -lt 1 ] || [ "$num" -gt "${#apps[@]}" ]; then
    err "Choix invalide."
    return 1
  fi
  echo "${apps[$((num-1))]}"
}

# ---------- État du serveur ----------

_menu_server_status() {
  while true; do
    _menu_header
    echo "=== État du serveur ==="
    echo ""
    echo "  1) Diagnostic global (doctor)"
    echo "  2) Afficher les routes"
    echo "  3) Afficher les apps installées"
    echo "  4) Retour"
    echo ""
    local choice
    read -rp "Choix [1-4] : " choice
    case "$choice" in
      1) _menu_ksf doctor ;;
      2) _menu_ksf routes ;;
      3) _menu_app installed ;;
      4) return ;;
      *) err "Choix invalide." ;;
    esac
    _menu_pause
  done
}

# ---------- Mettre à jour ----------

_menu_update() {
  while true; do
    _menu_header
    echo "=== Mettre à jour ==="
    echo ""
    echo "  1) Update all"
    echo "  2) Update Traefik"
    echo "  3) Update OAuth2 Proxy"
    echo "  4) Update CrowdSec"
    echo "  5) Render uniquement"
    echo "  6) Retour"
    echo ""
    local choice
    read -rp "Choix [1-6] : " choice
    case "$choice" in
      1)
        if _menu_confirm "Mettre à jour tous les services système ?"; then
          _menu_ksf update all
        fi
        ;;
      2)
        if _menu_confirm "Mettre à jour Traefik ?"; then
          _menu_ksf update traefik
        fi
        ;;
      3)
        if _menu_confirm "Mettre à jour OAuth2 Proxy ?"; then
          _menu_ksf update oauth2
        fi
        ;;
      4)
        if _menu_confirm "Mettre à jour CrowdSec ?"; then
          _menu_ksf update crowdsec
        fi
        ;;
      5)
        _menu_ksf render
        ;;
      6) return ;;
      *) err "Choix invalide." ;;
    esac
    _menu_pause
  done
}

# ---------- Applications ----------

_menu_apps() {
  while true; do
    _menu_header
    echo "=== Gérer les applications ==="
    echo ""
    echo "  1) Lister les apps disponibles"
    echo "  2) Lister les apps installées"
    echo "  3) Installer une app"
    echo "  4) Mettre à jour une app"
    echo "  5) Redémarrer une app"
    echo "  6) Désactiver une app"
    echo "  7) Supprimer une app"
    echo "  8) Retour"
    echo ""
    local choice app_name
    read -rp "Choix [1-8] : " choice
    case "$choice" in
      1) _menu_app list ;;
      2) _menu_app installed ;;
      3)
        read -rp "Nom de l'app à installer : " app_name
        if [ -n "$app_name" ]; then
          if _menu_confirm "Installer ${app_name} ?"; then
            _menu_app install "$app_name"
          fi
        fi
        ;;
      4)
        app_name=$(_menu_pick_installed_app) || { _menu_pause; continue; }
        if _menu_confirm "Mettre à jour ${app_name} ?"; then
          _menu_app update "$app_name"
        fi
        ;;
      5)
        app_name=$(_menu_pick_installed_app) || { _menu_pause; continue; }
        if _menu_confirm "Redémarrer ${app_name} ?"; then
          _menu_app restart "$app_name"
        fi
        ;;
      6)
        app_name=$(_menu_pick_installed_app) || { _menu_pause; continue; }
        if _menu_confirm "ATTENTION : Désactiver ${app_name} ? (destructif)"; then
          _menu_app disable "$app_name"
        fi
        ;;
      7)
        app_name=$(_menu_pick_installed_app) || { _menu_pause; continue; }
        if _menu_confirm "ATTENTION : Supprimer ${app_name} ? (données conservées mais stack supprimée)"; then
          _menu_app remove "$app_name"
        fi
        ;;
      8) return ;;
      *) err "Choix invalide." ;;
    esac
    _menu_pause
  done
}

# ---------- Sécurité ----------

_menu_security() {
  while true; do
    _menu_header
    echo "=== Sécurité ==="
    echo ""
    echo "  1) Voir les alertes CrowdSec"
    echo "  2) Voir les métriques CrowdSec"
    echo "  3) Voir les bouncers"
    echo "  4) Voir le statut AppSec / WAF"
    echo "  5) Retour"
    echo ""
    local choice
    read -rp "Choix [1-5] : " choice
    case "$choice" in
      1) _menu_ksf crowdsec alerts ;;
      2) _menu_ksf crowdsec metrics ;;
      3) _menu_ksf crowdsec bouncers ;;
      4) _menu_ksf crowdsec appsec status ;;
      5) return ;;
      *) err "Choix invalide." ;;
    esac
    _menu_pause
  done
}

# ---------- Logs ----------

_menu_logs() {
  local traefik_dir="${BASE_DIR}/proxy/traefik"
  local oauth2_dir="${BASE_DIR}/proxy/oauth2-proxy"

  while true; do
    _menu_header
    echo "=== Logs ==="
    echo ""
    echo "  1) Logs Traefik"
    echo "  2) Logs OAuth2 Proxy"
    echo "  3) Logs CrowdSec"
    echo "  4) Logs d'une app installée"
    echo "  5) Retour"
    echo ""
    local choice app_name
    read -rp "Choix [1-5] : " choice
    case "$choice" in
      1)
        if [ -f "${traefik_dir}/docker-compose.yml" ]; then
          (cd "${traefik_dir}" && docker compose logs --tail=200 traefik)
        else
          warn "Stack Traefik absente : ${traefik_dir}/docker-compose.yml"
        fi
        ;;
      2)
        if [ -f "${oauth2_dir}/docker-compose.yml" ]; then
          (cd "${oauth2_dir}" && docker compose logs --tail=200 oauth2-proxy)
        else
          warn "Stack OAuth2 Proxy absente : ${oauth2_dir}/docker-compose.yml"
        fi
        ;;
      3) _menu_ksf crowdsec logs ;;
      4)
        app_name=$(_menu_pick_installed_app) || { _menu_pause; continue; }
        _menu_app logs "$app_name"
        ;;
      5) return ;;
      *) err "Choix invalide." ;;
    esac
    _menu_pause
  done
}

# ---------- Paramètres KSF ----------

_menu_settings() {
  while true; do
    _menu_header
    echo "=== Paramètres KSF ==="
    echo ""
    echo "  1) Installer / réparer la commande globale ksf"
    echo "  2) Désinstaller la commande globale ksf"
    echo "  3) Vérifier la commande globale ksf"
    echo "  4) Retour"
    echo ""
    local choice
    read -rp "Choix [1-4] : " choice
    case "$choice" in
      1) _menu_ksf install-cli ;;
      2)
        if _menu_confirm "Désinstaller la commande globale ksf ?"; then
          _menu_ksf uninstall-cli
        fi
        ;;
      3)
        echo ""
        echo "=== Vérification de la commande ksf ==="
        echo ""
        local link_path="${HOME}/.local/bin/ksf"
        local bin_dir
        bin_dir="$(dirname "$link_path")"

        if [ -L "$link_path" ]; then
          local link_target
          link_target="$(readlink -f "$link_path" 2>/dev/null || true)"
          ok "Lien présent   : ${link_path}"
          info "Cible du lien  : ${link_target}"
          if [ -x "$link_target" ] || [ -x "$link_path" ]; then
            ok "Exécutable     : oui"
          else
            warn "Exécutable     : non"
          fi
        elif [ -e "$link_path" ]; then
          warn "Lien présent   : ${link_path} (pas un lien symbolique)"
        else
          warn "Lien absent    : ${link_path}"
        fi

        echo ""
        if _menu_cli_path_contains "$bin_dir" 2>/dev/null; then
          ok "~/.local/bin dans PATH actuel : oui"
        else
          warn "~/.local/bin dans PATH actuel : non"
        fi

        if [ -f "${HOME}/.profile" ] && grep -qF "# KSF CLI" "${HOME}/.profile" 2>/dev/null; then
          ok "Bloc KSF dans ~/.profile      : oui"
        else
          warn "Bloc KSF dans ~/.profile      : non"
        fi

        if [ -f "${HOME}/.bashrc" ] && grep -qF "# KSF CLI" "${HOME}/.bashrc" 2>/dev/null; then
          ok "Bloc KSF dans ~/.bashrc       : oui"
        else
          warn "Bloc KSF dans ~/.bashrc       : non"
        fi

        echo ""
        if command -v ksf >/dev/null 2>&1; then
          ok "command -v ksf → $(command -v ksf)"
          if ksf --help >/dev/null 2>&1; then
            ok "Exécution réelle de ksf       : OK"
          else
            warn "Exécution réelle de ksf       : échec"
            echo "  Lance : ./ksf.sh install-cli"
          fi
        else
          warn "command -v ksf → introuvable"
          echo "  Après installation, reconnecte-toi en SSH ou lance :"
          echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
        ;;
      4) return ;;
      *) err "Choix invalide." ;;
    esac
    _menu_pause
  done
}

# ---------- Menu principal ----------

menu_main() {
  while true; do
    _menu_header
    echo "  1) État du serveur"
    echo "  2) Mettre à jour"
    echo "  3) Gérer les applications"
    echo "  4) Sécurité"
    echo "  5) Logs"
    echo "  6) Paramètres KSF"
    echo "  7) Quitter"
    echo ""
    local choice
    read -rp "Choix [1-7] : " choice
    case "$choice" in
      1) _menu_server_status ;;
      2) _menu_update ;;
      3) _menu_apps ;;
      4) _menu_security ;;
      5) _menu_logs ;;
      6) _menu_settings ;;
      7) echo "Au revoir !"; exit 0 ;;
      *) err "Choix invalide." ;;
    esac
  done
}
