# AGENTS.md

Instructions de développement pour les agents travaillant sur KSF.

## Objectif du projet

KSF automatise la préparation d'un serveur Linux et la gestion de stacks Docker avec une séparation stricte :

- `bootstrap.sh` : installation système, utilisateur, Docker, SSH, groupes.
- `deploy.sh` : installation initiale de la plateforme, réseau Docker, Traefik, OAuth2 Proxy.
- `app.sh` : cycle de vie des applications installables après l'installation initiale.

Ne pas mélanger ces responsabilités.

## Règles générales

- Favoriser les changements petits, lisibles et testables.
- Ne pas introduire de dépendance lourde sans justification claire.
- Ne pas hardcoder de données personnelles, domaine réel, email réel, chemin local personnel ou secret.
- Les exemples publics doivent utiliser `example.com`, `admin`, `monuser` ou des valeurs génériques.
- Ne jamais committer de secrets, tokens, fichiers `.env` générés, logs ou données serveur.
- Garder les scripts compatibles Bash et Linux serveur.
- Ne pas supprimer les données applicatives lors d'une suppression d'app sauf demande explicite.

## Architecture attendue

Structure source :

```text
bootstrap.sh
deploy.sh
app.sh
ksf.sh
lib/
  common.sh
  steps.sh
  deploy_steps.sh
  app_steps.sh
  backup_steps.sh
  update_steps.sh
  render.sh
templates/
  compose/
  env/
  traefik/
  apps/
```

Structure générée :

```text
~/serverbox/
  .env
  config/
    ksf.env
    installed-apps/
  proxy/
    traefik/
    oauth2-proxy/
  apps/
  data/
  logs/
  backups/
```

## Responsabilités des scripts

### `bootstrap.sh`

Autorisé :

- Installer les paquets système.
- Installer Docker et Docker Compose.
- Créer un utilisateur.
- Installer une clé SSH.
- Durcir SSH.
- Créer l'arborescence initiale.
- Ajouter l'utilisateur au groupe `docker`.

Interdit :

- Générer des stacks applicatives.
- Installer Radarr, Dockge ou toute autre app métier.
- Gérer OAuth2 ou les routes Traefik.

### `deploy.sh`

Autorisé :

- Générer la configuration initiale KSF.
- Générer le réseau Docker.
- Générer Traefik.
- Générer OAuth2 Proxy si activé.
- Sauvegarder `~/serverbox/config/ksf.env`.

Interdit :

- Ajouter des flags `--with-<app>` pour des applications futures.
- Installer Radarr, Dockge, Sonarr, Portainer ou autres apps.
- Modifier l'utilisateur système ou Docker.

### `app.sh`

Autorisé :

- Lister les apps disponibles.
- Lister les apps installées.
- Installer une app depuis `templates/apps/<app>/`.
- Supprimer une app en préservant ses données.
- Générer les routes Traefik applicatives.
- Appliquer OAuth2 Proxy par app si demandé.

Interdit :

- Installer Docker.
- Régénérer toute la plateforme.
- Modifier la configuration SSH ou système.

### `ksf.sh`

Autorisé :

- Exploiter une installation existante : `doctor`, `render`, `restart`.
- Gérer CrowdSec, AppSec / WAF et les trusted-ips.
- Gérer les sauvegardes locales et les updates de stacks système.
- Diagnostiquer l'état de Traefik, OAuth2 Proxy, CrowdSec et des apps installées.

Interdit :

- Installer Docker ou modifier la configuration SSH/système.
- Installer ou supprimer des apps métier hors cycle `app.sh`.
- Régénérer une plateforme initiale comme `deploy.sh`.

## Ajout d'une application

Chaque application doit avoir un dossier dédié :

```text
templates/apps/<app>/
  app.env
  compose.yml
```

Règles :

- Un seul `compose.yml` par application.
- Les routes Traefik applicatives sont générées automatiquement depuis `app.env`.
- Ne pas ajouter de `route.yml` ou `route-oauth2.yml` dans les templates d'apps.
- `APP_PROTECTED=true` est le défaut et génère une route avec OAuth2 Proxy.
- `APP_PROTECTED=false` doit être explicite pour générer une route publique.
- Les données persistantes vont dans `${BASE_DIR}/data/<app>`.
- La stack générée va dans `${BASE_DIR}/apps/<app>`.
- Les routes générées vont dans `${BASE_DIR}/proxy/traefik/dynamic/route-<app>.yml`.
- Les ports directs doivent être limités à `127.0.0.1` si nécessaires.
- Ne pas exposer une app publiquement hors Traefik.

## Templates

- Les templates utilisent le format `${VARIABLE}`.
- Les fichiers générés ne doivent plus contenir de placeholders.
- Ne pas utiliser de placeholders de blocs YAML illisibles.
- Les Compose doivent rester valides avec `docker compose config` après rendu.
- Les routes Traefik doivent rester dans `templates/traefik/` ou `templates/apps/<app>/`.
- Les middlewares Traefik doivent rester séparés des routes et des Compose.

## Sécurité

- Les fichiers contenant des secrets doivent être créés en permission `600`.
- `ksf.env`, `.env` et les fichiers d'app installée ne doivent pas être commités.
- OAuth2 Proxy doit rester optionnel au niveau plateforme et optionnel par application.
- Si OAuth2 Proxy est demandé pour une app alors qu'il n'est pas configuré, le script doit échouer explicitement.
- Ne jamais exposer le socket Docker en écriture si un montage read-only suffit.
- Tout accès direct à une UI d'administration doit être local-only ou protégé par Traefik/OAuth2 Proxy.

## Dry-run

Les modes dry-run doivent garantir aucune écriture persistante.

Obligatoire :

- `deploy.sh --dry-run` ne doit pas créer de fichiers dans `${BASE_DIR}`.
- `app.sh install <app> --dry-run` ne doit pas créer de stack, route ou entrée `installed-apps`.
- Les actions simulées doivent être préfixées par `[DRY-RUN]`.

## Validation obligatoire

Après modification de scripts :

```bash
bash -n bootstrap.sh
bash -n deploy.sh
bash -n app.sh
bash -n ksf.sh
bash -n lib/common.sh
bash -n lib/steps.sh
bash -n lib/deploy_steps.sh
bash -n lib/app_steps.sh
bash -n lib/manage_steps.sh
bash -n lib/backup_steps.sh
bash -n lib/update_steps.sh
bash -n lib/render.sh
```

Ou, pour couvrir les scripts et bibliothèques présents :

```bash
bash -n ksf.sh lib/*.sh
```

Après modification de templates Compose, valider avec des variables de test :

```bash
BASE_DIR=/tmp/df-test NETWORK_NAME=proxy TZ_VALUE=Europe/Paris \
APP_PUID=$(id -u) APP_PGID=$(id -g) \
docker compose -f templates/apps/radarr/compose.yml config >/dev/null
```

Pour les changements touchant la génération, tester dans un répertoire temporaire neutre :

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

## Git et fichiers générés

- Ne pas créer de commit sans demande explicite.
- Ne pas modifier l'historique Git sans demande explicite.
- Ne pas ajouter les fichiers générés sous `~/serverbox`.
- Ne pas ajouter de logs, secrets ou données applicatives.

## Qualité attendue

- Toute erreur utilisateur doit produire un message clair.
- Toute variable obligatoire manquante doit faire échouer le script explicitement.
- Toute app installée doit être enregistrée dans `config/installed-apps/<app>.env`.
- Toute suppression d'app doit préserver `${BASE_DIR}/data/<app>`.
- Toute nouvelle app doit être documentée dans le README si elle est fournie par défaut.
