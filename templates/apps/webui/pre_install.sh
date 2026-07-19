# KSF Web UI - pre_install.sh
# Copie les fichiers du template et les templates d'apps dans APP_DIR
set -euo pipefail

if [ -d "${APP_TEMPLATE_DIR}" ]; then
  mkdir -p "${APP_DIR}"

  # Copie Dockerfile, requirements.txt, src/ et tout ce qui n'est pas compose.yml ou app.env
  for item in "${APP_TEMPLATE_DIR}"/*; do
    name="$(basename "$item")"
    case "$name" in
      compose.yml|app.env)
        continue
        ;;
    esac
    cp -r "$item" "${APP_DIR}/"
  done
fi

# Le Web UI délègue les opérations infrastructure complexes au même code
# versionné que le CLI afin de préserver les conventions KSF et les dry-runs.
KSF_REPO_DIR="$(dirname "$(dirname "$(dirname "${APP_TEMPLATE_DIR}")")")"
KSF_RUNTIME_DIR="${APP_DIR}/ksf"
if [ -f "${KSF_REPO_DIR}/ksf.sh" ] && [ -d "${KSF_REPO_DIR}/lib" ] && [ -d "${KSF_REPO_DIR}/templates" ]; then
  mkdir -p "${KSF_RUNTIME_DIR}"
  cp "${KSF_REPO_DIR}/ksf.sh" "${KSF_RUNTIME_DIR}/"
  cp "${KSF_REPO_DIR}/app.sh" "${KSF_RUNTIME_DIR}/"
  cp -r "${KSF_REPO_DIR}/lib" "${KSF_RUNTIME_DIR}/"
  cp -r "${KSF_REPO_DIR}/templates" "${KSF_RUNTIME_DIR}/"
fi

# Copie les templates d'apps (radarr, wordpress, etc.) pour que le Web UI
# puisse lister et installer les apps sans dépendre du repo KSF monté.
# APP_TEMPLATE_DIR = .../templates/apps/webui
# On copie .../templates/apps/ (le parent de APP_TEMPLATE_DIR) dans APP_DIR/templates/
APPS_TEMPLATES_SRC="$(dirname "${APP_TEMPLATE_DIR}")"
APPS_TEMPLATES_DST="${APP_DIR}/templates/apps"
if [ -d "$APPS_TEMPLATES_SRC" ]; then
  mkdir -p "$(dirname "$APPS_TEMPLATES_DST")"
  cp -r "$APPS_TEMPLATES_SRC" "$APPS_TEMPLATES_DST"
fi
