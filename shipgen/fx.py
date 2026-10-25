"""FX anchors: empties that mark where the game attaches particle effects and lights.

Blender particles don't survive glTF, and effects depend on the game state (thrust, mining,
damage), so the game owns the effects; the generators only say where they go. Each anchor is an
empty whose local +Y (Godot -Z) points where the effect is emitted, with extras
``shipgen_fx = {kind, size, ...}``. Kinds (see ``docs/export_format.md``):

- ships: ``exhaust`` (engine nozzle), ``rcs`` (attitude thruster), ``mining`` (rig work point),
  ``nav_light`` (``color``: red = port/left, green = starboard/right, white = tail);
- wrecks: ``spark`` (torn ends), ``smoke`` (holes), ``vent`` (gas from damaged parts);
- stations: ``beacon`` (blinking light), ``berth_light`` (``berth``: the berth's node name),
  ``vent`` (refinery stacks, tanks);
- asteroids: ``sublimation`` (ice venting from the surface).
"""

from __future__ import annotations

import bpy
from mathutils import Matrix, Vector

KINDS = ("exhaust", "rcs", "mining", "nav_light", "spark", "smoke", "vent", "beacon", "berth_light", "sublimation")


def matrix(pos, direction) -> Matrix:
    """Local +Y along ``direction``, +Z as close to world up as possible."""
    d = Vector(direction).normalized()
    return Matrix.Translation(Vector(pos)) @ d.to_track_quat("Y", "Z").to_matrix().to_4x4()


def anchor(name: str, coll, parent, pos, direction, kind: str, size: float, **extra):
    """An FX anchor in ``parent``'s space."""
    assert kind in KINDS, kind
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "CONE"
    e.empty_display_size = max(size, 0.05)
    e.matrix_basis = matrix(pos, direction)
    e["shipgen_fx"] = {"kind": kind, "size": round(size, 3), **extra}
    coll.objects.link(e)
    e.parent = parent
    return e


def anchors_of(objects) -> list:
    return [o for o in objects if "shipgen_fx" in o]
