# Conteneur Webui

Le build utilise Node `20.19.2-bookworm-slim` pour compiler Tailwind et `uv`
`0.7.13-python3.12-bookworm-slim` pour installer les dependances Python
verrouillees. L'image finale est `python:3.12.11-slim-bookworm` et inclut Docker
CLI `28.3.3` et le plugin Compose `2.38.2`, car le webui execute des operations
KSF. Ces tags et paquets sont explicitement epingles dans le `Dockerfile`; aucun
stage n'utilise `latest`.

Pour les mettre a jour, verifier les notes de version et compatibilites Docker,
modifier les versions ensemble, executer `make lock-check` et `make build`, puis
documenter la revue dans le changelog lorsque le changement est notable.

Le conteneur ne choisit pas un utilisateur statique : Compose fournit l'UID/GID
hote. Les donnees SQLite, la configuration et les secrets restent dans le
runtime KSF et jamais dans l'image.

Le socket Docker et le montage runtime inscriptible forment une frontiere
d'administration de l'hote. Ils sont reserves au webui protege par Traefik et
OAuth2 Proxy. Si un port direct est configure, Compose le lie exclusivement a
`127.0.0.1`; localhost est reserve a un administrateur deja connecte au serveur.
