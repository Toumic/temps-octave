# Temps-Octave — le cercle des quintes sur 120 octaves

*English summary below.*

Empilez des quintes pures (rapport 3/2) et des quintes tempérées (2^(7/12)) à partir du même La4 = 440 Hz : où les deux calibrages se rencontrent-ils, et de combien s'écartent-ils ? Ce programme Python compare les deux parcours sur **120 octaves** et en tire des résultats vérifiables.

## Ce que le programme calcule

- **412 points** : 206 quintes pures et 206 quintes tempérées, toutes numérotées depuis le même départ (La4) ;
- **206 rangs communs** : l'écart en cents entre la quinte pure et la quinte tempérée de même rang, du minimum non nul au maximum (jusqu'à environ 401 cents) ;
- **540 rapports entiers exacts** entre fréquences, dont **17 entre quinte pure et quinte tempérée** (les équivalences d'octave) et **523 à l'intérieur d'un même parcours** ;
- **42 436 comparaisons pur contre tempéré** (84 666 au total avec les comparaisons internes) ;
- une analyse **sans la tonique pure** (La4) : `without_pure_tonic`, 84 255 comparaisons, plus aucun unisson ni équivalence d'octave.

## Contenu du dépôt

| Fichier | Rôle |
|---|---|
| `main.py` | Le programme : calculs et fenêtre graphique (Tkinter, bibliothèque standard uniquement) |
| `test_main.py` | 32 tests qui vérifient les calculs |
| `article_cercle_des_quintes.pdf` | L'article : démarche et résultats |
| `Référence LA4.txt` | Sortie de référence du programme (84 666 comparaisons, 206 quintes de même rang) |
| `DOCUMENTATION.md` | Description détaillée de la fenêtre, des vues et des conventions de notation |
| `NOTES-MISE-A-JOUR.md` | Ce qui a changé entre la version 1 et la version 2 |
| `LICENSE` | Licence MIT |

## Lancer le programme

Il faut Python 3 avec Tkinter (inclus dans l'installation standard de Python.org, case « tcl/tk and IDLE »). Aucune bibliothèque à installer.

```powershell
python main.py
```

## Vérifier les calculs

```powershell
python -m unittest
```

Résultat attendu : `Ran 32 tests … OK`. Validé par l'auteur le 5 novembre 2026.

## Versions

- **Version 1** : le programme d'origine.
- **Version 2** : calculs alignés sur l'application web (équivalences d'octave comptées comme rapports entiers, comparaisons pur contre tempéré, analyse sans tonique pure), 32 tests réussis.

## Application web

Une version interactive existe : cercle des quintes avec écoute, carte des octaves, sphère 3D, liste des rencontres et rapport détaillé. Elle donne les mêmes chiffres que ce programme.

https://www.cabviva.com/temps-octave

## Licence

MIT — voir `LICENSE`. © 2026 Cabviva.

---

## English summary

Stack pure fifths (3/2) and equal-tempered fifths (2^(7/12)) from the same A4 = 440 Hz, and find where the two tunings meet and how far they drift apart. This standalone Python program (standard library only, Tkinter) compares both paths over **120 octaves**: 412 points, 206 matching ranks, 540 exact integer ratios (17 between pure and tempered, 523 within the same path) and 42,436 pure-versus-tempered comparisons.

Run it with `python main.py`, check the results with `python -m unittest` (32 tests). Licensed under MIT. Interactive web version: https://www.cabviva.com/temps-octave
