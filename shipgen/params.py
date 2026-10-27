"""Parameter schema and validation for the ship generator.

Pure Python (no ``bpy``), so it can be used by the add-on, the CLI, the AI
prompt module and plain unit tests alike.

Every leaf value has a type, a default and (where it makes sense) a range or a
set of allowed choices. ``validate()`` never raises on bad *values*: it clamps
or replaces them and reports what it changed, so arbitrary input (e.g. LLM
output) always yields a usable parameter set.
"""

from __future__ import annotations

import copy
import json
import random
import re
from dataclasses import dataclass, field
from typing import Any

from .version import META_KEYS

SHIP_CLASSES = ("fighter", "interceptor", "freighter", "miner", "corvette", "shuttle")
WING_TYPES = ("none", "delta", "swept", "straight", "forward_swept")
MINING_TYPES = ("none", "drill", "laser", "claw", "scoop")
CARGO_TYPES = ("none", "containers", "hoppers", "tanks", "habitat")
BUILDERS = ("kit", "classic")
# Kit building blocks (must match shipgen/kit; test_params checks it). "auto" = the seed picks.
KIT_PLANS = ("auto", "mono", "twin", "fork")
KIT_TAILS = ("auto", "flat", "taper", "flare", "outboard")
KIT_MIDS = ("auto", "straight", "waist", "bulge", "stepped", "sponson")
KIT_NOSES = ("auto", "wedge", "blunt", "hammer", "cockpit")
KIT_DESIGNS = 10  # designs per part library (engines, rigs, modules)
PALETTES = ("industrial_yellow", "military_grey", "white_red", "desert", "navy", "black_gold", "rust")

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


@dataclass(frozen=True)
class Field:
    type: type
    default: Any
    min: float | None = None
    max: float | None = None
    choices: tuple | None = None
    color: bool = False
    description: str = ""


SCHEMA: dict[str, Any] = {
    "seed": Field(int, 42, 0, 2**31 - 1, description="Random seed, makes every ship reproducible"),
    "class": Field(str, "fighter", choices=SHIP_CLASSES, description="Overall ship archetype"),
    "hull": {
        "length": Field(float, 12.0, 2.0, 200.0, description="Hull length in metres"),
        "width_ratio": Field(float, 0.35, 0.1, 1.0, description="Max width relative to length"),
        "height_ratio": Field(float, 0.5, 0.2, 1.5, description="Max height relative to max width"),
        "segments": Field(int, 6, 3, 16, description="Hull sections; stepped classes get one module per section"),
        "taper": Field(float, 0.2, 0.0, 1.0, description="How much the tail narrows"),
        "nose_sharpness": Field(float, 0.7, 0.0, 1.0, description="0 = blunt nose, 1 = needle nose"),
        "squareness": Field(float, 0.3, 0.0, 1.0, description="0 = heavily chamfered cross-section, 1 = boxy"),
        "variation": Field(float, 0.3, 0.0, 1.0, description="Random bulges (fighters) or module steps (freighters)"),
    },
    "wings": {
        "type": Field(str, "delta", choices=WING_TYPES),
        "count": Field(int, 2, 0, 6),
        "span": Field(float, 9.0, 0.0, 300.0),
        "sweep_deg": Field(float, 35.0, -45.0, 75.0),
    },
    "engines": {
        "count": Field(int, 2, 0, 8),
        "size": Field(float, 1.2, 0.1, 30.0),
        "glow_color": Field(str, "#44aaff", color=True),
    },
    "mining": {
        "type": Field(str, "none", choices=MINING_TYPES, description="Mining rig at the nose"),
        "count": Field(int, 2, 1, 4, description="Laser emitters or claw arms"),
        "size": Field(float, 0.5, 0.0, 1.0, description="Rig size relative to the hull"),
    },
    "cargo": {
        "type": Field(str, "none", choices=CARGO_TYPES,
                      description="containers = general freight, hoppers = ore, tanks = gas/liquid, habitat = passengers"),
        "modules": Field(int, 0, 0, 24, description="Number of cargo modules mounted on the hull"),
        "size": Field(float, 0.5, 0.0, 1.0, description="Module size relative to the hull"),
    },
    "greeble_density": Field(float, 0.4, 0.0, 1.0),
    "symmetry": Field(bool, True),
    "style": {
        "palette": Field(str, "military_grey", choices=PALETTES),
        "wear": Field(float, 0.3, 0.0, 1.0),
        "decals": Field(bool, True, description="Registration and company emblem on the flanks (kit builder)"),
    },
    "builder": Field(str, "kit", choices=BUILDERS,
                     description="kit = hull from sections + parts on sockets; classic = old generator (wings)"),
    "kit": {
        "plan": Field(str, "auto", choices=KIT_PLANS, description="Body plan: mono, twin (catamaran), fork"),
        "tail": Field(str, "auto", choices=KIT_TAILS),
        "mid": Field(str, "auto", choices=KIT_MIDS),
        "nose": Field(str, "auto", choices=KIT_NOSES),
        "engine_design": Field(int, -1, -1, KIT_DESIGNS - 1, description="-1 = seed picks"),
        "rig_design": Field(int, -1, -1, KIT_DESIGNS - 1, description="-1 = seed picks within mining.type"),
        "module_design": Field(int, -1, -1, KIT_DESIGNS - 1, description="-1 = seed picks within cargo.type"),
        "detail": Field(float, 1.0, 0.0, 1.0,
                        description="Hull surface detail (belt grooves, side panels, dorsal trench by class); 0 = plain"),
    },
    "spread": Field(float, 0.025, 0.0, 0.25,
                    description="Per-seed manufacturing spread (±) of proportions and part sizes; 0 = exact model"),
    "max_tris": Field(int, 15000, 500, 500000, description="Triangle budget for the whole ship"),
}


