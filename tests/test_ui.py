"""Extension panel: properties come from the schemas, operators run headless."""

import json
import os
import tempfile
import unittest

try:
    import bpy
except ImportError:
    bpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class PanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shipgen
        from shipgen import ui

        bpy.ops.wm.read_factory_settings(use_empty=True)
        shipgen.register()
        cls.ui = ui

    @classmethod
    def tearDownClass(cls):
        import shipgen

        shipgen.unregister()

    def test_every_asteroid_parameter_is_in_the_panel(self):
        from shipgen.asteroids import params as ap

        shown = [k for _, keys in self.ui.ASTEROID_GROUPS for k in keys]
        self.assertEqual(sorted(shown), sorted(ap.SCHEMA))

    def test_asteroid_operators(self):
        from shipgen.asteroids import params as ap

        scene = bpy.context.scene
        props = scene.shipgen_asteroid
        defaults = ap.defaults()
        for key, value in self.ui.props_to_params(props, ap).items():
            if isinstance(value, float):  # Blender stores 32-bit floats
                self.assertAlmostEqual(value, defaults[key], places=5, msg=key)
            else:
                self.assertEqual(value, defaults[key], msg=key)

        bpy.ops.shipgen.asteroid_load_preset(filepath=os.path.join(ROOT, "presets", "asteroids", "ice_m.json"))
        self.assertEqual(props.composition, "ice")
        root = bpy.data.objects["Asteroid"]
        stats = root["shipgen_asteroid"].to_dict()["stats"]
        self.assertEqual(stats["cargo"], "fluid_m3")

        chunks = [o for o in bpy.data.objects if o.get("asteroid_chunk") is not None]
        level = {o.name: o["asteroid_chunk"]["level"] for o in chunks}
        self.assertTrue(all(o.hide_viewport == (level[o.name] > 1) for o in chunks))
        props.show_level = 2  # the update callback swaps the visible chunks
        for o in chunks:
            if level[o.name] == 2:
                self.assertFalse(o.hide_viewport)
            if level[o.name] == 1 and o["asteroid_chunk"]["children"]:
                self.assertTrue(o.hide_viewport)

        with tempfile.TemporaryDirectory() as tmp:
            props.export_dir = tmp
            bpy.ops.shipgen.asteroid_export()
            name = f"asteroid_ice_{props.seed}"
            self.assertTrue(os.path.exists(os.path.join(tmp, name + ".glb")))
            with open(os.path.join(tmp, name + ".json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["stats"]["cargo"], "fluid_m3")
        self.assertEqual(props.show_level, 1)

        seed = props.seed
        bpy.ops.shipgen.asteroid_random_seed()
        self.assertNotEqual(props.seed, seed)

    def test_every_wreck_and_station_parameter_is_in_its_panel(self):
        from shipgen.stations import params as sp
        from shipgen.wrecks import params as wp

        self.assertEqual(sorted(k for _, keys in self.ui.WRECK_GROUPS for k in keys), sorted(wp.SCHEMA))
        station_keys = [self.ui._prop_name(path) for path, _ in sp.iter_fields(sp.SCHEMA)]
        self.assertEqual(sorted(k for _, keys in self.ui.STATION_GROUPS for k in keys), sorted(station_keys))

    def test_wreck_and_station_operators(self):
        scene = bpy.context.scene
        scene.shipgen.seed = 3
        scene.shipgen_wreck.breaks = 1
        bpy.ops.shipgen.wreck_generate()
        root = bpy.data.objects["Wreck"]
        self.assertEqual(root["shipgen_wreck"]["stats"]["segments"], 2)
        scene.shipgen_station.size = "small"
        bpy.ops.shipgen.station_generate()
        self.assertIn("shipgen_station", bpy.data.objects["Station"])
        with tempfile.TemporaryDirectory() as tmp:
            scene.shipgen_wreck.export_dir = tmp
            scene.shipgen_station.export_dir = tmp
            bpy.ops.shipgen.wreck_export()
            bpy.ops.shipgen.station_export()
            bpy.ops.shipgen.station_kit()
            bpy.ops.shipgen.station_export()
            files = sorted(os.listdir(tmp))
        self.assertIn("station_kit.glb", files)
        self.assertTrue(any(f.startswith("station_") and f.endswith(".glb") and f != "station_kit.glb" for f in files))
        self.assertTrue(any(f.startswith("wreck_") and f.endswith(".glb") for f in files))

    def test_ship_operators_still_work(self):
        bpy.ops.shipgen.load_preset(filepath=os.path.join(ROOT, "presets", "miner_s.json"))
        self.assertEqual(bpy.context.scene.shipgen.mining__type, "drill")
        self.assertIsNotNone(bpy.data.objects.get("Ship"))


if __name__ == "__main__":
    unittest.main()
