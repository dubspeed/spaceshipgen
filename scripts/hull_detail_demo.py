"""Hull surface detail before / after: per model one sheet per view, rows = seeds,
left kit.detail = 0 (plain), right kit.detail = 1.

    .venv/bin/python scripts/hull_detail_demo.py [--out docs/hull_detail] [--models miner_m,...]

Also prints a quality line per ship: closed mesh, degenerate faces, hull tris.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import bpy  # noqa: E402  (must come before bmesh)
import bmesh  # noqa: E402

from shipgen import export, kit, params  # noqa: E402

AMOUNTS = (0.0, 1.0)
SEEDS = (1, 2, 3)
RES, SAMPLES = (640, 400), 16


def quality(ship) -> str:
    hull = next(o for o in ship.parts if o["shipgen_role"] == "hull")
    bm = bmesh.new()
    bm.from_mesh(hull.data)
    open_edges = sum(not e.is_manifold for e in bm.edges)
    degenerate = sum(f.calc_area() <= 1e-9 for f in bm.faces)
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    bm.free()
    return f"open_edges={open_edges} degenerate={degenerate} hull_tris={tris}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "hull_detail"))
    ap.add_argument("--models", default="hauler_m,miner_m,corvette,fighter")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    tmp = tempfile.mkdtemp()
    for model in args.models.split(","):
        base = params.load(os.path.join(ROOT, "presets", f"{model}.json")).params
        frame = 1.1 * base["hull"]["length"]
        views = {"three_quarter": [], "top": []}
        for seed in SEEDS:
            for amount in AMOUNTS:
                t0 = time.time()
                ship = kit.build(dict(base, seed=seed), detail=amount)
                print(f"{model:10} seed={seed} detail={amount} {ship.design.label():28} {quality(ship)} "
                      f"{time.time() - t0:.2f}s warnings={ship.warnings}")
                for view in views:
                    path = os.path.join(tmp, f"{model}_{seed}_{amount}_{view}.png")
                    export.render_preview(ship, path, view=view, resolution=RES, samples=SAMPLES, frame=frame)
                    views[view].append(path)
        for view, paths in views.items():
            out = os.path.join(args.out, f"{model}_{view}.png")
            subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "contact_sheet.py"), out, "--cols",
                            str(len(AMOUNTS)), *paths], check=True, capture_output=True)
            print("wrote", out)


if __name__ == "__main__":
    main()
