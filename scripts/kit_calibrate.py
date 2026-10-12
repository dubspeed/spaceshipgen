"""Calibrate KIT_MINING_EFFICIENCY: a medium rig (size 0.5 on miner_m, reference hull) of each
kind should average ~100 mining power over that kind's designs.

    .venv/bin/python scripts/kit_calibrate.py

Prints the efficiency table to paste into shipgen/kit/__init__.py.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import bpy  # noqa: E402

from shipgen import kit, params  # noqa: E402
from shipgen.kit import rig_designs  # noqa: E402

TARGET = 100.0
REFERENCE = dict(plan="mono", tail="flat", mid="straight", nose="blunt")


def reference_params(kind: str) -> dict:
    p = params.load(os.path.join(ROOT, "presets", "miner_m.json")).params
    return dict(p, spread=0, mining=dict(p["mining"], type=kind, size=0.5))


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    table = {}
    for kind in ("drill", "laser", "claw", "scoop"):
        current = kit.KIT_MINING_EFFICIENCY[kind]
        powers = []
        for design in rig_designs.designs_of(kind):
            ship = kit.build(reference_params(kind), rig_design=design, **REFERENCE)
            powers.append(ship.gameplay["mining"]["power"] / current)  # power at efficiency 1
            print(f"{kind:6s} {rig_designs.NAMES[design]:14s} raw {powers[-1]:8.2f}")
        table[kind] = round(TARGET / (sum(powers) / len(powers)), 3)
    print("KIT_MINING_EFFICIENCY =", table)


if __name__ == "__main__":
    main()
