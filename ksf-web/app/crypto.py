"""Chiffrement symétrique Fernet pour les secrets au repos.

Trois colonnes sont chiffrées (suffixe `_encrypted`) :
- `webhook_endpoints.secret`  →  `webhook_endpoints.secret_encrypted`
- `audit_log.before`          →  `audit_log.before_encrypted`
- `audit_log.after`           →  `audit_log.after_encrypted`

Source de la clé (par ordre de priorité) :
1. `KSF_WEB_SECRET_KEY` env var (Fernet key url-safe 32 bytes encodée base64)
2. Fichier `${KSF_WEB_DATA_DIR}/secret.key` (chmod 600) — généré au premier
   accès si absent.

Le module expose un Fernet singleton via `get_fernet()`. Les fonctions
`encrypt`, `decrypt`, `maybe_encrypt`, `maybe_decrypt` sont stateless et
thread-safe.
"""
import base64
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

from app import config

logger = logging.getLogger("ksf-web.crypto")

_FERNET_KEY_BYTES = 32

_fernet: Fernet | None = None


def _generate_key() -> bytes:
    """Génère une nouvelle Fernet key (base64-encoded 32 bytes)."""
    return Fernet.generate_key()


def _load_or_create_keyfile() -> bytes:
    """Lit ou crée le fichier de clé Fernet.

    Le fichier est créé en mode 600 (lecture/écriture owner seul). Si la
    création échoue (perms), on log un warning et on génère une clé en
    mémoire qui ne survivra pas au restart — l'utilisateur devra fixer
    les perms manuellement.
    """
    path = config.FERNET_KEY_PATH
    if os.path.isfile(path):
        try:
            with open(path, "rb") as f:
                key = f.read().strip()
            Fernet(key)
            return key
        except (OSError, ValueError) as e:
            logger.warning("Lecture de %s impossible : %s — regénération", path, e)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        key = _generate_key()
        with open(path, "wb") as f:
            f.write(key)
        os.chmod(path, 0o600)
        logger.info("Nouvelle Fernet key générée et stockée dans %s (chmod 600)", path)
        return key
    except OSError as e:
        logger.warning("Impossible de persister la Fernet key (%s) — fallback mémoire", e)
        return _generate_key()


def get_fernet() -> Fernet:
    """Retourne l'instance Fernet singleton (lazy init).

    Source de la clé, par ordre de priorité :
    1. `KSF_WEB_SECRET_KEY` env var (si non vide).
       - Valide → utilisée.
       - Invalide (mauvais format Fernet) → RuntimeError fatale.
         On ne fallback PAS sur le fichier : un user qui set
         explicitement la clé veut celle-ci, pas une autre.
    2. `${KSF_WEB_DATA_DIR}/secret.key` (chmod 600) si env var absente :
       généré au premier accès.
    """
    global _fernet
    if _fernet is not None:
        return _fernet
    if config.KSF_WEB_SECRET_KEY:
        key = config.KSF_WEB_SECRET_KEY.encode("utf-8")
        try:
            _fernet = Fernet(key)
            return _fernet
        except (ValueError, TypeError) as e:
            raise RuntimeError(
                f"KSF_WEB_SECRET_KEY est set mais invalide ({e}). "
                f"La clé doit être un Fernet key valide (44 caractères base64-encoded, "
                f"32 bytes). Pour générer une clé : "
                f"python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
                f"ou retirez la variable pour utiliser le fallback fichier."
            ) from e
    key = _load_or_create_keyfile()
    _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: str) -> bytes:
    """Chiffre une string en bytes Fernet. Lève si Fernet non dispo."""
    if plaintext is None:
        return None  # type: ignore[return-value]
    return get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(blob: bytes) -> str | None:
    """Déchiffre un blob Fernet. Renvoie None si blob est None."""
    if blob is None:
        return None
    try:
        return get_fernet().decrypt(blob).decode("utf-8")
    except (InvalidToken, ValueError) as e:
        logger.warning("Déchiffrement échoué : %s — valeur NULL retournée", e)
        return None


def maybe_encrypt(value: str | None, column_name: str) -> bytes | None:
    """Chiffre `value` UNIQUEMENT si `column_name` finit par `_encrypted`.

    Permet un usage transparent dans les services :
        encrypted = maybe_encrypt(secret, "secret_encrypted")
    """
    if value is None:
        return None
    if not column_name.endswith("_encrypted"):
        return value.encode("utf-8") if isinstance(value, str) else value
    return encrypt(value)


def maybe_decrypt(blob: bytes | None, column_name: str) -> str | None:
    """Déchiffre `blob` UNIQUEMENT si `column_name` finit par `_encrypted`."""
    if blob is None:
        return None
    if not column_name.endswith("_encrypted"):
        if isinstance(blob, bytes):
            try:
                return blob.decode("utf-8")
            except UnicodeDecodeError:
                return None
        return str(blob)
    return decrypt(blob)


def is_encrypted_column(column_name: str) -> bool:
    return column_name.endswith("_encrypted")
