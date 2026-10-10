"""Run the test suite inside Blender.

    blender -b --factory-startup -P tests/run_blender.py [-- -k pattern]
    python tests/run_blender.py [-k pattern]      # with the bpy module from PyPI

Exits with a non-zero code if any test fails.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:] if sys.argv[0].endswith(".py") else []
patterns = argv[argv.index("-k") + 1 :][:1] if "-k" in argv else []

loader = unittest.TestLoader()
if patterns:
    loader.testNamePatterns = [f"*{patterns[0]}*"]
suite = loader.discover(os.path.join(ROOT, "tests"), top_level_dir=ROOT)
result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
