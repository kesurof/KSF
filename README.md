# KSF

## Présentation

KSF est un outil léger pour installer et gérer une base Docker Compose sur un serveur Linux.

Il crée un runtime local dans `~/serverbox`, séparé du dépôt Git. Le dépôt contient les scripts et les templates ; les données, secrets, stacks générées et logs restent dans le runtime utilisateur.

KSF permet de gérer Traefik, OAuth2 Proxy, CrowdSec, DNS Cloudflare et des applications Docker Compose installables après l'installation initiale.

## Concepts importants

- `KSF` : l'outil, le dépôt Git et les scripts de gestion.
- `serverbox` : le runtime local utilisateur, par défaut `~/serverbox`.
- `./deploy.sh` : installation initiale de la base KSF.
- `./ksf.sh` : gestion de l'infrastructure installée.
- `./app.sh` : gestion des applications.

## Structure runtime

```text
~/serverbox/
├── apps/
├── data/
├── proxy/
├── stacks/
├── logs/
└── config/
```

- `apps/` : stacks Docker Compose générées pour les applications.
- `data/` : données persistantes des applications.
- `proxy/` : stacks et configuration de Traefik, OAuth2 Proxy et CrowdSec.
- `stacks/` : espace réservé aux stacks gérées localement.
- `logs/` : journaux d'installation et de gestion.
- `config/` : configuration KSF, dont `ksf.env`, et registre des apps installées.

## Installation rapide

```bash
git clone https://github.com/kesurof/ksf.git
cd ksf
./deploy.sh
```

L'assistant d'installation pose les questions nécessaires, affiche un résumé, permet de modifier la configuration, puis lance l'installation après validation.

`deploy.sh` est réservé à l'installation initiale. Si `~/serverbox/config/ksf.env` existe déjà, utilisez `./ksf.sh` pour gérer l'existant. En mode interactif, `deploy.sh` propose alors un choix explicite : forcer la réinstallation ou annuler. En non-interactif, utilisez `./deploy.sh --force` uniquement pour régénérer volontairement l'installation.

Si Traefik ou OAuth2 Proxy sont activés, les stacks correspondantes sont générées et démarrées automatiquement.

## Configuration

La configuration principale est stockée dans `~/serverbox/config/ksf.env`.

Ce fichier contient la configuration locale et peut contenir des secrets. Il doit rester uniquement sur le serveur, ne doit pas être versionné et devrait être lisible uniquement par son propriétaire.

Variables importantes :

- `BASE_DIR` : chemin du runtime local, par défaut `~/serverbox`.
- `DOMAIN` : domaine principal de l'installation.
- `DEFAULT_DOMAIN` : variable interne, automatiquement égale à `DOMAIN`.
- `DOMAINS` : liste des domaines autorisés pour les apps.
- `TRAEFIK_TRUSTED_IPS` : liste CIDR optionnelle des proxies de confiance Traefik pour l'IP réelle visiteur.

`DEFAULT_DOMAIN` est écrit pour l'usage interne de KSF. Pour choisir les domaines utilisables par les applications, utilisez `DOMAIN` et `DOMAINS`.

## Commandes principales

Menu interactif :

```bash
./ksf.sh
./ksf.sh menu
```

Le menu KSF affiche un tableau de bord dynamique du runtime, des services plateforme et des apps installees. Ses entrees sont `Vue d'ensemble`, `Applications`, `Infrastructure`, `Securite`, `Logs` et `Maintenance`.

Dans `Applications`, le catalogue, l'installation, la gestion d'une instance et sa suppression sont distincts. Le detail d'une instance donne acces a son statut, demarrage/arret, redemarrage, logs, mise a jour, reconfiguration de l'acces, rebuild et desactivation. Les actions destructives demandent confirmation.

Le parcours `Applications -> Installer une app` resout les valeurs par defaut dans le menu, affiche un resume final unique, puis lance `app.sh install --yes` sans reposer les memes questions. Il propose un sous-domaine sur le domaine par defaut, un autre domaine autorise seulement si plusieurs domaines sont configures, un host complet ou `local-only`.

