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


if __name__ == "__main__":
    unittest.main()
