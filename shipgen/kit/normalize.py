"""Keep the stats of one ship model stable while the seed changes its look.

The seed picks body plans and part designs; those must not swing the stats. Every
design is therefore normalised to the mean of its kind, measured on the unit-size
designs (glow area for engines, volume^(2/3) for rigs, volume for modules), and the
hull is scaled to the reference volume (see ``volume_scale``).
"""

from __future__ import annotations

import functools

import bmesh
from mathutils import Vector

from . import engine_designs, module_designs, rig_designs


# how each library is measured: unit design on a socket facing this way
_MOUNT = {"engines": (engine_designs, (0, -1, 0)), "rigs": (rig_designs, (0, 1, 0)),
          "modules": (module_designs, (1, 0, 0))}


@functools.cache
def _measured(library: str) -> tuple[tuple[float, float], ...]:
    """(glow area, volume) of every unit-size design of a library."""
    module, normal = _MOUNT[library]
    out = []
    for i in range(len(module.DESIGNS)):
        bm = bmesh.new()
        module.build(bm, i, Vector((0, 0, 0)), Vector(normal), 1.0)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        out.append((sum(f.calc_area() for f in bm.faces if f.material_index == 1), abs(bm.calc_volume())))
        bm.free()
    return tuple(out)


def _to_mean(values) -> tuple[float, ...]:
    mean = sum(values) / len(values)
    return tuple(mean / v for v in values)


def _by_kind(library, values) -> tuple[float, ...]:
    """Like _to_mean, but within each kind of the library (drills with drills ...)."""
    out = []
    for i, name in enumerate(library.NAMES):
        same = [values[j] for j in library.designs_of(library.KIND[name])]
        out.append((sum(same) / len(same)) / values[i])
    return tuple(out)


@functools.cache
def engine_factors() -> tuple[float, ...]:
    """Multiply an engine's thrust by this so all designs push alike at equal size."""
    return _to_mean([glow for glow, _ in _measured("engines")])


@functools.cache
def engine_volume_factors() -> tuple[float, ...]:
    """Multiply an engine's mass by this so all designs weigh alike at equal size."""
    return _to_mean([vol for _, vol in _measured("engines")])


@functools.cache
def rig_factors() -> tuple[float, ...]:
    """Multiply mining power by this so all designs of a kind mine alike at equal size."""
    return _by_kind(rig_designs, [vol ** (2 / 3) for _, vol in _measured("rigs")])


@functools.cache
def rig_volume_factors() -> tuple[float, ...]:
    """Multiply a rig's mass by this so all designs of a kind weigh alike at equal size."""
    return _by_kind(rig_designs, [vol for _, vol in _measured("rigs")])


@functools.cache
def module_factors() -> tuple[float, ...]:
    """Multiply module capacity (and mass) by this so all designs of a kind hold alike at equal size."""
    return _by_kind(module_designs, [vol for _, vol in _measured("modules")])


def cross_section_integral(layouts, length: float) -> float:
    """Integral of width x height along the ship over all bodies (trapezoid rule)."""
    total = 0.0
    for lay in layouts:
        sts = lay.stations
        for a, b in zip(sts, sts[1:]):
            dy = (b.t - a.t) * length
            fa = a.half_width * (a.top + a.bottom)
            fb = b.half_width * (b.top + b.bottom)
            total += 0.5 * (fa + fb) * dy
    return total
