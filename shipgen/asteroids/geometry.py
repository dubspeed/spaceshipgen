"""Convex polytopes as point lists: hull, half-space clipping, Voronoi cells.

A polytope is the convex hull of its points; clipping keeps the points inside a
half-space plus the hull edges' crossings with the plane, so the result is again
the exact polytope (as its vertex set). Everything stays convex by construction,
which is what makes every asteroid chunk a valid convex collision shape.
"""

from __future__ import annotations

import math
import random

import bmesh
from mathutils import Vector

EPS = 1e-6


def _scale(points) -> float:
    lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return max((hi - lo).length, 1e-9)


def hull_bmesh(points) -> bmesh.types.BMesh:
    """Closed convex hull of ``points`` with outward normals. Interior points are dropped,
    near-duplicates and slivers dissolved and coplanar triangles merged into one facet, so
    every face has a reliable normal (clipping leaves points very close to each other)."""
    scale = _scale(points)
    bm = bmesh.new()
    verts = [bm.verts.new(p) for p in dedup(points, 1e-5 * scale)]
    res = bmesh.ops.convex_hull(bm, input=verts)
    junk = list({g for g in res["geom_interior"] + res["geom_unused"] if isinstance(g, bmesh.types.BMVert)})
    if junk:
        bmesh.ops.delete(bm, geom=junk, context="VERTS")
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges[:], dist=1e-4 * scale)
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(0.5), verts=bm.verts[:], edges=bm.edges[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def dedup(points, tol: float) -> list[Vector]:
    out: list[Vector] = []
    for p in points:
        if all((p - q).length > tol for q in out):
            out.append(p.copy())
    return out


def clip(points, normal: Vector, d: float) -> list[Vector]:
    """Vertices of hull(points) ∩ {x : normal·x <= d}."""
    tol = 1e-6 * _scale(points)
    bm = hull_bmesh(points)
    side = {v: normal.dot(v.co) - d for v in bm.verts}
    out = [v.co.copy() for v, s in side.items() if s <= tol]
    for e in bm.edges:
        a, b = e.verts
        sa, sb = side[a], side[b]
        if (sa < -tol and sb > tol) or (sa > tol and sb < -tol):
            out.append(a.co.lerp(b.co, sa / (sa - sb)))
    bm.free()
    return dedup(out, 10 * tol)


def planes(points) -> list[tuple[Vector, float]]:
    """Face planes (normal, d) of the hull; inside means normal·x <= d."""
    bm = hull_bmesh(points)
    out = [(f.normal.copy(), f.normal.dot(f.calc_center_median())) for f in bm.faces if f.normal.length > 0.5]
    bm.free()
    return out


def inside(p: Vector, pls, margin: float = 0.0) -> bool:
    return all(n.dot(p) <= d - margin for n, d in pls)


def volume(points) -> float:
    bm = hull_bmesh(points)
    v = abs(bm.calc_volume())
    bm.free()
    return v


def centroid(points) -> Vector:
    c = Vector((0, 0, 0))
    for p in points:
        c += p
    return c / max(len(points), 1)


def diameter(points) -> float:
    return max(((a - b).length for i, a in enumerate(points) for b in points[i + 1:]), default=0.0)


def spread_seeds(points, k: int, rng: random.Random) -> list[Vector]:
    """``k`` points spread evenly inside the polytope (farthest-point sampling of random
    interior candidates), so Voronoi cells come out of similar size."""
    pls = planes(points)
    lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    margin = 0.05 * (hi - lo).length
    cands = []
    for _ in range(4000):
        p = Vector(tuple(rng.uniform(lo[i], hi[i]) for i in range(3)))
        if inside(p, pls, margin):
            cands.append(p)
            if len(cands) >= 40 * k:
                break
    if len(cands) < k:
        return cands
    seeds = [cands[rng.randrange(len(cands))]]
    while len(seeds) < k:
        seeds.append(max(cands, key=lambda c: min((c - s).length for s in seeds)))
    return seeds


def voronoi_cells(points, seeds) -> tuple[list[list[Vector]], list[tuple[Vector, float]]]:
    """The polytope cut into one convex cell per seed, plus the bisector planes (the fracture
    planes: faces of a cell that lie on one of them are break faces, the rest is surface)."""
    cuts = []
    for i, s in enumerate(seeds):
        for t in seeds[i + 1:]:
            n = (t - s).normalized()
            cuts.append((n, n.dot((s + t) / 2)))
    cells = []
    for i, s in enumerate(seeds):
        cell = list(points)
        for j, t in enumerate(seeds):
            if i != j and len(cell) >= 4:
                n = (t - s).normalized()
                cell = clip(cell, n, n.dot((s + t) / 2))
        if len(cell) >= 4 and volume(cell) > EPS:
            cells.append(cell)
    return cells, cuts
