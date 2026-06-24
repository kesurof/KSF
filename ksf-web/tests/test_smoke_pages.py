"""Smoke tests pour les routes GET HTML (pages)."""
import pytest


# Pages canoniques (200 direct)
PAGES = [
    "/",
    "/containers",
    "/apps",
    "/backups",
    "/jobs",
    "/audit",
    "/settings/webhooks",
    "/config",
    "/security",
    "/security?tab=crowdsec",
    "/security?tab=appsec",
    "/security?tab=trusted-ips",
    "/diagnostics",
    "/diagnostics?tab=status",
    "/diagnostics?tab=config",
    "/diagnostics?tab=routes",
    "/diagnostics?tab=data",
    "/maintenance",
]

# Redirections (legacy URLs → URLs canoniques)
LEGACY_REDIRECTS = {
    "/security/crowdsec": "/security?tab=crowdsec",
    "/security/appsec": "/security?tab=appsec",
    "/security/trusted-ips": "/security?tab=trusted-ips",
    "/status": "/diagnostics?tab=status",
    "/routes": "/diagnostics?tab=routes",
    "/data": "/diagnostics?tab=data",
}


@pytest.mark.parametrize("path", PAGES)
def test_page_returns_200(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}: {r.text[:200]}"
    assert "text/html" in r.headers.get("content-type", "")


@pytest.mark.parametrize("old_path,new_path", list(LEGACY_REDIRECTS.items()))
def test_legacy_redirects(client, old_path, new_path):
    r = client.get(old_path, follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308), f"{old_path} should redirect, got {r.status_code}"
    assert r.headers.get("location") == new_path


def test_dashboard_contains_widgets(client):
    r = client.get("/")
    assert r.status_code == 200
    # Le dashboard doit contenir des stats cards
    body = r.text
    assert "ksf" in body.lower()  # branding


def test_config_contains_form(client):
    r = client.get("/config")
    assert r.status_code == 200
    # Le config editor doit avoir au moins un input form
    assert "form-input" in r.text or "form-field" in r.text
