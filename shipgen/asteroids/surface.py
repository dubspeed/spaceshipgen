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
CRATER_FLOOR = 0.55  # share of the radius that is flat floor
CRATER_RIM = 1.4  # the raised rim ends at this many radii
RIM_HEIGHT = 0.45  # rim height relative to the depth


@dataclass
class Surface:
    centre: Vector
    edge: float  # target edge length of the subdivided surface
    amp: float  # noise amplitude (m), large octave; the small one is a third of it
    freq: float
    offset: Vector
    craters: list = field(default_factory=list)  # (centre, radius, depth)
    coarse: float = 1.0  # > 1: bigger triangles everywhere (triangle budget)

    def displacement(self, p: Vector) -> float:
        """Outward (+) / inward (-) push at world point ``p``."""
        q = p * self.freq + self.offset
        d = self.amp * noise.noise(q) + 0.5 * self.amp * noise.noise(q * 2.7 + Vector((7.3, 1.1, 4.2)))
        # per-vertex jitter (a hash of the position, so neighbours that share a point agree):
        # chips the facets into small, sharp, uneven planes
        d += 0.22 * self.amp * noise.noise(p * 37.0 / self.edge + self.offset)
        # crater floors are smoother than the rock around them, so the bowl reads
        calm = max((max(0.0, 1.0 - (p - c).length / r) for c, r, _ in self.craters), default=0.0)
        d *= 1.0 - 0.75 * min(1.0, 2.0 * calm)
        for c, r, depth in self.craters:
            t = (p - c).length / r
            if t < CRATER_FLOOR:
                d -= depth  # flat floor
            elif t < 1.0:
                f = (1.0 - t) / (1.0 - CRATER_FLOOR)  # steep wall
                d -= depth * f * f * (3.0 - 2.0 * f)
            elif t < CRATER_RIM:
                d += RIM_HEIGHT * depth * math.sin(math.pi * (t - 1.0) / (CRATER_RIM - 1.0))  # raised rim
        return d

    def in_crater(self, p: Vector, reach: float = 1.0) -> bool:
        return any((p - c).length < reach * r for c, r, _ in self.craters)

    def crater_edge(self, p: Vector) -> float:
        """Target edge length near ``p``: finer in and around craters, so bowl and rim show."""
        for c, r, _ in self.craters:
            if (p - c).length < CRATER_RIM * r:
                return min(self.edge, self.coarse * r / 3.0)
        return self.edge


def make_surface(p, pieces, rng: random.Random, coarse: float = 1.0) -> Surface:
    """``coarse`` > 1 makes the surface triangles bigger (triangle budget)."""
    pts = [q for piece in pieces for q in piece]
    centre = geo.centroid(pts)
    size = p["size_m"]
    surf = Surface(centre=centre, edge=coarse * size / 10.0, amp=0.12 * size * p["roughness"],
                   freq=4.0 / size, offset=Vector((rng.uniform(-50, 50) for _ in range(3))), coarse=coarse)
    pls = [geo.planes(piece) for piece in pieces]
    for _ in range(p["craters"]):
        i = rng.randrange(len(pieces))
        start = geo.centroid(pieces[i])
        direction = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized()
        # where the ray from the piece's centre leaves it (convex): the crater sits on its surface
        t = min((d - n.dot(start)) / n.dot(direction) for n, d in pls[i] if n.dot(direction) > 1e-6)
        r = rng.uniform(0.08, 0.17) * size
        surf.craters.append((start + direction * t, r, rng.uniform(0.4, 0.55) * r))
    return surf


def roughen(bm, surf: Surface, limit: float, floor_material: int | None = None) -> None:
    """Subdivide the surface faces of ``bm`` (world space) and displace them; ``limit`` caps the
    push (thin chunks must not fold over). Surface faces on a crater floor get
    ``floor_material`` (fresh, uncovered rock) unless they show the resource."""
    layer = bm.faces.layers.int.get(FRACTURE_LAYER)

    def surface_face(f):
        return f[layer] == 0

    for _ in range(6):
        long = [e for e in bm.edges if all(surface_face(f) for f in e.link_faces)
                and e.calc_length() > surf.crater_edge((e.verts[0].co + e.verts[1].co) / 2)]
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
    if floor_material is not None:
        for f in bm.faces:
            if surface_face(f) and f.material_index == 0 and surf.in_crater(f.calc_center_median(), 0.9):
                f.material_index = floor_material
    if moved:  # break faces that lost their planarity are split into triangles
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if not surface_face(f) and len(f.verts) > 3])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
