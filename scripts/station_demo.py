"""Station sheets into docs/stations/ (or --out), the wreck sheet into docs/wrecks/ (or --wreck-out).

    .venv/bin/python scripts/station_demo.py [--only modules,stations,docked,wrecks]

modules.png   every module design of the kit, one per tile
stations.png  roles (rows: outpost, mining, trade) x sizes (columns: small, medium, large)
stations_massive.png  the same with build = massive (3x3x3 cores, thick modules, heavy docks)
stations_massive_top.png  large massive stations from above (flat spine, the game's view)
docked.png    stations with shop ships lying at their berths (scale check; top truss, bottom massive)
wrecks.png    wrecks of shop models (rows: miner_m, hauler_m, hauler_l; damage and breaks rise to the right)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import bpy  # noqa: E402,F401  (must come before bmesh)

from shipgen import export, generator, stations, wrecks  # noqa: E402
from shipgen.generator import Ship  # noqa: E402

RES, SAMPLES = (480, 360), 16
SHIP_FOR_BERTH = {"S": "hauler_s", "M": "miner_m", "L": "hauler_l"}


class View:
    """What export.render_preview needs: the objects to frame."""

    bounds = Ship.bounds

    def __init__(self, parts):
        self.parts = parts


def sheet(out, paths, cols):
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "contact_sheet.py"), out, "--cols", str(cols),
                    *paths], check=True, capture_output=True)
    print("wrote", out)


def render(view_obj, path, view="three_quarter", res=RES):
    return export.render_preview(view_obj, path, view=view, resolution=res, samples=SAMPLES)


def preset(name):
    with open(os.path.join(ROOT, "presets", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def dock_ships(station, seed=1):
    """Copies of shop ships at every berth (look only: shared meshes in a demo collection)."""
    coll = bpy.data.collections.new("Demo_Docked")
    bpy.context.scene.collection.children.link(coll)
    bpy.context.view_layer.update()
    berths = [(e.matrix_world.copy(), e["station_berth"]["size"]) for e in station.empties if "station_berth" in e]
    shapes = {}
    for size in sorted({s for _, s in berths}):
        ship = generator.generate(dict(preset(SHIP_FOR_BERTH[size]), seed=seed))
        shapes[size] = [(o.data.copy(), o.matrix_basis.copy()) for o in ship.parts]
    generator.clear()  # the copies keep the meshes and materials alive
    out = []
    for i, (matrix, size) in enumerate(berths):
        anchor = bpy.data.objects.new(f"Docked_{i}", None)
        coll.objects.link(anchor)
        anchor.matrix_world = matrix
        for k, (data, basis) in enumerate(shapes[size]):
            obj = bpy.data.objects.new(f"Docked_{i}_{k}", data)
            coll.objects.link(obj)
            obj.parent = anchor
            obj.matrix_basis = basis
            out.append(obj)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "stations"))
    ap.add_argument("--wreck-out", default=os.path.join(ROOT, "docs", "wrecks"))
    ap.add_argument("--only", default="modules,stations,docked,wrecks")
    args = ap.parse_args()
    only = set(args.only.split(","))
    os.makedirs(args.out, exist_ok=True)
    tmp = tempfile.mkdtemp()
    bpy.ops.wm.read_factory_settings(use_empty=True)

    if "modules" in only:
        kit = stations.build_kit({})
        paths = []
        for obj in kit.parts:
            for o in kit.parts:
                o.hide_render = o is not obj
            paths.append(render(View([obj]), os.path.join(tmp, f"{obj.name}.png"), res=(320, 240)))
        sheet(os.path.join(args.out, "modules.png"), paths, 6)

    if "stations" in only:
        for build, out in (("truss", "stations.png"), ("massive", "stations_massive.png")):
            paths = []
            for role in ("outpost", "mining", "trade"):
                for size, seed in (("small", 1), ("medium", 2), ("large", 3)):
                    st = stations.generate({"role": role, "size": size, "seed": seed, "build": build,
                                            "symmetry": "two" if seed == 2 else "four"})
                    print(build, role, size, st.stats["berths"], st.stats["modules"])
                    paths.append(render(st, os.path.join(tmp, f"{build}_{role}_{size}.png")))
            sheet(os.path.join(args.out, out), paths, 3)
            if build == "massive":  # flat: the game's top-down view
                tops = []
                for role in ("outpost", "mining", "trade"):
                    st = stations.generate({"role": role, "size": "large", "seed": 3, "build": build})
                    tops.append(render(st, os.path.join(tmp, f"top_{role}.png"), view="top"))
                sheet(os.path.join(args.out, "stations_massive_top.png"), tops, 3)

    if "docked" in only:
        paths = []
        for params in ({"role": "mining", "size": "medium", "seed": 2, "symmetry": "two"},
                       {"role": "trade", "size": "small", "seed": 4, "symmetry": "four"},
                       {"role": "mining", "size": "medium", "seed": 2, "symmetry": "two", "build": "massive"},
                       {"role": "trade", "size": "small", "seed": 4, "symmetry": "four", "build": "massive"}):
            st = stations.generate(params)
            ships = dock_ships(st)
            name = f"docked_{params['role']}_{params.get('build', 'truss')}.png"
            paths.append(render(View(st.parts + ships), os.path.join(tmp, name), res=(960, 640)))
            bpy.data.collections.remove(bpy.data.collections["Demo_Docked"])
        sheet(os.path.join(args.out, "docked.png"), paths, 2)

    if "wrecks" in only:
        generator.clear(stations.COLLECTION)
        paths = []
        for name, seed in (("miner_m", 1), ("hauler_m", 2), ("hauler_l", 3)):
            for damage, breaks in ((0.3, 0), (0.6, 1), (0.9, 2)):
                w = wrecks.generate({"seed": seed, "damage": damage, "breaks": breaks}, preset(name))
                print(name, damage, w.stats["parts"], w.warnings)
                paths.append(render(View(w.segments), os.path.join(tmp, f"wreck_{name}_{damage}.png")))
        os.makedirs(args.wreck_out, exist_ok=True)
        sheet(os.path.join(args.wreck_out, "wrecks.png"), paths, 3)


if __name__ == "__main__":
    main()
