"""Headless entry point.

    .venv/bin/python cli.py --preset fighter                 # bpy module (see scripts/setup_env.sh)
    .venv/bin/python cli.py --preset fighter --seeds 1-20 --no-render
    .venv/bin/python cli.py --preset freighter --set hull.length=40 --set style.wear=0.8
    blender -b --factory-startup -P cli.py -- --preset fighter    # with a Blender binary

Writes <name>.glb, <name>.blend, <name>.png (+ <name>_top.png) and <name>.json (validated params +
stats) per ship into --out (default: output/). Prints one JSON summary line per
ship prefixed with ``SHIPGEN_RESULT``. Exit code is non-zero on failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PRESET_DIR = os.path.join(ROOT, "presets")


def parse_seeds(spec: str) -> list[int]:
    """'1,4,10-12' -> [1, 4, 10, 11, 12]"""
    seeds: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            seeds.extend(range(int(a), int(b) + 1))
        else:
            seeds.append(int(part))
    return seeds


def parse_override(text: str) -> tuple[tuple[str, ...], object]:
    """'hull.length=20' -> (('hull', 'length'), 20). Values are parsed as JSON when possible."""
    key, sep, raw = text.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"--set expects key.path=value, got {text!r}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    return tuple(key.strip().split(".")), value


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cli.py", description="Procedural spaceship generator (headless)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--params", help="path to a parameter JSON file")
    src.add_argument("--preset", help="preset name(s) in presets/ without .json: 'fighter', 'miner_s,miner_m' or 'all'")
    src.add_argument("--asteroid", help="asteroid preset name(s) in presets/asteroids/: 'ore_m', 'ore_m,ice_l' or 'all'")
    ap.add_argument("--out", default=os.path.join(ROOT, "output"), help="output directory")
    ap.add_argument("--name", help="output file base name (default: <preset>_<seed>)")
    ap.add_argument("--seed", type=int, help="override the seed")
    ap.add_argument("--seeds", type=parse_seeds, help="batch: '1-20' or '1,5,9'")
    ap.add_argument("--set", dest="overrides", action="append", type=parse_override, default=[],
                    metavar="KEY=VALUE", help="override a parameter, e.g. hull.length=20 (repeatable)")
    ap.add_argument("--no-glb", action="store_true")
    ap.add_argument("--no-blend", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--views", default="three_quarter,top",
                    help="comma separated preview views: three_quarter, top")
    ap.add_argument("--frame", type=float, help="render every ship at the same scale: frame this many metres")
    ap.add_argument("--samples", type=int, default=16, help="Cycles samples for the preview")
    ap.add_argument("--resolution", default="960x540", help="preview size WxH")
    ap.add_argument("--strict", action="store_true", help="fail if parameters needed repairing")
    return ap


def script_args(argv: list[str]) -> list[str]:
    """Arguments meant for this script: after ``--`` when run by the Blender binary,
    everything after the script name when run as ``python cli.py`` (bpy module)."""
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    if argv and argv[0].endswith(".py"):
        return argv[1:]
    return []


def load_jobs(args: argparse.Namespace) -> list[tuple[str, dict]]:
    """(base name, raw params) for every ship source on the command line."""
    if args.params:
        with open(args.params, encoding="utf-8") as f:
            return [(os.path.splitext(os.path.basename(args.params))[0], json.load(f))]
    folder = os.path.join(PRESET_DIR, "asteroids") if args.asteroid else PRESET_DIR
    names = [n.strip() for n in (args.asteroid or args.preset or "fighter").split(",") if n.strip()]
    if names == ["all"]:
        names = sorted(os.path.splitext(n)[0] for n in os.listdir(folder) if n.endswith(".json"))
    jobs = []
    for name in names:
        with open(os.path.join(folder, name + ".json"), encoding="utf-8") as f:
            jobs.append((name, json.load(f)))
    return jobs


def run(args: argparse.Namespace) -> list[dict]:
    import bpy

    from shipgen import asteroids, export
    from shipgen import generator as ship_generator
    from shipgen import params as ship_params

    # same pipeline for both: asteroids bring their own schema and generator
    params, generator = (asteroids.params, asteroids) if args.asteroid else (ship_params, ship_generator)

    jobs = load_jobs(args)
    width, height = (int(v) for v in args.resolution.lower().split("x"))
    views = () if args.no_render else tuple(v.strip() for v in args.views.split(",") if v.strip())
    single = len(jobs) == 1 and len(args.seeds or [0]) == 1

    bpy.ops.wm.read_factory_settings(use_empty=True)

    results = []
    for base_name, base in jobs:
        for path, value in args.overrides:
            params.set_path(base, path, value)
        seeds = args.seeds or [args.seed if args.seed is not None else base.get("seed", 0)]
        for seed in seeds:
            checked = params.validate(dict(base, seed=seed))
            for w in checked.warnings:
                print(f"SHIPGEN_WARNING {w}", file=sys.stderr)
            if args.strict and checked.warnings:
                raise SystemExit(f"invalid parameters ({len(checked.warnings)} problems), see warnings above")

            ship = generator.generate(checked.params)
            name = args.name if (args.name and single) else f"{args.name or base_name}_{seed}"
            files = export.export_all(
                ship, args.out, name, glb=not args.no_glb, blend=not args.no_blend,
                views=views, resolution=(width, height), samples=args.samples, frame=args.frame,
            )
            stats = ship.stats if args.asteroid else ship.stats()
            result = {"name": name, "seed": seed, "files": files, "stats": stats, "warnings": ship.warnings}
            os.makedirs(args.out, exist_ok=True)
            with open(os.path.join(args.out, name + ".json"), "w", encoding="utf-8") as f:
                json.dump({"model": base_name, "model_params": checked.params, "params": ship.params,
                           "stats": result["stats"]}, f, indent=2)
            print("SHIPGEN_RESULT " + json.dumps(result), flush=True)
            results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(script_args(sys.argv if argv is None else argv))
    try:
        run(args)
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
