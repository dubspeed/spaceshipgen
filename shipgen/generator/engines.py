"""Low-poly engines: hexagonal nacelles at the tail with a recessed, glowing nozzle.

Up to 3 engines sit in one row; more are split into two rows (top/bottom).
"""

from __future__ import annotations

import math

import bmesh
import bpy

from .hull import HullShape

SIDES = 6
TRIS_PER_ENGINE = 3 * 2 * SIDES + 2 * (SIDES - 2)  # 3 hexagonal bands + front cap + glow cap
EMBED = 0.6  # fraction of the nacelle length hidden inside the hull


def engine_layout(count: int, radius: float, z_center: float) -> list[tuple[float, float]]:
    """(x, z) of each engine axis."""
    rows = 1 if count <= 3 else 2
    per_row = [math.ceil(count / rows), count // rows] if rows == 2 else [count]
    spacing = 2.1 * radius
    out = []
    for r, n in enumerate(per_row):
        z = z_center if rows == 1 else z_center + (1.05 * radius if r == 0 else -1.05 * radius)
        for i in range(n):
            out.append(((i - (n - 1) / 2) * spacing, z))
    return out


def _ring(bm, x, y, z, radius):
    return [
        bm.verts.new((x + radius * math.cos(a), y, z + radius * math.sin(a)))
        for a in (2 * math.pi * k / SIDES for k in range(SIDES))
    ]


def _bridge(bm, a, b, material: int = 0):
    for k in range(SIDES):
        k2 = (k + 1) % SIDES
        bm.faces.new((a[k], a[k2], b[k2], b[k])).material_index = material


def build_engines_mesh(params: dict, hull: HullShape, count: int, name: str = "Ship_Engines"):
    ep = params["engines"]
    if count == 0:
        return None
    radius = 0.5 * ep["size"]
    length = min(2.2 * ep["size"], 0.45 * hull.length)
    tail = hull.section(0.0)
    y_back = hull.y(0.0) - (1.0 - EMBED) * length
    y_front = y_back + length

    bm = bmesh.new()
    for x, z in engine_layout(count, radius, tail.z_center):
        front = _ring(bm, x, y_front, z, radius * 0.85)
        back = _ring(bm, x, y_back, z, radius)
        lip = _ring(bm, x, y_back, z, radius * 0.72)
        recess = _ring(bm, x, y_back + 0.15 * length, z, radius * 0.72)
        bm.faces.new(front)
        _bridge(bm, front, back)
        _bridge(bm, back, lip)
        _bridge(bm, lip, recess)
        bm.faces.new(list(reversed(recess))).material_index = 1  # glow

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def build_engines(params: dict, hull: HullShape, collection, parent=None, count: int | None = None):
    """``count`` overrides ``engines.count`` (used to fit the triangle budget)."""
    count = params["engines"]["count"] if count is None else count
    mesh = build_engines_mesh(params, hull, count)
    if mesh is None:
        return None
    obj = bpy.data.objects.new("Ship_Engines", mesh)
    collection.objects.link(obj)
    obj.parent = parent
    return obj
