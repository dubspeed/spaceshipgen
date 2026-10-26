"""Decals: registration numbers and company emblems as thin plates hugging the hull.

A decal is a closed slab (top grid, bottom grid, rim) laid onto the surface by ray casts, its
top face textured with a small pixel image (sRGB) whose background is the paint underneath. So
decals need no transparency, get cut with the hull (wrecks) and end up in the palette atlas like
any paint (atlas.py). Text is a 5x7 pixel font, emblems are pixel shapes; the emblem belongs to
the paint scheme, so ships of one company carry the same sign.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .atlas import paint_of, to_srgb
from .generator.materials import MATERIAL_PREFIX

LIFT = 0.025  # metres: top of a decal above the surface
SINK = 0.02  # bottom below it (the slab stays closed and anchored)
PAD = 2  # pixels around text

FONT = {  # 5x7, rows top to bottom
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111", "3": "11110 00001 00001 01110 00001 00001 11110",
    "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00010 01100",
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11100 10010 10001 10001 10001 10010 11100",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 10101 01010", "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
    "-": "00000 00000 00000 11111 00000 00000 00000", " ": "00000 00000 00000 00000 00000 00000 00000",
}

EMBLEM_SIZE = 16
CLASS_CODE = {"miner": "MN", "freighter": "FR", "shuttle": "SH", "fighter": "FT", "interceptor": "IC",
              "corvette": "CV"}
# one emblem per paint scheme (company)
EMBLEM_OF = {"industrial_yellow": "chevron", "military_grey": "star", "white_red": "ring", "desert": "triangle",
             "navy": "diamond", "black_gold": "crown", "rust": "gear"}


def _emblem_mask(kind: str, n: int = EMBLEM_SIZE) -> list[list[bool]]:
    """n x n pixel shape, rows from the bottom."""
    out = [[False] * n for _ in range(n)]
    c = (n - 1) / 2
    for y in range(n):
        for x in range(n):
            u, v = (x - c) / c, (y - c) / c  # -1..1, v up
            r, a = math.hypot(u, v), math.atan2(v, u)
            if kind == "chevron":
                on = abs(abs(u) * 0.9 - (v + 0.3)) < 0.32 and v < 0.75
            elif kind == "star":
                spike = 0.45 + 0.5 * max(0.0, math.cos(5 * (a - math.pi / 2))) ** 3
                on = r < spike
            elif kind == "ring":
                on = 0.6 < r < 0.95 or (abs(v) < 0.18 and r < 0.95)
            elif kind == "triangle":
                on = v > -0.8 and abs(u) < (0.85 - v) * 0.55 and not (v > -0.45 and abs(u) < (0.35 - v) * 0.4)
            elif kind == "diamond":
                on = abs(u) + abs(v) < 0.95 and not abs(u) + abs(v) < 0.45
            elif kind == "crown":
                on = (-0.7 < v < -0.3 and abs(u) < 0.85) or (v >= -0.3 and abs(u) < 0.85 and
                                                              (abs(u) % 0.85 < 0.28 or abs(u) > 0.72) and v < 0.8)
            else:  # gear
                teeth = 0.78 + 0.17 * (math.cos(8 * a) > 0)
                on = 0.35 < r < teeth
            out[y][x] = on
    return out


def _text_mask(text: str) -> list[list[bool]]:
    w = len(text) * 6 - 1 + 2 * PAD
    h = 7 + 2 * PAD
    out = [[False] * w for _ in range(h)]
    for i, ch in enumerate(text.upper()):
        rows = FONT.get(ch, FONT[" "]).split()
        for ry, row in enumerate(rows):
            for rx, bit in enumerate(row):
                if bit == "1":
                    out[h - 1 - PAD - ry][PAD + i * 6 + rx] = True
    return out


def image(name: str, mask, bg, fg):
    """Packed sRGB image from a mask (rows from the bottom); ``bg``/``fg`` linear colours."""
    h, w = len(mask), len(mask[0])
    img = bpy.data.images.new(name, w, h, alpha=False)
    bgs, fgs = [to_srgb(c) for c in bg], [to_srgb(c) for c in fg]
    px = []
    for row in mask:
        for on in row:
            px.extend((*(fgs if on else bgs), 1.0))
    img.pixels.foreach_set(px)
    img.pack()
    return img


def material(name: str, img, paint) -> bpy.types.Material:
    """The paint's metal/roughness, its colour from the image (``mat["shipgen_decal"]`` = image)."""
    _, metallic, rough, _, _ = paint_of(paint)
    mat = bpy.data.materials.new(MATERIAL_PREFIX + name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Closest"
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = rough
    mat.diffuse_color = paint.diffuse_color
    mat["shipgen_decal"] = img.name
    return mat


def contrast(bg) -> tuple:
    """Dark or light ink, whichever reads on ``bg``."""
    lum = 0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]
    return (0.02, 0.02, 0.02) if lum > 0.18 else (0.85, 0.85, 0.82)


