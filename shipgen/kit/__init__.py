"""Parts kit, the default builder: hulls from designed sections, parts on sockets.

    ship = kit.build(params, plan="twin", engine_design=3)

See docs/parts_kit.md for the concept. Uses the main params schema; the kit choices
(plan, tail, mid, nose, part designs) come from the seed unless given as arguments
or in ``params["kit"]``. Stages: ``_build_hull`` (bodies, add-ons, sockets) ->
``_place_parts`` -> collision resolver -> triangle budget -> greebles -> objects.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import bmesh
import bpy
from mathutils import Matrix, Vector

from .. import fx, meshutil
from .. import params as params_mod
from .. import stats
from ..generator import Ship, clear, materials, shapes, wings
from ..generator.hull import CLASS_PROFILES, Station
from . import collision, engine_designs, greeble_designs, hull_detail, module_designs, normalize, rig_designs
from .hull_kit import Design, HullLayout, Socket, layout_body, loft_body, section_at, RIDGE

COLLECTION = "ShipGen"
OUTBOARD_TRIGGER = 1.3  # requested engine radius / what fits the tail face


@dataclass
class KitShip(Ship):
    design: Design | None = None
    sockets: list[Socket] = field(default_factory=list)
    socket_objects: list = field(default_factory=list)
    fx_objects: list = field(default_factory=list)  # FX anchors (fx.py)
    colliders: list = field(default_factory=list)  # convex "-convcolonly" meshes for Godot
    engine_design: int = 0
    loadout: dict = field(default_factory=dict)
    conflicts: list = field(default_factory=list)  # collisions found before resolving
    instances: list = field(default_factory=list)
    obstacles: list = field(default_factory=list)

    @property
    def objects(self):
        return [self.root, *self.parts, *self.socket_objects, *self.fx_objects, *self.colliders]


# ---------------------------------------------------------------- hull pieces

def _grab(bm, fn, refs: list | None = None) -> list:
    """Run ``fn`` and return copies of the vertex positions it added to ``bm``
    (the vertices themselves are appended to ``refs`` if given)."""
    before = set(bm.verts)
    fn()
    new = [v for v in bm.verts if v not in before]
    if refs is not None:
        refs.extend(new)
    return [v.co.copy() for v in new]


def _mini_body(bm, x, y_back, y_front, w, top, bottom, chamfer, ridge, length, pointed=True):
    """Small lofted body (fork prong, sponson pod): wedge-ended on both sides."""
    y0 = -0.5 * length
    t = lambda y: (y - y0) / length  # noqa: E731
    span = y_front - y_back
    sts = [
        Station(t(y_back), w * 0.55, top * 0.7, bottom * 0.7, 0.0, 0.0),
        Station(t(y_back + 0.2 * span), w, top, bottom, 0.0, 0.0),
        Station(t(y_front - 0.3 * span), w, top, bottom, 0.0, 0.0),
        Station(t(y_front), 0.0 if pointed else w * 0.5, top * 0.3, bottom * 0.3, 0.0, 0.0),
    ]
    loft_body(bm, HullLayout(sts, y_back, (y_back, y_front), y_front, pointed, x_offset=x), length, chamfer, ridge)


def _engine_sockets(n, r_req, x_c, y, face: Station, prefer_outboard: bool) -> tuple[list[Socket], list, float]:
    """Sockets for n engines on a tail face; returns (sockets, pylons, radius actually used).

    Engines never overlap and never hang over the face: if the requested size does
    not fit, they move onto outboard pylons (even counts) or get smaller.
    """
    if n == 0:
        return [], [], 0.0
    w, h = face.half_width, face.top + face.bottom
    zc = (face.top - face.bottom) / 2
    rows = 1 if n <= 3 else 2
    per_row = math.ceil(n / rows)
    r_fit = 0.95 * min(w / per_row, h / (2 * rows))
    outboard = n % 2 == 0 and (prefer_outboard or r_req > OUTBOARD_TRIGGER * r_fit)
    normal = Vector((0, -1, 0))
    sockets, pylons = [], []
    if outboard:
        r = r_req
        pairs = n // 2
        for i in range(pairs):
            z = zc + (i - (pairs - 1) / 2) * 2.1 * r
            x = w + 1.15 * r
            for s in (1, -1):
                pos = Vector((x_c + s * x, y + 0.6 * r, z))
                sockets.append(Socket("engine", pos, normal, r))
                pylons.append((Vector((x_c + s * w * 0.6, y + 0.6 * r, z)), pos, r))
        return sockets, pylons, r
    r = min(r_req, r_fit)
    row_counts = [per_row, n - per_row] if rows == 2 else [n]
    for row, count in enumerate(row_counts):
        z = zc if rows == 1 else zc + (1 if row == 0 else -1) * (h / 4)
        for i in range(count):
            x = (i - (count - 1) / 2) * 2.05 * r
            sockets.append(Socket("engine", Vector((x_c + x, y, z)), normal, r))
    return sockets, pylons, r


def _side_sockets(layout: HullLayout, length: float, module: float, x_c: float, outer_only_sign=None):
    """Module sockets along the mid section's flat sides, as mirrored pairs."""
    y_a, y_b = layout.y_mid
    span = y_b - y_a
    cols = max(int(span // (2.2 * module)), 1)
    out = []
    for c in range(cols):
        y = y_a + span * (c + 0.5) / cols
        w = min(section_at(layout, yy, length).half_width for yy in (y - module, y, y + module))
        for s in (1, -1):
            if outer_only_sign is not None and s != outer_only_sign:
                continue
            out.append(Socket("side", Vector((x_c + s * w, y, 0.0)), Vector((s, 0, 0)), module))
    return out


def _top_sockets(layout: HullLayout, length: float, module: float, chamfer: float, ridge: float, single=False):
    """Roof sockets along the mid section: a mirrored pair of rows on the roof, or one row on
    the centre line of a twin hull (``single``; its twin provides the mirror)."""
    y_a, y_b = layout.y_mid
    span = y_b - y_a
    out = []
    probe = section_at(layout, 0.5 * (y_a + y_b), length)
    roof_w = probe.half_width * (1.0 - 0.7 * chamfer)  # half width of the flat roof
    m = min(module, (2.0 if single else 0.9) * roof_w * 0.9)
    if m < 0.25 * module:
        return out  # roof too narrow
    cols = max(int(span // (2.2 * m)), 1)
    for c in range(cols):
        y = y_a + span * (c + 0.5) / cols
        top = max(section_at(layout, yy, length).top for yy in (y - m, y, y + m))
        xs = (0.0,) if single else (0.55 * m, -0.55 * m)
        for x in xs:
            out.append(Socket("top", Vector((layout.x_offset + x, y, top)), Vector((0, 0, 1)), m))
    return out


# ---------------------------------------------------------------- assembly

MAX_CANDIDATES = 16
FIT_ISSUE = "fit: "  # warnings that mean the hull could not carry the loadout as ordered


def build(raw_params: dict, plan=None, tail=None, mid=None, nose=None, engine_design=None, rig_design=None,
          module_design=None, resolve: bool = True, detail: float | None = None,
          collection: str = COLLECTION) -> KitShip:
    """Build a kit ship.

    Hull blocks and part designs default to the seed's pick within the class kit (explicit
    arguments, then ``params["kit"]``, win). The seed tries hull designs in its own order and
    keeps the first that carries the whole loadout (part sizes come from the model params, not
    from the hull), so the seed changes the look but not the stats. ``resolve=False`` keeps
    colliding parts (to inspect conflicts). ``detail`` overrides ``kit.detail`` (hull surface
    detail 0..1, see hull_detail). ``collection``: where the ship is built (replacing what is
    there); wrecks build theirs next to the ship.
    """
    p = params_mod.individualize(params_mod.validate(raw_params).params)
    kp = p["kit"]  # explicit arguments win over the params; "auto" / -1 = the seed picks
    plan = plan or (None if kp["plan"] == "auto" else kp["plan"])
    tail = tail or (None if kp["tail"] == "auto" else kp["tail"])
    mid = mid or (None if kp["mid"] == "auto" else kp["mid"])
    nose = nose or (None if kp["nose"] == "auto" else kp["nose"])
    detail = kp["detail"] if detail is None else detail
    engine_design = engine_design if engine_design is not None else (kp["engine_design"] if kp["engine_design"] >= 0 else None)
    rig_design = rig_design if rig_design is not None else (kp["rig_design"] if kp["rig_design"] >= 0 else None)
    module_design = module_design if module_design is not None else (kp["module_design"] if kp["module_design"] >= 0 else None)
    early_warnings = []
    # a fixed design must belong to the chosen kind, or stats and looks would disagree
    if rig_design is not None and rig_designs.KIND[rig_designs.NAMES[rig_design]] != p["mining"]["type"]:
        early_warnings.append(f"kit.rig_design {rig_designs.NAMES[rig_design]} is not a {p['mining']['type']} rig: "
                              "the seed picks instead")
        rig_design = None
    if module_design is not None and module_designs.KIND[module_designs.NAMES[module_design]] != p["cargo"]["type"]:
        early_warnings.append(f"kit.module_design {module_designs.NAMES[module_design]} does not carry "
                              f"{p['cargo']['type']}: the seed picks instead")
        module_design = None
    cls = p["class"] if p["class"] in RIDGE else "freighter"
    # models of one class differ by role, so the role is part of the seed streams
    stream = f"{p['seed']}:{cls}:{p['mining']['type']}:{p['cargo']['type']}"
    if engine_design is None:
        engine_design = random.Random(f"{stream}:engine_design").randrange(len(engine_designs.DESIGNS))

    candidates = Design.candidates(cls, stream, plan=plan, tail=tail, mid=mid, nose=nose)[:MAX_CANDIDATES]
    best = None
    for design in candidates:
        ship = _build_once(p, cls, stream, design, engine_design, rig_design, module_design, resolve, detail,
                           collection)
        issues = sum(w.startswith(FIT_ISSUE) for w in ship.warnings)
        if issues == 0:
            ship.warnings[:0] = early_warnings
            return ship
        if best is None or issues < best[0]:
            best = (issues, design)
    ship = _build_once(p, cls, stream, best[1], engine_design, rig_design, module_design, resolve, detail,
                       collection)
    ship.warnings[:0] = early_warnings
    return ship


@dataclass
class _Frame:
    """Dimensions of one build: nominal ones size the parts, body ones the (volume-scaled) hull."""

    length: float
    beam: float  # nominal half beam: part sizes are derived from this
    body_beam: float
    body_height: float
    chamfer: float
    ridge: float
    module: float  # module socket size
    detail: frozenset = frozenset()  # hull_detail features of this build
    detail_amount: float = 0.0
    detail_salt: str = ""


@dataclass
class _Hull:
    bodies: list[HullLayout]  # lofted bodies (two for a twin hull)
    sockets: list[Socket] = field(default_factory=list)
    obstacles: list["Box"] = field(default_factory=list)  # hull add-ons parts must not cut into
    col_extras: list[list] = field(default_factory=list)  # add-ons and pylons, one convex shape each
    pylons: list = field(default_factory=list)  # (engine socket position, BMVerts): part of that engine
    warnings: list[str] = field(default_factory=list)
    body_bms: list = field(default_factory=list)  # detailed bodies, joined into the hull after the parts


def _build_once(p, cls, stream, design, engine_design, rig_design, module_design, resolve, detail=0.0,
                collection=COLLECTION) -> KitShip:
    clear(collection)
    coll = bpy.data.collections.new(collection)
    bpy.context.scene.collection.children.link(coll)
    root = bpy.data.objects.new("Ship", None)
    coll.objects.link(root)

    hp = p["hull"]
    length = hp["length"]
    beam = 0.5 * length * hp["width_ratio"]
    height = beam * hp["height_ratio"]
    # Same hull volume for every body plan of a model: scale the cross-section of the chosen
    # design to the reference design's (mono / flat / straight / blunt).
    reference = layout_body(Design("mono", "flat", "straight", "blunt"), length, beam, height, p["seed"])
    if design.plan == "twin":
        dry = [layout_body(design, length, 0.5 * beam, height, p["seed"])] * 2
    else:
        dry = [layout_body(design, length, beam, height, p["seed"])]
    vol_scale = math.sqrt(normalize.cross_section_integral([reference], length)
                          / normalize.cross_section_integral(dry, length))
    fr = _Frame(length, beam, beam * vol_scale, height * vol_scale,
                chamfer=min(max(1.0 - hp["squareness"], 0.0), 1.0), ridge=RIDGE[cls],
                module=0.6 * beam * (0.7 + 0.6 * p["cargo"]["size"]),
                detail=frozenset(hull_detail.details_for(cls, detail, p["max_tris"])), detail_amount=detail,
                detail_salt=f"{stream}:detail")

    hull_bm = bmesh.new()
    parts_bm = bmesh.new()  # engines, pylons, rigs, modules (material 0 accent, 1 glow, 2 cargo)
    hull = _build_hull(p, cls, design, fr, hull_bm, parts_bm)
    rig_design, module_design, instances = _place_parts(p, stream, design, fr, hull, parts_bm, engine_design,
                                                        rig_design, module_design)
    warnings = hull.warnings

    conflicts = find_conflicts(instances, hull.obstacles)
    if resolve:
        for group in resolve_conflicts(parts_bm, instances, hull.obstacles):
            warnings.append(f"{FIT_ISSUE}{group} dropped: collided with another part")
    _finish_bodies(hull_bm, hull, fr, instances)

    # triangle budget: drop module pairs (last placed first) until the ship fits
    def tris(bm):
        return sum(len(f.verts) - 2 for f in bm.faces)

    module_groups = sorted({i.group for i in instances if i.kind == "module" and i.verts},
                           key=lambda g: int(g.split("_")[1]))
    while module_groups and tris(hull_bm) + tris(parts_bm) > p["max_tris"]:
        group = module_groups.pop()
        doomed = [i for i in instances if i.group == group]
        bmesh.ops.delete(parts_bm, geom=[v for i in doomed for v in i.verts], context="VERTS")
        for i in doomed:
            i.verts = []
        warnings.append(f"{FIT_ISSUE}{group} dropped to stay within max_tris")

    _add_greebles(p, stream, parts_bm, instances, hull.obstacles, hull.bodies, fr, hull_bm, tris)

    # plain loft segments cover grooves and the trench (they only take material away); raised
    # side panels stand out of the loft, so the mid section is grown by the panel height there
    col_bodies = [hull_detail.inflated(b, fr.length, 1.6 * hull_detail.PANEL_HEIGHT * fr.beam) if "panels" in fr.detail
                  else b for b in hull.bodies]
    col_pieces = [seg for b in col_bodies
                  for seg in collision.merge(collision.body_segments(b, length, fr.chamfer, fr.ridge))]
    col_pieces += hull.col_extras
    for inst in instances:
        inst.freeze()

    def fitted(kind, names, design):  # only what is really on the ship after resolving
        return names[design] if any(i.kind == kind and i.live for i in instances) else "none"

    loadout = {
        "engine": fitted("engine", engine_designs.NAMES, engine_design),
        "rig": fitted("rig", rig_designs.NAMES, rig_design),
        "module": fitted("module", module_designs.NAMES, module_design),
        "wings": p["wings"]["type"] if any(i.kind == "wing" and i.live for i in instances) else "none",
    }
    designs = {"engine": loadout["engine"], "rig": loadout["rig"], "module": loadout["module"],
               "wing": loadout["wings"]}
    parts, part_colliders = _part_objects(p, coll, root, hull_bm, parts_bm, instances, hull.pylons, designs)
    colliders = collision.build_colliders(col_pieces, coll, root) + part_colliders
    socket_objects = [_socket_empty(sk, coll, root) for sk in hull.sockets]
    fx_objects = _fx_anchors(fr, hull, instances, coll, root)

    ship = KitShip(root=root, parts=parts, params=p, warnings=warnings, design=design, sockets=hull.sockets,
                   socket_objects=socket_objects, fx_objects=fx_objects, colliders=colliders, engine_design=engine_design, loadout=loadout,
                   conflicts=conflicts, instances=instances, obstacles=hull.obstacles)
    nose_sockets = [s for s in hull.sockets if s.kind == "nose"]
    nose_y = nose_sockets[0].pos.y if nose_sockets else 0.5 * length
    ref_bm = bmesh.new()  # the model's reference hull: hull stats come from it, the design is looks
    loft_body(ref_bm, reference, length, fr.chamfer, fr.ridge)
    reference_hull = {"volume": abs(ref_bm.calc_volume()), "area": sum(f.calc_area() for f in ref_bm.faces)}
    ref_bm.free()
    ship.gameplay = _normalized_stats(ship, _StatsHull(length, CLASS_PROFILES[cls], nose_y), engine_design,
                                      rig_design, module_design, reference_hull)
    root["shipgen"] = {"seed": p["seed"], "class": p["class"], "design": design.label(), **loadout,
                       "stats": ship.gameplay}
    return ship


def _build_hull(p, cls, design: Design, fr: _Frame, hull_bm, parts_bm) -> _Hull:
    """Loft the bodies and their add-ons; collect sockets, obstacles and collision pieces."""
    length, body_height, chamfer, ridge, module = fr.length, fr.body_height, fr.chamfer, fr.ridge, fr.module
    n_eng, r_req = p["engines"]["count"], 0.5 * p["engines"]["size"]

    def body_boxes(lay, applies_to):
        for a, b in zip(lay.stations, lay.stations[1:]):
            y0, y1 = (-0.5 + a.t) * length, (-0.5 + b.t) * length
            w = max(a.half_width, b.half_width)
            yield Box("hull", Vector((lay.x_offset - w, y0, -max(a.bottom, b.bottom))),
                      Vector((lay.x_offset + w, y1, max(a.top, b.top))), applies_to)

    def mount_engines(h, n, lay):
        sk, pylons, r = _engine_sockets(n, r_req, lay.x_offset, lay.y_tail, lay.stations[0],
                                        design.tail == "outboard")
        if sk and r < r_req * 0.99:
            h.warnings.append(f"{FIT_ISSUE}engines.size capped to {2 * r:.2f} to fit the tail")
        h.sockets += sk
        for a, c, rr in pylons:
            refs: list = []
            h.col_extras.append(_grab(parts_bm, lambda a=a, c=c, rr=rr: shapes.beam(parts_bm, a, c, 0.5 * rr,
                                                                                   0.25 * rr, 0), refs))
            h.pylons.append((c.copy(), refs))

    def add_on(h, bm, fn, box):  # hull add-on: one convex shape, one obstacle
        h.col_extras.append(_grab(bm, fn))
        h.obstacles.append(box)

    if design.plan == "twin":
        sub_beam = 0.5 * fr.body_beam
        gap = 0.9 * sub_beam
        bodies = []
        for s in (1, -1):
            lay = layout_body(design, length, sub_beam, body_height, p["seed"])
            lay.x_offset = s * (sub_beam + 0.5 * gap)
            bodies.append(lay)
        h = _Hull(bodies)
        for lay in bodies:
            _loft_detailed(hull_bm, h, lay, fr)
        for lay in bodies:
            h.obstacles += body_boxes(lay, {"rig"})
        lay = bodies[0]
        for f in (0.25, 0.75):  # bridges between the hulls
            y = lay.y_mid[0] + f * (lay.y_mid[1] - lay.y_mid[0])
            size = Vector((2 * (sub_beam + 0.5 * gap), 0.1 * length, 0.35 * body_height))
            centre = Vector((0, y, 0.15 * body_height))
            add_on(h, hull_bm, lambda c=centre, sz=size: shapes.box(hull_bm, c, sz),
                   Box("bridge", centre - size / 2, centre + size / 2, {"rig", "module", "engine"}))
        for b in bodies:
            mount_engines(h, n_eng // 2, b)
            h.sockets += _side_sockets(b, length, module, b.x_offset, outer_only_sign=1 if b.x_offset > 0 else -1)
            h.sockets += _top_sockets(b, length, module, chamfer, ridge, single=True)
        if n_eng % 2:
            h.warnings.append(f"{FIT_ISSUE}twin hulls need an even engine count; one engine dropped")
        h.sockets.append(Socket("nose", Vector((0, lay.y_mid[1], 0.0)), Vector((0, 1, 0)), 0.45 * gap))
    else:
        lay = layout_body(design, length, fr.body_beam, body_height, p["seed"])
        h = _Hull([lay])
        _loft_detailed(hull_bm, h, lay, fr)
        mount_engines(h, n_eng, lay)
        front = lay.stations[-1]
        if design.mid == "sponson":
            pw = 0.32 * fr.body_beam
            y_a, y_b = lay.y_mid
            pod_a, pod_b = y_a + 0.05 * length, y_b - 0.02 * length
            pod_top, pod_bottom = 0.5 * body_height * 0.55, 0.5 * body_height * 0.45
            mid_w = section_at(lay, 0.5 * (y_a + y_b), length).half_width
            for s in (1, -1):
                x = s * (mid_w + 0.5 * pw)
                add_on(h, hull_bm, lambda x=x: _mini_body(hull_bm, x, pod_a, pod_b, pw, pod_top, pod_bottom, chamfer,
                                                          ridge, length, pointed=False),
                       Box("pod", Vector((x - pw, pod_a, -pod_bottom)), Vector((x + pw, pod_b, pod_top)),
                           {"rig", "module", "engine", "wing"}))
            # modules mount on the pods' outer faces instead of the hull side
            x_out = mid_w + 1.5 * pw
            span_a, span_b = pod_a + 0.2 * (pod_b - pod_a), pod_b - 0.3 * (pod_b - pod_a)
            cols = max(int((span_b - span_a) // (2.1 * module)) + 1, 1)  # centre spacing >= 2.1 module
            if cols > 1 and (span_b - span_a) / (cols - 1) < 2.1 * module:
                cols -= 1
            for c in range(cols):
                y = span_a + (span_b - span_a) * (c / (cols - 1) if cols > 1 else 0.5)
                for s in (1, -1):
                    h.sockets.append(Socket("side", Vector((s * x_out, y, 0.0)), Vector((s, 0, 0)), module))
        else:
            h.sockets += _side_sockets(lay, length, module, 0.0)
        h.sockets += _top_sockets(lay, length, module, chamfer, ridge)
        if cls in BRIDGE_CLASSES and length >= BRIDGE_MIN_LENGTH:
            for fn, box in _bridge(hull_bm, lay, fr):
                add_on(h, hull_bm, fn, box)
        if design.plan == "fork":
            pw = 0.3 * front.half_width
            y0, y1 = lay.y_front - 0.08 * length, lay.y_front + 0.22 * length
            for s in (1, -1):
                x = s * (front.half_width - pw * 0.6)
                add_on(h, hull_bm, lambda x=x: _mini_body(hull_bm, x, y0, y1, pw, front.top * 0.8, front.bottom * 0.8,
                                                          chamfer, ridge, length),
                       Box("prong", Vector((x - pw, y0, -front.bottom)), Vector((x + pw, y1, front.top)),
                           {"rig", "module", "wing"}))
            inner = front.half_width - 1.6 * pw  # inner face of the prongs
            h.sockets.append(Socket("nose", Vector((0, lay.y_front, 0)), Vector((0, 1, 0)), 0.9 * inner))
        elif not lay.point_nose:
            h.sockets.append(Socket("nose", Vector((0, lay.y_front, 0)), Vector((0, 1, 0)), 0.95 * front.half_width))

    for i, sk in enumerate(h.sockets):
        sk.name = sk.name or f"Socket_{sk.kind}_{i}"
    return h


def _loft_detailed(hull_bm, h: _Hull, lay: HullLayout, fr: _Frame) -> None:
    """Loft one body, with grooves and side panels if this build has them. A detailed body
    stays a separate mesh (``h.body_bms``) until ``_finish_bodies``: the trench boolean needs
    one clean shell and has to know where the roof modules went. Sockets keep the plain layout."""
    if not fr.detail:
        loft_body(hull_bm, lay, fr.length, fr.chamfer, fr.ridge)
        return
    body = bmesh.new()
    loft = lay
    if "grooves" in fr.detail:
        loft, grooves = hull_detail.grooved(lay, fr.length, fr.detail_salt)
        for y0, y1 in grooves:  # greebles keep out of grooves
            st = section_at(lay, 0.5 * (y0 + y1), fr.length)
            h.obstacles.append(Box("groove", Vector((lay.x_offset - st.half_width, y0, -st.bottom)),
                                   Vector((lay.x_offset + st.half_width, y1, st.top)), set()))
    if h.body_bms:  # second twin body: mirrored from the first in _finish_bodies (exact symmetry)
        h.body_bms.append(None)
        body.free()
        return
    loft_body(body, loft, fr.length, fr.chamfer, fr.ridge)
    if "panels" in fr.detail:
        hull_detail.panels(body, lay.y_mid, fr.length, fr.beam, fr.detail_salt,
                           share=hull_detail.PANEL_SHARE * fr.detail_amount)
    h.body_bms.append(body)


def _finish_bodies(hull_bm, h: _Hull, fr: _Frame, instances) -> None:
    """Cut the trench into the detailed bodies where no roof module sits, then join them into
    the hull mesh. The trench becomes an obstacle for greebles (they would float over it).
    A twin's second body is the first one mirrored, so the two match exactly."""
    if not h.body_bms:
        return
    lay, body = h.bodies[0], h.body_bms[0]
    trench = []
    if "trench" in fr.detail:
        occupied = []
        for inst in instances:
            if inst.kind == "module" and inst.live and inst.sk.kind == "top":
                if abs(inst.sk.pos.x - lay.x_offset) < section_at(lay, inst.sk.pos.y, fr.length).half_width:
                    ys = [c.y for c in inst.coords()]
                    occupied.append((min(ys), max(ys)))
        cutter, boxes = hull_detail.trench_cutter(lay, fr.length, fr.body_height,
                                                  hull_detail.trench_stretches(lay, fr.length, occupied))
        hull_detail.boolean_difference(body, cutter)
        trench = [Box("trench", lo, hi, set()) for lo, hi in boxes]
    bodies = [body]
    if len(h.body_bms) == 2:
        twin = body.copy()
        for v in twin.verts:
            v.co.x = -v.co.x
        bmesh.ops.reverse_faces(twin, faces=twin.faces[:])
        bodies.append(twin)
        trench += [Box(b.what, Vector((-b.hi.x, b.lo.y, b.lo.z)), Vector((-b.lo.x, b.hi.y, b.hi.z)), set())
                   for b in trench]
    h.obstacles += trench
    for bm in bodies:
        mesh = bpy.data.meshes.new("_detail_body")
        bm.to_mesh(mesh)
        bm.free()
        hull_bm.from_mesh(mesh)
        bpy.data.meshes.remove(mesh)
    h.body_bms = []


BRIDGE_CLASSES = {"freighter", "miner"}
BRIDGE_MIN_LENGTH = 20.0


def _bridge(hull_bm, lay: HullLayout, fr: _Frame):
    """Command bridge on the tail roof, like a cargo ship's: a deck house with a raised bridge
    and a lit window band facing forward. Pure looks (hull stats come from the reference hull);
    it stays behind the mid section, so roof modules never reach it. Yields (builder, obstacle)."""
    y_a = lay.y_mid[0]
    span = y_a - lay.y_tail
    y0, y1 = lay.y_tail + 0.2 * span, y_a - 0.05 * span
    sts = [section_at(lay, y, fr.length) for y in (y0, 0.5 * (y0 + y1), y1)]
    roof_w = min(st.half_width for st in sts) * (1.0 - 0.7 * fr.chamfer)
    roof_z = min(st.top for st in sts) * (1.0 - 0.6 * fr.ridge)
    sink = 0.05 * fr.body_height  # sits into the roof, so no gap shows on ridged roofs
    h1, h2 = 0.24 * fr.body_height, 0.22 * fr.body_height
    deck = (Vector((0, 0.5 * (y0 + y1), roof_z + 0.5 * (h1 - sink))), Vector((1.3 * roof_w, y1 - y0, h1 + sink)))
    yb0 = y0 + 0.45 * (y1 - y0)  # the raised bridge sits on the front of the deck house
    top_z = roof_z + h1 - 0.5 * sink
    house = (Vector((0, 0.5 * (yb0 + y1), top_z + 0.5 * h2)), Vector((0.8 * roof_w, y1 - yb0, h2 + 0.5 * sink)))
    window = (Vector((0, y1 + 0.01 * span, top_z + 0.6 * h2)), Vector((0.7 * roof_w, 0.04 * span, 0.3 * h2)))
    applies = {"module", "engine", "wing", "rig"}
    for (c, size), mat in ((deck, 0), (house, 0), (window, 1)):
        yield (lambda c=c, size=size, mat=mat: shapes.box(hull_bm, c, size, material=mat),
               Box("bridge_house", c - size / 2, c + size / 2, applies))


def _place_parts(p, stream, design, fr: _Frame, hull: _Hull, parts_bm, engine_design, rig_design, module_design):
    """Engines, wings, rig and modules on the hull's sockets, each tracked as an Instance for the
    collision check. Returns (rig_design, module_design, instances); the seed picks missing designs."""
    instances: list[Instance] = []
    sockets, warnings = hull.sockets, hull.warnings
    pick = random.Random(f"{stream}:parts")

    def place(kind, group, builder, sk):
        refs = []
        _grab(parts_bm, builder, refs)
        instances.append(Instance(kind, group, sk.name, refs, sk))

    for sk in (s for s in sockets if s.kind == "engine"):
        place("engine", sk.name, lambda sk=sk: engine_designs.build(parts_bm, engine_design, sk.pos, sk.normal,
                                                                    sk.radius), sk)

    for i, piece in enumerate(wings.add_wings(parts_bm, p, _WingHull(fr.length, hull.bodies[0]))):
        x, y, z = piece.root
        kind = "wing" if piece.kind == "pair" else "fin"
        for side in ((1, -1) if piece.kind == "pair" else (0,)):
            sk = Socket(kind, Vector((side * x, y, z)), Vector(piece.normal) * (side or 1), 0.5 * fr.length,
                        f"Socket_{kind}_{i}" + ("" if side == 0 else ("_r" if side > 0 else "_l")))
            verts = [v for v in piece.verts if side == 0 or (v.co.x > 0) == (side > 0)]
            instances.append(Instance("wing", f"wings_{i}", sk.name, verts, sk))
            sockets.append(sk)

    mining_kind = p["mining"]["type"]
    nose_sockets = [s for s in sockets if s.kind == "nose"]
    if mining_kind == "none":
        rig_design = None
    elif rig_design is None:
        rig_design = pick.choice(rig_designs.designs_of(mining_kind))
    if rig_design is not None:
        if nose_sockets:
            sk = nose_sockets[0]
            radius = fr.beam * (0.4 + 0.5 * p["mining"]["size"])  # from the model, not the socket
            if radius > sk.radius:
                warnings.append(f"{FIT_ISSUE}mining rig shrunk to fit the nose ({sk.radius:.2f} < {radius:.2f})")
                radius = sk.radius
            place("rig", "rig", lambda: rig_designs.build(parts_bm, rig_design, sk.pos, sk.normal, radius), sk)
        else:
            warnings.append(f"{FIT_ISSUE}mining rig dropped: this nose has no mount face")

    cargo_kind = p["cargo"]["type"]
    if cargo_kind == "none":
        module_design = None
    elif module_design is None:
        module_design = pick.choice(module_designs.designs_of(cargo_kind))
    wanted = p["cargo"]["modules"] if module_design is not None else 0

    def pairs_of(kind):  # mirrored socket pairs, front to back
        socks = sorted((s for s in sockets if s.kind == kind), key=lambda s: (-s.pos.y, abs(s.pos.x), s.pos.x))
        return [socks[i:i + 2] for i in range(0, len(socks) - 1, 2)]

    placed = 0
    for pair in pairs_of("side") + pairs_of("top"):  # sides first, then the roof
        if placed + 2 > wanted:
            break
        for sk in pair:
            place("module", f"modules_{placed}", lambda sk=sk: module_designs.build(parts_bm, module_design, sk.pos,
                                                                                    sk.normal, sk.radius), sk)
        placed += 2
    if placed < wanted:
        warnings.append(f"{FIT_ISSUE}cargo.modules: placed {placed} of {wanted} "
                        "(pairs only, limited by side and roof sockets)")
    return rig_design, module_design, instances


ROLE_OF = {"engine": "engines", "rig": "mining", "module": "cargo", "wing": "wings", "greeble": "greebles"}
PART_NAME = {"engine": "Engine", "rig": "Rig", "module": "Module"}  # wings: Wings_<i> (pair), Fin_<i>


def _socket_matrix(sk: Socket) -> Matrix:
    """Ship space of a socket: origin at the mount, local +Y = socket normal (Godot: -Z)."""
    return Matrix.Translation(sk.pos) @ sk.normal.to_track_quat("Y", "Z").to_matrix().to_4x4()


def _part_objects(p, coll, root, hull_bm, parts_bm, instances, pylons, designs) -> tuple[list, list]:
    """One object per fitted part (engine, rig, module, wing), origin and orientation at its socket,
    with its own convex collider child; the hull and the greebles stay one object each. Frees both
    bmeshes. Returns (part objects, part colliders)."""
    mats = materials.create_materials(p)
    parts_bm.verts.index_update()
    pieces = [("Ship_Hull", "hull", hull_bm, ("hull", "glow"), None, None)]  # glow: bridge windows
    counters: dict[str, int] = {}
    greebles: set = set()
    wing_groups: dict[str, list] = {}
    for inst in instances:
        if not inst.live:
            continue
        if inst.kind == "greeble":
            greebles.update(v.index for v in inst.verts)
            continue
        if inst.kind == "wing":  # a wing pair is one closed mesh through the hull: one part
            wing_groups.setdefault(inst.group, []).append(inst)
            continue
        idx = {v.index for v in inst.verts}
        if inst.kind == "engine":  # its pylon (outboard engines) belongs to it
            for pos, refs in pylons:
                if (pos - inst.sk.pos).length < 1e-6:
                    idx.update(v.index for v in refs if v.is_valid)
        n = counters.get(inst.kind, 0)
        counters[inst.kind] = n + 1
        info = {"role": ROLE_OF[inst.kind], "kind": inst.kind, "design": designs[inst.kind], "socket": inst.socket}
        pieces.append((f"{PART_NAME[inst.kind]}_{n}", ROLE_OF[inst.kind], _subset(parts_bm, idx),
                       ("accent", "glow", "cargo"), _socket_matrix(inst.sk), info))
    for group, insts in wing_groups.items():
        i = group.split("_")[1]
        pair = len(insts) > 1
        idx = {v.index for inst in insts for v in inst.verts}
        # a pair sits on the centre line between its sockets, in ship axes; a fin on its socket
        matrix = (Matrix.Translation(sum((inst.sk.pos for inst in insts), Vector()) / len(insts)) if pair
                  else _socket_matrix(insts[0].sk))
        info = {"role": "wings", "kind": "wing" if pair else "fin", "design": designs["wing"],
                "socket": [inst.socket for inst in insts] if pair else insts[0].socket}
        pieces.append((f"Wings_{i}" if pair else f"Fin_{i}", "wings", _subset(parts_bm, idx),
                       ("hull", "glow", "cargo"), matrix, info))  # wings in hull paint
    if greebles:
        pieces.append(("Ship_Greebles", "greebles", _subset(parts_bm, greebles), ("accent", "glow", "cargo"), None, None))
    parts_bm.free()

    parts, colliders = [], []
    for name, role, bm, mat_keys, matrix, info in pieces:
        if not bm.faces:
            bm.free()
            continue
        if matrix is not None:
            bm.transform(matrix.inverted())  # mesh in the part's own space
        meshutil.orient_outward(bm)  # every shell of the part faces out (culling, volumes)
        points = [v.co.copy() for v in bm.verts]
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        for poly in mesh.polygons:
            poly.use_smooth = False
        for key in mat_keys:
            mesh.materials.append(mats[key])
        obj = bpy.data.objects.new(name, mesh)
        coll.objects.link(obj)
        obj.parent = root
        obj["shipgen_role"] = role
        if matrix is not None:
            obj.matrix_basis = matrix
            obj["shipgen_part"] = info
            col = collision.convex_object(points, f"{name}_col{collision.SUFFIX}", coll, obj)
            if col is not None:
                colliders.append(col)
        parts.append(obj)
    return parts, colliders


def _subset(bm, indices: set):
    """Copy of ``bm`` with only the vertices in ``indices`` (and their faces)."""
    out = bm.copy()
    out.verts.ensure_lookup_table()
    bmesh.ops.delete(out, geom=[v for v in out.verts if v.index not in indices], context="VERTS")
    return out


def _socket_empty(sk: Socket, coll, root):
    """Hardpoint for Godot (local +Y = socket normal -> Godot -Z forward)."""
    empty = bpy.data.objects.new(sk.name, None)
    empty.empty_display_type = "SINGLE_ARROW"
    empty.empty_display_size = sk.radius
    empty.location = sk.pos
    empty.rotation_euler = sk.normal.to_track_quat("Y", "Z").to_euler()
    empty["shipgen_socket"] = {"kind": sk.kind, "radius": round(sk.radius, 4)}
    coll.objects.link(empty)
    empty.parent = root
    return empty


def _fx_anchors(fr: _Frame, hull: _Hull, instances, coll, root) -> list:
    """Where the game attaches effects: engine exhaust, rig work point, attitude thrusters (RCS)
    in pairs at both ends, navigation lights (port red, starboard green, tail white)."""
    out = []
    counts: dict[str, int] = {}

    def add(kind, pos, direction, size, **extra):
        n = counts.get(kind, 0)
        counts[kind] = n + 1
        out.append(fx.anchor(f"FX_{kind}_{n}", coll, root, pos, direction, kind, size, **extra))

    for inst in instances:  # the far end of the part along its socket normal, its radius there
        if not inst.live or inst.kind not in ("engine", "rig"):
            continue
        n = inst.sk.normal
        coords = inst.coords()
        depth = max((c - inst.sk.pos).dot(n) for c in coords)
        radius = max(((c - inst.sk.pos) - n * (c - inst.sk.pos).dot(n)).length for c in coords)
        add("exhaust" if inst.kind == "engine" else "mining", inst.sk.pos + n * depth, n,
            (0.8 if inst.kind == "engine" else 0.5) * radius)

    length, size = fr.length, 0.08 * fr.beam
    twin = len(hull.bodies) > 1
    for y in (0.32 * length, -0.32 * length):
        for lay in hull.bodies:
            st = section_at(lay, y, length)
            cx = lay.x_offset
            add("rcs", (cx, y, st.top), (0, 0, 1), size)
            add("rcs", (cx, y, -st.bottom), (0, 0, -1), size)
            for side in (1, -1):
                if twin and side * cx < 0:
                    continue  # the inner flank of a twin body faces the other body
                add("rcs", (cx + side * st.half_width, y, 0.0), (side, 0, 0), size)

    # navigation lights at the widest point (wing tips, else the hull) and on the tail
    wing_pts = [c for i in instances if i.live and i.kind == "wing" for c in i.coords()]
    if wing_pts:
        tip = max(wing_pts, key=lambda c: c.x)
    else:
        best = None
        for k in range(21):
            y = (-0.45 + 0.9 * k / 20) * length
            for lay in hull.bodies:
                st = section_at(lay, y, length)
                x = lay.x_offset + st.half_width
                if best is None or x > best.x:
                    best = Vector((x, y, 0.0))
        tip = best
    light = 0.03 * length
    add("nav_light", (-tip.x, tip.y, tip.z), (-1, 0, 0), light, color="red")
    add("nav_light", tip, (1, 0, 0), light, color="green")
    tail = section_at(hull.bodies[0], -0.48 * length, length)
    add("nav_light", (0.0 if not twin else hull.bodies[0].x_offset, -0.5 * length, tail.top), (0, -1, 0), light,
        color="white")
    return out


def _normalized_stats(ship, hull, engine_design, rig_design, module_design, reference_hull) -> dict:
    """stats.compute, made independent of the seed's design choices:

    - hull mass, internal hold and hull HP come from the model's reference hull;
    - each part design is scaled to the mean of its kind (normalize.py).
    Parts still count with their real geometry (size, count), so the model params decide.
    """
    g = stats.compute(ship, hull, KIT_MINING_EFFICIENCY)
    m = stats.measure_roles(ship.parts)
    profile = hull.profile

    mass = g["mass_t"] + stats.DENSITY["hull"] * (reference_hull["volume"] - m["hull"]["volume"])
    # part masses as if every design weighed the mean of its kind
    for role, factor in (("engines", normalize.engine_volume_factors()[engine_design]),
                         ("mining", normalize.rig_volume_factors()[rig_design] if rig_design is not None else 1.0),
                         ("cargo", normalize.module_factors()[module_design] if module_design is not None else 1.0)):
        if role in m:
            mass += stats.DENSITY[role] * m[role]["volume"] * (factor - 1.0)
    thrust = g["thrust_kn"] * normalize.engine_factors()[engine_design]
    g["mass_t"] = round(mass, 2)
    g["thrust_kn"] = round(thrust, 2)
    g["acceleration_ms2"] = round(thrust / mass, 2) if mass else 0.0
    g["turn_rate_deg_s2"] = round(math.degrees(0.1 * 6.0 * thrust / (mass * hull.length)), 2) if mass else 0.0
    g["hull_hp"] = round(reference_hull["area"] * stats.HULL_HP_PER_M2 * profile.armor)

    cargo = {"general_m3": 0.0, "ore_m3": 0.0, "fluid_m3": 0.0, "passengers": 0}
    cargo[profile.hold_kind] += reference_hull["volume"] * profile.hold
    if "cargo" in m and ship.loadout["module"] != "none":
        usable = m["cargo"]["volume"] * stats.USABLE_MODULE_VOLUME
        usable *= normalize.module_factors()[module_design]
        kind = ship.params["cargo"]["type"]
        if kind == "habitat":
            cargo["passengers"] = int(usable // stats.M3_PER_PASSENGER)
        else:
            cargo[stats.CARGO_KIND[kind]] += usable
    g["cargo"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in cargo.items()}

    if ship.loadout["rig"] != "none":
        g["mining"]["power"] = round(g["mining"]["power"] * normalize.rig_factors()[rig_design], 2)
    return g


@dataclass
class _WingHull:
    """Kit layout in the shape wings.add_wings expects (outer edge of the outermost body)."""

    length: float
    layout: HullLayout

    def y(self, t: float) -> float:
        return (t - 0.5) * self.length

    def section(self, t: float) -> Station:
        st = section_at(self.layout, self.y(t), self.length)
        return Station(t, abs(self.layout.x_offset) + st.half_width, st.top, st.bottom, 0.0, 0.0)


@dataclass
class _StatsHull:
    """What stats.compute needs to know about the hull; mining reach counts from the nose mount."""

    length: float
    profile: object
    nose_y: float

    def y(self, t: float) -> float:
        return self.nose_y if t >= 1.0 else (t - 0.5) * self.length


# Mining power per rig kind for the kit's rig library: efficiency x rig volume^(2/3),
# calibrated (scripts/kit_calibrate.py) so a medium rig (size 0.5 on miner_m) averages ~100.
KIT_MINING_EFFICIENCY = {"drill": 7.002, "laser": 9.063, "claw": 11.618, "scoop": 10.456}


# ---------------------------------------------------------------- greebles

GREEBLE_STEP = 0.09  # spacing of candidate spots along the hull (fraction of the length)
GREEBLE_STYLE = 3  # designs per ship, so a ship looks coherent


def _add_greebles(p, stream, bm, instances, obstacles, bodies, fr: _Frame, hull_bm, tris) -> None:
    """Small details on free roof / side spots, in mirrored pairs; skipped where they would touch
    anything else, and only while the triangle budget lasts."""
    density = p["greeble_density"]
    if density <= 0:
        return
    length, beam, chamfer = fr.length, fr.beam, fr.chamfer
    rng = random.Random(f"{stream}:greebles")
    style = rng.sample(range(len(greeble_designs.DESIGNS)), GREEBLE_STYLE)
    taken = [i.box() for i in instances if i.live] + list(obstacles)
    spots = []  # (pair of (pos, normal)), front to back
    lay = bodies[0]
    n_steps = int(0.9 / GREEBLE_STEP)
    for k in range(n_steps):
        y = (-0.5 + 0.05 + k * GREEBLE_STEP) * length
        st = section_at(lay, y, length)
        if st.half_width < 0.05 * beam:
            continue
        roof_w = st.half_width * (1.0 - 0.7 * chamfer)
        cx = lay.x_offset
        twin = len(bodies) > 1
        for x, z, n in ((cx, st.top, (0, 0, 1)), (cx + 0.55 * roof_w, st.top, (0, 0, 1)),
                        (cx + st.half_width, 0.25 * st.top, (1, 0, 0))):
            right = (Vector((x, y, z)), Vector(n))
            mirrored = (Vector((-x, y, z)), Vector((-n[0], n[1], n[2])))
            if abs(x) < 1e-6 and not twin:
                spots.append((right,))  # centre line of a mono hull
            else:
                spots.append((right, mirrored))
    rng.shuffle(spots)
    for spot in spots:
        if rng.random() > density:
            continue
        if tris(hull_bm) + tris(bm) > p["max_tris"] - 200:
            break
        design = rng.choice(style)
        m = beam * rng.uniform(0.1, 0.18)
        group = f"greeble_{len(instances)}"
        placed = []
        for pos, normal in spot:
            sk = Socket("greeble", pos, normal, m, group)
            before = set(bm.verts)
            greeble_designs.build(bm, design, pos, normal, m)
            placed.append(Instance("greeble", group, group, [v for v in bm.verts if v not in before], sk))
        if any(inst.box().overlaps(other) for inst in placed for other in taken):
            bmesh.ops.delete(bm, geom=[v for inst in placed for v in inst.verts], context="VERTS")
            continue
        instances.extend(placed)
        taken.extend(inst.box() for inst in placed)


# ---------------------------------------------------------------- collisions

MARGIN = 1e-3


@dataclass
class Box:
    what: str
    lo: Vector
    hi: Vector
    applies_to: set = field(default_factory=set)  # instance kinds checked against this obstacle

    def overlaps(self, other: "Box") -> bool:
        return all(self.lo[i] < other.hi[i] - MARGIN and other.lo[i] < self.hi[i] - MARGIN for i in range(3))


@dataclass
class Instance:
    kind: str  # "engine", "wing", "rig", "module", "greeble"
    group: str  # instances of one group are dropped together (mirrored module pairs)
    socket: str
    verts: list  # BMVerts in the parts mesh; emptied when the part is dropped
    sk: Socket
    points: list | None = None  # vertex positions, kept by freeze() once the mesh is gone

    @property
    def live(self) -> bool:
        if self.points is not None:
            return bool(self.points)
        return bool(self.verts) and self.verts[0].is_valid

    def coords(self) -> list:
        return self.points if self.points is not None else [v.co for v in self.verts]

    def freeze(self) -> None:
        """Keep the positions so the finished ship can still be checked (find_conflicts_after)."""
        self.points = [v.co.copy() for v in self.verts] if self.live else []

    def box(self) -> Box:
        """Bounding box of the part outside its mount (the embedded root may sit in the hull)."""
        coords = self.coords()
        outside = [c for c in coords if (c - self.sk.pos).dot(self.sk.normal) > 0.05 * self.sk.radius]
        pts = outside or coords
        lo = Vector(tuple(min(c[i] for c in pts) for i in range(3)))
        hi = Vector(tuple(max(c[i] for c in pts) for i in range(3)))
        return Box(self.kind, lo, hi)


PRIORITY = {"greeble": -1, "module": 0, "wing": 1, "rig": 2, "engine": 3}  # lowest is dropped first


def find_conflicts_after(ship: "KitShip") -> list:
    """Collisions left in the finished ship (should always be empty when resolved)."""
    return find_conflicts(ship.instances, ship.obstacles)


def _collisions(instances, obstacles):
    """Yield (instance, other instance or None, obstacle or None) for every overlap."""
    live = [i for i in instances if i.live]
    boxes = {id(i): i.box() for i in live}
    for a_i, a in enumerate(live):
        for b in live[a_i + 1:]:
            if a.group != b.group and boxes[id(a)].overlaps(boxes[id(b)]):
                yield a, b, None
        for ob in obstacles:
            if a.kind in ob.applies_to and boxes[id(a)].overlaps(ob):
                yield a, None, ob


def find_conflicts(instances, obstacles) -> list[tuple[str, str]]:
    return [tuple(sorted((a.kind, b.kind))) if b is not None else (a.kind, ob.what)
            for a, b, ob in _collisions(instances, obstacles)]


def resolve_conflicts(bm, instances, obstacles) -> list[str]:
    """Drop the lowest-priority group involved in a collision until none is left."""
    dropped = []
    while True:
        victim = None
        for a, b, _ in _collisions(instances, obstacles):
            cand = a if b is None or PRIORITY[a.kind] <= PRIORITY[b.kind] else b
            if victim is None or PRIORITY[cand.kind] < PRIORITY[victim.kind]:
                victim = cand
        if victim is None:
            return dropped
        group = [i for i in instances if i.live and i.group == victim.group]
        bmesh.ops.delete(bm, geom=[v for i in group for v in i.verts], context="VERTS")
        for i in group:
            i.verts = []
        dropped.append(victim.group)
