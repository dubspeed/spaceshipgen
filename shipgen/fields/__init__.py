"""Asteroid fields: many rocks from a few unique prefabs, laid out flat for a top-down view.

    field = fields.generate({"shape": "belt", "count": 40, "seed": 3})
    fields.export_field(field, "output", "belt_3")   # belt_3.glb + belt_3_rock_<k>.glb

A field is built from ``prefabs`` unique asteroids (``asteroids.generate``; sizes spread
log-evenly between ``min_size_m`` and ``max_size_m``, compositions by the ore/metal/ice
shares) and ``count`` placements of them: position, rotation, prefab. Rocks are never scaled
(their stats come from their geometry) and never overlap (``gap_m``). Sizes follow a power law
(``size_bias``: many small, few large); compositions can be zoned along the field (``zoned``:
ore at one end, ice at the other; around a ring); ``clumping`` gathers rocks in clumps.

In Blender and in the field's .glb every placement is a node ``Rock_<i>`` with the prefab's
level-1 chunks as one shared preview mesh (glTF shares it between the nodes) and a shared convex
collider; extras ``asteroid_instance`` name the prefab. The breakable prefab (all break levels,
see asteroids) is exported once per prefab as ``<name>_rock_<k>.glb``: the game swaps it in.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

from .. import asteroids
from ..asteroids import geometry as geo
from ..generator import Ship
from ..generator import clear as _clear
from ..kit import collision
from . import params as params_mod

COLLECTION = "ShipGen_Field"
WORK = "ShipGen_FieldPrefab"  # where prefabs are generated (the Asteroids panel's rock stays)
COMPOSITIONS = ("ore", "metal", "ice")  # zone order along the field
SHAPE_WEIGHTS = (("round", 0.5), ("elongated", 0.35), ("binary", 0.15))
PLACE_TRIES = 40


@dataclass
class Prefab:
    index: int
    composition: str
    size_m: float
    params: dict  # asteroid params (full break levels: the prefab .glb)
    stats: dict = field(default_factory=dict)  # asteroid stats (whole rock)
    mesh: object = None  # preview: the level-1 chunks as one mesh
    collider: object = None  # its convex hull (shared by every placement)

    @property
    def name(self) -> str:
        return f"rock_{self.index}"


@dataclass
class Placement:
    prefab: Prefab
    position: Vector
    rotation: Euler
    zone: float  # 0..1 along the field (composition zones)


@dataclass
class AsteroidField:
    root: object
    parts: list  # Rock_<i> objects
    prefabs: list
    placements: list
    params: dict
    warnings: list[str] = field(default_factory=list)
    colliders: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    bounds = Ship.bounds

    @property
    def objects(self):
        return [self.root, *self.parts, *self.colliders]


def generate(raw_params: dict) -> AsteroidField:
    """Build a field (preview meshes); replaces the previous field."""
    result = params_mod.validate(raw_params)
    p = result.params
    warnings = list(result.warnings)
    rng = random.Random(f"{p['seed']}:field")
    prefabs = _prefabs(p, random.Random(f"{p['seed']}:field_prefabs"))
    placements = _place(p, prefabs, rng)
    if len(placements) < p["count"]:
        warnings.append(f"only {len(placements)} of {p['count']} rocks fit (gap_m / size_m)")
    used = sorted({pl.prefab.index for pl in placements})
    _clear(COLLECTION)
    for pf in prefabs:
        if pf.index in used:
            _preview(pf)
    _clear(WORK)
    mats = {c: asteroids._materials(c) for c in COMPOSITIONS}  # one set per composition, shared
    for pf in prefabs:
        if pf.mesh is not None:
            for key in ("surface", "plain", "resource"):
                pf.mesh.materials.append(mats[pf.composition][key])

    coll = bpy.data.collections.new(COLLECTION)
    bpy.context.scene.collection.children.link(coll)
    root = bpy.data.objects.new("AsteroidField", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 0.05 * p["size_m"]
    coll.objects.link(root)
    parts, colliders = [], []
    for i, pl in enumerate(placements):
        obj = bpy.data.objects.new(f"Rock_{i}", pl.prefab.mesh)
        coll.objects.link(obj)
        obj.parent = root
        obj.matrix_basis = Matrix.Translation(pl.position) @ pl.rotation.to_matrix().to_4x4()
        s = pl.prefab.stats
        obj["shipgen_role"] = "asteroid"
        obj["asteroid_instance"] = {"prefab": pl.prefab.name, "composition": pl.prefab.composition,
                                    "size_m": s["size_m"], "volume_m3": s["volume_m3"], "mass_t": s["mass_t"],
                                    "yield_m3": s["yield_m3"], "cargo": s["cargo"], "hardness": s["hardness"],
                                    "zone": round(pl.zone, 3)}
        col = bpy.data.objects.new(f"Rock_{i}_col{collision.SUFFIX}", pl.prefab.collider)
        col.display_type = "WIRE"
        col.hide_render = True
        col["shipgen_role"] = "collision"
        coll.objects.link(col)
        col.parent = obj
        parts.append(obj)
        colliders.append(col)
    f = AsteroidField(root, parts, [pf for pf in prefabs if pf.index in used], placements, p, warnings, colliders)
    f.stats = _stats(p, f)
    root["shipgen_field"] = {"seed": p["seed"], "shape": p["shape"],
                             "prefabs": [pf.name for pf in f.prefabs], "stats": f.stats}
    return f


# ---------------------------------------------------------------- prefabs

def _shares(p) -> dict:
    total = sum(p[c] for c in COMPOSITIONS)
    return {c: p[c] / total for c in COMPOSITIONS if p[c] > 0}


def _prefabs(p, rng) -> list[Prefab]:
    """Per composition (by share, at least one) rocks with sizes spread log-evenly."""
    shares = _shares(p)
    out = []
    lo, hi = p["min_size_m"], p["max_size_m"]
    for comp, share in shares.items():
        n = max(1, round(p["prefabs"] * share))
        for k in range(n):
            t = 0.5 if n == 1 else k / (n - 1)
            size = lo * (hi / lo) ** t if hi > lo else lo
            shapes = [(s, w) for s, w in SHAPE_WEIGHTS if s != "binary" or size >= 15]
            shape = rng.choices([s for s, _ in shapes], [w for _, w in shapes])[0]
            ap = {"seed": rng.randrange(1, 2**31 - 1), "composition": comp, "shape": shape, "size_m": round(size, 2),
                  "chunks": max(2, min(8, round(size / 5))), "min_chunk_m": max(2.0, 0.15 * size)}
            out.append(Prefab(len(out), comp, size, asteroids.params.validate(ap).params))
    return out


def _preview(pf: Prefab) -> None:
    """Generate the prefab's level 1 (same as the full rock's) as one mesh plus its convex hull."""
    rock = asteroids.generate(dict(pf.params, max_levels=1), collection=WORK)
    pf.stats = dict(rock.stats)
    bm = bmesh.new()
    for chunk in rock.parts:
        tmp = bmesh.new()
        tmp.from_mesh(chunk.data)
        tmp.transform(chunk.matrix_basis)
        me = bpy.data.meshes.new("_tmp")
        tmp.to_mesh(me)
        tmp.free()
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    pts = [v.co.copy() for v in bm.verts]
    mesh = bpy.data.meshes.new(f"Field_{pf.name}")
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = False
    pf.mesh = mesh
    hull = geo.exact_hull_bmesh(pts)
    col = bpy.data.meshes.new(f"Field_{pf.name}_col")
    hull.to_mesh(col)
    hull.free()
    pf.collider = col


# ---------------------------------------------------------------- placement

def _spot(p, rng) -> tuple[Vector, float]:
    """A random point of the field's shape (z: thickness) and its zone coordinate 0..1."""
    size, width = p["size_m"], p["width"] * p["size_m"]
    z = rng.gauss(0, 0.5) * p["thickness"] * size
    if p["shape"] == "belt":  # a gently bent band along X
        u = rng.random()
        x = (u - 0.5) * size
        y = rng.gauss(0, 0.33) * width + 0.12 * size * ((2 * u - 1) ** 2 - 1 / 3)
        return Vector((x, y, z)), u
    if p["shape"] == "ring":
        a = rng.uniform(0, math.tau)
        r = 0.5 * size + rng.gauss(0, 0.33) * width
        return Vector((r * math.cos(a), r * math.sin(a), z)), a / math.tau
    r = 0.5 * size * math.sqrt(rng.random()) * rng.uniform(0.6, 1.0)  # cluster: denser in the middle
    a = rng.uniform(0, math.tau)
    x, y = r * math.cos(a), r * math.sin(a)
    return Vector((x, y, z)), x / size + 0.5


