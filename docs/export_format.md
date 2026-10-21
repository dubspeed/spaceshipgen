# Exportformat: Schiffe und Asteroiden

Diese Beschreibung richtet sich an alle, die einen Importer für die ShipGen-Exporte schreiben
(Godot oder eine andere Engine). Sie beschreibt Stand **Extension 0.3.0** (Baukasten-Builder
`kit`, Standard für alle Presets). Alles hier ist aus echten Exporten nachgeprüft.

Pro Objekt entstehen zwei Dateien mit gleichem Namen:

| Datei | Inhalt |
|---|---|
| `<name>.glb` | glTF 2.0 (binär): Meshes, Materialien, Knoten-Hierarchie, Werte in den Extras |
| `<name>.json` | Parameter und Werte als reines JSON (unabhängig davon, ob die Engine glTF-Extras liest) |

Die Kommandozeile benennt Schiffe `<preset>_<seed>` (z. B. `miner_s_101`), Asteroiden
`<preset>_<seed>` (z. B. `ore_s_11`); der Export-Knopf im Blender-Panel schreibt
`<klasse>_<seed>` bzw. `asteroid_<stoff>_<seed>`.

---

## 1. Allgemeines (gilt für beide)

### Koordinaten und Einheiten

- **Achsen wie Godot:** +Y oben, −Z vorne, +X rechts (rechtshändig). Beim Schiff zeigt der
  Bug nach −Z, die Triebwerke nach +Z.
- **Einheiten:** Meter, Tonnen (t), Kilonewton (kN), m/s², Grad/s², m³. Die Werte sind
  „physikalisch angehaucht“; das Spiel balanciert mit eigenen Faktoren.
- **Transformationen:** nur `translation` und `rotation` (Quaternion `[x, y, z, w]`), nie
  `scale`. Fehlende Felder bedeuten die Identität (glTF lässt sie weg).
- Der Wurzelknoten (`Ship` bzw. `Asteroid`) liegt im Ursprung ohne Transformation.

### Meshes und Materialien

- Low Poly, flach schattiert: Vertex-Attribute nur `POSITION` und `NORMAL` (keine UVs, keine
  Vertex-Farben, keine Tangenten).
- Ein Mesh hat **ein Primitive pro verwendetem Material**.
- Jedes sichtbare Teil ist geschlossen (manifold); ein Teil kann aus mehreren
  überlappenden geschlossenen Körpern bestehen (z. B. Tank = zwei Kugeln + Halterung).
- Materialien sind reine PBR-Faktoren (`baseColorFactor`, `metallicFactor`,
  `roughnessFactor`), alle `doubleSided: true`, keine Texturen. Glühen über `emissiveFactor`
  + `KHR_materials_emissive_strength`.
- **Materialien über den Namen zuordnen, nicht über den Index** – die Reihenfolge im
  `materials`-Array ändert sich von Datei zu Datei. Alle Namen beginnen mit `ShipGen_`.

### Collision-Shapes

- Jeder Knoten, dessen Name auf **`-convcolonly`** endet, ist eine **unsichtbare, konvexe
  Collision-Shape**: Das Mesh ist eine konvexe Hülle (aus den Eckpunkten bauen, z. B.
  `ConvexPolygonShape3D`), kein Material, nicht rendern.
- Godot erkennt den Suffix beim Import selbst und legt dafür einen `StaticBody3D` mit
  `CollisionShape3D` an. Für bewegte Körper die Shapes unter den eigenen
  `RigidBody3D`/`CharacterBody3D` hängen (Import-Skript oder von Hand).
- Collider tragen zusätzlich `extras.shipgen_role = "collision"`.

### Extras (Metadaten)

Der Exporter schreibt Blender-Custom-Properties als glTF-`extras` an die Knoten. Ob eine
Engine sie als Node-Metadaten übernimmt, hängt von Engine/Version ab; die `.json`-Datei
enthält die Gesamtwerte in jedem Fall.

---

## 2. Schiffe

### Knoten-Hierarchie

```
Ship                                  extras.shipgen (Typ, verbaute Designs, alle Werte)
├── Ship_Hull                         Rumpf, keine Transformation
├── Ship_Greebles                     Deko-Kleinteile (optional), keine Transformation, kein Collider
├── Engine_0 … Engine_<n>             je Triebwerk (inkl. Pylon bei Außenbord-Triebwerken)
│   └── Engine_0_col-convcolonly
├── Rig_0                             Abbau-Rig (optional, max. eins)
│   └── Rig_0_col-convcolonly
├── Module_0 … Module_<n>             je Frachtmodul (optional)
│   └── Module_0_col-convcolonly
├── Wings_<i>                         Flügelpaar (optional), ein Knoten für beide Seiten
│   └── Wings_<i>_col-convcolonly
├── Fin_<i>                           Seitenleitwerk (optional)
│   └── Fin_<i>_col-convcolonly
├── Socket_<kind>_<i> …               Montagepunkte (leere Knoten)
└── Col_<i>-convcolonly …             Collider für Rumpf, Rumpf-Anbauten und Pylone
```

