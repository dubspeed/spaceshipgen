"""Materials. Kept to plain Principled BSDF values (no linked textures) so they
survive the glTF export unchanged."""

from __future__ import annotations

import bpy

# palette name -> (hull, accent) as linear-ish sRGB tuples
PALETTE_COLORS = {
    "military_grey": ((0.32, 0.34, 0.36), (0.55, 0.45, 0.12)),
    "white_red": ((0.85, 0.85, 0.83), (0.7, 0.06, 0.05)),
    "desert": ((0.62, 0.5, 0.34), (0.3, 0.22, 0.14)),
    "navy": ((0.08, 0.12, 0.25), (0.75, 0.75, 0.78)),
    "black_gold": ((0.04, 0.04, 0.045), (0.8, 0.6, 0.15)),
    "rust": ((0.35, 0.16, 0.08), (0.2, 0.2, 0.2)),
}

MATERIAL_PREFIX = "ShipGen_"


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _principled(name: str, color, metallic: float, roughness: float) -> bpy.types.Material:
    mat = bpy.data.materials.new(MATERIAL_PREFIX + name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    mat.diffuse_color = (*color, 1.0)
    mat.metallic = metallic
    mat.roughness = roughness
    return mat


def create_materials(params: dict) -> dict[str, bpy.types.Material]:
    hull_color, accent_color = PALETTE_COLORS[params["style"]["palette"]]
    wear = params["style"]["wear"]
    # Wear: duller, rougher, slightly darker paint.
    dull = 1.0 - 0.35 * wear
    hull_color = tuple(c * dull for c in hull_color)
    return {
        "hull": _principled("Hull", hull_color, 0.5 - 0.3 * wear, 0.3 + 0.5 * wear),
        "accent": _principled("Accent", accent_color, 0.3, 0.4 + 0.3 * wear),
    }


def remove_materials() -> None:
    for mat in list(bpy.data.materials):
        if mat.name.startswith(MATERIAL_PREFIX) and mat.users == 0:
            bpy.data.materials.remove(mat)
