"""Export a generated ship: .glb, .blend and a Cycles preview render."""

from __future__ import annotations

import math
import os

import bpy
from mathutils import Vector

PREVIEW_COLLECTION = "ShipGen_Preview"


def _select_only(objects) -> None:
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def export_glb(ship, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    _select_only(ship.objects)
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
    )
    return path


def save_blend(path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(path), copy=True, check_existing=False)
    return path


def _clear_preview() -> None:
    coll = bpy.data.collections.get(PREVIEW_COLLECTION)
    if coll is None:
        return
    for obj in list(coll.all_objects):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Camera):
                bpy.data.cameras.remove(data)
            elif isinstance(data, bpy.types.Light):
                bpy.data.lights.remove(data)
    bpy.data.collections.remove(coll)


def _look_at(obj, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _corners(lo: Vector, hi: Vector) -> list[Vector]:
    return [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]


def fit_distance(rot, points, center: Vector, tan_h: float, tan_v: float, margin: float = 1.12) -> float:
    """Camera distance from ``center`` (along the camera's back axis) so that all
    ``points`` fit in the frame."""
    inv = rot.transposed()
    distance = 0.0
    for p in points:
        local = inv @ (p - center)  # camera space: x right, y up, -z forward
        distance = max(
            distance,
            abs(local.x) * margin / tan_h + local.z,
            abs(local.y) * margin / tan_v + local.z,
        )
    return max(distance, 0.1)


def setup_preview(ship, resolution=(960, 540), samples: int = 16) -> bpy.types.Object:
    """Add camera + lights framing the ship and configure Cycles on the CPU."""
    _clear_preview()
    scene = bpy.context.scene
    coll = bpy.data.collections.new(PREVIEW_COLLECTION)
    scene.collection.children.link(coll)

    lo, hi = ship.bounds()
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.1)

    cam_data = bpy.data.cameras.new("ShipGen_Camera")
    cam_data.lens = 50
    cam_data.clip_start = radius * 0.01
    cam_data.clip_end = radius * 100
    cam = bpy.data.objects.new("ShipGen_Camera", cam_data)
    coll.objects.link(cam)

    # Three-quarter view from the front right, slightly above.
    view_dir = Vector((1.0, 0.9, 0.6)).normalized()
    cam.location = center + view_dir * radius * 4
    _look_at(cam, center)
    aspect = resolution[0] / resolution[1]
    tan_h = cam_data.sensor_width / 2 / cam_data.lens  # sensor_fit AUTO: width is the long side
    tan_v = tan_h / aspect
    distance = fit_distance(cam.rotation_euler.to_matrix(), _corners(lo, hi), center, tan_h, tan_v)
    cam.location = center + view_dir * distance
    scene.camera = cam

    def add_light(name, kind, energy, direction, color=(1, 1, 1), angle=None):
        data = bpy.data.lights.new(name, kind)
        data.energy = energy
        data.color = color
        if angle is not None:
            data.angle = angle
        obj = bpy.data.objects.new(name, data)
        obj.location = center + Vector(direction).normalized() * distance
        _look_at(obj, center)
        coll.objects.link(obj)
        return obj

    add_light("ShipGen_Key", "SUN", 1.6, (0.6, 0.3, 1.0), angle=math.radians(3))
    add_light("ShipGen_Rim", "SUN", 1.6, (-0.7, -0.6, 0.4), color=(0.6, 0.75, 1.0))
    add_light("ShipGen_Fill", "SUN", 0.35, (0.2, 1.0, -0.4), color=(1.0, 0.85, 0.7))

    world = scene.world or bpy.data.worlds.new("ShipGen_World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.012, 0.015, 0.03, 1.0)
        bg.inputs["Strength"].default_value = 1.0

    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.use_denoising = _has_oidn()  # not compiled into Ubuntu's Blender package
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    return cam


def _has_oidn() -> bool:
    try:
        import _cycles

        return bool(getattr(_cycles, "with_openimagedenoise", False))
    except ImportError:
        return False


def render_preview(ship, path: str, resolution=(960, 540), samples: int = 16) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    setup_preview(ship, resolution=resolution, samples=samples)
    scene = bpy.context.scene
    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)
    return path


def export_all(
    ship,
    out_dir: str,
    name: str,
    glb: bool = True,
    blend: bool = True,
    render: bool = True,
    resolution=(960, 540),
    samples: int = 16,
) -> dict[str, str]:
    """Write ``<name>.glb``, ``<name>.png`` and ``<name>.blend`` into ``out_dir``."""
    paths = {}
    if glb:
        paths["glb"] = export_glb(ship, os.path.join(out_dir, name + ".glb"))
    if render:
        paths["png"] = render_preview(
            ship, os.path.join(out_dir, name + ".png"), resolution=resolution, samples=samples
        )
    if blend:  # last, so the .blend also contains the preview camera and lights
        paths["blend"] = save_blend(os.path.join(out_dir, name + ".blend"))
    return paths
