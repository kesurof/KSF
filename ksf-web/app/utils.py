"""Utilitaires partagés ksf-web."""
from datetime import datetime, timezone


def utcnow_dt() -> datetime:
    """Datetime UTC courant (timezone-aware)."""
    return datetime.now(tz=timezone.utc)


def utcnow_str() -> str:
    """Timestamp UTC courant formaté (ex: '2026-06-24 15:09:42 UTC')."""
    return utcnow_dt().strftime("%Y-%m-%d %H:%M:%S UTC")
