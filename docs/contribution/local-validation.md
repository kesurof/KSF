# Validation Locale

Le point d'entree unique des controles KSF disponibles est :

```bash
make validate
```

Il verifie les prerequis et la syntaxe des scripts Bash. Les controles Web UI
(`ruff`, `pytest` et compilation Tailwind), le rendu Compose, le dry-run et
l'integration Docker restent cibles par lot : ils ne doivent pas etre remplaces
par cette commande generique.

## Prerequis

- Bash ;
- Docker avec le plugin Docker Compose (`docker compose`) ;
- Node.js et npm ;
- Python 3.12 ;
- `uv`.

Avant la premiere validation Web UI :

```bash
cd templates/apps/webui
uv sync --locked --all-groups
npm ci
cd ../../..
make validate
```

Les caches et artefacts produits par ces commandes (`node_modules`, `.venv`,
`__pycache__`, `.pytest_cache`, `.ruff_cache`, `build` et `dist`) sont locaux et
ignores par Git. Ne forcez jamais leur ajout.