Pour une exposition Traefik, le menu demande ensuite la protection OAuth2 Proxy et propose facultativement un port local. En `local-only`, un port lie a `127.0.0.1` est requis. Le menu refuse un domaine absent de `DOMAINS` et ne propose pas d'exposition publique lorsque Traefik ou le template ne le permettent pas.

Diagnostic :

```bash
./ksf.sh status
./ksf.sh config
./ksf.sh routes
./ksf.sh doctor
```

Rendu et redémarrage :

```bash
./ksf.sh render
./ksf.sh restart
```

Update :

```bash
./ksf.sh update crowdsec
./ksf.sh update traefik
./ksf.sh update oauth2
./ksf.sh update all --dry-run
```

CrowdSec / AppSec / WAF et trusted IPs :

```bash
./ksf.sh crowdsec status
./ksf.sh crowdsec decisions
./ksf.sh crowdsec appsec status
./ksf.sh trusted-ips cloudflare
./ksf.sh trusted-ips apply cloudflare
```

Maintenance locale :

```bash
./ksf.sh clean-data
```

## DNS et domaines

- `DOMAIN` est le domaine principal.
- `DOMAINS` est la liste des domaines autorisés pour les apps.
- Une app ne peut pas être exposée sur un domaine absent de `DOMAINS`.
- Si le DNS automatique est activé, KSF peut créer et supprimer les entrées Cloudflare des apps.

Les domaines utilisés par les apps doivent être autorisés dans `DOMAINS`. Par exemple, avec `DOMAINS=example.com,example.net`, une app peut être exposée sur `radarr.example.com` ou `radarr.example.net`, mais pas sur un autre domaine.

## OAuth2 Proxy

OAuth2 Proxy peut protéger Traefik et les apps exposées.

Le mode recommandé consiste à autoriser explicitement des emails GitHub avec `--oauth-allowed-email` pendant l'installation.

Après l'installation, configurez l'URL callback dans l'OAuth App GitHub :

```text
https://oauth2.<domaine>/oauth2/callback
```

Ne mettez jamais les secrets GitHub dans le dépôt.

## Mise à jour système

Les stacks système KSF se mettent à jour via `ksf.sh update`. Chaque update exécute `docker compose pull`, redémarre la stack puis lance `doctor`.

```bash
./ksf.sh update crowdsec
./ksf.sh update traefik
./ksf.sh update oauth2
./ksf.sh update all
```

`./ksf.sh update all` applique l'ordre sûr : CrowdSec, Traefik, puis OAuth2 Proxy. Utilisez `--dry-run` pour afficher les actions sans modifier le runtime, et `-y` ou `--yes` pour exécuter sans confirmation interactive.

## CrowdSec

CrowdSec est une brique de sécurité plateforme intégrée à Traefik. Ce n'est pas une app installable avec `app.sh`.

Activation à l'installation :

```bash
./deploy.sh --with-traefik --with-crowdsec
```

Fichiers locaux générés :

```text
~/serverbox/proxy/crowdsec/
~/serverbox/proxy/traefik/traefik.yml
~/serverbox/proxy/traefik/logs/access.log
~/serverbox/proxy/traefik/dynamic/middleware-crowdsec.yml
```

La clé bouncer est générée localement et stockée dans `~/serverbox/config/ksf.env`. CrowdSec n'est pas exposé par Traefik et sa Local API reste accessible uniquement sur le réseau Docker interne.

Traefik utilise le plugin CrowdSec nommé `bouncer` et le mode `stream`. Les routes publiques utilisent `security-chain` quand CrowdSec est actif. Les routes protégées restent sur `oauth2-chain`, qui appelle CrowdSec avant OAuth2 Proxy.

Si vos DNS Cloudflare sont en mode proxy, renseignez les CIDR Cloudflare via `--traefik-trusted-ips cloudflare` pendant l'installation, saisissez `cloudflare` dans le questionnaire, ou utilisez `./ksf.sh trusted-ips apply cloudflare` après installation. N'activez pas `forwardedHeaders.insecure=true` : sans trusted IPs correctes, CrowdSec peut voir et bannir les IP Cloudflare au lieu des vraies IP visiteurs.

