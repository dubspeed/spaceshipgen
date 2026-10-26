"""Add-on UI: sidebar panels (ships, wrecks, asteroids, stations) + operators.

Scene properties are generated from the schemas (``params.SCHEMA`` for ships, and the
``params.SCHEMA`` of ``asteroids``, ``wrecks`` and ``stations``) so the panels, the CLI and
the AI prompt always share the same parameters and limits.
"""

import json
import os
import random

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import asteroids, export, generator, params, stations, wrecks
from .asteroids import params as asteroid_params
from .stations import params as station_params
from .wrecks import params as wreck_params
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

ShipGenWreckProperties = _props_class("ShipGenWreckProperties", wreck_params.SCHEMA, {})
ShipGenStationProperties = _props_class("ShipGenStationProperties", station_params.SCHEMA, {})


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
        ship = generator.Ship(root=root, parts=list(root.children_recursive), params=p)  # incl. part colliders
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


# ---------------------------------------------------------------- wrecks

WRECK_GROUPS = (
    ("Wreck", ("seed", "ship_seed", "damage")),
    ("Damage", ("breaks", "spread", "holes", "burn", "debris")),
)


def _wreck(context):
    p = props_to_params(context.scene.shipgen_wreck, wreck_params)
    return p, wrecks.generate(p, props_to_params(context.scene.shipgen))


class SHIPGEN_OT_wreck_generate(bpy.types.Operator):
    bl_idname = "shipgen.wreck_generate"
    bl_label = "Wreck Ship"
    bl_description = "Build a wreck of the ship set up in the ShipGen panel (next to the ship)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _, wreck = _wreck(context)
        for w in wreck.warnings:
            self.report({"WARNING"}, w)
        parts = wreck.stats["parts"]
        self.report({"INFO"}, f"Wreck: {wreck.stats['segments']} segments, {parts['intact']} intact / "
                              f"{parts['damaged']} damaged / {parts['detached']} detached / "
                              f"{parts['destroyed']} destroyed")
        return {"FINISHED"}


class SHIPGEN_OT_wreck_random_seed(bpy.types.Operator):
    bl_idname = "shipgen.wreck_random_seed"
    bl_label = "Random Seed"
    bl_description = "Pick a new wreck seed and rebuild the wreck"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.shipgen_wreck.seed = random.randint(0, 999_999)
        return bpy.ops.shipgen.wreck_generate()


class SHIPGEN_OT_wreck_export(bpy.types.Operator):
    bl_idname = "shipgen.wreck_export"
    bl_label = "Export .glb"
    bl_description = "Export the wreck as .glb (plus params .json) into the export folder"

    def execute(self, context):
        p, wreck = _wreck(context)  # deterministic: rebuilds exactly what the panel shows
        out_dir = bpy.path.abspath(context.scene.shipgen_wreck.export_dir)
        name = f"wreck_{wreck.ship_params['class']}_{wreck.ship_params['seed']}_{p['seed']}"
        path = export.export_glb(wreck, os.path.join(out_dir, name + ".glb"))
        with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as f:
            json.dump({"params": p, "ship_params": wreck.ship_params, "stats": wreck.stats}, f, indent=2)
        self.report({"INFO"}, f"Exported {path}")
        return {"FINISHED"}


class SHIPGEN_PT_wrecks(bpy.types.Panel):
    bl_label = "Wrecks"
    bl_idname = "SHIPGEN_PT_wrecks"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ShipGen"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        props = context.scene.shipgen_wreck
        layout = self.layout
        layout.label(text="Wrecks the ship set up above", icon="INFO")
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("shipgen.wreck_generate", icon="MOD_EXPLODE")
        row.operator("shipgen.wreck_random_seed", text="", icon="FILE_REFRESH")
        for title, keys in WRECK_GROUPS:
            box = layout.box()
            box.label(text=title)
            col = box.column(align=True)
            for key in keys:
                col.prop(props, key)
        root = bpy.data.objects.get("Wreck")
        info = root.get("shipgen_wreck") if root is not None else None
        if info is not None:
            s = info["stats"]
            box = layout.box()
            box.label(text="Salvage", icon="INFO")
            col = box.column(align=True)
            parts = s["parts"]
            col.label(text=f"Parts: {parts['intact']} intact, {parts['damaged']} damaged")
            col.label(text=f"       {parts['detached']} detached, {parts['destroyed']} destroyed")
            col.label(text=f"Salvage {s['salvage_mass_t']:.1f} t, scrap {s['scrap_mass_t']:.1f} t")
        layout.prop(props, "export_dir")
        layout.operator("shipgen.wreck_export", icon="EXPORT")


# ---------------------------------------------------------------- stations

STATION_GROUPS = (
    ("Layout", ("seed", "role", "size", "symmetry", "build")),
    ("Style", ("style__palette", "style__wear", "style__glow_color")),
)


