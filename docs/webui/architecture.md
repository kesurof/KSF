# Architecture Webui

Le webui est une application FastAPI rendue cote serveur avec Jinja2, HTMX et
Alpine.js. Il est installe comme application KSF et lit le runtime partage pour
administrer la plateforme.

- FastAPI expose les pages et API.
- Jinja2 rend les pages et fragments serveur.
- HTMX met a jour les fragments representant l'etat serveur.
- Alpine.js gere les menus, modales et interactions locales.
- `aiosqlite` conserve les jobs sous `${BASE_DIR}/data/webui/jobs.db` ; voir
  `database.md` pour les contraintes d'evolution.
- Docker SDK et le CLI KSF embarque executent les operations d'administration.

Le conteneur tourne avec l'UID/GID hote et le groupe Docker afin que les fichiers
et operations restent compatibles avec le CLI Bash.
