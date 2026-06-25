"""Configuration centralisée du logging ksf-web.

Fournit :
- `configure_logging()` : à appeler en tout premier du lifespan (avant db.init)
  pour capturer les erreurs de migration.
- `get_correlation_id()` / `set_correlation_id()` : contexte `contextvars` pour
  corréler tous les events d'une même action.
- `with_correlation_id(cid, fn)` : helper pour les threads (asyncio.to_thread
  ne propage pas les contextvars nativement).
- `TeeSubprocess` : context manager pour lancer un subprocess et teer sa sortie
  vers un fichier brut (compatibilité SSE) + un logger structuré (JSONL).
- Formatter maison JSON (~30 lignes) et texte.

Choix design : stdlib `logging.config.dictConfig`, aucune nouvelle dépendance.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import logging.config
import os
import re
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from typing import IO, Iterator, Optional

# ── Context vars ─────────────────────────────────────────────────────────

# Stocke le correlation_id courant. Mis par RequestLogMiddleware avant chaque
# requête, restauré dans le finally. Lisible par tous les handlers de log via
# CorrelationFilter.
_correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ksf_web_correlation_id", default="-"
)

# Idem pour l'acteur (utilisé par les filtres pour enrichir les records).
_actor_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ksf_web_actor", default="-"
)


def get_correlation_id() -> str:
    return _correlation_id_var.get()


def set_correlation_id(value: str) -> contextvars.Token:
    return _correlation_id_var.set(value)


def reset_correlation_id(token: contextvars.Token) -> None:
    _correlation_id_var.reset(token)


def get_actor() -> str:
    return _actor_var.get()


def set_actor(value: str) -> contextvars.Token:
    return _actor_var.set(value)


def reset_actor(token: contextvars.Token) -> None:
    _actor_var.reset(token)


@contextmanager
def with_correlation_id(cid: str) -> Iterator[str]:
    """Pose un correlation_id pour la durée du contexte. Restaure après."""
    token = set_correlation_id(cid)
    try:
        yield cid
    finally:
        reset_correlation_id(token)


@contextmanager
def with_actor(actor: str) -> Iterator[str]:
    token = set_actor(actor)
    try:
        yield actor
    finally:
        reset_actor(token)


# ── Filter : injecte correlation_id + actor dans chaque record ───────────


class ContextFilter(logging.Filter):
    """Injecte correlation_id et actor dans `record.__dict__` depuis contextvars."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.correlation_id = _correlation_id_var.get()
        record.actor = _actor_var.get()
        return True


# ── Formatters ───────────────────────────────────────────────────────────


