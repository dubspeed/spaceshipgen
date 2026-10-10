#!/bin/bash
# Creates .venv with the `bpy` module (Blender as a Python package) so the CLI
# and tests run headless without a Blender install. Idempotent.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"

if [ ! -x "$VENV/bin/python" ]; then
    PY="$(command -v python3.13 || true)"
    if [ -z "$PY" ]; then
        echo "setup_env: python3.13 not found (required by bpy 5.2)" >&2
        exit 1
    fi
    "$PY" -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --disable-pip-version-check -r "$ROOT/requirements-dev.txt"
"$VENV/bin/python" -c "import bpy; print('setup_env: bpy', bpy.app.version_string)"
