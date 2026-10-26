"""Space stations from a module kit on a cubic grid (contract: ``modules.py``).

    station = stations.generate({"role": "mining", "size": "medium", "seed": 3})
    kit = stations.build_kit({"style": {"palette": "white_red"}})   # every module design, unassembled

The game can assemble stations itself from the kit (ports on a ``GRID`` metre grid) or use
the layouts made here: a vertical spine of hubs with role-specific core modules between them,
symmetric arms on every hub (two or four, each a chain of modules ending in a docking pier,
solar array, radiator ...), and spine ends. A module is only placed where its cells and its
reserved cells (docking berths) are free.

Objects: ``Station`` (or ``StationKit``) -> one mesh per module, ``<Name>_<i>`` (``Hub_0``,
``DockM_1``; kit: ``<Name>_v<design>``), origin = centre of its first cell, local +Y = its main
axis, extras ``station_module``; children: convex ``<name>_col_<j>-convcolonly`` colliders,
``<name>_Port_<k>`` empties (local +Y = outward, extras ``station_port``) and, on docks,
``<name>_Berth_<k>`` empties (where a docked ship's origin goes: local +Y = ship nose, +Z = up,
so a ship node can take the berth's transform as is; extras ``station_berth``).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import bmesh
import bpy
from mathutils import Matrix, Vector

from .. import decals, fx, meshutil
from ..generator import Ship
from ..generator import clear as _clear
from ..generator.materials import _principled, create_materials
from ..kit import collision
from . import modules
from . import params as params_mod
from .modules import GRID, KINDS, NAME

COLLECTION = "ShipGen_Station"
DENSITY = 0.1  # t/m^3 of module mesh volume (mostly hollow)
USABLE = 0.85  # share of a cargo shell's volume that holds cargo
M3_PER_CREW = 20.0
SOLAR_KW_PER_M2 = 0.25
RADIATOR_KW_PER_M2 = 0.5
REFINE_PER_M3 = 0.02  # m^3 of ore per hour per m^3 of refinery
COLLIDER_MERGE = 0.3  # neighbouring pieces merge while their hull grows less than this (fewer shapes)

# role -> core modules on the spine, arm chains, top and bottom ends of the spine
ROLES = {
    "outpost": dict(core=["habitat", "storage"],
                    arms=[["dock_s"], ["solar"], ["habitat", "dock_s"], ["corridor", "dock_m"], ["radiator"]],
                    docks=[["dock_s"], ["habitat", "dock_s"], ["corridor", "dock_m"]],
                    top=["antenna", "command"], bottom=["solar", "radiator", "tank"]),
    "mining": dict(core=["refinery", "silo", "silo", "tank"],
                   arms=[["silo", "dock_l"], ["corridor", "dock_m"], ["refinery", "dock_m"], ["solar"], ["radiator"],
                         ["silo", "dock_m"]],
                   docks=[["silo", "dock_l"], ["refinery", "dock_m"], ["silo", "dock_m"]],
                   top=["command", "antenna"], bottom=["radiator", "tank", "dock_l"]),
    "trade": dict(core=["storage", "habitat", "storage", "tank"],
                  arms=[["storage", "dock_l"], ["dock_m"], ["corridor", "dock_s"], ["habitat", "dock_m"],
                        ["storage", "dock_m"], ["solar"]],
                  docks=[["storage", "dock_l"], ["storage", "dock_m"], ["habitat", "dock_m"]],
                  top=["command", "antenna"], bottom=["solar", "dock_m", "radiator"]),
}
# the massive look: 3x3x3 cores instead of hubs, modules that fill their cells, heavy docks
ROLES_MASSIVE = {
    "outpost": dict(core=["quarters", "hall"],
                    arms=[["dock_heavy_s"], ["solar"], ["quarters", "dock_heavy_s"], ["bulkhead", "dock_heavy_m"],
                          ["radiator"]],
                    docks=[["dock_heavy_s"], ["quarters", "dock_heavy_s"], ["bulkhead", "dock_heavy_m"]],
                    top=["antenna", "command"], bottom=["solar", "radiator", "tank"]),
    "mining": dict(core=["smelter", "silo", "hall"],
                   arms=[["smelter", "dock_heavy_l"], ["bulkhead", "dock_heavy_m"], ["silo", "dock_heavy_m"],
                         ["solar"], ["radiator"], ["smelter", "bulkhead"]],
                   docks=[["smelter", "dock_heavy_l"], ["bulkhead", "dock_heavy_l"], ["silo", "dock_heavy_m"]],
                   top=["command", "antenna"], bottom=["radiator", "tank", "dock_heavy_l"]),
    "trade": dict(core=["hall", "quarters", "hall"],
                  arms=[["hall", "dock_heavy_l"], ["dock_heavy_m"], ["bulkhead", "dock_heavy_s"],
                        ["quarters", "dock_heavy_m"], ["hall", "dock_heavy_m"], ["solar"]],
                  docks=[["hall", "dock_heavy_l"], ["hall", "dock_heavy_m"], ["quarters", "dock_heavy_m"]],
                  top=["command", "antenna"], bottom=["solar", "dock_heavy_m", "radiator"]),
}
HUBS = {"small": 1, "medium": 2, "large": 3}
ROLE_CODE = {"outpost": "OP", "mining": "MI", "trade": "TR"}


def _rotations() -> list[Matrix]:
    """The 24 rotations of the cube (integer matrices)."""
    axes = [Vector(v) for v in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))]
    out = []
    for x in axes:
        for y in axes:
            if abs(x.dot(y)) < 0.5:
                out.append(Matrix((x, y, x.cross(y))).transposed())
    return out


ROTATIONS = _rotations()


def _key(v) -> tuple[int, int, int]:
    return tuple(int(round(c)) for c in v)


@dataclass
class Placement:
    kind: str
    design: int
    rot: Matrix
    origin: Vector  # cell of the module's (0, 0, 0)
    contract: modules.Module
    name: str = ""
    connected: set = field(default_factory=set)  # indices of its ports in use

    def cell(self, local) -> tuple[int, int, int]:
        return _key(self.origin + self.rot @ Vector(local))

    def cells(self):
        return [self.cell(c) for c in self.contract.cells]

    def reserved(self):
        return [self.cell(c) for c in self.contract.reserved]

    def ports(self):
        """(index, world cell, world direction)."""
        return [(i, self.cell(c), _key(self.rot @ Vector(d))) for i, (c, d) in enumerate(self.contract.ports)]

    def matrix(self) -> Matrix:
        return Matrix.Translation(self.origin * GRID) @ self.rot.to_4x4()


@dataclass
class Station:
    root: object
    parts: list  # module objects
    placements: list
    params: dict
    warnings: list[str] = field(default_factory=list)
    colliders: list = field(default_factory=list)
    empties: list = field(default_factory=list)  # ports and berths
    stats: dict = field(default_factory=dict)

    bounds = Ship.bounds

    @property
    def objects(self):
        return [self.root, *self.parts, *self.colliders, *self.empties]


_CONTRACTS: dict = {}


def contract(kind: str, design: int) -> modules.Module:
    """Cells, ports, reserved cells and berths of a design (built once, mesh thrown away)."""
    key = (kind, design)
    if key not in _CONTRACTS:
        bm = bmesh.new()
        _CONTRACTS[key] = modules.build(bm, kind, design)
        bm.free()
    return _CONTRACTS[key]


# ---------------------------------------------------------------- layout

class _Layout:
    def __init__(self, designs: dict):
        self.designs = designs
        self.placed: list[Placement] = []
        self.occupied: dict = {}
        self.reserved: set = set()

    def fits(self, pl: Placement) -> bool:
        cells, res = pl.cells(), pl.reserved()
        return (not any(c in self.occupied or c in self.reserved for c in cells)
                and not any(c in self.occupied for c in res))

    def candidate(self, kind: str, parent: Placement, port: int, up: Vector) -> Placement | None:
        """``kind`` hung off ``parent``'s port, its +Z as close to ``up`` as the port allows."""
        _, cell, d = parent.ports()[port]
        d = Vector(d)
        rots = [r for r in ROTATIONS if (r @ Vector((0, 1, 0)) - d).length < 1e-6]
        rot = max(rots, key=lambda r: (r @ Vector((0, 0, 1))).dot(up))
        design = self.designs[kind]
        return Placement(kind, design, rot, Vector(cell) + d, contract(kind, design))

    def add(self, pl: Placement, parent: Placement | None = None, port: int | None = None) -> None:
        for c in pl.cells():
            self.occupied[c] = pl
        self.reserved.update(pl.reserved())
        if parent is not None:
            parent.connected.add(port)
            pl.connected.add(0)  # every module attaches by its port 0
        self.placed.append(pl)

    def port_towards(self, pl: Placement, direction) -> int | None:
        d = _key(direction)
        for i, _, pd in pl.ports():
            if pd == d and i not in pl.connected:
                return i
        return None

    def chain(self, kinds, starts: list[tuple[Placement, Vector]], ups: list[Vector]) -> None:
        """The same chain of modules on every start (symmetric copies): a link is placed on all
        copies or on none, and the chain ends there."""
        heads = list(starts)
        for kind in kinds:
            for attempt in range(2):  # upright, then rolled a quarter turn (berths above / below)
                cands = []
                for (parent, d), up in zip(heads, ups):
                    port = self.port_towards(parent, d)
                    roll = up if attempt == 0 else Vector(d).cross(up)
                    cand = None if port is None else self.candidate(kind, parent, port, roll)
                    cands.append((cand, parent, port))
                trial = _Layout(self.designs)
                trial.occupied, trial.reserved = dict(self.occupied), set(self.reserved)
                ok = True
                for cand, _, _ in cands:
                    if cand is None or not trial.fits(cand):
                        ok = False
                        break
                    trial.add(cand)
                if ok:
                    break
            if not ok:
                return
            heads = []
            for (cand, parent, port), (_, d) in zip(cands, starts):
                self.add(cand, parent, port)
                heads.append((cand, d))


