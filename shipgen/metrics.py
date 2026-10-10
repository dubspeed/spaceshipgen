"""Shape metrics, e.g. to check that classes have distinct top-view silhouettes."""

from __future__ import annotations

import bpy
import numpy as np


def _world_triangles(objects) -> np.ndarray:
    """(n, 3, 3) world-space triangles of the evaluated meshes."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    tris = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        mesh.calc_loop_triangles()
        co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        idx = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int64)
        mesh.loop_triangles.foreach_get("vertices", idx)
        mat = np.array(obj.matrix_world)
        world = co @ mat[:3, :3].T + mat[:3, 3]
        tris.append(world[idx.reshape(-1, 3)])
        ev.to_mesh_clear()
    return np.concatenate(tris) if tris else np.zeros((0, 3, 3))


def top_view_mask(objects, resolution: int = 128) -> tuple[np.ndarray, tuple[float, float]]:
    """Rasterise the XY projection into a boolean mask over the XY bounding box.

    Returns (mask[rows=y, cols=x], (size_x, size_y)).
    """
    tris = _world_triangles(objects)[:, :, :2]
    lo = tris.reshape(-1, 2).min(axis=0)
    hi = tris.reshape(-1, 2).max(axis=0)
    size = np.maximum(hi - lo, 1e-9)
    scale = resolution / size.max()
    nx, ny = (np.ceil(size * scale).astype(int)).clip(1)
    xs = lo[0] + (np.arange(nx) + 0.5) / scale
    ys = lo[1] + (np.arange(ny) + 0.5) / scale
    px, py = np.meshgrid(xs, ys)
    mask = np.zeros((ny, nx), dtype=bool)
    for (ax, ay), (bx, by), (cx, cy) in tris:
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-12:
            continue  # edge-on in top view
        x0 = int(max((min(ax, bx, cx) - lo[0]) * scale - 0.5, 0))
        x1 = int(min((max(ax, bx, cx) - lo[0]) * scale + 0.5, nx - 1)) + 1
        y0 = int(max((min(ay, by, cy) - lo[1]) * scale - 0.5, 0))
        y1 = int(min((max(ay, by, cy) - lo[1]) * scale + 0.5, ny - 1)) + 1
        qx, qy = px[y0:y1, x0:x1], py[y0:y1, x0:x1]
        l1 = ((by - cy) * (qx - cx) + (cx - bx) * (qy - cy)) / det
        l2 = ((cy - ay) * (qx - cx) + (ax - cx) * (qy - cy)) / det
        mask[y0:y1, x0:x1] |= (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
    return mask, (float(size[0]), float(size[1]))


def top_view(ship, resolution: int = 128) -> dict:
    """Top-view silhouette metrics.

    fill:   silhouette area / bounding rectangle area (dart ~0.4, brick ~0.9)
    aspect: width / length of the silhouette's bounding rectangle
    """
    mask, (sx, sy) = top_view_mask(ship.parts, resolution)
    return {"fill": round(float(mask.mean()), 4), "aspect": round(sx / sy, 4)}
