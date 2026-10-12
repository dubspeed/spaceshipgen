"""Ten mining rig designs in unit size for the nose socket.

Same contract as engine_designs: mount at the socket, ``d`` along the socket
normal (forward) from ``-EMBED`` to at most ``MAX_LENGTH``, radius <= 1 around
the axis, mirror symmetric, closed pieces, glow = material index 1. Each design
belongs to a mining ``kind`` (the ``mining.type`` parameter); the seed picks a
design within the kind.
"""

from __future__ import annotations

from mathutils import Vector

from ..generator import shapes
from .engine_designs import _frame

METAL, GLOW = 0, 1
EMBED = 0.6
MAX_LENGTH = 2.2


def _base(bm, o, axis, r, radius=0.9, length=0.3):
    shapes.loft(bm, o - axis * EMBED * r, axis, [(0, radius * r), ((EMBED + length) * r, radius * r)], sides=8)


def drill_cone(bm, o, axis, r):
    _base(bm, o, axis, r)
    shapes.loft(bm, o + axis * 0.3 * r, axis, [(0, 0.75 * r), (0.6 * r, 0.6 * r), (1.0 * r, 0.42 * r)], sides=8,
                tip=1.9 * r)


def drill_triple(bm, o, axis, r):
    _base(bm, o, axis, r, 0.95, 0.2)
    side, up = _frame(axis)
    for c in (up * 0.45, side * 0.45 - up * 0.3, -side * 0.45 - up * 0.3):
        shapes.loft(bm, o + axis * 0.2 * r + c * r, axis, [(0, 0.38 * r), (0.5 * r, 0.3 * r)], sides=6, tip=1.5 * r)


def grinder_drum(bm, o, axis, r):
    _base(bm, o, axis, r, 0.7, 0.2)
    side, up = _frame(axis)
    for s in (1, -1):
        shapes.beam(bm, o + side * s * 0.62 * r, o + axis * 1.4 * r + side * s * 0.62 * r, 0.16 * r, 0.3 * r, METAL)
    drum = o + axis * 1.4 * r
    shapes.loft(bm, drum - side * 0.82 * r, side, [(0, 0.42 * r), (1.64 * r, 0.42 * r)], sides=8)
    for s in (1, -1):  # cutter rings
        shapes.loft(bm, drum + side * s * 0.32 * r - side * 0.06 * r, side, [(0, 0.47 * r), (0.12 * r, 0.47 * r)],
                    sides=8)


def laser_single(bm, o, axis, r):
    _base(bm, o, axis, r, 0.6, 0.2)
    shapes.beam(bm, o, o + axis * 1.3 * r, 0.32 * r, 0.32 * r, METAL)
    shapes.loft(bm, o + axis * 1.25 * r, axis, [(0, 0.36 * r), (0.6 * r, 0.36 * r), (0.6 * r, 0.24 * r), (0.45 * r, 0.24 * r)],
                sides=6, cap_materials=(None, GLOW))


def laser_twin(bm, o, axis, r):
    _base(bm, o, axis, r, 0.85, 0.15)
    side, _ = _frame(axis)
    for s in (1, -1):
        c = o + side * s * 0.55 * r
        shapes.beam(bm, c, c + axis * 1.1 * r, 0.24 * r, 0.24 * r, METAL)
        shapes.loft(bm, c + axis * 1.05 * r, axis, [(0, 0.3 * r), (0.5 * r, 0.3 * r), (0.5 * r, 0.2 * r), (0.38 * r, 0.2 * r)],
                    sides=6, cap_materials=(None, GLOW))


def laser_array(bm, o, axis, r):
    _base(bm, o, axis, r, 0.95, 0.35)
    side, up = _frame(axis)
    for c in (side + up, side - up, -side + up, -side - up):
        p = o + axis * 0.35 * r + c * 0.45 * r
        shapes.loft(bm, p, axis, [(0, 0.22 * r), (0.55 * r, 0.22 * r), (0.55 * r, 0.14 * r), (0.42 * r, 0.14 * r)],
                    sides=6, cap_materials=(None, GLOW))


