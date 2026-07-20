# Versionnement

KSF utilise le versionnement semantique : `MAJEUR.MINEUR.CORRECTIF`.

- MAJEUR : changement incompatible de CLI, runtime, configuration ou template.
- MINEUR : fonctionnalite compatible.
- CORRECTIF : correction compatible, documentation ou securite sans rupture.

Avant `1.0.0`, une migration incompatible est publiee dans un nouveau jalon
mineur `0.y.0`; elle doit decrire les incompatibilites et la procedure manuelle
attendue dans `CHANGELOG.md`. Le jalon `0.2.0` porte la migration du modele
app/port/Web UI et de son outillage de validation.

Avant une version, verifier le diff, les validations adaptees, la documentation
et les notes de version. Mettre a jour `VERSION` et `CHANGELOG.md` dans le meme
changement. Les fichiers runtime et secrets ne font jamais partie d'une version.
Executer `make check-release` apres cette mise a jour : il valide le format
SemVer de `VERSION` et la presence de son titre dans le changelog.