Alle Teile hängen direkt unter `Ship`; Collider eines Teils hängen unter dem Teil mit
Identitäts-Transformation (gleicher lokaler Raum wie das Teil-Mesh). Was ein Schiff nicht
hat, fehlt einfach (z. B. kein `Rig_0` ohne Abbau-Rig, keine `Wings_*` bei Frachtern).

### Teil-Knoten

| Knoten | `kind` | Ursprung / Ausrichtung | Hinweise |
|---|---|---|---|
| `Engine_<n>` | `engine` | auf seinem Sockel, −Z = Schubrichtung (nach hinten) | Nummerierung in Platzierungsreihenfolge |
| `Rig_0` | `rig` | auf dem Bug-Sockel, −Z = nach vorn | Drehachse eines Bohrers = lokale Z-Achse |
| `Module_<n>` | `module` | auf seinem Sockel, −Z = vom Rumpf weg | gespiegelte Paare sind aufeinanderfolgend (`0/1`, `2/3`, …), vorne nach hinten, erst Seiten, dann Dach |
| `Wings_<i>` | `wing` | Mitte zwischen den beiden Flügelsockeln, **ohne Rotation** | ein geschlossenes Mesh durch den Rumpf; `socket` ist eine Liste `[rechts, links]` |
| `Fin_<i>` | `fin` | auf seinem Sockel, −Z = nach oben | `i` teilt sich den Zähler mit `Wings_<i>` (z. B. `Wings_0` + `Fin_1`) |

**Knoten-Namen sind zur Orientierung; für Logik `extras.shipgen_part` verwenden.**

Jeder Teil-Knoten trägt:

```json
"extras": {
  "shipgen_role": "mining",
  "shipgen_part": {
    "role": "mining",              // hull | engines | mining | cargo | wings | greebles
    "kind": "rig",                 // engine | rig | module | wing | fin
    "design": "drill_triple",      // siehe Design-Listen unten
    "socket": "Socket_nose_14"     // Name des Sockel-Knotens (bei Wings_* eine Liste)
  }
}
```

`Ship_Hull` und `Ship_Greebles` haben nur `shipgen_role` (`hull` bzw. `greebles`).

### Sockel-Knoten (`Socket_<kind>_<i>`)

Leere Knoten an den Montagepunkten; ihre lokale −Z-Achse zeigt in Sockelrichtung (vom Rumpf
weg). Ein Teil-Knoten hat dieselbe Translation und Rotation wie sein Sockel (Ausnahme
`Wings_*`). `<i>` ist ein schiffsweiter Zähler, keine Zählung pro Art.

```json
"extras": { "shipgen_socket": { "kind": "nose", "radius": 1.6718 } }
```

| `kind` | Lage | trägt | −Z zeigt |
|---|---|---|---|
| `engine` | Heck | Triebwerk | nach hinten (+Z) |
| `nose` | Bug-Stirnfläche | Abbau-Rig | nach vorn (−Z) |
| `side` | Rumpfflanke | Frachtmodul | nach außen (±X) |
| `top` | Dach | Frachtmodul | nach oben (+Y) |
| `wing` | Flanke | Flügel (je Seite einer, Suffix `_r`/`_l`) | nach außen |
| `fin` | Rücken | Seitenleitwerk | nach oben |

`radius` = freier Radius um den Montagepunkt (quer zur Sockelrichtung) in Metern. Nicht jeder
Sockel ist belegt; freie Sockel kann das Spiel z. B. für Nachrüstungen nutzen.

### Materialien (Schiff)

| Name | Verwendung |
|---|---|
| `ShipGen_Hull` | Rumpflack (Rumpf, Flügel) |
| `ShipGen_Accent` | Metallteile (Triebwerke, Rigs, Modul-Rahmen, Greebles) |
| `ShipGen_Cargo` | Container-/Tankflächen |
| `ShipGen_Glow` | Leuchtend: Düsen, Fenster der Brücke, Habitat-Fensterbänder. Die Glow-Fläche der Triebwerke ist die Austrittsfläche (für Flammen-Effekte) |

### Gesamtwerte: `Ship.extras.shipgen`

