"""Browser journeys run against a local uvicorn process with deterministic APIs."""

import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).parents[3]
SOURCE = ROOT / "src"
REPOSITORY_ROOT = ROOT.parents[2]

LOG_OUTPUT = "\n".join(f"line {number}: service started" for number in range(1, 401))
LOG_SUCCESS = f'''<section id="fragment-result" tabindex="-1" aria-live="polite">
<h2>Logs</h2><p class="success-box" role="status">Résultat chargé.</p>
<pre class="fragment-output" tabindex="0" aria-label="Logs">{LOG_OUTPUT}</pre></section>'''
LOG_ERROR = '''<section id="fragment-result" tabindex="-1" aria-live="polite">
<h2>Logs</h2><p class="error-box" role="alert" tabindex="-1">Service indisponible.</p></section>'''
INSTALL_SUCCESS = '''<section id="fragment-content" tabindex="-1" aria-live="polite">
<h1>Installer une application</h1><p class="success-box" role="status">Installation lancée avec succès.</p></section>'''
INSTALL_ERROR = '''<section id="fragment-content" tabindex="-1" aria-live="polite">
<h1>Installer une application</h1><p class="error-box" role="alert" tabindex="-1">Instance invalide.</p></section>'''
JOBS = '''<section id="maintenance-output" tabindex="-1" aria-live="polite">
<h2>Opérations longues</h2><div class="record-list"><div class="record-row">
<span class="chip chip-ok">completed</span><strong>update</strong>
<span>une-sortie-volontairement-très-longue-pour-vérifier-le-retour-à-la-ligne</span>
</div></div></section>'''


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def webui_server(tmp_path_factory):
    runtime = tmp_path_factory.mktemp("ksf-runtime")
    (runtime / "config").mkdir()
    (runtime / "config" / "ksf.env").write_text(
        "DOMAIN=example.com\nWITH_TRAEFIK=true\nOAUTH2_ENABLED=true\n"
    )
    port = _free_port()
    environment = os.environ | {
        "KSF_BASE_DIR": str(runtime),
        "KSF_ENV": "development",
        "PYTHONPATH": str(SOURCE),
        "KSF_SCRIPT_DIR": str(REPOSITORY_ROOT),
    }
    process = subprocess.Popen(
        ["uvicorn", "webui.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            if process.poll() is not None:
                raise RuntimeError("Le serveur Web UI a quitte pendant le demarrage.")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Le serveur Web UI ne repond pas.")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.fixture(params=({"width": 390, "height": 844}, {"width": 1440, "height": 900}))
def page(webui_server, request):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=request.param, color_scheme="dark")

        def api(route):
            path = route.request.url.split("/api/", 1)[1].split("?", 1)[0]
            responses = {
                "status": {"installed": True, "docker_available": True, "apps_running": 0, "apps_total": 0, "with_crowdsec": False},
                "services": {"services": []},
                "apps": {"apps": []},
                "doctor": {"errors": 0, "warnings": 0},
                "jobs": {"jobs": []},
                "clean-data": {"directories": []},
            }
            if path.startswith("logs/"):
                response = {"logs": "service started"}
            else:
                response = responses.get(path, {"error": "API de test inconnue"})
            route.fulfill(status=200, content_type="application/json", body=json.dumps(response))

        page.route("**/api/**", api)
        yield page, webui_server, request.param
        browser.close()


def test_desktop_dashboard_and_empty_state(page):
    browser_page, url, _ = page
    browser_page.goto(url)
    expect(browser_page.get_by_role("heading", name="Tableau de bord")).to_be_visible()
    expect(browser_page.get_by_text("Aucune app installée.")).to_be_visible()
    expect(browser_page.locator('meta[name="color-scheme"]')).to_have_attribute("content", "dark")
    assert browser_page.evaluate("matchMedia('(prefers-color-scheme: dark)').matches")


def test_mobile_drawer_keyboard_and_reduced_motion(page):
    browser_page, url, viewport = page
    browser_page.emulate_media(color_scheme="dark", reduced_motion="reduce")
    browser_page.goto(url)
    label = "Ouvrir le menu" if viewport["width"] == 390 else "Replier la navigation"
    menu = browser_page.get_by_role("button", name=label)
    menu.focus()
    browser_page.keyboard.press("Enter")
    if viewport["width"] == 390:
        expect(browser_page.locator("#main").get_by_role("button", name="Fermer le menu")).to_be_visible()
        browser_page.keyboard.press("Escape")
        expect(browser_page.get_by_role("button", name="Ouvrir le menu")).to_be_focused()
    else:
        expect(browser_page.get_by_role("button", name="Déplier la navigation")).to_be_focused()
    assert browser_page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")


def test_form_success_and_error_are_announced(page):
    browser_page, url, _ = page
    responses = iter((INSTALL_ERROR, INSTALL_SUCCESS))
    browser_page.route(
        "**/ui/apps/install",
        lambda route: route.fulfill(content_type="text/html", body=next(responses))
        if route.request.method == "POST" else route.continue_(),
    )
    browser_page.goto(f"{url}/apps/install")
    expect(browser_page.get_by_role("heading", name="Installer une application")).to_be_visible()
    browser_page.locator("#instance").fill("invalide")
    browser_page.get_by_role("button", name="Installer").click()
    error = browser_page.get_by_role("alert")
    expect(error).to_have_text("Instance invalide.")
    browser_page.goto(f"{url}/apps/install")
    browser_page.locator("#instance").fill("radarr-test")
    browser_page.get_by_role("button", name="Installer").click()
    expect(browser_page.get_by_role("status")).to_have_text("Installation lancée avec succès.")


def test_logs_loading_success_error_and_long_output(page):
    browser_page, url, _ = page
    responses = iter((LOG_SUCCESS, LOG_ERROR))

    def fulfill_logs(route):
        route.fulfill(content_type="text/html", body=next(responses))

    browser_page.route(
        "**/ui/logs/traefik?*",
        fulfill_logs,
    )
    browser_page.goto(f"{url}/logs")
    expect(browser_page.get_by_role("heading", name="Logs")).to_be_visible()
    loading = browser_page.get_by_text("Chargement des logs...")
    expect(loading).to_have_attribute("role", "status")
    expect(loading).to_have_class("htmx-indicator")
    browser_page.get_by_role("button", name="Charger les logs").click()
    expect(browser_page.get_by_role("status")).to_have_text("Résultat chargé.")
    expect(browser_page.locator("pre[aria-label='Logs']")).to_contain_text("line 400: service started")
    browser_page.get_by_role("button", name="Charger les logs").click()
    error = browser_page.get_by_role("alert")
    expect(error).to_have_text("Service indisponible.")


def test_maintenance_jobs_and_empty_state(page):
    browser_page, url, _ = page
    browser_page.route(
        "**/ui/maintenance/operations",
        lambda route: route.fulfill(content_type="text/html", body=JOBS),
    )
    browser_page.goto(f"{url}/maintenance")
    expect(browser_page.get_by_text("Aucune donnée conservée à nettoyer.")).to_be_visible()
    browser_page.get_by_role("button", name="Voir les opérations longues").click()
    expect(browser_page.get_by_role("heading", name="Opérations longues")).to_be_visible()
    expect(browser_page.get_by_text("completed")).to_be_visible()
    expect(browser_page.get_by_text("une-sortie-volontairement-très-longue-pour-vérifier-le-retour-à-la-ligne")).to_be_visible()


def test_confirmation_modal_traps_focus_and_restores_opener(page):
    browser_page, url, _ = page
    browser_page.goto(url)
    opener = browser_page.get_by_role("button", name="Actualiser")
    opener.focus()
    browser_page.evaluate("() => { window.__ksfModal.confirm('Supprimer les données ?', true); }")
    modal = browser_page.get_by_role("dialog")
    expect(modal).to_be_visible()
    browser_page.get_by_role("button", name="Confirmer").focus()
    browser_page.keyboard.press("Tab")
    expect(browser_page.get_by_role("button", name="Fermer la fenêtre")).to_be_focused()
    browser_page.keyboard.press("Escape")
    expect(opener).to_be_focused()
