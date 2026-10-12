"""Hull surface detail (prototype): grooves, panels and boolean cuts.

Three techniques, so they can be compared side by side:

- ``grooves``: belt grooves around the body, made by inserting stations into the loft
  (no mesh surgery at all: the loft stays as clean as before);
- ``panels_raised`` / ``panels_recessed``: big side and roof faces are cut into panels,
  some panels are inset and pushed out (armour plates) or in (recesses) - bmesh only;
- ``trench``, ``notches``, ``intakes``: boolean DIFFERENCE with box cutters (Blender's
  Boolean modifier, MANIFOLD solver where available, else EXACT).

All of it is looks only: hull stats come from the reference hull, so details never move them.
Everything is mirror symmetric (choices are made per mirrored pair).
"""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from ..generator.hull import Station
from .hull_kit import HullLayout, section_at

DETAILS = ("grooves", "panels_raised", "panels_recessed", "trench", "notches", "intakes")
BOOLEAN = {"trench", "notches", "intakes"}


# ---------------------------------------------------------------- grooves (loft stations)

def grooved(layout: HullLayout, length: float, rng: random.Random, depth: float = 0.9) -> HullLayout:
    """Copy of ``layout`` with 1-3 belt grooves in the mid section (scaled-in stations with steep
    walls). Grooves never straddle an existing station, so hard steps stay untouched."""
    y_a, y_b = layout.y_mid
    width, wall = 0.035 * length, 0.006 * length
    taken = sorted((-0.5 + st.t) * length for st in layout.stations)
    # free stretches of the mid section (between stations), each long enough for a groove
    free = [(max(a, y_a) + wall, min(b, y_b) - wall) for a, b in zip(taken, taken[1:])
            if min(b, y_b) - max(a, y_a) > width + 2 * wall]
    count = rng.choice((1, 2, 2, 3))
    cuts = []
    for a, b in free:  # spread the grooves evenly over every free stretch
        k = max(1, min(count, int((b - a) / (4 * width))))
        for i in range(k):
            c = a + (b - a) * (i + 1) / (k + 1)
            cuts.append((c - 0.5 * width, c + 0.5 * width))
    sts = list(layout.stations)
    for y0, y1 in cuts:
        def at(y, k):
            st = section_at(layout, y, length)
            return Station((y + 0.5 * length) / length, st.half_width * k, st.top * k, st.bottom * k, 0.0, 0.0)
        sts += [at(y0, 1.0), at(y0 + wall, depth), at(y1 - wall, depth), at(y1, 1.0)]
    sts.sort(key=lambda s: s.t)
    out = HullLayout(sts, layout.y_tail, layout.y_mid, layout.y_front, layout.point_nose, layout.x_offset)
    return out


# ---------------------------------------------------------------- panels (bmesh)

def panels(bm, y_range, length: float, beam: float, rng: random.Random, raised: bool, share: float = 0.6) -> None:
    """Cut the hull into panels along Y, then inset some big side / roof faces and push them
    out (``raised``) or in. Chosen per mirrored pair, so the hull stays symmetric."""
    y_a, y_b = y_range
    step = 0.08 * length
    n = max(int((y_b - y_a) / step), 1)
    rings = {round(v.co.y, 4) for v in bm.verts}
    for i in range(1, n):
        y = y_a + (y_b - y_a) * i / n
        if any(abs(y - r) < 0.02 * length for r in rings):
            continue  # a cut on (or next to) an existing ring would leave slivers
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, y, 0),
                               plane_no=(0, 1, 0))
    min_area = (0.25 * beam) ** 2
    candidates = {}
    for f in bm.faces:
        c, nrm = f.calc_center_median(), f.normal
        if not (y_a + 0.01 * length < c.y < y_b - 0.01 * length) or f.calc_area() < min_area:
            continue
        if len(f.verts) != 4 or min(e.calc_length() for e in f.edges) < 0.2 * beam:
            continue  # thin slivers and triangles would inset into degenerate faces
        if abs(nrm.x) < 0.8 and nrm.z < 0.8:
            continue  # only sides and roof
        key = (round(c.y, 2), round(abs(c.x), 2), round(c.z, 2))
        candidates.setdefault(key, []).append(f)
    depth = (0.06 if raised else -0.05) * beam
    for key in sorted(candidates):
        if rng.random() > share:
            continue
        for f in candidates[key]:
            dims = sorted(e.calc_length() for e in f.edges)
            inset = 0.15 * dims[0]
            res = bmesh.ops.inset_individual(bm, faces=[f], thickness=inset, depth=0.0, use_even_offset=True)
            del res
            nrm = f.normal.copy()
            for v in f.verts:
                v.co += nrm * depth


