import os
import time
import logging
import docker
from docker.errors import NotFound, APIError

logger = logging.getLogger("ksf-web")

_docker_client = None

KSF_CORE_CONTAINERS = {"traefik", "oauth2-proxy", "crowdsec"}

INSTALLED_DIR = os.path.join(
    os.environ.get("KSF_BASE_DIR", "/serverbox"), "config", "installed-apps"
)


def get_client() -> docker.DockerClient | None:
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
        from datetime import datetime, timezone
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


def restart_container(container_id: str) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.containers.get(container_id).restart(timeout=10)
        return True
    except (NotFound, APIError, Exception):
        return False


def stop_container(container_id: str) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.containers.get(container_id).stop(timeout=10)
        return True
    except (NotFound, APIError, Exception):
        return False


def start_container(container_id: str) -> bool:
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
