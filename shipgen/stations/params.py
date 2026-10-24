"""Station parameter schema (same Field / validate machinery as the ships)."""

from __future__ import annotations

from typing import Any

from .. import params as ship_params
from ..params import PALETTES, Field

ROLES = ("outpost", "mining", "trade")
SIZES = ("small", "medium", "large")
SYMMETRIES = ("two", "four")

SCHEMA: dict[str, Any] = {
    "seed": Field(int, 1, 0, 2**31 - 1, description="Random seed: layout choices and module designs"),
    "role": Field(str, "mining", choices=ROLES, description="What the station is for: decides the module mix"),
    "size": Field(str, "medium", choices=SIZES, description="Hubs on the central spine: 1, 2 or 3"),
    "symmetry": Field(str, "four", choices=SYMMETRIES, description="Arms per hub: two (opposite) or four"),
    "style": {
        "palette": Field(str, "white_red", choices=PALETTES, description="Paint scheme (shared with the ships)"),
        "wear": Field(float, 0.3, 0.0, 1.0, description="Dull, rough paint"),
        "glow_color": Field(str, "#ffd9a0", color=True, description="Window and light colour (hex)"),
    },
}


def defaults() -> dict:
    return ship_params.defaults(SCHEMA)


def validate(data: Any) -> ship_params.ValidationResult:
    return ship_params.validate(data, SCHEMA)


set_path = ship_params.set_path
get_path = ship_params.get_path
iter_fields = ship_params.iter_fields
