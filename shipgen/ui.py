"""Add-on UI: sidebar panels (ships, asteroids) + operators.

Scene properties are generated from the schemas (``params.SCHEMA`` for ships,
``asteroids.params.SCHEMA`` for asteroids) so the panel, the CLI and the AI prompt
always share the same parameters and limits.
"""

import json
import os
import random

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import asteroids, export, generator, params
from .asteroids import params as asteroid_params
from .generator.materials import hex_to_rgb

_SEP = "__"


def _prop_name(path: tuple) -> str:
    return _SEP.join(path)


def _make_property(path: tuple, spec: params.Field):
    label = path[-1].replace("_", " ").title()
    kw = {"name": label, "description": spec.description or label}
    if spec.type is bool:
        return BoolProperty(default=spec.default, **kw)
    if spec.type is int:
        return IntProperty(default=spec.default, min=int(spec.min), max=int(spec.max), **kw)
    if spec.type is float:
        return FloatProperty(default=spec.default, min=spec.min, max=spec.max, **kw)
    if spec.choices:
        items = [(c, c.replace("_", " ").title(), "") for c in spec.choices]
        return EnumProperty(items=items, default=spec.default, **kw)
    if spec.color:
        return FloatVectorProperty(subtype="COLOR", size=3, min=0, max=1, default=hex_to_rgb(spec.default), **kw)
    return StringProperty(default=spec.default, **kw)


def _props_class(name: str, schema: dict, extra: dict):
    annotations = {_prop_name(path): _make_property(path, spec) for path, spec in params.iter_fields(schema)}
    annotations["export_dir"] = StringProperty(name="Export Folder", subtype="DIR_PATH", default="//output/")
    annotations.update(extra)
    return type(name, (bpy.types.PropertyGroup,), {"__annotations__": annotations})


def _show_level(self, context) -> None:
    """Viewport: show the asteroid's chunks of one break level (deeper levels are prepared hidden)."""
    for obj in bpy.data.objects:
        info = obj.get("asteroid_chunk")
        if info is None:
            continue
        level, leaf = info["level"], info["children"] == 0
        visible = level == self.show_level or (level < self.show_level and leaf)
        obj.hide_viewport = obj.hide_render = not visible
        for child in obj.children:
            if child.get("shipgen_role") == "collision":
                child.hide_viewport = not visible


ShipGenProperties = _props_class("ShipGenProperties", params.SCHEMA, {})
ShipGenAsteroidProperties = _props_class("ShipGenAsteroidProperties", asteroid_params.SCHEMA, {
    "show_level": IntProperty(name="Show Level", min=1, max=6, default=1, update=_show_level,
                              description="Viewport: show the chunks of this break level"),
})


def props_to_params(props, schema_mod=params) -> dict:
    out: dict = {}
    for path, spec in schema_mod.iter_fields(schema_mod.SCHEMA):
        value = getattr(props, _prop_name(path))
        if spec.color:
            value = "#" + "".join(f"{round(c * 255):02x}" for c in value)
        params.set_path(out, path, value)
    return schema_mod.validate(out).params


def params_to_props(p: dict, props, schema_mod=params) -> None:
    for path, spec in schema_mod.iter_fields(schema_mod.SCHEMA):
        value = params.get_path(p, path)
        if spec.color:
            value = hex_to_rgb(value)
        setattr(props, _prop_name(path), value)


class SHIPGEN_OT_generate(bpy.types.Operator):
    bl_idname = "shipgen.generate"
    bl_label = "Generate Ship"
    bl_description = "Build a ship from the current parameters"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = props_to_params(context.scene.shipgen)
        ship = generator.generate(p)
        stats = ship.stats()
        self.report({"INFO"}, f"Ship generated: {stats['tris']} tris (budget {stats['max_tris']})")
        return {"FINISHED"}


class SHIPGEN_OT_random_seed(bpy.types.Operator):
    bl_idname = "shipgen.random_seed"
    bl_label = "Random Seed"
    bl_description = "Pick a new seed and regenerate"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.shipgen.seed = random.randint(0, 999_999)
        return bpy.ops.shipgen.generate()


class SHIPGEN_OT_load_preset(bpy.types.Operator, ImportHelper):
    bl_idname = "shipgen.load_preset"
    bl_label = "Load Parameters"
    bl_description = "Load ship parameters from a JSON file (e.g. presets/fighter.json)"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        result = params.load(self.filepath)
        params_to_props(result.params, context.scene.shipgen)
        for w in result.warnings:
            self.report({"WARNING"}, w)
        return bpy.ops.shipgen.generate()


