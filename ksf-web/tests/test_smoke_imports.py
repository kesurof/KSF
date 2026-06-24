"""Smoke tests : vérifie que tous les modules Python s'importent sans erreur.

Bloque les NameError runtime comme celui qu'on a eu sur `re` (juin 2026).
"""
import importlib
import pytest


MODULES = [
    "app",
    "app.config",
    "app.db",
    "app.crypto",
    "app.utils",
    "app.security",
    "app.helpers",
    "app.ksf_commands",
    "app.docker_client",
    "app.services",
    "app.services.jobs",
    "app.services.notifications",
    "app.services.webhooks",
    "app.services.audit",
    "app.services.config_editor",
    "app.services.backups",
    "app.services.events",
    "app.routes",
    "app.routes.pages",
    "app.routes.actions",
    "app.routes.api",
    "app.routes.sse",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name):
    """Chaque module doit s'importer sans NameError, ImportError, SyntaxError."""
    importlib.import_module(module_name)