```json
{
  "seed": 101,
  "class": "miner",                       // fighter | interceptor | freighter | miner | corvette | shuttle
  "design": "mono/flare/stepped/blunt",   // Rumpf: Bauplan/Heck/Mitte/Bug
  "engine": "bell",                       // verbaute Designs ("none" = nicht verbaut)
  "rig": "drill_triple",
  "module": "ore_skip",
  "wings": "none",                        // Flügeltyp
  "stats": {
    "mass_t": 17.52,
    "thrust_kn": 236.37,
    "acceleration_ms2": 13.49,
    "turn_rate_deg_s2": 33.61,
    "hull_hp": 2101,
    "length_m": 13.8,
    "cargo": { "general_m3": 0.0, "ore_m3": 34.15, "fluid_m3": 0.0, "passengers": 0 },
    "mining": { "type": "drill", "power": 30.86, "range_m": 2.55 }
  }
}
```

`stats.mining` hat je nach `type` zusätzliche Felder: `laser` → `range_m` ist die
Strahlreichweite; `claw` → `grab_size_m` (größter greifbarer Brocken); `scoop` →
`intake_m2` (Einlassfläche). Ohne Rig: `{"type": "none", "power": 0.0, "range_m": 0.0}`.
Abbauleistung ist kalibriert: mittleres Rig ≈ 100.

### Design-Namen

| Liste | Werte |
|---|---|
| Triebwerke | `hex_nacelle`, `bell`, `ring_drive`, `block`, `twin_bell`, `finned`, `cluster`, `long_pod`, `ion_cone`, `heavy_stack` |
| Rigs (Art) | Bohrer `drill_cone`, `drill_triple`, `grinder_drum` · Laser `laser_single`, `laser_twin`, `laser_array` · Klauen `claw_twin`, `claw_quad` · Schaufel `scoop_funnel`, `scoop_ring` |
| Module (Fracht) | Container `crate`, `ribbed_container`, `double_container` · Erz `ore_hopper`, `ore_skip` · Tanks `tank_cylinder`, `tank_twin`, `tank_spheres` · Passagiere `habitat_drum`, `habitat_block` |
| Flügel | `delta`, `swept`, `straight`, `forward_swept` |

Fracht-Kategorien: Container → `general_m3`, Erz-Module → `ore_m3`, Tanks → `fluid_m3`,
Habitat → `passengers`.

### `<name>.json` (Schiff)

```json
{
  "model": "miner_s",        // Preset-Name (Shop-Modell)
  "model_params": { … },     // Parameter des Modells
  "params": { … },           // tatsächlich gebaute Parameter (inkl. Fertigungsstreuung des Seeds)
  "stats": {
    "gameplay": { … },       // wie extras.shipgen.stats
    "top_view": { "fill": …, "aspect": … },
    "tris": 1234, "max_tris": 20000,
    "bbox_min": [x, y, z], "bbox_max": [x, y, z], "dimensions": [x, y, z],
    "parts": ["Ship_Hull", "Engine_0", …]
  }
}
```

`bbox_*` und `dimensions` sind in **Blender-Achsen** (Z oben, Y vorn), nicht in glTF-Achsen.
Der Export-Knopf im Blender-Panel schreibt nur die Parameter (`params`) in die `.json`; die
Werte stehen dann nur in den glTF-Extras.

---

## 3. Asteroiden

Ein Asteroid ist **vorgebrochen**: Er besteht aus Brocken (Ebene 1), jeder größere Brocken
enthält seine Unterbrocken (Ebene 2, 3, …) bis zu einer Mindestgröße. **Alle Ebenen stecken
in derselben `.glb`, an ihrem Platz übereinander.**

### Knoten-Hierarchie

```
Asteroid                              extras.shipgen_asteroid (Gesamtwerte)
├── Chunk_0                           Ebene 1 (sichtbar)        extras.asteroid_chunk
│   ├── Chunk_0_col-convcolonly
│   ├── Chunk_0_0                     Ebene 2 (beim Laden ausblenden)
│   │   ├── Chunk_0_0_col-convcolonly
│   │   └── Chunk_0_0_0 …             Ebene 3 …
│   └── Chunk_0_1 …
├── Chunk_1 …
```

- Der Name kodiert den Pfad: `Chunk_2_1_3` = Kind 3 von Kind 1 von Brocken 2.
- **Ursprung jedes Brockens = sein Schwerpunkt.** Die Translation ist relativ zum
  Elternknoten (Ebene 1: relativ zu `Asteroid`, Ebene 2: relativ zum Eltern-Brocken). Keine
  Rotation.
- Jeder Brocken hat genau ein Collider-Kind `<Name>_col-convcolonly` (konvexe Hülle des
  Brocken-Meshes, Identitäts-Transformation). Das sichtbare Mesh ist nicht konvex (raue
  Oberfläche), liegt aber vollständig im Collider.

### Laden und Zerbrechen

1. Beim Laden alle Brocken mit `level > 1` ausblenden **und ihre Collider deaktivieren**
   (der glTF kennt keine Sichtbarkeit – sonst liegen alle Ebenen übereinander).