### AppSec / WAF

CrowdSec classique analyse les logs Traefik et applique les décisions via le bouncer. AppSec / WAF inspecte aussi les requêtes HTTP en temps réel via une datasource AppSec interne avant qu'elles atteignent les services.

AppSec est une option avancée. Elle n'est pas activée par défaut avec `--with-crowdsec` afin de garder l'installation CrowdSec simple et stable.

Activation à l'installation :

```bash
./deploy.sh --with-traefik --with-crowdsec --with-appsec --force --yes
```

Activation après installation :

```bash
./ksf.sh crowdsec appsec enable
```

Désactivation :

```bash
./ksf.sh crowdsec appsec disable
```

Statut, métriques et test contrôlé :

```bash
./ksf.sh crowdsec appsec status
./ksf.sh crowdsec appsec metrics
./ksf.sh crowdsec appsec test
```

Test HTTP manuel :

```bash
curl -I https://<host>/.env
```

Le résultat attendu est `HTTP 403` si AppSec bloque correctement la requête. AppSec peut générer des faux positifs selon les applications exposées : surveillez les alertes et la Console CrowdSec après activation.

Le port AppSec `7422` reste interne au réseau Docker entre Traefik et CrowdSec. Il ne doit pas être publié sur l'hôte ni exposé publiquement.

Commandes utiles :

```bash
./ksf.sh crowdsec status
./ksf.sh crowdsec logs
./ksf.sh crowdsec decisions
./ksf.sh crowdsec alerts
./ksf.sh crowdsec metrics
./ksf.sh crowdsec bouncers
./ksf.sh crowdsec ban 1.2.3.4 10m
./ksf.sh crowdsec unban 1.2.3.4
./ksf.sh crowdsec flush-decisions
./ksf.sh crowdsec console-status
./ksf.sh crowdsec restart
./ksf.sh crowdsec appsec status
./ksf.sh crowdsec appsec enable
./ksf.sh crowdsec appsec disable
./ksf.sh crowdsec appsec metrics
./ksf.sh crowdsec appsec test
./ksf.sh trusted-ips cloudflare
./ksf.sh trusted-ips apply cloudflare
```

Ces commandes appellent `cscli` dans le conteneur CrowdSec via Docker Compose. Les décisions locales restent gérées par `cscli` : `decisions` liste les décisions actives, `ban` ajoute une décision locale, `unban` la supprime, et `flush-decisions` exécute `cscli decisions delete --all`. `flush-decisions` est destructif : il supprime toutes les décisions actives.

Connexion à la Console CrowdSec officielle :

1. Créez un compte sur `https://app.crowdsec.net`.
2. Récupérez le token ou la commande d'enrôlement dans la Console CrowdSec.
3. Lancez `./ksf.sh crowdsec enroll '<token-ou-commande>'` sur le serveur.
4. Vérifiez avec `./ksf.sh crowdsec console-status`.
5. Vérifiez dans la Console que le Security Engine apparaît.

Le token d'enrôlement ne doit pas être commité. KSF ne l'écrit pas dans le dépôt et masque le token dans les messages dry-run.

`./ksf.sh trusted-ips cloudflare` récupère les CIDR depuis les endpoints officiels Cloudflare (`https://www.cloudflare.com/ips-v4` et `https://www.cloudflare.com/ips-v6`) et affiche une ligne `TRAEFIK_TRUSTED_IPS=...` prête à coller dans `ksf.env`, sans modifier la configuration. `./ksf.sh trusted-ips apply cloudflare` met à jour `ksf.env`, régénère Traefik et redémarre Traefik. Si Cloudflare modifie ses plages IP, relancez la commande `apply`.

Pour désactiver CrowdSec, passez `WITH_CROWDSEC=false` dans `~/serverbox/config/ksf.env`, relancez `./ksf.sh render`, puis `./ksf.sh restart`. Vous pouvez ensuite arrêter la stack avec `cd ~/serverbox/proxy/crowdsec && docker compose down`. Les données locales restent dans `~/serverbox/proxy/crowdsec/`.

## Apps

