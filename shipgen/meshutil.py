"""Mesh helpers for parts made of several closed shells (a tank of two spheres and a cradle,
a drill of three cones ...).

``bmesh.ops.recalc_face_normals`` can turn a whole shell inside out when shells overlap, which
both breaks rendering (back-face culling) and makes its volume count negative. Here every
shell is handled on its own: its signed volume tells which way it faces.
"""

from __future__ import annotations

import bmesh


def shells(bm) -> list[list]:
    """Faces grouped into edge-connected shells."""
    seen: set = set()
    out = []
    for f in bm.faces:
        if f in seen:
            continue
        stack, shell = [f], []
        seen.add(f)
        while stack:
            g = stack.pop()
            shell.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
        out.append(shell)
    return out


def signed_volume(faces) -> float:
    """Signed volume enclosed by ``faces`` (positive when their normals point outwards)."""
    v = 0.0
    for f in faces:
        co = [loop.vert.co for loop in f.loops]
        for i in range(1, len(co) - 1):
            v += co[0].dot(co[i].cross(co[i + 1]))
    return v / 6.0


def orient_outward(bm) -> None:
    """Consistent winding per shell, then every shell turned to face outwards."""
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    flip = [f for shell in shells(bm) if signed_volume(shell) < 0 for f in shell]
    if flip:
        bmesh.ops.reverse_faces(bm, faces=flip)
    bm.normal_update()


def volume(bm) -> float:
    """Sum of the shells' volumes, each counted positive (overlaps count twice, as before)."""
    return sum(abs(signed_volume(shell)) for shell in shells(bm))