@dataclass
class ValidationResult:
    params: dict
    warnings: list[str] = field(default_factory=list)


def defaults(schema: dict | None = None) -> dict:
    """Return a fresh dict with all default values."""
    schema = SCHEMA if schema is None else schema
    out = {}
    for key, spec in schema.items():
        out[key] = defaults(spec) if isinstance(spec, dict) else copy.deepcopy(spec.default)
    return out


def _coerce(path: str, spec: Field, value: Any, warnings: list[str]) -> Any:
    if spec.type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.lower() in ("true", "false", "yes", "no", "1", "0"):
            return value.lower() in ("true", "yes", "1")
        warnings.append(f"{path}: expected bool, got {value!r}; using default {spec.default!r}")
        return spec.default

    if spec.type in (int, float):
        if isinstance(value, bool) or value is None:
            num = None
        else:
            try:
                num = float(value)
            except (TypeError, ValueError):
                num = None
        if num is None or num != num or num in (float("inf"), float("-inf")):
            warnings.append(f"{path}: expected number, got {value!r}; using default {spec.default!r}")
            return spec.default
        if spec.min is not None and num < spec.min:
            warnings.append(f"{path}: {num} below minimum {spec.min}; clamped")
            num = spec.min
        if spec.max is not None and num > spec.max:
            warnings.append(f"{path}: {num} above maximum {spec.max}; clamped")
            num = spec.max
        if spec.type is int:
            rounded = int(round(num))
            if rounded != num:
                warnings.append(f"{path}: {num} rounded to integer {rounded}")
            return rounded
        return float(num)

    # strings
    if not isinstance(value, str):
        warnings.append(f"{path}: expected string, got {value!r}; using default {spec.default!r}")
        return spec.default
    if spec.choices is not None:
        norm = value.strip().lower().replace("-", "_").replace(" ", "_")
        if norm not in spec.choices:
            warnings.append(
                f"{path}: {value!r} not one of {list(spec.choices)}; using default {spec.default!r}"
            )
            return spec.default
        return norm
    if spec.color:
        value = value.strip()
        if not _HEX_COLOR.match(value):
            warnings.append(f"{path}: {value!r} is not a hex color; using default {spec.default!r}")
            return spec.default
        if len(value) == 4:  # #abc -> #aabbcc
            value = "#" + "".join(c * 2 for c in value[1:])
        return value.lower()
    return value


