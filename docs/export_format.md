# Exportformat: Schiffe, Asteroiden, Wracks und Stationen

Diese Beschreibung richtet sich an alle, die einen Importer für die ShipGen-Exporte schreiben
(Godot oder eine andere Engine). Sie beschreibt Stand **Extension 0.5.0** (Baukasten-Builder
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

## 1. Allgemeines (gilt für alle)

### Koordinaten und Einheiten

- **Achsen wie Godot:** +Y oben, −Z vorne, +X rechts (rechtshändig). Beim Schiff zeigt der
  Bug nach −Z, die Triebwerke nach +Z.
- **Einheiten:** Meter, Tonnen (t), Kilonewton (kN), m/s², Grad/s², m³. Die Werte sind
  „physikalisch angehaucht“; das Spiel balanciert mit eigenen Faktoren.
- **Transformationen:** nur `translation` und `rotation` (Quaternion `[x, y, z, w]`), nie
  `scale`. Fehlende Felder bedeuten die Identität (glTF lässt sie weg).
- Der Wurzelknoten (`Ship`, `Asteroid`, `Wreck`, `Station` bzw. `StationKit`) liegt im
  Ursprung ohne Transformation.

### Meshes und Materialien

- Low Poly, flach schattiert: Vertex-Attribute `POSITION`, `NORMAL`, `TEXCOORD_0` (keine
  Vertex-Farben, keine Tangenten).
- Jedes sichtbare Teil ist geschlossen (manifold); ein Teil kann aus mehreren
  überlappenden geschlossenen Körpern bestehen (z. B. Tank = zwei Kugeln + Halterung).
- **Ein Material für alles: `ShipGen_Atlas`** (Paletten-Atlas, ein Primitive pro Mesh, ein
  Draw Call pro Teil). Jede „Farbe“ (Rumpflack, Metall, Glow …) ist eine Zelle von 8 × 8
  Pixeln in drei kleinen Texturen; die UVs jeder Fläche zeigen in ihre Zelle:
  - `baseColorTexture` (`ShipGen_Atlas_Color`, sRGB),
  - `metallicRoughnessTexture` (`ShipGen_Atlas_MR`, G = Roughness, B = Metallic),
  - `emissiveTexture` (`ShipGen_Atlas_Emit`) mit `KHR_materials_emissive_strength` –
    leuchtend sind nur die Glow-Zellen.
  Sampler `NEAREST` (keine Unschärfe zwischen den Zellen); in Godot Texturfilter „Nearest“
  lassen. Unter den Farbzellen liegen die Decal-Bilder (Abschnitt „Decals“). `doubleSided: true`.
- Ein Atlas gilt pro Datei (alle Teile teilen ihn); verschiedene Dateien haben eigene Atlanten.
- Die in den folgenden Abschnitten genannten Materialnamen (`ShipGen_Hull`, `ShipGen_Glow` …)
  sind die Farben **in Blender** – mit `cli.py --no-atlas` stehen sie stattdessen als einzelne
  Materialien (reine PBR-Faktoren, ein Primitive pro Material) in der `.glb`; dann über den
  Namen zuordnen, nicht über den Index.

### Decals

Kennung und Firmen-Emblem (Schiffe: beide Flanken; Stationen: Habitat, Raffinerie, Tank) und
Warnstreifen (Pier-Köpfe der Andockarme) sind **Geometrie**: dünne geschlossene Platten
(2,5 cm über der Oberfläche), deren Oberseite ein Pixelbild im Atlas zeigt. Der Hintergrund
der Bilder ist der Lack darunter – keine Transparenz nötig, Wracks schneiden sie mit dem Rumpf.

- Kennung: Schiff `<Klasse>-<Seed mod 1000>` (z. B. `MN-102`, Klassen `MN` `FR` `SH` `FT` `IC`
  `CV`), Station `<Rolle>-<Seed>` (`OP`, `MI`, `TR`, z. B. `MI-002`). 5 × 7-Pixelschrift.
- Emblem: gehört zum Farbschema (`style.palette` = Firma): `industrial_yellow` Winkel,
  `military_grey` Stern, `white_red` Ring, `desert` Dreieck, `navy` Raute, `black_gold`
  Krone, `rust` Zahnrad.
- Abschaltbar mit `style.decals = false` (Schiffe). Kleine Schiffe (Jäger) haben meist keinen
  Platz dafür.

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

Farben in Blender bzw. mit `--no-atlas` (sonst Zellen von `ShipGen_Atlas`):

| Name | Verwendung |
|---|---|
| `ShipGen_Hull` | Rumpflack (Rumpf, Flügel) |
| `ShipGen_Accent` | Metallteile (Triebwerke, Rigs, Modul-Rahmen, Greebles) |
| `ShipGen_Cargo` | Container-/Tankflächen |
| `ShipGen_Glow` | Leuchtend: Düsen, Fenster der Brücke, Habitat-Fensterbänder. Die Glow-Fläche der Triebwerke ist die Austrittsfläche (für Flammen-Effekte) |
| `ShipGen_Decal_Text`, `ShipGen_Decal_Emblem` | Oberseiten der Decal-Platten (Bild, sonst Rumpflack) |

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
| `plain` | Bruchflächen tauber Brocken, Kraterböden |
| `resource` | Bruchflächen und Adern erzhaltiger Brocken (zeigt den Rohstoff) |

Es stehen nur die Materialien in der Datei, die vorkommen (z. B. fehlt `plain`, wenn alle
Brocken erzhaltig sind).

### `<name>.json` (Asteroid)

Kommandozeile: `{"model", "model_params", "params", "stats"}`; Panel-Export:
`{"params", "stats"}`. `stats` wie `extras.shipgen_asteroid.stats`.

---

## 4. Wracks

Ein Wrack ist ein Shop-Schiff (Kit-Builder), zerbrochen und teilweise zerstört. Teile und
ihre Extras sind dieselben wie beim Schiff (Abschnitt 2), dazu kommen Rumpfsegmente,
Splitter und Zustände. Kommandozeile: `<preset>_<seed>` (z. B. `miner_m_broken_1`),
Panel: `wreck_<klasse>_<schiffsseed>_<seed>`.

### Knoten-Hierarchie

```
Wreck                                 extras.shipgen_wreck (Gesamtwerte)
├── Hull_0                            Rumpfsegment (mit Greebles)   extras.wreck_segment
│   ├── Hull_0_col_0-convcolonly …    seine Collider
│   ├── Engine_0                      montiertes Teil (intact/damaged) extras.shipgen_part, shipgen_salvage
│   │   └── Engine_0_col-convcolonly
│   └── Module_2 …
├── Hull_1 …                          weitere Segmente (bei breaks > 0), verschoben und gedreht
├── Module_0                          abgerissenes Teil (detached), direkt unter Wreck
│   └── Module_0_col-convcolonly
└── Debris_0                          Splitter                      extras.wreck_debris
    └── Debris_0_col-convcolonly
```

- **Segmente** `Hull_<k>`: Ursprung = Schwerpunkt des Segments, Translation und Rotation
  relativ zu `Wreck`. `wreck_segment = {index, volume_m3, mass_t, anchor}`; genau ein Segment
  hat `anchor: true` (liegt, wo das Schiff lag). Collider `Hull_<k>_col_<j>-convcolonly`.
- **Teile** haben ihre Schiffsnamen (`Engine_<n>`, `Rig_0`, `Module_<n>`, `Wings_<i>`,
  `Fin_<i>`) – es fehlen die zerstörten. Montierte Teile hängen unter ihrem Segment, ihre
  Transformation ist relativ zum Segment; abgerissene hängen direkt unter `Wreck`.
  `shipgen_salvage = {state, condition, mass_t}` mit `state` ∈ `intact`, `damaged`,
  `detached` (`destroyed` steht nur in der Gesamtliste), `condition` 0–1.
- **Splitter** `Debris_<i>`: `wreck_debris = {source, volume_m3, mass_t}`; `source` =
  `hull` oder der Name des zerstörten Teils.
- Keine `Socket_*`-Knoten und keine `Col_*`-Knoten des Schiffs.

### Gesamtwerte: `Wreck.extras.shipgen_wreck`

```json
{
  "seed": 1, "ship_seed": 1, "class": "miner",
  "stats": {
    "ship": {"seed": 1, "class": "miner", "design": "mono/flat/stepped/hammer",
             "engine": "ring_drive", "rig": "laser_twin", "module": "ore_skip", "wings": "none"},
    "segments": 2, "debris": 11,
    "parts": {"intact": 2, "damaged": 3, "detached": 1, "destroyed": 1},
    "salvage": [{"name": "Engine_0", "kind": "engine", "design": "ring_drive",
                 "state": "intact", "condition": 0.89, "mass_t": 1.59}, "…"],
    "salvage_mass_t": 26.6,
    "scrap_mass_t": 68.61
  }
}
```

`salvage_mass_t` = Teile (ohne zerstörte), `scrap_mass_t` = Segmente + Splitter.

### Materialien (Wrack)

Wie beim Schiff (`ShipGen_Hull`, `ShipGen_Accent`, `ShipGen_Cargo`, abgenutzt), dazu
`ShipGen_Wreck_Inside` (offene Enden, Lochböden), `ShipGen_Wreck_Burnt` (Brandspuren) und
`ShipGen_Wreck_Dead` (statt `ShipGen_Glow`: erloschene Düsen und Fenster; ein Wrack hat kein
`ShipGen_Glow`).

### `<name>.json` (Wrack)

Kommandozeile: `{"model", "model_params", "params", "stats", "ship", "ship_params"}` –
`ship` = Name des Shop-Presets, `ship_params` = das gebaute Schiff. Panel-Export:
`{"params", "ship_params", "stats"}`.

---

## 5. Stationen

Stationen bestehen aus Modulen auf einem Würfelraster (`grid_m` = 16 m). Es gibt zwei
Exporte: eine **fertige Station** (`Station`, Kommandozeile `<preset>_<seed>`, Panel
`station_<rolle>_<seed>`) und den **Modul-Baukasten** (`StationKit`, `station_kit.glb`): jedes
Design jeder Modulart einmal, nebeneinander, damit das Spiel selbst Stationen bauen kann.

### Knoten-Hierarchie

```
Station                               extras.shipgen_station (Gesamtwerte)
├── Hub_0                             Modul                         extras.station_module
│   ├── Hub_0_col_0-convcolonly …
│   ├── Hub_0_Port_0 … Hub_0_Port_5   Ports                         extras.station_port
├── DockM_0                           Andockarm
│   ├── DockM_0_col_0-convcolonly …
│   ├── DockM_0_Port_0
│   ├── DockM_0_Berth_0               Liegeplatz                    extras.station_berth
│   └── DockM_0_Berth_1
└── …
```

- **Modulnamen:** `<Art>_<n>` mit `Hub`, `Corridor`, `Habitat`, `Storage`, `Silo`, `Tank`,
  `Refinery`, `DockS`, `DockM`, `DockL`, `Solar`, `Radiator`, `Antenna`, `Command`; im
  Baukasten `<Art>_v<design>` (z. B. `DockL_v1`).
- **Modul-Ursprung** = Mitte seiner ersten Rasterzelle; Translation = Zelle × 16 m, Rotation
  um Vielfache von 90°. Lokale +Y-Achse (Godot −Z) = Hauptachse des Moduls.
- `station_module = {kind, design, grid_m, cells, reserved, ports, stats}`: `cells` /
  `reserved` = belegte / freizuhaltende Zellen im Modul-Rahmen (Blender-Achsen, ganze Zahlen),
  `ports` = `[{cell, dir}]` (Zelle und Richtung im Modul-Rahmen, Blender-Achsen),
  `stats` = Werte des Moduls (siehe unten).
- **Ports** `<Modul>_Port_<k>`: Mitte der Zellseite, lokale +Y (Godot −Z) zeigt nach außen.
  `station_port = {index, connected, radius_m}`; `connected` ist im Baukasten immer `false`.
  Zwei Module passen zusammen, wenn ein Port auf dem anderen liegt und beide gegeneinander
  zeigen; Port 0 ist der Anschluss, mit dem ein Modul angebaut wird.
- **Liegeplätze** `<Modul>_Berth_<k>`: wo der Ursprung eines angedockten Schiffs hinkommt;
  lokale +Y (Godot −Z) = Bug, +Z (Godot +Y) = oben – die Transformation des Liegeplatzes
  direkt auf den Schiffsknoten setzen. `station_berth = {index, size, max_length_m}` mit
  `size` S (≤ 20 m), M (≤ 40 m), L (≤ 64 m).
- Collider `<Modul>_col_<j>-convcolonly`, Identitäts-Transformation relativ zum Modul.
  Schmale Andockklammern und Leuchten haben keinen Collider.

### Modulwerte: `station_module.stats`

Immer `volume_m3`, `mass_t`; je nach Art zusätzlich `general_m3` (storage), `ore_m3` (silo),
`fluid_m3` (tank), `crew` (habitat, command), `refine_m3_h` (refinery), `power_kw` (solar),
`cooling_kw` (radiator), `berths` (Andockarme, z. B. `["M", "M"]`).

### Gesamtwerte: `Station.extras.shipgen_station`

```json
{
  "seed": 2, "role": "mining", "size": "medium", "grid_m": 16.0,
  "stats": {"modules": 19, "volume_m3": 22297.3, "mass_t": 2230.1,
            "general_m3": 0.0, "ore_m3": 4469.7, "fluid_m3": 0.0, "crew": 40,
            "refine_m3_h": 103.4, "power_kw": 243.6, "cooling_kw": 0.0,
            "kinds": {"hub": 2, "silo": 3, "dock_l": 3, "…": 0},
            "berths": {"S": 0, "M": 4, "L": 3}, "free_ports": 0}
}
```

`free_ports` = Ports ohne Gegenstück (dort kann das Spiel anbauen). Der Baukasten trägt
`StationKit.extras.shipgen_station_kit = {grid_m, port_radius_m, kinds}`; seine `.json` hat
unter `stats.modules` die `station_module`-Daten aller Designs.

### Materialien (Station)

`ShipGen_Hull`, `ShipGen_Accent`, `ShipGen_Cargo`, `ShipGen_Glow` (Fenster, Lichter) wie beim
Schiff (Palette aus `style`), dazu `ShipGen_Solar` (Solarpaneele) und die Decals
`ShipGen_DecalText`, `ShipGen_DecalEmblem`, `ShipGen_DecalStripes`.

### `<name>.json` (Station)

`{"model", "model_params", "params", "stats"}` (Kommandozeile) bzw. `{"params", "stats"}`
(Panel).

---

## 6. FX-Anker (Partikel und Lichter)

Partikeleffekte und Lichter baut das Spiel selbst (glTF kennt keine Partikel, und Effekte hängen
vom Spielzustand ab). Die Generatoren liefern nur, **wo** sie hingehören: leere Knoten mit
`extras.shipgen_fx = {kind, size, …}`.

- **Name:** enthält immer `FX_<kind>_<i>` – Schiff/Wrack/Asteroid `FX_<kind>_<i>`, Station
  `<Modul>_FX_<kind>_<k>`. Ohne Extras reicht also der Name.
- **Richtung:** die lokale **−Z-Achse** (Blender +Y) zeigt, wohin der Effekt geht (Düsenstrahl,
  Funkenflug, Rauchfahne). Für `GPUParticles3D` die Richtung im `ParticleProcessMaterial` auf
  `(0, 0, −1)` stellen.
- **`size`:** Größenordnung in Metern (Düsenradius, Lochgröße …) zum Skalieren des Effekts.
- Anker hängen an dem Teil, zu dem sie gehören (Rumpf, Segment, Modul, Brocken): Wird es
  bewegt, abgerissen oder zerbrochen, geht der Effekt mit.

| `kind` | wo | Extras | Hängt an |
|---|---|---|---|
| `exhaust` | Ende jeder Düse, Richtung = Schub nach hinten | – | `Ship` |
| `rcs` | Steuerdüsen vorn und hinten (oben, unten, Flanken) | – | `Ship` |
| `mining` | Arbeitspunkt des Rigs (Spitze), nach vorn | – | `Ship` |
| `nav_light` | Positionslichter: Backbord links, Steuerbord rechts, Heck | `color`: `red` / `green` / `white` | `Ship` |
| `spark` | an den Bruchkanten, aus dem Segment heraus | – | `Hull_<k>` |
| `smoke` | Böden der Löcher, nach außen | – | `Hull_<k>` |
| `vent` | Wrack: beschädigte/abgerissene Teile; Station: Raffinerie-Kamine, Tanks | – | Teil / Modul |
| `beacon` | Blinklicht an Pier-Spitzen und Antennen | – | Modul |
| `berth_light` | Liegeplatz-Licht (frei/belegt einfärben) | `berth`: Name des Liegeplatz-Knotens | Modul |
| `sublimation` | Eis: Dampffahnen an den äußersten Punkten einiger Brocken | – | `Chunk_<i>` |

Ein Wrack hat keine `exhaust`/`rcs`/`mining`/`nav_light` (alles tot), Erz- und
Metallasteroiden haben keine Anker. Staub beim Zerbrechen eines Asteroiden: am Ursprung
(= Schwerpunkt) des zerbrechenden Brockens.

Godot-Hilfsskript: [`godot/shipgen_fx.gd`](../godot/shipgen_fx.gd) (`ShipGenFx.attach(root,
{"exhaust": preload(...), ...})` sucht alle Anker und hängt die Effekt-Szenen an).

---

## 7. Checkliste für einen Importer

- [ ] Achsen übernehmen (glTF = Godot), keine Umrechnung nötig.
- [ ] Knoten mit Suffix `-convcolonly` als konvexe Collision-Shapes behandeln, nicht rendern.
- [ ] Ein Material `ShipGen_Atlas` übernehmen, Texturfilter „Nearest“; nur mit `--no-atlas`
      Materialien über den Namen (`ShipGen_*`) zuordnen, nicht über den Index.
- [ ] Schiff: Teile über `extras.shipgen_part` finden (Rolle, Art, Design, Sockel);
      Gesamtwerte aus `Ship.extras.shipgen` oder der `.json`.
- [ ] Schiff: Teile drehen/animieren um ihren eigenen Ursprung (= Sockel); Effekte an
      Sockel-Knoten oder Glow-Flächen hängen.
- [ ] Asteroid: Ebenen > 1 beim Laden ausblenden und Collider deaktivieren; beim Zerbrechen
      Elternteil aus, Kinder an.
- [ ] Optionale Knoten (Rig, Module, Flügel, Greebles) dürfen fehlen.
- [ ] FX-Anker (`*FX_<kind>_*`) nicht rendern; Effekte daran hängen, Emission entlang −Z.
- [ ] Wrack: Teile über `shipgen_salvage` zum Bergen anbieten; Segmente, Teile und Splitter
      sind eigene Körper (eigene Collider).
- [ ] Station: Module über `station_module` erkennen; Schiffe an `*_Berth_*` andocken;
      eigene Stationen aus dem Baukasten über Ports auf dem 16-m-Raster zusammensetzen.

Das Format hat derzeit kein eigenes Versionsfeld; maßgeblich ist die Version der Extension
(`shipgen/blender_manifest.toml`). Ältere Exporte (bis 0.2.0) hatten statt einzelner Teile
ein Mesh pro Rolle (`Ship_Engines`, `Ship_Mining`, `Ship_Cargo`, `Ship_Wings`).
