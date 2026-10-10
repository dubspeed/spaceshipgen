# ShipGen

Procedural spaceship generator for Blender. Core idea: `generator.generate(params) -> Ship` is a
pure function of a validated parameter dict, independent of any UI. Three front-ends use it:
the add-on panel (`shipgen/ui.py`), the headless CLI (`cli.py`) and, later, the AI prompt
(`shipgen/ai_prompt.py`, which will only produce parameter JSON).

## Blender versions

- Cloud/CI: **Blender 4.0.2** (Ubuntu package). `scripts/cloud_setup.sh` installs it plus
  `python3-numpy` (the Ubuntu build uses system Python; the glTF exporter needs numpy).
  That build has no OpenImageDenoise, so previews are rendered without denoising.
- Local: **TODO: fill in your local Blender version.** For 4.2+ install as extension
  (`shipgen/blender_manifest.toml`); 4.0/4.1 use `bl_info` as legacy add-on.
- Keep code working on 4.0 *and* 4.2+: e.g. `mesh.use_auto_smooth` only exists < 4.1
  (see `hull.py`), use relative imports inside `shipgen/` (extensions are namespaced).
- Eevee/Workbench need a GPU/OpenGL context; headless previews use Cycles on the CPU.

## Layout

- `shipgen/params.py` – schema (type, default, min/max, choices) + `validate()`. Pure Python,
  no `bpy`. `validate()` never raises on bad values: it clamps/replaces and returns warnings.
  Add every new parameter here first; the add-on UI and `json_schema()` derive from it.
- `shipgen/generator/` – `__init__.py` (`generate`, `Ship`, `clear`), `hull.py`,
  `materials.py`. Planned: `wings.py`, `engines.py`, `greebles.py`.
- `shipgen/export.py` – `.glb`, `.blend`, Cycles preview PNG (camera auto-framed).
- `shipgen/ui.py` – sidebar panel "ShipGen"; properties generated from the schema
  (nested keys flattened as `hull__length`).
- `cli.py`, `presets/*.json`, `tests/`.

## Conventions

- Axes: nose +Y, up +Z, ship centred on the origin. Hull length == bbox Y extent.
- Randomness: one `random.Random(f"{seed}:<part>")` per part, so adding a part never
  changes the shapes of existing parts for the same seed.
- Triangle budget: hull uses at most `HULL_TRI_SHARE` (60 %) of `max_tris`; the remaining
  parts must share the rest. Tests enforce `tris <= max_tris`.
- Everything a ship creates lives in the `ShipGen` collection under the `Ship` empty;
  materials are prefixed `ShipGen_`. `generate()` replaces the previous ship.
- Materials: plain Principled values only (no linked textures), so the glTF matches.
- `output/` is git-ignored. Only commit presets and occasional example renders
  (`docs/renders/`).

## Commands

```bash
# one ship: output/fighter_42.{glb,blend,png,json}
blender -b --factory-startup -P cli.py -- --preset fighter
# batch / overrides / quick (no render)
blender -b --factory-startup -P cli.py -- --preset fighter --seeds 1-20 --no-render \
    --set hull.length=30 --set class=interceptor
# tests: pure Python (params + CLI end-to-end via blender subprocess)
python3 -m unittest discover -s tests -t .
# tests: inside Blender (generator + export)
blender -b --factory-startup -P tests/run_blender.py
```

After changing shapes, render previews (`--seeds 1-6`) and look at the PNGs.
