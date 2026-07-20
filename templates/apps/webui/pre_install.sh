# KSF Web UI - pre_install.sh
# Copie uniquement les sources necessaires au build et au runtime dans APP_DIR.
set -euo pipefail

if [ -d "${APP_TEMPLATE_DIR}" ]; then
  mkdir -p "${APP_DIR}/src"
  for file in Dockerfile Makefile package.json package-lock.json pyproject.toml uv.lock .dockerignore; do
    if [ -f "${APP_TEMPLATE_DIR}/${file}" ]; then
      cp "${APP_TEMPLATE_DIR}/${file}" "${APP_DIR}/${file}"
    fi
  done
  cp -R "${APP_TEMPLATE_DIR}/src/webui" "${APP_DIR}/src/"
  find "${APP_DIR}/src/webui" -type d -name __pycache__ -prune -exec rm -rf {} +
fi

# Le Web UI délègue les opérations infrastructure complexes au même code
# versionné que le CLI afin de préserver les conventions KSF et les dry-runs.
KSF_REPO_DIR="$(dirname "$(dirname "$(dirname "${APP_TEMPLATE_DIR}")")")"
KSF_RUNTIME_DIR="${APP_DIR}/ksf"
if [ -f "${KSF_REPO_DIR}/ksf.sh" ] && [ -d "${KSF_REPO_DIR}/lib" ] && [ -d "${KSF_REPO_DIR}/templates" ]; then
  mkdir -p "${KSF_RUNTIME_DIR}/lib" "${KSF_RUNTIME_DIR}/templates"
  cp "${KSF_REPO_DIR}/ksf.sh" "${KSF_RUNTIME_DIR}/"
  cp "${KSF_REPO_DIR}/app.sh" "${KSF_RUNTIME_DIR}/"
  cp "${KSF_REPO_DIR}"/lib/*.sh "${KSF_RUNTIME_DIR}/lib/"
  for directory in compose crowdsec env oauth2-proxy traefik; do
    cp -R "${KSF_REPO_DIR}/templates/${directory}" "${KSF_RUNTIME_DIR}/templates/"
  done
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
