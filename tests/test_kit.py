"""Fit checks for the parts-kit prototype: every part fits every hull."""

import itertools
import os
import unittest

try:
    import bpy
    import bmesh
except ImportError:
    bpy = None

from shipgen import params

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mirror_ok(coords, tol=4):
    xs = sorted(round(x, tol) + 0.0 for x, _, _ in coords)
    return xs == sorted(-x + 0.0 for x in xs)


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class EngineDesignTest(unittest.TestCase):
    def test_designs_honour_the_unit_contract(self):
        from shipgen.kit import engine_designs as ed

        for i, name in enumerate(ed.NAMES):
            with self.subTest(design=name):
                bm = bmesh.new()
                ed.build(bm, i, (0, 0, 0), (0, -1, 0), 1.0)  # thrust along -Y, like a tail socket
                self.assertTrue(all(e.is_manifold for e in bm.edges), "open edges")
                self.assertFalse(any(f.calc_area() <= 1e-9 for f in bm.faces), "degenerate faces")
                for v in bm.verts:
                    x, y, z = v.co
                    self.assertLessEqual((x * x + z * z) ** 0.5, 1.0 + 1e-6, "wider than the socket")
                    self.assertGreaterEqual(y, -ed.MAX_LENGTH - 1e-6, "longer than allowed")
                    self.assertLessEqual(y, ed.EMBED + 1e-6, "reaches too deep into the hull")
                self.assertTrue(_mirror_ok([v.co for v in bm.verts]), "not mirror symmetric")
                self.assertTrue(any(f.material_index == ed.GLOW for f in bm.faces), "no nozzle glow")
                bm.free()


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class KitShipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from shipgen import kit

        cls.kit = kit
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cls.base = dict(params.load(os.path.join(ROOT, "presets", "miner_m.json")).params, spread=0)

    def check_ship(self, ship):
        for part in ship.parts:
            bm = bmesh.new()
            bm.from_mesh(part.data)
            self.assertTrue(all(e.is_manifold for e in bm.edges), f"{part.name}: open edges")
            self.assertFalse(any(f.calc_area() <= 1e-9 for f in bm.faces), f"{part.name}: degenerate faces")
            bm.free()
            self.assertTrue(_mirror_ok([v.co for v in part.data.vertices]), f"{part.name} not symmetric")
        engines = [s for s in ship.sockets if s.kind == "engine"]
        for a, b in itertools.combinations(engines, 2):
            gap = ((a.pos.x - b.pos.x) ** 2 + (a.pos.z - b.pos.z) ** 2) ** 0.5
            self.assertGreaterEqual(gap, a.radius + b.radius - 1e-6, "engine sockets overlap")

    def test_every_hull_combination(self):
        from shipgen.kit import hull_kit as hk

        for plan, tail, mid, nose in itertools.product(hk.PLANS, hk.TAILS, hk.MIDS, hk.NOSES):
            with self.subTest(design=f"{plan}/{tail}/{mid}/{nose}"):
                self.check_ship(self.kit.build(self.base, plan=plan, tail=tail, mid=mid, nose=nose))

    def test_every_engine_on_every_tail(self):
        from shipgen.kit import engine_designs as ed
        from shipgen.kit import hull_kit as hk

        for tail, design in itertools.product(hk.TAILS, range(len(ed.DESIGNS))):
            for count, size in ((1, 2.0), (2, 2.6), (4, 1.5), (6, 1.0), (2, 6.0)):
                with self.subTest(tail=tail, design=ed.NAMES[design], count=count, size=size):
                    p = dict(self.base, engines=dict(self.base["engines"], count=count, size=size))
                    ship = self.kit.build(p, plan="mono", tail=tail, mid="straight", nose="blunt",
                                          engine_design=design)
                    self.check_ship(ship)
                    self.assertEqual(sum(s.kind == "engine" for s in ship.sockets), count)

    def test_oversized_engines_move_outboard_instead_of_overhanging(self):
        p = dict(self.base, engines=dict(self.base["engines"], count=2, size=8.0))
        ship = self.kit.build(p, plan="mono", tail="flat", mid="straight", nose="blunt")
        tail_w = max(abs(v.co.x) for v in ship.parts[0].data.vertices if v.co.y < -0.49 * p["hull"]["length"])
        for s in (s for s in ship.sockets if s.kind == "engine"):
            self.assertGreaterEqual(abs(s.pos.x) - s.radius, tail_w - 1e-6, "engine overlaps the tail face")
        self.assertEqual(ship.warnings, [])

    def test_designs_vary_by_seed_within_the_class_kit(self):
        from shipgen.kit import hull_kit as hk

        labels = {self.kit.build(dict(self.base, seed=s)).design.label() for s in range(1, 13)}
        self.assertGreaterEqual(len(labels), 6, labels)
        kit = hk.CLASS_KIT["miner"]
        for label in labels:
            plan, tail, mid, nose = label.split("/")
            self.assertIn(plan, kit["plans"])
            self.assertIn(tail, kit["tails"])

    def test_rigs_and_modules_fit_every_hull_without_collisions(self):
        """Stress loadout on every hull: nothing may collide, nothing may be dropped (regression:
        the fork socket used to be wider than the gap between its prongs)."""
        from shipgen.kit import hull_kit as hk

        for i, (plan, tail, mid, nose) in enumerate(itertools.product(hk.PLANS, hk.TAILS, hk.MIDS, hk.NOSES)):
            rig = ("drill", "laser", "claw", "scoop")[i % 4]
            cargo = ("containers", "hoppers", "tanks", "habitat")[(i // 4) % 4]
            p = dict(self.base, mining=dict(self.base["mining"], type=rig, size=1.0),
                     cargo=dict(self.base["cargo"], type=cargo, modules=12, size=0.8))
            with self.subTest(design=f"{plan}/{tail}/{mid}/{nose}", rig=rig, cargo=cargo):
                ship = self.kit.build(p, plan=plan, tail=tail, mid=mid, nose=nose)
                self.assertEqual(ship.conflicts, [])
                self.assertFalse([w for w in ship.warnings if "collided" in w], ship.warnings)
                pointed = plan == "mono" and hk.NOSES[nose].keys[-1][1] == 0  # no mount face: no rig
                self.assertEqual(ship.loadout["rig"] == "none", pointed, ship.warnings)
                self.check_ship(ship)

    def test_wings_on_every_mono_hull(self):
        """X-wings + fin + side modules on every mono hull: closed, symmetric, nothing left colliding."""
        from shipgen.kit import hull_kit as hk

        fighter = dict(params.load(os.path.join(ROOT, "presets", "fighter.json")).params, spread=0)
        for wing_type, count in (("delta", 3), ("swept", 4), ("straight", 2), ("forward_swept", 5)):
            for tail, mid, nose in itertools.product(hk.TAILS, hk.MIDS, hk.NOSES):
                p = dict(fighter, wings=dict(fighter["wings"], type=wing_type, count=count),
                         cargo={"type": "containers", "modules": 4, "size": 0.5})
                with self.subTest(wings=f"{wing_type}x{count}", design=f"mono/{tail}/{mid}/{nose}"):
                    ship = self.kit.build(p, plan="mono", tail=tail, mid=mid, nose=nose)
                    self.assertEqual(self.kit.find_conflicts_after(ship), [])
                    self.check_ship(ship)

    def test_greebles(self):
        """Greebles: density controls them, they never touch other parts and add no mass."""
        counts = []
        for density in (0.0, 0.4, 1.0):
            p = dict(self.base, greeble_density=density)
            ship = self.kit.build(p, plan="mono", tail="flat", mid="straight", nose="blunt")
            greebles = [i for i in ship.instances if i.kind == "greeble" and i.verts]
            counts.append(len(greebles))
            self.assertEqual(self.kit.find_conflicts_after(ship), [])
            self.check_ship(ship)
            if density == 0.0:
                bare = ship.gameplay
        self.assertEqual(counts[0], 0)
        self.assertLess(counts[1], counts[2])
        self.assertEqual(ship.gameplay["mass_t"], bare["mass_t"])  # look only

    def test_combat_silhouettes_stay_distinct(self):
        """Top view: winged fighters/interceptors stay darts, freighters stay bricks."""
        from shipgen import generator

        def fill(preset, seed):
            p = dict(params.load(os.path.join(ROOT, "presets", f"{preset}.json")).params, seed=seed)
            return generator.generate(p).stats()["top_view"]["fill"]

        for seed in range(1, 5):
            with self.subTest(seed=seed):
                self.assertLess(fill("fighter", seed), 0.6)
                self.assertLess(fill("interceptor", seed), 0.55)
                self.assertGreater(fill("hauler_m", seed), fill("fighter", seed) + 0.1)

    def test_part_designs_vary_with_the_seed(self):
        loadouts = {tuple(self.kit.build(dict(self.base, seed=s)).loadout.values()) for s in range(1, 13)}
        self.assertGreaterEqual(len(loadouts), 5, loadouts)

    def test_sockets_are_exported_for_godot(self):
        import json
        import struct
        import tempfile

        from shipgen import export

        ship = self.kit.build(self.base, plan="mono", tail="flat", mid="straight", nose="blunt")
        with tempfile.TemporaryDirectory() as tmp:
            path = export.export_glb(ship, os.path.join(tmp, "kit.glb"))
            with open(path, "rb") as f:
                f.read(12)
                n, _ = struct.unpack("<II", f.read(8))
                gltf = json.loads(f.read(n))
        sockets = [n for n in gltf["nodes"] if n["name"].startswith("Socket_")]
        self.assertEqual(len(sockets), len(ship.sockets))
        self.assertTrue(all("shipgen_socket" in n.get("extras", {}) for n in sockets))


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class KitStatsTest(unittest.TestCase):
    """The seed changes the look, not the stats: a model's ships stay comparable in the shop."""

    KEYS = ("mass_t", "acceleration_ms2", "hull_hp")

    @classmethod
    def setUpClass(cls):
        from shipgen import generator

        cls.generator = generator
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def model(self, name, **changes):
        return dict(params.load(os.path.join(ROOT, "presets", f"{name}.json")).params, **changes)

    def values(self, g):
        cargo = max(g["cargo"]["general_m3"], g["cargo"]["ore_m3"], g["cargo"]["fluid_m3"], g["cargo"]["passengers"])
        return {**{k: g[k] for k in self.KEYS}, "cargo": cargo, "mining": g["mining"]["power"]}

    def spread_of(self, name, seeds, **changes):
        rows = [self.values(self.generator.generate(self.model(name, seed=s, **changes)).gameplay) for s in seeds]
        out = {}
        for key in rows[0]:
            vals = [r[key] for r in rows]
            mean = sum(vals) / len(vals)
            out[key] = 0.0 if mean == 0 else max(abs(v / mean - 1) for v in vals)
        return out

    def test_design_choice_hardly_moves_stats(self):
        for name in ("miner_m", "hauler_m", "tanker_m"):
            for key, dev in self.spread_of(name, range(1, 9), spread=0).items():
                with self.subTest(model=name, stat=key):
                    self.assertLess(dev, 0.08, f"{name} {key} varies {dev:.0%} with the design alone")

    def test_manufacturing_spread_stays_slight(self):
        for name in ("miner_m", "hauler_m"):
            for key, dev in self.spread_of(name, range(1, 9)).items():
                with self.subTest(model=name, stat=key):
                    self.assertLess(dev, 0.2, f"{name} {key} varies {dev:.0%}")

    def test_models_keep_their_order(self):
        """Bigger models stay bigger, whatever the seed."""
        for small, big, key in (("miner_s", "miner_m", "mining"), ("miner_m", "miner_l", "mining"),
                                ("hauler_s", "hauler_m", "cargo"), ("hauler_m", "hauler_l", "cargo")):
            for seed in range(1, 5):
                a = self.values(self.generator.generate(self.model(small, seed=seed)).gameplay)[key]
                b = self.values(self.generator.generate(self.model(big, seed=seed)).gameplay)[key]
                with self.subTest(small=small, big=big, seed=seed):
                    self.assertLess(a, b)

    def test_mining_calibration(self):
        from shipgen import kit
        from shipgen.kit import rig_designs

        for kind in ("drill", "laser", "claw", "scoop"):
            powers = []
            for design in rig_designs.designs_of(kind):
                p = self.model("miner_m", spread=0, mining={"type": kind, "count": 2, "size": 0.5})
                ship = kit.build(p, plan="mono", tail="flat", mid="straight", nose="blunt", rig_design=design)
                powers.append(ship.gameplay["mining"]["power"])
            with self.subTest(kind=kind, powers=powers):
                self.assertAlmostEqual(sum(powers) / len(powers), 100, delta=10)
                self.assertLess(max(powers) / min(powers), 1.05, "designs of one kind should mine alike")

    def test_params_kit_choices_are_used(self):
        p = self.model("hauler_m", kit={"plan": "twin", "tail": "flare", "mid": "straight", "nose": "blunt",
                                        "engine_design": 3, "rig_design": -1, "module_design": 1})
        ship = self.generator.generate(p)
        self.assertEqual(ship.design.label(), "twin/flare/straight/blunt")
        self.assertEqual(ship.loadout["engine"], "block")
        self.assertEqual(ship.loadout["module"], "ribbed_container")

    def test_fixed_design_of_the_wrong_kind_is_ignored(self):
        p = self.model("miner_m", kit=dict(params.defaults()["kit"], rig_design=1))  # 1 = a drill, model mines by laser
        ship = self.generator.generate(p)
        self.assertTrue(ship.loadout["rig"].startswith("laser"), ship.loadout)
        self.assertTrue(any("not a laser rig" in w for w in ship.warnings), ship.warnings)

    def test_triangle_budget(self):
        p = self.model("hauler_m", max_tris=1200, cargo={"type": "tanks", "modules": 12, "size": 0.8})
        ship = self.generator.generate(p)
        self.assertLessEqual(ship.stats()["tris"], 1200)
        self.assertTrue(any("max_tris" in w for w in ship.warnings), ship.warnings)

    def test_stats_reach_the_glb(self):
        import json
        import struct
        import tempfile

        from shipgen import export

        ship = self.generator.generate(self.model("miner_m"))
        with tempfile.TemporaryDirectory() as tmp:
            path = export.export_glb(ship, os.path.join(tmp, "ship.glb"))
            with open(path, "rb") as f:
                f.read(12)
                n, _ = struct.unpack("<II", f.read(8))
                gltf = json.loads(f.read(n))
        root = next(node for node in gltf["nodes"] if node["name"] == "Ship")
        self.assertEqual(root["extras"]["shipgen"]["stats"], json.loads(json.dumps(ship.gameplay)))
        self.assertGreater(root["extras"]["shipgen"]["stats"]["mining"]["power"], 0)


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class GodotColliderTest(unittest.TestCase):
    """Convex collision shapes: convex, gap-free cover of the visible ship, Godot naming."""

    @classmethod
    def setUpClass(cls):
        from shipgen import kit

        cls.kit = kit
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cls.base = dict(params.load(os.path.join(ROOT, "presets", "miner_m.json")).params, spread=0)

    @staticmethod
    def planes(obj):
        mesh = obj.data
        return [(p.normal.copy(), mesh.vertices[p.vertices[0]].co.copy()) for p in mesh.polygons]

    def check(self, ship):
        self.assertTrue(ship.colliders)
        self.assertLessEqual(len(ship.colliders), 40, "too many shapes for a game object")
        length = ship.params["hull"]["length"]
        eps = 1e-3 * length
        hulls = []
        for col in ship.colliders:
            self.assertTrue(col.name.endswith("-convcolonly"), col.name)
            self.assertTrue(col.hide_render)
            planes = self.planes(col)
            for v in col.data.vertices:  # convex: no vertex in front of any face
                self.assertTrue(all(n.dot(v.co - o) <= eps for n, o in planes), f"{col.name} is not convex")
            hulls.append(planes)
        for part in ship.parts:
            if part["shipgen_role"] == "greebles":  # decoration: deliberately without colliders
                continue
            for v in part.data.vertices:
                inside = any(all(n.dot(v.co - o) <= eps for n, o in planes) for planes in hulls)
                self.assertTrue(inside, f"{part.name} vertex {tuple(v.co)} outside every collider")

    def test_colliders_cover_every_hull_combination(self):
        from shipgen.kit import hull_kit as hk

        for i, (plan, tail, mid, nose) in enumerate(itertools.product(hk.PLANS, hk.TAILS, hk.MIDS, hk.NOSES)):
            if i % 3:  # every third combination keeps the test fast; all blocks still appear
                continue
            with self.subTest(design=f"{plan}/{tail}/{mid}/{nose}"):
                self.check(self.kit.build(self.base, plan=plan, tail=tail, mid=mid, nose=nose))

    def test_waist_is_not_one_big_box(self):
        """Concave shapes must be split: a waisted hull needs more than one hull collider."""
        ship = self.kit.build(self.base, plan="mono", tail="flat", mid="waist", nose="blunt")
        straight = self.kit.build(self.base, plan="mono", tail="flat", mid="straight", nose="blunt")
        n_parts = len([i for i in ship.instances if i.verts])
        self.assertGreater(len(ship.colliders) - n_parts, len(straight.colliders) - n_parts)

    def test_colliders_are_exported(self):
        import json
        import struct
        import tempfile

        from shipgen import export

        ship = self.kit.build(self.base)
        with tempfile.TemporaryDirectory() as tmp:
            path = export.export_glb(ship, os.path.join(tmp, "kit.glb"))
            with open(path, "rb") as f:
                f.read(12)
                n, _ = struct.unpack("<II", f.read(8))
                gltf = json.loads(f.read(n))
        names = [n["name"] for n in gltf["nodes"] if n["name"].endswith("-convcolonly")]
        self.assertEqual(len(names), len(ship.colliders))
        self.assertLess(ship.stats()["tris"], 10_000)  # colliders don't count as ship geometry


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class CollisionCheckTest(unittest.TestCase):
    """The checker itself: it must see real overlaps and drop the right part."""

    def setUp(self):
        from mathutils import Vector

        from shipgen import kit
        from shipgen.kit import module_designs, rig_designs
        from shipgen.kit.hull_kit import Socket

        self.kit, self.Vector = kit, Vector
        self.bm = bmesh.new()
        self.instances = []

        def place(kind, group, builder, pos, normal, radius):
            sk = Socket(kind, Vector(pos), Vector(normal), radius, group)
            before = set(self.bm.verts)
            builder(self.bm, 0, sk.pos, sk.normal, radius)
            self.instances.append(kit.Instance(kind, group, group, [v for v in self.bm.verts if v not in before], sk))

        self.place, self.module_designs, self.rig_designs = place, module_designs, rig_designs

    def tearDown(self):
        self.bm.free()

    def test_detects_overlap_and_drops_the_lower_priority_part(self):
        # a module mounted right in front of the rig: it sticks into the rig's space
        self.place("rig", "rig", self.rig_designs.build, (0, 0, 0), (0, 1, 0), 1.0)
        self.place("module", "modules_0", self.module_designs.build, (-0.5, 1.0, 0), (1, 0, 0), 0.6)
        self.assertIn(("module", "rig"), self.kit.find_conflicts(self.instances, []))
        dropped = self.kit.resolve_conflicts(self.bm, self.instances, [])
        self.assertEqual(dropped, ["modules_0"])
        self.assertEqual(self.kit.find_conflicts(self.instances, []), [])

    def test_separate_parts_do_not_conflict(self):
        self.place("rig", "rig", self.rig_designs.build, (0, 0, 0), (0, 1, 0), 1.0)
        self.place("module", "modules_0", self.module_designs.build, (3.0, -4.0, 0), (1, 0, 0), 0.6)
        self.assertEqual(self.kit.find_conflicts(self.instances, []), [])

    def test_obstacles_only_apply_to_their_kinds(self):
        from shipgen.kit import Box

        self.place("rig", "rig", self.rig_designs.build, (0, 0, 0), (0, 1, 0), 1.0)
        prong = Box("prong", self.Vector((-0.3, 0.5, -0.3)), self.Vector((0.3, 1.5, 0.3)), {"module"})
        self.assertEqual(self.kit.find_conflicts(self.instances, [prong]), [])
        prong.applies_to = {"rig"}
        self.assertEqual(self.kit.find_conflicts(self.instances, [prong]), [("rig", "prong")])


if __name__ == "__main__":
    unittest.main()