```bash
./app.sh list
./app.sh install <template>
./app.sh status <instance>
./app.sh update <instance>
./app.sh configure <instance>
./app.sh restart <instance>
./app.sh disable <instance>
./app.sh remove <instance>
```

`remove` supprime la stack, la route et l'enregistrement de l'instance. Si un dossier de données local existe encore dans `~/serverbox/data/<instance>`, KSF propose ensuite explicitement de le supprimer, en affichant le chemin concerné avant confirmation.

`./ksf.sh clean-data <instance>` utilise le même wording: KSF affiche le chemin ciblé puis demande de confirmer avec le mot `SUPPRESSION` (majuscule ou minuscule acceptée).

Chaque app installable fournie par KSF part d'un template minimal `templates/apps/<template>/app.env` et `compose.yml`. Une fois installée, l'app devient une instance gérée sous `~/serverbox/apps/<instance>/`. La route Traefik `route-<instance>.yml` est générée automatiquement dans `~/serverbox/proxy/traefik/dynamic/` depuis `app.env`; par défaut une app exposée est protégée avec OAuth2 Proxy.

### Web UI

L'app `webui` expose les opérations d'administration KSF dans le navigateur. Elle doit être installée sur une plateforme déjà déployée et protégée par OAuth2 Proxy. La page **Opérations plateforme** permet de lancer le redémarrage et la mise à jour globale de l'infrastructure, le rendu complet, la réapplication d'OAuth2, les trusted IPs Cloudflare et les actions AppSec/CrowdSec.

Les opérations longues sont lancées comme jobs avec leur sortie affichée dans l'interface. Elles réutilisent les scripts KSF embarqués dans le conteneur Web UI, avec les mêmes mécanismes de rendu et de validation que le CLI. Les actions sensibles demandent une confirmation explicite. Les secrets Cloudflare et OAuth2 ne sont jamais renvoyés au navigateur.

Le webui est une frontiere d'administration: son montage runtime inscriptible et
le socket Docker lui donnent les privileges necessaires pour gerer KSF. Il reste
derriere Traefik et OAuth2 Proxy. Un port direct optionnel est strictement lie a
`127.0.0.1`, reserve a un administrateur connecte au serveur, et ne remplace pas
l'authentification. Les mutations navigateur exigent un `Origin` ou `Referer`
valide correspondant exactement au `Host`. En production, la specification
OpenAPI et les interfaces Swagger/ReDoc sont desactivees. Le webui ne se
reconstruit pas lui-meme: executez `./app.sh rebuild webui` depuis le serveur.

Le Web UI est l'unique exception a la regle interdisant les flags
`--with-<app>` de `deploy.sh` : `--with-webui` le delegue a `app.sh` une fois
l'infrastructure prete. Cette option requiert `--with-traefik`, `--domain` et
OAuth2 Proxy configure avec ses identifiants et une regle d'autorisation. Si
l'installation deleguee echoue, `deploy.sh` retourne un code non nul et indique
un deploiement plateforme partiel; les autres applications s'installent
uniquement via `app.sh`.

### Ports

KSF adopte le modèle suivant pour les apps :

- `APP_PORT` : port interne Docker de l'app. Il sert au routage Traefik et aux communications entre apps sur le réseau Docker.
- `APP_HOST_PORT` : port publié sur l'hôte en `127.0.0.1`. Il est optionnel et ne sert qu'à l'accès local depuis l'hôte.

Exemple :

- `radarr` peut écouter en interne sur `7878`
- `radarr2` peut aussi écouter en interne sur `7878`
- mais publier respectivement `127.0.0.1:7878` et `127.0.0.1:17878` si un accès local hôte est souhaité

Ainsi :

- Traefik et les autres apps Docker parlent toujours au port interne `APP_PORT`
- le port hôte local devient un choix explicite et ne crée plus de conflit multi-instance par défaut

Il n'y a pas de rétrocompatibilité avec l'ancien modèle où `APP_PORT` servait aussi de port publié hôte.

### Installation : domaine et sous-domaine

Pour une app exposée derrière Traefik, KSF doit connaître :

- le domaine cible
- le sous-domaine cible

