"""Print a Markdown table of gameplay stats from CLI result files.

    python scripts/stats_table.py output/*.json
"""

import json
import os
import sys

COLUMNS = (
    ("ship", lambda n, g: n),
    ("class", lambda n, g: g["class"]),
    ("length m", lambda n, g: g["stats"]["length_m"]),
    ("mass t", lambda n, g: g["stats"]["mass_t"]),
    ("accel m/s²", lambda n, g: g["stats"]["acceleration_ms2"]),
    ("turn °/s²", lambda n, g: g["stats"]["turn_rate_deg_s2"]),
    ("hull HP", lambda n, g: g["stats"]["hull_hp"]),
    ("general m³", lambda n, g: g["stats"]["cargo"]["general_m3"]),
    ("ore m³", lambda n, g: g["stats"]["cargo"]["ore_m3"]),
    ("fluid m³", lambda n, g: g["stats"]["cargo"]["fluid_m3"]),
    ("pax", lambda n, g: g["stats"]["cargo"]["passengers"]),
    ("mining", lambda n, g: g["stats"]["mining"]["type"]),
    ("mining power", lambda n, g: g["stats"]["mining"]["power"]),
    ("range m", lambda n, g: g["stats"]["mining"]["range_m"]),
)


def main(paths: list[str]) -> None:
    print("| " + " | ".join(c for c, _ in COLUMNS) + " |")
    print("|" + "---|" * len(COLUMNS))
    for path in sorted(paths):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        g = {"class": data["params"]["class"], "stats": data["stats"]["gameplay"]}
        name = os.path.splitext(os.path.basename(path))[0]
        print("| " + " | ".join(str(fn(name, g)) for _, fn in COLUMNS) + " |")


if __name__ == "__main__":
    main(sys.argv[1:])
