# UI Et UX Webui

Le design system est defini dans `src/webui/static/input.css` avec Tailwind CSS.
La feuille `legacy.css` conserve temporairement les styles historiques ; les
nouveaux composants utilisent les tokens et utilitaires Tailwind puis les
anciens styles sont migres progressivement.

- Mobile-first, avec verification a 390 px puis 1440 px.
- Theme sombre, focus visible, contrastes et cibles tactiles de 44 px minimum.
- HTMX est proprietaire de l'etat serveur ; Alpine est limite a l'etat local.
- Chaque parcours dynamique prevoit chargement, vide, erreur, succes et donnees
  volumineuses.
- Les animations respectent `prefers-reduced-motion`.