En non-interactif, tu peux les fournir explicitement avec `--domain`, `--subdomain` ou `--host`.

En interactif, si tu n'as pas fourni `--host`, KSF pose les questions au moment de `install` :

1. mode d'accès
2. si tu choisis `Sous-domaine`, KSF utilise directement le domaine par défaut et ne redemande que le sous-domaine
3. si tu choisis explicitement un autre domaine, KSF demande alors le domaine puis le sous-domaine
4. protection OAuth2 si applicable
5. si tu choisis `local-only`, KSF demande un port hôte local à publier
6. si tu choisis une exposition via Traefik, KSF peut proposer en option un accès local direct via `APP_HOST_PORT`

### Flags ports

Les flags disponibles sont :

- `--port` : port interne Docker de l'instance
- `--host-port` : port publié sur `127.0.0.1` pour l'accès local hôte
- `--no-host-port` : supprime la publication locale hôte lors d'une reconfiguration

Le cas standard reste simple :

- app exposée via Traefik : pas de port hôte publié par défaut
- app `local-only` : proposition d'un port hôte local, avec valeur par défaut issue du template
- app exposée via Traefik avec besoin avancé : proposition optionnelle d'un port hôte local supplémentaire

Questions interactives :

```text
Mode d'acces :
  1) Sous-domaine sur <domaine-par-defaut>
  2) Sous-domaine sur un autre domaine
  3) Host complet
  4) Local-only
```

Si `local-only` :

```text
Port local hote [<valeur-par-defaut>] :
```

Si exposition via Traefik :

```text
Acces local direct sur l'hote :
  1) Non
  2) Oui, publier un port local
Choix [1] :
```

Puis si `2` :

```text
Port local hote [<valeur-par-defaut>] :
```

Exemples :

```bash
./app.sh install radarr --domain example.com --subdomain films --auth
./app.sh install wordpress --instance blog --domain example.com --subdomain blog
./app.sh install wordpress --host blog.example.net --no-auth
./app.sh install speedtest-tracker --domain example.com --subdomain speedtest --auth
```

### Templates fournis par défaut

| Template | Description | Catégorie | Port interne |
|---|---|---|---|
| `baseo` | Gestion documentaire et comptes entreprises | content | 3000 |
| `dockge` | Gestionnaire de stacks Docker | admin | 5001 |
| `radarr` | Gestion de films | media | 7878 |
| `speedtest-tracker` | Suivi des performances internet | monitoring | 80 |
| `wordpress` | Site optimisé (PHP-FPM + MariaDB + Redis) | content | 80 |

`speedtest-tracker` embarque une clé de chiffrement `APP_KEY` et son `APP_URL`
générés par le hook `pre_install.sh` dans `apps/<instance>/.env` (permissions
`600`). La clé est préservée lors des `update` / `rebuild` / réinstallation pour
conserver les valeurs chiffrées en base ; `APP_URL` est régénéré depuis la
configuration d'accès courante.

`baseo` embarque sa propre authentification interne (compte administrateur
initial, connexion, demande de création d'entreprise et codes d'invitation).
Son template déclare donc `APP_PROTECTED=false` explicitement et publie une
route publique derrière Traefik (middlewares CrowdSec le cas échéant). Les
secrets (`BASEO_ADMIN_EMAIL`, `BASEO_ADMIN_PASSWORD`, `POSTGRES_PASSWORD`,
`BASEO_BACKUP_PASSPHRASE`, etc.) sont générés par le hook `pre_install.sh`
dans `apps/<instance>/.env` (permissions `600`) et préservés lors des `update` /
`rebuild` ; `BASEO_IMAGE` y est versionné pour piloter les mises à jour.

Lors d'une installation interactive (`app.sh install baseo`), KSF pose après
les questions de domaine les questions du compte administrateur initial :

```text
Compte administrateur initial Baseo
  Adresse email (défaut: admin@example.com) : admin@example.com
  Mot de passe (vide = générer un mot de passe aléatoire) :
```

En non-interactif (`--yes`), les valeurs par défaut sont utilisées et
surchargeables via l'environnement :

