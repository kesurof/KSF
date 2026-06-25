"""TypedDict pour les structures de données manipulées par les services.

But : remplacer les `dict[str, Any]` par des types documentés, ce qui :
- Facilite la lecture du code (un développeur voit la forme attendue)
- Permet aux outils statiques (mypy, pyright) de détecter les fautes de frappe
- Documente le contrat des fonctions publiques des services

Ce module est volontairement découplé des implémentations : les services
importent les TypedDict ici et continuent à manipuler des `dict` à
l'exécution (le pattern TypedDict + aiosqlite.Row + dict(r) est
totalement compatible : TypedDict n'est qu'une annotation).
"""
from __future__ import annotations

from typing import Any, TypedDict


# ── Audit ────────────────────────────────────────────────────

class AuditEntry(TypedDict, total=False):
    """Une entrée de audit_log, après déchiffrement.

    `total=False` car les colonnes nullable (before, after, target, etc.)
    peuvent être absentes.
    """
    id: int
    actor: str
    action: str
    target: str | None
    before: str | None
    after: str | None
    job_id: str | None
    ip: str | None
    ua: str | None
    created_at: str


# ── Jobs ─────────────────────────────────────────────────────

class JobRecord(TypedDict, total=False):
    """Un job tel qu'exposé par list_recent / get."""
    id: str
    kind: str
    command: str
    args: list[str] | None
    status: str  # 'queued' | 'running' | 'success' | 'failed' | 'cancelled' | 'interrupted'
    pid: int | None
    exit_code: int | None
    output_path: str | None
    output_size: int
    progress_current: int | None
    progress_total: int | None
    lock_key: str | None
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    triggered_by: str | None


# ── Webhooks ─────────────────────────────────────────────────

class WebhookEndpoint(TypedDict, total=False):
    """Un endpoint webhook, après déchiffrement du secret."""
    id: str
    name: str
    url: str
    events: list[str]
    secret: str | None  # déchiffré à la volée si besoin
    enabled: bool
    created_at: str


# ── Notifications ────────────────────────────────────────────

class NotificationPayload(TypedDict, total=False):
    """Payload envoyé aux webhooks lors d'un dispatch."""
    id: str
    level: str  # 'info' | 'warn' | 'error' | 'critical'
    category: str
    title: str
    body: str | None
    link: str | None


# ── Config (ksf.env) ─────────────────────────────────────────

class ConfigField(TypedDict, total=False):
    """Un champ du schéma ksf.env (utilisé par l'éditeur)."""
    key: str
    type: str  # 'text' | 'bool' | 'int' | 'email' | 'domain'
    required: bool
    required_if: dict[str, str]
    secret: bool
    advanced: bool
    default: str
    help: str
    section: str
    value: str  # valeur courante (sétée par form_from_current)


class ConfigVersion(TypedDict, total=False):
    """Une version sauvegardée de ksf.env."""
    id: int
    path: str
    content: str
    actor: str
    reason: str | None
    created_at: str
    size: int  # calculé par length(content) en SQL


# ── Containers (Docker) ──────────────────────────────────────

class ContainerInfo(TypedDict, total=False):
    """Container Docker tel qu'exposé par list_containers."""
    id: str
    name: str
    image: str
    status: str
    health: str
    uptime: str
    ports: list[str]
    networks: list[str]
    type: str  # 'core' | 'app' | 'other'
    created: str
    labels: dict[str, str]


class ContainerStats(TypedDict, total=False):
    """Stats one-shot d'un container (P3.12)."""
    cpu_percent: float
    mem_usage_bytes: int
    mem_limit_bytes: int
    mem_percent: float
    net_rx_bytes: int
    net_tx_bytes: int
    block_read_bytes: int
    block_write_bytes: int


# ── Locks ────────────────────────────────────────────────────

class LockInfo(TypedDict, total=False):
    """Un lock actif (job running avec lock_key)."""
    lock_key: str
    job_id: str
    kind: str
    since: str
