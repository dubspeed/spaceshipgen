# Rumpf-Details – Prototyp

Erzeugt mit `scripts/hull_detail_demo.py`; Code in `shipgen/kit/hull_detail.py`, aktiviert über
`kit.build(params, detail=(...))` (noch kein Parameter). Pro Bild: oben `plain`, `grooves`,
`panels_raised`; unten `panels_recessed`, `bool_cuts` (Graben, Kerben, Einlässe), `combined`.

| Technik | Wie | Kosten | Eindruck |
|---|---|---|---|
| `grooves` | Rillen ringsum: zusätzliche Querschnitte im Loft (eingezogen auf 90 %) | +80–240 Tris, kein Mesh-Eingriff | sauber, ruhig, gliedert lange Rümpfe |
| `panels_raised` / `_recessed` | Rumpf in Felder geschnitten (`bisect_plane`), ein Teil der Seiten-/Dachflächen eingerückt und gehoben/versenkt | +150–300 Tris | Panzerplatten-Look; erhaben und versenkt wirken fast gleich |
| `trench` (Bool) | Dachgraben über die Mitte | alle drei Schnitte zusammen +~120 Tris | stärkster Effekt, sehr „Sci-Fi“ |
| `notches`, `intakes` (Bool) | Kerben in den Bugschultern, Einlässe in den Heckflanken | gering | Kerben wirken teils wie Schaden |

Bool: Blender-Modifier ohne `bpy.ops`, Solver `MANIFOLD` (ab 4.5), sonst `EXACT`. Jeder
Rumpfkörper wird einzeln bearbeitet, bevor Kästen, Zinken und Brücke dazukommen (mit
überlappenden Schalen liefert der Solver das Mesh unverändert zurück).

Prüfung: alle 240 Rumpfkombinationen × 2 Detail-Sätze → geschlossene Meshes, keine
Null-Flächen, < 1 s pro Schiff. Werte unverändert (Rumpfwerte kommen vom Referenzrumpf).

## Offen, bevor es in den Standard-Builder kann

- Greebles wissen nichts von Graben/Vertiefungen und schweben dann darüber.
- Erhabene Paneele ragen etwas aus den Collision-Shapes (Test „jeder Vertex in einer Shape“).
- Auswahl per Klasse/Seed und ein Parameter (`hull.detail` 0–1?) fehlen noch.
- Classic-Builder bleibt außen vor.
