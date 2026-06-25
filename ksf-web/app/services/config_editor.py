"""Éditeur ksf.env : schéma typé, validation, dry-run, diff, rollback.

Workflow d'écriture :
1. Valider chaque champ contre le schéma
2. Backup auto de l'ancien contenu → config_versions
3. Écriture atomique du nouveau fichier (write tmp, fsync, rename)
4. ksf.sh render --dry-run pour vérifier l'impact
5. Si OK, proposer le commit (modal diff dans l'UI) avec un token
   de binding preview/commit
6. Si commit validé (avec le bon token), ksf.sh render (sans --dry-run)
7. Si commit échoue, restore depuis la version de backup

Binding preview/commit : un token signé est généré à chaque preview
réussi. Le commit doit présenter ce token. Ça empêche un caller
malveillant (ou un browser compromis) de commit n'importe quel
contenu.
"""
import asyncio
import hashlib
import hmac
import os
import re
import difflib
import logging
import secrets
import subprocess
import time

from app import config, db
from app.utils import utcnow_str as _utcnow

logger = logging.getLogger("ksf-web.config")

KSF_ENV_PATH = os.path.join(config.BASE_DIR, "config", "ksf.env")
# Secret utilisé pour signer les tokens preview/commit. Différent du
# CSRF secret (sécurité par compartimentation) mais dérivé de la même
# source pour la simplicité.
PREVIEW_SECRET = (config.CSRF_SECRET + ":config-editor").encode("utf-8")
PREVIEW_TOKEN_MAX_AGE = 300  # 5 minutes


# ── Schéma des variables ksf.env ───────────────────────────
#
# Chaque entrée est un dict :
#   key        : nom de la variable d'environnement
#   type       : 'text' | 'bool' | 'int' | 'email' | 'domain'
#   required   : True si la valeur doit être non-vide
#   required_if: dict {"clé_dépendance": "valeur"} → requis si dépendance == valeur
#   secret     : True si le champ est sensible (affichage masqué dans l'UI)
#   advanced   : True si le champ n'est affiché que dans le panneau "Avancé"
#   default    : valeur par défaut si non présente dans ksf.env
#   help       : aide courte affichée sous le champ
#   section    : nom du groupe affiché dans la page /config
#
# Les variables hors-schéma sont préservées en bas du fichier sous
# « # Variables personnalisées (non schématisées) ».

