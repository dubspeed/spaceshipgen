"""Collision report for the parts kit: which part combinations get in each other's way?

    .venv/bin/python scripts/kit_conflicts.py [--out docs/kit/conflicts.md]

Builds every hull (plan x tail x mid x nose) with every mining rig kind and every
cargo module kind on a stress loadout, without resolving collisions, and counts
what collided with what. Then checks that resolving leaves no collision.
"""

import argparse
import collections
import itertools
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import bpy  # noqa: E402

from shipgen import kit, params  # noqa: E402
from shipgen.kit import hull_kit as hk  # noqa: E402
from shipgen.kit import module_designs, rig_designs  # noqa: E402

RIGS = ("drill", "laser", "claw", "scoop")
CARGO = ("containers", "hoppers", "tanks", "habitat")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "kit", "conflicts.md"))
    args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    base = params.load(os.path.join(ROOT, "presets", "miner_m.json")).params
    base = dict(base, spread=0, cargo=dict(base["cargo"], modules=8, size=0.8),
                mining=dict(base["mining"], size=1.0))

    pairs = collections.Counter()
    by_block = collections.Counter()
    builds = ships_with_conflict = unresolved = dropped_rigs = 0
    examples = {}
    for (plan, tail, mid, nose), rig, cargo in itertools.product(
            itertools.product(hk.PLANS, hk.TAILS, hk.MIDS, hk.NOSES), RIGS, CARGO):
        p = dict(base, mining=dict(base["mining"], type=rig), cargo=dict(base["cargo"], type=cargo))
        rig_d = rig_designs.designs_of(rig)[builds % len(rig_designs.designs_of(rig))]
        mod_d = module_designs.designs_of(cargo)[builds % len(module_designs.designs_of(cargo))]
        ship = kit.build(p, plan=plan, tail=tail, mid=mid, nose=nose, rig_design=rig_d, module_design=mod_d)
        builds += 1
        if ship.conflicts:
            ships_with_conflict += 1
            for pair in set(ship.conflicts):
                pairs[pair] += 1
                examples.setdefault(pair, f"{ship.design.label()} + {ship.loadout}")
            for block in (plan, tail, mid, nose if plan != "fork" else "fork-nose"):
                by_block[block] += 1
        dropped_rigs += any(w.startswith("rig dropped") for w in ship.warnings)
        if kit.find_conflicts_after(ship):
            unresolved += 1

    lines = [
        "# Parts-kit collision report",
        "",
        f"{builds} builds (240 hulls x 4 rig kinds x 4 cargo kinds, stress loadout: 8 modules at size 0.8, rig size 1.0).",
        "",
        f"- ships with at least one collision before resolving: **{ships_with_conflict}** "
        f"({100 * ships_with_conflict / builds:.1f} %)",
        f"- ships still colliding after resolving: **{unresolved}**",
        f"- rigs dropped by the resolver: **{dropped_rigs}**",
        "",
        "| collision | ships | example |",
        "|---|---|---|",
    ]
    lines += [f"| {a} vs {b} | {n} | {examples[(a, b)]} |" for (a, b), n in pairs.most_common()]
    lines += ["", "Building blocks involved in collisions (ships):", ""]
    lines += [f"- {block}: {n}" for block, n in by_block.most_common()]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
