# Rumpfdetails

Vorher/nachher je Modell (Zeilen = Seeds 1–3, links `kit.detail = 0`, rechts `1`), erzeugt mit
`scripts/hull_detail_demo.py`. Code: `shipgen/kit/hull_detail.py`.

| Detail | Klassen | Wie |
|---|---|---|
| Rillen | alle | zusätzliche, auf 90 % eingezogene Querschnitte im Loft der Mittelsektion |
| Seitenpaneele | Frachter, Miner, Korvette | Flanken in kurze Felder geschnitten (max. 5 % der Länge bzw. 1,2 × Halbbreite), ein Teil eingerückt und angehoben – nur Seiten, nicht das Dach |
| Dachgraben | Frachter, Korvette | Boolean-Modifier (Solver `MANIFOLD`, auf Blender < 4.5 `EXACT`), nur auf Dachabschnitten ohne Module |

- Reine Optik: Rumpfwerte kommen vom Referenzrumpf.
- Greebles meiden Rillen und Graben. Die Collider sind der glatte Loft, im Mittelteil um die
  Paneelhöhe vergrößert.
- Jeder Rumpfkörper wird einzeln bearbeitet. Bei Twin-Rümpfen ist der zweite Körper der erste,
  gespiegelt, damit beide exakt symmetrisch sind.
- Knappe Dreiecksbudgets lassen Details weg (`MIN_TRIS`).
