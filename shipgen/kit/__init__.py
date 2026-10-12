"""Parts-kit prototype: hulls from designed sections, parts on sockets.

    ship = kit.build(params, plan="twin", engine_design=3)

See docs/parts_kit.md for the concept. Uses the main params schema; the kit
choices (plan, tail, mid, nose, engine design) come from the seed unless given.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import bmesh
import bpy
from mathutils import Vector

from .. import params as params_mod
from .. import stats
from ..generator import Ship, clear, materials, shapes, wings
from ..generator.hull import CLASS_PROFILES, Station
from . import collision, engine_designs, greeble_designs, module_designs, normalize, rig_designs
from .hull_kit import Design, HullLayout, Socket, layout_body, loft_body, section_at, RIDGE

COLLECTION = "ShipGen"
OUTBOARD_TRIGGER = 1.3  # requested engine radius / what fits the tail face


@dataclass
class KitShip(Ship):
    design: Design | None = None
    sockets: list[Socket] = field(default_factory=list)
    socket_objects: list = field(default_factory=list)
    colliders: list = field(default_factory=list)  # convex "-convcolonly" meshes for Godot
    engine_design: int = 0
    loadout: dict = field(default_factory=dict)
    conflicts: list = field(default_factory=list)  # collisions found before resolving
    instances: list = field(default_factory=list)
    obstacles: list = field(default_factory=list)

    @property
    def objects(self):
        return [self.root, *self.parts, *self.socket_objects, *self.colliders]


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
          module_design=None, resolve: bool = True) -> KitShip:
    """Build a kit ship.

    Hull blocks and part designs default to the seed's pick within the class kit (explicit
    arguments, then ``params["kit"]``, win). The seed tries hull designs in its own order and
    keeps the first that carries the whole loadout (part sizes come from the model params, not
    from the hull), so the seed changes the look but not the stats. ``resolve=False`` keeps
    colliding parts (to inspect conflicts).
    """
    p = params_mod.individualize(params_mod.validate(raw_params).params)
    kp = p["kit"]  # explicit arguments win over the params; "auto" / -1 = the seed picks
    plan = plan or (None if kp["plan"] == "auto" else kp["plan"])
    tail = tail or (None if kp["tail"] == "auto" else kp["tail"])
    mid = mid or (None if kp["mid"] == "auto" else kp["mid"])
    nose = nose or (None if kp["nose"] == "auto" else kp["nose"])
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
        ship = _build_once(p, cls, stream, design, engine_design, rig_design, module_design, resolve)
        issues = sum(w.startswith(FIT_ISSUE) for w in ship.warnings)
        if issues == 0:
            ship.warnings[:0] = early_warnings
            return ship
        if best is None or issues < best[0]:
            best = (issues, design)
    ship = _build_once(p, cls, stream, best[1], engine_design, rig_design, module_design, resolve)
    ship.warnings[:0] = early_warnings
    return ship


def _build_once(p, cls, stream, design, engine_design, rig_design, module_design, resolve) -> KitShip:
    clear(COLLECTION)
    coll = bpy.data.collections.new(COLLECTION)
    bpy.context.scene.collection.children.link(coll)
    root = bpy.data.objects.new("Ship", None)
    coll.objects.link(root)
    mats = materials.create_materials(p)

    hp = p["hull"]
    length = hp["length"]
    beam = 0.5 * length * hp["width_ratio"]  # nominal: part sizes are derived from this
    height = beam * hp["height_ratio"]
    chamfer = min(max(1.0 - hp["squareness"], 0.0), 1.0)
    ridge = RIDGE[cls]
    # Same hull volume for every body plan of a model: scale the cross-section of the chosen
    # design to the reference design's (mono / flat / straight / blunt).
    reference = layout_body(Design("mono", "flat", "straight", "blunt"), length, beam, height, p["seed"])
    if design.plan == "twin":
        dry = [layout_body(design, length, 0.5 * beam, height, p["seed"])] * 2
    else:
        dry = [layout_body(design, length, beam, height, p["seed"])]
    vol_scale = math.sqrt(normalize.cross_section_integral([reference], length)
                          / normalize.cross_section_integral(dry, length))
    body_beam, body_height = beam * vol_scale, height * vol_scale

    hull_bm = bmesh.new()
    parts_bm = bmesh.new()  # engines, pylons, rigs, modules (material 0 accent, 1 glow, 2 cargo)
    sockets: list[Socket] = []
    warnings: list[str] = []
    obstacles: list[Box] = []  # hull add-ons parts must not cut into
    col_bodies: list[HullLayout] = []  # lofted bodies, cut into convex segments for collision
    col_extras: list[list] = []  # point sets of hull add-ons and pylons (one convex shape each)
    pylon_verts: list = []  # pylons belong to the engines role
    n_eng, r_req = p["engines"]["count"], 0.5 * p["engines"]["size"]
    module = 0.6 * beam * (0.7 + 0.6 * p["cargo"]["size"])

    def add_body_boxes(lay, applies_to):
        for a, b in zip(lay.stations, lay.stations[1:]):
            y0, y1 = (-0.5 + a.t) * length, (-0.5 + b.t) * length
            w = max(a.half_width, b.half_width)
            obstacles.append(Box("hull", Vector((lay.x_offset - w, y0, -max(a.bottom, b.bottom))),
                                 Vector((lay.x_offset + w, y1, max(a.top, b.top))), applies_to))

    if design.plan == "twin":
        sub_beam = 0.5 * body_beam
        gap = 0.9 * sub_beam
        bodies = []
        for s in (1, -1):
            lay = layout_body(design, length, sub_beam, body_height, p["seed"])
            lay.x_offset = s * (sub_beam + 0.5 * gap)
            loft_body(hull_bm, lay, length, chamfer, ridge)
            add_body_boxes(lay, {"rig"})
            bodies.append(lay)
            col_bodies.append(lay)
        lay = bodies[0]
        for f in (0.25, 0.75):  # bridges between the hulls
            y = lay.y_mid[0] + f * (lay.y_mid[1] - lay.y_mid[0])
            size = Vector((2 * (sub_beam + 0.5 * gap), 0.1 * length, 0.35 * body_height))
            centre = Vector((0, y, 0.15 * body_height))
            col_extras.append(_grab(hull_bm, lambda c=centre, sz=size: shapes.box(hull_bm, c, sz)))
            obstacles.append(Box("bridge", centre - size / 2, centre + size / 2, {"rig", "module", "engine"}))
        for b in bodies:
            sk, py, r = _engine_sockets(n_eng // 2, r_req, b.x_offset, b.y_tail, b.stations[0],
                                        design.tail == "outboard")
            if sk and r < r_req * 0.99:
                warnings.append(f"{FIT_ISSUE}engines.size capped to {2 * r:.2f} to fit the tail")
            sockets += sk
            for a, c, rr in py:
                col_extras.append(_grab(parts_bm, lambda a=a, c=c, rr=rr: shapes.beam(parts_bm, a, c, 0.5 * rr, 0.25 * rr, 0), pylon_verts))
            sockets += _side_sockets(b, length, module, b.x_offset, outer_only_sign=1 if b.x_offset > 0 else -1)
            sockets += _top_sockets(b, length, module, chamfer, ridge, single=True)
        if n_eng % 2:
            warnings.append(f"{FIT_ISSUE}twin hulls need an even engine count; one engine dropped")
        sockets.append(Socket("nose", Vector((0, lay.y_mid[1], 0.0)), Vector((0, 1, 0)), 0.45 * gap))
    else:
        lay = layout_body(design, length, body_beam, body_height, p["seed"])
        loft_body(hull_bm, lay, length, chamfer, ridge)
        col_bodies.append(lay)
        tail_face = lay.stations[0]
        sk, py, r = _engine_sockets(n_eng, r_req, 0.0, lay.y_tail, tail_face, design.tail == "outboard")
        if r < r_req * 0.99:
            warnings.append(f"{FIT_ISSUE}engines.size capped to {2 * r:.2f} to fit the tail")
        sockets += sk
        for a, c, rr in py:
            col_extras.append(_grab(parts_bm, lambda a=a, c=c, rr=rr: shapes.beam(parts_bm, a, c, 0.5 * rr, 0.25 * rr, 0), pylon_verts))
        front = lay.stations[-1]
        if design.mid == "sponson":
            pw = 0.32 * body_beam
            y_a, y_b = lay.y_mid
            pod_a, pod_b = y_a + 0.05 * length, y_b - 0.02 * length
            pod_top, pod_bottom = 0.5 * body_height * 0.55, 0.5 * body_height * 0.45
            for s in (1, -1):
                x = s * (section_at(lay, 0.5 * (y_a + y_b), length).half_width + 0.5 * pw)
                col_extras.append(_grab(hull_bm, lambda x=x: _mini_body(
                    hull_bm, x, pod_a, pod_b, pw, pod_top, pod_bottom, chamfer, ridge, length, pointed=False)))
                obstacles.append(Box("pod", Vector((x - pw, pod_a, -pod_bottom)), Vector((x + pw, pod_b, pod_top)),
                                     {"rig", "module", "engine", "wing"}))
            # modules mount on the pods' outer faces instead of the hull side
            x_out = section_at(lay, 0.5 * (y_a + y_b), length).half_width + 1.5 * pw
            span_a, span_b = pod_a + 0.2 * (pod_b - pod_a), pod_b - 0.3 * (pod_b - pod_a)
            cols = max(int((span_b - span_a) // (2.1 * module)) + 1, 1)  # centre spacing >= 2.1 module
            if cols > 1 and (span_b - span_a) / (cols - 1) < 2.1 * module:
                cols -= 1
            for c in range(cols):
                y = span_a + (span_b - span_a) * (c / (cols - 1) if cols > 1 else 0.5)
                for s in (1, -1):
                    sockets.append(Socket("side", Vector((s * x_out, y, 0.0)), Vector((s, 0, 0)), module))
        else:
            sockets += _side_sockets(lay, length, module, 0.0)
        sockets += _top_sockets(lay, length, module, chamfer, ridge)
        if design.plan == "fork":
            pw = 0.3 * front.half_width
            for s in (1, -1):
                x = s * (front.half_width - pw * 0.6)
                y0, y1 = lay.y_front - 0.08 * length, lay.y_front + 0.22 * length
                col_extras.append(_grab(hull_bm, lambda x=x, y0=y0, y1=y1: _mini_body(
                    hull_bm, x, y0, y1, pw, front.top * 0.8, front.bottom * 0.8, chamfer, ridge, length)))
                obstacles.append(Box("prong", Vector((x - pw, y0, -front.bottom)), Vector((x + pw, y1, front.top)),
                                     {"rig", "module", "wing"}))
            inner = front.half_width - 1.6 * pw  # inner face of the prongs
            sockets.append(Socket("nose", Vector((0, lay.y_front, 0)), Vector((0, 1, 0)), 0.9 * inner))
        elif not lay.point_nose:
            sockets.append(Socket("nose", Vector((0, lay.y_front, 0)), Vector((0, 1, 0)), 0.95 * front.half_width))

    for i, sk in enumerate(sockets):
        sk.name = sk.name or f"Socket_{sk.kind}_{i}"

    # ---- parts on sockets, each tracked as an instance for the collision check
    instances: list[Instance] = []
    pick = random.Random(f"{stream}:parts")

    def place(kind, group, builder, sk):
        before = set(parts_bm.verts)
        builder()
        verts = [v for v in parts_bm.verts if v not in before]
        instances.append(Instance(kind, group, sk.name, verts, sk))

    for sk in (s for s in sockets if s.kind == "engine"):
        place("engine", sk.name, lambda sk=sk: engine_designs.build(parts_bm, engine_design, sk.pos, sk.normal,
                                                                    sk.radius), sk)

    wing_layout = bodies[0] if design.plan == "twin" else lay
    for i, piece in enumerate(wings.add_wings(parts_bm, p, _WingHull(length, wing_layout))):
        x, y, z = piece.root
        sides = (1, -1) if piece.kind == "pair" else (0,)
        for side in sides:
            normal = Vector(piece.normal) * (side or 1)
            kind = "wing" if piece.kind == "pair" else "fin"
            sk = Socket(kind, Vector((side * x, y, z)), normal, 0.5 * length,
                        f"Socket_{kind}_{i}" + ("" if side == 0 else ("_r" if side > 0 else "_l")))
            verts = [v for v in piece.verts if side == 0 or (v.co.x > 0) == (side > 0)]
            instances.append(Instance("wing", f"wings_{i}", sk.name, verts, sk))
            sockets.append(sk)

    mining_kind = p["mining"]["type"]
    nose_sockets = [s for s in sockets if s.kind == "nose"]
    if rig_design is None and mining_kind != "none":
        rig_design = pick.choice(rig_designs.designs_of(mining_kind))
    if rig_design is not None and mining_kind != "none":
        if nose_sockets:
            sk = nose_sockets[0]
            radius = beam * (0.4 + 0.5 * p["mining"]["size"])  # from the model, not the socket
            if radius > sk.radius:
                warnings.append(f"{FIT_ISSUE}mining rig shrunk to fit the nose ({sk.radius:.2f} < {radius:.2f})")
                radius = sk.radius
            place("rig", "rig", lambda: rig_designs.build(parts_bm, rig_design, sk.pos, sk.normal, radius), sk)
        else:
            warnings.append(f"{FIT_ISSUE}mining rig dropped: this nose has no mount face")

    cargo_kind = p["cargo"]["type"]
    if module_design is None and cargo_kind != "none":
        module_design = pick.choice(module_designs.designs_of(cargo_kind))
    wanted = p["cargo"]["modules"] if cargo_kind != "none" else 0
    # modules go on mirrored socket pairs (front to back), sides first, then the roof
    def pairs_of(kind):
        socks = sorted((s for s in sockets if s.kind == kind), key=lambda s: (-s.pos.y, abs(s.pos.x), s.pos.x))
        return [socks[i:i + 2] for i in range(0, len(socks) - 1, 2)]

    placed = 0
    for pair in pairs_of("side") + pairs_of("top"):
        if placed + 2 > wanted:
            break
        for sk in pair:
            place("module", f"modules_{placed}", lambda sk=sk: module_designs.build(parts_bm, module_design, sk.pos,
                                                                                    sk.normal, sk.radius), sk)
        placed += 2
    if placed < wanted:
        warnings.append(f"{FIT_ISSUE}cargo.modules: placed {placed} of {wanted} (pairs only, limited by side and roof sockets)")

    conflicts = find_conflicts(instances, obstacles)
    if resolve:
        dropped = resolve_conflicts(parts_bm, instances, obstacles)
        for group in dropped:
            warnings.append(f"{FIT_ISSUE}{group} dropped: collided with another part")

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

    _add_greebles(p, stream, parts_bm, instances, obstacles, col_bodies, length, beam, chamfer, hull_bm, tris)

    col_pieces = [seg for b in col_bodies for seg in collision.merge(collision.body_segments(b, length, chamfer, ridge))]
    col_pieces += col_extras
    col_pieces += [[v.co.copy() for v in i.verts] for i in instances
                   if i.kind != "greeble" and i.verts and i.verts[0].is_valid]  # greebles: too small to collide

    role_of = {"engine": "engines", "rig": "mining", "module": "cargo", "wing": "wings", "greeble": "greebles"}
    parts_bm.verts.index_update()
    role_verts: dict[str, set] = {"engines": {v.index for v in pylon_verts if v.is_valid}}
    for inst in instances:
        if inst.verts and inst.verts[0].is_valid:
            role_verts.setdefault(role_of[inst.kind], set()).update(v.index for v in inst.verts)
    pieces = [("Ship_Hull", "hull", hull_bm, ("hull",))]
    for role, idx in role_verts.items():
        if not idx:
            continue
        bm = parts_bm.copy()
        bm.verts.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index not in idx], context="VERTS")
        slots = ("hull", "glow", "cargo") if role == "wings" else ("accent", "glow", "cargo")  # wings in hull paint
        pieces.append((f"Ship_{role.capitalize()}", role, bm, slots))
    parts_bm.free()

    parts = []
    for name, role, bm, mat_keys in pieces:
        if not bm.faces:
            bm.free()
            continue
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
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
        parts.append(obj)

    colliders = collision.build_colliders(col_pieces, coll, root)

    socket_objects = []
    for sk in sockets:  # hardpoints for Godot (local +Y = socket normal -> Godot -Z forward)
        empty = bpy.data.objects.new(sk.name, None)
        empty.empty_display_type = "SINGLE_ARROW"
        empty.empty_display_size = sk.radius
        empty.location = sk.pos
        empty.rotation_euler = sk.normal.to_track_quat("Y", "Z").to_euler()
        empty["shipgen_socket"] = {"kind": sk.kind, "radius": round(sk.radius, 4)}
        coll.objects.link(empty)
        empty.parent = root
        socket_objects.append(empty)

    def fitted(kind, names, design):  # only what is really on the ship after resolving
        return names[design] if any(i.kind == kind and i.verts for i in instances) else "none"

    loadout = {
        "engine": fitted("engine", engine_designs.NAMES, engine_design),
        "rig": fitted("rig", rig_designs.NAMES, rig_design),
        "module": fitted("module", module_designs.NAMES, module_design),
        "wings": p["wings"]["type"] if any(i.kind == "wing" and i.verts for i in instances) else "none",
    }
    ship = KitShip(root=root, parts=parts, params=p, warnings=warnings, design=design, sockets=sockets,
                   socket_objects=socket_objects, colliders=colliders, engine_design=engine_design, loadout=loadout,
                   conflicts=conflicts, instances=instances, obstacles=obstacles)
    nose_y = nose_sockets[0].pos.y if nose_sockets else 0.5 * length
    ref_bm = bmesh.new()  # the model's reference hull: hull stats come from it, the design is looks
    loft_body(ref_bm, reference, length, chamfer, ridge)
    reference_hull = {"volume": abs(ref_bm.calc_volume()), "area": sum(f.calc_area() for f in ref_bm.faces)}
    ref_bm.free()
    ship.gameplay = _normalized_stats(ship, _StatsHull(length, CLASS_PROFILES[cls], nose_y), engine_design,
                                      rig_design, module_design, reference_hull)
    root["shipgen"] = {"seed": p["seed"], "class": p["class"], "design": design.label(), **loadout,
                       "stats": ship.gameplay}
    return ship


def _normalized_stats(ship, hull, engine_design, rig_design, module_design, reference_hull) -> dict:
    """stats.compute, made independent of the seed's design choices:

    - hull mass, internal hold and hull HP come from the model's reference hull;
    - each part design is scaled to the mean of its kind (normalize.py).
    Parts still count with their real geometry (size, count), so the model params decide.
    """
    g = stats.compute(ship, hull, KIT_MINING_EFFICIENCY)
    actual_hull = stats._measure(next(o for o in ship.parts if o["shipgen_role"] == "hull"))
    profile = hull.profile

    mass = g["mass_t"] + stats.DENSITY["hull"] * (reference_hull["volume"] - actual_hull["volume"])
    # part masses as if every design weighed the mean of its kind
    for role, factor in (("engines", normalize.engine_volume_factors()[engine_design]),
                         ("mining", normalize.rig_volume_factors()[rig_design] if rig_design is not None else 1.0),
                         ("cargo", normalize.module_factors()[module_design] if module_design is not None else 1.0)):
        obj = next((o for o in ship.parts if o["shipgen_role"] == role), None)
        if obj is not None:
            mass += stats.DENSITY[role] * stats._measure(obj)["volume"] * (factor - 1.0)
    thrust = g["thrust_kn"] * normalize.engine_factors()[engine_design]
    g["mass_t"] = round(mass, 2)
    g["thrust_kn"] = round(thrust, 2)
    g["acceleration_ms2"] = round(thrust / mass, 2) if mass else 0.0
    g["turn_rate_deg_s2"] = round(math.degrees(0.1 * 6.0 * thrust / (mass * hull.length)), 2) if mass else 0.0
    g["hull_hp"] = round(reference_hull["area"] * stats.HULL_HP_PER_M2 * profile.armor)

    cargo = {"general_m3": 0.0, "ore_m3": 0.0, "fluid_m3": 0.0, "passengers": 0}
    cargo[profile.hold_kind] += reference_hull["volume"] * profile.hold
    cargo_obj = next((o for o in ship.parts if o["shipgen_role"] == "cargo"), None)
    if cargo_obj is not None and ship.loadout["module"] != "none":
        usable = stats._measure(cargo_obj)["volume"] * stats.USABLE_MODULE_VOLUME
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


def _add_greebles(p, stream, bm, instances, obstacles, bodies, length, beam, chamfer, hull_bm, tris) -> None:
    """Small details on free roof / side spots, in mirrored pairs; skipped where they would touch
    anything else, and only while the triangle budget lasts."""
    density = p["greeble_density"]
    if density <= 0:
        return
    rng = random.Random(f"{stream}:greebles")
    style = rng.sample(range(len(greeble_designs.DESIGNS)), GREEBLE_STYLE)
    taken = [i.box() for i in instances if i.verts and i.verts[0].is_valid] + list(obstacles)
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
    kind: str  # "engine", "rig", "module"
    group: str  # instances of one group are dropped together (mirrored module pairs)
    socket: str
    verts: list
    sk: Socket

    def box(self) -> Box:
        """Bounding box of the part outside its mount (the embedded root may sit in the hull)."""
        outside = [v.co for v in self.verts if (v.co - self.sk.pos).dot(self.sk.normal) > 0.05 * self.sk.radius]
        pts = outside or [v.co for v in self.verts]
        lo = Vector(tuple(min(c[i] for c in pts) for i in range(3)))
        hi = Vector(tuple(max(c[i] for c in pts) for i in range(3)))
        return Box(self.kind, lo, hi)


PRIORITY = {"greeble": -1, "module": 0, "wing": 1, "rig": 2, "engine": 3}  # lowest is dropped first


def find_conflicts_after(ship: "KitShip") -> list:
    """Collisions left in the finished ship (should always be empty when resolved)."""
    return find_conflicts(ship.instances, ship.obstacles)


def find_conflicts(instances, obstacles) -> list[tuple[str, str]]:
    out = []
    live = [i for i in instances if i.verts and i.verts[0].is_valid]
    boxes = {id(i): i.box() for i in live}
    for a_i, a in enumerate(live):
        for b in live[a_i + 1:]:
            if a.group != b.group and boxes[id(a)].overlaps(boxes[id(b)]):
                out.append((a.kind, b.kind) if a.kind <= b.kind else (b.kind, a.kind))
        for ob in obstacles:
            if a.kind in ob.applies_to and boxes[id(a)].overlaps(ob):
                out.append((a.kind, ob.what))
    return out


def resolve_conflicts(bm, instances, obstacles) -> list[str]:
    """Drop the lowest-priority group involved in a collision until none is left."""
    dropped = []
    while True:
        live = [i for i in instances if i.verts and i.verts[0].is_valid]
        boxes = {id(i): i.box() for i in live}
        victim = None
        for a_i, a in enumerate(live):
            hits = [b for b in live[a_i + 1:] if a.group != b.group and boxes[id(a)].overlaps(boxes[id(b)])]
            hits += [None for ob in obstacles if a.kind in ob.applies_to and boxes[id(a)].overlaps(ob)]
            for b in hits:
                cand = a if b is None or PRIORITY[a.kind] <= PRIORITY[b.kind] else b
                if victim is None or PRIORITY[cand.kind] < PRIORITY[victim.kind]:
                    victim = cand
        if victim is None:
            return dropped
        group = [i for i in live if i.group == victim.group]
        bmesh.ops.delete(bm, geom=[v for i in group for v in i.verts], context="VERTS")
        for i in group:
            i.verts = []
        dropped.append(victim.group)
