# ShipGen

Procedural low-poly spaceship generator for Blender. Core idea: `generator.generate(params) -> Ship`
is a pure function of a validated parameter dict, independent of any UI. Three front-ends use it:
the extension panel (`shipgen/ui.py`), the headless CLI (`cli.py`) and, later, the AI prompt
(`shipgen/ai_prompt.py`, which will only produce parameter JSON).

## Art direction

- **Low poly, sharp edges.** Flat shading only, no smoothing, no subdivision. Hull sections
  have 10 vertices; a typical ship is 200–600 tris.
- **Distinct top-view silhouettes per class.** Fighter/interceptor = dart or needle with wings,
  freighter = brick of stepped modules, corvette = long hull, shuttle = stubby van.
  `Ship.stats()["top_view"]` measures it (`fill` = silhouette area / bounding rectangle);
  `test_classes_have_distinct_top_silhouettes` guards it. Check top renders after shape changes.

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
- `shipgen/generator/` – `__init__.py` (`generate`, `Ship`, `clear`), `hull.py` (class profiles,
  `HullShape` that other parts attach to), `wings.py`, `engines.py`, `materials.py`.
  Planned: `greebles.py`.
- `shipgen/metrics.py` – top-view silhouette metrics (numpy rasteriser).
- `shipgen/export.py` – `.glb`, `.blend`, Cycles previews (`three_quarter` and orthographic `top`).
- `shipgen/ui.py` – sidebar panel "ShipGen"; properties generated from the schema
  (nested keys flattened as `hull__length`).
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
  to its class keyframes; engines get what is left (count reduced, with a warning).
  Tests enforce `tris <= max_tris`.
- Every part is a closed, manifold mesh without zero-area faces; mirror symmetric when
  `symmetry` is on. Fan n-gon caps from their centre (`bmesh.ops.poke`) instead of
  triangulating them, since boxy sections have collinear points.
- Everything a ship creates lives in the `ShipGen` collection under the `Ship` empty;
  materials are prefixed `ShipGen_`. `generate()` replaces the previous ship.
- Materials: plain Principled values only (no linked textures), so the glTF matches.
- `output/` and `dist/` are git-ignored. Commit presets and, occasionally, `docs/renders/gallery.png`.

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
# installable extension zip -> dist/
python3 scripts/build_extension.py
```

With a local Blender binary the CLI also runs as `blender -b -P cli.py -- --preset fighter`.
