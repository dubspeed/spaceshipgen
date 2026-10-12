# Bauteil-Baukasten – Konzept

Zwei Probleme:

1. **Rümpfe sehen von oben alle gleich aus.** Zufälliges Verbiegen eines einzigen Grundrisses
   pro Klasse erzeugt keine erkennbaren Formen – es wirkt entweder gleich oder verzerrt.
2. **Passen alle Anbauteile an alle Rümpfe?** Wenn Teile frei skaliert und irgendwo angeklebt
   werden, hängen sie über, schneiden sich oder schweben.

Beide löst dasselbe Prinzip, das auch Modellbauer und Kitbashing nutzen: **entworfene
Bausteine + genormte Schnittstellen**, Zufall nur bei der *Auswahl*, nicht bei der *Form*.

## 1. Rümpfe aus Sektionen (Formensprache statt Rauschen)

Ein Rumpf = **Bauplan** + **Sektionen**:

| Baustein | Varianten | Wirkung auf die Draufsicht |
|---|---|---|
| Bauplan | `mono`, `twin` (Katamaran), `fork` (Gabelbug) | Grundtopologie: Pfeil, „II“, „U“ |
| Heck | `flat`, `taper`, `flare`, `outboard` | Breites Triebwerksheck, spitz, Ausleger |
| Mitte | `straight`, `waist`, `bulge`, `stepped`, `sponson` | Taille, Bauch, Stufen, Seitenkästen |
| Bug | `wedge`, `blunt`, `hammer`, `cockpit` | Spitze, Stumpf, T-Form, Kanzel |

- Jede Sektion ist **von Hand entworfen** (Keyframes), nicht zufällig – deshalb wirkt keine
  Kombination verzerrt.
- **Genormte Fuge:** Jede Sektion beginnt und endet am Normquerschnitt des Schiffs
  (Breite = 1, Höhe = 1 relativ zum Rumpfmaß). Deshalb passt jedes Heck an jede Mitte an
  jeden Bug – wie Lego.
- Die Klasse legt fest, **welche** Bausteine erlaubt sind (Miner: `blunt/hammer/fork`,
  Jäger: `wedge/cockpit` …); der Seed wählt daraus, feste Bausteine (`kit.*`) gewinnen.
  Eine Gabel bekommt immer den stumpfen Bug; ist ein anderer Bug fest gewählt, fällt die
  Gabel aus der Auswahl.
- 3 Baupläne × 4 Hecks × 5 Mitten × 4 Bugs = 240 Grundformen statt 6.

## 2. Anbauteile an Sockeln (Hardpoints)

Jede Sektion liefert **Sockel**: Position, Richtung (Normale), Art, **Maximalradius**.

| Sockel | kommt von | trägt |
|---|---|---|
| `engine` | Heck (Fläche oder Ausleger) | Triebwerke |
| `nose` | Bug (Stirnfläche) | Bohrer, Laser, Klauen, Schaufel |
| `side` / `top` | Mitte (flache Seitenflächen) | Container, Hopper, Tanks, Habitat |

Regeln, die „passt immer“ garantieren:

1. **Teile werden in Einheitsgröße entworfen** (Radius 1, Montageplatte im Ursprung) und nur
   **gleichmäßig** auf den Sockelradius skaliert – nie gestreckt, also nie verzerrt.
2. **Sockel überlappen nie.** Das Heck verteilt n Triebwerke so, dass jeder Sockel seinen
   Radius frei hat. Passt das gewünschte Triebwerk nicht auf die Heckfläche, wird
   **nicht gestaucht**, sondern auf Ausleger (`outboard`) ausgewichen oder die Größe
   gedeckelt (mit Warnung).
3. **Montage über Adapter.** Teile sitzen auf flachen Flächen und haben einen Kragen/eine
   Platte, die in den Rumpf ragt – die Fuge ist immer verdeckt. Ausleger bekommen einen
   Pylon, der Rumpf und Teil verbindet.
4. **Automatische Passprüfung:** Tests prüfen für alle Teil × Rumpf-Kombinationen:
   geschlossene Meshes, Spiegelsymmetrie, Teile innerhalb ihres Sockelradius, keine
   Überschneidung zwischen Teilen.