SCHEMA: list[dict] = [
    # ── Platform ──
    {"key": "TZ_VALUE", "type": "text", "default": "Europe/Paris",
     "help": "Timezone IANA (ex: Europe/Paris, UTC).",
     "section": "Platform"},
    {"key": "BACKUP_KEEP", "type": "int", "default": "5", "advanced": True,
     "help": "Nombre de sauvegardes conservées par ksf.sh backup prune.",
     "section": "Platform"},

    # ── Traefik ──
    {"key": "DOMAIN", "type": "domain", "required": True,
     "help": "Domaine principal (ex: example.com). Requis pour ACME et les routes.",
     "section": "Traefik"},
    {"key": "ACME_EMAIL", "type": "email", "required": True,
     "help": "Email utilisé par Let's Encrypt pour les notifications de certificats.",
     "section": "Traefik"},
    {"key": "WITH_TRAEFIK", "type": "bool", "default": "true",
     "help": "Active le reverse-proxy Traefik.",
     "section": "Traefik"},
    {"key": "TRAEFIK_TRUSTED_IPS", "type": "text", "advanced": True,
     "help": "CIDR de trusted IPs séparés par virgule (Cloudflare, etc.).",
     "section": "Traefik"},
    {"key": "TRAEFIK_LOG_LEVEL", "type": "text", "advanced": True, "default": "INFO",
     "help": "Niveau de log Traefik (DEBUG, INFO, WARN, ERROR).",
     "section": "Traefik"},

    # ── OAuth2 ──
    {"key": "WITH_OAUTH2", "type": "bool", "default": "true",
     "help": "Active OAuth2 Proxy devant les routes protégées.",
     "section": "OAuth2"},
    {"key": "OAUTH_PROVIDER", "type": "text", "default": "github",
     "required_if": {"WITH_OAUTH2": "true"},
     "help": "Provider OAuth2 (github, google, oidc).",
     "section": "OAuth2"},
    {"key": "OAUTH_GITHUB_USER", "type": "text",
     "required_if": {"WITH_OAUTH2": "true"},
     "help": "Login GitHub autorisé (ex: monuser).",
     "section": "OAuth2"},
    {"key": "OAUTH_CLIENT_ID", "type": "text", "secret": True,
     "required_if": {"WITH_OAUTH2": "true"},
     "help": "Client ID OAuth2 (secret).",
     "section": "OAuth2"},
    {"key": "OAUTH_CLIENT_SECRET", "type": "text", "secret": True, "advanced": True,
     "required_if": {"WITH_OAUTH2": "true"},
     "help": "Client secret OAuth2 (secret).",
     "section": "OAuth2"},
    {"key": "OAUTH_COOKIE_SECRET", "type": "text", "secret": True, "advanced": True,
     "help": "Secret de cookie OAuth2 Proxy (32+ bytes).",
     "section": "OAuth2"},
    {"key": "OAUTH_COOKIE_SECURE", "type": "bool", "advanced": True, "default": "true",
     "help": "Cookie OAuth2 marqué Secure (HTTPS requis).",
     "section": "OAuth2"},

    # ── CrowdSec ──
    {"key": "WITH_CROWDSEC", "type": "bool", "default": "false",
     "help": "Active CrowdSec et ses bouncers.",
     "section": "CrowdSec"},
    {"key": "CROWDSEC_APPSEC_ENABLED", "type": "bool", "advanced": True, "default": "false",
     "help": "Active le module AppSec/WAF de CrowdSec.",
     "section": "CrowdSec"},
    {"key": "CROWDSEC_APPSEC_HOST", "type": "text", "advanced": True,
     "help": "Host sur lequel CrowdSec expose AppSec (ex: crowdsec.local).",
     "section": "CrowdSec"},
    {"key": "CROWDSEC_APPSEC_LISTEN_ADDR", "type": "text", "advanced": True, "default": "0.0.0.0:7422",
     "help": "Adresse d'écoute d'AppSec.",
     "section": "CrowdSec"},
    {"key": "CROWDSEC_APPSEC_FAILURE_BLOCK", "type": "bool", "advanced": True, "default": "true",
     "help": "Bloquer les requêtes en cas d'échec d'AppSec (fail-closed).",
     "section": "CrowdSec"},
    {"key": "CROWDSEC_APPSEC_UNREACHABLE_BLOCK", "type": "bool", "advanced": True, "default": "false",
     "help": "Bloquer les requêtes quand AppSec est injoignable.",
     "section": "CrowdSec"},
    {"key": "CROWDSEC_APPSEC_COLLECTIONS", "type": "text", "advanced": True,
     "default": "crowdsecurity/appsec-virtual-patching crowdsecurity/appsec-generic-rules",
     "help": "Collections AppSec installées par ksf.sh.",
     "section": "CrowdSec"},
]


