import os
import time
import threading
import logging
import docker
from docker.errors import NotFound, APIError
from typing import Iterator

logger = logging.getLogger("ksf-web")

_docker_client: docker.DockerClient | None = None

KSF_CORE_CONTAINERS = {"traefik", "oauth2-proxy", "crowdsec"}

INSTALLED_DIR = os.path.join(
    os.environ.get("KSF_BASE_DIR", "/serverbox"), "config", "installed-apps"
)


def get_client() -> docker.DockerClient | None:
    """Retourne (ou crée) le client Docker singleton.

    Version sync, utilisée par les helpers bas-niveau (list_containers, etc.)
    qui sont eux-mêmes sync. Pas de health check ici pour rester simple.
    """
    global _docker_client
    if _docker_client is not None:
        return _docker_client
    try:
        _docker_client = docker.DockerClient(
            base_url="unix:///var/run/docker.sock", timeout=10
        )
        return _docker_client
    except Exception:
        logger.exception("Connexion Docker impossible")
        return None


def _container_type(name: str, labels: dict) -> str:
    if name in KSF_CORE_CONTAINERS:
        return "core"
    if labels.get("com.docker.compose.project", "") in KSF_CORE_CONTAINERS:
        return "core"
    env_file = os.path.join(INSTALLED_DIR, f"{name}.env")
    if os.path.isfile(env_file):
        return "app"
    compose_project = labels.get("com.docker.compose.project", "")
    if compose_project and os.path.isfile(os.path.join(INSTALLED_DIR, f"{compose_project}.env")):
        return "app"
    return "other"