# ---------------------------------------------------------------- boolean cuts

def _box_cutter(bm, centre, size, rot=None):
    """Box cutter, optionally rotated (Matrix 3x3) about its centre."""
    sx, sy, sz = (0.5 * s for s in size)
    rot = rot or Matrix.Identity(3)
    vs = [bm.verts.new(Vector(centre) + rot @ Vector((x, y, z)))
          for z in (-sz, sz) for x, y in ((-sx, -sy), (sx, -sy), (sx, sy), (-sx, sy))]
    for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([vs[i] for i in q])


def cutters(details, lay: HullLayout, length: float, beam: float, height: float, rng: random.Random):
    """Box cutters for the boolean details of one mono body (mirrored pairs)."""
    cbm = bmesh.new()
    x0 = lay.x_offset
    y_a, y_b = lay.y_mid
    mid = section_at(lay, 0.5 * (y_a + y_b), length)
    if "trench" in details:  # dorsal trench along the mid section
        w = 0.28 * mid.half_width
        d = 0.18 * height
        _box_cutter(cbm, (x0, 0.5 * (y_a + y_b), mid.top), (2 * w, 0.85 * (y_b - y_a), 2 * d))
    if "notches" in details:  # V-notches into the shoulders, just behind the nose
        y = y_b + 0.02 * length
        st = section_at(lay, y, length)
        for s in (1, -1):
            rot = Matrix.Rotation(math.radians(45) * s, 3, "Y")
            _box_cutter(cbm, (x0 + s * st.half_width, y, st.top * 0.7), (0.35 * beam, 0.05 * length, 0.35 * beam), rot)
    if "intakes" in details:  # slots in the flanks of the tail
        y = lay.y_tail + 0.6 * (y_a - lay.y_tail)
        st = section_at(lay, y, length)
        for s in (1, -1):
            _box_cutter(cbm, (x0 + s * st.half_width, y, 0.1 * st.top),
                        (0.3 * st.half_width, 0.6 * (y_a - lay.y_tail), 0.35 * height))
    return cbm


def boolean_difference(bm, cutter_bm) -> None:
    """bm -= cutter_bm, in place, via Blender's Boolean modifier (no bpy.ops)."""
    if not cutter_bm.faces:
        cutter_bm.free()
        return
    scene = bpy.context.scene
    objs = []
    for name, src in (("_detail_target", bm), ("_detail_cutter", cutter_bm)):
        me = bpy.data.meshes.new(name)
        src.to_mesh(me)
        ob = bpy.data.objects.new(name, me)
        scene.collection.objects.link(ob)
        objs.append(ob)
    cutter_bm.free()
    target, cutter = objs
    mod = target.modifiers.new("cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    solvers = mod.bl_rna.properties["solver"].enum_items.keys()
    mod.solver = "MANIFOLD" if "MANIFOLD" in solvers else "EXACT"
    dg = bpy.context.evaluated_depsgraph_get()
    ev = target.evaluated_get(dg)
    result = ev.to_mesh()
    bm.clear()
    bm.from_mesh(result)
    ev.to_mesh_clear()
    for ob in objs:
        me = ob.data
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(me)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges[:], dist=1e-5)
