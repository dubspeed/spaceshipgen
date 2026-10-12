"""End-to-end: run cli.py in a Blender subprocess. Runs from plain Python."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cli  # noqa: E402

BLENDER = os.environ.get("BLENDER") or shutil.which("blender")
IN_BLENDER_BINARY = os.path.basename(sys.argv[0]).startswith("blender")
HAS_BPY_MODULE = importlib.util.find_spec("bpy") is not None


def cli_command() -> list[str] | None:
    """How to run cli.py: $BLENDER if set, else this interpreter if it has the bpy
    module (PyPI), else the blender binary on PATH."""
    script = os.path.join(ROOT, "cli.py")
    if IN_BLENDER_BINARY:
        return None
    if os.environ.get("BLENDER") or not HAS_BPY_MODULE:
        return [BLENDER, "-b", "--factory-startup", "-P", script, "--"] if BLENDER else None
    return [sys.executable, script]


class ArgParsingTest(unittest.TestCase):
    def test_parse_seeds(self):
        self.assertEqual(cli.parse_seeds("1,4,10-12"), [1, 4, 10, 11, 12])

    def test_parse_override(self):
        self.assertEqual(cli.parse_override("hull.length=20"), (("hull", "length"), 20))
        self.assertEqual(cli.parse_override("class=freighter"), (("class",), "freighter"))
        self.assertEqual(cli.parse_override("symmetry=false"), (("symmetry",), False))

    def test_script_args(self):
        self.assertEqual(cli.script_args(["blender", "-b", "-P", "cli.py", "--", "--seed", "3"]), ["--seed", "3"])
        self.assertEqual(cli.script_args(["blender"]), [])


@unittest.skipIf(cli_command() is None, "needs the bpy module or a blender executable")
class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        cmd = [*cli_command(), *args]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        results = [
            json.loads(line.split(" ", 1)[1])
            for line in proc.stdout.splitlines()
            if line.startswith("SHIPGEN_RESULT ")
        ]
        return proc, results

    def test_fighter_preset_exports_everything(self):
        with tempfile.TemporaryDirectory() as out:
            proc, results = self.run_cli(
                "--params", os.path.join(ROOT, "presets", "fighter.json"),
                "--out", out, "--resolution", "160x90", "--samples", "2",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            self.assertEqual(len(results), 1)
            for suffix in (".glb", ".blend", ".png", "_top.png", ".json"):
                path = os.path.join(out, f"fighter_42{suffix}")
                self.assertTrue(os.path.isfile(path), path)
            with open(os.path.join(out, "fighter_42.json")) as f:
                meta = json.load(f)
            self.assertEqual(meta["params"]["seed"], 42)
            self.assertLessEqual(meta["stats"]["tris"], meta["params"]["max_tris"])

    def test_batch_seeds_and_overrides(self):
        with tempfile.TemporaryDirectory() as out:
            proc, results = self.run_cli(
                "--preset", "fighter", "--seeds", "1-3", "--no-render", "--no-blend",
                "--set", "hull.length=30", "--set", "max_tris=2000", "--set", "spread=0", "--out", out,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            self.assertEqual([r["seed"] for r in results], [1, 2, 3])
            for r in results:
                self.assertAlmostEqual(r["stats"]["bbox_max"][1], 15.0, places=3)  # nose at +length/2
                self.assertLessEqual(r["stats"]["tris"], 2000)
            self.assertEqual(sorted(os.listdir(out)), sorted(
                f"fighter_{s}.{e}" for s in (1, 2, 3) for e in ("glb", "json")))

    def test_strict_rejects_invalid_params(self):
        with tempfile.TemporaryDirectory() as out:
            proc, results = self.run_cli("--preset", "fighter", "--set", "hull.length=-5", "--strict",
                                         "--no-render", "--out", out)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(results, [])
            self.assertIn("SHIPGEN_WARNING hull.length", proc.stderr)

    def test_missing_params_file_fails(self):
        proc, _ = self.run_cli("--params", "/nonexistent.json", "--no-render")
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