def _format_uptime(started_at: str) -> str:
    if not started_at:
        return "-"
    try:
        from datetime import datetime
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        delta = time.time() - start.timestamp()
        days = int(delta // 86400)
        hours = int((delta % 86400) // 3600)
        minutes = int((delta % 3600) // 60)
        parts = []
        if days > 0:
            parts.append(f"{days}j")
        if hours > 0:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)
    except Exception:
        return "-"


def list_containers(all_: bool = True) -> tuple[list[dict], str | None]:
    client = get_client()
    if client is None:
        return [], "Docker indisponible"
    try:
        containers = client.containers.list(all=all_)
    except Exception:
        logger.exception("Erreur listage containers Docker")
        return [], "Docker indisponible"

    result = []
    for c in containers:
        info = c.attrs
        name = c.name
        labels = info.get("Config", {}).get("Labels", {}) or {}
        state = info.get("State", {})
        health = state.get("Health", {}).get("Status", "-") if state.get("Health") else "-"

        ports_raw = []
        for p in info.get("NetworkSettings", {}).get("Ports", {}).values() or []:
            if p:
                for binding in p:
                    ports_raw.append(
                        f"{binding.get('HostIp', '')}:{binding.get('HostPort', '')}"
                        f"->{p[0].get('Port', '')}/{p[0].get('Proto', '')}"
                    )

        result.append({
            "id": c.short_id,
            "name": name,
            "image": c.image.tags[0] if c.image.tags else c.image.short_id,
            "status": c.status,
            "health": health,
            "uptime": _format_uptime(state.get("StartedAt", "")),
            "ports": ports_raw,
            "networks": list((info.get("NetworkSettings", {}).get("Networks", {}) or {}).keys()),
            "type": _container_type(name, labels),
            "created": info.get("Created", ""),
            "labels": labels,
        })
    return result, None


# ── Cache TTL 3s sur list_containers (Phase 4.3) ────────────
#
# 4-5 widgets × 15s = ~20 calls/min. Le cache évite d'écraser le daemon
# Docker. Invalidé par toute action de mutation (start/stop/restart) ou
# manuellement via invalidate_list_cache().

import time as _time

_list_cache: list[dict] | None = None
_list_cache_ts: float = 0.0
_LIST_CACHE_TTL = 3.0


def list_containers_cached(all_: bool = True) -> tuple[list[dict], str | None]:
    """list_containers avec cache TTL 3s. Pas async — appel synchrone ok."""
    global _list_cache, _list_cache_ts
    now = _time.time()
    if _list_cache is not None and (now - _list_cache_ts) < _LIST_CACHE_TTL:
        return _list_cache, None
    result, err = list_containers(all_=all_)
    _list_cache = result
    _list_cache_ts = now
    return result, err


def invalidate_list_cache() -> None:
    global _list_cache, _list_cache_ts
    _list_cache = None
    _list_cache_ts = 0.0


# Invalide le cache à chaque mutation de container (déjà fait dans restart/stop/start ci-dessus)


def get_container(container_id: str) -> dict | None:
    client = get_client()
    if client is None:
        return None
    try:
        c = client.containers.get(container_id)
    except (NotFound, APIError, Exception):
        return None
    info = c.attrs
    name = c.name
    labels = info.get("Config", {}).get("Labels", {}) or {}
    state = info.get("State", {})
    health = state.get("Health", {}).get("Status", "-") if state.get("Health") else "-"

    mounts = [
        {
            "type": m.get("Type", ""),
            "source": m.get("Source", ""),
            "destination": m.get("Destination", ""),
            "mode": m.get("Mode", ""),
            "rw": m.get("RW", True),
        }
        for m in info.get("Mounts", [])
    ]

    ports = []
    for container_port, bindings in (info.get("NetworkSettings", {}).get("Ports") or {}).items():
        if bindings:
            for b in bindings:
                ports.append(f"{b.get('HostIp', '0.0.0.0')}:{b.get('HostPort', '')} -> {container_port}")
        else:
            ports.append(container_port)

    networks = {
        net_name: net_conf.get("IPAddress", "")
        for net_name, net_conf in (info.get("NetworkSettings", {}).get("Networks") or {}).items()
    }

    useful_labels = {k: v for k, v in labels.items() if not k.startswith("maintainer")}

    return {
        "id": c.short_id,
        "full_id": c.id[:12],
        "name": name,
        "image": c.image.tags[0] if c.image.tags else c.image.short_id,
        "status": c.status,
        "health": health,
        "created": info.get("Created", ""),
        "started_at": state.get("StartedAt", ""),
        "uptime": _format_uptime(state.get("StartedAt", "")),
        "ports": ports,
        "mounts": mounts,
        "networks": networks,
        "labels": useful_labels,
        "type": _container_type(name, labels),
        "restart_count": state.get("RestartCount", 0),
        "exit_code": state.get("ExitCode", 0),
    }


def get_container_logs(container_id: str, tail: int = 200) -> str:
    client = get_client()
    if client is None:
        return ""
    try:
        c = client.containers.get(container_id)
    except (NotFound, APIError, Exception):
        return ""
    try:
        return c.logs(tail=tail, timestamps=False, follow=False).decode("utf-8", errors="replace")
    except Exception:
        return ""


def stream_container_logs(container_id: str, tail: int = 100, stop_event: threading.Event | None = None) -> Iterator[str]:
    """Yield lignes de logs en streaming depuis Docker. S'arrête quand stop_event est set."""
    client = get_client()
    if client is None:
        return
    try:
        c = client.containers.get(container_id)
    except (NotFound, APIError, Exception):
        return
    try:
        gen = c.logs(stream=True, follow=True, tail=tail, stdout=True, stderr=True)
        for raw in gen:
            if stop_event is not None and stop_event.is_set():
                try:
                    gen.close()
                except Exception:
                    pass
                return
            line = raw.decode("utf-8", errors="replace")
            if line.endswith("\n"):
                line = line[:-1]
            yield line
    except Exception:
        return


def restart_container(container_id: str) -> bool:
    invalidate_list_cache()
    client = get_client()
    if client is None:
        return False
    try:
        client.containers.get(container_id).restart(timeout=10)
        return True
    except (NotFound, APIError, Exception):
        return False


def stop_container(container_id: str) -> bool:
    invalidate_list_cache()
    client = get_client()
    if client is None:
        return False
    try:
        client.containers.get(container_id).stop(timeout=10)
        return True
    except (NotFound, APIError, Exception):
        return False


def start_container(container_id: str) -> bool:
    invalidate_list_cache()
    client = get_client()
    if client is None:
        return False
    try:
        client.containers.get(container_id).start()
        return True
    except (NotFound, APIError, Exception):
        return False


def get_container_names() -> list[str]:
    client = get_client()
    if client is None:
        return []
    try:
        return [c.name for c in client.containers.list(all=True)]
    except Exception:
        return []


# ── Container stats (P3.12) ─────────────────────────────────
#
# Récupère CPU%, mémoire et réseau d'un container en one-shot (non-streaming).
# Le calcul CPU suit la formule officielle du SDK Docker :
#   cpu_delta = cpu_stats.total_usage - precpu_stats.total_usage
#   system_delta = system_cpu_usage - precpu_stats.system_cpu_usage
#   cpu_percent = (cpu_delta / system_delta) * num_cores * 100
# num_cores = Online_Cpus ?? len(CPUUsage.Percpu_usage)

def get_container_stats(container_id: str) -> dict | None:
    """Renvoie {cpu_percent, mem_usage_bytes, mem_limit_bytes, mem_percent,
    net_rx_bytes, net_tx_bytes, block_read_bytes, block_write_bytes} pour un container.
    Renvoie None si le container est introuvable ou si Docker est indisponible.
    """
    client = get_client()
    if client is None:
        return None
    try:
        c = client.containers.get(container_id)
    except (NotFound, APIError, Exception):
        return None
    try:
        stats = c.stats(stream=False, one_shot=True)
    except (NotFound, APIError, Exception):
        return None

    cpu_delta = 0.0
    system_delta = 0.0
    cpu_stats = stats.get("cpu_stats", {}) or {}
    precpu_stats = stats.get("precpu_stats", {}) or {}
    cpu_usage = cpu_stats.get("cpu_usage", {}) or {}
    precpu_usage = precpu_stats.get("cpu_usage", {}) or {}
    if cpu_usage.get("total_usage") is not None and precpu_usage.get("total_usage") is not None:
        cpu_delta = float(cpu_usage["total_usage"]) - float(precpu_usage["total_usage"])
    system_usage = cpu_stats.get("system_cpu_usage")
    pre_system = precpu_stats.get("system_cpu_usage")
    if system_usage is not None and pre_system is not None:
        system_delta = float(system_usage) - float(pre_system)
    num_cores = cpu_stats.get("online_cpus") or len(cpu_usage.get("percpu_usage") or []) or 1
    cpu_percent = 0.0
    if system_delta > 0 and cpu_delta > 0:
        cpu_percent = (cpu_delta / system_delta) * num_cores * 100.0

    mem_stats = stats.get("memory_stats", {}) or {}
    mem_usage = int(mem_stats.get("usage", 0) or 0)
    mem_limit = int(mem_stats.get("limit", 0) or 0)
    mem_percent = (mem_usage / mem_limit * 100.0) if mem_limit > 0 else 0.0

    net_rx = 0
    net_tx = 0
    for net_name, net_data in (stats.get("networks") or {}).items():
        net_rx += int(net_data.get("rx_bytes", 0) or 0)
        net_tx += int(net_data.get("tx_bytes", 0) or 0)

    blk_read = 0
    blk_write = 0
    for entry in (stats.get("blkio_stats", {}) or {}).get("io_service_bytes_recursive") or []:
        op = entry.get("op", "").lower()
        val = int(entry.get("value", 0) or 0)
        if op == "read":
            blk_read += val
        elif op == "write":
            blk_write += val

    return {
        "cpu_percent": round(cpu_percent, 2),
        "mem_usage_bytes": mem_usage,
        "mem_limit_bytes": mem_limit,
        "mem_percent": round(mem_percent, 2),
        "net_rx_bytes": net_rx,
        "net_tx_bytes": net_tx,
        "block_read_bytes": blk_read,
        "block_write_bytes": blk_write,
    }