5. **Sichtprüfung per Matrix-Render:** jedes Triebwerk auf jedem Heck in einem Sheet.

Die Sockel werden als leere Nodes (`Socket_engine_0` …) in die `.glb` exportiert. Godot kann
damit später Teile tauschen (Triebwerk nachrüsten), ohne neu zu generieren.

## 3. Rigs und Module (Stand)

- **10 Rigs** (`kit/rig_designs.py`): Bohrer (Kegel, Dreifach, Fräswalze), Laser (einzeln, doppelt,
  Array), Klauen (2 und 4 Arme), Schaufeln (Trichter, Ring). `mining.type` wählt die Art, der
  Seed das Design. Spitze Bugs haben keine Stirnfläche → kein Rig (Warnung); Miner dürfen nur
  stumpfe Bugs, Hammerköpfe oder Gabeln wählen.
- **10 Module** (`kit/module_designs.py`): Container (Kiste, gerippt, Doppel), Erz (Hopper, Skip),
  Tanks (Zylinder, Zwilling, Kugeln), Habitat (Trommel, Block). Bauraum je Seitensockel:
  Tiefe 1 × Länge 2 × Höhe 1, immer paarweise gespiegelt. Bei Seitenkästen sitzen sie außen
  an den Kästen. Reihenfolge: erst Seitensockel, dann **Dachsockel** (Mono: zwei gespiegelte
  Reihen auf dem Dach, wenn es breit genug ist; Twin: eine Reihe pro Rumpf). Auf dem Dach
  zeigt das „oben“ des Moduls nach außen, damit gespiegelte Sockel gespiegelte Module tragen.
  Ausnahme: offene Erzbehälter (`UPRIGHT`: Hopper, Skip, mit sichtbarem Erzhaufen) werden auf
  dem Dach als Ganzes aufgerichtet – Öffnung nach oben, starr verschoben, also gleiches Volumen.

## 4. Kollisionen

Jedes Teil wird als Instanz verfolgt; geprüft wird seine Hüllbox *außerhalb* seiner Montage
(der eingesteckte Fuß darf im Rumpf sitzen). Rumpf-Anbauten (Zinken, Kästen, Brücken,
Twin-Rümpfe) sind Hindernisse. Bei Treffern wird das unwichtigste Teil entfernt
(Modulpaar → Rig → Triebwerk) und gewarnt. `scripts/kit_conflicts.py` baut alle 240 Rümpfe
× 4 Rig-Arten × 4 Fracht-Arten mit Stress-Loadout und zählt, was womit kollidiert
(`docs/kit/conflicts.md`). Erster Lauf: Rig gegen Gabelzinken in allen 480 Gabel-Builds
(Sockel zu breit) → behoben, jetzt 0.

**Godot-Kollisionsformen** (`kit/collision.py`): Godot erzeugt beim Import aus jedem Mesh mit
dem Suffix `-convcolonly` eine unsichtbare konvexe Collision-Shape. Exportiert werden:
jeder Rumpfkörper zwischen je zwei Querschnitten zerschnitten (jedes Stück ist konvex) und
benachbarte Stücke zusammengelegt, solange ihre gemeinsame Hülle ≤ 6 % größer ist (so bleibt
eine Taille eine Taille); dazu je eine Hülle pro Zinke/Kasten/Brücke/Pylon und pro Anbauteil.
Typisch 12–17 Shapes pro Schiff. Tests prüfen: jede Shape konvex, jeder sichtbare Vertex liegt
in mindestens einer Shape (keine Lücken), Namen kommen in der `.glb` an.
Hinweis für Godot: `-convcolonly`-Nodes werden beim Import zu StaticBody3D mit
CollisionShape3D; für ein bewegtes Schiff die CollisionShape3D-Kinder unter den eigenen
RigidBody3D/CharacterBody3D hängen (oder im Import-Skript umhängen).

## 4b. Flügel, Brücke und Greebles

