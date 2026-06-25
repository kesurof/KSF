"""Configuration centrale de ksf-web.

Toutes les variables d'environnement et chemins sont centralisés ici.
"""
import os

BASE_DIR = os.environ.get("KSF_BASE_DIR", "/serverbox")
REPO_DIR = os.environ.get("KSF_REPO_DIR", "/ksf")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")

LOG_DIR = os.path.join(BASE_DIR, "logs", "ksf-web")
ACTIONS_LOG_DIR = os.path.join(BASE_DIR, "logs", "ksf-web", "actions")
JOB_LOG_DIR = os.path.join(BASE_DIR, "logs", "ksf-web", "jobs")

# DB_PATH : par défaut sur /var/lib/ksf-web (volume Docker nommé, persistant,
# permissions Docker-managed). Pas de dépendance sur les perms du host sur
# ${BASE_DIR}. Peut être overridé via KSF_WEB_DB_PATH si besoin (debug, tests).
_DATA_DIR = os.environ.get("KSF_WEB_DATA_DIR", "/var/lib/ksf-web")
DB_PATH = os.environ.get("KSF_WEB_DB_PATH", os.path.join(_DATA_DIR, "state.db"))

OUTPUT_TRUNCATE_BYTES = 8 * 1024

# ── Logging ─────────────────────────────────────────────────────
# Format du log fichier + stdout ("text" lisible, "json" pour agrégation).
# Défaut "text" pour ne rien casser du parsing docker logs existant.
LOG_FORMAT = os.environ.get("KSF_WEB_LOG_FORMAT", "text").lower()
LOG_LEVEL = os.environ.get("KSF_WEB_LOG_LEVEL", "INFO").upper()
LOG_FILE_MAX_BYTES = int(os.environ.get("KSF_WEB_LOG_FILE_MAX_BYTES", str(10 * 1024 * 1024)))
LOG_FILE_BACKUPS = int(os.environ.get("KSF_WEB_LOG_FILE_BACKUPS", "5"))
LOG_RETENTION_DAYS = int(os.environ.get("KSF_WEB_LOG_RETENTION_DAYS", "30"))

ACTIONS_ENABLED = os.environ.get("KSF_WEB_ACTIONS_ENABLED", "true").lower() == "true"

CSRF_COOKIE = "ksf_csrf"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_MAX_AGE = 60 * 60 * 8
CSRF_SALT = "ksf-web-csrf-v1"
CSRF_SECRET = os.environ.get("KSF_WEB_SECRET_KEY") or BASE_DIR + "-csrf-default"
CSRF_COOKIE_SECURE = os.environ.get("KSF_WEB_COOKIE_SECURE", "true").lower() == "true"

# ── Encryption (Fernet) ───────────────────────────────────
# KSF_WEB_SECRET_KEY est la clé Fernet dédiée (optionnelle : si absente,
# `app/crypto.py` génère et persiste une clé dans FERNET_KEY_PATH au premier
# accès). Cette clé chiffre les secrets au repos dans SQLite (webhooks,
# audit log before/after).
KSF_WEB_SECRET_KEY = os.environ.get("KSF_WEB_SECRET_KEY")
FERNET_KEY_PATH = os.path.join(_DATA_DIR, "secret.key")
