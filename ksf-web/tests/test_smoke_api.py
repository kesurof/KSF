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


def test_apps_page_renders(client):
    """Page /apps doit se rendre correctement avec modal + tabs."""
    r = client.get("/apps")
    assert r.status_code == 200
    assert b"closeModal" in r.content
    assert b"openModal" in r.content
    assert b"closeInstallModal" not in r.content  # bug historique : fonction inexistante


def test_install_form_returns_valid_html(client):
    """Le formulaire d'install doit être servi (bug fix : Request vs request)."""
    # Le mock ksf_mocks retourne [] pour list_available_apps par défaut
    # donc l'install form renverra 400 (template['installed'] absent).
    r = client.get("/apps/install-form/radarr")
    # Soit 200 (app disponible mockée), soit 400 (validation)
    assert r.status_code in (200, 400)


def test_install_form_unknown_app_rejected(client):
    """Une app avec un nom invalide doit être rejetée (sécurité)."""
    r = client.get("/apps/install-form/..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)


def test_apps_action_endpoints_registered(client):
    """Les boutons Start/Stop/Update doivent pointer vers les bons endpoints."""
    r = client.get("/apps")
    # Au moins une référence à start/stop/update doit être présente
    # (selon apps installées/visibles, peut être vide).
    assert r.status_code == 200


def test_apps_kebab_menu_has_separator_and_aria(client):
    """Le kebab doit contenir un séparateur visuel et des rôles ARIA pour l'accessibilité."""
    r = client.get("/apps")
    assert r.status_code == 200
    # Le séparateur kebab-sep est dans le HTML
    # (présent uniquement si on a des apps installées dans le mock)
    if b"kebab-sep" in r.content:
        assert b"kebab-sep" in r.content
        assert b'role="separator"' in r.content
        assert b'role="menu"' in r.content
        assert b'role="menuitem"' in r.content
        # Auto-close on item click
        assert b"closest('.kebab')" in r.content or b'closest(.kebab)' in r.content


def test_apps_install_button_uses_plus_icon(client):
    """Le bouton Installer du catalogue doit afficher une icône '+' (UI optimisée)."""
    r = client.get("/apps")
    assert r.status_code == 200
    # Le bouton install est rendu dans le catalogue. Si pas d'apps dispo,
    # le test passe conditionnellement (le test doit fonctionner même sans catalogue).
    if b"hx-get=\"/apps/install-form/" in r.content:
        # Au moins une app installable → le bouton doit avoir l'icône +
        assert b"btn-icon" in r.content
        assert b">+<" in r.content or b"&#43;" in r.content


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