- **Flügel** kommen aus `generator/wings.add_wings` (gleiche Geometrie wie im classic-Generator)
  und docken an `wing`-/`fin`-Sockeln an; Kollisionen mit Modulen, Kästen, Zinken oder
  Triebwerken zählen als Passproblem → anderer Rumpf.
- **Brücke**: Frachter und Miner ab 20 m (Mono/Gabel) bekommen auf dem Heckdach ein
  Deckshaus mit erhöhter Brücke und leuchtendem Fensterband (wie ein Frachtschiff). Es gehört
  zum Rumpf, ist reine Optik (Rumpfwerte kommen vom Referenzrumpf) und endet vor der Mitte,
  wo die Dachmodule sitzen.
- **Rumpfdetails** (`kit/hull_detail.py`, `kit.detail` 0–1, je Klasse): Rillen ringsum
  (zusätzliche Querschnitte im Loft, alle Klassen), erhabene Paneele nur an den Flanken (Frachter,
  Miner, Korvette; das Dach ist mit Modulen und Greebles schon voll), Dachgraben per
  Boolean-Modifier (Frachter, Korvette) nur auf Dachabschnitten ohne Module. Reine Optik.
- **Greebles** (`kit/greeble_designs.py`, 6 Designs: Lüftung, Antenne, Schüssel, Platte,
  Leitungen, Licht): freie Dach-/Seitenplätze, gespiegelt, `greeble_density` steuert die Menge,
  der Seed wählt 3 Designs als Stil des Schiffs. Sie werden nur platziert, wo sie nichts
  berühren, zählen nicht in die Werte und bekommen keine Collider.

## 5. Werte: der Seed ändert die Optik, nicht die Werte

Der Seed wählt Bauplan und Teile-Designs – das darf die Werte eines Modells nicht verschieben
(gemessen vorher: Beschleunigung ×7, Abbauleistung ×13 zwischen Seeds eines Modells).

- **Teilegrößen aus dem Modell**, nicht aus dem Sockel. Der Seed probiert Rumpfdesigns in
  seiner Reihenfolge und nimmt das erste, das das ganze Loadout trägt (großer Bohrer → keine
  Gabel). Warnungen mit `fit:` heißen: kein Rumpf trug es vollständig.
- **Rumpfwerte aus dem Referenzrumpf** des Modells (mono/flat/straight/blunt, gleiche Maße):
  Masse, Laderaum, Hülle. Der gewählte Bauplan ist reine Optik.
- **Design-Normierung:** jedes Triebwerks-, Rig- und Moduldesign auf den Mittelwert seiner Art
  (`kit/normalize.py`, gemessen an den Einheitsdesigns).
- Übrig bleibt die Fertigungsstreuung (`spread` 0.025 → etwa ±10 %).

Ergebnis (8 Seeds je Modell): Design allein < 8 %, mit Streuung ±6–15 % je Wert.
Abbau-Kalibrierung: mittleres Rig = 100 je Art (`scripts/kit_calibrate.py`).

## Code

- `shipgen/kit/hull_kit.py`: Sektionen, Baupläne, Klassen-Baukästen, Kandidatenreihenfolge.
- `shipgen/kit/__init__.py`: `build` → `_build_hull` (Körper, Anbauten, Sockel) →
  `_place_parts` → Kollisionsauflösung → Dreiecksbudget → Greebles → Objekte, Sockel, Collider, Werte.
- `shipgen/kit/*_designs.py`: Teile-Bibliotheken (Einheitsvertrag im Modul-Docstring).
- `scripts/kit_demo.py`: Sheets der Teile, Rumpf-Silhouetten und Matrix Triebwerke × Hecks
  (`docs/kit/`); `scripts/kit_conflicts.py`: Kollisions-Stresstest; `scripts/kit_calibrate.py`.
- `tests/test_kit.py`: die Passprüfungen aus Regel 4, Werte-Stabilität, Collider.
- Der Baukasten ist der Standard-Generator (`builder: kit`) für alle Presets, inklusive
  Kampfschiffe (Flügel an Sockeln); `classic` bleibt nur zum Vergleich.
