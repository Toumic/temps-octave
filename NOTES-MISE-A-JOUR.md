# Temps-Octave — notes de mise à jour (5 novembre 2026)

Cette archive est le dossier « temps-octave » complet, mis à jour.

## Ce qui n'a pas changé
- L'article PDF.
- Les résultats de référence : 412 points, 84 666 comparaisons, 1 unisson, 206 quintes de même rang.
- L'interface Tk du programme et tous les anciens tests.
- `Référence LA4.txt` est jointe (sortie métrique du programme, 84 666 comparaisons). L'application web a été vérifiée contre elle.

## Ce qui a changé dans main.py (calculs seulement)
1. **Équivalences d'octave = rapports entiers.** Les 17 équivalences d'octave entre quinte pure et quinte tempérée sont maintenant toutes comptées comme rapports entiers (puissances de 2). Avant, 14 d'entre elles échappaient au comptage parce que leur rapport dépasse la précision des nombres décimaux.
   - Rapports entiers au total : 526 -> 540.
   - Dont entre calibrages : 3 -> 17.
   - Dont à l'intérieur d'un même parcours : 523 (inchangé).
2. **Nouveaux champs de CycleAnalysis** : `internal_integer_multiples` (rapports entiers internes à un parcours) et `cross_comparisons` (comparaisons pur contre tempéré : 42 436).
3. **Nouvelle fonction `without_pure_tonic(analysis)`** : l'analyse sans la tonique pure (La4 pur, quinte 0). Résultat : 84 255 comparaisons, 42 230 pur contre tempéré, aucun unisson, 205 quintes de même rang, aucune équivalence d'octave, 523 rapports entiers. L'écart minimal et l'écart maximal ne sont pas recalculés.
4. **Nouvelles fonctions** `pair_integer_multiple` et `format_multiple` : le rapport entier d'une paire (y compris 2^n très grand) et son écriture (2^n au-delà de 2^40).
5. Le rapport textuel des rapports entiers écrit ces grandes puissances de 2 sous la forme 2^n.

## Nouveaux tests (test_main.py, classe NovemberUpdateTests)
Comptes de référence inchangés, 540 / 17 / 523, 42 436 comparaisons pur contre tempéré, écriture 2^n, analyse sans tonique pure.

## À faire de votre côté
Ces modifications ont été écrites sans pouvoir exécuter Python. Lancez une fois `python -m unittest` : les chiffres attendus sont ceux de l'application web (calculés avec le même algorithme). Si un test échoue, dites-moi lequel et je corrige.

## Ce que l'application web fait en plus (hors programme)
- Cercle des quintes animé et sonore (pure, tempérée ou les deux ; registres ; volume et muet).
- Vue « Octaves » : deux rails sur 120 octaves, rencontres filtrables, courbe de l'écart par rang, quasi-rencontres (tolérance en cents, « à l'octave près »), zoom.
- Sphère (globe déroulé) avec feuilles et surface continue ; liste des rencontres ; tableau des 206 rangs.
- Interrupteur des comparaisons internes ; option de retirer la tonique pure.
- Manuel, logique, README en volet, textes FR/EN.
