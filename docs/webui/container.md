# Conteneur Webui

Le build utilise Node pour compiler Tailwind et `uv` pour installer les
dependances Python verrouillees. L'image finale inclut le CLI Docker et Compose,
car le webui execute des operations KSF.

Le conteneur ne choisit pas un utilisateur statique : Compose fournit l'UID/GID
hote. Les donnees SQLite, la configuration et les secrets restent dans le
runtime KSF et jamais dans l'image.
