# Preflight KSF

- L'objectif, le perimetre et les criteres d'acceptation sont explicites.
- Le script ou template proprietaire du changement est identifie.
- Les frontieres `bootstrap`, `deploy`, `app` et `ksf` restent respectees.
- Les impacts runtime, donnees persistantes, routes, DNS et secrets sont connus.
- Les ecritures dry-run et les permissions sont definies.
- Les instances, ports internes et ports hote restent distincts.
- Le rendu et la validation Compose necessaires sont identifies.
- Les risques OAuth2 Proxy, Traefik, CrowdSec et socket Docker sont evalues.
- Pour le webui, les etats UI, mobile, accessibilite et ownership hote sont
  traites si concernes.
- Les tests et documents a mettre a jour sont listes.
