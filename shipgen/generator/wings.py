"""Low-poly wings: each wing is a lofted diamond (4-vertex) airfoil, root to tip.

``wings.count`` sets the layout: pairs are mirrored left/right and fanned out
in dihedral (2 = flat pair, 4 = X-wing); an odd count adds a vertical tail fin.
``wings.span`` is the total tip-to-tip span.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import bmesh
import bpy

from .hull import HullShape


@dataclass(frozen=True)
class WingType:
    root_chord: float  # relative to hull length
    tip_ratio: float  # tip chord / root chord
    root_t: float  # position of the root's mid chord (0 = tail, 1 = nose)
    sweep_scale: float  # multiplier applied to sweep_deg


WING_TYPES = {
    "delta": WingType(root_chord=0.5, tip_ratio=0.08, root_t=0.35, sweep_scale=1.0),
    "swept": WingType(root_chord=0.3, tip_ratio=0.4, root_t=0.38, sweep_scale=1.0),
    "straight": WingType(root_chord=0.2, tip_ratio=0.85, root_t=0.42, sweep_scale=0.15),
    "forward_swept": WingType(root_chord=0.26, tip_ratio=0.5, root_t=0.3, sweep_scale=-0.8),
}

THICKNESS = 0.07  # airfoil thickness relative to chord
ROOT_EMBED = 0.7  # root sits this far out of the hull's half width (hides the seam)


def _airfoil(bm, le_y: float, chord: float, x: float, z: float, thick: float, vertical: bool):
    """Diamond section: leading edge, top, trailing edge, bottom."""
    mid = le_y - 0.4 * chord
    if vertical:  # fin: span along +Z, thickness along X
        pts = ((0.0, le_y, z), (thick, mid, z), (0.0, le_y - chord, z), (-thick, mid, z))
    else:
        pts = ((x, le_y, z), (x, mid, z + thick), (x, le_y - chord, z), (x, mid, z - thick))
    return [bm.verts.new(p) for p in pts]


def _loft(bm, root, tip) -> None:
    for j in range(4):
        j2 = (j + 1) % 4
        bm.faces.new((root[j], root[j2], tip[j2], tip[j]))
    bm.faces.new(list(reversed(root)))
    bm.faces.new(tip)


def build_wings_mesh(params: dict, hull: HullShape, name: str = "Ship_Wings"):
    wp = params["wings"]
    if wp["type"] == "none" or wp["count"] == 0:
        return None
    rng = random.Random(f"{params['seed']}:wings")
    wt = WING_TYPES[wp["type"]]
    length = hull.length

    root_t = min(max(wt.root_t + rng.uniform(-0.05, 0.05), 0.15), 0.8)
    sec = hull.section(root_t)
    root_chord = wt.root_chord * length
    tip_chord = max(root_chord * wt.tip_ratio, 0.02 * length)
    root_le = hull.y(root_t) + 0.5 * root_chord
    root_x = sec.half_width * ROOT_EMBED
    semi = 0.5 * wp["span"] - root_x
    sweep = math.radians(wp["sweep_deg"] * wt.sweep_scale)

    tip_le = root_le - math.tan(sweep) * semi
    if wp["type"] == "delta":  # keep the trailing edge straight or swept back
        tip_le = min(tip_le, root_le - (root_chord - tip_chord))

    bm = bmesh.new()
    pairs, fin = divmod(wp["count"], 2)
    if semi > 0.05 * length:
        if pairs == 1:
            dihedrals = [rng.uniform(-4.0, 8.0)]
        else:
            dihedrals = [-22.0 + 44.0 * i / (pairs - 1) for i in range(pairs)]
        for i, dihedral in enumerate(dihedrals):
            d = math.radians(dihedral)
            z_root = sec.z_center - 0.15 * sec.bottom + math.copysign(0.35, dihedral) * sec.top * (pairs > 1)
            for side in (1.0, -1.0):
                root = _airfoil(bm, root_le, root_chord, side * root_x, z_root, THICKNESS * root_chord, False)
                tip = _airfoil(
                    bm, tip_le, tip_chord, side * (root_x + semi * math.cos(d)),
                    z_root + semi * math.sin(d), THICKNESS * tip_chord, False,
                )
                _loft(bm, root, tip)
    if fin:
        tail_t = 0.12
        tail = hull.section(tail_t)
        fin_chord = 0.6 * root_chord if wp["type"] == "delta" else root_chord
        fin_le = hull.y(tail_t) + 0.6 * fin_chord
        fin_height = max(0.35 * wp["span"] * 0.5, 0.15 * length)
        z0 = tail.z_center + tail.top * 0.7
        root = _airfoil(bm, fin_le, fin_chord, 0.0, z0, THICKNESS * fin_chord, True)
        tip = _airfoil(
            bm, fin_le - math.tan(math.radians(40)) * fin_height, fin_chord * 0.4, 0.0,
            z0 + fin_height, THICKNESS * fin_chord * 0.4, True,
        )
        _loft(bm, root, tip)

    if not bm.faces:
        bm.free()
        return None
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def build_wings(params: dict, hull: HullShape, collection, parent=None):
    mesh = build_wings_mesh(params, hull)
    if mesh is None:
        return None
    obj = bpy.data.objects.new("Ship_Wings", mesh)
    collection.objects.link(obj)
    obj.parent = parent
    return obj
