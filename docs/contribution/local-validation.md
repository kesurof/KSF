# Validation Locale

Le point d'entree unique des controles KSF disponibles est :

```bash
make validate
```

Cette commande verifie la syntaxe Bash, les validateurs partages, les routes,
le cycle de vie applicatif avec Docker simule, les DNS Cloudflare simules, la
matrice de rendu statique et les garanties zero-ecriture des dry-runs `deploy`,
`app install` et `install-cli`. Elle ne requiert ni reseau, ni daemon Docker,
ni dependance Web UI. Elle ne lance pas `docker compose config`, les tests
d'integration Docker, les tests Python/Web UI, les audits ou Playwright.

## Prerequis

- Bash.

`make validate` lance aussi ShellCheck et shfmt lorsqu'ils sont installes. Leur
absence affiche `SKIP` avec la commande d'installation et ne fait pas echouer
la validation hors ligne.

## Controles Cibles

```bash
make test-validators    # validateurs communs
make test-dry-run       # aucun fichier runtime cree
make test-install-cli   # aucun profil shell modifie
make test-routes-dns-lifecycle # routes, DNS Cloudflare mocke et lifecycle CLI
make test-app-install-rollback # rollback render, DNS, hook et Compose
make test-compose-matrix # rendu plateforme/apps, placeholders et middlewares
make check-shellcheck    # lint Bash, ou SKIP actionnable si absent
make check-shfmt         # format Bash, ou SKIP actionnable si absent
make check-release      # validate + format SemVer et entree CHANGELOG de VERSION
```

Les controles suivants sont opt-in et peuvent necessiter des outils locaux :

```bash
make check-compose      # docker compose config de la matrice + template WordPress
make test-docker        # smoke Compose et templates avec daemon Docker accessible
make check-webui        # lock check, Ruff, Pytest et build Tailwind du Web UI
```

Avant la premiere validation Web UI, installer les dependances verrouillees :

```bash
cd templates/apps/webui
uv sync --locked --all-groups
npm ci
make lock-check
make ui-install-browser # telecharge Chromium pour Playwright
make test-ui
cd ../../..
make validate
```

Pour une livraison, consigner dans `docs/checklists/release.md` les commandes
executees, les sorties `SKIP`, les controles opt-in non executes et les risques
residuels. Ne pas deduire qu'un controle opt-in a ete execute parce que
`make validate` a reussi.

La politique de mise a jour des dependances et des images est dans
`docs/contribution/dependency-policy.md`.

Les caches et artefacts produits par ces commandes (`node_modules`, `.venv`,
`__pycache__`, `.pytest_cache`, `.ruff_cache`, `playwright-report`,
`test-results`, `build` et `dist`) sont locaux et ignores par Git. Ne forcez
jamais leur ajout.
