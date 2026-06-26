# ============================================================
# KSF — Étapes bootstrap infrastructure
# ============================================================

step_user() {
  if [ -n "$SSH_KEY" ] && [ -z "$CREATE_USER" ]; then
    err "--ssh-key nécessite --create-user."
    exit 1
  fi
  if [ -n "$CREATE_USER" ]; then
    SUDO_GROUP="sudo"
    if ! getent group sudo >/dev/null 2>&1; then
      if getent group wheel >/dev/null 2>&1; then
        SUDO_GROUP="wheel"
      else
        err "Aucun groupe sudo/wheel disponible pour accorder les droits administrateur."
        exit 1
      fi
    fi

    if id "$CREATE_USER" &>/dev/null; then
      ok "L'utilisateur ${CREATE_USER} existe déjà."
    else
      info "Création de l'utilisateur ${CREATE_USER}..."
      run sudo useradd -m -s /bin/bash "$CREATE_USER"
      ok "Utilisateur ${CREATE_USER} créé."
      warn "Définis un mot de passe avec : sudo passwd ${CREATE_USER}"
    fi
    run sudo chown "${CREATE_USER}:${CREATE_USER}" "/home/${CREATE_USER}"

    if groups "$CREATE_USER" | grep -qw "$SUDO_GROUP"; then
      ok "L'utilisateur ${CREATE_USER} est déjà dans le groupe ${SUDO_GROUP}."
    else
      info "Ajout de ${CREATE_USER} au groupe ${SUDO_GROUP}..."
      run sudo usermod -aG "$SUDO_GROUP" "$CREATE_USER"
      ok "Utilisateur ${CREATE_USER} ajouté au groupe ${SUDO_GROUP}."
    fi

    if [ -n "$SSH_KEY" ]; then
      SSH_DIR="/home/${CREATE_USER}/.ssh"
      AUTH_KEYS="${SSH_DIR}/authorized_keys"
      info "Installation de la clé SSH pour ${CREATE_USER}..."
      run sudo mkdir -p "$SSH_DIR"
      if [ "$DRY_RUN" = false ]; then
        echo "$SSH_KEY" | sudo tee "$AUTH_KEYS" >/dev/null
      else
        warn "[DRY-RUN] echo \"\$SSH_KEY\" | sudo tee \"$AUTH_KEYS\" >/dev/null"
      fi
      run sudo chown -R "${CREATE_USER}:${CREATE_USER}" "$SSH_DIR"
      run sudo chmod 700 "$SSH_DIR"
      run sudo chmod 600 "$AUTH_KEYS"
      ok "Clé SSH installée pour ${CREATE_USER}."
    fi
  fi
}

step_system() {
  if [ "$SKIP_SYSTEM" = false ]; then
    info "Mise à jour de l'index des paquets..."
    update_pkgs
    info "Installation des paquets utiles..."
    install_pkgs curl git ca-certificates gnupg lsb-release nano unzip
  else
    info "Étape système ignorée (--skip-system)."
  fi
}

step_docker_install() {
  if [ "$SKIP_DOCKER" = false ]; then
    if command -v docker >/dev/null 2>&1; then
      ok "Docker est déjà installé : $(docker --version)"
    else
      info "Installation de Docker..."
      if [ "$DRY_RUN" = false ]; then
        curl -fsSL https://get.docker.com | sudo sh
        ok "Docker installé."
      else
        warn "[DRY-RUN] curl -fsSL https://get.docker.com | sudo sh"
        ok "Docker installé (simulé)."
      fi
    fi
    if [ "$DRY_RUN" = true ]; then
      ok "Docker Compose (simulé en dry-run)"
    else
      info "Activation du service Docker..."
      run sudo systemctl enable docker
      run sudo systemctl start docker
      if docker compose version >/dev/null 2>&1; then
        ok "Docker Compose plugin disponible : $(docker compose version)"
      elif command -v docker-compose >/dev/null 2>&1; then
        warn "Docker Compose v1 (standalone) détecté : $(docker-compose --version)"
        warn "Remplace 'docker compose' par 'docker-compose' dans tes stacks."
      else
        err "Aucun Docker Compose (v1 ou v2) n'est disponible."
        exit 1
      fi
    fi
  else
    info "Étape Docker ignorée (--skip-docker)."
  fi
}

