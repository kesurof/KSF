#!/bin/sh
# Entrypoint ksf-web : valide l'environnement, puis lance uvicorn en non-root.
#
# Architecture : la persistance utilise un BIND MOUNT (${BASE_DIR}/.ksf-web-data),
# pas un volume nommé. Le dossier hôte est créé et chowné par app_install avant
# le `docker compose up`. Donc :
#   - Pas besoin de chown/chmod dans l'entrypoint (le bind mount gère les perms)
#   - Le test d'écriture fail-fast sert uniquement à détecter un mount cassé
set -e

DATA_DIR="${KSF_WEB_DATA_DIR:-/var/lib/ksf-web}"
TARGET_UID="${APP_PUID}"
TARGET_GID="${APP_PGID}"

# Vérification : APP_PUID et APP_PGID doivent être set.
# Sans ce check, `user: ':'` est silencieusement accepté par Docker et gosu
# échoue plus tard sans contexte.
if [ -z "$TARGET_UID" ] || [ -z "$TARGET_GID" ]; then
    echo "FATAL: APP_PUID et APP_PGID doivent être définis." >&2
    echo "       Déployez via 'app.sh install ksf-web' ou 'app.sh update ksf-web'" >&2
    echo "       qui les pose automatiquement depuis 'id -u'/'id -g'." >&2
    exit 1
fi

# Test d'écriture réel : fail-fast si le bind mount n'est pas monté
# ou si les perms sont incorrectes.
if ! : > "$DATA_DIR/.write_test" 2>/dev/null; then
    echo "FATAL: impossible d'écrire dans $DATA_DIR" >&2
    echo "       Causes possibles :" >&2
    echo "       - bind mount mal configuré dans le compose" >&2
    echo "       - perms incorrectes sur le dossier hôte (doit être ${TARGET_UID}:${TARGET_GID})" >&2
    echo "       - dossier hôte absent" >&2
    ls -la "$DATA_DIR" >&2 || true
    echo "---" >&2
    mount | grep "$DATA_DIR" >&2 || echo "(pas de mount trouvé pour $DATA_DIR)" >&2
    exit 1
fi
rm -f "$DATA_DIR/.write_test"

# Lancer la commande passée en argument (uvicorn) en tant qu'utilisateur cible
if [ "$(id -u)" = "0" ]; then
    exec gosu "$TARGET_UID:$TARGET_GID" "$@"
else
    # Déjà en non-root (rare mais possible)
    exec "$@"
fi
