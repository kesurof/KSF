# Donnees Webui

Les jobs du webui sont conserves dans `${BASE_DIR}/data/webui/jobs.db` avec
`aiosqlite`. `KSF_WEBUI_DB_PATH` permet de remplacer ce chemin, notamment pour
les tests. La base doit rester dans un volume persistant hors de l'image.

Le repertoire de la base est cree en `700`; la base, ses fichiers WAL/SHM et
les sauvegardes sont en `600`. Ils appartiennent par defaut a l'UID/GID du
processus webui, qui est l'UID/GID hote. Les variables optionnelles
`KSF_WEBUI_DB_UID` et `KSF_WEBUI_DB_GID` permettent de verifier cette propriete
lors d'une execution administree.

Chaque ouverture de la base active `journal_mode=WAL`, un `busy_timeout` de cinq
secondes et les cles etrangeres, puis execute `PRAGMA integrity_check`. Une
verification en erreur empeche le traitement du job concerne : arreter le
webui et restaurer une copie valide avant de reprendre les operations.

Toute evolution de schema doit etre compatible avec les bases deja installees,
testee sur une base peuplee et accompagnee d'une procedure de sauvegarde avant
modification destructive. KSF n'adopte ni SQLAlchemy ni Alembic par defaut : une
migration vers ces outils requiert une decision d'architecture explicite.

Les versions appliquees sont stockees dans `schema_migrations`. Chaque migration
est executee dans une transaction `BEGIN IMMEDIATE`; les migrations destructives
creent auparavant une sauvegarde SQLite coherente dans le repertoire de la base,
sous le nom `jobs.db.v<version>.pre-migration-<timestamp>.bak`. La sauvegarde
est une copie SQLite coherente, pas une copie brute du fichier WAL. Pour
restaurer, arreter le webui, conserver la base defectueuse a des fins de
diagnostic, remplacer `jobs.db` par cette sauvegarde, supprimer les sidecars
`jobs.db-wal` et `jobs.db-shm` devenus incompatibles, puis retablir l'ownership
hote et le mode `600` avant le redemarrage.

Une contrainte SQLite interdit deux jobs `pending` ou `running` pour une meme
cible, y compris entre plusieurs processus webui. Les jobs termines ou echoues
sont conserves 30 jours par defaut; regler `KSF_WEBUI_JOB_RETENTION_DAYS` a `0`
pour les purger des la creation d'un nouveau job. La retention est appliquee
lors de la creation d'un job, pas par une tache planifiee.

La couverture Python verifie la base vide, une migration de base peuplee, la
sauvegarde pre-migration, l'echec transactionnel, le verrou SQLite, la retention
et la redaction. Les permissions et l'ownership doivent aussi etre verifies dans
un conteneur avec les UID/GID de l'hote avant une livraison qui modifie ce code.
