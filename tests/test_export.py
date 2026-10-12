"""Export tests (.glb, .blend, preview .png). Need Blender."""

import json
import os
import struct
import tempfile
import unittest

try:
    import bpy
except ImportError:
    bpy = None

from shipgen import params

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_glb_json(path: str) -> dict:
    with open(path, "rb") as f:
        magic, version, _length = struct.unpack("<4sII", f.read(12))
        assert magic == b"glTF" and version == 2, (magic, version)
        chunk_len, chunk_type = struct.unpack("<II", f.read(8))
        assert chunk_type == 0x4E4F534A  # 'JSON'
        return json.loads(f.read(chunk_len))


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from shipgen import export, generator

        bpy.ops.wm.read_factory_settings(use_empty=True)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.params = params.load(os.path.join(ROOT, "presets", "fighter.json")).params
        cls.params["builder"] = "classic"  # this class covers the classic builder; kit: test_kit
        cls.ship = generator.generate(cls.params)
        cls.tris = cls.ship.stats()["tris"]
        cls.files = export.export_all(
            cls.ship, cls.tmp.name, "fighter", resolution=(160, 90), samples=2
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_files_written(self):
        self.assertEqual(set(self.files), {"glb", "blend", "png", "png_top"})
        for path in self.files.values():
            self.assertTrue(os.path.isfile(path), path)
            self.assertGreater(os.path.getsize(path), 0, path)

    def test_glb_contains_only_the_ship(self):
        gltf = read_glb_json(self.files["glb"])
        names = {n["name"] for n in gltf["nodes"]}
        self.assertEqual(names, {"Ship", "Ship_Hull", "Ship_Wings", "Ship_Engines"})
        self.assertEqual(len(gltf["meshes"]), 3)
        materials = {m["name"]: m for m in gltf["materials"]}
        self.assertEqual(set(materials), {"ShipGen_Hull", "ShipGen_Accent", "ShipGen_Glow"})
        self.assertGreater(max(materials["ShipGen_Glow"]["emissiveFactor"]), 0)
        # triangle count survives the export
        indices = sum(
            gltf["accessors"][prim["indices"]]["count"] for mesh in gltf["meshes"] for prim in mesh["primitives"]
        )
        self.assertEqual(indices // 3, self.tris)

    def test_glb_carries_stats_as_extras(self):
        gltf = read_glb_json(self.files["glb"])
        root = next(n for n in gltf["nodes"] if n["name"] == "Ship")
        extras = root["extras"]["shipgen"]
        self.assertEqual(extras["seed"], self.params["seed"])
        self.assertEqual(extras["stats"], json.loads(json.dumps(self.ship.gameplay)))
        self.assertGreater(extras["stats"]["acceleration_ms2"], 0)

    def test_png(self):
        for key in ("png", "png_top"):
            with open(self.files[key], "rb") as f:
                header = f.read(24)
            self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", header[16:24])
            self.assertEqual((width, height), (160, 90))

    def test_png_is_not_empty_background(self):
        for key in ("png", "png_top"):
            img = bpy.data.images.load(self.files[key])
            try:
                px = list(img.pixels)
            finally:
                bpy.data.images.remove(img)
            lum = [0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2] for i in range(0, len(px), 4)]
            background = lum[0]  # corner pixel
            lit = sum(1 for v in lum if v > background + 0.05)
            self.assertGreater(lit / len(lum), 0.05, f"ship hardly visible in {key}")

    def test_blend_reloads(self):
        with bpy.data.libraries.load(self.files["blend"]) as (src, _dst):
            objects = list(src.objects)
        self.assertIn("Ship", objects)
        self.assertIn("Ship_Hull", objects)
        self.assertIn("ShipGen_Camera", objects)


if __name__ == "__main__":
    unittest.main()


def _rotate(q, v):
    """Rotate vector v by the glTF quaternion q = (x, y, z, w)."""
    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v); v' = v + w * t + cross(q.xyz, t)
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx))


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class GodotAxesTest(unittest.TestCase):
    """The .glb must match Godot: +Y up, -Z forward (nose), +X right. Ship parts carry no node
    rotation; sockets are rotated so that their -Z (Godot's forward) is the socket normal."""

    def export(self, preset, builder):
        from shipgen import export, generator

        p = params.load(os.path.join(ROOT, "presets", preset)).params
        p["spread"] = 0  # exact hull length
        p["builder"] = builder
        ship = generator.generate(p)
        with tempfile.TemporaryDirectory() as tmp:
            path = export.export_glb(ship, os.path.join(tmp, "ship.glb"))
            return p, read_glb_json(path)

    @staticmethod
    def extent(gltf, mesh_name):
        mesh = next(m for m in gltf["meshes"] if m["name"] == mesh_name)
        acc = gltf["accessors"][mesh["primitives"][0]["attributes"]["POSITION"]]
        return acc["min"], acc["max"]

    def check_axes(self, p, gltf, fin_mesh):
        for node in gltf["nodes"]:
            if not node["name"].startswith("Socket_"):
                self.assertNotIn("rotation", node, node["name"])
        half = p["hull"]["length"] / 2
        hull_min, hull_max = self.extent(gltf, "Ship_Hull")
        self.assertAlmostEqual(hull_min[2], -half, places=3)  # nose at -Z
        self.assertAlmostEqual(hull_max[2], half, places=3)
        engines_min, _ = self.extent(gltf, "Ship_Engines")
        self.assertGreater(engines_min[2], 0)  # engines at the back (+Z)
        _, wings_max = self.extent(gltf, fin_mesh)
        self.assertGreater(wings_max[1], hull_max[1])  # tail fin points up (+Y)

    def test_classic_axes(self):
        p, gltf = self.export("interceptor.json", "classic")  # has a tail fin
        self.check_axes(p, gltf, "Ship_Wings")

    def test_kit_axes_and_sockets(self):
        p, gltf = self.export("interceptor.json", "kit")
        self.check_axes(p, gltf, "Ship_Wings")
        expected = {"engine": (0, 0, 1), "nose": (0, 0, -1), "top": (0, 1, 0), "fin": (0, 1, 0)}  # glTF directions
        sockets = [n for n in gltf["nodes"] if n["name"].startswith("Socket_")]
        self.assertTrue(sockets)
        for node in sockets:
            kind = node["extras"]["shipgen_socket"]["kind"]
            forward = _rotate(node.get("rotation", (0, 0, 0, 1)), (0, 0, -1))  # Godot forward
            if kind in expected:
                for got, want in zip(forward, expected[kind]):
                    self.assertAlmostEqual(got, want, places=4, msg=f"{node['name']} faces {forward}")
            if kind == "wing":
                self.assertAlmostEqual(abs(forward[0]), 1.0, places=4, msg=node["name"])
