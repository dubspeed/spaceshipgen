"""Headless entry point.

    blender -b --factory-startup -P cli.py -- --params presets/fighter.json
    blender -b --factory-startup -P cli.py -- --preset fighter --seeds 1-20 --no-render
    blender -b --factory-startup -P cli.py -- --preset freighter --set hull.length=40 --set style.wear=0.8

Writes <name>.glb, <name>.blend, <name>.png and <name>.json (validated params +
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
    src.add_argument("--preset", help="name of a preset in presets/ (without .json)")
    ap.add_argument("--out", default=os.path.join(ROOT, "output"), help="output directory")
    ap.add_argument("--name", help="output file base name (default: <preset>_<seed>)")
    ap.add_argument("--seed", type=int, help="override the seed")
    ap.add_argument("--seeds", type=parse_seeds, help="batch: '1-20' or '1,5,9'")
    ap.add_argument("--set", dest="overrides", action="append", type=parse_override, default=[],
                    metavar="KEY=VALUE", help="override a parameter, e.g. hull.length=20 (repeatable)")
    ap.add_argument("--no-glb", action="store_true")
    ap.add_argument("--no-blend", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--samples", type=int, default=16, help="Cycles samples for the preview")
    ap.add_argument("--resolution", default="960x540", help="preview size WxH")
    ap.add_argument("--strict", action="store_true", help="fail if parameters needed repairing")
    return ap


def script_args(argv: list[str]) -> list[str]:
    return argv[argv.index("--") + 1 :] if "--" in argv else []


def run(args: argparse.Namespace) -> list[dict]:
    import bpy

    from shipgen import export, generator, params

    if args.params:
        with open(args.params, encoding="utf-8") as f:
            base = json.load(f)
        base_name = os.path.splitext(os.path.basename(args.params))[0]
    else:
        preset = args.preset or "fighter"
        with open(os.path.join(PRESET_DIR, preset + ".json"), encoding="utf-8") as f:
            base = json.load(f)
        base_name = preset

    for path, value in args.overrides:
        params.set_path(base, path, value)

    seeds = args.seeds or [args.seed if args.seed is not None else base.get("seed", 0)]
    width, height = (int(v) for v in args.resolution.lower().split("x"))

    bpy.ops.wm.read_factory_settings(use_empty=True)

    results = []
    for seed in seeds:
        raw = dict(base, seed=seed)
        checked = params.validate(raw)
        for w in checked.warnings:
            print(f"SHIPGEN_WARNING {w}", file=sys.stderr)
        if args.strict and checked.warnings:
            raise SystemExit(f"invalid parameters ({len(checked.warnings)} problems), see warnings above")

        ship = generator.generate(checked.params)
        name = args.name if (args.name and len(seeds) == 1) else f"{args.name or base_name}_{seed}"
        files = export.export_all(
            ship,
            args.out,
            name,
            glb=not args.no_glb,
            blend=not args.no_blend,
            render=not args.no_render,
            resolution=(width, height),
            samples=args.samples,
        )
        result = {"name": name, "seed": seed, "files": files, "stats": ship.stats(), "warnings": checked.warnings}
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, name + ".json"), "w", encoding="utf-8") as f:
            json.dump({"params": ship.params, "stats": result["stats"]}, f, indent=2)
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
