"""Gemeinsame Hilfen für die Tests der Windows-App.

Die Tests laufen mit jedem Python ≥ 3.11 mit tkinter, pandas, openpyxl,
reportlab und Pillow. Oberflächentests benötigen ein Display (unter Linux
z. B. ``xvfb-run``) und werden sonst übersprungen.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

COLUMNS = [
    "Vertrag-Nr.",
    "Beginnt am",
    "Abrechnungszyklus",
    "Netto [€]",
    "Zahlungsart",
    "Bemerkung",
    "Rechnungsempfänger Email",
    "Kundennummer",
    "Firmenname",
    "Anwenderstatus",
]


def write_excel(path: Path, rows: list[list], columns: list[str] = COLUMNS) -> Path:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(columns)
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


@pytest.fixture
def excel_file(tmp_path: Path) -> Path:
    from datetime import datetime

    rows = [
        ["V-1001", datetime(2023, 1, 15), "jeden Monat", 49.9, "Lastschr", "x SW-Pflege Warenwirtschaft", "rechnung@muster.de", 10042, "Muster GmbH", "Aktiv"],
        ["V-1002", datetime(2022, 6, 1), "monatlich", 120.0, "Überweisung", "Hott-KI Assistent", "rechnung@muster.de", 10042, "Muster GmbH", "Aktiv"],
        ["V-1003", datetime(2021, 3, 1), "jährlich", 300.0, "Sofort", "Hotline Premium", "rechnung@muster.de", 10042, "Muster GmbH", "Aktiv"],
        ["V-0999", datetime(2020, 1, 1), "jährlich", 10.0, "Sofort", "Alter Vertrag", "rechnung@muster.de", 10042, "Muster GmbH", "Inaktiv"],
    ]
    return write_excel(tmp_path / "vertraege.xlsx", rows)


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "gui-config.json"
    monkeypatch.setenv("UE_CONFIG_FILE", str(path))
    import appstate

    monkeypatch.setattr(appstate, "CONFIG_FILE", path)
    return path


def display_available() -> bool:
    if sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY"))


def pump(app, seconds: float = 0.3) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.01)


def wait_until(app, condition, timeout: float = 60.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if condition():
            return True
        time.sleep(0.02)
    return False
