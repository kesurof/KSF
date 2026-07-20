# Changelog

Toutes les evolutions notables de KSF sont documentees dans ce fichier.

## [0.2.0] - 2026-07-20

### Added

- Documentation complete du parcours d'acces applicatif par menu et CLI.
- Documentation du modele de confiance localhost du Web UI, des migrations
  SQLite, des sauvegardes et de la restauration.
- Evidence de release : controles executes, controles non executes et risques
  residuels du jalon de migration.

### Changed

- Synchronisation des instructions agents et skills avec `make validate`,
  `make check-release` et les controles opt-in reels.
- Le jalon de migration est versionne en `0.2.0` selon SemVer pre-1.0.

### Migration

- Le port interne `APP_PORT` et le port hote optionnel `APP_HOST_PORT` sont
  distincts. Les instances existantes qui utilisaient `APP_PORT` comme port
  publie doivent etre reconfigurees explicitement avec `app.sh configure
  <instance> --host-port <port>` si un acces local est voulu.
- Les applications exposees par Traefik ne publient plus automatiquement de
  port hote; les acces directs restent limites a `127.0.0.1`.

## [0.1.0] - 2026-07-20

### Added

- Base de documentation, workflow et outillage de contribution KSF.