step_docker_group() {
  DOCKER_USER="${TARGET_USER:-$USER}"
  if command -v docker >/dev/null 2>&1; then
    if groups "$DOCKER_USER" | grep -qw docker; then
      ok "L'utilisateur ${DOCKER_USER} est déjà dans le groupe docker."
      if [ "$DOCKER_USER" = "$USER" ] && ! docker ps >/dev/null 2>&1; then
        warn "La session courante n'a pas encore les droits Docker. Déconnecte-toi puis reconnecte-toi."
        exit 0
      fi
      return 0
    fi

    info "Ajout de ${DOCKER_USER} au groupe docker..."
    run sudo usermod -aG docker "$DOCKER_USER"
    warn "Ajouté au groupe docker. Déconnecte-toi puis reconnecte-toi en SSH."
    if [ -n "$CREATE_USER" ]; then
      warn "Connecte-toi en tant que ${CREATE_USER} puis : git clone https://github.com/kesurof/ksf.git && cd ksf && ./deploy.sh"
    else
      warn "Puis lance : ./deploy.sh"
    fi
    exit 0
  fi
}

step_dirs() {
  info "Création de l'arborescence dans ${BASE_DIR}..."
  run sudo mkdir -p \
    "${BASE_DIR}" \
    "${BASE_DIR}/proxy" \
    "${BASE_DIR}/apps" \
    "${BASE_DIR}/data" \
    "${BASE_DIR}/logs" \
    "${BASE_DIR}/config"
  run sudo chown "${TARGET_USER}:${TARGET_USER}" "${BASE_DIR}" \
    "${BASE_DIR}/proxy" \
    "${BASE_DIR}/apps" \
    "${BASE_DIR}/data" \
    "${BASE_DIR}/logs" \
    "${BASE_DIR}/config"
  run sudo chmod 750 "${BASE_DIR}/logs"
  ok "Arborescence prête."
}

step_ssh_hardening() {
  if [ "$SSH_HARDENING" = true ]; then
    SSHD_CONFIG="/etc/ssh/sshd_config"
    if [ ! -f "${SSHD_CONFIG}.bak" ]; then
      info "Sauvegarde de ${SSHD_CONFIG} -> ${SSHD_CONFIG}.bak"
      run sudo cp "$SSHD_CONFIG" "${SSHD_CONFIG}.bak"
    else
      ok "Sauvegarde SSH déjà présente : ${SSHD_CONFIG}.bak"
    fi

    info "Désactivation de l'authentification par mot de passe SSH..."
    for param in "PasswordAuthentication" "KbdInteractiveAuthentication" "ChallengeResponseAuthentication" "PermitRootLogin"; do
      if run sudo grep -q "^${param}" "$SSHD_CONFIG"; then
        run sudo sed -i "s/^${param}.*/${param} no/" "$SSHD_CONFIG"
      else
        if [ "$DRY_RUN" = false ]; then
          echo "${param} no" | sudo tee -a "$SSHD_CONFIG" >/dev/null
        else
          warn "[DRY-RUN] echo \"${param} no\" >> ${SSHD_CONFIG}"
        fi
      fi
    done

    SSH_SERVICE_NAME="ssh"
    if systemctl list-units --type=service --all 2>/dev/null | grep -q 'sshd\.service'; then
      SSH_SERVICE_NAME="sshd"
    fi

    info "Test de la configuration SSH..."
    if run sudo sshd -t; then
      ok "Configuration SSH valide."
      info "Rechargement du service SSH (${SSH_SERVICE_NAME})..."
      run sudo systemctl reload "$SSH_SERVICE_NAME"
      ok "Service SSH rechargé."
    else
      err "La configuration SSH est invalide. Restauration de la sauvegarde."
      run sudo cp "${SSHD_CONFIG}.bak" "$SSHD_CONFIG"
      exit 1
    fi
  fi
}
