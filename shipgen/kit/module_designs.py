"""Cargo / ore / tank / habitat module designs in unit size for side and roof sockets.

Local frame at the socket: ``n`` = socket normal (out of the hull), ``t`` = along
the ship (+Y), ``u`` = up (+Z). Contract (the module's build space):
n in [-EMBED, DEPTH], t in [-HALF_LENGTH, HALF_LENGTH], u in [-HALF_HEIGHT, HALF_HEIGHT],
times the socket radius; closed pieces; mirrored sockets give mirrored modules.
Materials: 0 accent, 1 glow, 2 cargo.
"""

from __future__ import annotations

from mathutils import Vector

from ..generator import shapes

ACCENT, GLOW, CARGO = 0, 1, 2
EMBED, DEPTH, HALF_LENGTH, HALF_HEIGHT = 0.1, 0.9, 1.0, 0.5


class Frame:
    def __init__(self, pos, normal, m):
        self.o, self.n, self.m = Vector(pos), Vector(normal).normalized(), m
        self.t = Vector((0, 1, 0))
        if abs(self.n.z) > 0.9:  # roof socket: "up" of the module points outboard, so mirrored
            self.u = Vector((1.0 if self.o.x >= 0 else -1.0, 0, 0))  # sockets give mirrored modules
        else:
            self.u = Vector((0, 0, 1))

    def p(self, n, t, u):
        return self.o + (self.n * n + self.t * t + self.u * u) * self.m


def _hexa(bm, f: Frame, corners, material):
    """Box from 8 local corners: bottom ring (u-) then top ring (u+), each (n, t) ccw."""
    v = [bm.verts.new(f.p(*c)) for c in corners]
    for quad in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([v[i] for i in quad]).material_index = material


def _box(bm, f, n0, n1, t0, t1, u0, u1, material=CARGO, taper=0.0):
    """Local box; ``taper`` > 0 narrows the lower face (hopper shape)."""
    n1b = n1 - (n1 - n0) * taper
    inset = 0.3 * taper
    _hexa(bm, f, [
        (n0, t0 + inset, u0), (n1b, t0 + inset, u0), (n1b, t1 - inset, u0), (n0, t1 - inset, u0),
        (n0, t0, u1), (n1, t0, u1), (n1, t1, u1), (n0, t1, u1),
    ], material)


def crate(bm, f):
    _box(bm, f, -EMBED, 0.85, -0.95, 0.95, -0.45, 0.45)


def ribbed_container(bm, f):
    _box(bm, f, -EMBED, 0.8, -0.95, 0.95, -0.42, 0.42)
    for t in (-0.6, 0.0, 0.6):
        _box(bm, f, -EMBED, 0.88, t - 0.07, t + 0.07, -0.48, 0.48, material=ACCENT)


def double_container(bm, f):
    for t0, t1 in ((-0.98, -0.04), (0.04, 0.98)):
        _box(bm, f, -EMBED, 0.85, t0, t1, -0.45, 0.45)
    _box(bm, f, -EMBED, 0.3, -0.1, 0.1, -0.2, 0.2, material=ACCENT)  # coupling


def ore_hopper(bm, f):
    _box(bm, f, -EMBED, 0.9, -0.9, 0.9, -0.5, 0.45, taper=0.45)
    _box(bm, f, -EMBED, 0.92, -0.92, 0.92, 0.42, 0.5, material=ACCENT)  # rim


def ore_skip(bm, f):
    _box(bm, f, -EMBED, 0.88, -0.98, 0.98, -0.45, 0.45)
    _box(bm, f, 0.2, 0.9, -0.7, 0.7, 0.45, 0.5, material=ACCENT)  # hatch


def _cyl(bm, f, n, u, radius, t0, t1, sides=8, cones=True, material=CARGO):
    c0 = f.p(n, t0, u)
    sec = [(0.0, radius * 0.55), (0.15 * (t1 - t0), radius), (0.85 * (t1 - t0), radius), (t1 - t0, radius * 0.55)]
    if not cones:
        sec = [(0.0, radius), (t1 - t0, radius)]
    shapes.loft(bm, c0, f.t, [(d * f.m, rad * f.m) for d, rad in sec], sides=sides, material=material)


def tank_cylinder(bm, f):
    _cyl(bm, f, 0.43, 0.0, 0.45, -0.98, 0.98)
    _box(bm, f, -EMBED, 0.15, -0.6, 0.6, -0.15, 0.15, material=ACCENT)  # cradle


def tank_twin(bm, f):
    for u in (0.24, -0.24):
        _cyl(bm, f, 0.45, u, 0.24, -0.98, 0.98)
    _box(bm, f, -EMBED, 0.3, -0.7, 0.7, -0.4, 0.4, material=ACCENT)


def tank_spheres(bm, f):
    for t in (-0.5, 0.5):
        c = f.p(0.45, t - 0.45, 0.0)
        shapes.loft(bm, c, f.t, [(0, 0.2 * f.m), (0.25 * f.m, 0.45 * f.m), (0.65 * f.m, 0.45 * f.m), (0.9 * f.m, 0.2 * f.m)],
                    sides=8, material=CARGO)
    _box(bm, f, -EMBED, 0.2, -0.9, 0.9, -0.12, 0.12, material=ACCENT)


def habitat_drum(bm, f):
    for t0, t1, rad, mat in ((-0.98, -0.15, 0.45, CARGO), (-0.15, 0.15, 0.4, GLOW), (0.15, 0.98, 0.45, CARGO)):
        _cyl(bm, f, 0.45, 0.0, rad, t0, t1, sides=6, cones=False, material=mat)


def habitat_block(bm, f):
    _box(bm, f, -EMBED, 0.82, -0.95, 0.95, -0.45, 0.45)
    _box(bm, f, 0.6, 0.88, -0.85, 0.85, 0.05, 0.2, material=GLOW)  # window band


DESIGNS = (crate, ribbed_container, double_container, ore_hopper, ore_skip, tank_cylinder, tank_twin, tank_spheres,
           habitat_drum, habitat_block)
NAMES = tuple(f.__name__ for f in DESIGNS)
KIND = {"crate": "containers", "ribbed_container": "containers", "double_container": "containers",
        "ore_hopper": "hoppers", "ore_skip": "hoppers",
        "tank_cylinder": "tanks", "tank_twin": "tanks", "tank_spheres": "tanks",
        "habitat_drum": "habitat", "habitat_block": "habitat"}


def designs_of(kind: str) -> list[int]:
    return [i for i, name in enumerate(NAMES) if KIND[name] == kind]


def build(bm, design: int, pos, normal, radius: float) -> None:
    DESIGNS[design % len(DESIGNS)](bm, Frame(pos, normal, radius))
