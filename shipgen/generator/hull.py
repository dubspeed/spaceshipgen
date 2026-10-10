"""Low-poly hull: faceted 10-vertex cross-sections lofted along the ship axis.

Each ship class has its own plan-form (width/height keyframes from tail to nose),
so classes read differently from the top. Faces are flat shaded; edges stay sharp.

Coordinate convention: nose points to +Y, up is +Z, the hull spans exactly
``hull.length`` along Y centred on the origin.
"""

from __future__ import annotations

import bisect
import random
from dataclasses import dataclass

import bmesh
import bpy

# Share of the ship's triangle budget the hull may use; the rest is for wings,
# engines and greebles.
HULL_TRI_SHARE = 0.6

# Merge an even station into a keyframe if they are closer than this (in t).
_MIN_STATION_GAP = 0.04
# Half length (in t) of the step between two modules of a stepped hull.
_STEP = 0.008
# Nose narrower than this (relative to max width) becomes a single tip vertex.
_POINT_NOSE = 0.05


@dataclass(frozen=True)
class ClassProfile:
    # (t, width, height) keyframes; t: 0 = tail, 1 = nose; values relative to max
    keys: tuple[tuple[float, float, float], ...]
    ridge: float  # raises the top centre line into a spine (0 = flat roof)
    chamfer_bias: float  # added to (1 - squareness)
    stepped: bool = False  # variation as blocky modules with hard steps instead of bulges


CLASS_PROFILES = {
    # dart: wide engine section, long tapering nose with a canopy bump
    "fighter": ClassProfile(
        keys=((0.0, 0.75, 0.7), (0.18, 1.0, 0.85), (0.42, 0.8, 1.0), (0.62, 0.5, 1.0), (0.8, 0.28, 0.55), (1.0, 0.0, 0.15)),
        ridge=0.35, chamfer_bias=0.1,
    ),
    # needle: slim, very long nose
    "interceptor": ClassProfile(
        keys=((0.0, 0.6, 0.7), (0.15, 0.8, 0.8), (0.45, 0.5, 0.95), (0.7, 0.28, 0.7), (1.0, 0.0, 0.1)),
        ridge=0.5, chamfer_bias=0.15,
    ),
    # brick: constant-width cargo body, stepped-down cab, blunt nose
    "freighter": ClassProfile(
        keys=((0.0, 0.95, 0.95), (0.05, 1.0, 1.0), (0.78, 1.0, 1.0), (0.84, 0.82, 0.85), (1.0, 0.6, 0.55)),
        ridge=0.0, chamfer_bias=-0.2, stepped=True,
    ),
    # long hexagonal warship
    "corvette": ClassProfile(
        keys=((0.0, 0.8, 0.8), (0.12, 1.0, 1.0), (0.55, 0.9, 1.0), (0.8, 0.6, 0.8), (1.0, 0.22, 0.35)),
        ridge=0.25, chamfer_bias=0.0, stepped=True,
    ),
    # stubby van
    "shuttle": ClassProfile(
        keys=((0.0, 0.85, 0.85), (0.2, 1.0, 1.0), (0.68, 1.0, 1.0), (0.88, 0.75, 0.8), (1.0, 0.4, 0.5)),
        ridge=0.1, chamfer_bias=-0.05, stepped=True,
    ),
}


@dataclass(frozen=True)
class Station:
    t: float
    half_width: float
    top: float  # height above z_center
    bottom: float  # depth below z_center
    z_center: float
    asym: float  # right side scaled by (1 + asym), left by (1 - asym)


@dataclass(frozen=True)
class HullShape:
    """The hull's sections. Other parts (wings, engines) attach to it."""

    length: float
    stations: tuple[Station, ...]
    chamfer: float
    ridge: float
    point_nose: bool

    def y(self, t: float) -> float:
        return (t - 0.5) * self.length

    def section(self, t: float) -> Station:
        """Linearly interpolated section at t (0 = tail, 1 = nose)."""
        ts = [s.t for s in self.stations]
        i = min(max(bisect.bisect_right(ts, t) - 1, 0), len(ts) - 2)
        a, b = self.stations[i], self.stations[i + 1]
        f = min(max((t - a.t) / (b.t - a.t), 0.0), 1.0)
        mix = lambda u, v: u + (v - u) * f  # noqa: E731
        return Station(
            t, mix(a.half_width, b.half_width), mix(a.top, b.top), mix(a.bottom, b.bottom),
            mix(a.z_center, b.z_center), mix(a.asym, b.asym),
        )


def _profile_value(keys, t: float, idx: int) -> float:
    ts = [k[0] for k in keys]
    i = min(max(bisect.bisect_right(ts, t) - 1, 0), len(ts) - 2)
    a, b = keys[i], keys[i + 1]
    f = (t - a[0]) / (b[0] - a[0])
    return a[idx] + (b[idx] - a[idx]) * f


def _station_ts(keys, segments: int, with_even: bool, stepped: bool) -> tuple[list[float], set[int]]:
    """Station positions, and the module boundaries (indices 1..segments-1) that got a step."""
    ts = [k[0] for k in keys]
    steps: set[int] = set()
    if with_even:
        for i in range(1, segments):
            t = i / segments
            if all(abs(t - k) >= _MIN_STATION_GAP for k in ts):
                if stepped:
                    ts += [t - _STEP, t + _STEP]
                    steps.add(i)
                else:
                    ts.append(t)
    return sorted(ts), steps


