"""Vergleich zweier Messungen von ``bench_app.py`` (Mediane): Markdown-Tabelle und eine Zeile ``BRIEF …``.

    python bench_compare.py <Präfix Vorversion> <Präfix neu>

Gelesen werden alle Dateien ``<Präfix>-*.json`` (je Messteil eine). Kein Test – nur Ausgabe.
"""

from __future__ import annotations

import glob
import json
import statistics
import sys

KEYS = ("start.imports", "start.controller", "start.qml", "start.erstes_bild", "start.startseite", "start.alle_seiten",
        "reader.klein", "reader.gross", "oeffnen_mit.erstes_bild", "oeffnen_mit.seite")


def load(prefix: str) -> dict:
    data = {"version": "?", "results": {}}
    for path in sorted(glob.glob(prefix + "-*.json")):
        with open(path, encoding="utf-8") as handle:
            part = json.load(handle)
        data["version"] = part["version"]
        data["results"].update(part["results"])
    return data


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    old, new = load(sys.argv[1]), load(sys.argv[2])
    rows = [f"| Messung (Median) | {old['version']} | {new['version']} | Unterschied |", "| --- | ---: | ---: | ---: |"]
    brief = []
    for key in KEYS:
        a, b = old["results"].get(key), new["results"].get(key)
        if not a or not b:
            continue
        a, b = statistics.median(a), statistics.median(b)
        rows.append(f"| {key} | {a:.0f} ms | {b:.0f} ms | {b - a:+.0f} ms ({(b - a) / a * 100:+.0f} %) |")
        brief.append(f"{key} {a:.0f} -> {b:.0f} ms")
    print("\n".join(rows))
    print("BRIEF " + " · ".join(brief))
    return 0


if __name__ == "__main__":
    sys.exit(main())
