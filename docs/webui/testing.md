# Tests Webui

Les tests Python sont executes avec `uv run pytest`. Les tests existants couvrent
les validations, API, diagnostics, jobs et rendu de composants. Tout correctif
ajoute un test de non-regression lorsque possible.

`ruff` demarre avec un socle bloquant de syntaxe et de noms indefinis. Les
regles de formatage, imports et modernisation sont appliquees progressivement
aux fichiers modifies, puis seront activees globalement lorsque la dette legacy
aura ete traitee.

La validation visuelle est progressive : controles manuels documentes aux
viewports requis aujourd'hui, puis tests Playwright pour les parcours critiques
lorsque l'environnement de test navigateur est stabilise.
