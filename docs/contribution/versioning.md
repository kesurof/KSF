# Versionnement

KSF utilise le versionnement semantique : `MAJEUR.MINEUR.CORRECTIF`.

- MAJEUR : changement incompatible de CLI, runtime, configuration ou template.
- MINEUR : fonctionnalite compatible.
- CORRECTIF : correction compatible, documentation ou securite sans rupture.

Avant une version, verifier le diff, les validations adaptees, la documentation
et les notes de version. Mettre a jour `VERSION` et `CHANGELOG.md` dans le meme
changement. Les fichiers runtime et secrets ne font jamais partie d'une version.
