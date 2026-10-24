"""Wreck parameter schema (same Field / validate machinery as the ships).

The ship itself comes from the ship params (a shop model): ``wrecks.generate(params, ship_params)``.
"""

from __future__ import annotations

from typing import Any

from .. import params as ship_params
from ..params import Field

SCHEMA: dict[str, Any] = {
    "seed": Field(int, 1, 0, 2**31 - 1, description="Random seed of the damage (where it broke, what was lost)"),
    "ship_seed": Field(int, -1, -1, 2**31 - 1, description="Seed of the ship before it was wrecked (-1 = same as seed)"),
    "damage": Field(float, 0.5, 0.0, 1.0, description="How much of the ship's parts is damaged, torn off or destroyed"),
    "breaks": Field(int, 1, 0, 3, description="Places where the hull broke apart"),
    "spread": Field(float, 0.5, 0.0, 1.0, description="How far the pieces drifted apart (and how much they turned)"),
    "holes": Field(int, 4, 0, 20, description="Holes torn into the hull plating"),
    "burn": Field(float, 0.5, 0.0, 1.0, description="Scorch marks on hull and parts"),
    "debris": Field(int, 8, 0, 40, description="Extra hull fragments floating around the breaks"),
}


def defaults() -> dict:
    return ship_params.defaults(SCHEMA)


def validate(data: Any) -> ship_params.ValidationResult:
    return ship_params.validate(data, SCHEMA)


set_path = ship_params.set_path
get_path = ship_params.get_path
iter_fields = ship_params.iter_fields