def hull_shape(params: dict) -> HullShape:
    """Compute the hull's sections from parameters (no Blender data created)."""
    hp = params["hull"]
    profile = CLASS_PROFILES[params["class"]]
    rng = random.Random(f"{params['seed']}:hull")

    length = hp["length"]
    max_half_width = 0.5 * length * hp["width_ratio"]
    max_height = max_half_width * hp["height_ratio"]
    variation = hp["variation"]
    ns = hp["nose_sharpness"]

    keys = [list(k) for k in profile.keys]
    keys[0][1] *= 1.0 - 0.5 * hp["taper"]  # narrower tail
    keys[0][2] *= 1.0 - 0.3 * hp["taper"]
    nose_w = keys[-1][1] * (1.0 - 0.8 * ns) + 0.25 * (1.0 - ns) ** 2
    if keys[-1][1] > 0:
        keys[-1][2] *= nose_w / keys[-1][1]  # keep the nose face's proportions
    keys[-1][1] = nose_w
    point_nose = nose_w < _POINT_NOSE

    budget = int(params["max_tris"] * HULL_TRI_SHARE)
    segments = hp["segments"]
    ts, steps = _station_ts(keys, segments, True, profile.stepped)
    if 20 * len(ts) > budget:  # ~20 tris per ring; fall back to the class keyframes only
        ts, steps = _station_ts(keys, segments, False, profile.stepped)

    def asym() -> float:
        return 0.0 if params["symmetry"] else rng.uniform(-0.25, 0.25) * max(variation, 0.3)

    if profile.stepped:
        # One (width, height, asym) factor per module; modules only ever shrink, so
        # the hull's maximum width/height still follow the parameters. Boundaries
        # without a step (too close to a keyframe) merge with the previous module.
        modules = []
        for m in range(segments):
            if m > 0 and m not in steps:
                modules.append(modules[-1])
                continue
            nose_module = m == segments - 1
            pick = lambda: 1.0 - variation * rng.choice((0.0, 0.0, 0.12, 0.25))  # noqa: E731
            modules.append((1.0, 1.0, 0.0) if nose_module else (pick(), pick(), asym()))
        jitter = [modules[min(int(t * segments), segments - 1)] + (0.0,) for t in ts]
    else:
        jitter = []
        for i in range(len(ts)):
            inner = 0 < i < len(ts) - 1
            jitter.append((
                1.0 + rng.uniform(-0.25, 0.25) * variation if inner else 1.0,
                1.0 + rng.uniform(-0.25, 0.25) * variation if inner else 1.0,
                asym(),
                rng.uniform(-0.12, 0.12) * variation if inner else 0.0,
            ))

    stations = []
    for t, (jw, jh, a, jz) in zip(ts, jitter):
        w = max(max_half_width * _profile_value(keys, t, 1) * jw, 1e-3)
        h = max(max_height * _profile_value(keys, t, 2) * jh, 1e-3)
        stations.append(Station(t, w, h * 0.55, h * 0.45, jz * max_height, a))
    if point_nose:
        last = stations[-1]
        stations[-1] = Station(last.t, 0.0, 0.0, 0.0, last.z_center, 0.0)

    chamfer = min(max(1.0 - hp["squareness"] + profile.chamfer_bias, 0.0), 1.0)
    return HullShape(length, tuple(stations), chamfer, profile.ridge, point_nose)


def cross_section(st: Station, chamfer: float, ridge: float) -> list[tuple[float, float]]:
    """10 (x, z) points, clockwise from the top centre, mirror symmetric (unless asym)."""
    w, top, bot = st.half_width, st.top, st.bottom
    c = chamfer
    roof = top * (1.0 - 0.6 * ridge)
    right = [
        (w * (1.0 - 0.7 * c), roof),  # roof edge
        (w, roof * (0.55 - 0.45 * c)),  # upper side
        (w * (1.0 - 0.15 * c), -bot * 0.3),  # lower side
        (w * (1.0 - 0.6 * c) * 0.85, -bot),  # bottom edge
    ]
    pts = [(0.0, top)]
    pts += [(x * (1.0 + st.asym), z) for x, z in right]
    pts.append((0.0, -bot))
    pts += [(-x * (1.0 - st.asym), z) for x, z in reversed(right)]
    return [(x, z + st.z_center) for x, z in pts]


def build_hull_mesh(shape: HullShape, name: str = "Ship_Hull") -> bpy.types.Mesh:
    bm = bmesh.new()
    rings = []
    stations = shape.stations[:-1] if shape.point_nose else shape.stations
    for st in stations:
        y = shape.y(st.t)
        rings.append([bm.verts.new((x, y, z)) for x, z in cross_section(st, shape.chamfer, shape.ridge)])

    n = len(rings[0])
    for a, b in zip(rings, rings[1:]):
        for j in range(n):
            j2 = (j + 1) % n
            bm.faces.new((a[j], a[j2], b[j2], b[j]))

    bm.faces.new(list(reversed(rings[0])))  # flat tail (engine mount)
    if shape.point_nose:
        tip_st = shape.stations[-1]
        tip = bm.verts.new((0.0, shape.y(tip_st.t), tip_st.z_center))
        last = rings[-1]
        for j in range(n):
            bm.faces.new((last[j], last[(j + 1) % n], tip))
    else:
        bm.faces.new(rings[-1])

    # Fan the n-gon caps from their centre: a plain triangulation would create
    # zero-area triangles where boxy sections have collinear points.
    bmesh.ops.poke(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = False
    return mesh


def build_hull(params: dict, collection, parent=None) -> tuple[bpy.types.Object, HullShape]:
    shape = hull_shape(params)
    obj = bpy.data.objects.new("Ship_Hull", build_hull_mesh(shape))
    collection.objects.link(obj)
    obj.parent = parent
    return obj, shape
