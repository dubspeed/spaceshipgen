"""Cargo modules bolted onto the hull: containers, ore hoppers, tanks, habitats.

Modules fill slots in the class's cargo zone. Slots are filled lane by lane so
the ship stays mirror symmetric: first a left/right pair along the hull sides,
then a row on top, then an outer side pair, then a second layer on top.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import bmesh
import bpy

from . import shapes
from .hull import HullShape

# Lane fill orders and column orders the seed picks from (look only: same modules, same volume).
LANE_ORDERS = (
    (("side", 1), ("top", 1), ("side", 2), ("top", 2)),
    (("top", 1), ("side", 1), ("top", 2), ("side", 2)),
)
COLUMN_ORDERS = ("centre", "front", "back")
EMBED = 0.1  # fraction of a module sunk into the hull / neighbour (no visible gaps)


@dataclass(frozen=True)
class ModuleType:
    width: float  # x, relative to the module base size
    height: float  # z
    length: float  # y


MODULE_TYPES = {
    "containers": ModuleType(1.0, 1.0, 2.0),
    "hoppers": ModuleType(1.0, 0.9, 1.4),
    "tanks": ModuleType(1.0, 1.0, 2.6),
    "habitat": ModuleType(1.1, 0.8, 1.8),
}


def module_base(hull: HullShape, size: float) -> float:
    return hull.max_half_width * (0.35 + 0.5 * size)


def slots(params: dict, hull: HullShape) -> list[tuple[float, float, float]]:
    """Centres (x, y, z) of all modules, in fill order, already cut to the module count."""
    cp = params["cargo"]
    if cp["type"] == "none" or cp["modules"] == 0:
        return []
    mt = MODULE_TYPES[cp["type"]]
    base = module_base(hull, cp["size"])
    w, h, length = mt.width * base, mt.height * base, mt.length * base
    t0, t1 = hull.profile.cargo_zone
    zone = (t1 - t0) * hull.length
    columns = max(int(zone // (length * 1.08)), 1)
    length = min(length, zone)
    pitch = zone / columns
    ys = [hull.y(t0) + pitch * (i + 0.5) for i in range(columns)]
    rng = random.Random(f"{params['seed']}:cargo_layout")
    lanes = rng.choice(LANE_ORDERS)
    order = rng.choice(COLUMN_ORDERS)
    centre = hull.y(0.5 * (t0 + t1))
    ys.sort(key={"centre": lambda y: abs(y - centre), "front": lambda y: -y, "back": lambda y: y}[order])

    def section_at(y):
        ts = [(yy / hull.length) + 0.5 for yy in (y - 0.5 * length, y, y + 0.5 * length)]
        secs = [hull.section(min(max(t, 0.0), 1.0)) for t in ts]
        return max(s.half_width for s in secs), max(s.top for s in secs), secs[1].z_center

    remaining = cp["modules"]
    out = []
    for kind, tier in lanes:
        for y in ys:
            hw, top, zc = section_at(y)
            if kind == "side" and remaining >= 2:
                x = hw + (tier - 0.5 - EMBED) * w
                out += [(x, y, zc), (-x, y, zc)]
                remaining -= 2
            elif kind == "top" and remaining >= 1:
                out.append((0.0, y, zc + top + (tier - 0.5 - EMBED) * h))
                remaining -= 1
    return out


def build_cargo_mesh(params: dict, hull: HullShape, name: str = "Ship_Cargo"):
    cp = params["cargo"]
    centres = slots(params, hull)
    if not centres:
        return None, 0
    rng = random.Random(f"{params['seed']}:cargo")
    mt = MODULE_TYPES[cp["type"]]
    base = module_base(hull, cp["size"])
    w, h = mt.width * base, mt.height * base
    t0, t1 = hull.profile.cargo_zone
    zone = (t1 - t0) * hull.length
    length = min(mt.length * base, zone)

    # one colour per mirrored pair, so symmetry holds
    colours = {}
    bm = bmesh.new()
    for x, y, z in centres:
        mat = colours.setdefault((abs(round(x, 4)), round(y, 4), round(z, 4)), rng.choice((0, 0, 1)))
        if cp["type"] == "containers":
            shapes.box(bm, (x, y, z), (w * 0.96, length * 0.96, h * 0.96), material=mat)
        elif cp["type"] == "hoppers":
            shapes.box(bm, (x, y, z), (w, length, h), material=0, bottom_scale=0.6)
        elif cp["type"] == "tanks":
            r = 0.5 * w
            shapes.loft(
                bm, (x, y - 0.5 * length, z), (0, 1, 0),
                [(0.0, 0.55 * r), (0.15 * length, r), (0.85 * length, r), (length, 0.55 * r)], sides=8,
            )
        else:  # habitat: hexagonal drum with a glowing window band
            r = 0.5 * w
            shapes.loft(
                bm, (x, y - 0.5 * length, z), (0, 1, 0),
                [(0.0, r), (0.4 * length, r)], sides=6,
            )
            shapes.loft(
                bm, (x, y - 0.1 * length, z), (0, 1, 0),
                [(0.0, r * 0.92), (0.2 * length, r * 0.92)], sides=6, material=2,
            )
            shapes.loft(
                bm, (x, y + 0.1 * length, z), (0, 1, 0),
                [(0.0, r), (0.4 * length, r)], sides=6,
            )
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh, len(centres)


def build_cargo(params: dict, hull: HullShape, collection, parent=None):
    """Returns (object or None, number of modules placed)."""
    mesh, placed = build_cargo_mesh(params, hull)
    if mesh is None:
        return None, 0
    obj = bpy.data.objects.new("Ship_Cargo", mesh)
    collection.objects.link(obj)
    obj.parent = parent
    obj["shipgen_role"] = "cargo"
    obj["shipgen_cargo_type"] = params["cargo"]["type"]
    return obj, placed

