# UI Et UX Webui

Le design system est defini dans `src/webui/static/input.css` avec Tailwind CSS.
Les composants specifiques et les tokens de compatibilite y sont regroupes ;
`app.css` est le fichier compile servi au navigateur.

Inventaire des composants partages par ecran :

- Base et navigation : `layout`, `sidebar`, `topbar`, `nav-*`, `breadcrumb`,
  `modal*`, `toast*`.
- Tableau de bord : `metric-*`, `record-*`, `chip`, `empty-state`.
- Applications et infrastructure : `app-card`, `service-row`, `record-*`,
  `form-*`.
- General, securite et maintenance : `card`, `tabs`, `dropdown*`, `spinner`,
  `skeleton`, `error-box`, `success-box`.
- Les styles utilisent les tokens Tailwind dans `input.css`; la conservation des
  selecteurs critiques et l'absence de feuilles de compatibilite sont couvertes
  par test statique.

- Mobile-first, avec verification a 390 px puis 1440 px.
- Theme sombre, focus visible, contrastes et cibles tactiles de 44 px minimum.
- HTMX est proprietaire de l'etat serveur ; Alpine est limite a l'etat local.
- Chaque parcours dynamique prevoit chargement, vide, erreur, succes et donnees
  volumineuses.
- Les animations respectent `prefers-reduced-motion`.
- Les modales restaurent le focus et bloquent Tabulation dans leur contenu.
- Les composants partages d'onglets, menus et combobox sont utilisables au clavier.
