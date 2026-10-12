"""Hull kit: hand-designed sections joined at a standard joint, plus body plans.

Every section is a list of keyframes ``(u, width, top, bottom)``: ``u`` runs along
the section (tail: 0 = stern .. 1 = joint, mid: joint .. joint, nose: joint .. tip),
the other values are factors of the ship's beam / height. All sections start and
end at the standard joint (1, 1, 1), so any tail fits any mid fits any nose.

Coordinates as in the main generator: nose +Y, up +Z, centred on the origin.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import bmesh
from mathutils import Vector

from ..generator.hull import Station, cross_section
from ..generator import shapes

E = 0.02  # length of a hard step (in u)


@dataclass(frozen=True)
class Section:
    keys: tuple[tuple[float, float, float, float], ...]
    share: tuple[float, float]  # (min, max) fraction of the ship length


TAILS = {
    "flat": Section(((0, 1, 1, 1), (1, 1, 1, 1)), (0.08, 0.12)),
    "taper": Section(((0, 0.6, 0.7, 0.7), (1, 1, 1, 1)), (0.15, 0.2)),
    "flare": Section(((0, 1.3, 1.05, 1.05), (0.45, 1.3, 1.05, 1.05), (1, 1, 1, 1)), (0.15, 0.2)),
    "outboard": Section(((0, 0.7, 0.8, 0.8), (1, 1, 1, 1)), (0.12, 0.16)),
}
MIDS = {
    "straight": Section(((0, 1, 1, 1), (1, 1, 1, 1)), (0.3, 0.7)),
    "waist": Section(((0, 1, 1, 1), (0.5, 0.72, 0.9, 0.9), (1, 1, 1, 1)), (0.3, 0.7)),
    "bulge": Section(((0, 1, 1, 1), (0.5, 1.25, 1.1, 1.1), (1, 1, 1, 1)), (0.3, 0.7)),
    "stepped": Section(
        ((0, 1, 1, 1), (0.3, 1, 1, 1), (0.3 + E, 0.8, 0.85, 0.85), (0.7, 0.8, 0.85, 0.85),
         (0.7 + E, 1, 1, 1), (1, 1, 1, 1)),
        (0.3, 0.7),
    ),
    "sponson": Section(((0, 1, 1, 1), (1, 1, 1, 1)), (0.3, 0.7)),  # + side pods
}
NOSES = {
    "wedge": Section(((0, 1, 1, 1), (0.5, 0.6, 0.85, 0.75), (1, 0, 0.2, 0.2)), (0.25, 0.35)),
    "blunt": Section(((0, 1, 1, 1), (0.6, 0.95, 0.95, 0.9), (1, 0.75, 0.7, 0.65)), (0.12, 0.18)),
    "hammer": Section(
        ((0, 1, 1, 1), (0.35, 0.65, 0.9, 0.85), (0.6, 0.65, 0.9, 0.85), (0.6 + E, 1.45, 0.75, 0.7),
         (1, 1.45, 0.7, 0.65)),
        (0.2, 0.26),
    ),
    "cockpit": Section(((0, 1, 1, 1), (0.35, 0.85, 1.3, 0.9), (0.7, 0.55, 1.0, 0.7), (1, 0, 0.25, 0.2)), (0.22, 0.3)),
}
PLANS = ("mono", "twin", "fork")

# Which building blocks a class may use; the seed picks from these.
CLASS_KIT = {
    "miner": dict(plans=("mono", "fork", "twin"), tails=("flat", "flare", "outboard"),
                  mids=("straight", "stepped", "sponson", "bulge"), noses=("blunt", "hammer")),
    "freighter": dict(plans=("mono", "twin"), tails=("flat", "flare", "taper"),
                      mids=("straight", "stepped", "sponson", "waist"), noses=("blunt", "hammer", "cockpit")),
    "shuttle": dict(plans=("mono",), tails=("flat", "taper"), mids=("straight", "bulge", "waist"),
                    noses=("blunt", "cockpit")),
    "corvette": dict(plans=("mono", "twin"), tails=("taper", "flare", "outboard"),
                     mids=("straight", "stepped", "waist"), noses=("wedge", "hammer")),
    "fighter": dict(plans=("mono",), tails=("taper", "flare", "outboard"), mids=("straight", "waist", "bulge"),
                    noses=("wedge", "cockpit")),
    "interceptor": dict(plans=("mono",), tails=("taper", "outboard"), mids=("straight", "waist"),
                        noses=("wedge",)),
}
RIDGE = {"fighter": 0.35, "interceptor": 0.5, "corvette": 0.25, "shuttle": 0.1, "miner": 0.15, "freighter": 0.0}


@dataclass
class Socket:
    kind: str  # "engine", "nose", "side", "top"
    pos: Vector
    normal: Vector
    radius: float  # free radius around pos, perpendicular to the normal
    name: str = ""


@dataclass
class Design:
    """The chosen building blocks of one hull."""

    plan: str
    tail: str
    mid: str
    nose: str

    @classmethod
    def pick(cls, cls_name: str, seed, **overrides) -> "Design":
        kit = CLASS_KIT[cls_name]
        rng = random.Random(f"{seed}:design")
        d = cls(rng.choice(kit["plans"]), rng.choice(kit["tails"]), rng.choice(kit["mids"]), rng.choice(kit["noses"]))
        for key, value in overrides.items():
            if value is not None:
                setattr(d, key, value)
        if d.plan == "fork":
            d.nose = "blunt"  # the prongs need a flat front face between them
        return d

    def label(self) -> str:
        return f"{self.plan}/{self.tail}/{self.mid}/{self.nose}"


@dataclass
class HullLayout:
    """Absolute stations of one lofted body + where its sections are."""

    stations: list[Station]
    y_tail: float
    y_mid: tuple[float, float]
    y_front: float  # y of the front face (or tip)
    point_nose: bool
    x_offset: float = 0.0
    sockets: list[Socket] = field(default_factory=list)


def layout_body(design: Design, length: float, beam: float, height: float, seed: int) -> HullLayout:
    """Stations for one body (mono hull or one twin hull) centred at x = 0."""
    rng = random.Random(f"{seed}:shares")
    tail, mid, nose = TAILS[design.tail], MIDS[design.mid], NOSES[design.nose]
    f_tail = rng.uniform(*tail.share)
    f_nose = rng.uniform(*nose.share)
    f_mid = 1.0 - f_tail - f_nose
    y0 = -0.5 * length
    spans = ((tail, y0, f_tail * length), (mid, y0 + f_tail * length, f_mid * length),
             (nose, y0 + (f_tail + f_mid) * length, f_nose * length))
    top, bottom = 0.55 * height, 0.45 * height
    stations: list[Station] = []
    for i, (section, start, span) in enumerate(spans):
        keys = section.keys if i == 0 else section.keys[1:]  # joints are shared
        for u, w, t, b in keys:
            y = start + u * span
            stations.append(Station((y - y0) / length, beam * w, top * t, bottom * b, 0.0, 0.0))
    point = stations[-1].half_width <= 1e-6
    return HullLayout(stations, y0, (spans[1][1], spans[1][1] + spans[1][2]), 0.5 * length, point)


def loft_body(bm, layout: HullLayout, length: float, chamfer: float, ridge: float):
    """Closed, flat-shaded loft of the layout's stations."""
    y0 = -0.5 * length
    rings = []
    stations = layout.stations[:-1] if layout.point_nose else layout.stations
    for st in stations:
        y = y0 + st.t * length
        rings.append([bm.verts.new((layout.x_offset + x, y, z)) for x, z in cross_section(st, chamfer, ridge)])
    n = len(rings[0])
    for a, b in zip(rings, rings[1:]):
        for j in range(n):
            bm.faces.new((a[j], a[(j + 1) % n], b[(j + 1) % n], b[j]))
    caps = [bm.faces.new(list(reversed(rings[0])))]
    if layout.point_nose:
        tip = bm.verts.new((layout.x_offset, layout.y_front, 0.0))
        for j in range(n):
            bm.faces.new((rings[-1][j], rings[-1][(j + 1) % n], tip))
    else:
        caps.append(bm.faces.new(rings[-1]))
    bmesh.ops.poke(bm, faces=caps)


def section_at(layout: HullLayout, y: float, length: float) -> Station:
    t = (y + 0.5 * length) / length
    sts = layout.stations
    for a, b in zip(sts, sts[1:]):
        if a.t <= t <= b.t:
            f = 0.0 if b.t == a.t else (t - a.t) / (b.t - a.t)
            mix = lambda u, v: u + (v - u) * f  # noqa: E731
            return Station(t, mix(a.half_width, b.half_width), mix(a.top, b.top), mix(a.bottom, b.bottom), 0.0, 0.0)
    return sts[0] if t < sts[0].t else sts[-1]
