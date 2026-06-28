# AGENTS.md

Instructions de développement pour les agents travaillant sur KSF.

## Objectif du projet

KSF automatise la préparation d'un serveur Linux et la gestion d'une plateforme Docker Compose locale avec séparation stricte des responsabilités.

- `bootstrap.sh` : préparation système, utilisateur, SSH, Docker.
- `deploy.sh` : installation initiale de la plateforme KSF.
- `app.sh` : cycle de vie des applications installables.
- `ksf.sh` : exploitation et maintenance d'une installation existante.

Ne pas mélanger ces responsabilités.

## Priorités de développement

- Favoriser les changements petits, lisibles et testables.
- Préserver la compatibilité Bash et Linux serveur.
- Ne pas introduire de dépendance lourde sans justification claire.
- Ne pas hardcoder de domaine réel, email réel, identifiant personnel, chemin local personnel ou secret.
- Utiliser `example.com`, `admin`, `monuser` et des valeurs génériques dans les exemples publics.
- Ne jamais committer de secrets, tokens, `.env` générés, logs, données applicatives ou runtime local.
- Ne jamais supprimer les données applicatives lors d'une suppression d'app sauf demande explicite.
- Maintenir des messages d'erreur clairs quand une entrée utilisateur est invalide ou incomplète.

## Architecture attendue

Structure source actuelle :

```text
bootstrap.sh
deploy.sh
app.sh
ksf.sh
lib/
  app_steps.sh
  common.sh
  deploy_steps.sh
  dns_cloudflare.sh
  manage_steps.sh
  menu.sh
  render.sh
  steps.sh
  update_steps.sh
templates/
  apps/
  compose/
  crowdsec/
  env/
  oauth2-proxy/
  traefik/
```

Runtime généré localement :

```text
~/serverbox/
  .env
  apps/
  config/
    ksf.env
    installed-apps/
  data/
  logs/
  proxy/
    crowdsec/
    oauth2-proxy/
    traefik/
  stacks/
```

Le dépôt Git contient les scripts et templates. Le runtime local sous `~/serverbox` contient les fichiers générés, secrets, stacks rendues et données serveur.

## Frontières des scripts

### `bootstrap.sh`

Autorisé :

- Installer les paquets système.
- Installer Docker et le plugin Docker Compose.
- Créer un utilisateur système.
- Installer une clé SSH.
- Durcir SSH.
- Créer l'arborescence runtime initiale si pertinent.
- Ajouter l'utilisateur au groupe `docker`.

Interdit :

- Générer des stacks applicatives.
- Installer Traefik, OAuth2 Proxy, CrowdSec ou une app métier.
- Gérer les routes Traefik ou le DNS applicatif.

### `deploy.sh`

Autorisé :

- Générer la configuration initiale KSF.
- Générer le réseau Docker de la plateforme.
- Générer Traefik.
- Générer OAuth2 Proxy si activé.
- Générer CrowdSec et AppSec si activés.
- Sauvegarder `~/serverbox/config/ksf.env`.
- Démarrer les stacks d'infrastructure générées.
- Si une installation existe déjà et que l'agent est en mode interactif, proposer un choix explicite entre forcer la réinstallation et annuler ; en non-interactif, exiger `--force`.

Interdit :

- Installer des apps métier via des flags `--with-<app>`.
- Gérer le cycle de vie de Radarr, Dockge, WordPress ou autres apps applicatives.
- Modifier l'utilisateur système, SSH ou l'installation Docker.

### `app.sh`

Autorisé :

- Lister les apps disponibles et installées.
- Lister les templates d'apps disponibles et les apps installées.
- Installer une app depuis `templates/apps/<template>/`.
- Installer plusieurs instances d'un même template via `--instance`.
- Mettre à jour, reconfigurer l'accès, reconstruire, démarrer, arrêter, redémarrer, désactiver ou supprimer une instance installée.
- Générer la stack applicative et la route Traefik associée.
- Appliquer OAuth2 Proxy par app si demandé.
- Gérer les hooks optionnels `pre_install.sh` et `post_install.sh` d'une app.

Interdit :

- Installer Docker.
- Régénérer toute la plateforme.
- Modifier la configuration SSH ou système.
- Gérer les stacks plateforme hors périmètre applicatif.

### `ksf.sh`

Autorisé :

- Exploiter une installation existante : `status`, `config`, `routes`, `doctor`, `render`, `restart`.
- Gérer CrowdSec, AppSec / WAF et les trusted IPs.
- Gérer les updates de stacks système.
- Nettoyer les données conservées avec `clean-data`.
- Installer ou supprimer la commande CLI globale `ksf`.
- Diagnostiquer l'état de Traefik, OAuth2 Proxy, CrowdSec et des apps installées.

Interdit :

- Installer Docker ou modifier la configuration SSH ou système.
- Installer ou supprimer des apps métier hors cycle `app.sh`.
- Régénérer une plateforme initiale comme `deploy.sh`.

## Applications

Chaque template d'application doit vivre dans un dossier dédié :

```text
templates/apps/<app>/
  app.env
  compose.yml
```

Hooks optionnels autorisés :

```text
templates/apps/<app>/
  pre_install.sh
  post_install.sh
```

Règles :

