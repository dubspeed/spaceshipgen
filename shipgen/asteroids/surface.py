"""Rough rock surface: breaks the big flat facets of the convex chunks.

The surface faces of a chunk (not its break faces) are cut into smaller triangles and every
vertex that touches the surface is pushed along the radial direction by world-space noise
(two octaves) and by a few craters (bowl + low rim). Because the displacement depends only
on the world position, neighbouring chunks and the sub-chunks of a chunk get the same
surface where they meet: breaking a chunk doesn't change how the rock looks.

The displaced mesh is no longer convex; each chunk's collider is the convex hull of its
displaced vertices (a separate ``-convcolonly`` object).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import bmesh
from mathutils import Vector, noise

from . import geometry as geo

FRACTURE_LAYER = "fracture"  # int face layer: 1 on break faces (kept flat-ish, not subdivided)


@dataclass
class Surface:
    centre: Vector
    edge: float  # target edge length of the subdivided surface
    amp: float  # noise amplitude (m), large octave; the small one is a third of it
    freq: float
    offset: Vector
    craters: list = field(default_factory=list)  # (centre, radius, depth)

    def displacement(self, p: Vector) -> float:
        """Outward (+) / inward (-) push at world point ``p``."""
        q = p * self.freq + self.offset
        d = self.amp * noise.noise(q) + 0.5 * self.amp * noise.noise(q * 2.7 + Vector((7.3, 1.1, 4.2)))
        # per-vertex jitter (a hash of the position, so neighbours that share a point agree):
        # chips the facets into small, sharp, uneven planes
        d += 0.22 * self.amp * noise.noise(p * 37.0 / self.edge + self.offset)
        for c, r, depth in self.craters:
            t = (p - c).length / r
            if t < 1.0:
                d -= depth * (1.0 - t * t)  # bowl
            elif t < 1.35:
                d += 0.25 * depth * math.sin(math.pi * (t - 1.0) / 0.35)  # rim
        return d


def make_surface(p, pieces, rng: random.Random) -> Surface:
    pts = [q for piece in pieces for q in piece]
    centre = geo.centroid(pts)
    size = p["size_m"]
    surf = Surface(centre=centre, edge=size / 10.0, amp=0.12 * size * p["roughness"],
                   freq=4.0 / size, offset=Vector((rng.uniform(-50, 50) for _ in range(3))))
    pls = [geo.planes(piece) for piece in pieces]
    for _ in range(p["craters"]):
        i = rng.randrange(len(pieces))
        start = geo.centroid(pieces[i])
        direction = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized()
        # where the ray from the piece's centre leaves it (convex): the crater sits on its surface
        t = min((d - n.dot(start)) / n.dot(direction) for n, d in pls[i] if n.dot(direction) > 1e-6)
        r = rng.uniform(0.14, 0.3) * size
        surf.craters.append((start + direction * t, r, rng.uniform(0.3, 0.45) * r))
    return surf


def roughen(bm, surf: Surface, limit: float) -> None:
    """Subdivide the surface faces of ``bm`` (world space) and displace them; ``limit`` caps the
    push (thin chunks must not fold over)."""
    layer = bm.faces.layers.int.get(FRACTURE_LAYER)

    def surface_face(f):
        return f[layer] == 0

    for _ in range(4):
        long = [e for e in bm.edges
                if e.calc_length() > surf.edge and all(surface_face(f) for f in e.link_faces)]
        if not long:
            break
        bmesh.ops.subdivide_edges(bm, edges=long, cuts=1, use_grid_fill=True, use_single_edge=True)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if surface_face(f) and len(f.verts) > 3])
    moved = False
    for v in bm.verts:
        if not any(surface_face(f) for f in v.link_faces):
            continue  # deep inside the rock: only break faces meet here
        radial = v.co - surf.centre
        if radial.length < 1e-9:
            continue
        d = max(-limit, min(limit, surf.displacement(v.co)))
        v.co += radial.normalized() * d
        moved = True
    if moved:  # break faces that lost their planarity are split into triangles
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if not surface_face(f) and len(f.verts) > 3])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
