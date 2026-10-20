"""Convex collision shapes for Godot.

Godot's scene importer turns every mesh node whose name ends in ``-convcolonly``
into an invisible convex collision shape. We export a small set of convex hulls
that together cover the visible ship:

- each lofted hull body is cut between consecutive stations (a segment between two
  convex cross-sections is convex), then neighbours are merged while their joint
  convex hull is barely larger than the pieces (``MERGE_TOLERANCE``);
- hull add-ons (prongs, pods, bridges, pylons) and every fitted part get one hull each.
"""

from __future__ import annotations

import bmesh
import bpy
from mathutils import Vector

from ..generator.hull import cross_section

SUFFIX = "-convcolonly"
MERGE_TOLERANCE = 0.06


def _hull_bmesh(points):
    bm = bmesh.new()
    verts = [bm.verts.new(p) for p in points]
    res = bmesh.ops.convex_hull(bm, input=verts)
    junk = list({g for g in res["geom_interior"] + res["geom_unused"] if isinstance(g, bmesh.types.BMVert)})
    if junk:
        bmesh.ops.delete(bm, geom=junk, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def hull_volume(points) -> float:
    bm = _hull_bmesh(points)
    vol = abs(bm.calc_volume())
    bm.free()
    return vol


def body_segments(layout, length, chamfer, ridge) -> list[list[Vector]]:
    """Point sets of the convex segments of one lofted body."""
    y0 = -0.5 * length
    rings = []
    stations = layout.stations[:-1] if layout.point_nose else layout.stations
    for st in stations:
        y = y0 + st.t * length
        rings.append([Vector((layout.x_offset + x, y, z)) for x, z in cross_section(st, chamfer, ridge)])
    segs = [a + b for a, b in zip(rings, rings[1:])]
    if layout.point_nose:
        segs.append(rings[-1] + [Vector((layout.x_offset, layout.y_front, 0.0))])
    return segs


def merge(pieces: list[list[Vector]], tolerance: float = MERGE_TOLERANCE) -> list[list[Vector]]:
    """Greedily merge neighbouring pieces whose union is still (almost) convex."""
    out: list[list[Vector]] = []
    vols: list[float] = []
    for piece in pieces:
        v = hull_volume(piece)
        if out:
            joined = out[-1] + piece
            joined_vol = hull_volume(joined)
            if joined_vol <= (vols[-1] + v) * (1.0 + tolerance):
                out[-1], vols[-1] = joined, joined_vol
                continue
        out.append(list(piece))
        vols.append(v)
    return out


def convex_object(points, name: str, collection, parent):
    """Convex hull of ``points`` (in the parent's space) as a Godot collision-only object
    (``name`` must end in ``SUFFIX``); None if the points span no volume."""
    if len(points) < 4:
        return None
    bm = _hull_bmesh(points)
    if not bm.faces:
        bm.free()
        return None
    mesh = bpy.data.meshes.new(name.removesuffix(SUFFIX))
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.display_type = "WIRE"
    obj.hide_render = True
    obj["shipgen_role"] = "collision"
    collection.objects.link(obj)
    obj.parent = parent
    return obj


def build_colliders(pieces: list[list[Vector]], collection, parent, prefix: str = "Col") -> list:
    objects = []
    for i, points in enumerate(pieces):
        obj = convex_object(points, f"{prefix}_{i}{SUFFIX}", collection, parent)
        if obj is not None:
            objects.append(obj)
    return objects
