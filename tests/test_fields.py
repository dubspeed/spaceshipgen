"""Asteroid fields: rocks from a few prefabs, no overlaps, zones, manifest = what the .glb holds."""

import json
import math
import os
import struct
import tempfile
import unittest

try:
    import bpy
    from mathutils import Quaternion, Vector
except ImportError:
    bpy = None


def read_glb_json(path):
    with open(path, "rb") as f:
        data = f.read()
    return json.loads(data[20:20 + struct.unpack("<I", data[12:16])[0]])


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class FieldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from shipgen import fields

        cls.fields = fields
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_shapes(self):
        for shape in self.fields.params.SHAPES:
            with self.subTest(shape=shape):
                f = self.fields.generate({"shape": shape, "seed": 4, "count": 60})
                self.assertEqual(len(f.parts), len(f.placements))
                self.assertGreater(len(f.parts), 50)
                gap = f.params["gap_m"]
                pls = f.placements
                for i, a in enumerate(pls):  # nominal spheres never overlap
                    for b in pls[i + 1:]:
                        d = (a.position - b.position).length
                        self.assertGreaterEqual(d, 0.5 * (a.prefab.size_m + b.prefab.size_m) + gap - 1e-6)
                lo, hi = f.params["min_size_m"], f.params["max_size_m"]
                for pf in f.prefabs:
                    self.assertTrue(lo - 1e-6 <= pf.size_m <= hi + 1e-6)
                meshes = {o.data.name for o in f.parts}
                self.assertEqual(len(meshes), len(f.prefabs))  # placements share their prefab's mesh
                self.assertTrue(all(c.data is f.prefabs[0].collider or c.name.endswith("-convcolonly")
                                    for c in f.colliders))
                zs = [pl.position.z for pl in pls]
                self.assertLess(max(zs) - min(zs), 0.5 * f.params["size_m"])  # flat

    def test_zones(self):
        f = self.fields.generate({"shape": "belt", "seed": 2, "zoned": 1.0, "clumping": 0.0, "count": 80,
                                  "ore": 0.5, "metal": 0.0, "ice": 0.5})
        x = {c: [pl.position.x for pl in f.placements if pl.prefab.composition == c] for c in ("ore", "ice")}
        self.assertTrue(x["ore"] and x["ice"])
        self.assertLess(max(x["ore"]), min(x["ice"]) + 1e-6)  # ore at one end, ice at the other

    def test_size_bias(self):
        many_small = self.fields.generate({"seed": 3, "size_bias": 4.0, "count": 60})
        even = self.fields.generate({"seed": 3, "size_bias": 0.0, "count": 60})

        def mean(f):
            return sum(pl.prefab.size_m for pl in f.placements) / len(f.placements)

        self.assertLess(mean(many_small), mean(even))

    def test_export_and_manifest(self):
        from shipgen import export

        f = self.fields.generate({"seed": 6, "count": 20, "prefabs": 4})
        with tempfile.TemporaryDirectory() as tmp:
            path = export.export_glb(f, os.path.join(tmp, "f.glb"))
            prefabs = self.fields.export_prefabs(f, tmp, "f")
            gltf = read_glb_json(path)
            self.assertEqual(len(prefabs), len(f.prefabs))
            for p in prefabs:
                self.assertTrue(os.path.isfile(p))
                rock = read_glb_json(p)
                self.assertTrue(any(n["name"].startswith("Chunk_") for n in rock["nodes"]))
        man = self.fields.manifest(f, "f")
        nodes = {n["name"]: n for n in gltf["nodes"]}
        self.assertEqual(len(gltf["meshes"]), 2 * len(f.prefabs))  # preview + collider, shared
        for rock in man["rocks"]:
            node = nodes[rock["name"]]
            self.assertEqual(node["extras"]["asteroid_instance"]["prefab"], rock["prefab"])
            for a, b in zip(node["translation"], rock["position"]):
                self.assertAlmostEqual(a, b, places=3)
            q1 = Quaternion((node["rotation"][3], *node["rotation"][:3]))
            q2 = Quaternion((rock["rotation"][3], *rock["rotation"][:3]))
            self.assertGreater(abs(q1.dot(q2)), 0.9999)
        self.assertEqual(man["axes"], "godot")
        total = sum(f.prefabs[[pf.name for pf in f.prefabs].index(r["prefab"])].stats["yield_m3"]
                    for r in man["rocks"])
        self.assertAlmostEqual(total, sum(f.stats["yield"].values()), delta=0.5)

    def test_leaves_the_asteroid_panel_alone(self):
        from shipgen import asteroids

        rock = asteroids.generate({"seed": 1, "size_m": 10})
        name = rock.root.name
        self.fields.generate({"seed": 1, "count": 10})
        self.assertIn(name, bpy.data.objects)
        self.assertTrue(math.isfinite(bpy.data.objects[name].location.x))
