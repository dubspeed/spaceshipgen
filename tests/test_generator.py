"""Generator tests. Need Blender: run via ``blender -b --factory-startup -P tests/run_blender.py``."""

import os
import random
import unittest

try:
    import bmesh
    import bpy
except ImportError:  # plain Python
    bpy = None

from shipgen import params

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = range(1, 21)


def random_params(seed: int) -> dict:
    """Varied but valid parameters derived from the seed."""
    rng = random.Random(seed)
    p = params.load(os.path.join(ROOT, "presets", "fighter.json")).params
    p["seed"] = seed
    p["class"] = rng.choice(params.SHIP_CLASSES)
    p["symmetry"] = rng.random() > 0.2
    p["max_tris"] = rng.choice([500, 2000, 15000, 60000])
    for key in ("width_ratio", "height_ratio", "taper", "nose_sharpness", "squareness", "variation"):
        spec = params.SCHEMA["hull"][key]
        p["hull"][key] = rng.uniform(spec.min, spec.max)
    p["hull"]["length"] = rng.uniform(4, 120)
    p["hull"]["segments"] = rng.randint(3, 16)
    return params.validate(p).params


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class GeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from shipgen import generator

        cls.generator = generator
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def hull_coords(self, ship):
        return [tuple(round(c, 6) for c in v.co) for v in ship.parts[0].data.vertices]

    def test_many_seeds(self):
        for seed in SEEDS:
            p = random_params(seed)
            with self.subTest(seed=seed, cls=p["class"]):
                ship = self.generator.generate(p)
                stats = ship.stats()
                self.assertEqual(ship.warnings, [])

                # triangle budget
                self.assertGreater(stats["tris"], 0)
                self.assertLessEqual(stats["tris"], p["max_tris"])

                # bounding box plausible: length along Y, sane width and height
                dx, dy, dz = stats["dimensions"]
                length = p["hull"]["length"]
                self.assertAlmostEqual(dy, length, delta=length * 0.01)
                self.assertGreater(dx, 0.02 * length)
                self.assertLess(dx, 1.6 * length)
                self.assertGreater(dz, 0.01 * length)
                self.assertLess(dz, 1.6 * length)
                for lo, hi in zip(stats["bbox_min"], stats["bbox_max"]):
                    self.assertLess(abs(lo + hi) / 2, length)  # roughly centred

                # closed, consistent mesh
                bm = bmesh.new()
                bm.from_mesh(ship.parts[0].data)
                self.assertTrue(all(e.is_manifold for e in bm.edges), "hull has open/non-manifold edges")
                self.assertFalse(any(f.calc_area() <= 0 for f in bm.faces), "degenerate faces")
                bm.free()

                if p["symmetry"]:
                    xs = sorted(round(v.co.x, 4) for v in ship.parts[0].data.vertices)
                    self.assertEqual(xs, sorted(-x + 0.0 for x in xs), "hull not mirror symmetric")

    def test_same_seed_same_ship(self):
        p = random_params(5)
        a = self.hull_coords(self.generator.generate(p))
        b = self.hull_coords(self.generator.generate(p))
        self.assertEqual(a, b)

    def test_different_seed_different_ship(self):
        p = params.defaults()
        a = self.hull_coords(self.generator.generate(dict(p, seed=1)))
        b = self.hull_coords(self.generator.generate(dict(p, seed=2)))
        self.assertNotEqual(a, b)

    def test_regenerate_replaces_previous_ship(self):
        for seed in (1, 2, 3):
            self.generator.generate(dict(params.defaults(), seed=seed))
        self.assertEqual(len(bpy.data.collections["ShipGen"].objects), 2)  # root + hull
        self.assertEqual(sum(1 for o in bpy.data.objects if o.name.startswith("Ship_Hull")), 1)
        self.assertEqual(sum(1 for m in bpy.data.meshes if m.name.startswith("Ship_Hull")), 1)

    def test_accepts_raw_params(self):
        ship = self.generator.generate({"hull": {"length": 1e6}, "class": "nope"})
        self.assertEqual(ship.params["hull"]["length"], 200.0)
        self.assertEqual(len(ship.warnings), 2)


class ResolutionTest(unittest.TestCase):
    @unittest.skipIf(bpy is None, "requires Blender (bpy)")
    def test_choose_resolution_respects_budget(self):
        from shipgen.generator.hull import choose_resolution

        for segments in range(3, 17):
            for max_tris in (500, 1000, 15000, 500000):
                budget = int(max_tris * 0.6)
                verts, rings = choose_resolution(segments, budget)
                self.assertLessEqual(2 * verts * rings, budget, (segments, max_tris))


if __name__ == "__main__":
    unittest.main()
