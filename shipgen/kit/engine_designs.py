"""Ten engine designs, all built in unit size around a socket.

Contract (what makes every design fit every engine socket):
- the mount is at the socket position; ``d`` runs along the socket normal
  (thrust direction), from ``-EMBED`` (inside the hull / pylon) to at most ``MAX_LENGTH``;
- nothing extends further than radius 1 from the axis;
- the part is mirror symmetric about the vertical plane through its axis;
- every piece is a closed mesh; nozzle glow uses material index 1.
Scaling is uniform (``r``), never stretched.
"""

from __future__ import annotations

from mathutils import Vector

from ..generator import shapes

METAL, GLOW = 0, 1
EMBED = 0.6
MAX_LENGTH = 2.1


def _frame(axis: Vector):
    """(side, up) unit vectors perpendicular to ``axis``; side is horizontal."""
    side = axis.cross(Vector((0, 0, 1)))
    side = side.normalized() if side.length > 1e-6 else Vector((1, 0, 0))
    return side, side.cross(axis).normalized()


def _loft(bm, o, axis, r, sections, sides, glow_end=True):
    shapes.loft(bm, o, axis, [(d * r, rad * r) for d, rad in sections], sides=sides,
                cap_materials=(None, GLOW if glow_end else None))


def hex_nacelle(bm, o, axis, r):
    _loft(bm, o - axis * EMBED * r, axis, r, [(0, 0.85), (EMBED + 1.2, 1.0), (EMBED + 1.2, 0.72), (EMBED + 0.95, 0.72)], 6)


def bell(bm, o, axis, r):
    _loft(bm, o - axis * EMBED * r, axis, r,
          [(0, 0.6), (EMBED + 0.3, 0.6), (EMBED + 0.5, 0.5), (EMBED + 1.4, 1.0), (EMBED + 1.4, 0.85), (EMBED + 0.9, 0.45)], 8)


def ring_drive(bm, o, axis, r):
    _loft(bm, o - axis * EMBED * r, axis, r, [(0, 0.5), (EMBED + 1.1, 0.5), (EMBED + 1.1, 0.35), (EMBED + 0.95, 0.35)], 8)
    # the ring: a closed 8-sided tube (outer and inner wall)
    rings = [
        shapes.ring(bm, o + axis * d * r, rad * r, 8, axis)
        for d, rad in ((0.55, 1.0), (1.05, 1.0), (1.05, 0.8), (0.55, 0.8))
    ]
    for a, b in zip(rings, rings[1:] + rings[:1]):
        shapes.bridge(bm, a, b, GLOW if a is rings[1] else METAL)
    side, up = _frame(axis)
    for v in (side, -side, up, -up):  # struts
        shapes.beam(bm, o + axis * 0.8 * r + v * 0.45 * r, o + axis * 0.8 * r + v * 0.85 * r, 0.12 * r,
                    0.25 * r, METAL, up=axis)


def block(bm, o, axis, r):
    side, up = _frame(axis)
    shapes.beam(bm, o - axis * EMBED * r, o + axis * 1.2 * r, 1.6 * r, 1.0 * r, METAL, up=up)
    shapes.beam(bm, o + axis * 1.15 * r, o + axis * 1.25 * r, 1.3 * r, 0.45 * r, GLOW, up=up)


def twin_bell(bm, o, axis, r):
    side, up = _frame(axis)
    shapes.beam(bm, o - axis * EMBED * r, o + axis * 0.3 * r, 1.7 * r, 0.7 * r, METAL, up=up)
    for s in (1, -1):
        _loft(bm, o + side * s * 0.52 * r, axis, 0.47 * r,
              [(0, 0.6), (0.6, 0.6), (0.8, 0.5), (2.0, 1.0), (2.0, 0.85), (1.4, 0.45)], 8)


def finned(bm, o, axis, r):
    _loft(bm, o - axis * EMBED * r, axis, r, [(0, 0.7), (EMBED + 1.1, 0.7), (EMBED + 1.1, 0.5), (EMBED + 0.9, 0.5)], 6)
    side, up = _frame(axis)
    for v in (side, -side, up, -up):
        a, b = o + v * 0.78 * r, o + axis * 1.0 * r + v * 0.78 * r
        shapes.beam(bm, a, b, 0.08 * r, 0.3 * r, METAL, up=v)


def cluster(bm, o, axis, r):
    _loft(bm, o - axis * EMBED * r, axis, r, [(0, 0.95), (EMBED + 0.2, 0.95)], 8, glow_end=False)
    side, up = _frame(axis)
    for c in (up * 0.45, side * 0.45 - up * 0.3, -side * 0.45 - up * 0.3):
        _loft(bm, o + axis * 0.15 * r + c * r, axis, 0.4 * r, [(0, 1.0), (1.8, 1.0), (1.8, 0.7), (1.3, 0.7)], 6)


def long_pod(bm, o, axis, r):
    _loft(bm, o - axis * EMBED * r, axis, r,
          [(0, 0.5), (EMBED + 0.1, 0.7), (EMBED + 1.3, 0.7), (EMBED + 1.5, 0.6), (EMBED + 1.5, 0.45), (EMBED + 1.3, 0.45)], 8)


def ion_cone(bm, o, axis, r):
    _loft(bm, o - axis * EMBED * r, axis, r,
          [(0, 0.9), (EMBED + 0.2, 0.95), (EMBED + 1.1, 0.6), (EMBED + 1.1, 0.5), (EMBED + 0.8, 0.5)], 8)


def heavy_stack(bm, o, axis, r):
    _loft(bm, o - axis * EMBED * r, axis, r,
          [(0, 0.6), (EMBED + 0.2, 0.6), (EMBED + 0.2, 0.8), (EMBED + 0.7, 0.8), (EMBED + 0.7, 1.0),
           (EMBED + 1.3, 1.0), (EMBED + 1.3, 0.8), (EMBED + 1.0, 0.8)], 8)


DESIGNS = (hex_nacelle, bell, ring_drive, block, twin_bell, finned, cluster, long_pod, ion_cone, heavy_stack)
NAMES = tuple(f.__name__ for f in DESIGNS)


def build(bm, design: int, origin, axis, radius: float) -> None:
    DESIGNS[design % len(DESIGNS)](bm, Vector(origin), Vector(axis).normalized(), radius)
