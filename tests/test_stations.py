"""Station module kit (grid contract) and generated layouts (no overlaps, ports meet)."""

import itertools
import unittest

try:
    import bpy
    import bmesh
except ImportError:
    bpy = None


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class ModuleKitTest(unittest.TestCase):
    def test_every_design_honours_the_contract(self):
        from mathutils import Vector

        from shipgen.stations import modules

        g, h = modules.GRID, 0.5 * modules.GRID
        for kind, (_, count) in modules.DESIGNS.items():
            for design in range(count):
                with self.subTest(kind=kind, design=design):
                    bm = bmesh.new()
                    m = modules.build(bm, kind, design)
                    self.assertEqual(m.ports[0], ((0, 0, 0), (0, -1, 0)))  # the attaching port
                    self.assertEqual(m.cells[0], (0, 0, 0))
                    self.assertFalse(set(m.cells) & set(m.reserved))
                    cells = [Vector(c) * g for c in m.cells]
                    for v in bm.verts:  # inside its cells
                        self.assertTrue(any(all(abs(v.co[i] - c[i]) <= h + 1e-4 for i in range(3)) for c in cells),
                                        (kind, design, tuple(v.co)))
                    for cell, d in m.ports:  # a flange ends exactly on the cell face
                        face = (Vector(cell) + 0.5 * Vector(d)) * g
                        on_face = [v for v in bm.verts if (v.co - face).dot(Vector(d)) > -1e-4
                                   and (v.co - face).length <= modules.PORT_RADIUS * 1.2]
                        self.assertTrue(on_face, (kind, cell, d))
                    self.assertTrue(m.pieces)
                    self.assertEqual(kind.startswith("dock"), bool(m.berths))
                    bm.free()


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class StationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from shipgen import stations

        cls.stations = stations
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def check_layout(self, placements):
        occupied, reserved = {}, set()
        for pl in placements:
            for c in pl.cells():
                self.assertNotIn(c, occupied, pl.name)
                occupied[c] = pl
            reserved.update(pl.reserved())
        self.assertFalse(reserved & set(occupied))
        ports = {}
        for pl in placements:
            for i, cell, d in pl.ports():
                ports[(cell, d)] = (pl, i)
        for pl in placements:  # every connected port meets an opposite connected port
            for i, cell, d in pl.ports():
                if i in pl.connected:
                    other = tuple(c + k for c, k in zip(cell, d))
                    mate = ports.get((other, tuple(-k for k in d)))
                    self.assertIsNotNone(mate, (pl.name, i))
                    self.assertIn(mate[1], mate[0].connected)

    def test_roles_and_sizes(self):
        from shipgen.stations import params

        for role, size, sym in itertools.product(params.ROLES, params.SIZES, params.SYMMETRIES):
            with self.subTest(role=role, size=size, symmetry=sym):
                st = self.stations.generate({"seed": 3, "role": role, "size": size, "symmetry": sym})
                self.check_layout(st.placements)
                self.assertGreater(sum(st.stats["berths"].values()), 0)
                hubs = sum(1 for pl in st.placements if pl.kind == "hub")
                self.assertEqual(hubs, {"small": 1, "medium": 2, "large": 3}[size])
                names = [o.name for o in st.objects]
                self.assertEqual(len(names), len(set(names)))
                for o in st.parts:
                    bm = bmesh.new()
                    bm.from_mesh(o.data)
                    self.assertTrue(all(e.is_manifold for e in bm.edges), o.name)
                    bm.free()

    def test_berths_face_along_the_pier(self):
        from mathutils import Vector

        st = self.stations.generate({"seed": 5, "role": "trade", "size": "small"})
        bpy.context.view_layer.update()
        berths = [e for e in st.empties if "station_berth" in e]
        self.assertTrue(berths)
        for e in berths:
            dock = e.parent
            nose = e.matrix_world.to_3x3() @ Vector((0, 1, 0))
            pier = dock.matrix_world.to_3x3() @ Vector((0, 1, 0))
            self.assertAlmostEqual(nose.dot(pier), 1.0, places=5)

    def test_kit_has_every_design(self):
        from shipgen.stations import modules

        kit = self.stations.build_kit({})
        self.assertEqual(len(kit.parts), sum(n for _, n in modules.DESIGNS.values()))
        self.assertTrue(all(any(c.name.endswith("-convcolonly") for c in o.children) for o in kit.parts))

    def test_deterministic(self):
        a = [(pl.kind, tuple(pl.origin)) for pl in self.stations.generate({"seed": 9, "size": "large"}).placements]
        b = [(pl.kind, tuple(pl.origin)) for pl in self.stations.generate({"seed": 9, "size": "large"}).placements]
        self.assertEqual(a, b)
