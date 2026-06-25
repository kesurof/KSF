#!/usr/bin/env bash
# WordPress post_install : configure WP apres le premier demarrage.
#
# Ce hook attend que le conteneur wordpress soit healthy (wp-admin dispo),
# puis :
#   1. Installe le plugin Redis Object Cache
#   2. L'active et active l'object cache
#   3. Configure les permalinks (postname) pour de meilleures URLs
#   4. Optionnel : install FR si pas deja fait (wordpress_locale)
#
# Variables disponibles (exportees par app_install / app_update) :
#   APP_NAME, APP_DIR, APP_DATA, APP_PUID, APP_PGID, APP_HOST, APP_PORT,
#   APP_TEMPLATE_DIR, BASE_DIR, NETWORK_NAME, TZ_VALUE, DOCKER_GID,
#   DRY_RUN, AUTO_YES

set -euo pipefail

# Container names suffixes par APP_INSTANCE (cf. compose.yml).
WP_CONTAINER="${APP_INSTANCE}-wp"
WP_READY_MAX_WAIT=120  # secondes

# ---------- Attendre que WordPress soit pret ----------
if [ "${DRY_RUN:-false}" = true ]; then
  info "[DRY-RUN] Attente de la disponibilite de ${WP_CONTAINER} (healthcheck)"
  info "[DRY-RUN] Installation du plugin Redis Object Cache"
  info "[DRY-RUN] Activation du cache + configuration permalinks"
  return 0 2>/dev/null || true
  exit 0
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${WP_CONTAINER}\$"; then
  warn "Conteneur ${WP_CONTAINER} absent, post-install ignore."
  return 0 2>/dev/null || exit 0
fi

info "Attente de WordPress (max ${WP_READY_MAX_WAIT}s)..."
elapsed=0
until docker exec "${WP_CONTAINER}" php -r 'exit(is_dir("/var/www/html/wp-admin") ? 0 : 1);' >/dev/null 2>&1; do
  if [ "${elapsed}" -ge "${WP_READY_MAX_WAIT}" ]; then
    warn "WordPress n'est pas devenu pret en ${WP_READY_MAX_WAIT}s, post-install ignore."
    return 0 2>/dev/null || exit 0
  fi
  sleep 5
  elapsed=$((elapsed + 5))
done

# ---------- Installation de wp-cli si absent ----------
# wp-cli n'est pas inclus dans wordpress:fpm-alpine. On telecharge le PHAR
# dans /tmp (tmpfs /tmp est monte, donc on l'utilise pour le PHAR).
info "Installation de wp-cli..."
docker exec -u www-data "${WP_CONTAINER}" sh -c '
  if [ ! -f /tmp/wp-cli.phar ]; then
    curl -fsSL -o /tmp/wp-cli.phar https://github.com/wp-cli/wp-cli/releases/download/v2.11.0/wp-cli-2.11.0.phar
    chmod +x /tmp/wp-cli.phar
  fi
' || { warn "Echec installation wp-cli, post-install ignore."; exit 0; }

WP_CLI="php /tmp/wp-cli.phar --allow-root --path=/var/www/html"

# ---------- Installation du plugin Redis Object Cache ----------
info "Installation du plugin Redis Object Cache..."
if docker exec -u www-data "${WP_CONTAINER}" sh -c "${WP_CLI} plugin is-installed redis-cache 2>/dev/null"; then
  info "Plugin redis-cache deja installe."
else
  docker exec -u www-data "${WP_CONTAINER}" sh -c "${WP_CLI} plugin install redis-cache --activate" \
    || warn "Echec installation plugin redis-cache (peut-etre pas bloquant)."
fi

# ---------- Activation du cache Redis ----------
info "Activation de l'object cache Redis..."
docker exec -u www-data "${WP_CONTAINER}" sh -c "${WP_CLI} redis enable" \
  || warn "Echec activation redis (peut-etre deja active ou conteneur redis pas pret)."

# ---------- Permaliens : Postname (optionnel) ----------
# On ne touche aux permaliens que si le site est deja configure
# (wp-config est initialise, ce qui se passe au premier acces HTTP).
if docker exec -u www-data "${WP_CONTAINER}" sh -c "${WP_CLI} option get siteurl 2>/dev/null | grep -q http"; then
  info "Configuration des permaliens (postname)..."
  docker exec -u www-data "${WP_CONTAINER}" sh -c "${WP_CLI} rewrite structure '/%postname%/' --hard" \
    || warn "Echec configuration permaliens (sera reconfigurable via WP admin)."
else
  info "Site pas encore configure via HTTP — permaliens a configurer apres la premiere visite."
fi

ok "Post-install WordPress (${APP_INSTANCE}) termine."
