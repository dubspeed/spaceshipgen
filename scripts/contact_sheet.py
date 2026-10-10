"""Tile preview PNGs into one image (for reviewing many ships at once).

    python scripts/contact_sheet.py out.png a.png b.png ... [--cols 4]
"""

import os
import sys

import bpy
import numpy as np


def load(path: str) -> np.ndarray:
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)


def main(argv: list[str]) -> None:
    cols = 4
    if "--cols" in argv:
        i = argv.index("--cols")
        cols = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2 :]
    out, paths = os.path.abspath(argv[0]), [os.path.abspath(p) for p in argv[1:]]
    tiles = [load(p) for p in paths]
    h, w = tiles[0].shape[:2]
    rows = -(-len(tiles) // cols)
    sheet = np.zeros((rows * h, cols * w, 4), dtype=np.float32)
    sheet[..., 3] = 1.0
    for n, tile in enumerate(tiles):
        r, c = divmod(n, cols)
        y = (rows - 1 - r) * h  # Blender images start at the bottom row
        sheet[y : y + h, c * w : (c + 1) * w] = tile[:h, :w]
    img = bpy.data.images.new("contact_sheet", cols * w, rows * h, alpha=True)
    img.pixels.foreach_set(sheet.ravel())
    img.filepath_raw = out
    img.file_format = "PNG"
    img.save()


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    main(args)
