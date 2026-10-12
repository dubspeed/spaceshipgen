import glob
import json
import os
import unittest

from shipgen import params

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DefaultsTest(unittest.TestCase):
    def test_defaults_are_valid(self):
        result = params.validate(params.defaults())
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.params, params.defaults())

    def test_empty_input_gives_defaults(self):
        for data in ({}, None):
            self.assertEqual(params.validate(data).params, params.defaults())

    def test_defaults_within_limits(self):
        for path, spec in params.iter_fields():
            with self.subTest(path=path):
                if spec.min is not None:
                    self.assertGreaterEqual(spec.default, spec.min)
                if spec.max is not None:
                    self.assertLessEqual(spec.default, spec.max)
                if spec.choices:
                    self.assertIn(spec.default, spec.choices)

    def test_defaults_are_fresh_copies(self):
        a = params.defaults()
        a["hull"]["length"] = 99
        self.assertNotEqual(params.defaults()["hull"]["length"], 99)


class RepairTest(unittest.TestCase):
    def check(self, data, path, expected, warns=True):
        result = params.validate(data)
        self.assertEqual(params.get_path(result.params, path), expected)
        self.assertEqual(bool(result.warnings), warns, result.warnings)

    def test_clamps_numbers(self):
        self.check({"hull": {"length": 10_000}}, ("hull", "length"), 200.0)
        self.check({"hull": {"taper": -3}}, ("hull", "taper"), 0.0)
        self.check({"max_tris": 1}, ("max_tris",), 500)

    def test_numeric_strings_and_int_rounding(self):
        self.check({"hull": {"length": "20"}}, ("hull", "length"), 20.0, warns=False)
        self.check({"hull": {"segments": 5.6}}, ("hull", "segments"), 6)
        self.check({"seed": 7.0}, ("seed",), 7, warns=False)

    def test_bad_types_fall_back_to_default(self):
        self.check({"hull": {"length": "long"}}, ("hull", "length"), 12.0)
        self.check({"hull": {"length": None}}, ("hull", "length"), 12.0)
        self.check({"hull": {"length": float("nan")}}, ("hull", "length"), 12.0)
        self.check({"seed": True}, ("seed",), 42)
        self.check({"hull": "big"}, ("hull", "length"), 12.0)

    def test_choices_are_normalised(self):
        self.check({"class": "Fighter"}, ("class",), "fighter", warns=False)
        self.check({"wings": {"type": "forward-swept"}}, ("wings", "type"), "forward_swept", warns=False)
        self.check({"class": "battlestar"}, ("class",), "fighter")

    def test_bool(self):
        self.check({"symmetry": "false"}, ("symmetry",), False, warns=False)
        self.check({"symmetry": 0}, ("symmetry",), False, warns=False)
        self.check({"symmetry": "maybe"}, ("symmetry",), True)

    def test_colors(self):
        self.check({"engines": {"glow_color": "#4AF"}}, ("engines", "glow_color"), "#44aaff", warns=False)
        self.check({"engines": {"glow_color": "blue"}}, ("engines", "glow_color"), "#44aaff")

    def test_unknown_keys_warn(self):
        result = params.validate({"hull": {"lenght": 3}, "lasers": 4})
        self.assertEqual(len(result.warnings), 2)
        self.assertNotIn("lasers", result.params)

    def test_validate_is_idempotent(self):
        once = params.validate({"hull": {"length": 9999, "segments": 2.2}, "class": "SHUTTLE"}).params
        twice = params.validate(once)
        self.assertEqual(twice.params, once)
        self.assertEqual(twice.warnings, [])


class IndividualizeTest(unittest.TestCase):
    def setUp(self):
        self.model = params.load(os.path.join(ROOT, "presets", "miner_m.json")).params

    def test_deterministic_per_seed(self):
        a = params.individualize(dict(self.model, seed=5))
        b = params.individualize(dict(self.model, seed=5))
        c = params.individualize(dict(self.model, seed=6))
        self.assertEqual(a, b)
        self.assertNotEqual(a["hull"], c["hull"])

    def test_stays_within_spread_and_schema(self):
        spread = self.model["spread"]
        for seed in range(50):
            ind = params.individualize(dict(self.model, seed=seed))
            self.assertEqual(params.validate(ind).warnings, [])
            for key in ("length", "width_ratio", "height_ratio"):
                ratio = ind["hull"][key] / self.model["hull"][key]
                self.assertLessEqual(abs(ratio - 1), spread + 1e-9, (seed, key))
            # discrete choices are never touched
            for path in (("class",), ("mining", "type"), ("cargo", "modules"), ("engines", "count")):
                self.assertEqual(params.get_path(ind, path), params.get_path(self.model, path))

    def test_zero_spread_is_identity(self):
        model = dict(self.model, spread=0.0)
        self.assertEqual(params.individualize(model), model)


class SchemaTest(unittest.TestCase):
    def test_json_schema_mirrors_schema(self):
        js = params.json_schema()
        json.dumps(js)  # serialisable
        self.assertEqual(js["properties"]["hull"]["properties"]["length"]["maximum"], 200.0)
        self.assertEqual(js["properties"]["class"]["enum"], list(params.SHIP_CLASSES))

    def test_presets_are_valid(self):
        presets = glob.glob(os.path.join(ROOT, "presets", "*.json"))
        self.assertIn("fighter.json", [os.path.basename(p) for p in presets])
        for path in presets:
            with self.subTest(preset=os.path.basename(path)):
                self.assertEqual(params.load(path).warnings, [])


if __name__ == "__main__":
    unittest.main()