def _zone_composition(p, t: float) -> str:
    """Zones along the field in the order ore, metal, ice, each as long as its share."""
    acc = 0.0
    shares = _shares(p)
    for comp, share in shares.items():
        acc += share
        if t <= acc:
            return comp
    return list(shares)[-1]


def _place(p, prefabs: list[Prefab], rng) -> list[Placement]:
    shares = _shares(p)
    by_comp = {c: sorted((pf for pf in prefabs if pf.composition == c), key=lambda pf: pf.size_m) for c in shares}
    clumps = [_spot(p, rng) for _ in range(max(1, p["count"] // 8))]
    placed: list[Placement] = []
    taken: list[tuple[Vector, float]] = []
    lo, hi = p["min_size_m"], p["max_size_m"]
    for _ in range(p["count"]):
        want = lo * (hi / lo) ** (rng.random() ** (1.0 + p["size_bias"])) if hi > lo else lo
        for _ in range(PLACE_TRIES):
            if rng.random() < p["clumping"]:
                centre, t = rng.choice(clumps)
                pos = centre + Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 0.3))) * 0.06 * p["size_m"]
            else:
                pos, t = _spot(p, rng)
            comp = (_zone_composition(p, t) if rng.random() < p["zoned"]
                    else rng.choices(list(shares), list(shares.values()))[0])
            pf = min(by_comp[comp], key=lambda pf: abs(math.log(pf.size_m / want)))
            radius = 0.5 * pf.size_m * 1.15  # rough rocks stick out of their nominal size a little
            if all((pos - q).length >= radius + r + p["gap_m"] for q, r in taken):
                taken.append((pos, radius))
                rot = Euler([rng.uniform(0, math.tau) for _ in range(3)])
                placed.append(Placement(pf, pos, rot, t))
                break
    return placed


