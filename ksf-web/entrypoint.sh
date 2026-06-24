#!/bin/sh
# Entrypoint ksf-web : prépare les volumes, puis lance uvicorn en non-root.
#
# Le problème : les volumes Docker nommés sont créés en root:root 755.
# L'appuser (UID 1000 ou APP_PUID) ne peut donc pas écrire dedans.
# Solution : chown récursif du dossier de données au démarrage.
set -e

DATA_DIR="${KSF_WEB_DATA_DIR:-/var/lib/ksf-web}"
TARGET_UID="${APP_PUID:-1000}"
TARGET_GID="${APP_PGID:-1000}"

# Préparer le dossier de données
mkdir -p "$DATA_DIR"
# Chown à l'UID/GID cible (idempotent)
chown -R "$TARGET_UID:$TARGET_GID" "$DATA_DIR" 2>/dev/null || true

# Lancer la commande passée en argument (uvicorn) en tant qu'utilisateur cible
if [ "$(id -u)" = "0" ]; then
    exec gosu "$TARGET_UID:$TARGET_GID" "$@"
else
    # Déjà en non-root (rare mais possible)
    exec "$@"
fi