def _layout(p) -> list[Placement]:
    rng = random.Random(f"{p['seed']}:{p['role']}:station")
    massive = p["build"] == "massive"
    role = (ROLES_MASSIVE if massive else ROLES)[p["role"]]
    # the slim kinds draw from the main stream exactly as before the massive kinds existed
    designs = {kind: rng.randrange(modules.DESIGNS[kind][1]) for kind in KINDS if kind not in modules.MASSIVE}
    extra = random.Random(f"{p['seed']}:{p['role']}:massive")
    designs.update({kind: extra.randrange(modules.DESIGNS[kind][1]) for kind in modules.MASSIVE})
    lay = _Layout(designs)
    up = Vector((0, 0, 1))
    node = "core" if massive else "hub"  # the spine's nodes: 6 ports, axis-aligned with the first one

    def node_at(port_cell, direction) -> Placement:
        """A node whose port facing -direction meets the port at ``port_cell``."""
        c = contract(node, designs[node])
        own = next(cell for cell, d in c.ports if Vector(d) == -direction)
        return Placement(node, designs[node], Matrix.Identity(3),
                         Vector(port_cell) + direction - Vector(own), c)

    flat = p["spine"] == "horizontal" or (p["spine"] == "auto" and massive)
    axis = Vector((1, 0, 0)) if flat else up  # the spine: side by side (top-down view) or stacked
    first = Placement(node, designs[node], Matrix.Identity(3), Vector((0, 0, 0)), contract(node, designs[node]))
    lay.add(first)
    hubs = [first]
    for _ in range(HUBS[p["size"]] - 1):
        below = hubs[-1]
        port = lay.port_towards(below, axis)
        core = lay.candidate(rng.choice(role["core"]), below, port, up if flat else Vector((1, 0, 0)))
        hub = node_at(core.ports()[1][1], axis)
        if not (lay.fits(core) and lay.fits(hub)):
            break
        lay.add(core, below, port)
        core.connected.add(1)
        lay.add(hub)
        hub.connected.add(lay.port_towards(hub, -axis))
        hubs.append(hub)
    if flat:
        _flat_arms(p, rng, role, lay, hubs, axis, up)
        return lay.placed
    # arms: symmetric chains on every hub; the first hub always gets a dock
    turn = Matrix.Rotation(math.pi / 2, 3, "Z")
    base = Vector((1, 0, 0)) if rng.random() < 0.5 else Vector((0, 1, 0))
    if p["symmetry"] == "four":
        groups = [[base, turn @ base, -base, -(turn @ base)]]
    else:
        groups = [[base, -base], [turn @ base, -(turn @ base)]]
    for i, hub in enumerate(hubs):
        for g, dirs in enumerate(groups):
            recipe = rng.choice(role["docks"] if i == 0 and g == 0 else role["arms"])
            lay.chain(recipe, [(hub, d) for d in dirs], [up] * len(dirs))
    # spine ends
    for hub, d, ends in ((hubs[-1], up, role["top"]), (hubs[0], -up, role["bottom"])):
        lay.chain([rng.choice(ends)], [(hub, d)], [Vector((1, 0, 0))])
    return lay.placed