2. Ein Brocken zerbricht: ihn ausblenden und seinen Collider deaktivieren, seine direkten
   Kinder (`extras.asteroid_chunk.level == level + 1`) einblenden und als eigene Körper
   lösen. Die Kinder füllen den Elternbrocken lückenlos (Risse ausgenommen); ihre Oberfläche
   passt zur Oberfläche des Elternbrockens.
3. `children == 0` = kleinster Brocken, zerbricht nicht weiter.

### Brocken-Extras: `Chunk_*.extras.asteroid_chunk`

```json
{
  "level": 1,              // 1 = ganz außen
  "resource": "ore",       // ore | metal | ice, oder "rock" für tauben Brocken
  "volume_m3": 84.96,
  "mass_t": 229.4,
  "yield_m3": 42.48,       // abbaubarer Ertrag dieses Brockens
  "cargo": "ore_m3",       // Fracht-Kategorie wie beim Schiff (ore_m3 | fluid_m3)
  "hardness": 1.0,         // Abbauzeit-Faktor (Erz = 1)
  "size_m": 8.55,          // größte Ausdehnung
  "children": 4            // Zahl der Unterbrocken
}
```

Die Werte eines Brockens umfassen ihn ganz; die Summe seiner Kinder ist ungefähr gleich
(kleine Abweichungen durch Risse und Oberfläche). Vorschlag fürs Spiel:
Abbauzeit ≈ `hardness × yield_m3 ÷ mining.power`; eine Klaue greift Brocken bis
`grab_size_m`.

| Stoff | Dichte t/m³ | `hardness` | Ertrag reicher Brocken | `cargo` |
|---|---|---|---|---|
| `ore` | 2,7 | 1,0 | 50 % des Volumens | `ore_m3` |
| `metal` | 5,0 | 1,8 | 70 % | `ore_m3` |
| `ice` | 0,92 | 0,5 | 90 % | `fluid_m3` |

Taube Brocken (`resource: "rock"`) liefern 5 %.

### Gesamtwerte: `Asteroid.extras.shipgen_asteroid`

```json
{
  "seed": 11,
  "composition": "ore",               // ore | metal | ice
  "shape": "round",                   // round | elongated | binary
  "stats": {
    "composition": "ore",
    "size_m": 10.0,                   // größte Ausdehnung des ganzen Asteroiden
    "volume_m3": 221.0,               // Summen über Ebene 1
    "mass_t": 596.7,
    "yield_m3": 110.5,
    "cargo": "ore_m3",
    "hardness": 1.0,
    "chunks_per_level": { "1": 4, "2": 4 },
    "smallest_chunk_m": 4.68,
    "largest_chunk_m": 8.55
  }
}
```

### Materialien (Asteroid)

`ShipGen_Asteroid_<stoff>_<rolle>` mit `<stoff>` = `ore` | `metal` | `ice`:

| Rolle | Verwendung |
|---|---|
| `surface` | Außenfläche |
| `plain` | Bruchflächen tauber Brocken |
| `resource` | Bruchflächen und Adern erzhaltiger Brocken (zeigt den Rohstoff) |

Es stehen nur die Materialien in der Datei, die vorkommen (z. B. fehlt `plain`, wenn alle
Brocken erzhaltig sind).

### `<name>.json` (Asteroid)

Kommandozeile: `{"model", "model_params", "params", "stats"}`; Panel-Export:
`{"params", "stats"}`. `stats` wie `extras.shipgen_asteroid.stats`.

---

## 4. Checkliste für einen Importer

- [ ] Achsen übernehmen (glTF = Godot), keine Umrechnung nötig.
- [ ] Knoten mit Suffix `-convcolonly` als konvexe Collision-Shapes behandeln, nicht rendern.
- [ ] Materialien über den Namen (`ShipGen_*`) zuordnen, nicht über den Index.
- [ ] Schiff: Teile über `extras.shipgen_part` finden (Rolle, Art, Design, Sockel);
      Gesamtwerte aus `Ship.extras.shipgen` oder der `.json`.
- [ ] Schiff: Teile drehen/animieren um ihren eigenen Ursprung (= Sockel); Effekte an
      Sockel-Knoten oder Glow-Flächen hängen.
- [ ] Asteroid: Ebenen > 1 beim Laden ausblenden und Collider deaktivieren; beim Zerbrechen
      Elternteil aus, Kinder an.
- [ ] Optionale Knoten (Rig, Module, Flügel, Greebles) dürfen fehlen.

Das Format hat derzeit kein eigenes Versionsfeld; maßgeblich ist die Version der Extension
(`shipgen/blender_manifest.toml`). Ältere Exporte (bis 0.2.0) hatten statt einzelner Teile
ein Mesh pro Rolle (`Ship_Engines`, `Ship_Mining`, `Ship_Cargo`, `Ship_Wings`).
