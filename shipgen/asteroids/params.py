"""Asteroid parameter schema (same Field / validate machinery as the ships)."""

from __future__ import annotations

from typing import Any

from .. import params as ship_params
from ..params import Field

COMPOSITIONS = ("ore", "metal", "ice")
SHAPES = ("round", "elongated", "binary")

SCHEMA: dict[str, Any] = {
    "seed": Field(int, 1, 0, 2**31 - 1, description="Random seed, makes every asteroid reproducible"),
    "composition": Field(str, "ore", choices=COMPOSITIONS, description="What it is made of (and yields)"),
    "shape": Field(str, "round", choices=SHAPES, description="round, elongated or binary (two lobes)"),
    "size_m": Field(float, 24.0, 3.0, 400.0, description="Largest extent in metres"),
    "facets": Field(int, 22, 8, 80, description="Points of the rock hull: few = big flat facets"),
    "chunks": Field(int, 7, 2, 16, description="Pieces per break of the whole asteroid"),
    "sub_chunks": Field(int, 4, 2, 8, description="Pieces per break of a chunk"),
    "min_chunk_m": Field(float, 4.0, 0.5, 100.0, description="Chunks smaller than about twice this don't break further"),
    "max_levels": Field(int, 4, 1, 6, description="Break levels prepared in advance"),
    "richness": Field(float, 0.6, 0.0, 1.0, description="Share of chunks that carry the resource (rest is plain rock)"),
    "gap": Field(float, 0.03, 0.0, 0.15, description="Crack width between chunks: gap x size_m / 2"),
    "max_tris": Field(int, 30000, 500, 500000, description="Triangle budget for all levels together"),
}


def defaults() -> dict:
    return ship_params.defaults(SCHEMA)


def validate(data: Any) -> ship_params.ValidationResult:
    return ship_params.validate(data, SCHEMA)


def load(path: str) -> ship_params.ValidationResult:
    import json

    with open(path, encoding="utf-8") as f:
        return validate(json.load(f))


set_path = ship_params.set_path
get_path = ship_params.get_path
iter_fields = ship_params.iter_fields
