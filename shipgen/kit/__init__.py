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
from ..generator import Ship, clear, materials, shapes
from ..generator.hull import Station
from . import engine_designs, module_designs, rig_designs
from .hull_kit import Design, HullLayout, Socket, layout_body, loft_body, section_at, RIDGE

COLLECTION = "ShipGen"
OUTBOARD_TRIGGER = 1.3  # requested engine radius / what fits the tail face


@dataclass
class KitShip(Ship):
    design: Design | None = None
    sockets: list[Socket] = field(default_factory=list)
    socket_objects: list = field(default_factory=list)
    engine_design: int = 0
    loadout: dict = field(default_factory=dict)
    conflicts: list = field(default_factory=list)  # collisions found before resolving
    instances: list = field(default_factory=list)
    obstacles: list = field(default_factory=list)

    @property
    def objects(self):
        return [self.root, *self.parts, *self.socket_objects]


# ---------------------------------------------------------------- hull pieces

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


# ---------------------------------------------------------------- assembly

def build(raw_params: dict, plan=None, tail=None, mid=None, nose=None, engine_design=None, rig_design=None,
          module_design=None, resolve: bool = True) -> KitShip:
    """Build a kit ship. Design choices default to the seed's pick within the class kit;
    ``resolve=False`` keeps colliding parts (to inspect conflicts)."""
    p = params_mod.individualize(params_mod.validate(raw_params).params)
    cls = p["class"] if p["class"] in RIDGE else "freighter"
    # models of one class differ by role, so the role is part of the seed streams
    stream = f"{p['seed']}:{cls}:{p['mining']['type']}:{p['cargo']['type']}"
    design = Design.pick(cls, stream, plan=plan, tail=tail, mid=mid, nose=nose)
    if engine_design is None:
        engine_design = random.Random(f"{stream}:engine_design").randrange(len(engine_designs.DESIGNS))

    clear(COLLECTION)
    coll = bpy.data.collections.new(COLLECTION)
    bpy.context.scene.collection.children.link(coll)
    root = bpy.data.objects.new("Ship", None)
    coll.objects.link(root)
    mats = materials.create_materials(p)

    hp = p["hull"]
    length = hp["length"]
    beam = 0.5 * length * hp["width_ratio"]
    height = beam * hp["height_ratio"]
    chamfer = min(max(1.0 - hp["squareness"], 0.0), 1.0)
    ridge = RIDGE[cls]

    hull_bm = bmesh.new()
    parts_bm = bmesh.new()  # engines, pylons, rigs, modules (material 0 accent, 1 glow, 2 cargo)
    sockets: list[Socket] = []
    warnings: list[str] = []
    obstacles: list[Box] = []  # hull add-ons parts must not cut into
    n_eng, r_req = p["engines"]["count"], 0.5 * p["engines"]["size"]
    module = 0.6 * beam * (0.7 + 0.6 * p["cargo"]["size"])

    def add_body_boxes(lay, applies_to):
        for a, b in zip(lay.stations, lay.stations[1:]):
            y0, y1 = (-0.5 + a.t) * length, (-0.5 + b.t) * length
            w = max(a.half_width, b.half_width)
            obstacles.append(Box("hull", Vector((lay.x_offset - w, y0, -max(a.bottom, b.bottom))),
                                 Vector((lay.x_offset + w, y1, max(a.top, b.top))), applies_to))

    if design.plan == "twin":
        sub_beam = 0.5 * beam
        gap = 0.9 * sub_beam
        bodies = []
        for s in (1, -1):
            lay = layout_body(design, length, sub_beam, height, p["seed"])
            lay.x_offset = s * (sub_beam + 0.5 * gap)
            loft_body(hull_bm, lay, length, chamfer, ridge)
            add_body_boxes(lay, {"rig"})
            bodies.append(lay)
        lay = bodies[0]
        for f in (0.25, 0.75):  # bridges between the hulls
            y = lay.y_mid[0] + f * (lay.y_mid[1] - lay.y_mid[0])
            size = Vector((2 * (sub_beam + 0.5 * gap), 0.1 * length, 0.35 * height))
            centre = Vector((0, y, 0.15 * height))
            shapes.box(hull_bm, centre, size)
            obstacles.append(Box("bridge", centre - size / 2, centre + size / 2, {"rig", "module", "engine"}))
        for b in bodies:
            sk, py, r = _engine_sockets(n_eng // 2, r_req, b.x_offset, b.y_tail, b.stations[0],
                                        design.tail == "outboard")
            sockets += sk
            for a, c, rr in py:
                shapes.beam(parts_bm, a, c, 0.5 * rr, 0.25 * rr, 0)
            sockets += _side_sockets(b, length, module, b.x_offset, outer_only_sign=1 if b.x_offset > 0 else -1)
        if n_eng % 2:
            warnings.append("twin hulls need an even engine count; one engine dropped")
        sockets.append(Socket("nose", Vector((0, lay.y_mid[1], 0.0)), Vector((0, 1, 0)), 0.45 * gap))
    else:
        lay = layout_body(design, length, beam, height, p["seed"])
        loft_body(hull_bm, lay, length, chamfer, ridge)
        tail_face = lay.stations[0]
        sk, py, r = _engine_sockets(n_eng, r_req, 0.0, lay.y_tail, tail_face, design.tail == "outboard")
        if r < r_req * 0.99:
            warnings.append(f"engines.size capped to {2 * r:.2f} to fit the tail")
        sockets += sk
        for a, c, rr in py:
            shapes.beam(parts_bm, a, c, 0.5 * rr, 0.25 * rr, 0)
        front = lay.stations[-1]
        if design.mid == "sponson":
            pw = 0.32 * beam
            y_a, y_b = lay.y_mid
            pod_a, pod_b = y_a + 0.05 * length, y_b - 0.02 * length
            pod_top, pod_bottom = 0.5 * height * 0.55, 0.5 * height * 0.45
            for s in (1, -1):
                x = s * (section_at(lay, 0.5 * (y_a + y_b), length).half_width + 0.5 * pw)
                _mini_body(hull_bm, x, pod_a, pod_b, pw, pod_top, pod_bottom, chamfer, ridge, length, pointed=False)
                obstacles.append(Box("pod", Vector((x - pw, pod_a, -pod_bottom)), Vector((x + pw, pod_b, pod_top)),
                                     {"rig", "module", "engine"}))
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
        if design.plan == "fork":
            pw = 0.3 * front.half_width
            for s in (1, -1):
                x = s * (front.half_width - pw * 0.6)
                y0, y1 = lay.y_front - 0.08 * length, lay.y_front + 0.22 * length
                _mini_body(hull_bm, x, y0, y1, pw, front.top * 0.8, front.bottom * 0.8, chamfer, ridge, length)
                obstacles.append(Box("prong", Vector((x - pw, y0, -front.bottom)), Vector((x + pw, y1, front.top)),
                                     {"rig", "module"}))
            inner = front.half_width - 1.6 * pw  # inner face of the prongs
            sockets.append(Socket("nose", Vector((0, lay.y_front, 0)), Vector((0, 1, 0)), 0.9 * inner))
        elif not lay.point_nose:
            sockets.append(Socket("nose", Vector((0, lay.y_front, 0)), Vector((0, 1, 0)),
                                  min(front.half_width, front.top + front.bottom)))

    for i, sk in enumerate(sockets):
        sk.name = f"Socket_{sk.kind}_{i}"

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

    mining_kind = p["mining"]["type"]
    nose_sockets = [s for s in sockets if s.kind == "nose"]
    if rig_design is None and mining_kind != "none":
        rig_design = pick.choice(rig_designs.designs_of(mining_kind))
    if rig_design is not None and mining_kind != "none":
        if nose_sockets:
            sk = nose_sockets[0]
            radius = sk.radius * (0.6 + 0.4 * p["mining"]["size"])
            place("rig", "rig", lambda: rig_designs.build(parts_bm, rig_design, sk.pos, sk.normal, radius), sk)
        else:
            warnings.append("mining rig dropped: this nose has no mount face")

    cargo_kind = p["cargo"]["type"]
    if module_design is None and cargo_kind != "none":
        module_design = pick.choice(module_designs.designs_of(cargo_kind))
    wanted = p["cargo"]["modules"] if cargo_kind != "none" else 0
    # modules go on mirrored socket pairs (front to back), so the ship stays symmetric
    sides = sorted((s for s in sockets if s.kind == "side"), key=lambda s: (-s.pos.y, abs(s.pos.x), s.pos.x))
    placed = 0
    for pair in (sides[i:i + 2] for i in range(0, len(sides) - 1, 2)):
        if placed + 2 > wanted:
            break
        for sk in pair:
            place("module", f"modules_{placed}", lambda sk=sk: module_designs.build(parts_bm, module_design, sk.pos,
                                                                                    sk.normal, sk.radius), sk)
        placed += 2
    if placed < wanted:
        warnings.append(f"cargo.modules: placed {placed} of {wanted} (pairs only, limited by side sockets)")

    conflicts = find_conflicts(instances, obstacles)
    if resolve:
        dropped = resolve_conflicts(parts_bm, instances, obstacles)
        for group in dropped:
            warnings.append(f"{group} dropped: collided with another part")

    parts = []
    for name, bm, mat_keys in (("Ship_Hull", hull_bm, ("hull",)), ("Ship_Parts", parts_bm, ("accent", "glow", "cargo"))):
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
        obj["shipgen_role"] = name.removeprefix("Ship_").lower()
        parts.append(obj)

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
    }
    root["shipgen"] = {"seed": p["seed"], "class": p["class"], "design": design.label(), **loadout}
    return KitShip(root=root, parts=parts, params=p, warnings=warnings, design=design, sockets=sockets,
                   socket_objects=socket_objects, engine_design=engine_design, loadout=loadout,
                   conflicts=conflicts, instances=instances, obstacles=obstacles)


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


PRIORITY = {"module": 0, "rig": 1, "engine": 2}  # lowest is dropped first


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
