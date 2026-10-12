# Asteroiden – Prototyp

Code: `shipgen/asteroids/` (Generator, Schema, konvexe Geometrie), Presets: `presets/asteroids/`,
Bilder: `scripts/asteroid_demo.py`.

```bash
.venv/bin/python cli.py --asteroid ore_m                 # output/ore_m_12{.glb,.blend,.png,.json}
.venv/bin/python cli.py --asteroid all --no-blend --views three_quarter
.venv/bin/python cli.py --asteroid ore_m --set size_m=40 --set richness=0.8
```

- `types.png`: Erz / Metall / Eis (Zeilen) × rund / länglich / Doppel (Spalten), je 24 m
- `levels.png`: ein 30-m-Erzasteroid, ganz und dann Ebene 1–3 auseinandergezogen
- `scale.png`: 24-m-Asteroid neben dem `miner_m` (26 m)
- `variants_*.png`: je 9 Seeds pro Stoff (14–40 m, alle Formen, 14–32 Facettenpunkte)
- `closeup.png`: Nahansicht der rauen Oberfläche (Erz, Metall, Eis, je 30 m)

## Aufbau

- **Form:** konvexe Hülle aus Zufallspunkten (wenige Punkte = große Facetten); „binary“ =
  zwei Hälften, an einer Ebene getrennt (Taille). Low Poly, flach schattiert.
- **Vorgebrochen:** Voronoi-Zerlegung in konvexe Brocken (`chunks`), große Brocken zerfallen
  weiter (`sub_chunks`), bis unter etwa 2 × `min_chunk_m` oder `max_levels`. Knappe
  `max_tris` nehmen Ebenen weg (mit Warnung).
- **Raue Oberfläche** (`surface.py`, `roughness`, `craters`): die Außenflächen jedes Brockens
  werden in kleinere Dreiecke geteilt und per Rauschen (zwei Oktaven + kleines Zittern) und
  Kratern verschoben. Das Rauschen hängt nur von der Weltposition ab: Nachbarn und
  Unterbrocken haben an derselben Stelle dieselbe Oberfläche. Bruchflächen bleiben glatt.
- **Collider:** jeder Brocken hat ein Kind `<Name>_col-convcolonly` = konvexe Hülle seiner
  Punkte (Godot: unsichtbare konvexe Collision-Shape), das sichtbare Mesh liegt komplett darin.
- **Lesbarkeit:** feine Risse zwischen den Brocken (`gap`). Erzhaltige Brocken haben
  Bruchflächen in Rohstoff-Farbe (sichtbar in den Rissen und beim Zerbrechen) und ein paar
  Adern an der Oberfläche; taube Brocken (`resource: rock`) sind innen grau.

## In Godot

```
Asteroid                      extras.shipgen_asteroid: Gesamtwerte
├── Chunk_0  (Ebene 1, sichtbar)   extras.asteroid_chunk: level, resource, volume_m3,
│   ├── Chunk_0_col-convcolonly      mass_t, yield_m3, cargo, hardness, size_m, children
│   ├── Chunk_0_0  (Ebene 2)
│   │   ├── Chunk_0_0_col-convcolonly
│   │   └── Chunk_0_0_0 …
│   └── Chunk_0_1 …
└── Chunk_1 …
```

Die `.glb` enthält alle Ebenen an ihrem Platz. Beim Laden Ebenen > 1 ausblenden (Collider
deaktivieren); zerbricht ein Brocken: ihn ausblenden, seine Kinder einblenden (und als eigene
Körper lösen). Jeder Brocken hat seinen Ursprung im eigenen Schwerpunkt.

## Werte (aus der Geometrie, wie bei den Schiffen)

| Stoff | Dichte t/m³ | Härte | Gehalt reicher Brocken | Fracht |
|---|---|---|---|---|
| Erz | 2,7 | 1,0 | 50 % | `ore_m3` (Hopper) |
| Metall | 5,0 | 1,8 | 70 % | `ore_m3` (Hopper) |
| Eis | 0,92 | 0,5 | 90 % | `fluid_m3` (Tanks) |

Taube Brocken liefern 5 %. Idee für das Spiel: Abbauzeit ≈ Härte × Ertrag ÷ Abbauleistung
(mittleres Rig = 100); Klauen greifen Brocken bis `grab_size_m`.

## Offen

- Panel in Blender (bisher nur Kommandozeile/Python).
- Gase (Gaswolken/Kometen) später.
- Unterbrocken weichen bei sehr kleinen Brocken bis ~8 % im Volumen vom Elternbrocken ab (die
  Verschiebung ist pro Brocken begrenzt, damit dünne Brocken nicht umklappen).

