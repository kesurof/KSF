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

- [ ] Ajouter des validateurs partages pour instance, domaine, sous-domaine,
  host, port et chemins derives.
- [ ] Valider les arguments avant toute ecriture, route, appel DNS ou Compose.
- [ ] Corriger `ksf.sh install-cli --dry-run` afin qu'il ne modifie jamais les
  profils shell.
- [ ] Ajouter ou clarifier le support `bootstrap.sh --dry-run`.
- [ ] Garantir que les logs bootstrap dry-run restent hors de `${BASE_DIR}`.
- [ ] Ajouter des tests zero-ecriture pour bootstrap, deploy, app install et
  install-cli.

## 2. Cycle De Vie Des Apps

- [ ] Faire de `app.sh` la source unique des mutations applicatives.
- [ ] Faire deleguer les mutations webui a `app.sh` via des jobs.
- [ ] Corriger le rendu webui de `DOCKER_GROUP_ADD_BLOCK`.
- [ ] Aligner le fallback `APP_DOCKER_SERVICE` avec le CLI Bash.
- [ ] Declarer `APP_DOCKER_SERVICE` dans chaque template fourni.
- [ ] Ajouter des tests de parite CLI/Web UI pour chaque template.
- [ ] Ajouter un rollback pour les erreurs de rendu, DNS, hook et Compose.
- [ ] Ne jamais supprimer les donnees existantes pendant un rollback.

## 3. Deploy Avec Webui

- [ ] Valider que `--with-webui` requiert Traefik, domaine et OAuth2 Proxy.
- [ ] Faire echouer `deploy.sh` si l'installation webui deleguee echoue.
- [ ] Distinguer explicitement deployment plateforme et deployment partiel dans
  les logs et le code retour.
- [ ] Aligner aide CLI, README et AGENTS.md.

## 4. Rendu WordPress Et Secrets

- [ ] Identifier tous les placeholders WordPress et Compose differes.
- [ ] Generer les secrets par instance dans des fichiers runtime `600`.
- [ ] Rendre les Compose sans placeholder KSF residuel.
- [ ] Tester deux instances WordPress avec secrets et donnees distincts.
- [ ] Verifier les permissions des fichiers generes.
- [ ] Epingler et verifier le telechargement WP-CLI, ou le supprimer.

## 5. Securite Webui

- [ ] Conserver les ports directs webui sur `127.0.0.1` uniquement.
- [ ] Documenter localhost comme frontiere de confiance acceptee.
- [ ] Normaliser la verification stricte Origin/Referer/Host.
- [ ] Refuser les mutations navigateur sans Origin ni Referer valide.
- [ ] Desactiver OpenAPI et Swagger en production.
- [ ] Exiger une confirmation serveur pour les actions sensibles et destructives.
- [ ] Ajouter des tests HTTP directs pour les confirmations et CSRF.
- [ ] Supprimer le self-rebuild root/non deterministe du webui.
- [ ] Conserver le rebuild webui via CLI jusqu'a un mecanisme sur execute avec
  UID/GID hote.
- [ ] Documenter et tester le socket Docker comme frontiere administrative.
- [ ] Renforcer la redaction des secrets dans les jobs, logs et SQLite.

## 6. Base De Donnees Webui

- [ ] Rendre le chemin SQLite configurable et testable.
- [ ] Creer repertoire et base avec permissions et ownership hote corrects.
- [ ] Ajouter une table `schema_migrations` et des migrations transactionnelles.
- [ ] Retirer les `except Exception: pass` de migration.
- [ ] Sauvegarder avant toute migration destructive.
- [ ] Configurer et documenter WAL, busy timeout et integrity check.
- [ ] Ajouter une retention des jobs.
- [ ] Empecher les jobs concurrents au niveau SQLite.
- [ ] Tester base vide, base peuplee, upgrade, erreur, permissions, concurrence,
  redaction et restauration.

## 7. Migration HTMX