- Un seul `compose.yml` par template d'application.
- Les routes Traefik applicatives sont générées automatiquement depuis `app.env`.
- Ne pas ajouter de `route.yml` ou `route-oauth2.yml` dans les templates d'apps.
- `APP_PROTECTED=true` est le défaut et génère une route avec OAuth2 Proxy.
- `APP_PROTECTED=false` doit être explicite pour générer une route publique.
- Les données persistantes vont dans `${BASE_DIR}/data/<instance>`.
- La stack générée va dans `${BASE_DIR}/apps/<instance>`.
- L'enregistrement d'installation va dans `${BASE_DIR}/config/installed-apps/<instance>.env`.
- Les routes générées vont dans `${BASE_DIR}/proxy/traefik/dynamic/route-<instance>.yml`.
- Les ports directs doivent être limités à `127.0.0.1` si nécessaires.
- Ne pas exposer une app publiquement hors Traefik.
- En mode multi-instance, le template doit utiliser `${APP_INSTANCE}` pour éviter les collisions de noms, volumes ou containers, y compris dans `container_name`, les volumes nommés et les chemins dérivés.
- Les templates fournis par défaut doivent eux aussi rester multi-instance safe ; ne pas laisser d'exception implicite pour `radarr`, `dockge`, `wordpress` ou une autre app du dépôt.
- Dans KSF, `APP_INSTANCE` est l'identité prioritaire affichee a l'utilisateur ; `APP_NAME` reste le nom du template.
- Pour les apps multi-services dans un seul `compose.yml`, utiliser `APP_DOCKER_SERVICE` pour declarer le service upstream principal ; les autres services doivent etre diagnostiquables via `docker compose ps -a`.
- Le diagnostic doit pouvoir afficher un resume simple par service, par exemple `web: healthy`, `db: healthy`, `cache: healthy`.
- Quand une app est exposee, le parcours d'installation doit poser les questions de domaine et sous-domaine si `--host`, `--domain` et `--subdomain` n'ont pas deja ete fournis.
- La reconfiguration d'une app doit permettre de modifier seulement le sous-domaine et/ou le domaine sans reinstallation complete.

## Templates et rendu

- Les templates utilisent le format `${VARIABLE}`.
- Les fichiers générés ne doivent plus contenir de placeholders.
- Ne pas introduire de blocs de placeholders YAML difficiles à relire.
- Les fichiers Compose rendus doivent rester valides avec `docker compose config`.
- Les middlewares Traefik doivent rester séparés des routes et des Compose.
- Les routes plateforme restent dans `templates/traefik/`.
- Les stacks plateforme restent dans `templates/compose/`.

## Sécurité

- Les fichiers contenant des secrets doivent être créés en permission `600`.
- `ksf.env`, `.env` et les fichiers d'app installée ne doivent pas être commités.
- OAuth2 Proxy doit rester optionnel au niveau plateforme et au niveau application.
- Si OAuth2 Proxy est demandé pour une app alors qu'il n'est pas configuré, le script doit échouer explicitement.
- Ne jamais exposer le socket Docker en écriture si un montage read-only suffit.
- Tout accès direct à une UI d'administration doit être local-only ou protégé par Traefik et éventuellement OAuth2 Proxy.
- CrowdSec et AppSec restent des briques plateforme, pas des apps installables.

## Dry-run

Les modes dry-run doivent garantir zéro écriture persistante dans `${BASE_DIR}`.

Obligatoire :

- `deploy.sh --dry-run` ne doit créer aucun fichier dans `${BASE_DIR}`.
- `app.sh install <app> --dry-run` ne doit créer ni stack, ni route, ni entrée `installed-apps`.
- Les hooks d'app ne doivent pas être exécutés en dry-run ; ils doivent seulement être loggués.
- Les actions simulées doivent être préfixées par `[DRY-RUN]`.

## Validation obligatoire

Après modification de scripts Bash :

```bash
bash -n bootstrap.sh deploy.sh app.sh ksf.sh lib/*.sh
```

Après modification d'un template Compose, valider au minimum avec des variables de test :

```bash
BASE_DIR=/tmp/ksf-compose-test NETWORK_NAME=proxy TZ_VALUE=Europe/Paris \
APP_PUID=$(id -u) APP_PGID=$(id -g) APP_INSTANCE=radarr \
docker compose -f templates/apps/radarr/compose.yml config >/dev/null
```

Pour les changements touchant la génération ou le rendu, tester dans un répertoire temporaire neutre :

```bash
./deploy.sh --base-dir /tmp/ksf-test \
  --with-traefik \
  --domain example.com \
  --acme-email admin@example.com \
  --oauth-client-id id \
  --oauth-client-secret secret \
  --oauth-github-user monuser \
  -y

./app.sh install radarr \
  --base-dir /tmp/ksf-test \
  --subdomain films \
  --auth \
  -y
```

Vérifier ensuite :

```bash
docker compose -f /tmp/ksf-test/proxy/traefik/docker-compose.yml config >/dev/null
docker compose -f /tmp/ksf-test/proxy/oauth2-proxy/docker-compose.yml config >/dev/null
docker compose -f /tmp/ksf-test/apps/radarr/docker-compose.yml config >/dev/null
```

## Documentation et cohérence

- Toute nouvelle app fournie par défaut doit être documentée dans le README.
- Toute nouvelle commande utilisateur ou tout nouveau flag notable doit être reflété dans le README et l'aide CLI concernée.
- `AGENTS.md` doit rester aligné avec l'architecture réelle du repo, pas avec une architecture supposée.
- Si une convention apparaît à la fois dans le code, le README et `AGENTS.md`, éviter les contradictions ; mettre à jour les trois quand nécessaire.

## Git et fichiers générés

- Ne pas créer de commit sans demande explicite.
- Ne pas modifier l'historique Git sans demande explicite.
- Ne pas ajouter les fichiers générés sous `~/serverbox`.
- Ne pas ajouter de logs, secrets, données applicatives ou artefacts runtime.
