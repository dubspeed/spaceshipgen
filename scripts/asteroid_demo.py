"""Asteroid sheets (prototype) into docs/asteroids/ (or --out).

    .venv/bin/python scripts/asteroid_demo.py

types.png     composition (rows: ore, metal, ice) x shape (columns: round, elongated, binary)
levels.png    one asteroid exploded level by level: whole, level 1, level 2, level 3
scale.png     a 24 m ore asteroid next to the miner_m (26 m) at the same scale
"""

import argparse
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import bpy  # noqa: E402,F401  (must come before bmesh)
from mathutils import Vector  # noqa: E402

from shipgen import asteroids, export, generator, params  # noqa: E402
from shipgen.generator import Ship  # noqa: E402

RES, SAMPLES = (480, 360), 16


class View:
    """What export.render_preview needs: the objects to frame."""

    bounds = Ship.bounds

    def __init__(self, parts):
        self.parts = parts


def sheet(out, paths, cols):
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "contact_sheet.py"), out, "--cols", str(cols),
                    *paths], check=True, capture_output=True)
    print("wrote", out)


def render(view_obj, path, view="three_quarter"):
    return export.render_preview(view_obj, path, view=view, resolution=RES, samples=SAMPLES)


def explode(rock, level: int, amount: float):
    """Show the chunks of one level, pushed apart from the centre; returns them."""
    shown = []
    for c in rock.chunks:
        visible = c.level == level or (c.level < level and not c.children)
        c.obj.hide_viewport = c.obj.hide_render = not visible
        if visible:
            shown.append(c.obj)
    bpy.context.view_layer.update()
    centre = sum((o.matrix_world.translation for o in shown), Vector()) / len(shown)
    for o in shown:
        world = o.matrix_world.translation
        o.matrix_world.translation = world + (world - centre) * amount
    bpy.context.view_layer.update()
    return shown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "asteroids"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    tmp = tempfile.mkdtemp()

    paths = []
    for comp in asteroids.params.COMPOSITIONS:
        for shape in asteroids.params.SHAPES:
            rock = asteroids.generate({"composition": comp, "shape": shape, "size_m": 24, "seed": 5})
            print(comp, shape, rock.stats["chunks_per_level"], rock.stats["yield_m3"], rock.warnings)
            paths.append(render(rock, os.path.join(tmp, f"{comp}_{shape}.png")))
    sheet(os.path.join(args.out, "types.png"), paths, 3)

    paths = []
    for level, amount in ((1, 0.0), (1, 0.35), (2, 0.5), (3, 0.7)):
        rock = asteroids.generate({"composition": "ore", "shape": "round", "size_m": 30, "seed": 7})
        shown = explode(rock, level, amount)
        paths.append(render(View(shown), os.path.join(tmp, f"level_{level}_{amount}.png")))
    sheet(os.path.join(args.out, "levels.png"), paths, 4)

    rock = asteroids.generate({"composition": "ore", "shape": "round", "size_m": 24, "seed": 5})
    rock.root.location = (0, 0, 0)
    ship = generator.generate(params.load(os.path.join(ROOT, "presets", "miner_m.json")).params)
    ship.root.location = (-26, 0, 0)
    bpy.context.view_layer.update()
    paths = [render(View(rock.parts + ship.parts), os.path.join(tmp, f"scale_{v}.png"), v)
             for v in ("three_quarter", "top")]
    sheet(os.path.join(args.out, "scale.png"), paths, 2)


if __name__ == "__main__":
    main()
