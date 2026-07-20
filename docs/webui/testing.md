# Tests Webui

Les tests Python sont executes avec `uv run pytest`; `make verify` execute aussi
le lock check, Ruff et le build CSS. Les tests existants couvrent les
validations, API, diagnostics, jobs, migrations SQLite et rendu de composants.
Tout correctif ajoute un test de non-regression lorsque possible.

## Navigateur

Playwright est une dependance du groupe Python `dev`, verrouillee dans `uv.lock`.
Installez Chromium une fois apres `uv sync --locked --all-groups`, puis executez
la suite depuis `templates/apps/webui/` :

```bash
make ui-install-browser
make test-ui
```

La suite lance Uvicorn localement et intercepte les fragments navigateur avec
des reponses deterministes. Elle ne demande ni daemon Docker ni runtime KSF
reel, mais demande les dependances verrouillees et Chromium installe. Chaque
scenario est execute aux viewports `390x844` et `1440x900`. Elle couvre
navigation et drawer, formulaires avec erreur et succes, modale de confirmation,
jobs, maintenance, logs avec erreur et sortie longue, mode sombre, reduced
motion, etats vide et chargement, ainsi que le clavier et le focus.

Preuve d'execution : le 2026-07-20, `make test-ui` a execute avec succes les 12
scenarios Playwright sur Chromium 149.0.7827.55 (Playwright 1.61.0), apres
`uv sync --locked --all-groups`, `npm ci` et `make ui-install-browser`.

`ruff` demarre avec un socle bloquant de syntaxe et de noms indefinis. Les
regles de formatage, imports et modernisation sont appliquees progressivement
aux fichiers modifies, puis seront activees globalement lorsque la dette legacy
aura ete traitee.

La validation visuelle reste completee par la checklist
`docs/checklists/ui-review.md` pour les etats de chargement, erreur, succes et
les contenus longs non encore automatises.
