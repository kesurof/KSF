# Livraison KSF

- Les criteres d'acceptation sont verifies.
- Le diff et les fichiers non suivis ont ete inspectes.
- Les controles Bash, rendu, Compose, tests webui et dry-run pertinents ont ete
  executes.
- Les donnees existantes restent preservees ou disposent d'une procedure de
  migration et restauration.
- Aucun secret, runtime, log ou artefact local n'est ajoute au depot.
- README, AGENTS.md, aide CLI, skills et documentation sont coherents.
- Les risques residuels et controles non executes sont declares.
- `VERSION` et `CHANGELOG.md` sont mis a jour lorsqu'une version est preparee.

## Evidence De La Revue Finale 0.2.0

Controles executes le 2026-07-20 :

- Revue equivalente a `/check-project` : inspection du worktree et du diff,
  puis `git diff --check`.
- `make check-release` : syntaxe Bash, validateurs, dry-run, lifecycle,
  rollback, matrice de rendu statique et coherence `VERSION`/`CHANGELOG.md`.
- `make check-compose` : matrice Compose avec Docker Compose et rendu isole de
  deux instances WordPress, incluant les secrets en permission `600`.
- Web UI : `ruff check src` et `PYTHONPATH=src pytest -q src/tests/test_webui.py`
  (56 tests passes) : formulaire et endpoint de configuration confirmes,
  reactivation forcee et mise a jour globale confirmee.
- Navigation Web UI : `PATH=/tmp/ksf-ui-tools/bin:$PATH make test-ui` : 12
  parcours Playwright passes aux formats 390 x 844 et 1440 x 900.
- `make test-docker` : smoke Docker Compose opt-in execute avec succes.
- `npm audit --omit=dev` : aucune vulnerabilite trouvee.

SKIP et controles non executes :

- ShellCheck et shfmt ont ete appeles par `make check-release` et ont affiche
  `SKIP`, car ils ne sont pas installes.
- `make check-webui` n'a pas ete execute comme agregat, car `uv` n'est pas
  installe globalement. Les controles Ruff, pytest et Playwright ont ete lances
  avec l'environnement temporaire versionne `/tmp/ksf-ui-tools`.
- `pip-audit` est absent : l'audit Python n'a pas ete execute.

Risques residuels :

- Les parcours Playwright couvrent les deux largeurs prescrites, mais ne
  remplacent pas une revue manuelle de l'ensemble des navigateurs cibles.
- L'absence de ShellCheck, shfmt et pip-audit laisse respectivement non verifiees
  les conventions shell et les vulnerabilites Python.
- Le smoke Docker Compose est volontairement minimal et ne couvre ni DNS reel,
  ni ACME, ni l'ownership d'un runtime serveur complet.