class SHIPGEN_OT_station_generate(bpy.types.Operator):
    bl_idname = "shipgen.station_generate"
    bl_label = "Generate Station"
    bl_description = "Lay out and build a station from the module kit"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = stations.generate(props_to_params(context.scene.shipgen_station, station_params))
        s = st.stats
        berths = ", ".join(f"{n}×{k}" for k, n in s["berths"].items() if n)
        self.report({"INFO"}, f"Station: {s['modules']} modules, berths {berths or 'none'}")
        return {"FINISHED"}


class SHIPGEN_OT_station_random_seed(bpy.types.Operator):
    bl_idname = "shipgen.station_random_seed"
    bl_label = "Random Seed"
    bl_description = "Pick a new seed and regenerate the station"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.shipgen_station.seed = random.randint(0, 999_999)
        return bpy.ops.shipgen.station_generate()


class SHIPGEN_OT_station_kit(bpy.types.Operator):
    bl_idname = "shipgen.station_kit"
    bl_label = "Build Module Kit"
    bl_description = "Every station module design, unassembled (the library the game builds stations from)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        kit = stations.build_kit(props_to_params(context.scene.shipgen_station, station_params))
        self.report({"INFO"}, f"Module kit: {len(kit.parts)} designs")
        return {"FINISHED"}


class SHIPGEN_OT_station_export(bpy.types.Operator):
    bl_idname = "shipgen.station_export"
    bl_label = "Export .glb"
    bl_description = "Export the station (or the module kit, whichever is built) as .glb into the export folder"

    def execute(self, context):
        props = context.scene.shipgen_station
        p = props_to_params(props, station_params)
        if bpy.data.objects.get("StationKit") is not None:
            built, name = stations.build_kit(p), "station_kit"
        else:
            built, name = stations.generate(p), f"station_{p['role']}_{p['seed']}"
        out_dir = bpy.path.abspath(props.export_dir)
        path = export.export_glb(built, os.path.join(out_dir, name + ".glb"))
        with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as f:
            json.dump({"params": p, "stats": built.stats}, f, indent=2)
        self.report({"INFO"}, f"Exported {path}")
        return {"FINISHED"}


class SHIPGEN_PT_stations(bpy.types.Panel):
    bl_label = "Stations"
    bl_idname = "SHIPGEN_PT_stations"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ShipGen"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        props = context.scene.shipgen_station
        layout = self.layout
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("shipgen.station_generate", icon="MESH_GRID")
        row.operator("shipgen.station_random_seed", text="", icon="FILE_REFRESH")
        layout.operator("shipgen.station_kit", icon="ASSET_MANAGER")
        for title, keys in STATION_GROUPS:
            box = layout.box()
            box.label(text=title)
            col = box.column(align=True)
            for key in keys:
                col.prop(props, key)
        root = bpy.data.objects.get("Station")
        info = root.get("shipgen_station") if root is not None else None
        if info is not None:
            s = info["stats"]
            box = layout.box()
            box.label(text="Values", icon="INFO")
            col = box.column(align=True)
            b = s["berths"]
            col.label(text=f"{s['modules']} modules, berths S {b['S']} / M {b['M']} / L {b['L']}")
            col.label(text=f"Storage {s['general_m3']:.0f} m³, ore {s['ore_m3']:.0f} m³, "
                           f"fluid {s['fluid_m3']:.0f} m³")
            col.label(text=f"Crew {s['crew']}, power {s['power_kw']:.0f} kW, free ports {s['free_ports']}")
        layout.prop(props, "export_dir")
        layout.operator("shipgen.station_export", icon="EXPORT")


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
    ShipGenWreckProperties,
    SHIPGEN_OT_wreck_generate,
    SHIPGEN_OT_wreck_random_seed,
    SHIPGEN_OT_wreck_export,
    SHIPGEN_PT_wrecks,
    ShipGenStationProperties,
    SHIPGEN_OT_station_generate,
    SHIPGEN_OT_station_random_seed,
    SHIPGEN_OT_station_kit,
    SHIPGEN_OT_station_export,
    SHIPGEN_PT_stations,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.shipgen = bpy.props.PointerProperty(type=ShipGenProperties)
    bpy.types.Scene.shipgen_asteroid = bpy.props.PointerProperty(type=ShipGenAsteroidProperties)
    bpy.types.Scene.shipgen_wreck = bpy.props.PointerProperty(type=ShipGenWreckProperties)
    bpy.types.Scene.shipgen_station = bpy.props.PointerProperty(type=ShipGenStationProperties)


def unregister():
    del bpy.types.Scene.shipgen_station
    del bpy.types.Scene.shipgen_wreck
    del bpy.types.Scene.shipgen_asteroid
    del bpy.types.Scene.shipgen
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
