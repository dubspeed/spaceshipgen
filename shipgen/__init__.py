"""ShipGen - procedural spaceship generator, packaged as a Blender 4.2+ extension
(see ``blender_manifest.toml``; build the zip with ``scripts/build_extension.py``).

The UI lives in ``ui.py`` and is only imported on registration, so the generator
can also be driven headless (``cli.py``) and ``shipgen.params`` needs no Blender.
"""


def register():
    from . import ui

    ui.register()


def unregister():
    from . import ui

    ui.unregister()
