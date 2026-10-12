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
    p["builder"] = "classic"
    p["wings"] = {
        "type": rng.choice(params.WING_TYPES),
        "count": rng.randint(0, 6),
        "span": length * rng.uniform(0.0, 1.5),
        "sweep_deg": rng.uniform(-45, 75),
    }
    p["engines"]["count"] = rng.randint(0, 8)
    p["engines"]["size"] = length * rng.uniform(0.03, 0.2)
    p["mining"] = {"type": rng.choice(params.MINING_TYPES), "count": rng.randint(1, 4), "size": rng.random()}
    p["cargo"] = {"type": rng.choice(params.CARGO_TYPES), "modules": rng.randint(0, 24), "size": rng.random()}
    return params.validate(p).params


def silhouette_params(cls: str, seed: int) -> dict:
    """Preset params for the classic generator (these tests cover it; kit tests are in test_kit)."""
    p = params.load(os.path.join(ROOT, "presets", f"{cls}.json")).params
    p["seed"] = seed
    p["builder"] = "classic"
    return p


def classic_defaults() -> dict:
    return dict(params.defaults(), builder="classic")


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
                self.assertTrue(all("reduced" in w for w in ship.warnings), ship.warnings)

                # triangle budget
                self.assertGreater(stats["tris"], 0)
                self.assertLessEqual(stats["tris"], p["max_tris"])

                # hull spans exactly the hull length; the whole ship stays plausible
                hull = ship.parts[0]
                length = ship.params["hull"]["length"]  # after the seed's spread
                self.assertAlmostEqual(hull.dimensions.y, length, delta=length * 0.001)
                self.assertAlmostEqual(length, p["hull"]["length"], delta=p["hull"]["length"] * p["spread"] + 1e-6)
                dx, dy, dz = stats["dimensions"]
                self.assertGreater(dx, 0.02 * length)
                self.assertLess(dx, 3.0 * length)
                self.assertLess(dy, 2.6 * length)  # rig at the nose + engines at the tail
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
        p = classic_defaults()
        a = self.hull_coords(self.generator.generate(dict(p, seed=1)))
        b = self.hull_coords(self.generator.generate(dict(p, seed=2)))
        self.assertNotEqual(a, b)

    def test_regenerate_replaces_previous_ship(self):
        for seed in (1, 2, 3):
            self.generator.generate(dict(classic_defaults(), seed=seed))
        names = sorted(o.name for o in bpy.data.collections["ShipGen"].objects)
        self.assertEqual(names, ["Ship", "Ship_Engines", "Ship_Hull", "Ship_Wings"])
        self.assertEqual(sorted(o.name for o in bpy.data.objects if o.name.startswith("Ship_")), names[1:])
        self.assertEqual(sorted(m.name for m in bpy.data.meshes), names[1:])

    def test_accepts_raw_params(self):
        ship = self.generator.generate({"hull": {"length": 1e6}, "class": "nope", "spread": 0, "builder": "classic"})
        self.assertEqual(ship.params["hull"]["length"], 200.0)
        self.assertEqual(len(ship.warnings), 2)


    def test_no_wings_no_engines(self):
        p = dict(classic_defaults(), wings={"type": "none", "count": 2, "span": 9, "sweep_deg": 0})
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

    def test_spread_gives_individual_ships_with_similar_stats(self):
        """Seeds of one model differ slightly (manufacturing spread), never wildly."""
        base = silhouette_params("miner_m", 1)
        model = self.generator.generate(dict(base, spread=0)).gameplay
        keys = ("mass_t", "acceleration_ms2", "hull_hp")
        samples = [self.generator.generate(dict(base, seed=s)).gameplay for s in range(1, 9)]
        for key in keys:
            values = [g[key] for g in samples]
            with self.subTest(key=key, values=values):
                self.assertGreater(len(set(values)), 4)  # seeds really differ
                for v in values:
                    self.assertLess(abs(v / model[key] - 1), 0.35)
        ore = [g["cargo"]["ore_m3"] for g in samples]
        power = [g["mining"]["power"] for g in samples]
        self.assertLess(max(ore) / min(ore), 1.6, ore)
        self.assertLess(max(power) / min(power), 1.6, power)

    def test_zero_spread_builds_the_exact_model(self):
        base = dict(silhouette_params("miner_m", 1), spread=0)
        a = self.generator.generate(dict(base, seed=1))
        b = self.generator.generate(dict(base, seed=2))
        self.assertEqual(a.params["hull"], b.params["hull"])
        self.assertEqual(a.gameplay["mining"], b.gameplay["mining"])

    def test_mining_rigs(self):
        base = dict(silhouette_params("miner_m", 1), spread=0)  # calibration is for the exact model
        for kind in ("drill", "laser", "claw", "scoop"):
            p = dict(base, mining=dict(base["mining"], type=kind, count=2, size=0.5))
            with self.subTest(kind=kind):
                ship = self.generator.generate(p)
                self.assertIn("Ship_Mining", [o.name for o in ship.parts])
                mining = ship.gameplay["mining"]
                self.assertEqual(mining["type"], kind)
                self.assertAlmostEqual(mining["power"], 100, delta=15)  # calibrated medium rig
                self.assertGreater(mining["range_m"], 0)

    def test_bigger_rig_mines_more(self):
        base = silhouette_params("miner_m", 1)
        power = [
            self.generator.generate(dict(base, mining=dict(base["mining"], size=size))).gameplay["mining"]["power"]
            for size in (0.2, 0.5, 0.8)
        ]
        self.assertEqual(power, sorted(power))
        self.assertGreater(power[0], 0)

    def test_cargo_types_fill_their_kind(self):
        expected = {"containers": "general_m3", "hoppers": "ore_m3", "tanks": "fluid_m3", "habitat": "passengers"}
        base = silhouette_params("freighter", 1)
        hold_only = self.generator.generate(base).gameplay["cargo"]
        for kind, key in expected.items():
            with self.subTest(kind=kind):
                ship = self.generator.generate(dict(base, cargo={"type": kind, "modules": 6, "size": 0.5}))
                self.assertEqual(ship.warnings, [])
                self.assertGreater(ship.gameplay["cargo"][key], hold_only[key])

    def test_more_modules_more_cargo_but_slower(self):
        base = silhouette_params("hauler_m", 1)
        ships = [
            self.generator.generate(dict(base, cargo=dict(base["cargo"], modules=n))).gameplay for n in (0, 4, 8)
        ]
        cargo = [g["cargo"]["general_m3"] for g in ships]
        accel = [g["acceleration_ms2"] for g in ships]
        self.assertEqual(cargo, sorted(cargo))
        self.assertEqual(accel, sorted(accel, reverse=True))
        self.assertGreater(cargo[2], cargo[0])

    def test_bigger_engines_accelerate_faster(self):
        base = silhouette_params("hauler_m", 1)
        accel = [
            self.generator.generate(dict(base, engines=dict(base["engines"], size=size))).gameplay["acceleration_ms2"]
            for size in (1.5, 3.0, 4.5)
        ]
        self.assertEqual(accel, sorted(accel))

    def test_miner_hold_carries_ore(self):
        cargo = self.generator.generate(silhouette_params("miner_s", 1)).gameplay["cargo"]
        self.assertGreater(cargo["ore_m3"], 0)
        self.assertEqual(cargo["general_m3"], 0)

    def test_too_many_modules_are_reduced_with_warning(self):
        p = silhouette_params("hauler_s", 1)
        p["cargo"] = {"type": "tanks", "modules": 24, "size": 1.0}
        ship = self.generator.generate(p)
        self.assertTrue(any(w.startswith("cargo.modules reduced") for w in ship.warnings), ship.warnings)

    def test_presets_generate_cleanly(self):
        for name in sorted(n for n in os.listdir(os.path.join(ROOT, "presets")) if n.endswith(".json")):
            with self.subTest(preset=name):
                ship = self.generator.generate(params.load(os.path.join(ROOT, "presets", name)).params)
                self.assertEqual(ship.warnings, [])
                self.assertLessEqual(ship.stats()["tris"], ship.params["max_tris"])

    def test_low_budget_stays_within_max_tris(self):
        for cls in params.SHIP_CLASSES:
            p = dict(classic_defaults(), max_tris=500)
            p["class"] = cls
            p["hull"] = dict(p["hull"], segments=16)
            p["engines"] = dict(p["engines"], count=8)
            p["wings"] = dict(p["wings"], count=6)
            p["mining"] = {"type": "claw", "count": 4, "size": 1.0}
            p["cargo"] = {"type": "habitat", "modules": 24, "size": 0.3}
            with self.subTest(cls=cls):
                self.assertLessEqual(self.generator.generate(p).stats()["tris"], 500)


if __name__ == "__main__":
    unittest.main()