def _flat_arms(p, rng, role, lay, hubs, axis: Vector, up: Vector) -> None:
    """Arms for a horizontal spine, all in the plane (berths flat, seen from above): a
    symmetric pair across the spine on every node, every other one with docks; at the two ends of the
    spine another pair of arms (``four``) or end modules (``two``); an antenna or command module
    on top of the middle node."""
    side = axis.cross(up)
    for i, hub in enumerate(hubs):
        recipe = rng.choice(role["docks"] if i % 2 == 0 else role["arms"])  # every other node docks
        lay.chain(recipe, [(hub, side), (hub, -side)], [up, up])
    ends = [(hubs[0], -axis), (hubs[-1], axis)]
    if p["symmetry"] == "four":
        lay.chain(rng.choice(role["arms"]), ends, [up, up])
    else:
        for (hub, d), pool in zip(ends, (role["bottom"], role["top"])):
            lay.chain([rng.choice(pool)], [(hub, d)], [up])
    lay.chain([rng.choice(role["top"])], [(hubs[len(hubs) // 2], up)], [axis])


# ---------------------------------------------------------------- objects

def _materials(p) -> dict:
    style = p["style"]
    mats = create_materials({"style": {"palette": style["palette"], "wear": style["wear"]},
                             "engines": {"glow_color": style["glow_color"]}})
    mats["solar"] = _principled("Solar", (0.03, 0.06, 0.16), 0.7, 0.25)
    # decals: the station's code, the company emblem (by paint scheme), hazard stripes
    hull = decals.paint_of(mats["hull"])[0]
    accent = decals.paint_of(mats["accent"])[0]
    text = f"{ROLE_CODE[p['role']]}-{p['seed'] % 1000:03d}"
    emblem = decals.EMBLEM_OF.get(style["palette"], "ring")
    stripes = [[(x + y) // 4 % 2 == 0 for x in range(16)] for y in range(16)]
    for key, img in (("decal_text", decals.image(f"ShipGen_Decal_{text}", decals._text_mask(text), hull,
                                                   decals.contrast(hull))),
                     ("decal_emblem", decals.image(f"ShipGen_Emblem_{emblem}", decals._emblem_mask(emblem), hull,
                                                     accent)),
                     ("decal_stripes", decals.image("ShipGen_Stripes", stripes, (0.02, 0.02, 0.02), (0.8, 0.55, 0.02)))):
        mats[key] = decals.material(key.title().replace("_", ""), img, mats["accent"] if key == "decal_stripes"
                                    else mats["hull"])
    return mats


def _module_object(pl: Placement, name: str, coll, parent, mats, matrix: Matrix):
    bm = bmesh.new()
    m = modules.build(bm, pl.kind, pl.design)
    meshutil.orient_outward(bm)
    module_stats = _module_stats(m, bm)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for key in ("hull", "accent", "glow", "cargo", "solar", "decal_text", "decal_emblem", "decal_stripes"):
        mesh.materials.append(mats[key])
    for poly in mesh.polygons:
        poly.use_smooth = False
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    obj.parent = parent
    obj.matrix_basis = matrix
    obj["shipgen_role"] = "station"
    obj["station_module"] = {
        "kind": pl.kind, "design": pl.design, "grid_m": GRID,
        "cells": [list(c) for c in m.cells], "reserved": [list(c) for c in m.reserved],
        "ports": [{"cell": list(c), "dir": list(d)} for c, d in m.ports],
        "stats": module_stats,
    }
    colliders = []
    for j, pts in enumerate(collision.merge(m.pieces, COLLIDER_MERGE)):
        col = collision.convex_object(pts, f"{name}_col_{j}{collision.SUFFIX}", coll, obj)
        if col is not None:
            colliders.append(col)
    empties = []
    for k, (cell, d) in enumerate(m.ports):
        pos = (Vector(cell) + 0.5 * Vector(d)) * GRID
        e = _empty(f"{name}_Port_{k}", coll, obj, pos, Vector(d), Vector((0, 0, 1)) if abs(d[2]) == 0 else Vector((1, 0, 0)),
                   modules.PORT_RADIUS)
        e["station_port"] = {"index": k, "connected": k in pl.connected, "radius_m": modules.PORT_RADIUS}
        empties.append(e)
    for k, (kind, pos, direction, size, extra) in enumerate(m.fx):
        if "berth" in extra:  # the berth's node name, so the game can pair them
            extra = {"berth": f"{name}_Berth_{extra['berth']}"}
        empties.append(fx.anchor(f"{name}_FX_{kind}_{k}", coll, obj, pos, direction, kind, size, **extra))
    for k, br in enumerate(m.berths):
        e = _empty(f"{name}_Berth_{k}", coll, obj, br.pos, br.nose, br.up, 0.25 * br.max_length)
        e.empty_display_type = "ARROWS"
        e["station_berth"] = {"index": k, "size": br.size, "max_length_m": br.max_length}
        empties.append(e)
    return obj, colliders, empties


def _empty(name, coll, parent, pos: Vector, forward: Vector, up: Vector, size: float):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "SINGLE_ARROW"
    e.empty_display_size = size
    side = forward.cross(up)
    e.matrix_basis = Matrix.Translation(pos) @ Matrix((side, forward, up)).transposed().to_4x4()
    coll.objects.link(e)
    e.parent = parent
    return e


def _module_stats(m: modules.Module, bm) -> dict:
    by_mat: dict[int, float] = {}
    for shell in meshutil.shells(bm):
        mats = [f.material_index for f in shell]
        key = max(sorted(set(mats)), key=mats.count)
        by_mat[key] = by_mat.get(key, 0.0) + abs(meshutil.signed_volume(shell))
    vol = meshutil.volume(bm)
    out = {"volume_m3": round(vol, 1), "mass_t": round(vol * DENSITY, 1)}
    cargo = by_mat.get(modules.CARGO, 0.0) * USABLE
    if m.kind in ("storage", "hall"):
        out["general_m3"] = round(cargo, 1)
    elif m.kind == "silo":
        out["ore_m3"] = round(cargo, 1)
    elif m.kind == "tank":
        out["fluid_m3"] = round(cargo, 1)
    elif m.kind in ("habitat", "command", "quarters", "core"):
        out["crew"] = int(by_mat.get(modules.HULL, 0.0) // M3_PER_CREW)
    elif m.kind in ("refinery", "smelter"):
        out["refine_m3_h"] = round(vol * REFINE_PER_M3, 1)
    elif m.kind == "solar":
        area = sum(f.calc_area() for f in bm.faces if f.material_index == modules.SOLAR)
        out["power_kw"] = round(0.5 * area * SOLAR_KW_PER_M2, 1)
    elif m.kind == "radiator":
        area = sum(f.calc_area() for f in bm.faces if f.material_index == modules.HULL)
        out["cooling_kw"] = round(0.5 * area * RADIATOR_KW_PER_M2, 1)
    if m.berths:
        out["berths"] = [b.size for b in m.berths]
    return out


def _new_collection(root_name: str):
    _clear(COLLECTION)
    coll = bpy.data.collections.new(COLLECTION)
    bpy.context.scene.collection.children.link(coll)
    root = bpy.data.objects.new(root_name, None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = GRID
    coll.objects.link(root)
    return coll, root


def generate(raw_params: dict) -> Station:
    """Lay out and build a station; replaces the previous station (or kit)."""
    result = params_mod.validate(raw_params)
    p = result.params
    placements = _layout(p)
    coll, root = _new_collection("Station")
    mats = _materials(p)
    counters: dict[str, int] = {}
    parts, colliders, empties = [], [], []
    for pl in placements:
        n = counters.get(pl.kind, 0)
        counters[pl.kind] = n + 1
        pl.name = f"{NAME[pl.kind]}_{n}"
        obj, cols, emps = _module_object(pl, pl.name, coll, root, mats, pl.matrix())
        parts.append(obj)
        colliders += cols
        empties += emps
    station = Station(root, parts, placements, p, list(result.warnings), colliders, empties)
    station.stats = _stats(parts, empties)
    root["shipgen_station"] = {"seed": p["seed"], "role": p["role"], "size": p["size"], "build": p["build"],
                               "spine": p["spine"],
                               "grid_m": GRID,
                               "stats": station.stats}
    return station


def build_kit(raw_params: dict | None = None) -> Station:
    """Every design of every module kind, unassembled, in a row (the game's module library)."""
    result = params_mod.validate(raw_params or {})
    p = result.params
    coll, root = _new_collection("StationKit")
    mats = _materials(p)
    parts, colliders, empties, placements = [], [], [], []
    y = 0.0
    for kind in KINDS:  # one row per kind, its designs side by side
        designs = [contract(kind, d) for d in range(modules.DESIGNS[kind][1])]
        y_lo = min(cell[1] for c in designs for cell in c.cells + c.reserved)
        y_hi = max(cell[1] for c in designs for cell in c.cells + c.reserved)
        y += (0.5 - y_lo) * GRID
        x = 0.0
        for design, c in enumerate(designs):
            cells = c.cells + c.reserved
            x += (0.5 - min(cell[0] for cell in cells)) * GRID
            pl = Placement(kind, design, Matrix.Identity(3), Vector(), c, f"{NAME[kind]}_v{design}")
            obj, cols, emps = _module_object(pl, pl.name, coll, root, mats, Matrix.Translation((x, y, 0)))
            x += (max(cell[0] for cell in cells) + 1.0) * GRID
            parts.append(obj)
            colliders += cols
            empties += emps
            placements.append(pl)
        y += (y_hi + 1.0) * GRID
    kit = Station(root, parts, placements, p, list(result.warnings), colliders, empties)
    kit.stats = {"modules": {pl.name: obj["station_module"].to_dict() for pl, obj in zip(placements, parts)}}
    root["shipgen_station_kit"] = {"grid_m": GRID, "port_radius_m": modules.PORT_RADIUS,
                                   "kinds": list(KINDS)}
    return kit


def _stats(parts, empties) -> dict:
    total: dict = {"modules": len(parts), "volume_m3": 0.0, "mass_t": 0.0, "general_m3": 0.0, "ore_m3": 0.0,
                   "fluid_m3": 0.0, "crew": 0, "refine_m3_h": 0.0, "power_kw": 0.0, "cooling_kw": 0.0}
    kinds: dict[str, int] = {}
    berths = {"S": 0, "M": 0, "L": 0}
    for obj in parts:
        info = obj["station_module"]
        kinds[info["kind"]] = kinds.get(info["kind"], 0) + 1
        for key, value in info["stats"].to_dict().items():
            if key == "berths":
                for size in value:
                    berths[size] += 1
            else:
                total[key] = total.get(key, 0) + value
    for key, value in total.items():
        if isinstance(value, float):
            total[key] = round(value, 1)
    total["kinds"] = kinds
    total["berths"] = berths
    total["free_ports"] = sum(1 for e in empties if "station_port" in e and not e["station_port"]["connected"])
    return total
