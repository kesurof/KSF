# Revue UI Webui

- Verifier les largeurs 390 px et 1440 px pour les parcours modifies.
- Les cibles tactiles et le focus clavier restent utilisables.
- Les textes longs, donnees vides, erreurs, chargements et succes sont lisibles.
- Les formulaires conservent les valeurs et affichent les erreurs utiles.
- Les actions destructives demandent une confirmation explicite.
- Le contraste, les libelles et le mode sombre restent coherents.
- HTMX conserve l'etat serveur ; Alpine ne conserve que l'etat local.
- Les swaps HTMX preservent ou annoncent le focus lorsque necessaire.
- Les animations respectent `prefers-reduced-motion`.
- Les modales restaurent le focus et retiennent Tabulation entre leurs controles.
- Les composants partages d'onglets, menus et combobox sont testables au clavier.
- Le CSS est compile depuis `input.css`; aucun import ou fichier de
  compatibilite obsolete ne reste reference.
