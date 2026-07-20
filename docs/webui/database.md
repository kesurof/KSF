# Donnees Webui

Les jobs du webui sont conserves dans `${BASE_DIR}/data/webui/jobs.db` avec
`aiosqlite`. Le fichier persiste hors de l'image et doit rester accessible a
l'UID/GID hote avec une permission restrictive.

Toute evolution de schema doit etre compatible avec les bases deja installees,
testee sur une base peuplee et accompagnee d'une procedure de sauvegarde avant
modification destructive. KSF n'adopte ni SQLAlchemy ni Alembic par defaut : une
migration vers ces outils requiert une decision d'architecture explicite.
