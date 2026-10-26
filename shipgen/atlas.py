"""Palette atlas: every exported mesh gets one material instead of one per paint.

In Blender the generators keep plain Principled materials per paint (hull, accent, glow ...):
stats read them (glow area = thrust, cargo volume) and they stay editable. At export
(``baked``) every material becomes a cell of a small atlas, every face points into its cell via
UVs, and every mesh uses the one material ``ShipGen_Atlas``:

- ``ShipGen_Atlas_Color``  base colour (RGB),
- ``ShipGen_Atlas_MR``     glTF metallic-roughness (G = roughness, B = metallic),
- ``ShipGen_Atlas_Emit``   emission (RGB, scaled so the brightest cell is 1; the strength sits
  in the material).

Decal materials (``mat["shipgen_decal"]`` = image name; see decals.py) are copied into the atlas
below the paint cells, and their faces' UVs are moved into that region.

The textures are tiny and want ``NEAREST`` filtering (no blur between cells); cells are
``CELL`` pixels wide with their colour filling the whole cell, so mipmaps down to 1/CELL stay
clean.
"""

from __future__ import annotations

import contextlib
import math

import bpy

MATERIAL = "ShipGen_Atlas"
CELL = 8  # pixels per paint cell
COLS = 8  # paint cells per row


def _principled(mat):
    if mat is None or not mat.use_nodes:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def paint_of(mat) -> tuple:
    """(rgb, metallic, roughness, emission rgb, emission strength) of a plain material."""
    b = _principled(mat)
    if b is None:
        c = tuple(mat.diffuse_color[:3]) if mat is not None else (0.5, 0.5, 0.5)
        return c, 0.0, 0.5, (0.0, 0.0, 0.0), 0.0
    strength = b.inputs["Emission Strength"].default_value
    emit = tuple(b.inputs["Emission Color"].default_value[:3]) if strength > 0 else (0.0, 0.0, 0.0)
    return (tuple(b.inputs["Base Color"].default_value[:3]), b.inputs["Metallic"].default_value,
            b.inputs["Roughness"].default_value, emit, strength)


