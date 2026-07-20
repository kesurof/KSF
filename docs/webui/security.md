# Securite Webui

OAuth2 Proxy protege le webui. Les en-tetes d'identite ne sont dignes de
confiance que derriere le proxy KSF. Toute mutation valide ses entrees, verifie
l'origine lorsque necessaire et exige une confirmation pour les actions
destructives.

Le montage `${BASE_DIR}` inscriptible et `/var/run/docker.sock` donnent au webui
des privileges d'administration. Ils sont necessaires aux operations actuelles,
mais constituent une frontiere de confiance : ne pas exposer le webui hors
Traefik et conserver l'ownership hote des fichiers crees.
