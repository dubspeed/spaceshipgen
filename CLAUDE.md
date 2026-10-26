# ShipGen

Procedural low-poly spaceship generator for Blender (plus asteroids, wrecks and modular
stations), producing ships for a Godot game about
asteroid mining, freight and transport (combat exists but is secondary). Core idea: `generator.generate(params) -> Ship`
is a pure function of a validated parameter dict, independent of any UI. Two builders
(`params["builder"]`): **`kit`** (default for every preset; hulls from designed sections, parts
on sockets, see `docs/parts_kit.md`) and **`classic`** (old single-loft generator, kept for
comparison; `generator/wings.py` serves both). Three front-ends use it:
the extension panel (`shipgen/ui.py`), the headless CLI (`cli.py`) and, later, the AI prompt
(`shipgen/ai_prompt.py`, which will only produce parameter JSON).

## Art direction

- **Low poly, sharp edges.** Flat shading only, no smoothing, no subdivision. Hull sections
  have 10 vertices; a typical ship is 200–600 tris.
- **Surface detail stays in the hull's own geometry** (`kit/hull_detail.py`): grooves, raised
  flank panels, a dorsal trench - never on the roof where modules and greebles sit. Each lofted
  body is detailed alone (booleans need one clean shell); a twin's second body is the first
  mirrored. Greebles treat grooves/trench as obstacles; colliders use the plain loft, grown by
  the panel height over the mid section.
- **Distinct top-view silhouettes per class.** Fighter/interceptor = dart or needle with wings,
  freighter = brick of stepped modules, corvette = long hull, shuttle = stubby van.
  `Ship.stats()["top_view"]` measures it (`fill` = silhouette area / bounding rectangle);
  `test_classes_have_distinct_top_silhouettes` guards it. Check top renders after shape changes.

## Gameplay stats (geometry is the source of truth)

`shipgen/stats.py` derives stats from the generated meshes, never from the parameters directly:
mass from part volumes × density, thrust from glowing nozzle area, acceleration and turn rate
from both, hull HP from hull surface × class armor, cargo from module volumes (containers →
`general_m3`, hoppers → `ore_m3`, tanks → `fluid_m3`, habitat → `passengers`) plus the class's
internal hold, mining power = per-type efficiency × rig volume^(2/3). Units are physical-ish;
the game balances with its own multipliers. Stats go into the CLI JSON and the glTF extras
(`root["shipgen"]`).

**The seed changes the look, not the stats** (kit builder):
- part sizes come from the model params (`engines.size`, `mining.size`, `cargo.size`), never
  from the socket; the seed tries hull designs in its own order and keeps the first that carries
  the whole loadout (warnings starting with `fit:` mean it could not);
- hull mass / hold / HP come from the model's reference hull (mono/flat/straight/blunt with the
  same dimensions), so the body plan is pure looks;
- every engine / rig / module design is normalised to the mean of its kind
  (`kit/normalize.py`, measured on the unit designs);
- what remains is the manufacturing `spread` (default 0.025 → roughly ±10 % per stat).
`KitStatsTest` guards this (design alone < 8 %, with spread < 20 %, bigger models stay bigger).
Mining calibration: medium rig (size 0.5 on `miner_m`) = 100 per kind; rerun
`scripts/kit_calibrate.py` and update `KIT_MINING_EFFICIENCY` after changing rig designs or rig
sizing. The classic builder has its own `MINING_EFFICIENCY` (`test_mining_rigs`).

## Shop lineup

Presets are the ship models a player can buy: size tiers × loadouts (`miner_s/m/l`,
`miner_m_hauler`, `miner_gas`, `hauler_s/m/l`, `hauler_m_fast`, `tanker_m`, `liner_m`) plus
combat/generic ones. The seed only
changes the look within a model. Every preset must generate without warnings
(`test_presets_generate_cleanly`); a kit model whose loadout doesn't fit any hull for some seeds
needs fewer/smaller modules (see `hauler_l`). `kit.*` in a preset pins blocks/designs
(`miner_m_hauler` pins the sponson mid so it doesn't share `miner_m`'s hulls: models with the
same class, mining and cargo type share the seed streams).