- [ ] Migrer dashboard et statuts vers des fragments serveur.
- [ ] Migrer liste et detail des applications.
- [ ] Migrer installation et configuration d'app.
- [ ] Migrer infrastructure et logs.
- [ ] Migrer general, routes, config et doctor.
- [ ] Migrer CrowdSec, AppSec et securite.
- [ ] Migrer maintenance et operations longues.
- [ ] Limiter Alpine au drawer, modales, menus et etat visuel local.
- [ ] Ajouter chargement, vide, erreur, succes et donnees longues a chaque flux.
- [ ] Gerer focus et annonces apres swaps HTMX.
- [ ] Ajouter des tests de fragments et erreurs HTTP.

## 8. Tailwind Et Accessibilite

- [ ] Conserver `legacy.css` charge tant que ses classes sont utilisees.
- [ ] Verifier que `app.css` compile conserve les selecteurs legacy requis.
- [ ] Inventorier les styles legacy par ecran.
- [ ] Migrer les composants partages vers tokens et utilitaires Tailwind.
- [ ] Retirer les styles inline.
- [ ] Implementer modal accessible avec focus trap et restauration du focus.
- [ ] Implementer tabs, dropdowns et combobox accessibles au clavier.
- [ ] Ajouter les icones SVG manquantes.
- [ ] Preserver dark mode, contraste, focus visible et reduced motion.
- [ ] Servir HTMX et Alpine localement depuis des dependances npm verrouillees.
- [ ] Supprimer `legacy.css` seulement lorsqu'il est vide et non reference.

## 9. Validation UI

- [ ] Installer et configurer Playwright.
- [ ] Remplacer `make test-ui` par une suite executable.
- [ ] Tester les parcours critiques a 390 x 844 et 1440 x 900.
- [ ] Tester navigation, drawer, modales, formulaires, jobs, logs et maintenance.
- [ ] Tester dark mode, reduced motion, etats vide/erreur/chargement/succes et
  textes longs.
- [ ] Ajouter des controles d'accessibilite, focus et clavier.

## 10. Dependances Et Images

- [ ] Supprimer `templates/apps/webui/requirements.txt`.
- [ ] Utiliser `pyproject.toml`/`uv.lock` comme source Python unique.
- [ ] Utiliser `package.json`/`package-lock.json` comme source Node unique.
- [ ] Ajouter les cibles locales audit Python, audit npm, lock check et build
  image.
- [ ] Documenter la mise a jour des fichiers lock.
- [ ] Remplacer toutes les images `latest` par des tags versionnes revus.
- [ ] Epingler les tags Node, Python et uv du Dockerfile.
- [ ] Documenter les versions Docker CLI et Compose de l'image webui.
- [ ] Nettoyer les caches, bytecode et fichiers temporaires des templates.
- [ ] Reduire les copies larges de `pre_install.sh` a une liste explicite.

## 11. Suite De Validation Locale

- [ ] Ajouter des tests Bash pour validateurs, dry-run, routes, DNS et lifecycle.
- [ ] Ajouter une matrice de rendu Compose plateforme et applications.
- [ ] Executer `docker compose config --quiet` sur chaque Compose rendu.
- [ ] Echec si un placeholder KSF reste dans un fichier genere.
- [ ] Valider routes Traefik et references de middlewares.
- [ ] Ajouter des tests Cloudflare mockes.
- [ ] Ajouter des tests Docker d'integration opt-in.
- [ ] Ajouter ShellCheck et shfmt aux controles locaux.
- [ ] Executer Ruff, Pytest, pip-audit et npm audit pour le webui.
- [ ] Verifier la coherence VERSION/CHANGELOG avant une release.

## 12. Documentation Et Livraison

- [ ] Aligner README sur le vrai parcours d'acces applicatif.
- [ ] Implementer le menu d'acces documente ou corriger la documentation.
- [ ] Mettre a jour AGENTS.md et les skills apres chaque lot.
- [ ] Documenter le modele localhost du webui.
- [ ] Documenter migrations SQLite, sauvegarde et restauration.
- [ ] Documenter la politique de versions d'images et dependances.
- [ ] Mettre a jour VERSION et CHANGELOG a chaque jalon.
- [ ] Executer `/preflight` avant un lot significatif.
- [ ] Executer `/check-project` avant livraison.
- [ ] Declarer les controles non executes et les risques residuels.
