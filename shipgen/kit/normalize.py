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


def _measure(build, design, normal):
    bm = bmesh.new()
    build(bm, design, Vector((0, 0, 0)), Vector(normal), 1.0)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    glow = sum(f.calc_area() for f in bm.faces if f.material_index == 1)
    volume = abs(bm.calc_volume())
    bm.free()
    return glow, volume


@functools.cache
def engine_factors() -> tuple[float, ...]:
    """Multiply an engine's thrust by this so all designs push alike at equal size."""
    areas = [_measure(engine_designs.build, i, (0, -1, 0))[0] for i in range(len(engine_designs.DESIGNS))]
    mean = sum(areas) / len(areas)
    return tuple(mean / a for a in areas)


def _by_kind(library, values) -> tuple[float, ...]:
    out = []
    for i, name in enumerate(library.NAMES):
        same = [values[j] for j in library.designs_of(library.KIND[name])]
        out.append((sum(same) / len(same)) / values[i])
    return tuple(out)


@functools.cache
def rig_factors() -> tuple[float, ...]:
    """Multiply mining power by this so all designs of a kind mine alike at equal size."""
    raw = [_measure(rig_designs.build, i, (0, 1, 0))[1] ** (2 / 3) for i in range(len(rig_designs.DESIGNS))]
    return _by_kind(rig_designs, raw)


@functools.cache
def module_factors() -> tuple[float, ...]:
    """Multiply module capacity by this so all designs of a kind hold alike at equal size."""
    raw = [_measure(module_designs.build, i, (1, 0, 0))[1] for i in range(len(module_designs.DESIGNS))]
    return _by_kind(module_designs, raw)


@functools.cache
def engine_volume_factors() -> tuple[float, ...]:
    vols = [_measure(engine_designs.build, i, (0, -1, 0))[1] for i in range(len(engine_designs.DESIGNS))]
    mean = sum(vols) / len(vols)
    return tuple(mean / v for v in vols)


@functools.cache
def rig_volume_factors() -> tuple[float, ...]:
    """Multiply a rig's mass by this so all designs of a kind weigh alike at equal size."""
    vols = [_measure(rig_designs.build, i, (0, 1, 0))[1] for i in range(len(rig_designs.DESIGNS))]
    return _by_kind(rig_designs, vols)


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
