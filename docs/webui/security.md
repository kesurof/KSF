# Securite Webui

OAuth2 Proxy protege le webui. Les en-tetes d'identite ne sont dignes de
confiance que derriere le proxy KSF. Toute mutation valide ses entrees, verifie
l'origine et le referent contre le `Host` exact, et exige une confirmation cote
serveur pour les actions sensibles ou destructives. Une mutation sans `Origin`
ni `Referer` valide est refusee. En production (`KSF_ENV=production`, valeur par
defaut), OpenAPI, Swagger et ReDoc sont desactives.

Un port direct eventuel du webui doit rester publie uniquement sur
`127.0.0.1`. Cette interface locale est une frontiere de confiance acceptee
pour l'administrateur deja connecte au serveur, pas un mecanisme
d'authentification : elle ne doit pas etre exposee par une adresse publique,
un tunnel non maitrise ou un proxy qui elargit cette ecoute. L'acces distant
normal passe par Traefik et OAuth2 Proxy. Une publication locale ne remplace ni
la gestion des comptes du serveur ni OAuth2 Proxy pour l'acces via le domaine.

Le montage `${BASE_DIR}` inscriptible et `/var/run/docker.sock` donnent au webui
des privileges d'administration. Ils sont necessaires aux operations actuelles,
mais constituent une frontiere de confiance : ne pas exposer le webui hors
Traefik et conserver l'ownership hote des fichiers crees.

Le socket Docker est un acces administrateur a l'hote. Le montage reste en
ecriture car les operations KSF doivent creer et gerer des conteneurs ; il ne
doit jamais etre ajoute a une application non administrative. Le webui refuse
de se reconstruire lui-meme : lancer `app.sh rebuild webui` depuis le serveur
conserve l'UID/GID hote et evite un conteneur helper privilegie.

Les sorties de jobs sont redactees avant leur persistence SQLite et leur retour
au navigateur. Cette redaction reduit le risque de fuite accidentelle, mais ne
remplace pas l'interdiction de transmettre un secret dans un argument, une URL
ou un log applicatif non reconnu par le redacteur.