class JsonFormatter(logging.Formatter):
    """Formateur JSON compact, 1 event par ligne, jq-friendly."""

    RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        actor = getattr(record, "actor", None)
        if actor and actor != "-":
            payload["actor"] = actor
        # Champs additionnels passés via `extra=`
        for k, v in record.__dict__.items():
            if k in self.RESERVED or k in payload or k.startswith("_"):
                continue
            if k in ("correlation_id", "actor"):
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except (TypeError, ValueError):
                payload[k] = repr(v)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Formateur texte lisible (utilisé sur stdout = docker logs)."""

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s [%(levelname)s] %(name)s [%(correlation_id)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        # Garantit que le filtre a tourné (au cas où le logger n'a pas le filter).
        if not hasattr(record, "correlation_id"):
            record.correlation_id = _correlation_id_var.get()
        return super().format(record)


# ── Configuration principale ─────────────────────────────────────────────


def configure_logging() -> None:
    """Pose la config logging globale. Idempotent."""
    # Import local pour éviter cycle au démarrage.
    from app import config as app_config

    os.makedirs(app_config.LOG_DIR, exist_ok=True)
    log_file = os.path.join(app_config.LOG_DIR, "ksf-web.log")

    fmt = os.environ.get("KSF_WEB_LOG_FORMAT", app_config.LOG_FORMAT).lower()
    level_name = os.environ.get("KSF_WEB_LOG_LEVEL", app_config.LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)

    if fmt == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = TextFormatter()

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=app_config.LOG_FILE_MAX_BYTES,
        backupCount=app_config.LOG_FILE_BACKUPS,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    file_handler.addFilter(ContextFilter())

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)
    stream_handler.addFilter(ContextFilter())

    # Root logger "ksf-web" : capture tout. On n'utilise PAS le root logging
    # pour ne pas aspirer les logs uvicorn / fastapi.
    root = logging.getLogger("ksf-web")
    root.setLevel(level)
    # Reset les handlers au cas où configure_logging est appelé 2x (reload).
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    root.addFilter(ContextFilter())
    root.propagate = False

    # Enfants nommés (utilisés dans le code via getLogger("ksf-web.<x>")).
    for name in ("request", "actions", "jobs", "audit", "errors"):
        child = logging.getLogger(f"ksf-web.{name}")
        child.setLevel(level)
        child.propagate = True

    # Uvicorn : on récupère ses logs (access + error) et on les pousse dans
    # notre pipeline. Sinon `docker logs` ne montrerait que stdout uvicorn
    # (texte brut), pas les events applicatifs structurés.
    for uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(uv_name)
        uv.handlers = []
        uv.propagate = False
        uv.addHandler(stream_handler)
        uv.addHandler(file_handler)
        uv.addFilter(ContextFilter())
        uv.setLevel(logging.INFO if uv_name == "uvicorn.access" else level)


# ── TeeSubprocess : capture structurée des subprocess ───────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _infer_level(line: str) -> int:
    """Déduit le niveau logging depuis le contenu (préfixes [ERREUR]/[WARN])."""
    upper = line.upper()
    if "[ERREUR]" in upper or "[ERROR]" in upper or "[FATAL]" in upper:
        return logging.ERROR
    if "[WARN]" in upper or "[ATTENTION]" in upper:
        return logging.WARNING
    if "[DEBUG]" in upper:
        return logging.DEBUG
    return logging.INFO


class TeeSubprocess:
    """Lance un subprocess et tee sa sortie vers :
    - un fichier brut (`log_path`) — compatibilité SSE / download
    - le logger `ksf-web.actions` ou `ksf-web.jobs` — events structurés JSONL
    - un callback optionnel `on_line(stream, n, text)` — pour le SSE jobs

    Usage (async) :
        async with TeeSubprocess(cmd, log_path, logger_name="ksf-web.actions") as tee:
            await tee.process.wait()
        # tee.exit_code, tee.duration_ms disponibles
    """

    def __init__(
        self,
        cmd: list[str],
        log_path: str,
        logger_name: str = "ksf-web.actions",
        cwd: str | None = None,
        env: dict | None = None,
        correlation_id: str | None = None,
        extra: dict | None = None,
        on_line: "callable | None" = None,
    ) -> None:
        self.cmd = cmd
        self.log_path = log_path
        self.logger = logging.getLogger(logger_name)
        self.cwd = cwd
        self.env = env
        self.correlation_id = correlation_id or get_correlation_id()
        self.extra = extra or {}
        self.on_line = on_line
        self.process: asyncio.subprocess.Process | None = None
        self.exit_code: int | None = None
        self.duration_ms: int = 0
        self._logf: Optional[IO[bytes]] = None
        self._started_at: float = 0.0
        self._line_counts = {"stdout": 0, "stderr": 0}

    async def __aenter__(self) -> "TeeSubprocess":
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self._started_at = time.monotonic()
        self._logf = open(self.log_path, "ab", buffering=0)
        self.process = await asyncio.create_subprocess_exec(
            *self.cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
            env=self.env,
            start_new_session=True,
        )
        # Lance les readers en parallèle ; ils se terminent quand chaque
        # stream EOF (le proc ferme ses pipes après exit).
        self._readers = await asyncio.gather(
            self._read_stream(self.process.stdout, "stdout", ""),
            self._read_stream(self.process.stderr, "stderr", "[stderr] "),
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.process is not None:
            try:
                await self.process.wait()
            except Exception:
                pass
            self.exit_code = self.process.returncode
        self.duration_ms = int((time.monotonic() - self._started_at) * 1000)
        if self._logf is not None:
            try:
                self._logf.close()
            except Exception:
                pass

    async def _read_stream(self, stream, stream_name: str, prefix: str) -> None:
        if stream is None or self._logf is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            self._logf.write(line)
            self._line_counts[stream_name] += 1
            try:
                text = line.decode("utf-8", errors="replace").rstrip("\n")
            except Exception:
                text = repr(line)
            text = _strip_ansi(text)
            masked = self._mask_secrets(text)
            if prefix:
                displayed = prefix + masked
            else:
                displayed = masked
            level = _infer_level(masked)
            self.logger.log(
                level,
                "subprocess.line",
                extra={
                    "stream": stream_name,
                    "n": self._line_counts[stream_name],
                    "line": masked,
                    "cmd": self.cmd[0] if self.cmd else None,
                    "correlation_id": self.correlation_id,
                },
            )
            # Callback SSE
            if self.on_line is not None:
                try:
                    res = self.on_line(stream_name, self._line_counts[stream_name], displayed)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass

    @staticmethod
    def _mask_secrets(text: str) -> str:
        """Délègue à utils.mask_secrets si disponible (évite cycle d'import)."""
        try:
            from app.utils import mask_secrets
            return mask_secrets(text)
        except Exception:
            return text
