"""Wrecks: closed meshes, colliders that cover the hull segments, every part accounted for."""

import json
import os
import unittest

try:
    import bpy
    import bmesh
except ImportError:
    bpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def preset(name):
    with open(os.path.join(ROOT, "presets", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class WreckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from shipgen import wrecks
        from shipgen.asteroids import geometry

        cls.wrecks, cls.geo = wrecks, geometry
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def check(self, w, length):
        for obj in w.parts:
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            self.assertTrue(all(e.is_manifold for e in bm.edges), obj.name)
            self.assertFalse(any(f.calc_area() <= 1e-9 for f in bm.faces), obj.name)
            bm.free()
            for mat in obj.data.materials:  # the lights are out
                self.assertFalse(mat.name.startswith("ShipGen_Glow"), obj.name)
        for seg in w.segments:  # the ship's hull pieces, clipped: they still cover the plating
            planes = [self.geo.planes([v.co for v in c.data.vertices]) for c in seg.children
                      if c.name.endswith("-convcolonly")]
            self.assertTrue(planes, seg.name)
            hull = [i for i, m in enumerate(seg.data.materials) if m.name.startswith("ShipGen_Hull")]
            for poly in seg.data.polygons:
                if poly.material_index in hull:
                    for i in poly.vertices:
                        p = seg.data.vertices[i].co
                        self.assertTrue(any(self.geo.inside(p, pl, -0.01 * length) for pl in planes), seg.name)

    def test_shop_models(self):
        for name in ("miner_m", "hauler_l", "fighter", "shuttle", "tanker_m"):
            for breaks in (0, 1, 3):
                with self.subTest(name=name, breaks=breaks):
                    w = self.wrecks.generate({"seed": 2, "breaks": breaks, "damage": 0.7, "holes": 8}, preset(name))
                    self.assertEqual(len(w.segments), breaks + 1)
                    self.assertEqual(sum(1 for s in w.segments if s["wreck_segment"]["anchor"]), 1)
                    self.check(w, preset(name)["hull"]["length"])

    def test_parts_accounted_for(self):
        from shipgen import generator

        sp = preset("hauler_m")
        ship = generator.generate(dict(sp, seed=5))
        names = sorted(o.name for o in ship.parts if "shipgen_part" in o)
        w = self.wrecks.generate({"seed": 7, "ship_seed": 5, "damage": 0.8, "breaks": 2}, sp)
        salvage = w.stats["salvage"]
        self.assertEqual(sorted(e["name"] for e in salvage), names)
        self.assertEqual(sum(w.stats["parts"].values()), len(names))
        alive = {o.name for o in w.parts}
        for e in salvage:
            self.assertEqual(e["name"] in alive, e["state"] != "destroyed", e)
            if e["state"] != "destroyed":
                obj = bpy.data.objects[e["name"]]
                self.assertEqual(obj["shipgen_salvage"]["state"], e["state"])
                mounted = e["state"] in ("intact", "damaged")
                self.assertEqual(obj.parent.name.startswith("Hull_"), mounted, e)

    def test_undamaged_wreck_keeps_every_part(self):
        w = self.wrecks.generate({"seed": 1, "damage": 0.0, "breaks": 0, "holes": 0, "debris": 0}, preset("miner_m"))
        self.assertEqual(w.stats["parts"]["destroyed"], 0)
        self.assertEqual(w.stats["parts"]["intact"], sum(w.stats["parts"].values()))
        self.assertEqual(w.stats["debris"], 0)

    def test_deterministic(self):
        a = self.wrecks.generate({"seed": 4, "breaks": 2}, preset("miner_s")).stats
        b = self.wrecks.generate({"seed": 4, "breaks": 2}, preset("miner_s")).stats
        self.assertEqual(a, b)
