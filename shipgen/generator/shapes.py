"""Low-poly primitives on a bmesh: lofted rings along an axis, boxes, beams.

Every helper produces closed geometry; ``material`` sets the face material index.
"""

from __future__ import annotations

import math

from mathutils import Vector


def ring(bm, center, radius: float, sides: int, axis: Vector, phase: float = 0.0):
    """Vertices of a regular polygon around ``axis`` through ``center``."""
    axis = Vector(axis).normalized()
    u = axis.orthogonal().normalized()
    if abs(axis.z) < 0.9:  # keep a flat side facing up for horizontal axes
        u = axis.cross(Vector((0, 0, 1))).normalized()
    v = axis.cross(u)
    center = Vector(center)
    return [
        bm.verts.new(center + radius * (math.cos(a) * u + math.sin(a) * v))
        for a in (phase + math.pi / sides + 2 * math.pi * k / sides for k in range(sides))
    ]


def bridge(bm, a, b, material: int = 0) -> None:
    n = len(a)
    for k in range(n):
        k2 = (k + 1) % n
        bm.faces.new((a[k], a[k2], b[k2], b[k])).material_index = material


def cap(bm, verts, material: int = 0):
    face = bm.faces.new(verts)
    face.material_index = material
    return face


def loft(bm, start, axis, sections, sides: int, material: int = 0, cap_materials=(None, None),
         tip: float | None = None):
    """Loft polygon rings along ``axis`` from ``start``.

    ``sections``: list of (distance along axis, radius). ``tip``: if given, the
    loft ends in a point at that distance instead of a flat end cap.
    Returns the rings.
    """
    axis = Vector(axis).normalized()
    start = Vector(start)
    rings = [ring(bm, start + axis * d, r, sides, axis) for d, r in sections]
    for a, b in zip(rings, rings[1:]):
        bridge(bm, a, b, material)
    first_mat, last_mat = (material if m is None else m for m in cap_materials)
    cap(bm, list(reversed(rings[0])), first_mat)
    if tip is None:
        cap(bm, rings[-1], last_mat)
    else:
        apex = bm.verts.new(start + axis * tip)
        last = rings[-1]
        for k in range(sides):
            bm.faces.new((last[k], last[(k + 1) % sides], apex)).material_index = last_mat
    return rings


def box(bm, center, size, material: int = 0, bottom_scale: float = 1.0) -> None:
    """Axis-aligned box; ``bottom_scale`` < 1 tapers the lower face (hopper)."""
    cx, cy, cz = center
    sx, sy, sz = (0.5 * s for s in size)
    verts = []
    for z, k in ((-sz, bottom_scale), (sz, 1.0)):
        for x, y in ((-sx, -sy), (sx, -sy), (sx, sy), (-sx, sy)):
            verts.append(bm.verts.new((cx + x * k, cy + y * k, cz + z)))
    _box_faces(bm, verts, material)


def beam(bm, a, b, width: float, height: float | None = None, material: int = 0, up=(0, 0, 1)) -> None:
    """Box with a rectangular cross-section from point ``a`` to ``b``."""
    a, b = Vector(a), Vector(b)
    fwd = (b - a).normalized()
    up = Vector(up)
    if abs(fwd.dot(up)) > 0.99:
        up = Vector((1, 0, 0))
    side = fwd.cross(up).normalized()
    up = side.cross(fwd).normalized()
    hw, hh = 0.5 * width, 0.5 * (width if height is None else height)
    verts = []
    for base in (a, b):
        for s, u in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            verts.append(bm.verts.new(base + side * s * hw + up * u * hh))
    _box_faces(bm, verts, material)


def _box_faces(bm, v, material: int) -> None:
    for quad in (
        (v[0], v[1], v[2], v[3]), (v[4], v[5], v[6], v[7]),
        (v[0], v[1], v[5], v[4]), (v[1], v[2], v[6], v[5]),
        (v[2], v[3], v[7], v[6]), (v[3], v[0], v[4], v[7]),
    ):
        bm.faces.new(quad).material_index = material

