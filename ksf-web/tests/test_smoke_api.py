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


def test_jobs_list_pagination_with_before(client):
    """Pagination cursor : ?before=ISO8601 est accepté, renvoie 200."""
    r = client.get("/api/jobs/list?before=2026-01-01T00:00:00Z")
    assert r.status_code == 200


def test_settings_general(client):
    r = client.get("/settings?tab=general")
    assert r.status_code == 200
    assert b"Param\xc3\xa8tres" in r.content or b"Param" in r.content


def test_settings_security(client):
    r = client.get("/settings?tab=security")
    assert r.status_code == 200
    assert b"CSRF" in r.content


def test_settings_default_redirects_to_general(client):
    r = client.get("/settings")
    assert r.status_code == 200


def test_settings_invalid_tab_falls_back_to_general(client):
    r = client.get("/settings?tab=invalid")
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


def test_container_stats_unknown_container(client):
    """Stats d'un container inexistant → 404."""
    r = client.get("/api/containers/zzzzzz/stats")
    assert r.status_code == 404


def test_webhook_health_unknown_id(client):
    """Health check d'un webhook inexistant → 404 (avec token CSRF).

    On initie un GET pour amorcer le cookie CSRF, puis on POSTe en
    réutilisant ce cookie + header.
    """
    r = client.get("/")
    csrf_cookie = client.cookies.get("ksf_csrf", "")
    assert csrf_cookie, "CSRF cookie manquant après un GET"
    r2 = client.post(
        "/api/webhooks/zzzzzz/health",
        cookies={"ksf_csrf": csrf_cookie},
        headers={"X-CSRF-Token": csrf_cookie},
    )
    assert r2.status_code == 404
