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
        cls.ship = generator.generate(cls.params)
        cls.tris = cls.ship.stats()["tris"]
        cls.files = export.export_all(
            cls.ship, cls.tmp.name, "fighter", resolution=(160, 90), samples=2
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_files_written(self):
        self.assertEqual(set(self.files), {"glb", "blend", "png"})
        for path in self.files.values():
            self.assertTrue(os.path.isfile(path), path)
            self.assertGreater(os.path.getsize(path), 0, path)

    def test_glb_contains_only_the_ship(self):
        gltf = read_glb_json(self.files["glb"])
        names = {n["name"] for n in gltf["nodes"]}
        self.assertEqual(names, {"Ship", "Ship_Hull"})
        self.assertEqual(len(gltf["meshes"]), 1)
        self.assertEqual(gltf["materials"][0]["name"], "ShipGen_Hull")
        # triangle count survives the export
        prim = gltf["meshes"][0]["primitives"][0]
        indices = gltf["accessors"][prim["indices"]]["count"]
        self.assertEqual(indices // 3, self.tris)

    def test_png(self):
        with open(self.files["png"], "rb") as f:
            header = f.read(24)
        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", header[16:24])
        self.assertEqual((width, height), (160, 90))

    def test_png_is_not_empty_background(self):
        img = bpy.data.images.load(self.files["png"])
        try:
            px = list(img.pixels)
        finally:
            bpy.data.images.remove(img)
        lum = [0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2] for i in range(0, len(px), 4)]
        background = lum[0]  # corner pixel
        lit = sum(1 for v in lum if v > background + 0.05)
        self.assertGreater(lit / len(lum), 0.05, "ship hardly visible in preview")

    def test_blend_reloads(self):
        with bpy.data.libraries.load(self.files["blend"]) as (src, _dst):
            objects = list(src.objects)
        self.assertIn("Ship", objects)
        self.assertIn("Ship_Hull", objects)
        self.assertIn("ShipGen_Camera", objects)


if __name__ == "__main__":
    unittest.main()