class SHIPGEN_OT_copy_params(bpy.types.Operator):
    bl_idname = "shipgen.copy_params"
    bl_label = "Copy Parameters"
    bl_description = "Copy the current parameters as JSON to the clipboard"

    def execute(self, context):
        context.window_manager.clipboard = json.dumps(props_to_params(context.scene.shipgen), indent=2)
        self.report({"INFO"}, "Parameters copied to clipboard")
        return {"FINISHED"}


class SHIPGEN_OT_export(bpy.types.Operator):
    bl_idname = "shipgen.export"
    bl_label = "Export .glb"
    bl_description = "Export the current ship as .glb (plus params .json) into the export folder"

    def execute(self, context):
        props = context.scene.shipgen
        root = bpy.data.objects.get("Ship")
        if root is None:
            self.report({"ERROR"}, "Generate a ship first")
            return {"CANCELLED"}
        p = props_to_params(props)
        ship = generator.Ship(root=root, parts=list(root.children), params=p)
        out_dir = bpy.path.abspath(props.export_dir)
        name = f"{p['class']}_{p['seed']}"
        path = export.export_glb(ship, os.path.join(out_dir, name + ".glb"))
        with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(p, f, indent=2)
        self.report({"INFO"}, f"Exported {path}")
        return {"FINISHED"}


class SHIPGEN_PT_panel(bpy.types.Panel):
    bl_label = "ShipGen"
    bl_idname = "SHIPGEN_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ShipGen"

    def draw(self, context):
        props = context.scene.shipgen
        layout = self.layout

        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("shipgen.generate", icon="MESH_ICOSPHERE")
        row.operator("shipgen.random_seed", text="", icon="FILE_REFRESH")

        col = layout.column(align=True)
        col.prop(props, "seed")
        col.prop(props, "class")
        col.prop(props, "max_tris")
        col.prop(props, "symmetry")
        col.prop(props, "greeble_density")

        for group, spec in params.SCHEMA.items():
            if not isinstance(spec, dict):
                continue
            box = layout.box()
            box.label(text=group.title())
            sub = box.column(align=True)
            for key in spec:
                sub.prop(props, _prop_name((group, key)))

        row = layout.row(align=True)
        row.operator("shipgen.load_preset", icon="FILEBROWSER")
        row.operator("shipgen.copy_params", icon="COPYDOWN")
        layout.prop(props, "export_dir")
        layout.operator("shipgen.export", icon="EXPORT")


# ---------------------------------------------------------------- asteroids

# panel sections; every asteroid parameter appears in one (test_ui checks it)
ASTEROID_GROUPS = (
    ("Rock", ("seed", "composition", "shape", "size_m", "facets")),
    ("Surface", ("roughness", "craters", "gap")),
    ("Breaking", ("chunks", "sub_chunks", "min_chunk_m", "max_levels", "richness", "max_tris")),
)


def _asteroid_props(context):
    return context.scene.shipgen_asteroid


class SHIPGEN_OT_asteroid_generate(bpy.types.Operator):
    bl_idname = "shipgen.asteroid_generate"
    bl_label = "Generate Asteroid"
    bl_description = "Build an asteroid (pre-fractured into chunks) from the current parameters"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = _asteroid_props(context)
        rock = asteroids.generate(props_to_params(props, asteroid_params))
        props.show_level = 1  # the whole rock
        s = rock.stats
        for w in rock.warnings:
            self.report({"WARNING"}, w)
        self.report({"INFO"}, f"Asteroid generated: {len(rock.chunks)} chunks, {s['yield_m3']:.0f} m³ {s['cargo']}")
        return {"FINISHED"}


class SHIPGEN_OT_asteroid_random_seed(bpy.types.Operator):
    bl_idname = "shipgen.asteroid_random_seed"
    bl_label = "Random Seed"
    bl_description = "Pick a new seed and regenerate the asteroid"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _asteroid_props(context).seed = random.randint(0, 999_999)
        return bpy.ops.shipgen.asteroid_generate()


