"""Gameplay stats derived from the generated geometry.

The visuals are the source of truth: a bigger cargo bay *is* more cargo volume,
bigger nozzles *are* more thrust. Units are physical-ish (m, m^3, t, kN, m/s^2);
the game is expected to balance them with its own multipliers.
"""

from __future__ import annotations

import math

import bmesh

# t per m^3 of mesh volume (hulls and modules are mostly hollow)
DENSITY = {"hull": 0.12, "wings": 0.25, "engines": 0.4, "mining": 0.5, "cargo": 0.08, "greebles": 0.0}
THRUST_PER_NOZZLE_M2 = 250.0  # kN per m^2 of glowing nozzle area
HULL_HP_PER_M2 = 10.0
USABLE_MODULE_VOLUME = 0.85
M3_PER_PASSENGER = 8.0
# Mining power = efficiency x rig volume^(2/3): every rig type scales the same way
# (like a working surface, so big rigs don't run away); calibrated so a medium rig
# (size 0.5, count 2 on miner_m) gives ~100.
MINING_EFFICIENCY = {"drill": 5.1, "laser": 27.6, "claw": 18.8, "scoop": 6.25}
CARGO_KIND = {"containers": "general_m3", "hoppers": "ore_m3", "tanks": "fluid_m3"}


def measure(obj) -> dict:
    """Volume, area, glowing area and extent of one part object."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    glow_slots = {i for i, m in enumerate(obj.data.materials) if m is not None and m.name.startswith("ShipGen_Glow")}
    out = {
        "volume": abs(bm.calc_volume()),
        "area": sum(f.calc_area() for f in bm.faces),
        "glow_area": sum(f.calc_area() for f in bm.faces if f.material_index in glow_slots),
        "max_y": max((v.co.y for v in bm.verts), default=0.0),
        "max_x": max((abs(v.co.x) for v in bm.verts), default=0.0),
    }
    bm.free()
    return out


def compute(ship, hull, efficiency: dict | None = None) -> dict:
    """``hull`` is the ship's HullShape (or anything with ``length``, ``profile`` and ``y(t)``);
    ``efficiency`` overrides MINING_EFFICIENCY (each part library is calibrated separately)."""
    efficiency = MINING_EFFICIENCY if efficiency is None else efficiency
    p = ship.params
    parts = {o["shipgen_role"]: o for o in ship.parts}
    m = {role: measure(obj) for role, obj in parts.items()}

    mass = sum(DENSITY.get(role, 0.2) * d["volume"] for role, d in m.items())
    thrust = m["engines"]["glow_area"] * THRUST_PER_NOZZLE_M2 if "engines" in m else 0.0
    accel = thrust / mass if mass else 0.0
    # angular acceleration of a rod (I = m L^2 / 12) with thrust acting at half length
    turn = math.degrees(0.1 * 6.0 * thrust / (mass * hull.length)) if mass else 0.0

    cargo = {"general_m3": 0.0, "ore_m3": 0.0, "fluid_m3": 0.0, "passengers": 0}
    cargo[hull.profile.hold_kind] += m["hull"]["volume"] * hull.profile.hold
    if "cargo" in m:
        usable = m["cargo"]["volume"] * USABLE_MODULE_VOLUME
        kind = p["cargo"]["type"]
        if kind == "habitat":
            cargo["passengers"] = int(usable // M3_PER_PASSENGER)
        else:
            cargo[CARGO_KIND[kind]] += usable

    mining = {"type": "none", "power": 0.0, "range_m": 0.0}
    if "mining" in m:
        d = m["mining"]
        kind = p["mining"]["type"]
        reach = max(d["max_y"] - hull.y(1.0), 0.0)
        mining = {"type": kind}
        mining.update(power=efficiency[kind] * d["volume"] ** (2 / 3), range_m=reach)
        if kind == "laser":
            mining["range_m"] = 20.0 * reach  # beam range scales with the emitter boom
        elif kind == "claw":
            mining["grab_size_m"] = 2.0 * d["max_x"]
        elif kind == "scoop":
            mining["intake_m2"] = d["glow_area"]

    def r(v):
        return round(v, 2) if isinstance(v, float) else v

    return {
        "mass_t": r(mass),
        "thrust_kn": r(thrust),
        "acceleration_ms2": r(accel),
        "turn_rate_deg_s2": r(turn),
        "hull_hp": round(m["hull"]["area"] * HULL_HP_PER_M2 * hull.profile.armor),
        "length_m": r(hull.length),
        "cargo": {k: r(v) for k, v in cargo.items()},
        "mining": {k: r(v) for k, v in mining.items()},
    }