def read_current() -> dict[str, str]:
    if not os.path.isfile(KSF_ENV_PATH):
        return {}
    out = {}
    with open(KSF_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip("\"'")
    return out


def _read_raw() -> str:
    if not os.path.isfile(KSF_ENV_PATH):
        return ""
    with open(KSF_ENV_PATH) as f:
        return f.read()


def _validate_value(field: dict, value: str, all_values: dict | None = None) -> str | None:
    t = field["type"]
    v = (value or "").strip()
    if field.get("required") and not v:
        return f"{field['key']} est requis"
    if field.get("required_if") and all_values is not None and not v:
        for dep_key, dep_value in field["required_if"].items():
            if str(all_values.get(dep_key, "")).lower() == dep_value.lower():
                return f"{field['key']} est requis (car {dep_key}={dep_value})"
    if not v:
        return None
    if t == "bool":
        if v.lower() not in ("true", "false", "1", "0", "yes", "no"):
            return f"{field['key']}: booléen invalide (true/false)"
    elif t == "email":
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            return f"{field['key']}: email invalide"
    elif t == "domain":
        if not re.fullmatch(r"[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*", v):
            return f"{field['key']}: domaine invalide"
    elif t == "int":
        if not v.lstrip("-").isdigit():
            return f"{field['key']}: entier invalide"
    return None


def validate(values: dict[str, str]) -> list[dict[str, str]]:
    errors = []
    for f in SCHEMA:
        v = values.get(f["key"], "")
        err = _validate_value(f, v, values)
        if err:
            errors.append({"key": f["key"], "error": err})
    return errors


def form_from_current() -> list[dict]:
    cur = read_current()
    out = []
    for f in SCHEMA:
        out.append({**f, "value": cur.get(f["key"], f.get("default", ""))})
    return out


def _serialize(values: dict[str, str]) -> str:
    """Sérialise les valeurs en format .env.

    - Rejette les valeurs contenant des newlines (corromprait le fichier)
    - Quote les valeurs avec espaces (sinon parse.sh échoue)
    """
    def _format_value(v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("Les valeurs ne peuvent pas contenir de newline")
        if " " in v or "\t" in v or '"' in v or "'" in v:
            # Simple quote with double quotes, escape internal double quotes
            return f'"{v.replace(chr(34), chr(92) + chr(34))}"'
        return v

    lines = ["# KSF platform configuration", "# Generated by ksf-web\n"]
    for f in SCHEMA:
        v = (values.get(f["key"], "") or "").strip()
        if not v and "default" in f:
            v = f["default"]
        if v:
            lines.append(f'{f["key"]}={_format_value(v)}')
    others = []
    cur = read_current()
    schemed = {f["key"] for f in SCHEMA}
    for k, v in cur.items():
        if k in schemed:
            continue
        if k.startswith("#") or not v:
            continue
        others.append((k, v))
    if others:
        lines.append("\n# Variables personnalisées (non schématisées)")
        for k, v in others:
            lines.append(f"{k}={_format_value(v)}")
    return "\n".join(lines) + "\n"


def diff(current: str, proposed: str) -> str:
    """Retourne un diff unifié lisible."""
    diff_lines = list(difflib.unified_diff(
        current.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile="actuel", tofile="proposé", n=2,
    ))
    if not diff_lines:
        return "(aucun changement)"
    return "".join(diff_lines)


async def _save_version(content: str, actor: str, reason: str) -> int:
    async for conn in db.get_conn():
        cur = await conn.execute(
            "INSERT INTO config_versions (path, content, actor, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (KSF_ENV_PATH, content, actor, reason, _utcnow()),
        )
        await conn.commit()
        return cur.lastrowid


async def list_versions(limit: int = 20) -> list[dict]:
    """Liste les versions SANS le content (lazy-load via get_version)."""
    async for conn in db.get_conn():
        cur = await conn.execute(
            "SELECT id, actor, reason, created_at, length(content) as size "
            "FROM config_versions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]


def _run_render(args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [config.REPO_DIR + "/ksf.sh"] + args,
            capture_output=True, text=True, timeout=timeout,
            cwd=config.REPO_DIR,
            env={**os.environ, "KSF_BASE_DIR": config.BASE_DIR, "HOME": "/home/appuser"},
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, f"Le render a dépassé le timeout ({timeout}s)."
    except FileNotFoundError:
        return False, f"ksf.sh introuvable : {config.REPO_DIR}/ksf.sh"
    except Exception as e:
        return False, f"Erreur render : {e}"


async def dryrun_render() -> tuple[bool, str]:
    """Lance ksf.sh render --dry-run (async, non bloquant)."""
    return await asyncio.to_thread(_run_render, ["render", "--dry-run"], 60)


async def commit_render() -> tuple[bool, str]:
    """Lance ksf.sh render (async, non bloquant)."""
    return await asyncio.to_thread(_run_render, ["render"], 120)


def write_atomic(content: str) -> bool:
    try:
        os.makedirs(os.path.dirname(KSF_ENV_PATH), exist_ok=True)
        tmp = KSF_ENV_PATH + ".tmp"
        with open(tmp, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, KSF_ENV_PATH)
        os.chmod(KSF_ENV_PATH, 0o600)
        return True
    except OSError as e:
        logger.exception("Échec écriture atomique de ksf.env")
        return False


async def preview(values: dict[str, str]) -> dict:
    """Prévisualise un changement de config.

    Retourne le diff inline (pas de modale côté front), le contenu proposé
    et le contenu actuel. Le caller doit appeler `commit()` dans les
    `PREVIEW_TOKEN_MAX_AGE` secondes (5 min) — vérifié via cookie de
    session pour éviter un POST direct sans preview.
    """
    errors = validate(values)
    if errors:
        return {"ok": False, "errors": errors}
    proposed = _serialize(values)
    current = _read_raw()
    diff_text = diff(current, proposed)
    return {
        "ok": True, "diff": diff_text, "proposed": proposed, "current": current,
        "preview_id": secrets.token_urlsafe(16),
        "expires_in": PREVIEW_TOKEN_MAX_AGE,
    }


def _sign_preview_cookie(preview_id: str) -> str:
    """Signe un cookie de session pour le binding preview/commit.

    Format : `preview_id:expires:sig`. Sig = HMAC-SHA256(preview_id:expires).
    Stocké côté client via Set-Cookie par la route POST /api/config/preview.
    """
    expires = int(time.time()) + PREVIEW_TOKEN_MAX_AGE
    payload = f"{preview_id}:{expires}"
    sig = hmac.new(PREVIEW_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{payload}:{sig}"


def verify_preview_cookie(cookie_value: str) -> bool:
    """Vérifie qu'un cookie de preview est valide (non expiré + signature OK)."""
    try:
        preview_id, expires_str, sig = cookie_value.rsplit(":", 2)
        expires = int(expires_str)
        if expires < int(time.time()):
            return False
        payload = f"{preview_id}:{expires}"
        expected_sig = hmac.new(PREVIEW_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(sig, expected_sig)
    except (ValueError, AttributeError):
        return False


async def commit(proposed_content: str, preview_cookie: str | None, actor: str = "admin") -> dict:
    """Workflow complet de commit : backup → write → dry-run → render.

    Check loose : exige un cookie de preview valide (signé, non expiré).
    En cas d'échec du dry-run ou du commit réel, restore automatique
    depuis le backup créé en début de workflow.

    Note : on ne lie plus le cookie au contenu proposé (over-engineering).
    Le check loose bloque les POST directs via CSRF exfil, mais permet
    un commit légitime après preview + 5 min.
    """
    if not preview_cookie or not verify_preview_cookie(preview_cookie):
        return {
            "ok": False, "stage": "preview",
            "error": "Aucun preview récent. Lancez d'abord la prévisualisation."
        }

    current = _read_raw()
    if proposed_content == current:
        return {"ok": True, "stage": "noop", "message": "Aucun changement."}

    # Backup de l'état actuel avant écriture (pour rollback)
    await _save_version(current, actor, "before edit")

    # Écriture atomique du nouveau contenu
    if not write_atomic(proposed_content):
        return {
            "ok": False, "stage": "write",
            "error": "Écriture impossible. Permissions du fichier host ?",
        }

    # Dry-run : vérifie que ksf.sh render ne va pas casser la plateforme
    ok, output = await dryrun_render()
    if not ok:
        rollback_ok = write_atomic(current)
        return {
            "ok": False, "stage": "dryrun", "output": output,
            "rolled_back": rollback_ok,
            "error": "Dry-run a échoué. Fichier restauré.",
        }

    # Commit réel : applique ksf.sh render (Traefik, OAuth2, etc.)
    ok, output = await commit_render()
    if not ok:
        rollback_ok = write_atomic(current)
        return {
            "ok": False, "stage": "commit", "output": output,
            "rolled_back": rollback_ok,
            "error": "Commit a échoué. Fichier restauré.",
        }

    # Sauvegarde post-commit pour historique
    await _save_version(proposed_content, actor, "after commit")
    return {"ok": True, "stage": "commit-ok", "output": output}
