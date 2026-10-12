"""Generator core: ``generate(params) -> Ship``.

Independent of any UI. Used by the add-on panel, ``cli.py`` and tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import bpy
from mathutils import Vector

from .. import params as params_mod
from .. import stats as stats_mod
from . import cargo, engines, hull, materials, mining, wings

COLLECTION_NAME = "ShipGen"


@dataclass
class Ship:
    root: bpy.types.Object
    parts: list[bpy.types.Object]
    params: dict  # what was built: the model params after the seed's spread
    warnings: list[str] = field(default_factory=list)
    gameplay: dict = field(default_factory=dict)  # see shipgen.stats

    @property
    def objects(self) -> list[bpy.types.Object]:
        return [self.root, *self.parts]

    def tri_count(self) -> int:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        total = 0
        for obj in self.parts:
            if obj.type != "MESH":
                continue
            total += _tri_count(obj.evaluated_get(depsgraph).to_mesh())
            obj.evaluated_get(depsgraph).to_mesh_clear()
        return total

    def bounds(self) -> tuple[Vector, Vector]:
        """World-space axis-aligned bounding box (min, max)."""
        bpy.context.view_layer.update()
        lo = Vector((float("inf"),) * 3)
        hi = Vector((float("-inf"),) * 3)
        for obj in self.parts:
            for corner in obj.bound_box:
                p = obj.matrix_world @ Vector(corner)
                lo = Vector(map(min, lo, p))
                hi = Vector(map(max, hi, p))
        return lo, hi

    def stats(self) -> dict:
        from .. import metrics

        lo, hi = self.bounds()
        return {
            "gameplay": self.gameplay,
            "top_view": metrics.top_view(self),
            "tris": self.tri_count(),
            "max_tris": self.params["max_tris"],
            "bbox_min": list(lo),
            "bbox_max": list(hi),
            "dimensions": list(hi - lo),
            "parts": [o.name for o in self.parts],
        }


def _tri_count(mesh) -> int:
    return sum(len(poly.vertices) - 2 for poly in mesh.polygons)


def clear(collection_name: str = COLLECTION_NAME) -> None:
    """Remove a previously generated ship (objects, meshes, materials)."""
    coll = bpy.data.collections.get(collection_name)
    if coll is None:
        return
    for obj in list(coll.all_objects):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)
    bpy.data.collections.remove(coll)
    materials.remove_materials()
    bpy.context.view_layer.update()  # drop stale entries of the removed objects


def generate(raw_params: dict, collection_name: str = COLLECTION_NAME) -> Ship:
    """Build a ship from (possibly unvalidated) parameters into its own collection.

    Any previous ship in that collection is replaced.
    """
    result = params_mod.validate(raw_params)
    if result.params["builder"] == "kit":
        from .. import kit

        ship = kit.build(result.params)
        ship.warnings[:0] = result.warnings
        return ship
    p = params_mod.individualize(result.params)

    clear(collection_name)
    coll = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(coll)

    root = bpy.data.objects.new("Ship", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = p["hull"]["length"] * 0.1
    coll.objects.link(root)

    mats = materials.create_materials(p)
    hull_obj, shape = hull.build_hull(p, coll, parent=root)
    hull_obj.data.materials.append(mats["hull"])
    parts = [hull_obj]

    wings_obj = wings.build_wings(p, shape, coll, parent=root)
    if wings_obj is not None:
        wings_obj.data.materials.append(mats["hull"])
        parts.append(wings_obj)

    warnings = list(result.warnings)

    mining_obj = mining.build_mining(p, shape, coll, parent=root)
    if mining_obj is not None:
        mining_obj.data.materials.append(mats["accent"])
        mining_obj.data.materials.append(mats["glow"])
        parts.append(mining_obj)

    # Budget order: hull, wings, mining are fixed; then engines, then cargo modules.
    tris_left = p["max_tris"] - sum(_tri_count(o.data) for o in parts)
    engine_count = min(p["engines"]["count"], max(tris_left // engines.TRIS_PER_ENGINE, 0))
    if engine_count < p["engines"]["count"]:
        warnings.append(f"engines.count reduced to {engine_count} to stay within max_tris")
    engines_obj = engines.build_engines(p, shape, coll, parent=root, count=engine_count)
    if engines_obj is not None:
        engines_obj.data.materials.append(mats["accent"])
        engines_obj.data.materials.append(mats["glow"])
        parts.append(engines_obj)
        tris_left -= _tri_count(engines_obj.data)

    cargo_obj, placed = cargo.build_cargo(p, shape, coll, parent=root)
    if cargo_obj is not None and _tri_count(cargo_obj.data) > tris_left:
        fit = tris_left // (_tri_count(cargo_obj.data) // placed)
        fit -= fit % 2 if fit > 1 else 0  # keep pairs symmetric
        _remove(cargo_obj)
        cargo_obj, placed = cargo.build_cargo(dict(p, cargo=dict(p["cargo"], modules=fit)), shape, coll, root)
    if placed < p["cargo"]["modules"] and p["cargo"]["type"] != "none":
        warnings.append(f"cargo.modules reduced to {placed} (no room on the hull or over max_tris)")
    if cargo_obj is not None:
        for key in ("cargo", "accent", "glow"):
            cargo_obj.data.materials.append(mats[key])
        parts.append(cargo_obj)

    # TODO: greebles

    for obj in parts:
        if "shipgen_role" not in obj:
            obj["shipgen_role"] = obj.name.removeprefix("Ship_").lower()
    ship = Ship(root=root, parts=parts, params=p, warnings=warnings)
    ship.gameplay = stats_mod.compute(ship, shape)
    # exported as glTF extras on the root node (Godot imports them as node metadata)
    root["shipgen"] = {"seed": p["seed"], "class": p["class"], "stats": ship.gameplay}
    return ship


def _remove(obj) -> None:
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.meshes.remove(mesh)
