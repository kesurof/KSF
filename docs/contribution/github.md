# GitHub Et CI

Les modeles de workflows se trouvent dans `docs/templates/github/workflows/`.
Ils sont volontairement inactifs tant que les controles ne sont pas actives dans
le depot GitHub.

Avant activation, epingler les actions a des SHA valides, conserver des
permissions minimales et n'executer que les controles reproductibles : syntaxe
Bash, rendu Compose, tests webui avec `uv`, audit de dependances et analyse de
secrets. La publication d'image reste hors perimetre : le webui est construit
par instance et embarque une copie versionnee du runtime KSF.
