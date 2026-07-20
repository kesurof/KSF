# Checklist De Migration KSF

Cette checklist suit les nouvelles regles KSF. Cocher un lot seulement apres
validation des criteres de sortie et mise a jour de la documentation concernee.

## 0. Socle

- [x] Versionner les agents, commandes, skills, docs, `VERSION` et `CHANGELOG.md`.
- [x] Ajouter une commande locale unique pour les validations KSF.
- [x] Documenter les prerequis locaux : Bash, Docker Compose, Node/npm, Python
  3.12 et `uv`.
- [x] Verifier que les caches et artefacts locaux ne sont pas inclus dans une
  livraison.

## 1. Bash Et Dry-Run

- [x] Ajouter des validateurs partages pour instance, domaine, sous-domaine,
  host, port et chemins derives.
- [x] Valider les arguments avant toute ecriture, route, appel DNS ou Compose.
- [x] Corriger `ksf.sh install-cli --dry-run` afin qu'il ne modifie jamais les
  profils shell.
- [x] Ajouter ou clarifier le support `bootstrap.sh --dry-run`.
- [x] Garantir que les logs bootstrap dry-run restent hors de `${BASE_DIR}`.
- [x] Ajouter des tests zero-ecriture pour bootstrap, deploy, app install et
  install-cli.

## 2. Cycle De Vie Des Apps

- [x] Faire de `app.sh` la source unique des mutations applicatives.
- [x] Faire deleguer les mutations webui a `app.sh` via des jobs.
- [x] Corriger le rendu webui de `DOCKER_GROUP_ADD_BLOCK`.
- [x] Aligner le fallback `APP_DOCKER_SERVICE` avec le CLI Bash.
- [x] Declarer `APP_DOCKER_SERVICE` dans chaque template fourni.
- [x] Ajouter des tests de parite CLI/Web UI pour chaque template.
- [x] Ajouter un rollback pour les erreurs de rendu, DNS, hook et Compose.
- [x] Ne jamais supprimer les donnees existantes pendant un rollback.

## 3. Deploy Avec Webui

- [x] Valider que `--with-webui` requiert Traefik, domaine et OAuth2 Proxy.
- [x] Faire echouer `deploy.sh` si l'installation webui deleguee echoue.
- [x] Distinguer explicitement deployment plateforme et deployment partiel dans
  les logs et le code retour.
- [x] Aligner aide CLI, README et AGENTS.md.

## 4. Rendu WordPress Et Secrets

- [x] Identifier tous les placeholders WordPress et Compose differes.
- [x] Generer les secrets par instance dans des fichiers runtime `600`.
- [x] Rendre les Compose sans placeholder KSF residuel.
- [x] Tester deux instances WordPress avec secrets et donnees distincts.
- [x] Verifier les permissions des fichiers generes.
- [x] Epingler et verifier le telechargement WP-CLI, ou le supprimer.

## 5. Securite Webui

- [x] Conserver les ports directs webui sur `127.0.0.1` uniquement.
- [x] Documenter localhost comme frontiere de confiance acceptee.
- [x] Normaliser la verification stricte Origin/Referer/Host.
- [x] Refuser les mutations navigateur sans Origin ni Referer valide.
- [x] Desactiver OpenAPI et Swagger en production.
- [x] Exiger une confirmation serveur pour les actions sensibles et destructives.
- [x] Ajouter des tests HTTP directs pour les confirmations et CSRF.
- [x] Supprimer le self-rebuild root/non deterministe du webui.
- [x] Conserver le rebuild webui via CLI jusqu'a un mecanisme sur execute avec
  UID/GID hote.
- [x] Documenter et tester le socket Docker comme frontiere administrative.
- [x] Renforcer la redaction des secrets dans les jobs, logs et SQLite.

## 6. Base De Donnees Webui

- [x] Rendre le chemin SQLite configurable et testable.
- [x] Creer repertoire et base avec permissions et ownership hote corrects.
- [x] Ajouter une table `schema_migrations` et des migrations transactionnelles.
- [x] Retirer les `except Exception: pass` de migration.
- [x] Sauvegarder avant toute migration destructive.
- [x] Configurer et documenter WAL, busy timeout et integrity check.
- [x] Ajouter une retention des jobs.
- [x] Empecher les jobs concurrents au niveau SQLite.
- [x] Tester base vide, base peuplee, upgrade, erreur, permissions, concurrence,
  redaction et restauration.

## 7. Migration HTMX

