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
docker exec "${WP_CONTAINER}" sh -c '
  if [ ! -f /tmp/wp-cli.phar ]; then
    curl -fsSL -o /tmp/wp-cli.phar https://github.com/wp-cli/wp-cli/releases/download/v2.11.0/wp-cli-2.11.0.phar
    chmod +x /tmp/wp-cli.phar
  fi
' || { warn "Echec installation wp-cli, post-install ignore."; exit 0; }

WP_CLI="HOME=/tmp php /tmp/wp-cli.phar --allow-root --path=/var/www/html"
# HOME=/tmp : wp-cli cherche $HOME/.wp-cli/cache/ ; le home par defaut dans
# l'image wordpress (Alpine) est /, non writable en 1002:1002. /tmp est un
# tmpfs world-writable, donc on y force le cache wp-cli.

# ---------- Garde : site WP pas encore installe via HTTP ----------
# Tant que l'utilisateur n'a pas complete l'install wizard (5-min install),
# les commandes wp-cli qui touchent wp_options (plugin install, redis enable,
# eval update_option) echouent toutes avec des erreurs SQL ou des warnings.
#
# On ne peut PAS utiliser :
#   - `option get siteurl` : le cache Redis objet sert l'ancienne valeur meme
#     si wp_options a ete vide.
#   - `core is-installed` : il retourne 0 des que wp-config.php est valide,
#     meme sans wp_options.
#   - `db query` : shell out vers mysql client via proc_open() qui est desactive
#     dans php.ini (cf. disable_functions = exec,passthru,shell_exec,system,
#     proc_open,popen).
#
# `wp eval` charge WP en interne et appelle get_option() qui detourne par
# l'object cache Redis — mais en sortie d'install wizard, le cache est vide
# et wp_options est peuple : ca matche. En pre-install (cache + table vides),
# get_option retourne false, le grep echoue, le guard se declenche.
if ! docker exec "${WP_CONTAINER}" sh -c "${WP_CLI} eval 'echo (string) get_option(\"siteurl\");' 2>/dev/null | grep -qE '^https?://'"; then
  info "==========================================================================="
  info " WordPress pas encore installe : la 5-min install n'a pas ete faite."
  info ""
  info " Etape 1 : ouvrir https://${APP_HOST}/ dans un navigateur et suivre"
  info "           l'assistant (titre, identifiants admin, mot de passe DB)."
  info ""
  info " Etape 2 : une fois l'install terminee, relancer le post-install avec :"
  info "           ./app.sh update ${APP_INSTANCE}"
  info "           (installe le plugin Redis Object Cache, active l'object cache,"
  info "            configure les permaliens postname)"
  info "==========================================================================="
  return 0 2>/dev/null || exit 0
fi

# ---------- Installation du plugin Redis Object Cache ----------
info "Installation du plugin Redis Object Cache..."
if docker exec "${WP_CONTAINER}" sh -c "${WP_CLI} plugin is-installed redis-cache 2>/dev/null"; then
  info "Plugin redis-cache deja installe."
else
  docker exec "${WP_CONTAINER}" sh -c "${WP_CLI} plugin install redis-cache --activate" \
    || warn "Echec installation plugin redis-cache (peut-etre pas bloquant)."
fi

# ---------- Activation du cache Redis ----------
info "Activation de l'object cache Redis..."
docker exec "${WP_CONTAINER}" sh -c "${WP_CLI} redis enable" \
  || warn "Echec activation redis (peut-etre deja active ou conteneur redis pas pret)."

# ---------- Permaliens : Postname ----------
# wp-cli 2.11.0 n'a pas de flag --skip-rewrite-rules : il tente systematiquement
# de regenerer .htaccess apres un rewrite structure, ce qui echoue avec
# proc_open() desactive dans php.ini. Inutile ici : nginx gere les permaliens
# via try_files, .htaccess n'est pas lu. On utilise wp eval pour toucher
# uniquement la DB, en evitant la logique wp-cli qui veut regenerer .htaccess.
info "Configuration des permaliens (postname)..."
docker exec "${WP_CONTAINER}" sh -c "${WP_CLI} eval 'update_option( \"permalink_structure\", \"/%postname%/\" );'" \
  || warn "Echec configuration permaliens (sera reconfigurable via WP admin)."

ok "Post-install WordPress (${APP_INSTANCE}) termine."
