"""Hull built from superellipse cross-sections lofted along the ship axis.

Coordinate convention: nose points to +Y, up is +Z, the hull is centred on the
origin along Y. (The glTF exporter converts this to glTF's Y-up on export.)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import bmesh
import bpy

# Share of the ship's triangle budget the hull may use; the rest is reserved
# for wings, engines and greebles.
HULL_TRI_SHARE = 0.6

# (ring vertices, rings per segment), best quality first.
_RESOLUTIONS = ((32, 8), (24, 6), (20, 5), (16, 4), (12, 3), (8, 2), (8, 1), (6, 1))


@dataclass(frozen=True)
class ClassTraits:
    peak: float  # position (0 = tail, 1 = nose) of the widest section
    cockpit: float  # position of the cockpit hump
    hump: float  # hump height relative to local section height
    belly: float  # bottom half height relative to top half
    squareness_bias: float


CLASS_TRAITS = {
    "fighter": ClassTraits(peak=0.35, cockpit=0.68, hump=0.35, belly=0.75, squareness_bias=0.0),
    "interceptor": ClassTraits(peak=0.25, cockpit=0.6, hump=0.3, belly=0.7, squareness_bias=-0.1),
    "freighter": ClassTraits(peak=0.5, cockpit=0.88, hump=0.15, belly=1.0, squareness_bias=0.35),
    "corvette": ClassTraits(peak=0.45, cockpit=0.75, hump=0.25, belly=0.9, squareness_bias=0.2),
    "shuttle": ClassTraits(peak=0.5, cockpit=0.8, hump=0.2, belly=0.9, squareness_bias=0.1),
}


def choose_resolution(segments: int, tri_budget: int) -> tuple[int, int]:
    """Pick (ring_verts, ring_count) so the hull stays within ``tri_budget``.

    The hull has ``2 * ring_verts * ring_count`` triangles (quads between rings
    plus a triangle fan at nose and tail).
    """
    for verts, per_segment in _RESOLUTIONS:
        rings = segments * per_segment + 1
        if 2 * verts * rings <= tri_budget:
            return verts, rings
    verts, per_segment = _RESOLUTIONS[-1]
    return verts, segments * per_segment + 1


def _smoothstep(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def _sample(controls: list[float], t: float) -> float:
    """Catmull-Rom interpolation of evenly spaced control values at t in [0, 1]."""
    n = len(controls) - 1
    x = min(max(t, 0.0), 1.0) * n
    i = min(int(x), n - 1)
    f = x - i
    p0 = controls[max(i - 1, 0)]
    p1 = controls[i]
    p2 = controls[i + 1]
    p3 = controls[min(i + 2, n)]
    return 0.5 * (
        2 * p1 + (-p0 + p2) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f * f + (-p0 + 3 * p1 - 3 * p2 + p3) * f**3
    )


def envelope(t: float, peak: float, taper: float, nose_sharpness: float) -> float:
    """Base width profile, 0 at the nose tip, 1 at ``peak``."""
    if t <= peak:
        tail = max(1.0 - taper, 0.08)
        return tail + (1.0 - tail) * _smoothstep(t / peak if peak > 0 else 1.0)
    u = (1.0 - t) / (1.0 - peak)  # 1 at peak, 0 at nose
    exponent = 0.25 + 1.5 * nose_sharpness
    return u**exponent


def _superellipse(theta: float, exponent: float) -> tuple[float, float]:
    c, s = math.cos(theta), math.sin(theta)
    # cos(pi/2) is ~6e-17, which |c| ** 0.25 would blow up to ~1e-4.
    c = 0.0 if abs(c) < 1e-9 else c
    s = 0.0 if abs(s) < 1e-9 else s
    e = 2.0 / exponent
    return math.copysign(abs(c) ** e, c), math.copysign(abs(s) ** e, s)


def build_hull_mesh(params: dict, name: str = "Ship_Hull") -> bpy.types.Mesh:
    hp = params["hull"]
    traits = CLASS_TRAITS[params["class"]]
    rng = random.Random(f"{params['seed']}:hull")

    length = hp["length"]
    half_width = 0.5 * length * hp["width_ratio"]
    half_height = half_width * hp["height_ratio"]
    squareness = min(max(hp["squareness"] + traits.squareness_bias, 0.0), 1.0)
    exponent = 2.0 + 6.0 * squareness
    variation = hp["variation"]
    peak = min(max(traits.peak + rng.uniform(-0.08, 0.08) * variation, 0.15), 0.7)

    segments = hp["segments"]
    budget = int(params["max_tris"] * HULL_TRI_SHARE)
    ring_verts, ring_count = choose_resolution(segments, budget)

    # Per-control-point random modulation (bulges, pinches, spine offsets).
    def jitter(amount: float) -> list[float]:
        vals = [1.0 + rng.uniform(-amount, amount) * variation for _ in range(segments)]
        vals[-1] = 1.0  # keep the nose clean
        return vals

    width_mod = jitter(0.35)
    height_mod = jitter(0.35)
    spine_mod = [rng.uniform(-0.15, 0.15) * variation for _ in range(segments)]
    asym_mod = (
        [0.0] * segments
        if params["symmetry"]
        else [rng.uniform(-0.25, 0.25) * max(variation, 0.3) for _ in range(segments)]
    )

    bm = bmesh.new()
    rings = []
    for k in range(ring_count):
        t = k / ring_count  # last ring stops short of the tip
        env = envelope(t, peak, hp["taper"], hp["nose_sharpness"])
        w = max(half_width * env * _sample(width_mod, t), 1e-3)
        h_top = max(half_height * env * _sample(height_mod, t), 1e-3)
        h_bottom = h_top * traits.belly
        hump = traits.hump * h_top * math.exp(-(((t - traits.cockpit) / 0.12) ** 2))
        z_center = _sample(spine_mod, t) * half_height
        asym = _sample(asym_mod, t)
        y = (t - 0.5) * length

        ring = []
        for j in range(ring_verts):
            theta = math.pi / 2 + 2 * math.pi * j / ring_verts  # start at top: mirror symmetric
            sx, sz = _superellipse(theta, exponent)
            x = sx * w * (1.0 + asym if sx > 0 else 1.0 - asym)
            if sz >= 0:
                z = sz * h_top + hump * sz * sz  # hump only on the upper half
            else:
                z = sz * h_bottom
            ring.append(bm.verts.new((x, y, z_center + z)))
        rings.append(ring)

    tip_z = _sample(spine_mod, 1.0) * half_height
    tip = bm.verts.new((0.0, 0.5 * length, tip_z))
    tail_center = bm.verts.new((0.0, -0.5 * length, sum(v.co.z for v in rings[0]) / ring_verts))

    for a, b in zip(rings, rings[1:]):
        for j in range(ring_verts):
            j2 = (j + 1) % ring_verts
            bm.faces.new((a[j], a[j2], b[j2], b[j]))
    last = rings[-1]
    for j in range(ring_verts):
        bm.faces.new((last[j], last[(j + 1) % ring_verts], tip))
    first = rings[0]
    for j in range(ring_verts):
        bm.faces.new((first[(j + 1) % ring_verts], first[j], tail_center))

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()

    for poly in mesh.polygons:
        poly.use_smooth = True
    if hasattr(mesh, "use_auto_smooth"):  # Blender < 4.1
        mesh.use_auto_smooth = True
        mesh.auto_smooth_angle = math.radians(40)
    return mesh


def build_hull(params: dict, collection: bpy.types.Collection, parent=None) -> bpy.types.Object:
    mesh = build_hull_mesh(params)
    obj = bpy.data.objects.new("Ship_Hull", mesh)
    collection.objects.link(obj)
    obj.parent = parent
    if not hasattr(mesh, "use_auto_smooth"):  # Blender >= 4.1: smooth-by-angle modifier
        try:
            with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
                bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40))
        except (AttributeError, RuntimeError):
            pass
    return obj
