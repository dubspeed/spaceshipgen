"""Hull surface detail: belt grooves, side panels and a dorsal trench.

- **grooves**: belt grooves around the body, made by inserting stations into the loft
  (no mesh surgery: the loft stays as clean as before);
- **panels**: the flanks are cut into short panels and some are inset and raised
  (armour plates) - bmesh only, sides only (the roof is busy with modules and greebles);
- **trench**: a dorsal trench cut with Blender's Boolean modifier (MANIFOLD solver where
  available, else EXACT), only along stretches of the roof without modules.

Which class gets what: ``CLASS_DETAIL``; ``kit.detail`` (0..1) scales it, 0 = plain hull.
All of it is looks only: hull stats come from the reference hull. Everything is mirror
symmetric (panel choices are made per mirrored pair).
"""

from __future__ import annotations

import random

import bmesh
import bpy
from mathutils import Vector

from ..generator.hull import Station
from .hull_kit import HullLayout, section_at

CLASS_DETAIL = {
    "freighter": {"grooves", "panels", "trench"},
    "corvette": {"grooves", "panels", "trench"},
    "miner": {"grooves", "panels"},
    "shuttle": {"grooves"},
    "fighter": {"grooves"},
    "interceptor": {"grooves"},
}
MIN_TRIS = {"grooves": 2000, "panels": 4000, "trench": 3000}  # skip a detail on tighter budgets
GROOVE_DEPTH = 0.9  # section scale at the bottom of a groove
PANEL_HEIGHT = 0.06  # raised panels stand out by this x beam
PANEL_SHARE = 0.6  # share of flank panels raised at kit.detail = 1
TRENCH_MIN = 0.12  # shortest trench stretch, x length


def details_for(cls: str, amount: float, max_tris: int) -> set[str]:
    if amount <= 0:
        return set()
    return {d for d in CLASS_DETAIL.get(cls, ()) if max_tris >= MIN_TRIS[d]}


# ---------------------------------------------------------------- grooves (loft stations)

def grooved(layout: HullLayout, length: float, salt: str) -> tuple[HullLayout, list[tuple[float, float]]]:
    """Copy of ``layout`` with belt grooves (scaled-in stations with steep walls) in the free
    stretches of the mid section, plus the grooves' (y0, y1). Grooves never straddle an
    existing station, so hard steps stay untouched. ``salt`` seeds the choices (the same for
    both bodies of a twin hull, so they mirror each other)."""
    y_a, y_b = layout.y_mid
    width, wall = 0.035 * length, 0.006 * length
    taken = sorted((-0.5 + st.t) * length for st in layout.stations)
    free = [(max(a, y_a) + wall, min(b, y_b) - wall) for a, b in zip(taken, taken[1:])
            if min(b, y_b) - max(a, y_a) > width + 2 * wall]
    count = random.Random(f"{salt}:grooves").choice((1, 2, 2, 3))
    cuts = []
    for a, b in free:  # spread the grooves evenly over every free stretch
        k = max(1, min(count, int((b - a) / (4 * width))))
        for i in range(k):
            c = a + (b - a) * (i + 1) / (k + 1)
            cuts.append((c - 0.5 * width, c + 0.5 * width))

    def at(y, k):
        st = section_at(layout, y, length)
        return Station((y + 0.5 * length) / length, st.half_width * k, st.top * k, st.bottom * k, 0.0, 0.0)

    sts = list(layout.stations)
    for y0, y1 in cuts:
        sts += [at(y0, 1.0), at(y0 + wall, GROOVE_DEPTH), at(y1 - wall, GROOVE_DEPTH), at(y1, 1.0)]
    sts.sort(key=lambda s: s.t)
    out = HullLayout(sts, layout.y_tail, layout.y_mid, layout.y_front, layout.point_nose, layout.x_offset)
    return out, cuts


# ---------------------------------------------------------------- side panels (bmesh)

