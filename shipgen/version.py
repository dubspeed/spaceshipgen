"""The one version number: the extension's (``blender_manifest.toml``).

It is also the export format's version: every exported root node carries it as
``extras.format_version`` and every written .json as ``"format_version"`` (docs/export_format.md).
Bump the manifest's ``version`` whenever the .glb / .json structure changes.
"""

from __future__ import annotations

import os
import re

_MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_manifest.toml")


def _read() -> str:
    with open(_MANIFEST, encoding="utf-8") as f:
        m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
    if m is None:
        raise RuntimeError(f"no version in {_MANIFEST}")
    return m.group(1)


FORMAT_VERSION = _read()
META_KEYS = ("format_version",)  # top-level keys of a written .json that aren't parameters (validate skips them)


def stamp(root) -> None:
    """Mark an exported root object (custom property -> glTF extras)."""
    root["format_version"] = FORMAT_VERSION


def tagged(record: dict) -> dict:
    """``record`` with ``format_version`` as its first key (for .json files)."""
    return {"format_version": FORMAT_VERSION, **record}
