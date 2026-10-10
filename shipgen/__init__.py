"""ShipGen - procedural spaceship generator for Blender.

Works as a legacy add-on (Blender 4.0/4.1, via ``bl_info``) and as an
extension (Blender 4.2+, via ``blender_manifest.toml``). The UI lives in
``ui.py`` and is only imported on registration, so ``shipgen.params`` can be
imported without Blender.
"""

bl_info = {
    "name": "ShipGen",
    "author": "ShipGen contributors",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > ShipGen",
    "description": "Procedural spaceship generator",
    "category": "Add Mesh",
}


def register():
    from . import ui

    ui.register()


def unregister():
    from . import ui

    ui.unregister()
