"""Render the parts-kit prototype sheets into docs/kit/ (or --out).

    .venv/bin/python scripts/kit_demo.py [--out docs/kit] [--quick]

engines.png        the 10 engine designs, unit size, rear view
rigs.png           the 10 mining rig designs, unit size
modules.png        the 10 cargo / ore / tank / habitat module designs, unit size
silhouettes_*.png  top views of 8 seeds per model, same scale
ships_*.png        the same ships in three-quarter view
matrix.png         every engine design (columns) on every tail (rows), rear view
"""

import argparse
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import bpy  # noqa: E402  (must come before bmesh)
import bmesh  # noqa: E402

from shipgen import export, kit, params  # noqa: E402
from shipgen.generator import Ship, clear, materials  # noqa: E402
from shipgen.kit import engine_designs, module_designs, rig_designs  # noqa: E402

RES, SAMPLES = (400, 225), 24

PYTHON = sys.executable


def sheet(out, paths, cols):
    subprocess.run([PYTHON, os.path.join(ROOT, "scripts", "contact_sheet.py"), out, "--cols", str(cols), *paths],
                   check=True, capture_output=True)


def render(ship, path, view, res, samples, frame=None):
    export.render_preview(ship, path, view=view, resolution=res, samples=samples, frame=frame)
    return path


def part_sheet(tmp, out, name, builder, count, normal, view, frame, cols=5):
    """Render ``count`` unit-size part designs, each alone on a socket at the origin."""
    paths = []
    p = params.defaults()
    for i in range(count):
        clear("ShipGen")
        coll = bpy.data.collections.new("ShipGen")
        bpy.context.scene.collection.children.link(coll)
        mats = materials.create_materials(p)
        bm = bmesh.new()
        builder(bm, i, (0, 0, 0), normal, 1.0)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        for key in ("accent", "glow", "cargo"):
            mesh.materials.append(mats[key])
        obj = bpy.data.objects.new(name, mesh)
        coll.objects.link(obj)
        ship = Ship(root=obj, parts=[obj], params=p)
        paths.append(render(ship, os.path.join(tmp, f"{name}_{i}.png"), view, RES, SAMPLES, frame=frame))
    sheet(os.path.join(out, f"{name}.png"), paths, cols)


def model_sheets(tmp, out, model, seeds, res, samples, frame):
    base = params.load(os.path.join(ROOT, "presets", f"{model}.json")).params
    tops, threes, labels = [], [], []
    for seed in seeds:
        ship = kit.build(dict(base, seed=seed))
        lo = ship.loadout
        labels.append(f"{seed}: {ship.design.label()} + {lo['engine']} / {lo['rig']} / {lo['module']}"
                      + (f" (warnings: {'; '.join(ship.warnings)})" if ship.warnings else ""))
        tops.append(render(ship, os.path.join(tmp, f"{model}_{seed}_top.png"), "top", res, samples, frame))
        threes.append(render(ship, os.path.join(tmp, f"{model}_{seed}.png"), "three_quarter", res, samples))
    sheet(os.path.join(out, f"silhouettes_{model}.png"), tops, 4)
    sheet(os.path.join(out, f"ships_{model}.png"), threes, 4)
    return labels


def matrix_sheet(tmp, out, res, samples):
    base = params.load(os.path.join(ROOT, "presets", "miner_m.json")).params
    base = dict(base, spread=0, engines=dict(base["engines"], count=2, size=2.6))
    paths = []
    for tail in ("flat", "taper", "flare", "outboard"):
        for i in range(len(engine_designs.DESIGNS)):
            ship = kit.build(base, plan="mono", tail=tail, mid="straight", nose="blunt", engine_design=i)
            paths.append(render(ship, os.path.join(tmp, f"m_{tail}_{i}.png"), "rear", res, samples))
    sheet(os.path.join(out, "matrix.png"), paths, len(engine_designs.DESIGNS))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "kit"))
    ap.add_argument("--quick", action="store_true", help="tiny renders for a smoke test")
    args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    os.makedirs(args.out, exist_ok=True)
    global RES, SAMPLES
    if args.quick:
        RES, SAMPLES = (160, 90), 4
    res, samples = RES, SAMPLES
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with tempfile.TemporaryDirectory() as tmp:
        part_sheet(tmp, args.out, "engines", engine_designs.build, len(engine_designs.DESIGNS), (0, -1, 0), "rear", 4.6)
        part_sheet(tmp, args.out, "rigs", rig_designs.build, len(rig_designs.DESIGNS), (0, 1, 0), "three_quarter", 4.4)
        part_sheet(tmp, args.out, "modules", module_designs.build, len(module_designs.DESIGNS), (1, 0, 0),
                   "three_quarter", 4.4)
        labels = []
        for model, frame in (("miner_m", 40), ("hauler_m", 40), ("tanker_m", 46), ("liner_m", 42)):
            labels += [f"{model} {line}" for line in model_sheets(tmp, args.out, model, range(1, 9), res, samples, frame)]
        matrix_sheet(tmp, args.out, (240, 135) if not args.quick else (120, 68), samples)
    with open(os.path.join(args.out, "README.md"), "w", encoding="utf-8") as f:
        f.write("# Kit prototype renders\n\nGenerated by `scripts/kit_demo.py`.\n\n")
        f.write("- `engines.png`: " + ", ".join(f"{i} {n}" for i, n in enumerate(engine_designs.NAMES)) + "\n")
        f.write("- `rigs.png`: " + ", ".join(f"{i} {n} ({rig_designs.KIND[n]})" for i, n in enumerate(rig_designs.NAMES)) + "\n")
        f.write("- `modules.png`: " + ", ".join(f"{i} {n} ({module_designs.KIND[n]})"
                                                for i, n in enumerate(module_designs.NAMES)) + "\n")
        f.write("- `conflicts.md`: collision report from `scripts/kit_conflicts.py`\n")
        f.write("- `matrix.png`: rows = tails flat, taper, flare, outboard; columns = engine designs 0-9\n")
        f.write("- `silhouettes_*.png` / `ships_*.png`: seeds 1-8, left to right, top to bottom:\n\n")
        f.writelines(f"  - {line}\n" for line in labels)
    print("\n".join(labels))


if __name__ == "__main__":
    main()
