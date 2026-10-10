"""Zip shipgen/ into an installable extension: dist/shipgen-<version>.zip

    python scripts/build_extension.py

Install in Blender 4.2+: Edit > Preferences > Get Extensions > (v menu) > Install from Disk.
"""

import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "shipgen")


def main() -> str:
    with open(os.path.join(SRC, "blender_manifest.toml"), encoding="utf-8") as f:
        version = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M).group(1)
    out = os.path.join(ROOT, "dist", f"shipgen-{version}.zip")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(SRC):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                path = os.path.join(dirpath, name)
                zf.write(path, os.path.relpath(path, SRC))
    return out


if __name__ == "__main__":
    print(main())
