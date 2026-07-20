# Workflow De Contribution

1. Inspecter les scripts, templates et documentation concernes.
2. Definir le perimetre, les criteres d'acceptation et les risques.
3. Pour un changement significatif, lancer `/preflight` et resoudre les points
   bloquants avant implementation.
4. Implementer un lot petit et testable dans la couche proprietaire.
5. Executer les validations proportionnees au risque.
6. Mettre a jour les tests, `README.md`, `AGENTS.md`, skills et documents
   concernes.
7. Executer `/check-project` pour les changements significatifs.

Un correctif de bug ajoute une preuve de non-regression lorsque cela est
praticable. Les changements Bash, Compose, routes, donnees persistantes et
securite exigent une attention particuliere au dry-run et au runtime KSF.