```bash
BASEO_ADMIN_EMAIL=admin@example.com BASEO_ADMIN_PASSWORD=mon-mot-de-passe \
  ./app.sh install baseo --subdomain baseo --no-auth --yes
```

Après le premier démarrage, le mot de passe se change dans l'interface Baseo,
pas en modifiant `.env`.

Après installation, tu peux modifier uniquement l'accès d'une app sans la réinstaller :

```bash
./app.sh configure blog --subdomain articles
./app.sh configure blog --domain example.net
./app.sh configure blog --domain example.net --subdomain blog
./app.sh configure blog --host blog.example.net
./app.sh configure blog --host-port 18080
./app.sh configure blog --no-host-port
```

`configure` met à jour les fichiers d'instance, la route Traefik et, si le DNS auto est actif, l'enregistrement DNS associé.

Si `./app.sh install <template>` cible une instance déjà présente, KSF n'échoue plus sèchement en mode interactif : il propose explicitement de forcer la réinstallation de cette instance ou d'annuler. En non-interactif, utilisez `--force` uniquement pour réinstaller volontairement une instance du même template.

### Hooks pre/post install

Une app peut fournir deux scripts shell optionnels qui sont sourcés (et non exécutés) par `app.sh` aux moments clés du cycle de vie :

| Fichier | Moment d'exécution | Usage typique |
|---|---|---|
| `templates/apps/<app>/pre_install.sh` | Après le rendu du compose, avant `docker compose up` (et idem sur `update` / `rebuild`) | Génération de secrets, création de fichiers de config, génération de `${app_dir}/.env` pour docker compose |
| `templates/apps/<app>/post_install.sh` | Après un `docker compose up` réussi (et idem sur `update` / `rebuild`) | Activation de plugins, configuration post-démarrage via `wp-cli` ou `docker exec` |

Les hooks sont sourcés dans un sous-shell, ce qui leur donne accès à toutes les variables KSF (BASE_DIR, APP_DIR, APP_DATA, APP_PUID, APP_PGID, APP_HOST, APP_PORT, DRY_RUN, ...).

En dry-run, les hooks ne sont **pas exécutés** : ils sont uniquement loggués avec `[DRY-RUN] source <path>`. Le pre-install qui écrit un `.env` ne tourne donc pas en dry-run, ce qui signifie qu'un dry-run complet de bout en bout n'est pas possible pour les apps qui dépendent de secrets générés au pre-install. C'est cohérent avec la règle "le dry-run ne doit créer aucun fichier dans `${BASE_DIR}`".

### Multi-instance : installer plusieurs fois le même template

Pour des apps comme WordPress, Nextcloud, Gitea, Vaultwarden, etc., il est courant de vouloir plusieurs instances indépendantes sur la même plateforme. KSF supporte ce cas via le flag `--instance` :

```bash
./app.sh install wordpress --subdomain blog --instance blog
./app.sh install wordpress --subdomain shop --instance shop
./app.sh install wordpress --subdomain docs --instance docs
./app.sh list
#   blog    (template : wordpress)
#   docs    (template : wordpress)
#   shop    (template : wordpress)
./app.sh status blog
./app.sh update shop
./app.sh remove docs
```

Concepts :

- **Template** (`wordpress`) : le type d'app, défini par `templates/apps/<template>/`. Immuable, partagé entre toutes les instances.
- **Instance** (`blog`, `shop`, `docs`) : l'identité prioritaire côté KSF. Chaque instance a ses propres chemins (`apps/<instance>/`, `data/<instance>/`), son propre fichier `installed-apps/<instance>.env`, ses propres containers Docker, et sa propre route Traefik (via le `--subdomain`).

Le template doit référencer `${APP_INSTANCE}` dans son `compose.yml` pour tout ce qui doit être unique par instance, au minimum `container_name`, les volumes nommés et les chemins dérivés. Les templates fournis par défaut doivent respecter cette règle, y compris `radarr`, `dockge` et `wordpress`. C'est le template qui s'adapte : KSF raisonne d'abord en instance et ne doit pas supposer une structure Docker interne figée.

Si `--instance` n'est pas fourni, l'instance prend le nom du template (mode mono-instance historique, rétrocompatible).

