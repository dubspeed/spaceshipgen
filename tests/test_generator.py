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
    p["hull"]["length"] = length = rng.uniform(4, 120)
    p["hull"]["segments"] = rng.randint(3, 16)
    p["wings"] = {
        "type": rng.choice(params.WING_TYPES),
        "count": rng.randint(0, 6),
        "span": length * rng.uniform(0.0, 1.5),
        "sweep_deg": rng.uniform(-45, 75),
    }
    p["engines"]["count"] = rng.randint(0, 8)
    p["engines"]["size"] = length * rng.uniform(0.03, 0.2)
    return params.validate(p).params


def silhouette_params(cls: str, seed: int) -> dict:
    p = params.load(os.path.join(ROOT, "presets", f"{cls}.json")).params
    p["seed"] = seed
    return p


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

                # hull spans exactly the hull length; the whole ship stays plausible
                hull = ship.parts[0]
                length = p["hull"]["length"]
                self.assertAlmostEqual(hull.dimensions.y, length, delta=length * 0.001)
                dx, dy, dz = stats["dimensions"]
                self.assertGreater(dx, 0.02 * length)
                self.assertLess(dx, 3.0 * length)
                self.assertLess(dy, 1.6 * length)
                self.assertGreater(dz, 0.01 * length)
                self.assertLess(dz, 2.0 * length)

                for part in ship.parts:
                    bm = bmesh.new()
                    bm.from_mesh(part.data)
                    self.assertTrue(all(e.is_manifold for e in bm.edges), f"{part.name}: open edges")
                    self.assertFalse(any(f.calc_area() <= 1e-9 for f in bm.faces), f"{part.name}: degenerate faces")
                    bm.free()
                    self.assertFalse(any(poly.use_smooth for poly in part.data.polygons), "expected flat shading")
                    if p["symmetry"]:
                        xs = sorted(round(v.co.x, 4) + 0.0 for v in part.data.vertices)
                        self.assertEqual(xs, sorted(-x + 0.0 for x in xs), f"{part.name} not mirror symmetric")

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
        names = sorted(o.name for o in bpy.data.collections["ShipGen"].objects)
        self.assertEqual(names, ["Ship", "Ship_Engines", "Ship_Hull", "Ship_Wings"])
        self.assertEqual(sorted(o.name for o in bpy.data.objects if o.name.startswith("Ship_")), names[1:])
        self.assertEqual(sorted(m.name for m in bpy.data.meshes), names[1:])

    def test_accepts_raw_params(self):
        ship = self.generator.generate({"hull": {"length": 1e6}, "class": "nope"})
        self.assertEqual(ship.params["hull"]["length"], 200.0)
        self.assertEqual(len(ship.warnings), 2)


    def test_no_wings_no_engines(self):
        p = dict(params.defaults(), wings={"type": "none", "count": 2, "span": 9, "sweep_deg": 0})
        p["engines"] = dict(p["engines"], count=0)
        ship = self.generator.generate(p)
        self.assertEqual([o.name for o in ship.parts], ["Ship_Hull"])

    def test_classes_have_distinct_top_silhouettes(self):
        """Top view: darts (fighter, interceptor) fill little of their bounding box,
        the freighter brick fills most of it."""
        fill = {}
        for cls in ("fighter", "interceptor", "freighter"):
            fill[cls] = [self.generator.generate(silhouette_params(cls, s)).stats()["top_view"]["fill"]
                         for s in range(1, 6)]
        with self.subTest(fill=fill):
            self.assertLess(max(fill["fighter"]), 0.55)
            self.assertLess(max(fill["interceptor"]), 0.45)
            self.assertGreater(min(fill["freighter"]), 0.7)

    def test_low_budget_stays_within_max_tris(self):
        for cls in params.SHIP_CLASSES:
            p = dict(params.defaults(), max_tris=500)
            p["class"] = cls
            p["hull"] = dict(p["hull"], segments=16)
            p["engines"] = dict(p["engines"], count=8)
            p["wings"] = dict(p["wings"], count=6)
            with self.subTest(cls=cls):
                self.assertLessEqual(self.generator.generate(p).stats()["tris"], 500)


if __name__ == "__main__":
    unittest.main()