class SHIPGEN_OT_asteroid_load_preset(bpy.types.Operator, ImportHelper):
    bl_idname = "shipgen.asteroid_load_preset"
    bl_label = "Load Parameters"
    bl_description = "Load asteroid parameters from a JSON file (e.g. presets/asteroids/ore_m.json)"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        result = asteroid_params.load(self.filepath)
        params_to_props(result.params, _asteroid_props(context), asteroid_params)
        for w in result.warnings:
            self.report({"WARNING"}, w)
        return bpy.ops.shipgen.asteroid_generate()


class SHIPGEN_OT_asteroid_copy_params(bpy.types.Operator):
    bl_idname = "shipgen.asteroid_copy_params"
    bl_label = "Copy Parameters"
    bl_description = "Copy the current asteroid parameters as JSON to the clipboard"

    def execute(self, context):
        p = props_to_params(_asteroid_props(context), asteroid_params)
        context.window_manager.clipboard = json.dumps(p, indent=2)
        self.report({"INFO"}, "Parameters copied to clipboard")
        return {"FINISHED"}


class SHIPGEN_OT_asteroid_export(bpy.types.Operator):
    bl_idname = "shipgen.asteroid_export"
    bl_label = "Export .glb"
    bl_description = "Export the asteroid with all break levels as .glb (plus params .json) into the export folder"

    def execute(self, context):
        props = _asteroid_props(context)
        p = props_to_params(props, asteroid_params)
        rock = asteroids.generate(p)  # deterministic: rebuilds exactly what the panel shows
        props.show_level = 1
        out_dir = bpy.path.abspath(props.export_dir)
        name = f"asteroid_{p['composition']}_{p['seed']}"
        path = export.export_glb(rock, os.path.join(out_dir, name + ".glb"))
        with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as f:
            json.dump({"params": p, "stats": rock.stats}, f, indent=2)
        self.report({"INFO"}, f"Exported {path}")
        return {"FINISHED"}


class SHIPGEN_PT_asteroids(bpy.types.Panel):
    bl_label = "Asteroids"
    bl_idname = "SHIPGEN_PT_asteroids"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ShipGen"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        props = _asteroid_props(context)
        layout = self.layout

        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("shipgen.asteroid_generate", icon="MESH_ICOSPHERE")
        row.operator("shipgen.asteroid_random_seed", text="", icon="FILE_REFRESH")

        for title, keys in ASTEROID_GROUPS:
            box = layout.box()
            box.label(text=title)
            col = box.column(align=True)
            for key in keys:
                col.prop(props, key)

        root = bpy.data.objects.get("Asteroid")
        info = root.get("shipgen_asteroid") if root is not None else None
        if info is not None:
            s = info["stats"]
            box = layout.box()
            box.label(text="Values", icon="INFO")
            col = box.column(align=True)
            col.label(text=f"{s['size_m']:.1f} m   {s['volume_m3']:.0f} m³   {s['mass_t']:.0f} t")
            col.label(text=f"Yield {s['yield_m3']:.0f} m³ ({s['cargo']}), hardness {s['hardness']}")
            levels = ", ".join(f"L{k}: {v}" for k, v in sorted(s["chunks_per_level"].items()))
            col.label(text=f"Chunks {levels}")
            box.prop(props, "show_level")

        row = layout.row(align=True)
        row.operator("shipgen.asteroid_load_preset", icon="FILEBROWSER")
        row.operator("shipgen.asteroid_copy_params", icon="COPYDOWN")
        layout.prop(props, "export_dir")
        layout.operator("shipgen.asteroid_export", icon="EXPORT")


classes = (
    ShipGenProperties,
    ShipGenAsteroidProperties,
    SHIPGEN_OT_generate,
    SHIPGEN_OT_random_seed,
    SHIPGEN_OT_load_preset,
    SHIPGEN_OT_copy_params,
    SHIPGEN_OT_export,
    SHIPGEN_PT_panel,
    SHIPGEN_OT_asteroid_generate,
    SHIPGEN_OT_asteroid_random_seed,
    SHIPGEN_OT_asteroid_load_preset,
    SHIPGEN_OT_asteroid_copy_params,
    SHIPGEN_OT_asteroid_export,
    SHIPGEN_PT_asteroids,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.shipgen = bpy.props.PointerProperty(type=ShipGenProperties)
    bpy.types.Scene.shipgen_asteroid = bpy.props.PointerProperty(type=ShipGenAsteroidProperties)


def unregister():
    del bpy.types.Scene.shipgen_asteroid
    del bpy.types.Scene.shipgen
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
