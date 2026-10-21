"""Erzeugt die Symbole von Novadesk (seit 5.0) aus den SVG-Vorlagen in ``windows-app/assets/symbole``.

* ``assets/icon.ico`` – App-Symbol (ein freistehendes »N« vor drei Seiten in Grün, Orange und Rot): App, Taskleiste,
  Setup, Deinstallation.
* ``assets/datei-<art>.ico`` – ein eigenes Symbol je Dateiart (PDF, Text, Tabelle, Präsentation, CSV): Explorer und
  »Öffnen mit«, damit man vor dem Öffnen sieht, was man öffnet. Bis 32 px ohne Aufschrift (``<art>-klein.svg``).
* ``app/qml/images/<art>-<px>.png`` – dieselben Symbole für die Oberfläche (Startseite, Tabs, zuletzt verwendet), je
  einfach und doppelt groß für hohe Bildschirmauflösungen; ``app-96.png`` für den Kopf der Startseite.

Gerendert wird mit Chromium (Playwright, ``render_svg.mjs``), damit Verläufe, Schatten und die Schrift der Aufschrift
genau wie im Entwurf aussehen; die Ergebnisse liegen im Repository – der Build braucht weder Node noch Chromium.
Die Website (``public/``) behält bis zur stabilen Version 5.0 das Symbol von PDF Tool.

Aufruf (aus dem Repository-Hauptordner, Node mit Playwright und Pillow nötig):
    python windows-app/scripts/make_icons.py
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / "windows-app"
SOURCES = APP_ROOT / "assets" / "symbole"
ASSETS = APP_ROOT / "assets"
IMAGES = APP_ROOT / "app" / "qml" / "images"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
SMALL_UP_TO = 32  # bis zu dieser Größe: Dateisymbole ohne Aufschrift
FILE_KINDS = ("pdf", "text", "tabelle", "praesentation", "csv")
UI_SIZES = (16, 24, 32, 48)  # Oberfläche (je einfach und doppelt)
HERO_SIZE = 96  # App-Symbol oben auf der Startseite (nur »app«)


def source(kind: str, size: int) -> Path:
    if kind == "app":
        return SOURCES / "app.svg"
    return SOURCES / (f"{kind}-klein.svg" if size <= SMALL_UP_TO else f"{kind}.svg")


def render_all(jobs: list[tuple[str, int]], folder: Path) -> dict[tuple[str, int], Image.Image]:
    task = [{"svg": str(source(kind, size)), "size": size, "out": str(folder / f"{kind}-{size}.png")} for kind, size in jobs]
    (folder / "auftrag.json").write_text(json.dumps(task), encoding="utf-8")
    subprocess.check_call(["node", str(Path(__file__).with_name("render_svg.mjs")), str(folder / "auftrag.json")])
    return {(kind, size): Image.open(folder / f"{kind}-{size}.png").convert("RGBA") for kind, size in jobs}


def write_ico(path: Path, images: list[Image.Image]) -> None:
    images = sorted(images, key=lambda image: image.width)
    largest = images[-1]
    largest.save(path, format="ICO", sizes=[image.size for image in images], append_images=images[:-1])
    check = Image.open(path)
    assert sorted(check.ico.sizes()) == sorted(image.size for image in images), check.ico.sizes()


def main() -> None:
    kinds = ("app", *FILE_KINDS)
    ui = sorted({size for base in UI_SIZES for size in (base, 2 * base)})
    jobs = sorted({(kind, size) for kind in kinds for size in (*ICON_SIZES, *ui)} | {("app", HERO_SIZE), ("app", 2 * HERO_SIZE)})
    IMAGES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        rendered = render_all(jobs, Path(temp))
        write_ico(ASSETS / "icon.ico", [rendered["app", size] for size in ICON_SIZES])
        for kind in FILE_KINDS:
            write_ico(ASSETS / f"datei-{kind}.ico", [rendered[kind, size] for size in ICON_SIZES])
        for kind in kinds:
            for base in UI_SIZES:
                rendered[kind, base].save(IMAGES / f"{kind}-{base}.png", optimize=True)
                rendered[kind, 2 * base].save(IMAGES / f"{kind}-{base}@2x.png", optimize=True)
        rendered["app", HERO_SIZE].save(IMAGES / f"app-{HERO_SIZE}.png", optimize=True)
        rendered["app", 2 * HERO_SIZE].save(IMAGES / f"app-{HERO_SIZE}@2x.png", optimize=True)
    print("Symbole geschrieben:", ASSETS / "icon.ico", ", ".join(f"datei-{kind}.ico" for kind in FILE_KINDS), IMAGES)


if __name__ == "__main__":
    main()
