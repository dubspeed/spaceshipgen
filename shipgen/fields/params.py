"""Asteroid field schema (same Field / validate machinery as the ships)."""

from __future__ import annotations

from typing import Any

from .. import params as ship_params
from ..params import Field

SHAPES = ("belt", "cluster", "ring")

SCHEMA: dict[str, Any] = {
    "seed": Field(int, 1, 0, 2**31 - 1, description="Random seed: placement, rocks, zones"),
    "shape": Field(str, "belt", choices=SHAPES,
                   description="belt = long band, cluster = clumped blob, ring = annulus around the centre"),
    "size_m": Field(float, 500.0, 100.0, 20000.0,
                    description="Extent of the field (belt length, cluster/ring diameter)"),
    "width": Field(float, 0.3, 0.05, 1.0, description="Belt / ring width relative to size_m"),
    "thickness": Field(float, 0.06, 0.0, 0.5,
                       description="Vertical spread relative to size_m (flat for a top-down view)"),
    "count": Field(int, 80, 1, 2000, description="Asteroids in the field"),
    "prefabs": Field(int, 9, 1, 40, description="Unique rocks the field is built from (each has its own .glb)"),
    "min_size_m": Field(float, 6.0, 3.0, 400.0, description="Smallest rock"),
    "max_size_m": Field(float, 48.0, 3.0, 400.0, description="Largest rock"),
    "size_bias": Field(float, 2.0, 0.0, 4.0, description="Power law: 0 = sizes even, higher = mostly small rocks"),
    "ore": Field(float, 0.6, 0.0, 1.0, description="Share of ore rocks"),
    "metal": Field(float, 0.25, 0.0, 1.0, description="Share of metal rocks"),
    "ice": Field(float, 0.15, 0.0, 1.0, description="Share of ice rocks"),
    "zoned": Field(float, 0.6, 0.0, 1.0,
                   description="0 = compositions mixed everywhere, "
                               "1 = separate zones (ore at one end, ice at the other)"),
    "clumping": Field(float, 0.4, 0.0, 1.0, description="0 = spread evenly, 1 = rocks gather in clumps"),
    "gap_m": Field(float, 4.0, 0.0, 100.0, description="Free space between neighbouring rocks"),
}


def defaults() -> dict:
    return ship_params.defaults(SCHEMA)


def validate(data: Any) -> ship_params.ValidationResult:
    result = ship_params.validate(data, SCHEMA)
    p = result.params
    if p["min_size_m"] > p["max_size_m"]:
        p["min_size_m"], p["max_size_m"] = p["max_size_m"], p["min_size_m"]
        result.warnings.append("min_size_m > max_size_m: swapped")
    if p["ore"] + p["metal"] + p["ice"] <= 0:
        p["ore"] = 1.0
        result.warnings.append("no composition share > 0: ore only")
    return result


set_path = ship_params.set_path
get_path = ship_params.get_path
iter_fields = ship_params.iter_fields