class Surface:
    """Ray casts onto a bmesh (the hull) to lay decals on it."""

    def __init__(self, bm):
        bm.normal_update()
        self.bvh = BVHTree.FromBMesh(bm)

    def project(self, centre: Vector, normal: Vector, up: Vector, width: float, height: float,
                nu: int, nv: int, reach: float):
        """Grid of (hit point, hit normal) over the rectangle, or None where it doesn't sit well
        (a ray misses, the surface turns away, or it jumps). The decal faces the way the surface
        does at its centre (chamfered flanks), ``up`` kept as upright as that allows."""
        hit = self.bvh.ray_cast(centre + normal * reach, -normal, 2 * reach)
        if hit[0] is None or hit[1].dot(normal) < 0.3:
            return None
        normal = hit[1].normalized()
        up = (up - normal * up.dot(normal)).normalized()
        centre = hit[0]
        right = up.cross(normal).normalized()  # reads left to right seen from outside
        grid = []
        for j in range(nv + 1):
            row = []
            for i in range(nu + 1):
                p = centre + right * (i / nu - 0.5) * width + up * (j / nv - 0.5) * height
                hit = self.bvh.ray_cast(p + normal * reach, -normal, 2 * reach)
                if hit[0] is None or hit[1].dot(normal) < 0.35:  # it may bend round a chamfer
                    return None
                row.append((hit[0], hit[1]))
            grid.append(row)
        depths = [(p - centre).dot(normal) for row in grid for p, _ in row]
        if max(depths) - min(depths) > 0.5 * height:
            return None
        return grid


def lay(bm, grid, top_mat: int, side_mat: int, uv_layer, flip_u=False) -> int:
    """A closed slab over ``grid``; the top face carries the decal UVs. Returns its triangles."""
    nv, nu = len(grid) - 1, len(grid[0]) - 1
    top = [[bm.verts.new(p + n * LIFT) for p, n in row] for row in grid]
    bot = [[bm.verts.new(p - n * SINK) for p, n in row] for row in grid]
    faces = 0
    for j in range(nv):
        for i in range(nu):
            f = bm.faces.new((top[j][i], top[j][i + 1], top[j + 1][i + 1], top[j + 1][i]))
            f.material_index = top_mat
            for loop in f.loops:
                jj = next(r for r in range(nv + 1) if loop.vert in top[r])
                ii = top[jj].index(loop.vert)
                u = ii / nu
                loop[uv_layer].uv = (1.0 - u if flip_u else u, jj / nv)
            g = bm.faces.new((bot[j + 1][i], bot[j + 1][i + 1], bot[j][i + 1], bot[j][i]))
            g.material_index = side_mat
            faces += 4
    ring_t = [top[0][i] for i in range(nu)] + [top[j][nu] for j in range(nv)] + \
             [top[nv][i] for i in range(nu, 0, -1)] + [top[j][0] for j in range(nv, 0, -1)]
    ring_b = [bot[0][i] for i in range(nu)] + [bot[j][nu] for j in range(nv)] + \
             [bot[nv][i] for i in range(nu, 0, -1)] + [bot[j][0] for j in range(nv, 0, -1)]
    for k in range(len(ring_t)):
        k2 = (k + 1) % len(ring_t)
        bm.faces.new((ring_b[k], ring_b[k2], ring_t[k2], ring_t[k])).material_index = side_mat
        faces += 2
    return faces
