"""Re-render every picture and table in the docs, so the README stays current after changes.

    .venv/bin/python scripts/render_docs.py                      # everything (takes a while)
    .venv/bin/python scripts/render_docs.py --only lineup,stations
    .venv/bin/python scripts/render_docs.py --list

Each step runs in its own process (a fresh Blender scene each time).
"""

import argparse
import glob
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(*args):
    subprocess.run([PY, *args], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


def lineup():
    """docs/renders/shop_lineup.png, shop_lineup_top.png (every preset at one scale) and
    docs/shop_stats.md."""
    tmp = tempfile.mkdtemp()
    run("cli.py", "--preset", "all", "--frame", "64", "--no-glb", "--no-blend", "--resolution", "400x170",
        "--out", tmp)
    for suffix, name in (("", "shop_lineup.png"), ("_top", "shop_lineup_top.png")):
        pngs = sorted(p for p in glob.glob(os.path.join(tmp, f"*{suffix}.png")) if suffix or "_top" not in p)
        run("scripts/contact_sheet.py", os.path.join(ROOT, "docs", "renders", name), "--cols", "4", *pngs)
    table = subprocess.run([PY, "scripts/stats_table.py", *sorted(glob.glob(os.path.join(tmp, "*.json")))],
                           cwd=ROOT, check=True, capture_output=True, text=True).stdout
    with open(os.path.join(ROOT, "docs", "shop_stats.md"), "w", encoding="utf-8") as f:
        f.write(table)


STEPS = {
    "lineup": lineup,
    "kit": lambda: run("scripts/kit_demo.py"),
    "hull_detail": lambda: run("scripts/hull_detail_demo.py"),
    "asteroids": lambda: run("scripts/asteroid_demo.py"),
    "stations": lambda: run("scripts/station_demo.py"),  # incl. docs/wrecks/wrecks.png
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma separated subset of: " + ", ".join(STEPS))
    ap.add_argument("--list", action="store_true", help="list the steps and exit")
    args = ap.parse_args()
    if args.list:
        for name, fn in STEPS.items():
            print(f"{name:12} {(fn.__doc__ or '').split(chr(10))[0]}")
        return
    names = args.only.split(",") if args.only else list(STEPS)
    unknown = [n for n in names if n not in STEPS]
    if unknown:
        ap.error(f"unknown step(s): {', '.join(unknown)}")
    for name in names:
        t = time.time()
        print(f"{name} ...", flush=True)
        STEPS[name]()
        print(f"{name} done in {time.time() - t:.0f} s", flush=True)


if __name__ == "__main__":
    main()
