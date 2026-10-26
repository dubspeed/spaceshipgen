"""Export tests (.glb, .blend, preview .png). Need Blender."""

import itertools
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
        # one atlas material (atlas.py): colour, metal/roughness and glow textures
        self.assertEqual([m["name"] for m in gltf["materials"]], ["ShipGen_Atlas"])
        mat = gltf["materials"][0]
        self.assertIn("emissiveTexture", mat)
        self.assertIn("baseColorTexture", mat["pbrMetallicRoughness"])
        self.assertIn("metallicRoughnessTexture", mat["pbrMetallicRoughness"])
        self.assertTrue(all(s.get("magFilter") == 9728 for s in gltf["samplers"]))  # NEAREST
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
    """The .glb must match Godot: +Y up, -Z forward (nose), +X right. The hull carries no node
    rotation; sockets, FX anchors and the kit's parts sitting on them, are rotated so that their -Z
    (Godot's forward) is the socket normal."""

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

    @staticmethod
    def world_corners(gltf, prefix):
        """Bounding-box corners (glTF space) of the meshes of all nodes named ``prefix*`` under
        the ship root (which has no transform), colliders left out."""
        pts = []
        for node in gltf["nodes"]:
            if not node["name"].startswith(prefix) or "mesh" not in node or node["name"].endswith("-convcolonly"):
                continue
            acc = gltf["accessors"][gltf["meshes"][node["mesh"]]["primitives"][0]["attributes"]["POSITION"]]
            t = node.get("translation", (0, 0, 0))
            for corner in itertools.product(*zip(acc["min"], acc["max"])):
                r = _rotate(node.get("rotation", (0, 0, 0, 1)), corner)
                pts.append(tuple(a + b for a, b in zip(r, t)))
        return pts

    def check_axes(self, p, gltf, engines, fin):
        for node in gltf["nodes"]:
            extras = node.get("extras", {})
            if not node["name"].startswith("Socket_") and "shipgen_part" not in extras and "shipgen_fx" not in extras:
                self.assertNotIn("rotation", node, node["name"])
        half = p["hull"]["length"] / 2
        hull_min, hull_max = self.extent(gltf, "Ship_Hull")
        self.assertAlmostEqual(hull_min[2], -half, places=3)  # nose at -Z
        self.assertAlmostEqual(hull_max[2], half, places=3)
        self.assertGreater(min(z for _, _, z in self.world_corners(gltf, engines)), 0)  # engines at the back (+Z)
        self.assertGreater(max(y for _, y, _ in self.world_corners(gltf, fin)), hull_max[1])  # tail fin up (+Y)

    def test_classic_axes(self):
        p, gltf = self.export("interceptor.json", "classic")  # has a tail fin
        self.check_axes(p, gltf, "Ship_Engines", "Ship_Wings")

    def test_kit_axes_and_sockets(self):
        p, gltf = self.export("interceptor.json", "kit")
        self.check_axes(p, gltf, "Engine_", "Fin_")
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


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class PartNodesTest(unittest.TestCase):
    """Kit parts are their own nodes: findable by name and extras, origin and orientation on their
    socket, each with its own collider child."""

    def test_miner_parts_in_the_glb(self):
        from shipgen import export, generator

        p = dict(params.load(os.path.join(ROOT, "presets", "miner_s.json")).params, spread=0)
        ship = generator.generate(p)
        with tempfile.TemporaryDirectory() as tmp:
            gltf = read_glb_json(export.export_glb(ship, os.path.join(tmp, "ship.glb")))
        nodes = {n["name"]: n for n in gltf["nodes"]}
        root = nodes["Ship"]["extras"]["shipgen"]

        rig = nodes["Rig_0"]
        info = rig["extras"]["shipgen_part"]
        self.assertEqual((info["role"], info["kind"], info["design"]), ("mining", "rig", root["rig"]))
        self.assertTrue(info["design"].startswith("drill"))
        socket = nodes[info["socket"]]
        for key, default in (("translation", (0, 0, 0)), ("rotation", (0, 0, 0, 1))):
            for a, b in zip(rig.get(key, default), socket.get(key, default)):
                self.assertAlmostEqual(a, b, places=4, msg=key)
        children = [gltf["nodes"][i]["name"] for i in rig.get("children", [])]
        self.assertEqual(children, ["Rig_0_col-convcolonly"])

        engines = [n for n in nodes if n.startswith("Engine_") and not n.endswith("-convcolonly")]
        modules = [n for n in nodes if n.startswith("Module_") and not n.endswith("-convcolonly")]
        self.assertEqual(len(engines), p["engines"]["count"])
        self.assertEqual(len(modules), p["cargo"]["modules"])
        for name in engines + modules:
            self.assertIn(name + "_col-convcolonly", nodes)
            self.assertEqual(nodes[name]["extras"]["shipgen_part"]["design"],
                             root["engine" if name.startswith("Engine") else "module"])


if __name__ == "__main__":
    unittest.main()