## Blender versions

- Target: **Blender 4.2+**, packaged only as an extension (`shipgen/blender_manifest.toml`),
  no legacy `bl_info`. The owner runs Blender 5.x locally; it must keep working there.
- Cloud sessions: the SessionStart hook (`.claude/settings.json`) runs `scripts/setup_env.sh`,
  which puts the `bpy` module (Blender 5.2 LTS from PyPI, pinned in `requirements-dev.txt`,
  needs Python 3.13) into `.venv`. No Blender binary is installed; run everything with
  `.venv/bin/python`.
- Inside `shipgen/` use relative imports only (extensions are namespaced as `bl_ext.*`).
- Headless previews use Cycles on the CPU (Eevee/Workbench need a GPU).
- After deleting objects, call `view_layer.update()` before iterating `view_layer.objects`
  (Blender 5 keeps stale `None` entries otherwise).

## Layout

- `shipgen/params.py` – schema (type, default, min/max, choices) + `validate()`. Pure Python,
  no `bpy`. `validate()` never raises on bad values: it clamps/replaces and returns warnings.
  Add every new parameter here first; the UI and `json_schema()` derive from it.
- `shipgen/generator/` – `__init__.py` (`generate`, `Ship`, `clear`), `hull.py` (class profiles
  incl. cargo zone / hold / armor, `HullShape` that other parts attach to), `wings.py`,
  `engines.py`, `mining.py` (nose rigs), `cargo.py` (modules in symmetric lanes),
  `shapes.py` (low-poly primitives), `materials.py` (classic only; greebles are kit-only).
- `shipgen/stats.py` – gameplay stats from geometry (see above).
- `shipgen/kit/` – the default builder: `hull_kit.py` (sections with a standard joint, body plans
  mono/twin/fork, class kits), `engine_designs.py` / `rig_designs.py` / `module_designs.py`
  (10 each, unit size), `greeble_designs.py` (6, look only), `hull_detail.py` (surface detail by
  class, `kit.detail`: belt grooves as extra loft stations, raised side panels via bmesh inset,
  dorsal trench via Boolean modifier - MANIFOLD solver, EXACT on Blender < 4.5), `__init__.py`
  (`build` -> `_build_hull` (bodies, add-ons incl. the command bridge, sockets) -> `_place_parts`
  -> collision check + resolver -> `_finish_bodies` (trench where no roof module sits, join the
  detailed bodies) -> triangle budget -> greebles -> role objects, sockets as empties),
  `collision.py` (convex `-convcolonly`
  shapes for Godot), `normalize.py` (stat normalisation). Concept: `docs/parts_kit.md`.
  Every new part design must honour the unit contract in its module docstring
  (`EngineDesignTest`, `ModuleDesignTest` check it); new hull
  blocks must also be added to `params.KIT_*` (test checks it).
- `shipgen/asteroids/` – asteroid generator (prototype, `docs/asteroids/README.md`): own schema
  (`params.py`, same `Field`/`validate` machinery), `geometry.py` (convex polytopes as point
  lists: hull, half-space clip, Voronoi cells), `__init__.py` (`generate`: faceted rock,
  pre-fractured into convex chunks level by level down to `min_chunk_m`; surface faces roughened
  by `surface.py` (world-space noise + craters, so neighbours and sub-chunks match); each chunk
  has a convex `<name>_col-convcolonly` child (exact hull of its vertices); deeper levels are
  parented under their chunk and hidden; per-chunk stats from the mesh; `COMPOSITION` =
  ore/metal/ice constants). Presets in `presets/asteroids/`.
