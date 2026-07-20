# Politique Des Dependances

Les dependances doivent rester explicites, reproductibles et limitees au besoin
fonctionnel. Une dependance ne doit pas etre ajoutee pour remplacer une fonction
simple deja disponible en Bash, Python ou Node standard.

## Web UI

- Python est defini par `pyproject.toml` et verrouille par `uv.lock`.
- Node est defini par `package.json` et verrouille par `package-lock.json`.
- Installer avec `uv sync --locked --all-groups` et `npm ci` ; ne pas modifier
  les fichiers lock manuellement.
- Pour mettre a jour Python, modifier `pyproject.toml`, executer `uv lock` (ou
  `uv lock --upgrade <paquet>`), puis tester le lock avec `make lock-check`.
- Pour mettre a jour Node, modifier `package.json`, executer `npm install
  --package-lock-only`, puis tester le lock avec `make lock-check`.
- Toute mise a jour de dependance inclut les fichiers manifest et lock, les
  controles adaptes et une note dans le changelog lorsqu'elle est notable.
- Les audits de vulnerabilites sont executes explicitement avec les outils
  disponibles ; ils ne font pas partie de `make validate` car ils peuvent
  demander un acces reseau a une base d'avis de securite.

## Images Docker

- Les remplacements de `latest` utilisent un tag de version ou de revision
  exact. Une nouvelle image ou une mise a jour ne doit jamais introduire
  `latest`; les tags de branche ou majeurs seuls ne sont pas acceptes.
- Les versions remplacees lors de la revue du 20 juillet 2026 sont :
  `quay.io/oauth2-proxy/oauth2-proxy:v7.15.3`,
  `crowdsecurity/crowdsec:v1.7.8`, `louislam/dockge:1.5.0` et
  `lscr.io/linuxserver/radarr:6.3.0.10514-ls312`.
- Toute mise a jour doit etre revue dans les notes de version amont, conserver
  les options Compose existantes et mettre a jour cette liste si elle concerne
  une des images ci-dessus.
- Une mise a jour d'image est testee par rendu Compose et, quand Docker est
  disponible, par `docker compose config` avant livraison.
- Les images de build du Web UI et les paquets Docker CLI/Compose utilisent des
  versions explicites documentees dans `docs/webui/container.md`.

## Controles Locaux

`make validate` reste hors ligne et sans daemon Docker. Les controles Web UI,
Compose, audits et integration Docker sont opt-in afin de ne pas masquer un
echec de test par une dependance d'environnement.

Depuis `templates/apps/webui/`, les cibles disponibles sont `make lock-check`,
`make audit-python`, `make audit-npm`, `make test-ui` et `make build`. Les audits
et l'installation du navigateur Playwright peuvent necessiter un acces reseau.
