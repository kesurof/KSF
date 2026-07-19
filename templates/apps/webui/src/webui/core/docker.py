import shutil
import docker
from typing import Optional
from .config import BASE_DIR


class DockerClient:
    def __init__(self):
        self._client: Optional[docker.DockerClient] = None

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def available(self) -> bool:
        try:
            self.client.ping()
            return True
        except Exception:
            return False

    def compose_ps(self, stack_dir: str) -> list[dict]:
        try:
            import subprocess
            result = subprocess.run(
                [*self.compose_command(), "ps", "-a", "--format", "{{.Service}}|{{.Name}}|{{.State}}|{{.Health}}"],
                cwd=stack_dir, capture_output=True, text=True, timeout=30
            )
            services = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|")
                if len(parts) >= 3:
                    services.append({
                        "service": parts[0],
                        "name": parts[1],
                        "state": parts[2],
                        "health": parts[3] if len(parts) > 3 else "",
                    })
            return services
        except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            return []

    @staticmethod
    def compose_command() -> list[str]:
        if shutil.which("docker"):
            return ["docker", "compose"]
        if shutil.which("docker-compose"):
            return ["docker-compose"]
        raise FileNotFoundError("La commande Docker Compose est introuvable dans le conteneur.")

    def compose_run(self, stack_dir: str, *args: str) -> tuple[int, str, str]:
        import subprocess
        try:
            result = subprocess.run(
                [*self.compose_command(), *args],
                cwd=stack_dir, capture_output=True, text=True, timeout=300
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout"
        except OSError as e:
            return -1, "", str(e)

    def compose_up(self, stack_dir: str, build: bool = False) -> tuple[int, str, str]:
        args = ["up", "-d", "--force-recreate"]
        if build:
            args.append("--build")
        return self.compose_run(stack_dir, *args)

    def compose_stop(self, stack_dir: str) -> tuple[int, str, str]:
        return self.compose_run(stack_dir, "stop")

    def compose_restart(self, stack_dir: str) -> tuple[int, str, str]:
        return self.compose_run(stack_dir, "restart")

    def compose_down(self, stack_dir: str) -> tuple[int, str, str]:
        return self.compose_run(stack_dir, "down")

    def compose_pull(self, stack_dir: str) -> tuple[int, str, str]:
        return self.compose_run(stack_dir, "pull")

    def compose_build(self, stack_dir: str, no_cache: bool = False) -> tuple[int, str, str]:
        args = ["build"]
        if no_cache:
            args.append("--no-cache")
        return self.compose_run(stack_dir, *args)

    def compose_logs(self, stack_dir: str, tail: int = 200) -> str:
        _, stdout, stderr = self.compose_run(stack_dir, "logs", "--tail", str(tail))
        return stdout + stderr

    def stack_state(self, stack_dir: str, primary_service: str = "") -> dict:
        services = self.compose_ps(stack_dir)
        total = len(services)
        running = sum(1 for s in services if s["state"] == "running")
        unhealthy = sum(1 for s in services if s.get("health") == "unhealthy")
        selected = None
        for s in services:
            if primary_service and s["service"] == primary_service:
                selected = s
                break
        if not selected and services:
            selected = services[0]
        if total == 0:
            return {"state": "not-created", "running": 0, "total": 0, "unhealthy": 0, "services": []}

        if running == total and total > 0 and unhealthy == 0:
            state = "running"
        elif running > 0:
            state = "degraded"
        else:
            state = "stopped"
        return {
            "state": state,
            "running": running,
            "total": total,
            "unhealthy": unhealthy,
            "services": services,
            "primary_service": selected["service"] if selected else "",
            "primary_name": selected["name"] if selected else "",
            "primary_state": selected["state"] if selected else "",
            "primary_health": selected.get("health", "") if selected else "",
        }

    def container_health(self, container_name: str) -> str:
        try:
            container = self.client.containers.get(container_name)
            attrs = container.attrs
            state = attrs.get("State", {})
            status = state.get("Status", "unknown")
            health = state.get("Health", {}).get("Status", "")
            return f"{status} ({health})" if health else status
        except docker.errors.NotFound:
            return "absent"
        except Exception:
            return "error"


_docker: Optional[DockerClient] = None


def get_docker() -> DockerClient:
    global _docker
    if _docker is None:
        _docker = DockerClient()
    return _docker