def to_srgb(c: float) -> float:
    """Linear (Principled values) -> sRGB (what a glTF colour texture stores)."""
    c = min(max(c, 0.0), 1.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _pow2(n: int) -> int:
    return 1 << max(0, math.ceil(math.log2(max(n, 1))))


class Atlas:
    """Layout of paint cells and decal images; pixels written by ``build``."""

    def __init__(self, materials):
        self.paints: dict = {}  # paint key -> cell index
        self.decals: dict = {}  # image name -> (x0, y0, w, h) in pixels
        self.cell_of: dict = {}  # material name -> ("paint", cell) or ("decal", image name, paint cell)
        decal_images = []
        for mat in materials:
            name = mat["shipgen_decal"] if mat is not None and "shipgen_decal" in mat else None
            key = paint_of(mat)
            cell = self.paints.setdefault(key, len(self.paints))
            if name is not None and name in bpy.data.images:
                if name not in [d.name for d in decal_images]:
                    decal_images.append(bpy.data.images[name])
                self.cell_of[mat.name] = ("decal", name, cell)
            else:
                self.cell_of[mat.name if mat is not None else ""] = ("paint", cell)
        rows = math.ceil(len(self.paints) / COLS)
        y = rows * CELL
        width = COLS * CELL
        for img in decal_images:
            w, h = img.size
            self.decals[img.name] = (0, y, w, h)
            y += h
            width = max(width, w)
        self.width, self.height = _pow2(width), _pow2(y)
        self.images = decal_images

    def cell_uv(self, cell: int) -> tuple[float, float]:
        cx, cy = cell % COLS, cell // COLS
        return ((cx + 0.5) * CELL / self.width, (cy + 0.5) * CELL / self.height)

    def decal_uv(self, name: str, uv) -> tuple[float, float]:
        x0, y0, w, h = self.decals[name]
        return ((x0 + uv[0] * w) / self.width, (y0 + uv[1] * h) / self.height)

    def build(self):
        """Create the three images and the material."""
        w, h = self.width, self.height
        color = [0.0] * (w * h * 4)
        mr = [0.0] * (w * h * 4)
        emit = [0.0] * (w * h * 4)
        max_strength = max((k[4] for k in self.paints), default=0.0) or 1.0

        def put(buf, x, y, rgba):
            i = (y * w + x) * 4
            buf[i:i + 4] = rgba

        for key, cell in self.paints.items():
            rgb, metallic, rough, erg, strength = key
            cx, cy = (cell % COLS) * CELL, (cell // COLS) * CELL
            e = [to_srgb(c * strength / max_strength) for c in erg]
            srgb = [to_srgb(c) for c in rgb]
            for y in range(cy, cy + CELL):
                for x in range(cx, cx + CELL):
                    put(color, x, y, (*srgb, 1.0))
                    put(mr, x, y, (0.0, rough, metallic, 1.0))
                    put(emit, x, y, (*e, 1.0))
        for img in self.images:  # decals (sRGB pixels already): their own pixels, the paint's metal/roughness
            x0, y0, dw, dh = self.decals[img.name]
            px = list(img.pixels)
            hull = next(k for k, c in self.paints.items() if ("decal", img.name, c) in self.cell_of.values())
            for y in range(dh):
                for x in range(dw):
                    i = (y * dw + x) * 4
                    put(color, x0 + x, y0 + y, (*px[i:i + 3], 1.0))
                    put(mr, x0 + x, y0 + y, (0.0, hull[2], hull[1], 1.0))
                    put(emit, x0 + x, y0 + y, (0.0, 0.0, 0.0, 1.0))
        imgs = {}
        for name, buf, colorspace in (("Color", color, "sRGB"), ("MR", mr, "Non-Color"), ("Emit", emit, "sRGB")):
            img = bpy.data.images.new(f"{MATERIAL}_{name}", w, h, alpha=False)
            img.colorspace_settings.name = colorspace
            img.pixels.foreach_set(buf)
            img.pack()
            imgs[name] = img
        self.material = _material(imgs, max_strength)
        self.textures = list(imgs.values())
        return self.material


def _material(imgs, strength: float):
    mat = bpy.data.materials.new(MATERIAL)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")

    def tex(img, x):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = img
        n.interpolation = "Closest"
        n.location = (x, 0)
        return n

    nt.links.new(tex(imgs["Color"], -600).outputs["Color"], bsdf.inputs["Base Color"])
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(tex(imgs["MR"], -800).outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    nt.links.new(tex(imgs["Emit"], -600).outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = strength
    return mat


def _bake_mesh(mesh, atlas: Atlas):
    """A copy of ``mesh`` with atlas UVs and the atlas material."""
    out = mesh.copy()
    uv_src = mesh.uv_layers.get("UVMap")
    for layer in list(out.uv_layers):
        out.uv_layers.remove(layer)
    uv = out.uv_layers.new(name="UVMap")
    names = [m.name if m is not None else "" for m in mesh.materials]
    for poly in out.polygons:
        slot = atlas.cell_of.get(names[poly.material_index] if poly.material_index < len(names) else "",
                                 ("paint", 0))
        for li in poly.loop_indices:
            if slot[0] == "decal" and uv_src is not None:
                uv.data[li].uv = atlas.decal_uv(slot[1], uv_src.data[li].uv)
            else:
                uv.data[li].uv = atlas.cell_uv(slot[-1])
    out.materials.clear()
    out.materials.append(atlas.material)
    for poly in out.polygons:
        poly.material_index = 0
    return out


@contextlib.contextmanager
def baked(objects):
    """While inside: every mesh of ``objects`` with materials uses the shared atlas material."""
    meshes = [o for o in objects if o.type == "MESH" and len(o.data.materials)]
    if not meshes:
        yield None
        return
    mats = list(dict.fromkeys(m for o in meshes for m in o.data.materials))
    atlas = Atlas(mats)
    atlas.build()
    swapped = []
    try:
        for obj in meshes:
            original = obj.data
            obj.data = _bake_mesh(original, atlas)
            swapped.append((obj, original))
        bpy.context.view_layer.update()  # the exporter reads the evaluated (depsgraph) meshes
        yield atlas
    finally:
        for obj, original in swapped:
            copy = obj.data
            obj.data = original
            bpy.data.meshes.remove(copy)
        bpy.data.materials.remove(atlas.material)
        for img in atlas.textures:
            bpy.data.images.remove(img)
