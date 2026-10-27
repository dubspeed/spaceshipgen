"""One version number (blender_manifest.toml) on every exported root and in every .json."""

import json
import os
import re
import struct
import tempfile
import unittest

try:
    import bpy
except ImportError:
    bpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def preset(name):
    with open(os.path.join(ROOT, "presets", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


class VersionTest(unittest.TestCase):
    def test_from_the_manifest(self):
        from shipgen import version

        with open(os.path.join(ROOT, "shipgen", "blender_manifest.toml"), encoding="utf-8") as f:
            manifest = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.MULTILINE).group(1)
        self.assertEqual(version.FORMAT_VERSION, manifest)
        self.assertRegex(version.FORMAT_VERSION, r"^\d+\.\d+\.\d+$")

    def test_params_json_with_version_loads_cleanly(self):
        from shipgen import params, version

        result = params.validate(version.tagged(preset("miner_m")))
        self.assertEqual(result.warnings, [])


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class RootVersionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_every_root_and_glb(self):
        from shipgen import asteroids, export, fields, generator, stations, version, wrecks

        builders = {
            "ship": lambda: generator.generate(preset("miner_m")),
            "classic": lambda: generator.generate(dict(preset("fighter"), builder="classic")),
            "wreck": lambda: wrecks.generate({"seed": 1}, preset("hauler_s")),
            "asteroid": lambda: asteroids.generate({"seed": 1, "size_m": 10}),
            "station": lambda: stations.generate({"seed": 1, "size": "small"}),
            "station_kit": lambda: stations.build_kit({}),
            "field": lambda: fields.generate({"seed": 1, "count": 8, "prefabs": 2}),
        }
        for name, build in builders.items():
            with self.subTest(name=name):
                built = build()
                self.assertEqual(built.root["format_version"], version.FORMAT_VERSION)
                with tempfile.TemporaryDirectory() as tmp:
                    path = export.export_glb(built, os.path.join(tmp, "x.glb"))
                    with open(path, "rb") as f:
                        data = f.read()
                gltf = json.loads(data[20:20 + struct.unpack("<I", data[12:16])[0]])
                roots = [gltf["nodes"][i] for i in gltf["scenes"][0]["nodes"]]
                self.assertEqual([r["extras"]["format_version"] for r in roots], [version.FORMAT_VERSION])
                if name == "field":
                    self.assertEqual(fields.manifest(built, "f")["format_version"], version.FORMAT_VERSION)
