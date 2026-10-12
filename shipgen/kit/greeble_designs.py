"""Greebles: small surface details in unit size (look only, no stats, no colliders).

Same local frame as module_designs (n = out of the hull, t = along the ship, u = up or,
on the roof, outboard). Contract: n in [-EMBED, MAX_HEIGHT], |t| <= 1, |u| <= 0.5, times the
socket radius; closed pieces; every design is mirror symmetric in u, so it may also sit on
the centre line. Materials: 0 accent, 1 glow, 2 cargo.
"""

from __future__ import annotations

from ..generator import shapes
from .module_designs import ACCENT, CARGO, GLOW, Frame, _box

EMBED, MAX_HEIGHT = 0.1, 2.0


def vent(bm, f):
    _box(bm, f, -EMBED, 0.25, -0.8, 0.8, -0.45, 0.45, material=ACCENT)
    for t in (-0.45, 0.0, 0.45):
        _box(bm, f, 0.2, 0.4, t - 0.1, t + 0.1, -0.4, 0.4, material=ACCENT)


def antenna(bm, f):
    _box(bm, f, -EMBED, 0.2, -0.3, 0.3, -0.3, 0.3, material=ACCENT)
    _box(bm, f, 0.15, 1.9, -0.05, 0.05, -0.05, 0.05, material=ACCENT)
    _box(bm, f, 1.3, 1.4, -0.06, 0.06, -0.45, 0.45, material=ACCENT)
    _box(bm, f, 1.85, 2.0, -0.08, 0.08, -0.08, 0.08, material=GLOW)


def dish(bm, f):
    _box(bm, f, -EMBED, 0.5, -0.12, 0.12, -0.12, 0.12, material=ACCENT)
    shapes.loft(bm, f.p(0.45, 0.0, 0.0), f.n, [(0.0, 0.12 * f.m), (0.35 * f.m, 0.48 * f.m)], sides=8,
                material=CARGO)


def panel(bm, f):
    _box(bm, f, -EMBED, 0.12, -0.95, 0.95, -0.45, 0.45, material=CARGO)
    _box(bm, f, 0.1, 0.18, -0.6, 0.6, -0.3, 0.3, material=ACCENT)


def pipes(bm, f):
    for u in (-0.25, 0.25):
        _box(bm, f, -EMBED, 0.22, -1.0, 1.0, u - 0.1, u + 0.1, material=ACCENT)
    for t in (-0.7, 0.7):
        _box(bm, f, -EMBED, 0.28, t - 0.08, t + 0.08, -0.4, 0.4, material=ACCENT)


def light(bm, f):
    _box(bm, f, -EMBED, 0.25, -0.25, 0.25, -0.2, 0.2, material=ACCENT)
    _box(bm, f, 0.2, 0.35, -0.15, 0.15, -0.12, 0.12, material=GLOW)


DESIGNS = (vent, antenna, dish, panel, pipes, light)
NAMES = tuple(f.__name__ for f in DESIGNS)


def build(bm, design: int, pos, normal, radius: float) -> None:
    DESIGNS[design % len(DESIGNS)](bm, Frame(pos, normal, radius))