def panels(bm, y_range, length: float, beam: float, salt: str, share: float) -> None:
    """Cut the flanks into short panels along Y and raise a ``share`` of them (inset + push
    out along the face normal). Each choice depends only on the panel's mirrored position
    (``salt`` + |x|, y, z), so mirrored panels - also across twin hulls - always agree."""
    y_a, y_b = y_range
    step = min(0.05 * length, 1.2 * beam)  # short panels, also on long hulls
    n = max(int((y_b - y_a) / step), 1)
    rings = {round(v.co.y, 4) for v in bm.verts}
    for i in range(1, n):
        y = y_a + (y_b - y_a) * i / n
        if any(abs(y - r) < 0.4 * step for r in rings):
            continue  # a cut on (or next to) an existing ring would leave slivers
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, y, 0),
                               plane_no=(0, 1, 0))
    min_edge = 0.2 * beam
    pairs: dict[tuple, list] = {}
    for f in bm.faces:
        c, nrm = f.calc_center_median(), f.normal
        if not (y_a + 0.01 * length < c.y < y_b - 0.01 * length):
            continue
        if abs(nrm.x) < 0.7 or abs(nrm.z) > 0.6:
            continue  # flanks only
        if len(f.verts) != 4 or min(e.calc_length() for e in f.edges) < min_edge:
            continue  # thin slivers would inset into degenerate faces
        pairs.setdefault((round(c.y, 2), round(abs(c.x), 2), round(c.z, 2)), []).append(f)
    for key in sorted(pairs):
        if random.Random(f"{salt}:panel:{key}").random() > share:
            continue
        for f in pairs[key]:
            inset = 0.15 * min(e.calc_length() for e in f.edges)
            bmesh.ops.inset_individual(bm, faces=[f], thickness=inset, depth=0.0, use_even_offset=True)
            nrm = f.normal.copy()
            for v in f.verts:
                v.co += nrm * PANEL_HEIGHT * beam


def inflated(layout: HullLayout, length: float, by: float) -> HullLayout:
    """Copy of ``layout`` grown by ``by`` in width and height over the mid section, so collision
    shapes lofted from it cover the raised panels."""
    y_a, y_b = layout.y_mid
    eps = 1e-6 * length
    sts = []
    for st in layout.stations:
        if y_a - eps <= (-0.5 + st.t) * length <= y_b + eps:
            st = Station(st.t, st.half_width + by, st.top + by, st.bottom + by, st.z_center, st.asym)
        sts.append(st)
    return HullLayout(sts, layout.y_tail, layout.y_mid, layout.y_front, layout.point_nose, layout.x_offset)


# ---------------------------------------------------------------- dorsal trench (boolean)

def trench_stretches(lay: HullLayout, length: float, occupied) -> list[tuple[float, float]]:
    """Stretches of the mid roof not covered by ``occupied`` (y0, y1) ranges, long enough."""
    y_a, y_b = lay.y_mid
    margin = 0.03 * length
    edges = [(y_a, y_a)] + sorted(occupied) + [(y_b, y_b)]
    out = []
    for (_, end), (start, _) in zip(edges, edges[1:]):
        a, b = max(end, y_a) + margin, min(start, y_b) - margin
        if b - a >= TRENCH_MIN * length:
            out.append((a, b))
    return out


def trench_cutter(lay: HullLayout, length: float, height: float, stretches):
    """Box cutters (one bmesh) for the trench stretches of one body, and their (lo, hi) boxes."""
    cbm = bmesh.new()
    boxes = []
    for y0, y1 in stretches:
        sts = [section_at(lay, y, length) for y in (y0, 0.5 * (y0 + y1), y1)]
        w = 0.28 * min(st.half_width for st in sts)
        top = max(st.top for st in sts)
        lo = Vector((lay.x_offset - w, y0, top - 0.15 * height))
        hi = Vector((lay.x_offset + w, y1, top + 0.15 * height))
        _box(cbm, lo, hi)
        boxes.append((lo, hi))
    return cbm, boxes


def _box(bm, lo, hi):
    vs = [bm.verts.new((x, y, z)) for z in (lo.z, hi.z) for x, y in
          ((lo.x, lo.y), (hi.x, lo.y), (hi.x, hi.y), (lo.x, hi.y))]
    for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([vs[i] for i in q])


def boolean_difference(bm, cutter_bm) -> None:
    """bm -= cutter_bm, in place, via Blender's Boolean modifier (no bpy.ops). ``bm`` must be
    one clean closed shell: with overlapping shells the solver returns it unchanged."""
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
    ev = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    result = ev.to_mesh()
    bm.clear()
    bm.from_mesh(result)
    ev.to_mesh_clear()
    for ob in objs:
        me = ob.data
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(me)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges[:], dist=1e-5)