def _claw_arm(bm, o, axis, out, r, scale):
    """Three-segment arm in the plane of ``axis`` and ``out``, closing towards the axis."""
    up = axis.cross(out)
    p0 = o + out * 0.5 * r
    p1 = p0 + out * 0.32 * r * scale + axis * 0.9 * r * scale
    p2 = p1 - out * 0.35 * r * scale + axis * 0.8 * r * scale
    p3 = p2 - out * 0.3 * r * scale + axis * 0.2 * r * scale
    shapes.beam(bm, p0, p1, 0.2 * r * scale, material=METAL, up=up)
    shapes.beam(bm, p1, p2, 0.17 * r * scale, material=METAL, up=up)
    shapes.beam(bm, p2, p3, 0.13 * r * scale, 0.26 * r * scale, material=METAL, up=up)


def claw_twin(bm, o, axis, r):
    _base(bm, o, axis, r, 0.7, 0.2)
    side, _ = _frame(axis)
    for s in (1, -1):
        _claw_arm(bm, o, axis, side * s, r, 1.0)


def claw_quad(bm, o, axis, r):
    _base(bm, o, axis, r, 0.7, 0.2)
    side, up = _frame(axis)
    for v in (side, -side, up, -up):
        _claw_arm(bm, o, axis, v, r, 0.85)


def scoop_funnel(bm, o, axis, r):
    rings = shapes.loft(bm, o - axis * EMBED * r, axis,
                        [(0, 0.45 * r), ((EMBED + 0.3) * r, 0.5 * r), ((EMBED + 1.4) * r, 0.98 * r)], sides=8)
    front = rings[-1]
    face = next(f for f in bm.faces if set(f.verts) == set(front))
    bm.faces.remove(face)
    inner = shapes.ring(bm, o + axis * 1.4 * r, 0.82 * r, 8, axis)
    throat = shapes.ring(bm, o + axis * 0.7 * r, 0.4 * r, 8, axis)
    shapes.bridge(bm, front, inner, METAL)
    shapes.bridge(bm, inner, throat, GLOW)
    shapes.cap(bm, throat, GLOW)


def scoop_ring(bm, o, axis, r):
    _base(bm, o, axis, r, 0.4, 1.0)
    shapes.loft(bm, o + axis * 1.0 * r, axis, [(0, 0.4 * r), (0.4 * r, 0.25 * r)], sides=8, cap_materials=(None, GLOW))
    rings = [shapes.ring(bm, o + axis * d * r, rad * r, 8, axis) for d, rad in ((1.1, 1.0), (1.6, 1.0), (1.6, 0.8), (1.1, 0.8))]
    for a, b in zip(rings, rings[1:] + rings[:1]):
        shapes.bridge(bm, a, b, GLOW if a is rings[2] else METAL)
    side, up = _frame(axis)
    for v in (side, -side, up, -up):
        shapes.beam(bm, o + axis * 1.35 * r + v * 0.3 * r, o + axis * 1.35 * r + v * 0.85 * r, 0.12 * r, 0.25 * r, METAL,
                    up=axis)


DESIGNS = (drill_cone, drill_triple, grinder_drum, laser_single, laser_twin, laser_array,
           claw_twin, claw_quad, scoop_funnel, scoop_ring)
NAMES = tuple(f.__name__ for f in DESIGNS)
KIND = {"drill_cone": "drill", "drill_triple": "drill", "grinder_drum": "drill",
        "laser_single": "laser", "laser_twin": "laser", "laser_array": "laser",
        "claw_twin": "claw", "claw_quad": "claw", "scoop_funnel": "scoop", "scoop_ring": "scoop"}


def designs_of(kind: str) -> list[int]:
    return [i for i, name in enumerate(NAMES) if KIND[name] == kind]


def build(bm, design: int, origin, axis, radius: float) -> None:
    DESIGNS[design % len(DESIGNS)](bm, Vector(origin), Vector(axis).normalized(), radius)