- `shipgen/wrecks/` – wrecks of shop models (prototype, `docs/wrecks/README.md`): builds the kit
  ship, cuts hull + greebles into drifting segments `Hull_<k>` (ragged rim, hollow cap), pits,
  scorch, dead glow; parts keep names/extras plus `shipgen_salvage` state; segment colliders are
  the ship's hull pieces clipped by the break planes. Own `ShipGen_Wreck` collection, so it can
  sit next to the ship (Blender suffixes its names `.001`; `export._plain_names` strips them).
  Presets in `presets/wrecks/` name their ship preset under `"ship"`.
- `shipgen/stations/` – station module kit + layouts (prototype, `docs/stations/README.md`):
  `modules.py` holds the grid contract (16 m cells, ports on cell faces, port 0 on -Y of cell 0,
  reserved berth cells; `ModuleKitTest` checks every design) and the designs; `__init__.py` lays
  out stations (spine of hubs, symmetric arm chains per role) and builds the kit (`build_kit`).
  `build`: `truss` (slim) or `massive` (`modules.MASSIVE`: 3x3x3 `core` nodes, cell-filling
  modules, heavy docks); massive kinds draw designs from their own rng stream. `spine`: auto
  (massive horizontal = flat for the game's top-down view, truss vertical), horizontal, vertical.
  Rng draws must never depend on set order (BMesh element hashes are addresses).
  Presets in `presets/stations/`.
- `shipgen/atlas.py` – palette atlas at export (one `ShipGen_Atlas` material per mesh);
  `shipgen/decals.py` – 5x7 pixel font, company emblems by palette, decal slabs.
- `shipgen/fx.py` – FX anchors (empties with `shipgen_fx` extras, local +Y = emission
  direction, name contains `FX_<kind>_`) that every generator adds; the game owns the particle
  effects (`godot/shipgen_fx.gd` attaches them). FX draws use their own rng stream so they never
  change shapes.
- `shipgen/metrics.py` – top-view silhouette metrics (numpy rasteriser).
- `shipgen/export.py` – `.glb`, `.blend`, Cycles previews (`three_quarter` and orthographic `top`).
- `shipgen/ui.py` – sidebar tab "ShipGen": ship panel + "Wrecks", "Asteroids", "Stations"
  panels (`WRECK_GROUPS`, `ASTEROID_GROUPS`, `STATION_GROUPS`,
  `show_level` toggles the break levels in the viewport); properties generated from the schemas
  (nested keys flattened as `hull__length`); `tests/test_ui.py` runs the operators headless.
- `cli.py`, `presets/*.json` (one per class), `tests/`, `scripts/`.

## Conventions

- Export target is **Godot** (+Y up, -Z forward, +X right). The glTF exporter's Y-up
  conversion maps Blender's nose +Y to -Z, so modelling stays in Blender axes and no node
  rotation is needed; `GodotAxesTest` pins this. Don't add a rotation at export time.
- Axes in Blender: nose +Y, up +Z, ship centred on the origin. The **hull** spans exactly `hull.length`
  in Y; engines may stick out behind it.
- Randomness: one `random.Random(f"{seed}:<part>")` per part, so changing one part never
  changes the shapes of other parts for the same seed.
- Triangle budget: the hull uses at most `HULL_TRI_SHARE` (60 %) of `max_tris` and falls back
  to its class keyframes; then wings and mining rig; engines and finally cargo modules get what
  is left (counts reduced, with a warning). Modules that don't fit the cargo zone are dropped
  with a warning too.
  Tests enforce `tris <= max_tris`.
- Every part is a closed, manifold mesh without zero-area faces; mirror symmetric when
  `symmetry` is on. Fan n-gon caps from their centre (`bmesh.ops.poke`) instead of
  triangulating them, since boxy sections have collinear points.
- Each part object carries `shipgen_role` (hull, wings, engines, mining, cargo; kit colliders:
  collision); stats sum parts per role (`stats.measure_roles`, in ship space via
  `matrix_basis`). Kit ships export one object per fitted part (`Engine_<i>`, `Rig_0`,
  `Module_<i>`, `Wings_<i>`, `Fin_<i>`; origin and rotation = its socket, extras
  `shipgen_part` = role/kind/design/socket, own `<name>_col-convcolonly` child), plus
  `Ship_Hull`, `Ship_Greebles`, `Socket_<kind>_<i>` empties and `Col_<i>-convcolonly` meshes
  for the hull and add-ons (Godot turns `-convcolonly` meshes into collision shapes on import).
- Parts are several overlapping closed shells: orient them with `meshutil.orient_outward` and
  measure with `meshutil.volume` (per shell) - `recalc_face_normals` alone can turn a whole
  shell inside out (wrong lighting, negative volume).
- Everything a ship creates lives in the `ShipGen` collection under the `Ship` empty;
  materials are prefixed `ShipGen_`. `generate()` replaces the previous ship.
- Materials in Blender: plain Principled values per paint (stats read them: glow area = thrust,
  cargo shells), no linked textures except decal images. The .glb gets one material per mesh:
  `atlas.baked` turns every paint into an 8 px cell of a palette atlas at export time (UVs into
  the cell, NEAREST sampling; `--no-atlas` exports the paints). Atlas/decal pixels are sRGB.
- Decals (`decals.py`) are geometry: thin closed slabs laid onto the surface by ray casts, top
  face textured, background = the paint underneath (no alpha); ship decals are projected on the
  starboard flank and mirrored (exact symmetry), greebles keep off them.
- The export format (node names, extras, materials, asteroid levels) is specified for importer
  authors in `docs/export_format.md`: update it whenever the .glb/.json structure changes.
- `output/` and `dist/` are git-ignored. Commit presets and, occasionally, the docs sheets
  (`scripts/render_docs.py` regenerates all of them).

## Commands

```bash
scripts/setup_env.sh                       # once (the hook does this in cloud sessions)
# one ship: output/fighter_42{.glb,.blend,.png,_top.png,.json}
.venv/bin/python cli.py --preset fighter
# batch / overrides / quick (no render)
.venv/bin/python cli.py --preset fighter --seeds 1-20 --no-render --set hull.length=30
# all tests (params, generator, export, CLI end-to-end)
.venv/bin/python -m unittest discover -s tests -t .
# compare silhouettes: render top views, tile them
.venv/bin/python cli.py --preset freighter --seeds 1-6 --views top --no-glb --no-blend --out /tmp/s
.venv/bin/python scripts/contact_sheet.py /tmp/s/sheet.png --cols 3 /tmp/s/*_top.png
# shop lineup at one scale + stats table
.venv/bin/python cli.py --preset all --frame 64 --no-glb --no-blend --out /tmp/l
python3 scripts/stats_table.py /tmp/l/*.json
# kit: collision report, mining calibration, part/ship sheets (docs/kit/)
.venv/bin/python scripts/kit_conflicts.py
.venv/bin/python scripts/kit_calibrate.py
.venv/bin/python scripts/kit_demo.py [--only parts,ships,matrix,colliders]
# hull detail before/after sheets (docs/hull_detail/)
.venv/bin/python scripts/hull_detail_demo.py
# asteroids: CLI (presets/asteroids/), demo sheets (docs/asteroids/)
.venv/bin/python cli.py --asteroid ore_m
.venv/bin/python scripts/asteroid_demo.py
# wrecks and stations: CLI (presets/wrecks/, presets/stations/), sheets (docs/stations/, docs/wrecks/)
.venv/bin/python cli.py --wreck miner_m_broken
.venv/bin/python cli.py --station mining_m
.venv/bin/python cli.py --station-kit --no-render
.venv/bin/python scripts/station_demo.py [--only modules,stations,docked,wrecks]
# re-render every docs picture/table (lineup + stats, kit, hull_detail, asteroids, stations/wrecks)
.venv/bin/python scripts/render_docs.py [--only lineup,stations] [--list]
# installable extension zip -> dist/
python3 scripts/build_extension.py
```

With a local Blender binary the CLI also runs as `blender -b -P cli.py -- --preset fighter`.
