"""FX anchors: where the game attaches particle effects and lights (shipgen/fx.py)."""

import json
import os
import struct
import tempfile
import unittest

try:
    import bpy
    from mathutils import Quaternion, Vector
    from mathutils.bvhtree import BVHTree
except ImportError:
    bpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def preset(name):
    with open(os.path.join(ROOT, "presets", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class FxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from shipgen import fx

        cls.fx = fx
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def kinds(self, objects):
        out = {}
        for o in self.fx.anchors_of(objects):
            self.assertIn(o["shipgen_fx"]["kind"], self.fx.KINDS)
            self.assertIn(f"FX_{o['shipgen_fx']['kind']}_", o.name)  # the name alone tells the kind
            out[o["shipgen_fx"]["kind"]] = out.get(o["shipgen_fx"]["kind"], 0) + 1
        return out

    def test_ships(self):
        from shipgen import generator

        for name in ("miner_m", "fighter", "hauler_l", "shuttle"):
            with self.subTest(name=name):
                ship = generator.generate(preset(name))
                kinds = self.kinds(ship.objects)
                engines = sum(1 for o in ship.parts if o.get("shipgen_role") == "engines")
                self.assertEqual(kinds.get("exhaust", 0), engines)
                self.assertEqual(kinds.get("mining", 0), sum(1 for o in ship.parts if o.name == "Rig_0"))
                self.assertGreaterEqual(kinds["rcs"], 8)
                lights = [o["shipgen_fx"]["color"] for o in ship.fx_objects if o["shipgen_fx"]["kind"] == "nav_light"]
                self.assertEqual(sorted(lights), ["green", "red", "white"])
                # attitude thrusters sit on the hull surface
                bpy.context.view_layer.update()
                hull = next(o for o in ship.parts if o.name == "Ship_Hull")
                tree = BVHTree.FromObject(hull, bpy.context.evaluated_depsgraph_get())
                beam = 0.5 * ship.params["hull"]["length"] * ship.params["hull"]["width_ratio"]
                for o in ship.fx_objects:
                    if o["shipgen_fx"]["kind"] == "rcs":
                        _, _, _, dist = tree.find_nearest(o.matrix_world.translation)
                        self.assertLess(dist, 0.2 * beam, o.name)

    def test_exhaust_points_backwards_in_godot(self):
        from shipgen import export, generator

        ship = generator.generate(preset("hauler_m"))
        with tempfile.TemporaryDirectory() as tmp:
            path = export.export_glb(ship, os.path.join(tmp, "s.glb"))
            with open(path, "rb") as f:
                data = f.read()
        gltf = json.loads(data[20:20 + struct.unpack("<I", data[12:16])[0]])
        exhausts = [n for n in gltf["nodes"] if n["name"].startswith("FX_exhaust_")]
        self.assertTrue(exhausts)
        for n in exhausts:
            self.assertEqual(n["extras"]["shipgen_fx"]["kind"], "exhaust")
            x, y, z, w = n.get("rotation", [0, 0, 0, 1])
            emit = Quaternion((w, x, y, z)) @ Vector((0, 0, -1))  # an anchor emits along its -Z
            self.assertGreater(emit.z, 0.99, n["name"])  # Godot: nose -Z, exhaust out of the back

    def test_wreck(self):
        from shipgen import wrecks

        w = wrecks.generate({"seed": 2, "breaks": 2, "damage": 0.8, "holes": 6}, preset("miner_m"))
        kinds = self.kinds(w.objects)
        self.assertFalse({"exhaust", "rcs", "nav_light", "mining"} & set(kinds))  # dead
        self.assertGreater(kinds["spark"], 0)
        self.assertGreater(kinds["smoke"], 0)
        alive = {o.name for o in w.objects}
        for o in w.fx_objects:
            self.assertIn(o.parent.name, alive)

    def test_station(self):
        from shipgen import stations

        st = stations.generate({"seed": 3, "role": "mining", "size": "medium"})
        kinds = self.kinds(st.objects)
        berths = {e.name for e in st.empties if "station_berth" in e}
        lights = [o["shipgen_fx"]["berth"] for o in st.empties if o.get("shipgen_fx", {}).get("kind") == "berth_light"]
        self.assertEqual(sorted(lights), sorted(berths))
        docks = sum(1 for pl in st.placements if pl.kind.startswith("dock"))
        antennas = sum(1 for pl in st.placements if pl.kind == "antenna")
        self.assertEqual(kinds.get("beacon", 0), docks + antennas)

    def test_asteroids(self):
        from shipgen import asteroids

        ice = asteroids.generate({"composition": "ice", "seed": 3})
        self.assertEqual(self.kinds(ice.objects), {"sublimation": asteroids.ICE_VENTS})
        ore = asteroids.generate({"composition": "ore", "seed": 3})
        self.assertEqual(self.kinds(ore.objects), {})
