"""Ship wrecks: a shop model (kit ship), broken apart, burnt and partly stripped.

    wreck = wrecks.generate({"seed": 3, "damage": 0.6}, ship_params)

The ship is built by the kit builder from ``ship_params`` (so a wreck looks like the ship the
player knows), then:

- the hull (with its greebles) is cut by ``breaks`` tilted planes into segments ``Hull_<k>``;
  the torn ends get a ragged rim and a dark, hollow cap; segments drift apart and turn a little;
- ``holes`` pits are punched into the plating, ``burn`` scorches faces, glow goes dark;
- every fitted part (``Engine_<n>``, ``Rig_0``, ``Module_<n>``, ``Wings_<i>``, ``Fin_<i>``)
  keeps its name and ``shipgen_part`` extras and gets a state (``shipgen_salvage``): intact or
  damaged (still mounted, on its segment), detached (drifting free near the wreck) or destroyed
  (gone, shattered into ``Debris_<i>``). Parts that sat across a break are always destroyed.

Colliders: each segment's ``-convcolonly`` pieces are the ship's hull pieces clipped by the
break planes (still convex, they cover the segment: rims, caps and pits only move inwards);
parts keep their own; debris has the exact hull of its vertices.

Generating a wreck replaces the ship in the ``ShipGen`` collection (it is built as one).
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

from .. import meshutil, stats
from ..asteroids import geometry as geo
from ..generator import Ship
from ..generator.materials import MATERIAL_PREFIX, _principled
from ..kit import collision
from . import params as params_mod

STATES = ("intact", "damaged", "detached", "destroyed")
SCRAP_DENSITY = stats.DENSITY["hull"]  # t/m^3 of hull segments and debris


@dataclass
class Wreck:
    root: object
    segments: list  # hull pieces Hull_<k>
    parts: list  # every visible mesh: segments, remaining parts, debris
    params: dict
    ship_params: dict  # the ship as built before it was wrecked
    warnings: list[str] = field(default_factory=list)
    colliders: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    bounds = Ship.bounds

    @property
    def objects(self):
        return [self.root, *self.parts, *self.colliders]


def generate(raw_params: dict, ship_params: dict) -> Wreck:
    """Build a wreck of the ship ``ship_params`` describes (kit builder, seed = ``ship_seed``)."""
    from .. import generator

    result = params_mod.validate(raw_params)
    p = result.params
    sp = copy.deepcopy(ship_params)
    sp["builder"] = "kit"
    sp["seed"] = p["ship_seed"] if p["ship_seed"] >= 0 else p["seed"]
    style = sp.setdefault("style", {})
    style["wear"] = max(style.get("wear", 0.0), 0.5 + 0.5 * p["damage"])  # old, dull paint
    ship = generator.generate(sp)
    warnings = list(result.warnings) + [w for w in ship.warnings if not w.startswith("fit:")]
    rng = random.Random(f"{p['seed']}:wreck")
    wreck = _Wrecker(p, ship, rng).run()
    wreck.warnings = warnings
    return wreck


def _materials() -> dict:
    return {
        "inside": _principled("Wreck_Inside", (0.03, 0.03, 0.035), 0.4, 0.8),
        "burnt": _principled("Wreck_Burnt", (0.025, 0.02, 0.018), 0.1, 0.95),
        "dead": _principled("Wreck_Dead", (0.05, 0.05, 0.055), 0.2, 0.6),  # glow that went out
    }


def _is_glow(mat) -> bool:
    return mat is not None and mat.name.startswith(MATERIAL_PREFIX + "Glow")


def _bm_of(obj, matrix=None):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    if matrix is not None:
        bm.transform(matrix)
    return bm


def _volume(bm) -> float:
    return meshutil.volume(bm)


class _Wrecker:
    def __init__(self, p, ship, rng: random.Random):
        self.p, self.ship, self.rng = p, ship, rng
        self.coll = bpy.data.collections["ShipGen"]
        self.root = ship.root
        self.length = ship.params["hull"]["length"]
        self.beam = 0.5 * self.length * ship.params["hull"]["width_ratio"]
        self.mats = _materials()

    # ------------------------------------------------------------ plan

    def _planes(self) -> list[tuple[Vector, float]]:
        """Break planes, front to back sorted by their y; normals point to the nose."""
        n = self.p["breaks"]
        if n == 0:
            return []
        span = 0.62 * self.length  # breaks stay off the very ends
        slot = span / n
        out = []
        for i in range(n):
            y = -0.5 * span + slot * (i + self.rng.uniform(0.3, 0.7))
            normal = Vector((self.rng.uniform(-0.35, 0.35), 1.0, self.rng.uniform(-0.35, 0.35))).normalized()
            out.append((normal, normal.dot(Vector((0.0, y, 0.0)))))
        return out

    def _segment_of(self, point: Vector) -> int:
        return sum(1 for n, d in self.planes if n.dot(point) > d)

    def _straddles(self, points) -> bool:
        for n, d in self.planes:
            s = [n.dot(q) - d for q in points]
            lo, hi = min(s), max(s)
            if lo < 0 < hi and min(-lo, hi) > 0.15 * (hi - lo):
                return True
        return False

    def _fate(self, obj, points) -> str:
        if self._straddles(points):
            return "destroyed"
        dmg = self.p["damage"]
        r = self.rng.random()
        if r < 0.3 * dmg:
            return "destroyed"
        if r < 0.45 * dmg:
            return "detached"
        if r < 0.9 * dmg:
            return "damaged"
        return "intact"

    # ------------------------------------------------------------ run

    def run(self) -> Wreck:
        ship = self.ship
        self.planes = self._planes()
        for obj in ship.parts:  # the lights are out
            for i, mat in enumerate(obj.data.materials):
                if _is_glow(mat):
                    obj.data.materials[i] = self.mats["dead"]

        hull = next(o for o in ship.parts if o.name == "Ship_Hull")
        greebles = [o for o in ship.parts if o.name == "Ship_Greebles"]
        parts = [o for o in ship.parts if "shipgen_part" in o]
        hull_cols = [c for c in ship.colliders if c.parent is ship.root]

        fates = {}
        for obj in parts:
            points = [obj.matrix_basis @ v.co for v in obj.data.vertices]
            fates[obj.name] = (self._fate(obj, points), points)

        segments, seg_cols, rests = self._segments(hull, greebles, hull_cols)
        debris = []
        kept = []
        salvage = []
        for obj in parts:
            fate, points = fates[obj.name]
            info = dict(obj["shipgen_part"].to_dict())
            role = obj["shipgen_role"]
            if fate == "destroyed":
                debris += self._shatter(obj, points)
                salvage.append({"name": obj.name, "kind": info["kind"], "design": info["design"],
                                "state": fate, "condition": 0.0, "mass_t": 0.0})
                for child in list(obj.children):
                    _remove(child)
                _remove(obj)
                continue
            condition = {"intact": self.rng.uniform(0.85, 1.0), "damaged": self.rng.uniform(0.3, 0.7),
                         "detached": self.rng.uniform(0.4, 0.9)}[fate]
            if fate == "detached":
                self._detach(obj)
            else:
                k = self._segment_of(obj.matrix_basis.translation)
                if fate == "damaged":  # bent on its mount
                    obj.matrix_basis = obj.matrix_basis @ Euler(
                        [self.rng.uniform(-0.15, 0.15) for _ in range(3)]).to_matrix().to_4x4()
                obj.parent = segments[k]
                obj.matrix_parent_inverse = Matrix.Identity(4)
                obj.matrix_basis = rests[k] @ obj.matrix_basis
            if fate != "intact" or self.rng.random() < self.p["burn"]:
                self._scorch(obj, 0.25 + 0.5 * self.p["burn"] if fate != "intact" else 0.15 * self.p["burn"])
            bm = _bm_of(obj)
            mass = round(stats.DENSITY.get(role, 0.2) * _volume(bm), 2)
            bm.free()
            entry = {"state": fate, "condition": round(condition, 2), "mass_t": mass}
            obj["shipgen_salvage"] = entry
            salvage.append({"name": obj.name, "kind": info["kind"], "design": info["design"], **entry})
            kept.append(obj)
        debris += self._fragments(segments, rests)

        for obj in [*ship.socket_objects, *hull_cols, hull, *greebles]:
            _remove(obj)
        self.root.name = "Wreck"
        ship_info = dict(self.root["shipgen"].to_dict())
        del self.root["shipgen"]
        bpy.context.view_layer.update()

        colliders = seg_cols + [c for o in kept for c in o.children if c.get("shipgen_role") == "collision"]
        colliders += [c for d in debris for c in d.children]
        wreck = Wreck(root=self.root, segments=segments, parts=[*segments, *kept, *debris], params=self.p,
                      ship_params=ship.params, colliders=colliders)
        wreck.stats = self._stats(ship_info, segments, debris, salvage)
        self.root["shipgen_wreck"] = {"seed": self.p["seed"], "ship_seed": ship.params["seed"],
                                      "class": ship.params["class"], "stats": wreck.stats}
        return wreck

    # ------------------------------------------------------------ hull segments

    def _segments(self, hull, greebles, hull_cols):
        """Cut hull + greebles into segments; returns (segment objects, their colliders,
        rest matrices ship space -> segment space)."""
        slots = []  # materials of the joined hull mesh

        def slot(mat):
            if mat not in slots:
                slots.append(mat)
            return slots.index(mat)

        whole = bmesh.new()
        for obj in [hull, *greebles]:
            src = _bm_of(obj, obj.matrix_basis)
            remap = [slot(m) for m in obj.data.materials]
            for f in src.faces:
                f.material_index = remap[f.material_index] if f.material_index < len(remap) else 0
            tmp = bpy.data.meshes.new("_wreck_tmp")
            src.to_mesh(tmp)
            src.free()
            whole.from_mesh(tmp)
            bpy.data.meshes.remove(tmp)
        hull_slot = slot(hull.data.materials[0])
        inside, burnt = slot(self.mats["inside"]), slot(self.mats["burnt"])
        self._holes(whole, hull_slot, inside, burnt)
        self._burn_patches(whole, burnt, 0.06 * self.p["burn"])

        n_seg = len(self.planes) + 1
        seg_bms = []
        for k in range(n_seg):
            bm = whole.copy()
            cuts = []  # (outward normal of this segment's torn end, d)
            if k > 0:  # keep the front side of plane k-1
                n, d = self.planes[k - 1]
                bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-6,
                                       plane_co=n * d, plane_no=n, clear_inner=True)
                cuts.append((-n, -d))
            if k < n_seg - 1:
                n, d = self.planes[k]
                bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-6,
                                       plane_co=n * d, plane_no=n, clear_outer=True)
                cuts.append((n, d))
            if cuts:
                self._tear(bm, cuts, inside, burnt)
            seg_bms.append(bm)
        whole.free()

        # the biggest segment stays where the ship was; the others drift off their break
        vols = [_volume(bm) for bm in seg_bms]
        anchor = vols.index(max(vols))
        spread = self.p["spread"]
        segments, colliders, rests = [], [], []
        col_points = [[c.matrix_basis @ v.co for v in c.data.vertices] for c in hull_cols]
        for k, bm in enumerate(seg_bms):
            centre = geo.centroid([v.co for v in bm.verts])
            bm.transform(Matrix.Translation(-centre))
            offset = Vector()
            for i in range(min(k, anchor), max(k, anchor)):  # the breaks between it and the anchor
                n = self.planes[i][0]
                offset += n * (1 if k > anchor else -1) * self.length * (0.04 + 0.1 * spread) * self.rng.uniform(0.7, 1.3)
            turn = Euler([self.rng.uniform(-1, 1) * math.radians(25) * spread * (k != anchor) for _ in range(3)])
            mesh = bpy.data.meshes.new(f"Hull_{k}")
            bm.to_mesh(mesh)
            bm.free()
            for mat in slots:
                mesh.materials.append(mat)
            for poly in mesh.polygons:
                poly.use_smooth = False
            obj = bpy.data.objects.new(f"Hull_{k}", mesh)
            self.coll.objects.link(obj)
            obj.parent = self.root
            obj.matrix_basis = Matrix.Translation(centre + offset) @ turn.to_matrix().to_4x4()
            obj["shipgen_role"] = "hull"
            segments.append(obj)
            rests.append(Matrix.Translation(-centre))
            # colliders: the ship's convex hull pieces, clipped to this segment
            bounds = []
            if k > 0:
                n, d = self.planes[k - 1]
                bounds.append((-n, -d))
            if k < n_seg - 1:
                bounds.append(self.planes[k])
            j = 0
            for pts in col_points:
                for n, d in bounds:
                    if len(pts) >= 4 and min(n.dot(q) for q in pts) < d:
                        pts = geo.clip(pts, n, d)
                    elif len(pts) >= 4:
                        pts = []
                if len(pts) >= 4 and geo.volume(pts) > 1e-6 * self.length ** 3:
                    col = collision.convex_object([q - centre for q in pts], f"Hull_{k}_col_{j}{collision.SUFFIX}",
                                                  self.coll, obj)
                    if col is not None:
                        colliders.append(col)
                        j += 1
            obj["wreck_segment"] = {"index": k, "volume_m3": round(vols[k], 2),
                                    "mass_t": round(vols[k] * SCRAP_DENSITY, 2), "anchor": k == anchor}
        return segments, colliders, rests

    def _tear(self, bm, cuts, inside: int, burnt: int) -> None:
        """Ragged rim on every open end, then a dark cap pushed into the segment (hollow look)."""
        jag = 0.12 * self.beam
        boundary = [e for e in bm.edges if e.is_boundary]
        long = [e for e in boundary if e.calc_length() > 1.2 * jag]
        if long:
            bmesh.ops.subdivide_edges(bm, edges=long, cuts=1)
        rim = {v for e in bm.edges if e.is_boundary for v in e.verts}
        for v in rim:
            n_out = min(cuts, key=lambda c: abs(c[0].dot(v.co) - c[1]))[0]
            normals = [f.normal for f in v.link_faces]
            if not normals:
                continue
            fn = sum(normals, Vector()).normalized()
            t = -n_out - fn * (-n_out).dot(fn)  # back along the surface, away from the break
            if t.length < 1e-6:
                continue
            reach = min((e.calc_length() for e in v.link_edges if not e.is_boundary), default=0.0)
            v.co += t.normalized() * min(0.8 * reach, jag * self.rng.choice((0.1, 0.5, 1.0)) * self.rng.uniform(0.6, 1.0))
        for f in {f for v in rim for f in v.link_faces}:
            if self.rng.random() < 0.3 + 0.6 * self.p["burn"]:
                f.material_index = burnt
        bmesh.ops.triangulate(bm, faces=list({f for v in rim for f in v.link_faces if len(f.verts) > 3}))
        caps = _fill_loops(bm)
        for f in caps:
            f.material_index = inside
        poked = bmesh.ops.poke(bm, faces=caps)
        for v in poked["verts"]:
            n_out = min(cuts, key=lambda c: abs(c[0].dot(v.co) - c[1]))[0]
            radius = max((e.calc_length() for e in v.link_edges), default=0.0)
            v.co -= n_out * 0.35 * radius
        bmesh.ops.dissolve_degenerate(bm, edges=bm.edges[:], dist=1e-5 * self.length)
        meshutil.orient_outward(bm)

    def _holes(self, bm, hull_slot: int, inside: int, burnt: int) -> None:
        """Pits torn into the plating: big hull faces inset, the middle pushed in and broken."""
        faces = [f for f in bm.faces if f.material_index == hull_slot and f.calc_area() > (0.15 * self.beam) ** 2]
        self.rng.shuffle(faces)
        for f in faces[: self.p["holes"]]:
            if not f.is_valid:
                continue
            size = math.sqrt(f.calc_area())
            normal = f.normal.copy()
            res = bmesh.ops.inset_individual(bm, faces=[f], thickness=0.18 * size, depth=0.0)
            for g in res["faces"]:
                g.material_index = burnt
            f.material_index = inside
            for v in f.verts:
                v.co -= normal * 0.12 * size * self.rng.uniform(0.5, 1.0)
            poked = bmesh.ops.poke(bm, faces=[f])
            for v in poked["verts"]:
                v.co -= normal * 0.2 * size
        bmesh.ops.dissolve_degenerate(bm, edges=bm.edges[:], dist=1e-5 * self.length)

    def _burn_patches(self, bm, burnt: int, share: float) -> None:
        for f in bm.faces:
            if self.rng.random() < share:
                f.material_index = burnt

    # ------------------------------------------------------------ parts

    def _scorch(self, obj, share: float) -> None:
        mesh = obj.data
        mesh.materials.append(self.mats["burnt"])
        idx = len(mesh.materials) - 1
        for poly in mesh.polygons:
            if self.rng.random() < share:
                poly.material_index = idx

    def _detach(self, obj) -> None:
        """Torn off its mount: drifts away along the socket normal, tumbling."""
        m = obj.matrix_basis
        out = m.to_3x3() @ Vector((0, 1, 0))
        side = Vector((m.translation.x, 0, m.translation.z))
        direction = (out + 0.5 * (side.normalized() if side.length > 1e-6 else Vector())).normalized()
        dist = self.beam * (1.0 + 2.5 * self.p["spread"]) * self.rng.uniform(0.6, 1.2)
        tumble = Euler([self.rng.uniform(-1, 1) * math.radians(60) for _ in range(3)]).to_matrix().to_4x4()
        obj.matrix_basis = Matrix.Translation(direction * dist) @ m @ tumble

    def _shatter(self, obj, points) -> list:
        """A destroyed part: most of it is gone, a few shrunken convex shards are thrown outwards."""
        if geo.volume(points) < 1e-6:
            return []
        cells, _ = geo.voronoi_cells(points, geo.spread_seeds(points, 5, self.rng))
        self.rng.shuffle(cells)
        out = []
        for cell in cells[: self.rng.randint(1, 3)]:
            c = geo.centroid(cell)
            shard = [c + (q - c) * self.rng.uniform(0.4, 0.6) for q in cell]
            out.append(self._debris(shard, [obj.data.materials[0], self.mats["burnt"]], obj.name))
        return [d for d in out if d is not None]

    def _fragments(self, segments, rests) -> list:
        """Loose hull plates around the breaks (or around the hull without breaks)."""
        out = []
        hull_mat = segments[0].data.materials[0]
        for i in range(self.p["debris"]):
            if self.planes:
                n, d = self.planes[i % len(self.planes)]
                centre = n * d
            else:
                n, centre = Vector((0, 1, 0)), Vector((0, self.rng.uniform(-0.4, 0.4) * self.length, 0))
            size = self.beam * self.rng.uniform(0.1, 0.3)
            u = n.orthogonal().normalized()
            w = n.cross(u)
            pts = []
            for _ in range(7):  # a thin bent plate
                a, b = self.rng.uniform(-1, 1), self.rng.uniform(-1, 1)
                pts.append(u * a * size + w * b * size + n * self.rng.uniform(-0.12, 0.12) * size)
            pos = centre + Vector([self.rng.gauss(0, 1) for _ in range(3)]) * self.beam * (0.8 + 1.5 * self.p["spread"])
            pts = [Euler([self.rng.uniform(0, math.tau) for _ in range(3)]).to_matrix() @ q + pos for q in pts]
            d = self._debris(pts, [hull_mat, self.mats["burnt"]], "hull")
            if d is not None:
                out.append(d)
        return out

    def _debris(self, points, mats, source: str):
        if len(points) < 4 or geo.volume(points) < 1e-7 * self.length ** 3:
            return None
        bm = geo.hull_bmesh(points)
        centre = geo.centroid([v.co for v in bm.verts])
        bm.transform(Matrix.Translation(-centre))
        vol = abs(bm.calc_volume())
        burn = self.p["burn"]
        for f in bm.faces:
            f.material_index = 1 if self.rng.random() < 0.3 + 0.5 * burn else 0
        local = [v.co.copy() for v in bm.verts]
        name = f"Debris_{len([o for o in self.coll.objects if o.name.startswith('Debris_') and '_col' not in o.name])}"
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        for m in mats:
            mesh.materials.append(m)
        for poly in mesh.polygons:
            poly.use_smooth = False
        obj = bpy.data.objects.new(name, mesh)
        self.coll.objects.link(obj)
        obj.parent = self.root
        # thrown off: away from the ship's axis, a little further than the drifting parts
        away = Vector((centre.x, 0.0, centre.z))
        if away.length < 1e-6:
            away = Vector([self.rng.gauss(0, 1) for _ in range(3)])
        throw = (away.normalized() + Vector([self.rng.gauss(0, 0.4) for _ in range(3)])) * self.beam
        throw *= (0.5 + 1.5 * self.p["spread"]) * self.rng.uniform(0.5, 1.2)
        obj.matrix_basis = (Matrix.Translation(centre + throw)
                            @ Euler([self.rng.uniform(0, math.tau) for _ in range(3)]).to_matrix().to_4x4())
        obj["shipgen_role"] = "debris"
        obj["wreck_debris"] = {"source": source, "volume_m3": round(vol, 3), "mass_t": round(vol * SCRAP_DENSITY, 3)}
        collision.convex_object(local, f"{name}_col{collision.SUFFIX}", self.coll, obj)
        return obj

    # ------------------------------------------------------------ stats

    def _stats(self, ship_info, segments, debris, salvage) -> dict:
        counts = {s: sum(1 for e in salvage if e["state"] == s) for s in STATES}
        scrap = sum(o["wreck_segment"]["mass_t"] for o in segments) + sum(o["wreck_debris"]["mass_t"] for o in debris)
        return {
            "ship": {k: ship_info[k] for k in ("seed", "class", "design", "engine", "rig", "module", "wings")},
            "segments": len(segments),
            "debris": len(debris),
            "parts": counts,
            "salvage": salvage,
            "salvage_mass_t": round(sum(e["mass_t"] for e in salvage), 2),
            "scrap_mass_t": round(scrap, 2),
        }


def _fill_loops(bm) -> list:
    """One n-gon per open boundary loop (``holes_fill`` gives up on bent, ragged loops)."""
    caps = []
    left = {e for e in bm.edges if e.is_boundary}
    while left:
        start = left.pop()
        loop = [start.verts[0], start.verts[1]]
        while True:
            nxt = [e for e in loop[-1].link_edges if e in left]
            if not nxt:
                break
            e = nxt[0]
            left.discard(e)
            v = e.other_vert(loop[-1])
            if v is loop[0]:
                break
            loop.append(v)
        if len(loop) >= 3:
            try:
                caps.append(bm.faces.new(loop))
            except ValueError:
                pass
    return caps


def _remove(obj) -> None:
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if isinstance(data, bpy.types.Mesh) and data.users == 0:
        bpy.data.meshes.remove(data)
