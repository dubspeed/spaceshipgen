"""Palette atlas (one material per exported mesh) and decals (registration, emblem, stripes)."""

import json
import os
import unittest

try:
    import bpy
except ImportError:
    bpy = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def preset(name):
    with open(os.path.join(ROOT, "presets", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class AtlasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from shipgen import atlas

        cls.atlas = atlas
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def texel(self, img, uv):
        w, h = img.size
        x, y = min(int(uv[0] * w), w - 1), min(int(uv[1] * h), h - 1)
        i = (y * w + x) * 4
        return img.pixels[i:i + 4]

    def check(self, objects):
        """Inside ``baked``: one material per mesh, every paint face samples its own colour,
        metal/roughness and glow; afterwards everything is as before."""
        before = {o.name: (o.data.name, [m.name for m in o.data.materials]) for o in objects if o.type == "MESH"}
        paints = {o.name: [(p.material_index, o.data.materials[p.material_index]) for p in o.data.polygons]
                  for o in objects if o.type == "MESH" and len(o.data.materials)}
        with self.atlas.baked(objects) as a:
            imgs = {i.name.rsplit("_", 1)[-1]: i for i in a.textures}
            for o in objects:
                if o.name not in paints:
                    continue
                self.assertEqual([m.name for m in o.data.materials], [self.atlas.MATERIAL])
                uv = o.data.uv_layers["UVMap"]
                for poly, (_, mat) in zip(o.data.polygons, paints[o.name]):
                    if "shipgen_decal" in mat:
                        continue
                    rgb, metallic, rough, emit, strength = self.atlas.paint_of(mat)
                    loop_uv = uv.data[poly.loop_indices[0]].uv
                    c = self.texel(imgs["Color"], loop_uv)
                    for got, want in zip(c[:3], rgb):
                        self.assertAlmostEqual(got, self.atlas.to_srgb(want), delta=0.01)
                    mr = self.texel(imgs["MR"], loop_uv)
                    self.assertAlmostEqual(mr[1], rough, delta=0.01)
                    self.assertAlmostEqual(mr[2], metallic, delta=0.01)
                    glowing = max(self.texel(imgs["Emit"], loop_uv)[:3]) > 0.01
                    self.assertEqual(glowing, strength > 0 and max(emit) > 0, mat.name)
        after = {o.name: (o.data.name, [m.name for m in o.data.materials]) for o in objects if o.type == "MESH"}
        self.assertEqual(before, after)
        self.assertNotIn(self.atlas.MATERIAL, bpy.data.materials)

    def test_ship(self):
        from shipgen import generator

        self.check(generator.generate(preset("miner_m")).objects)

    def test_station_and_wreck(self):
        from shipgen import stations, wrecks

        self.check(stations.generate({"seed": 2, "role": "mining"}).objects)
        self.check(wrecks.generate({"seed": 3, "breaks": 1}, preset("hauler_m")).objects)


@unittest.skipIf(bpy is None, "requires Blender (bpy)")
class DecalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def decal_faces(self, obj):
        idx = {i for i, m in enumerate(obj.data.materials) if "shipgen_decal" in m}
        return [p for p in obj.data.polygons if p.material_index in idx]

    def test_shop_ships_carry_registration_and_emblem(self):
        from shipgen import generator

        for name in ("miner_m", "hauler_m", "hauler_l", "tanker_m", "miner_s"):
            with self.subTest(name=name):
                ship = generator.generate(preset(name))
                hull = next(o for o in ship.parts if o.name == "Ship_Hull")
                names = [m.name for m in hull.data.materials]
                self.assertIn("ShipGen_Decal_Text", names)
                faces = self.decal_faces(hull)
                left = sum(1 for p in faces if p.center.x < 0)
                self.assertEqual(left, len(faces) - left)  # both flanks
                code = f"-{ship.params['seed'] % 1000:03d}"
                self.assertTrue(any(code in i.name for i in bpy.data.images))

    def test_decals_off(self):
        from shipgen import generator

        p = preset("hauler_m")
        p["style"]["decals"] = False
        ship = generator.generate(p)
        hull = next(o for o in ship.parts if o.name == "Ship_Hull")
        self.assertEqual(self.decal_faces(hull), [])

    def test_station_decals(self):
        from shipgen import stations

        st = stations.generate({"seed": 4, "role": "mining", "size": "medium"})
        docks = [o for o in st.parts if o["station_module"]["kind"].startswith("dock")]
        self.assertTrue(docks)
        for o in docks:  # hazard stripes on every pier head
            self.assertTrue(self.decal_faces(o), o.name)
