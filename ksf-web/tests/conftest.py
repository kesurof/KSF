"""Configuration pytest : TestClient + mocks Docker/ksf + DB temporaire."""
import os
import tempfile
from unittest.mock import patch

import pytest


@pytest.fixture
def tmp_db_path(monkeypatch, tmp_path):
    """DB SQLite temporaire isolée par test."""
    db_file = tmp_path / "state.db"
    monkeypatch.setenv("KSF_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("KSF_WEB_DATA_DIR", str(tmp_path))
    from app import config, db
    config.DB_PATH = str(db_file)
    config.JOB_LOG_DIR = str(tmp_path / "jobs")
    config.LOG_DIR = str(tmp_path / "logs")
    db._conn = None
    db._migrations_applied = False
    yield str(db_file)


@pytest.fixture
def docker_mocks(monkeypatch):
    """Mock le client Docker (pas de daemon requis)."""
    from app import docker_client

    fake_containers = [
        {
            "id": "abc123", "name": "ksf-web", "image": "ksf-web:latest",
            "status": "running", "health": "-", "uptime": "5m",
            "ports": [], "networks": ["proxy"],
            "type": "app", "created": "2026-01-01", "labels": {},
        },
    ]

    monkeypatch.setattr(docker_client, "list_containers", lambda all_=True: (fake_containers, None))
    monkeypatch.setattr(docker_client, "list_containers_cached", lambda all_=True: (fake_containers, None))
    monkeypatch.setattr(docker_client, "get_container_names", lambda: ["ksf-web"])
    monkeypatch.setattr(docker_client, "get_client", lambda: None)
    return fake_containers


@pytest.fixture
def ksf_mocks(monkeypatch):
    """Mock les commandes ksf.sh / app.sh."""
    from app import ksf_commands

    async def fake_run_command(key, extra_args=None, timeout=120):
        return True, f"mock output for {key}"

    monkeypatch.setattr(ksf_commands, "run_command", fake_run_command)
    monkeypatch.setattr(ksf_commands, "list_installed_apps", lambda: [])
    monkeypatch.setattr(ksf_commands, "list_available_apps", lambda: [])
    monkeypatch.setattr(ksf_commands, "list_backups", lambda: ([], None))
    monkeypatch.setattr(
        ksf_commands, "get_ksf_env",
        lambda: {"DOMAIN": "example.com", "WITH_CROWDSEC": "false"},
    )
    monkeypatch.setattr(ksf_commands, "get_appsec_state", lambda: "inactive")


@pytest.fixture
def client(tmp_db_path, docker_mocks, ksf_mocks):
    """TestClient FastAPI avec tous les mocks en place."""
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