- [x] Migrer dashboard et statuts vers des fragments serveur. Evidence : `/ui/dashboard` et les fragments de statut restent rendus par FastAPI.
- [x] Migrer liste et detail des applications. Evidence : `/ui/apps` et `/ui/apps/{instance}`.
- [x] Migrer installation et configuration d'app. Evidence : `/ui/apps/install` et `/ui/apps/{instance}/configure`.
- [x] Migrer infrastructure et logs. Evidence : `/ui/infrastructure`, `/ui/infrastructure/{name}` et `/ui/logs/{target}` rendent du HTML.
- [x] Migrer general, routes, config et doctor. Evidence : `/ui/general/{doctor,routes,config}`.
- [x] Migrer CrowdSec, AppSec et securite. Evidence : `/ui/security/{crowdsec,appsec,alerts}`.
- [x] Migrer maintenance et operations longues. Evidence : `/ui/maintenance` et `/ui/maintenance/operations`.
- [x] Limiter Alpine au drawer, modales, menus et etat visuel local. Evidence : `app.js` ne charge aucun etat metier.
- [x] Ajouter chargement, vide, erreur, succes et donnees longues a chaque flux. Evidence : loaders HTMX, `fragments/result.html` et `fragment-output`.
- [x] Gerer focus et annonces apres swaps HTMX. Evidence : `htmx:afterSwap`, regions `aria-live` et focus des erreurs HTML.
- [x] Ajouter des tests de fragments et erreurs HTTP. Evidence : `FragmentTests` couvre la matrice des fragments et les erreurs HTML.

## 8. Tailwind Et Accessibilite

- [x] Conserver la feuille de compatibilite chargee tant que ses classes sont utilisees.
- [x] Verifier que `app.css` compile conserve les selecteurs partages requis.
- [x] Inventorier les composants par ecran.
- [x] Migrer les composants partages vers tokens et utilitaires Tailwind.
- [x] Retirer les styles inline.
- [x] Implementer modal accessible avec focus trap et restauration du focus.
- [x] Implementer tabs, dropdowns et combobox accessibles au clavier.
- [x] Ajouter les icones SVG manquantes.
- [x] Preserver dark mode, contraste, focus visible et reduced motion.
- [x] Servir HTMX et Alpine localement depuis des dependances npm verrouillees.
- [x] Migrer les selecteurs restants dans `input.css`, supprimer la feuille de
  compatibilite et verifier son absence de reference.

## 9. Validation UI

- [x] Installer et configurer Playwright : `uv` 0.7.13, Playwright 1.61.0 et
  Chromium 149.0.7827.55 ont ete installes le 2026-07-20.
- [x] Executer `make test-ui` : 12 scenarios Playwright verts le 2026-07-20.
- [x] Tester les parcours critiques a 390 x 844 et 1440 x 900.
- [x] Tester navigation, drawer, modales, formulaires, jobs, logs et maintenance.
- [x] Tester dark mode, reduced motion, etats vide/erreur/chargement/succes et
  textes longs.
- [x] Ajouter des controles d'accessibilite, focus et clavier.

## 10. Dependances Et Images

- [x] Supprimer `templates/apps/webui/requirements.txt`.
- [x] Utiliser `pyproject.toml`/`uv.lock` comme source Python unique.
- [x] Utiliser `package.json`/`package-lock.json` comme source Node unique.
- [x] Ajouter les cibles locales audit Python, audit npm, lock check et build
  image.
- [x] Documenter la mise a jour des fichiers lock.
- [x] Remplacer toutes les images `latest` par des tags versionnes revus.
- [x] Epingler les tags Node, Python et uv du Dockerfile.
- [x] Documenter les versions Docker CLI et Compose de l'image webui.
- [x] Nettoyer les caches, bytecode et fichiers temporaires des templates.
- [x] Reduire les copies larges de `pre_install.sh` a une liste explicite.

## 11. Suite De Validation Locale

- [x] Ajouter un harnais Bash hors ligne pour les validateurs, les dry-runs et
  `install-cli`.
- [x] Ajouter des tests Bash pour validateurs, dry-run, routes, DNS et lifecycle.
- [x] Ajouter une matrice de rendu Compose plateforme et applications.
- [x] Executer `docker compose config --quiet` sur chaque Compose rendu.
- [x] Echec si un placeholder KSF reste dans un fichier genere.
- [x] Valider routes Traefik et references de middlewares.
- [x] Ajouter des tests Cloudflare mockes.
- [x] Ajouter des tests Docker d'integration opt-in.
- [x] Ajouter ShellCheck et shfmt aux controles locaux.
- [x] Executer Ruff, Pytest, pip-audit et npm audit pour le webui.
- [x] Verifier la coherence VERSION/CHANGELOG avant une release.

## 12. Documentation Et Livraison

- [x] Aligner README sur le vrai parcours d'acces applicatif.
- [x] Implementer le menu d'acces documente ou corriger la documentation.
- [x] Mettre a jour AGENTS.md et les skills apres chaque lot.
- [x] Documenter le modele localhost du webui.
- [x] Documenter migrations SQLite, sauvegarde et restauration.
- [x] Documenter la politique de versions d'images et dependances.
- [x] Mettre a jour VERSION et CHANGELOG a chaque jalon.
- [x] Executer `/preflight` avant un lot significatif.
- [x] Executer `/check-project` avant livraison.
- [x] Declarer les controles non executes et les risques residuels.