# ---------------------------------------------------------------- stats and export

def _stats(p, f: AsteroidField) -> dict:
    counts = {c: 0 for c in COMPOSITIONS}
    yields = {"ore_m3": 0.0, "fluid_m3": 0.0}
    mass = 0.0
    for pl in f.placements:
        s = pl.prefab.stats
        counts[pl.prefab.composition] += 1
        yields[s["cargo"]] = yields.get(s["cargo"], 0.0) + s["yield_m3"]
        mass += s["mass_t"]
    lo, hi = f.bounds()
    return {
        "rocks": len(f.placements),
        "per_composition": counts,
        "yield": {k: round(v, 1) for k, v in yields.items()},
        "mass_t": round(mass, 1),
        "extent_m": [round(c, 1) for c in hi - lo],
        "prefabs": {pf.name: {"composition": pf.composition, "size_m": pf.stats["size_m"],
                              "yield_m3": pf.stats["yield_m3"], "uses": sum(1 for pl in f.placements if pl.prefab is pf)}
                    for pf in f.prefabs},
    }


def _godot(m: Matrix) -> tuple[list, list]:
    """Position and rotation quaternion [x, y, z, w] in glTF / Godot axes (Y up, Blender -Y -> +Z)."""
    c = Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0)))
    pos = c @ m.translation
    q = (c @ m.to_3x3() @ c.transposed()).to_quaternion()
    return [round(v, 4) for v in pos], [round(q.x, 6), round(q.y, 6), round(q.z, 6), round(q.w, 6)]


def manifest(f: AsteroidField, name: str) -> dict:
    """Everything the game needs to build the field from the prefab files, in Godot axes."""
    rocks = []
    for obj, pl in zip(f.parts, f.placements):
        pos, rot = _godot(obj.matrix_basis)
        rocks.append({"name": obj.name, "prefab": pl.prefab.name, "file": f"{name}_{pl.prefab.name}.glb",
                      "position": pos, "rotation": rot, "composition": pl.prefab.composition,
                      "zone": round(pl.zone, 3)})
    return {"axes": "godot", "params": f.params, "stats": f.stats,
            "prefabs": {pf.name: {"file": f"{name}_{pf.name}.glb", "asteroid_params": pf.params}
                        for pf in f.prefabs},
            "rocks": rocks}


def export_prefabs(f: AsteroidField, out_dir: str, name: str, atlas: bool = True) -> list[str]:
    """``<name>_rock_<k>.glb`` for every prefab the field uses, with all break levels."""
    import os

    from .. import export

    paths = []
    for pf in f.prefabs:
        rock = asteroids.generate(pf.params, collection=WORK)
        paths.append(export.export_glb(rock, os.path.join(out_dir, f"{name}_{pf.name}.glb"), atlas=atlas))
    _clear(WORK)
    return paths
