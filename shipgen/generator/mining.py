"""Mining rigs mounted on the nose: drill, laser emitters, claw arms, gas/ice scoop."""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

from . import shapes
from .hull import HullShape

# material indices on the mining object
METAL, GLOW = 0, 1


def rig_scale(params: dict, hull: HullShape) -> float:
    return hull.max_half_width * (0.5 + 0.9 * params["mining"]["size"])


def _mount_points(count: int, hw: float, top: float, bottom: float) -> list[tuple[float, float]]:
    """(x, z offset from the section centre) around the nose, mirror symmetric."""
    side = (hw * 0.85, 0.0)
    layouts = {
        1: [(0.0, top * 0.8)],
        2: [side, (-side[0], 0.0)],
        3: [(0.0, top * 0.8), (hw * 0.8, -bottom * 0.3), (-hw * 0.8, -bottom * 0.3)],
        4: [(hw * 0.7, top * 0.5), (-hw * 0.7, top * 0.5), (hw * 0.7, -bottom * 0.5), (-hw * 0.7, -bottom * 0.5)],
    }
    return layouts[count]


def build_mining_mesh(params: dict, hull: HullShape, name: str = "Ship_Mining"):
    mp = params["mining"]
    if mp["type"] == "none":
        return None
    s = rig_scale(params, hull)
    nose = hull.section(1.0)
    y0 = hull.y(1.0)
    zc = nose.z_center
    # a pointed nose has no face to mount on: use a ring a bit further back
    hw = nose.half_width if not hull.point_nose else hull.section(0.85).half_width
    top = nose.top if not hull.point_nose else hull.section(0.85).top
    bottom = nose.bottom if not hull.point_nose else hull.section(0.85).bottom
    hw, top, bottom = max(hw, 0.3 * s), max(top, 0.2 * s), max(bottom, 0.2 * s)
    fwd = Vector((0, 1, 0))

    bm = bmesh.new()
    if mp["type"] == "drill":
        shapes.loft(
            bm, (0.0, y0 - 0.3 * s, zc), fwd,
            [(0.0, 0.75 * s), (0.5 * s, 0.75 * s), (0.5 * s, 0.6 * s), (1.2 * s, 0.38 * s)],
            sides=8, tip=2.1 * s,
        )
    elif mp["type"] == "laser":
        for x, dz in _mount_points(mp["count"], hw, top, bottom):
            z = zc + dz
            shapes.beam(bm, (x, y0 - 0.4 * s, z), (x, y0 + 0.7 * s, z), 0.18 * s)
            shapes.loft(
                bm, (x, y0 + 0.65 * s, z), fwd,
                [(0.0, 0.16 * s), (0.35 * s, 0.16 * s), (0.35 * s, 0.11 * s), (0.25 * s, 0.11 * s)],
                sides=6, cap_materials=(None, GLOW),
            )
    elif mp["type"] == "claw":
        count = max(mp["count"], 2)
        layouts = {2: [0, 180], 3: [0, 180, 270], 4: [0, 90, 180, 270]}
        for angle in layouts[count]:
            a = math.radians(angle)
            out = Vector((math.cos(a), 0.0, math.sin(a)))
            radial = hw if abs(out.x) > 0.5 else (top if out.z > 0 else bottom)
            p0 = Vector((0.0, y0 - 0.2 * s, zc)) + out * radial * 0.8
            p1 = p0 + out * 0.6 * s + fwd * 0.8 * s
            p2 = p1 - out * 0.35 * s + fwd * 0.9 * s
            p3 = p2 - out * 0.45 * s + fwd * 0.15 * s
            up = Vector((0, 0, 1)) if abs(out.z) < 0.5 else Vector((1, 0, 0))
            shapes.beam(bm, p0, p1, 0.22 * s, material=METAL, up=up)
            shapes.beam(bm, p1, p2, 0.18 * s, material=METAL, up=up)
            shapes.beam(bm, p2, p3, 0.14 * s, 0.3 * s, material=METAL, up=up)
    else:  # scoop: wide intake funnel with a glowing throat
        rings = shapes.loft(
            bm, (0.0, y0 - 0.3 * s, zc), fwd,
            [(0.0, 0.6 * s), (0.4 * s, 0.7 * s), (1.5 * s, 1.5 * s)],
            sides=8, cap_materials=(None, GLOW),
        )
        # recess the intake: replace the flat front cap by an inner funnel
        front = rings[-1]
        cap_face = next(f for f in bm.faces if set(f.verts) == set(front))
        bm.faces.remove(cap_face)
        inner = shapes.ring(bm, (0.0, y0 + 1.2 * s - 0.3 * s, zc), 1.25 * s, 8, fwd)
        throat = shapes.ring(bm, (0.0, y0 + 0.5 * s - 0.3 * s, zc), 0.6 * s, 8, fwd)
        shapes.bridge(bm, front, inner, METAL)
        shapes.bridge(bm, inner, throat, GLOW)
        shapes.cap(bm, throat, GLOW)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def build_mining(params: dict, hull: HullShape, collection, parent=None):
    mesh = build_mining_mesh(params, hull)
    if mesh is None:
        return None
    obj = bpy.data.objects.new("Ship_Mining", mesh)
    collection.objects.link(obj)
    obj.parent = parent
    obj["shipgen_role"] = "mining"
    obj["shipgen_mining_type"] = params["mining"]["type"]
    return obj