### Status et apps multi-services

Quand une app embarque plusieurs services dans un seul `compose.yml` comme `web`, `wp`, `db` et `cache`, KSF traite toujours l'installation comme une seule instance, mais le diagnostic affiche aussi un résumé par service.

Exemple attendu :

```text
Etat stack : running (4/4 service(s) running)
Service cle : web -> blog-web (running, health: healthy)
Services :
  - web: healthy
  - wp: healthy
  - db: healthy
  - cache: healthy
```

`APP_DOCKER_SERVICE` dans `app.env` reste le point d'entrée principal pour Traefik et pour l'identification du service clé dans les statuts KSF. Le reste de la stack est diagnostiqué via `docker compose ps -a` dans le dossier de l'instance.

Exemples :

```bash
./app.sh install radarr --subdomain radarr --auth
./app.sh install radarr --subdomain radarr --domain example.com --auth
./app.sh install radarr --subdomain radarr --no-auth
./app.sh install radarr --local-only
```

## Dry-run

```bash
./deploy.sh --dry-run
```

Le dry-run simule l'installation sans appliquer de modification au runtime. Les actions simulées sont préfixées par `[DRY-RUN]` et les logs sont écrits dans un répertoire temporaire hors de `~/serverbox`.

Utilisez ce mode pour vérifier le plan avant une installation réelle.

## Prérequis

- Linux.
- Bash.
- Docker.
- Plugin Docker Compose.
- Node.js et npm (validation et build du Web UI).
- Python 3.12 et `uv` (validation et dependances du Web UI).
- Accès réseau.
- Domaine DNS si exposition publique.
- Compte Cloudflare pour Traefik avec DNS-01 ou DNS automatique.
- OAuth App GitHub si OAuth2 Proxy est activé.

## Contribution

Les conventions de developpement sont documentees dans `docs/`. Les agents,
commandes et skills OpenCode du depot sont dans `.opencode/` : `/preflight`
confronte un plan significatif et `/check-project` execute une revue de
coherence avant livraison.

La validation locale par defaut ne demande ni reseau ni daemon Docker : executez
`make validate` depuis la racine. Elle couvre la syntaxe Bash, les validateurs,
les dry-runs, `install-cli`, les routes, le DNS Cloudflare simule, le lifecycle
applicatif simule et la matrice de rendu statique. ShellCheck et shfmt sont
executes s'ils sont presents, sinon la sortie indique clairement comment les
installer. `make check-release` ajoute la coherence entre `VERSION` et
`CHANGELOG.md`. Les controles Docker, Compose et Web UI restent opt-in ; leurs
prerequis et leur perimetre sont documentes dans
`docs/contribution/local-validation.md`. La politique de versions des dependances et images est dans
`docs/contribution/dependency-policy.md`.

Le Web UI utilise `uv` pour les dependances Python et npm/Node pour compiler
Tailwind CSS. Depuis `templates/apps/webui/`, les commandes utiles sont :

```bash
uv sync --locked --all-groups
npm ci
make verify
make ui-install-browser
make test-ui
```

`make verify` execute le lock check, Ruff, Pytest et le build CSS. Les audits
(`make audit-python`, `make audit-npm`), la construction d'image (`make build`)
et la suite navigateur (`make test-ui`) sont explicites et peuvent demander des
outils ou un acces reseau supplementaires.

Les details d'architecture, de securite, d'UX et de validation webui sont dans
`docs/webui/`. Les mises a jour de `uv.lock` et `package-lock.json`, les audits
et les versions de l'image webui sont documentes dans
`docs/contribution/dependency-policy.md`.

## Notes de sécurité

- Les secrets restent dans `~/serverbox/config/ksf.env`.
- Les permissions recommandées pour `ksf.env` sont `600`.
- Ne commitez jamais `~/serverbox/config/ksf.env`.
- Ne commitez jamais les clés bouncer, données, décisions ou bases CrowdSec générées localement.
- N'exposez pas d'application sans authentification sauf choix volontaire.
- Vérifiez l'installation avec `./ksf.sh doctor`.
