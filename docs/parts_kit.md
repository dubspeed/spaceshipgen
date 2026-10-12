# Bauteil-Baukasten – Konzept (Prototyp)

Zwei Probleme:

1. **Rümpfe sehen von oben alle gleich aus.** Zufälliges Verbiegen eines einzigen Grundrisses
   pro Klasse erzeugt keine erkennbaren Formen – es wirkt entweder gleich oder verzerrt.
2. **Passen alle Anbauteile an alle Rümpfe?** Wenn Teile frei skaliert und irgendwo angeklebt
   werden, hängen sie über, schneiden sich oder schweben.

Beide löst dasselbe Prinzip, das auch Modellbauer und Kitbashing nutzen: **entworfene
Bausteine + genormte Schnittstellen**, Zufall nur bei der *Auswahl*, nicht bei der *Form*.

## 1. Rümpfe aus Sektionen (Formensprache statt Rauschen)

Ein Rumpf = **Bauplan** + **Sektionen**:

| Baustein | Varianten (Prototyp) | Wirkung auf die Draufsicht |
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
  Jäger: `wedge/cockpit` …); der Seed wählt daraus. Die ±4 % Streuung bleibt obendrauf.
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
  an den Kästen.

## 4. Kollisionen

Jedes Teil wird als Instanz verfolgt; geprüft wird seine Hüllbox *außerhalb* seiner Montage
(der eingesteckte Fuß darf im Rumpf sitzen). Rumpf-Anbauten (Zinken, Kästen, Brücken,
Twin-Rümpfe) sind Hindernisse. Bei Treffern wird das unwichtigste Teil entfernt
(Modulpaar → Rig → Triebwerk) und gewarnt. `scripts/kit_conflicts.py` baut alle 240 Rümpfe
× 4 Rig-Arten × 4 Fracht-Arten mit Stress-Loadout und zählt, was womit kollidiert
(`docs/kit/conflicts.md`). Erster Lauf: Rig gegen Gabelzinken in allen 480 Gabel-Builds
(Sockel zu breit) → behoben, jetzt 0.

**Später für Godot:** dieselben Instanzen liefern Kollisionsformen. Godot erzeugt beim Import
Collision-Shapes aus Meshes mit dem Suffix `-convcolonly` (konvex, unsichtbar). Plan: pro
Rumpfsektion und pro Teil eine konvexe Hülle exportieren.

## Prototyp-Umfang

- `shipgen/kit/`: Sektionen + Baupläne + Sockel, 10 Triebwerks-Designs, Container an
  Seitensockeln, Sockel als Empties.
- `scripts/kit_demo.py`: rendert (a) die 10 Triebwerke, (b) Draufsicht-Silhouetten vieler
  Rumpfkombinationen, (c) Matrix Triebwerke × Hecks.
- `tests/test_kit.py`: die Passprüfungen aus Regel 4.
- Der bestehende Generator bleibt unverändert; Integration erst nach Entscheidung.
