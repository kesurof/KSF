"""Smoke tests pour les endpoints /api/* et /health."""
import pytest


def test_health_returns_health_check(client):
    r = client.get("/health")
    # Avec un Docker mocké à None, on s'attend à 503 (docker unreachable).
    # Sans mock, ce serait 200. On accepte les deux et on vérifie la structure.
    assert r.status_code in (200, 503)
    body = r.json()
    assert "db" in body
    assert "docker" in body
    assert "version" in body
    assert body["status"] in ("ok", "err")


def test_dashboard_summary(client):
    r = client.get("/api/dashboard/summary")
    assert r.status_code == 200


def test_jobs_list(client):
    r = client.get("/api/jobs/list")
    assert r.status_code == 200


def test_audit_export_json(client):
    r = client.get("/api/audit/export?fmt=json")
    assert r.status_code == 200
    assert "json" in r.headers.get("content-type", "").lower() or "attachment" in r.headers.get("content-disposition", "")


def test_locks_api(client):
    r = client.get("/api/locks")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_api_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200


def test_api_routes(client):
    r = client.get("/api/routes")
    assert r.status_code == 200


def test_api_data_list(client):
    r = client.get("/api/data/list")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_api_trusted_ips(client):
    r = client.get("/api/security/trusted-ips")
    assert r.status_code == 200


def test_api_crowdsec_decisions(client):
    r = client.get("/api/security/crowdsec/decisions")
    assert r.status_code == 200
