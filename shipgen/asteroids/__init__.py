"""Asteroid generator: faceted low-poly rocks, pre-fractured into convex chunks.

    rock = asteroids.generate({"composition": "ore", "size_m": 30, "seed": 4})

The rock is the convex hull of random points (two hulls cut apart for a binary
asteroid), split into Voronoi cells; cells bigger than about twice ``min_chunk_m``
split again, down to ``max_levels``. Every chunk is convex, so in Godot it is its own
convex collision shape (``-convcol`` suffix: mesh + collider).

Hierarchy (what the game uses): ``Asteroid`` -> level-1 chunks (visible, they tile the
whole rock) -> each chunk's own sub-chunks (hidden in Blender, in place; the .glb has all
levels, so the game hides levels > 1 on load) -> ... When a chunk breaks,
hide it and show its children. Each chunk carries ``asteroid_chunk`` extras: level,
resource, volume, mass, yield, cargo kind, hardness, size.

Faces on fracture planes are break faces: resource-coloured on rich chunks, so cracks and
broken chunks show what's inside; a few surface faces of rich chunks show veins.
Stats come from the meshes, like the ships' (``COMPOSITION`` holds the physical-ish
constants; the game balances with its own multipliers).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import bmesh
import bpy
from mathutils import Euler, Vector

from ..generator import Ship
from ..generator import clear as _clear
from ..generator.materials import MATERIAL_PREFIX
from . import geometry as geo
from . import params as params_mod

COLLECTION = "ShipGen_Asteroid"
SUFFIX = "-convcol"  # Godot: mesh + convex collision shape

# density t/m^3, hardness (mining time factor, ore = 1), grade = resource share of a rich
# chunk's volume, cargo kind as in the ships' stats, colours (surface, plain inside, resource)
COMPOSITION = {
    "ore": dict(density=2.7, hardness=1.0, grade=0.5, cargo="ore_m3",
                surface=((0.2, 0.18, 0.16), 0.0, 0.9), plain=((0.33, 0.3, 0.28), 0.0, 0.85),
                resource=((0.7, 0.3, 0.07), 0.4, 0.45)),
    "metal": dict(density=5.0, hardness=1.8, grade=0.7, cargo="ore_m3",
                  surface=((0.16, 0.16, 0.18), 0.6, 0.55), plain=((0.3, 0.3, 0.32), 0.3, 0.6),
                  resource=((0.88, 0.8, 0.55), 0.5, 0.3)),  # bright and warm, readable on dark rock
    "ice": dict(density=0.92, hardness=0.5, grade=0.9, cargo="fluid_m3",
                surface=((0.72, 0.8, 0.86), 0.0, 0.45), plain=((0.42, 0.48, 0.53), 0.0, 0.6),
                resource=((0.3, 0.62, 0.95), 0.0, 0.12)),
}
TRACE_GRADE = 0.05  # plain rock still yields a little
VEIN_SHARE = 0.25  # surface faces of a rich chunk that show the resource
INHERIT_RICH = 0.85  # a rich chunk's pieces stay rich with this chance


@dataclass
class Chunk:
    name: str
    level: int
    points: list  # vertices of the convex chunk before its cracks are cut (world space)
    rich: bool
    children: list["Chunk"] = field(default_factory=list)
    obj: object = None


@dataclass
class Asteroid:
    root: object
    parts: list  # level-1 chunk objects (the visible rock)
    chunks: list[Chunk]  # all chunks, every level
    params: dict
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    bounds = Ship.bounds

    @property
    def objects(self):
        return [self.root, *(c.obj for c in self.chunks)]


def generate(raw_params: dict) -> Asteroid:
    """Build an asteroid from (possibly unvalidated) params; replaces the previous one."""
    result = params_mod.validate(raw_params)
    p = result.params
    warnings = list(result.warnings)
    levels = p["max_levels"]
    while True:
        tree, fractures = _fracture(p, levels)
        tris = sum(_tris(c.points) for c in _walk(tree))
        if tris <= p["max_tris"] or levels == 1:
            break
        levels -= 1
        warnings.append(f"max_levels reduced to {levels} to stay within max_tris ({tris} tris)")
    rock = _build_objects(p, tree, fractures)
    rock.warnings = warnings
    return rock


# ---------------------------------------------------------------- shape and fracture

def _blob(rng, center: Vector, axes, n: int) -> list[Vector]:
    pts = []
    for _ in range(n):
        v = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized()
        r = rng.uniform(0.72, 1.0)  # uneven radii give big, varied facets
        pts.append(center + Vector((v.x * axes[0], v.y * axes[1], v.z * axes[2])) * r)
    return pts


def _base_pieces(p, rng) -> list[list[Vector]]:
    """Convex base pieces of the rock: one, or two lobes cut apart for a binary."""
    n = p["facets"]
    if p["shape"] == "binary":
        a = _blob(rng, Vector((-0.4, 0, 0)), (0.62, 0.58, 0.5), n)
        b = _blob(rng, Vector((0.45, rng.uniform(-0.1, 0.1), rng.uniform(-0.1, 0.1))), (0.5, 0.45, 0.42), n)
        normal = Vector((1, rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25))).normalized()
        d = normal.dot(Vector((0.08, 0, 0)))
        pieces = [geo.clip(a, normal, d), geo.clip(b, -normal, -d)]  # the waist stays surface
    elif p["shape"] == "elongated":
        pieces = [_blob(rng, Vector(), (1.0, rng.uniform(0.48, 0.6), rng.uniform(0.4, 0.52)), n)]
    else:
        pieces = [_blob(rng, Vector(), (1.0, rng.uniform(0.8, 0.95), rng.uniform(0.66, 0.84)), n)]
    rot = Euler((rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4), rng.uniform(0, math.tau))).to_matrix()
    scale = p["size_m"] / geo.diameter([rot @ q for piece in pieces for q in piece])
    return [[(rot @ q) * scale for q in piece] for piece in pieces]


def _fracture(p, levels: int) -> tuple[list[Chunk], list[tuple[Vector, float]]]:
    """Chunk tree + every fracture plane (break faces lie on one of them)."""
    rng = random.Random(f"{p['seed']}:{p['composition']}:asteroid")
    pieces = _base_pieces(p, rng)
    fractures: list[tuple[Vector, float]] = []
    total = sum(geo.volume(pc) for pc in pieces)
    top: list[Chunk] = []
    for piece in pieces:
        k = max(2, round(p["chunks"] * geo.volume(piece) / total)) if len(pieces) > 1 else p["chunks"]
        cells, cuts = geo.voronoi_cells(piece, geo.spread_seeds(piece, k, rng))
        fractures += cuts
        for cell in cells:
            top.append(Chunk(f"Chunk_{len(top)}", 1, cell, rng.random() < p["richness"]))

    def split(chunk: Chunk) -> None:
        if chunk.level >= levels or geo.diameter(chunk.points) < 2 * p["min_chunk_m"]:
            return
        cells, cuts = geo.voronoi_cells(chunk.points, geo.spread_seeds(chunk.points, p["sub_chunks"], rng))
        if len(cells) < 2:
            return
        fractures.extend(cuts)
        for i, cell in enumerate(cells):
            rich = rng.random() < (INHERIT_RICH if chunk.rich else 0.25 * p["richness"])
            child = Chunk(f"{chunk.name}_{i}", chunk.level + 1, cell, rich)
            chunk.children.append(child)
            split(child)

    for chunk in top:
        split(chunk)
    return top, fractures


def _walk(chunks):
    for c in chunks:
        yield c
        yield from _walk(c.children)


def _tris(points) -> int:
    bm = geo.hull_bmesh(points)
    n = sum(len(f.verts) - 2 for f in bm.faces)
    bm.free()
    return n


# ---------------------------------------------------------------- objects and stats

def _materials(comp: str) -> dict:
    out = {}
    for key in ("surface", "plain", "resource"):
        color, metallic, rough = COMPOSITION[comp][key]
        mat = bpy.data.materials.new(f"{MATERIAL_PREFIX}Asteroid_{comp}_{key}")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = rough
        mat.diffuse_color = (*color, 1.0)
        out[key] = mat
    return out


def _on_fracture(n: Vector, d: float, fractures, tol: float, inset: float = 0.0) -> bool:
    """Does the plane (n, d) lie on a fracture plane (either side of it), moved ``inset`` inwards?"""
    for fn, fd in fractures:
        k = n.dot(fn)
        if abs(k) > 0.9999 and abs(d - (fd if k > 0 else -fd) + inset) < tol:
            return True
    return False


def _build_objects(p, tree: list[Chunk], fractures) -> Asteroid:
    _clear(COLLECTION)
    coll = bpy.data.collections.new(COLLECTION)
    bpy.context.scene.collection.children.link(coll)
    root = bpy.data.objects.new("Asteroid", None)
    coll.objects.link(root)
    comp = COMPOSITION[p["composition"]]
    mats = _materials(p["composition"])
    tol = 1e-4 * p["size_m"]
    chunks = list(_walk(tree))

    crack = 0.5 * p["gap"] * p["size_m"]

    def make(chunk: Chunk, parent, parent_c: Vector) -> None:
        # cracks of constant width: only the break faces move in (half a crack each), the rock
        # surface stays where it is, so small chunks never stick out of big shrunk ones
        inset = min(0.5 * crack, 0.1 * geo.diameter(chunk.points))
        pts = chunk.points
        for n, d in geo.planes(chunk.points):
            if _on_fracture(n, d, fractures, tol):
                pts = geo.clip(pts, n, d - inset)
        bm = geo.hull_bmesh(pts)
        rng = random.Random(f"{p['seed']}:vein:{chunk.name}")
        for f in bm.faces:
            if _on_fracture(f.normal, f.normal.dot(f.calc_center_median()), fractures, tol, inset):
                f.material_index = 2 if chunk.rich else 1
            else:
                f.material_index = 2 if chunk.rich and rng.random() < VEIN_SHARE else 0
        c = geo.centroid([v.co for v in bm.verts])
        for v in bm.verts:
            v.co -= c
        mesh = bpy.data.meshes.new(chunk.name)
        bm.to_mesh(mesh)
        bm.free()
        for key in ("surface", "plain", "resource"):
            mesh.materials.append(mats[key])
        for poly in mesh.polygons:
            poly.use_smooth = False
        obj = bpy.data.objects.new(chunk.name + SUFFIX, mesh)
        coll.objects.link(obj)
        obj.parent = parent
        obj.location = c - parent_c
        hidden = chunk.level > 1
        obj.hide_viewport = obj.hide_render = hidden
        chunk.obj = obj
        obj["asteroid_chunk"] = _chunk_stats(chunk, mesh, comp, p)
        for child in chunk.children:
            make(child, obj, c)

    for chunk in tree:
        make(chunk, root, Vector())
    rock = Asteroid(root=root, parts=[c.obj for c in tree], chunks=chunks, params=p)
    rock.stats = _stats(p, tree, chunks)
    root["shipgen_asteroid"] = {"seed": p["seed"], "composition": p["composition"], "shape": p["shape"],
                                "stats": rock.stats}
    return rock


def _chunk_stats(chunk: Chunk, mesh, comp: dict, p) -> dict:
    bm = bmesh.new()
    bm.from_mesh(mesh)
    vol = abs(bm.calc_volume())
    size = geo.diameter([v.co for v in bm.verts])
    bm.free()
    grade = comp["grade"] if chunk.rich else TRACE_GRADE
    return {
        "level": chunk.level,
        "resource": p["composition"] if chunk.rich else "rock",
        "volume_m3": round(vol, 2),
        "mass_t": round(vol * comp["density"], 2),
        "yield_m3": round(vol * grade, 2),
        "cargo": comp["cargo"],
        "hardness": comp["hardness"],
        "size_m": round(size, 2),
        "children": len(chunk.children),
    }


def _stats(p, tree, chunks) -> dict:
    top = [c.obj["asteroid_chunk"] for c in tree]
    leaves = [c.obj["asteroid_chunk"] for c in chunks if not c.children]
    per_level = {}
    for c in chunks:
        per_level[str(c.level)] = per_level.get(str(c.level), 0) + 1
    comp = COMPOSITION[p["composition"]]
    return {
        "composition": p["composition"],
        "size_m": round(geo.diameter([q for c in tree for q in c.points]), 2),
        "volume_m3": round(sum(t["volume_m3"] for t in top), 2),
        "mass_t": round(sum(t["mass_t"] for t in top), 2),
        "yield_m3": round(sum(t["yield_m3"] for t in top), 2),
        "cargo": comp["cargo"],
        "hardness": comp["hardness"],
        "chunks_per_level": per_level,
        "smallest_chunk_m": round(min(c["size_m"] for c in leaves), 2) if leaves else 0.0,
        "largest_chunk_m": round(max(t["size_m"] for t in top), 2) if top else 0.0,
    }