def _validate(data: Any, schema: dict, prefix: str, warnings: list[str]) -> dict:
    if not isinstance(data, dict):
        if data is not None:
            warnings.append(f"{prefix or '<root>'}: expected object, got {type(data).__name__}; using defaults")
        data = {}
    out = {}
    for key, spec in schema.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(spec, dict):
            out[key] = _validate(data.get(key), spec, path, warnings)
        elif key in data:
            out[key] = _coerce(path, spec, data[key], warnings)
        else:
            out[key] = copy.deepcopy(spec.default)
    for key in data:
        if key not in schema and not (prefix == "" and key in META_KEYS):
            path = f"{prefix}.{key}" if prefix else key
            warnings.append(f"{path}: unknown parameter ignored")
    return out


def validate(data: Any, schema: dict | None = None) -> ValidationResult:
    """Validate (and repair) a parameter dict against ``schema`` (default: the ship schema).
    Missing values get defaults."""
    warnings: list[str] = []
    params = _validate(data, SCHEMA if schema is None else schema, "", warnings)
    return ValidationResult(params, warnings)


# (path, kind): "scale" multiplies by 1 ± spread, "shift" adds ± spread * amount.
# Proportions and part sizes change the stats slightly; the shape knobs mostly the look.
_SPREAD = (
    (("hull", "length"), "scale", 1.0),
    (("hull", "width_ratio"), "scale", 1.0),
    (("hull", "height_ratio"), "scale", 1.0),
    (("hull", "taper"), "shift", 1.5),
    (("hull", "nose_sharpness"), "shift", 1.5),
    (("hull", "squareness"), "shift", 2.0),
    (("wings", "span"), "scale", 1.0),
    (("wings", "sweep_deg"), "shift", 60.0),
    (("engines", "size"), "scale", 1.0),
    (("mining", "size"), "shift", 1.0),
    (("cargo", "size"), "shift", 1.0),
)


def individualize(params: dict) -> dict:
    """The concrete ship of a model: apply the seed's manufacturing spread.

    Deterministic per seed, independent of the shape random streams. Expects
    validated params; returns validated params (values stay within the schema).
    """
    spread = params["spread"]
    if spread <= 0:
        return copy.deepcopy(params)
    rng = random.Random(f"{params['seed']}:individual")
    out = copy.deepcopy(params)
    for path, kind, amount in _SPREAD:
        u = rng.uniform(-1.0, 1.0)  # always drawn, so the sequence doesn't depend on values
        value = get_path(out, path)
        set_path(out, path, value * (1.0 + u * spread) if kind == "scale" else value + u * spread * amount)
    return validate(out).params


def load(path: str) -> ValidationResult:
    with open(path, encoding="utf-8") as f:
        return validate(json.load(f))


def iter_fields(schema: dict | None = None, prefix: tuple = ()):
    """Yield ``(path_tuple, Field)`` for every leaf in the schema."""
    schema = SCHEMA if schema is None else schema
    for key, spec in schema.items():
        if isinstance(spec, dict):
            yield from iter_fields(spec, prefix + (key,))
        else:
            yield prefix + (key,), spec


def get_path(params: dict, path: tuple) -> Any:
    for key in path:
        params = params[key]
    return params


def set_path(params: dict, path: tuple, value: Any) -> None:
    for key in path[:-1]:
        params = params.setdefault(key, {})
    params[path[-1]] = value


def json_schema() -> dict:
    """Export the schema as JSON Schema (used to instruct the AI prompt)."""

    def convert(schema: dict) -> dict:
        props = {}
        for key, spec in schema.items():
            if isinstance(spec, dict):
                props[key] = convert(spec)
                continue
            p: dict[str, Any] = {
                "type": {int: "integer", float: "number", str: "string", bool: "boolean"}[spec.type],
                "default": spec.default,
            }
            if spec.min is not None:
                p["minimum"] = spec.min
            if spec.max is not None:
                p["maximum"] = spec.max
            if spec.choices:
                p["enum"] = list(spec.choices)
            if spec.color:
                p["pattern"] = _HEX_COLOR.pattern
            if spec.description:
                p["description"] = spec.description
            props[key] = p
        return {"type": "object", "properties": props, "additionalProperties": False}

    return convert(SCHEMA)
