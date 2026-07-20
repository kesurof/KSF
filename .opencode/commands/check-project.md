---
description: Verifie la qualite, la coherence et les controles adaptes avant livraison.
agent: review
---

Charge les skills `ksf-testing` et `ksf-coherence`. Inspecte le diff et les
fichiers non suivis, execute les controles reellement disponibles et proportionnes
au risque, puis produis une revue independante. Pour une version, execute `make
check-release` si possible. Ne pretends jamais avoir execute un controle non
lance; consigne les `SKIP`, controles opt-in non executes et risques residuels
dans la checklist de release.
