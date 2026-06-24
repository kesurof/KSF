"""Services liés aux sauvegardes : delete, download, restore.

Toutes les opérations passent par ksf.sh. Les opérations longues (restore)
utilisent la job queue (services/jobs.py).
"""
import os
import re
import logging

from app import config

logger = logging.getLogger("ksf-web.backups")

BACKUPS_DIR = os.path.join(config.BASE_DIR, "backups")
BACKUPS_DIR_REAL = os.path.realpath(BACKUPS_DIR)


_BACKUP_NAME_RE = re.compile(r"^[a-zA-Z0-9._\-]+\.tar\.gz$")


def _safe_path(name: str) -> str | None:
    """Renvoie le chemin absolu d'un backup après validation, ou None.

    Bloque :
    - caractères hors [a-zA-Z0-9._-]
    - traversal `..` et chemins absolus
    - symlinks pointant hors de BACKUPS_DIR (anti-`os.path.realpath` escape)
    """
    if not _BACKUP_NAME_RE.fullmatch(name):
        return None
    if ".." in name or name.startswith("/"):
        return None
    candidate = os.path.join(BACKUPS_DIR, name)
    real = os.path.realpath(candidate)
    if not (real + os.sep).startswith(BACKUPS_DIR_REAL + os.sep) and real != BACKUPS_DIR_REAL:
        return None
    return real


def delete_backup(name: str) -> tuple[bool, str]:
    path = _safe_path(name)
    if path is None or not os.path.isfile(path):
        return False, "Backup introuvable ou nom invalide."
    try:
        os.remove(path)
        sha = path + ".sha256"
        if os.path.isfile(sha):
            os.remove(sha)
        return True, f"Backup {name} supprimé."
    except OSError as e:
        return False, f"Suppression impossible : {e}"
