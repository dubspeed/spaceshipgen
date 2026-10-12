"""Asteroid generator: chunks that tile their parent down to the minimum size, each with a
convex collider that covers its (roughened) mesh."""

import os
import tempfile
import unittest

try:
    import bpy
    import bmesh
except ImportError:
    bpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class AsteroidTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from shipgen import asteroids

        cls.asteroids = asteroids
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def mesh_info(self, obj):
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        closed = all(e.is_manifold for e in bm.edges)
        degenerate = any(f.calc_area() <= 1e-9 for f in bm.faces)
        vol = abs(bm.calc_volume())
        # convex = the mesh is its own convex hull (what Godot builds from the vertices); face
        # normals of thin slivers are too noisy to test against
        hull = bmesh.new()
        bmesh.ops.convex_hull(hull, input=[hull.verts.new(v.co) for v in bm.verts])
        convex = abs(abs(hull.calc_volume()) - vol) <= 1e-3 * max(vol, 1e-9)
        hull.free()
        bm.free()
        return closed, degenerate, convex, vol

    @staticmethod
    def covers(collider, obj) -> bool:
        """Every vertex of ``obj`` inside the convex ``collider``: adding them to the collider's
        points must not grow its hull (face normals of tiny triangles are too noisy to test)."""
        def hull_volume(points):
            bm = bmesh.new()
            bmesh.ops.convex_hull(bm, input=[bm.verts.new(p) for p in points])
            vol = abs(bm.calc_volume())
            bm.free()
            return vol

        col = [v.co for v in collider.data.vertices]
        base = hull_volume(col)
        return hull_volume(col + [v.co for v in obj.data.vertices]) <= base * (1 + 1e-4)

    def test_every_kind(self):
        for comp in self.asteroids.params.COMPOSITIONS:
            for shape in self.asteroids.params.SHAPES:
                with self.subTest(comp=comp, shape=shape):
                    p = {"composition": comp, "shape": shape, "size_m": 20, "seed": 3, "min_chunk_m": 3.0}
                    rock = self.asteroids.generate(p)
                    self.assertEqual(rock.warnings, [])
                    self.assertGreater(len(rock.parts), 1)
                    for c in rock.chunks:
                        closed, degenerate, _, _ = self.mesh_info(c.obj)
                        self.assertTrue(closed, f"{c.name}: open edges")
                        self.assertFalse(degenerate, f"{c.name}: degenerate faces")
                        self.assertTrue(self.mesh_info(c.collider)[2], f"{c.name}: collider not convex")
                        self.assertTrue(c.collider.name.endswith("-convcolonly"))
                        self.assertIs(c.collider.parent, c.obj)
                        self.assertTrue(self.covers(c.collider, c.obj), f"{c.name}: mesh outside its collider")
                    stats = rock.stats
                    self.assertAlmostEqual(stats["size_m"], 20, delta=0.5)
                    self.assertGreater(stats["yield_m3"], 0)
                    self.assertEqual(stats["cargo"], "fluid_m3" if comp == "ice" else "ore_m3")

    def test_chunks_tile_their_parent_down_to_the_minimum(self):
        p = {"composition": "ore", "size_m": 30, "seed": 5, "min_chunk_m": 4.0, "gap": 0.0, "max_levels": 6,
             "max_tris": 500000, "roughness": 0.0, "craters": 0}  # exact tiling needs the plain cells
        rock = self.asteroids.generate(p)
        for c in rock.chunks:
            size = c.obj["asteroid_chunk"]["size_m"]
            if c.children:
                self.assertGreaterEqual(size, 2 * p["min_chunk_m"] - 1e-6, f"{c.name} split below the minimum")
                parent = self.mesh_info(c.obj)[3]
                kids = sum(self.mesh_info(k.obj)[3] for k in c.children)
                self.assertAlmostEqual(kids / parent, 1.0, delta=0.01, msg=f"{c.name}: children don't fill it")
                for k in c.children:
                    self.assertTrue(k.obj.hide_render, "deeper levels start hidden")
                    self.assertIs(k.obj.parent, c.obj)
            else:
                self.assertLess(size, 2 * p["min_chunk_m"] * 1.8, f"{c.name} big but not split")
        whole = sum(self.mesh_info(c.obj)[3] for c in rock.chunks if c.level == 1)
        self.assertAlmostEqual(rock.stats["volume_m3"], whole, delta=0.01 * whole)

    def test_roughness_keeps_children_close_to_their_parent(self):
        """Sub-chunks share the parent's surface (world-space noise): their volumes add up."""
        rock = self.asteroids.generate({"size_m": 24, "seed": 6, "gap": 0.0})
        for c in rock.chunks:
            if c.children:
                parent = self.mesh_info(c.obj)[3]
                kids = sum(self.mesh_info(k.obj)[3] for k in c.children)
                # the push is capped per chunk (thin chunks must not fold), so small ones differ a bit
                self.assertAlmostEqual(kids / parent, 1.0, delta=0.15, msg=c.name)

    def test_same_seed_same_rock(self):
        a = self.asteroids.generate({"seed": 9}).stats
        b = self.asteroids.generate({"seed": 9}).stats
        c = self.asteroids.generate({"seed": 10}).stats
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_triangle_budget_drops_levels(self):
        rock = self.asteroids.generate({"size_m": 60, "min_chunk_m": 2.0, "max_tris": 3000, "seed": 2})
        tris = sum(len(poly.vertices) - 2 for c in rock.chunks for poly in c.obj.data.polygons)
        self.assertLessEqual(tris, 3000)
        self.assertTrue(any("max_levels" in w for w in rock.warnings))

    def test_glb_has_every_level_with_extras(self):
        from shipgen import export

        rock = self.asteroids.generate({"seed": 4, "size_m": 16})
        expected = [n for c in rock.chunks for n in (c.obj.name, c.collider.name)]
        stats = rock.stats
        with tempfile.TemporaryDirectory() as tmp:
            path = export.export_glb(rock, os.path.join(tmp, "rock.glb"))
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.ops.import_scene.gltf(filepath=path)
            names = {o.name for o in bpy.data.objects}
            for name in expected:
                self.assertIn(name, names)
            imported = bpy.data.objects["Asteroid"]
            imported_stats = imported["shipgen_asteroid"].to_dict()["stats"]
            self.assertEqual(imported_stats["chunks_per_level"], stats["chunks_per_level"])

    def test_presets_generate_cleanly(self):
        folder = os.path.join(ROOT, "presets", "asteroids")
        for name in sorted(os.listdir(folder)):
            with self.subTest(preset=name):
                checked = self.asteroids.params.load(os.path.join(folder, name))
                self.assertEqual(checked.warnings, [])
                self.assertEqual(self.asteroids.generate(checked.params).warnings, [])


if __name__ == "__main__":
    unittest.main()
