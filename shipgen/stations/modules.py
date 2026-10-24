"""Station modules: the kit the game assembles stations from.

Contract (every design):

- The station is built on a cubic grid of ``GRID`` metres. A module occupies whole cells
  (``Module.cells``, integer offsets in its own frame, (0, 0, 0) first) and stays inside them.
- Module frame: origin = centre of cell (0, 0, 0); +Y = main axis; the attaching port is on
  the -Y face of cell (0, 0, 0), so every design can hang off any free port.
- Ports sit in the middle of a cell face, with a flange collar of radius ``PORT_RADIUS`` that
  ends exactly on the face: two modules connect when their ports coincide and face each other.
- ``reserved`` cells stay free of other modules (a docking berth, where the ship lies).
- Berths (docking arms) say where a docked ship's centre goes, its nose direction (+Y) and up
  (+Z), plus the largest ship length that fits.
- Closed convex primitives; each one is also a convex collider piece (thin details excepted).

Materials: 0 hull, 1 accent, 2 glow, 3 cargo, 4 solar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from mathutils import Vector

from ..generator import shapes

GRID = 16.0  # metres per cell
PORT_RADIUS = 0.2 * GRID
COLLAR = 0.07 * GRID  # depth of a port's flange collar
NECK = 0.16 * GRID  # short tube from the collar into the module
HULL, ACCENT, GLOW, CARGO, SOLAR = range(5)
H = 0.5 * GRID

# berth sizes: largest ship length, half beam and half height (shop models: S <= 20 m, ...).
# A docked ship lies beside the pier in the next column of cells (L: the next two), in the
# pier's layer, its tail BERTH_GAP behind the module's first cell face.
BERTHS = {"S": (20.0, 6.0, 7.5), "M": (40.0, 7.5, 7.5), "L": (64.0, 15.0, 7.5)}
BERTH_GAP = 0.5


@dataclass
class Berth:
    pos: Vector  # where the docked ship's centre goes (module frame)
    nose: Vector  # ship nose direction (ship +Y)
    up: Vector  # ship up (ship +Z)
    size: str

    @property
    def max_length(self) -> float:
        return BERTHS[self.size][0]


@dataclass
class Module:
    """One built design in its own frame: the mesh pieces and the grid contract."""

    kind: str
    design: int
    cells: list[tuple[int, int, int]]
    ports: list[tuple[tuple[int, int, int], tuple[int, int, int]]]  # (cell, outward direction)
    reserved: list[tuple[int, int, int]] = field(default_factory=list)
    berths: list[Berth] = field(default_factory=list)
    pieces: list[list[Vector]] = field(default_factory=list)  # convex collider point sets


class Builder:
    """Adds closed primitives to ``bm`` and records the convex ones as collider pieces."""

    def __init__(self, bm, module: Module):
        self.bm, self.m = bm, module

    def _track(self, before: set, collide: bool):
        new = [v.co.copy() for v in self.bm.verts if v not in before]
        if collide and len(new) >= 4:
            self.m.pieces.append(new)

    def box(self, lo, hi, material=HULL, collide=True):
        before = set(self.bm.verts)
        lo, hi = Vector(lo), Vector(hi)
        shapes.box(self.bm, (lo + hi) / 2, hi - lo, material)
        self._track(before, collide)

    def loft(self, start, axis, sections, sides=8, material=HULL, collide=True, tip=None):
        """``sections`` = (distance, radius) in metres along ``axis`` from ``start``."""
        before = set(self.bm.verts)
        shapes.loft(self.bm, Vector(start), Vector(axis), sections, sides=sides, material=material, tip=tip)
        self._track(before, collide)

    def beam(self, a, b, w, h=None, material=ACCENT, collide=True, up=(0, 0, 1)):
        before = set(self.bm.verts)
        shapes.beam(self.bm, Vector(a), Vector(b), w, h, material, up=up)
        self._track(before, collide)

    def port(self, cell, direction):
        """Flange collar ending on the cell face, plus a neck towards the cell centre."""
        c, d = Vector(cell) * GRID, Vector(direction)
        face = c + d * H
        self.loft(face - d * COLLAR, d, [(0.0, PORT_RADIUS), (COLLAR, PORT_RADIUS)], sides=8, material=ACCENT)
        self.loft(face - d * (COLLAR + NECK), d, [(0.0, 0.7 * PORT_RADIUS), (NECK + 0.01, 0.7 * PORT_RADIUS)],
                  sides=8, material=HULL, collide=False)
        u = d.orthogonal().normalized()
        for k in (1, -1):  # two docking lights on the rim
            p = face - d * (0.5 * COLLAR) + u * k * PORT_RADIUS * 1.02
            self.box(p - Vector((0.2, 0.2, 0.2)), p + Vector((0.2, 0.2, 0.2)), GLOW, collide=False)


Y = Vector((0, 1, 0))
Z = Vector((0, 0, 1))
X = Vector((1, 0, 0))
IN = ((0, 0, 0), (0, -1, 0))  # the attaching port every module has


def _out(n_cells: int):
    return ((0, n_cells - 1, 0), (0, 1, 0))


# ---------------------------------------------------------------- designs

def hub(b: Builder, v: int):
    m = b.m
    m.cells = [(0, 0, 0)]
    dirs = [(0, -1, 0), (0, 1, 0), (1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1)]
    m.ports = [((0, 0, 0), d) for d in dirs]
    r = 0.4 * GRID
    if v == 0:  # octagonal drum
        b.loft((0, 0, -0.3 * GRID), Z, [(0, 0.7 * r), (0.12 * GRID, r), (0.48 * GRID, r), (0.6 * GRID, 0.7 * r)])
        b.loft((0, 0, -0.04 * GRID), Z, [(0, r * 1.02), (0.08 * GRID, r * 1.02)], material=GLOW, collide=False)
    elif v == 1:  # faceted ball
        b.loft((0, 0, -r), Z, [(0, 0.45 * r), (0.45 * r, 0.95 * r), (1.55 * r, 0.95 * r), (2 * r, 0.45 * r)], sides=8)
    else:  # chamfered block with corner pods
        s = 0.3 * GRID
        b.box((-s, -s, -s), (s, s, s))
        for x in (-1, 1):
            for y in (-1, 1):
                c = Vector((x, y, 0)) * 0.8 * s
                b.box(c - Vector((2, 2, 0.8 * s)), c + Vector((2, 2, 0.8 * s)), ACCENT)
        b.box((-0.6 * s, -0.6 * s, s), (0.6 * s, 0.6 * s, s + 0.4), GLOW, collide=False)
    for cell, d in m.ports:
        b.port(cell, d)


def corridor(b: Builder, v: int):
    m = b.m
    m.cells = [(0, 0, 0)]
    m.ports = [IN, _out(1)]
    if v == 0:  # pressurised tube with ribs
        b.loft((0, -H + 0.5 * COLLAR, 0), Y, [(0, 0.15 * GRID), (GRID - COLLAR, 0.15 * GRID)], sides=8)
        for y in (-0.25, 0.0, 0.25):
            b.loft((0, y * GRID - 0.6, 0), Y, [(0, 0.18 * GRID), (1.2, 0.18 * GRID)], sides=8, material=ACCENT,
                   collide=False)
    else:  # open truss
        s = 0.14 * GRID
        for x in (-s, s):
            for z in (-s, s):
                b.beam((x, -H + COLLAR, z), (x, H - COLLAR, z), 0.6, material=ACCENT)
        for y in (-0.3, 0.0, 0.3):
            b.box((-s - 0.4, y * GRID - 0.3, -s - 0.4), (s + 0.4, y * GRID + 0.3, s + 0.4), ACCENT, collide=False)
        b.loft((0, -H + 0.5 * COLLAR, 0), Y, [(0, 0.06 * GRID), (GRID - COLLAR, 0.06 * GRID)], sides=6,
               collide=False)  # cable duct
    for cell, d in m.ports:
        b.port(cell, d)


def habitat(b: Builder, v: int):
    m = b.m
    m.cells = [(0, 0, 0), (0, 1, 0)]
    m.ports = [IN, _out(2)]
    r = 0.42 * GRID
    y0, y1 = -H + COLLAR + 0.12 * GRID, 1.5 * GRID - COLLAR - 0.12 * GRID
    if v == 0:  # drum with window bands
        sides = 8
        b.loft((0, y0, 0), Y, [(0, 0.5 * r), (0.15 * GRID, r), (y1 - y0 - 0.15 * GRID, r), (y1 - y0, 0.5 * r)], sides=sides)
        for t in (0.3, 0.7):
            y = y0 + t * (y1 - y0)
            b.loft((0, y - 0.6, 0), Y, [(0, r * 1.02), (1.2, r * 1.02)], sides=sides, material=GLOW, collide=False)
    else:  # three pods around a spine
        b.loft((0, y0, 0), Y, [(0, 0.16 * GRID), (y1 - y0, 0.16 * GRID)], sides=8)
        for k in range(3):
            a = math.pi / 2 + k * 2 * math.pi / 3
            c = Vector((math.cos(a), 0, math.sin(a))) * 0.27 * GRID
            b.loft(c + Y * (y0 + 0.08 * GRID), Y, [(0, 0.08 * GRID), (0.1 * GRID, 0.15 * GRID),
                                                   (y1 - y0 - 0.26 * GRID, 0.15 * GRID), (y1 - y0 - 0.16 * GRID, 0.08 * GRID)],
                   sides=6)
            win = c * 1.55
            b.box(win + Vector((-0.5, y0 + 0.3 * GRID, -0.5)), win + Vector((0.5, y1 - 0.3 * GRID, 0.5)), GLOW,
                  collide=False)
    for cell, d in m.ports:
        b.port(cell, d)


def _spine(b, n_cells, r=0.07):
    y0, y1 = -H + COLLAR, (n_cells - 0.5) * GRID - COLLAR
    b.box((-r * GRID, y0, -r * GRID), (r * GRID, y1, r * GRID), ACCENT)
    return y0, y1


def storage(b: Builder, v: int):
    m = b.m
    m.cells = [(0, 0, 0), (0, 1, 0)]
    m.ports = [IN, _out(2)]
    y0, y1 = _spine(b, 2)
    rows = 3 if v == 0 else 2
    slot = (y1 - y0 - 2.0) / rows
    sides = ((1, 0), (-1, 0), (0, 1), (0, -1)) if v != 2 else ((1, 0), (-1, 0))
    for sx, sz in sides:
        for k in range(rows):
            ya, yb = y0 + 1.0 + k * slot + 0.4, y0 + 1.0 + (k + 1) * slot - 0.4
            n = Vector((sx, 0, sz))
            t = Vector((sz, 0, sx))  # across
            lo = n * 0.08 * GRID - t * 0.22 * GRID
            hi = n * (0.42 if v == 2 else 0.36) * GRID + t * 0.22 * GRID
            lo, hi = Vector(map(min, lo, hi)), Vector(map(max, lo, hi))
            b.box((lo.x, ya, lo.z), (hi.x, yb, hi.z), CARGO)
    for y in (y0 + 0.3, y1 - 0.3):
        b.box((-0.3 * GRID, y - 0.3, -0.3 * GRID), (0.3 * GRID, y + 0.3, 0.3 * GRID), ACCENT, collide=False)
    for cell, d in m.ports:
        b.port(cell, d)


def silo(b: Builder, v: int):
    m = b.m
    m.cells = [(0, 0, 0), (0, 1, 0)]
    m.ports = [IN, _out(2)]
    y0, y1 = _spine(b, 2)
    count = 4 if v == 0 else 3
    r = (0.16 if v == 0 else 0.19) * GRID
    for k in range(count):
        a = math.pi / 4 + k * 2 * math.pi / count
        c = Vector((math.cos(a), 0, math.sin(a))) * (0.48 * GRID - r)
        length = y1 - y0 - 2.0
        b.loft(c + Y * (y0 + 1.0), Y, [(0, 0.35 * r), (0.2 * length, r), (0.92 * length, r), (length, 0.7 * r)], sides=6,
               material=CARGO)
        for t in (0.45, 0.75):
            b.loft(c + Y * (y0 + 1.0 + t * length), Y, [(0, 1.04 * r), (0.8, 1.04 * r)], sides=6, material=ACCENT,
                   collide=False)
    for cell, d in m.ports:
        b.port(cell, d)


def tank(b: Builder, v: int):
    m = b.m
    m.cells = [(0, 0, 0)]
    m.ports = [IN, _out(1)]
    y0, y1 = _spine(b, 1)
    if v == 0:  # four spheres
        r = 0.17 * GRID
        for k in range(4):
            a = math.pi / 4 + k * math.pi / 2
            c = Vector((math.cos(a), 0, math.sin(a))) * 0.26 * GRID
            b.loft(c - Y * r, Y, [(0, 0.45 * r), (0.35 * r, r), (1.65 * r, r), (2 * r, 0.45 * r)], sides=8,
                   material=CARGO)
    else:  # one big cylinder around the spine
        r = 0.4 * GRID
        length = y1 - y0 - 1.0
        b.loft(Y * (y0 + 0.5), Y, [(0, 0.5 * r), (0.2 * length, r), (0.8 * length, r), (length, 0.5 * r)], sides=10,
               material=CARGO)
    for cell, d in m.ports:
        b.port(cell, d)


def refinery(b: Builder, v: int):
    m = b.m
    m.cells = [(0, 0, 0), (0, 1, 0)]
    m.ports = [IN, _out(2)]
    y0, y1 = -H + COLLAR + 0.1 * GRID, 1.5 * GRID - COLLAR - 0.1 * GRID
    w = 0.34 * GRID
    b.box((-w, y0, -0.26 * GRID), (w, y1, 0.22 * GRID))
    b.box((-0.5 * w, y0 + 0.2 * GRID, -0.46 * GRID), (0.5 * w, y0 + 0.8 * GRID, -0.26 * GRID), CARGO)  # ore intake
    stacks = (-0.2, 0.2) if v == 0 else (-0.25, 0.0, 0.25)
    for k, x in enumerate(stacks):
        y = y0 + (0.55 + 0.25 * (k % 2)) * (y1 - y0)
        b.loft((x * GRID, y, 0.22 * GRID), Z, [(0, 0.07 * GRID), (0.2 * GRID, 0.06 * GRID)], sides=6, material=ACCENT)
        b.loft((x * GRID, y, 0.42 * GRID), Z, [(0, 0.065 * GRID), (0.04 * GRID, 0.065 * GRID)], sides=6, material=GLOW,
               collide=False)
    for x in (-1, 1):  # furnace windows
        b.box((x * w - 0.2, y0 + 0.15 * GRID, -0.1 * GRID), (x * w + 0.2, y1 - 0.15 * GRID, 0.0), GLOW, collide=False)
    for cell, d in m.ports:
        b.port(cell, d)


def _dock(b: Builder, v: int, size: str, n_cells: int):
    m = b.m
    m.cells = [(0, k, 0) for k in range(n_cells)]
    m.ports = [IN]
    length, half_beam, half_height = BERTHS[size]
    pier = 0.1 * GRID
    y0, y1 = -H + COLLAR, (n_cells - 0.5) * GRID - 0.1 * GRID
    b.box((-pier, y0, -pier), (pier, y1, pier))
    for x in (-pier, pier):  # walkway rails
        b.box((x - 0.3, y0, pier), (x + 0.3, y1, pier + 0.5), ACCENT, collide=False)
    b.box((-pier * 1.6, y1 - 0.15 * GRID, -pier * 1.6), (pier * 1.6, y1 + 0.3, pier * 1.6), ACCENT)
    b.box((-0.6, y1 + 0.3, -0.6), (0.6, y1 + 0.06 * GRID, 0.6), GLOW, collide=False)  # beacon
    offset = H + BERTH_GAP + half_beam
    mid = -H + BERTH_GAP + 0.5 * length
    sides = (1, -1) if v == 0 else (1,)
    clamps = max(2, n_cells + 1)
    for s in sides:
        for k in range(clamps):
            y = y0 + (k + 0.5) * (y1 - y0) / clamps
            reach = H - 0.6
            # clamps: slender, no colliders (ships snap to the berth, they don't fly between them)
            b.beam((0, y, 0), (s * reach, y, 0), 0.05 * GRID, material=ACCENT, collide=False)
            b.box((s * reach - 0.5, y - 0.1 * GRID, -0.16 * GRID), (s * reach + 0.5, y + 0.1 * GRID, 0.12 * GRID),
                  ACCENT, collide=False)
            b.box((s * reach - 0.2, y - 0.2, 0.12 * GRID), (s * reach + 0.2, y + 0.2, 0.12 * GRID + 0.4), GLOW,
                  collide=False)
        m.berths.append(Berth(Vector((s * offset, mid, 0.0)), Y.copy(), Z.copy(), size))
    # the berths: every cell a docked ship's box touches stays free
    own = set(m.cells)
    res = set()
    for br in m.berths:
        lo = br.pos - Vector((half_beam, 0.5 * length, half_height))
        hi = br.pos + Vector((half_beam, 0.5 * length, half_height))
        rng = [range(math.floor((lo[i] + H) / GRID), math.floor((hi[i] + H - 1e-6) / GRID) + 1) for i in range(3)]
        res |= {(x, y, z) for x in rng[0] for y in rng[1] for z in rng[2]} - own
    m.reserved = sorted(res)
    for cell, d in m.ports:
        b.port(cell, d)


def dock_s(b, v):
    _dock(b, v, "S", 1)


def dock_m(b, v):
    _dock(b, v, "M", 2)


def dock_l(b, v):
    _dock(b, v, "L", 4)


def solar(b: Builder, v: int):
    m = b.m
    span = 2 if v == 0 else 1
    m.cells = [(0, 0, 0)] + [(s * k, 0, 0) for k in range(1, span + 1) for s in (1, -1)]
    m.ports = [IN]
    y0 = -H + COLLAR
    b.loft((0, y0, 0), Y, [(0, 0.08 * GRID), (0.75 * GRID, 0.08 * GRID)], sides=6, material=ACCENT)
    rows = (0.05,) if v == 0 else (-0.12, 0.28)
    tip = (span + 0.47) * GRID
    for y in rows:
        b.beam((-tip, y * GRID, 0), (tip, y * GRID, 0), 0.04 * GRID, material=ACCENT)
        for s in (1, -1):
            x0, x1 = s * 0.12 * GRID, s * tip
            lo, hi = min(x0, x1), max(x0, x1)
            b.box((lo, y * GRID - 0.17 * GRID, -0.08), (hi, y * GRID + 0.17 * GRID, 0.08), SOLAR)
    for cell, d in m.ports:
        b.port(cell, d)


def radiator(b: Builder, v: int):
    m = b.m
    m.cells = [(0, 0, 0), (0, 0, 1), (0, 0, -1)]
    m.ports = [IN]
    y0 = -H + COLLAR
    b.loft((0, y0, 0), Y, [(0, 0.07 * GRID), (0.85 * GRID, 0.07 * GRID)], sides=6, material=ACCENT)
    fins = (-0.2, 0.05, 0.3) if v == 0 else (-0.1, 0.25)
    for y in fins:
        b.box((-0.03 * GRID, y * GRID - 0.08 * GRID, -1.45 * GRID), (0.03 * GRID, y * GRID + 0.08 * GRID, 1.45 * GRID))
        b.box((-0.05 * GRID, y * GRID - 0.02 * GRID, -1.45 * GRID), (0.05 * GRID, y * GRID + 0.02 * GRID, 1.45 * GRID),
              ACCENT, collide=False)
    for cell, d in m.ports:
        b.port(cell, d)


def antenna(b: Builder, v: int):
    m = b.m
    m.cells = [(0, 0, 0)]
    m.ports = [IN]
    y0 = -H + COLLAR
    b.loft((0, y0, 0), Y, [(0, 0.06 * GRID), (0.55 * GRID, 0.04 * GRID)], sides=6, material=ACCENT)
    if v == 0:  # dish looking along the axis
        b.loft((0, 0.05 * GRID, 0), Y, [(0, 0.06 * GRID), (0.3 * GRID, 0.42 * GRID), (0.33 * GRID, 0.42 * GRID)],
               sides=10, material=HULL)
    else:  # mast with cross bars
        b.beam((0, 0.0, 0), (0, 0.45 * GRID, 0), 0.03 * GRID, material=ACCENT)
        for y in (0.15, 0.3):
            b.beam((-0.4 * GRID, y * GRID, 0), (0.4 * GRID, y * GRID, 0), 0.025 * GRID, material=ACCENT)
    b.box((-0.4, 0.44 * GRID, -0.4), (0.4, 0.47 * GRID, 0.4), GLOW, collide=False)
    for cell, d in m.ports:
        b.port(cell, d)


def command(b: Builder, v: int):
    m = b.m
    m.cells = [(0, 0, 0)]
    m.ports = [IN]
    y0 = -H + COLLAR + 0.12 * GRID
    if v == 0:  # tapered bridge with a window band
        b.loft((0, y0, 0), Y, [(0, 0.3 * GRID), (0.35 * GRID, 0.4 * GRID), (0.75 * GRID, 0.3 * GRID)], sides=8)
        b.loft((0, y0 + 0.3 * GRID, 0), Y, [(0, 0.405 * GRID), (0.1 * GRID, 0.39 * GRID)], sides=8, material=GLOW,
               collide=False)
    else:  # stepped block: lower deck and a bridge with a window front
        b.box((-0.36 * GRID, y0, -0.24 * GRID), (0.36 * GRID, y0 + 0.55 * GRID, 0.08 * GRID))
        b.box((-0.26 * GRID, y0 + 0.1 * GRID, 0.08 * GRID), (0.26 * GRID, y0 + 0.66 * GRID, 0.3 * GRID))
        b.box((-0.22 * GRID, y0 + 0.66 * GRID, 0.14 * GRID), (0.22 * GRID, y0 + 0.68 * GRID, 0.26 * GRID), GLOW,
              collide=False)
        for x in (-1, 1):
            b.box((x * 0.36 * GRID - 0.3, y0 + 0.1 * GRID, -0.1 * GRID), (x * 0.36 * GRID + 0.3, y0 + 0.45 * GRID,
                  -0.02 * GRID), GLOW, collide=False)
    for cell, d in m.ports:
        b.port(cell, d)


DESIGNS = {
    "hub": (hub, 3), "corridor": (corridor, 2), "habitat": (habitat, 2), "storage": (storage, 3),
    "silo": (silo, 2), "tank": (tank, 2), "refinery": (refinery, 2),
    "dock_s": (dock_s, 2), "dock_m": (dock_m, 2), "dock_l": (dock_l, 2),
    "solar": (solar, 2), "radiator": (radiator, 2), "antenna": (antenna, 2), "command": (command, 2),
}
KINDS = tuple(DESIGNS)
NAME = {"hub": "Hub", "corridor": "Corridor", "habitat": "Habitat", "storage": "Storage", "silo": "Silo",
        "tank": "Tank", "refinery": "Refinery", "dock_s": "DockS", "dock_m": "DockM", "dock_l": "DockL",
        "solar": "Solar", "radiator": "Radiator", "antenna": "Antenna", "command": "Command"}


def build(bm, kind: str, design: int) -> Module:
    fn, count = DESIGNS[kind]
    m = Module(kind, design % count, [], [])
    fn(Builder(bm, m), design % count)
    return m
