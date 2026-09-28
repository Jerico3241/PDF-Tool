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


@pytest.fixture(params=[True, False], ids=["animationen", "ohne-animationen"])
def app(request, config_file: Path, monkeypatch):
    """Gestartete App mit frischer Konfiguration (Neuerungen bereits gesehen)."""
    import json

    import appstate

    config_file.write_text(json.dumps({"gesehen": appstate.VERSION, "theme": "light", "accent": "#005FB8"}), encoding="utf-8")
    if request.param:
        monkeypatch.delenv("UE_NO_ANIMATIONS", raising=False)
    else:
        monkeypatch.setenv("UE_NO_ANIMATIONS", "1")
    from ui import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    import vertragdesk

    instance = vertragdesk.App()
    instance.ctx.anim.enabled = request.param
    pump(instance, 0.5)
    yield instance
    try:
        instance._on_close()
    except Exception:
        pass
    # Tk-Objekte im Hauptthread freigeben, nicht später in einem Worker-Thread.
    import gc

    gc.collect()


def neustart(app):
    """App schließen (speichert wie beim Beenden) und mit derselben Konfiguration neu starten."""
    import gc

    import vertragdesk

    app._on_close()
    gc.collect()
    neu = vertragdesk.App()
    neu.ctx.anim.enabled = False
    pump(neu, 0.3)
    return neu


def schliessen(app) -> None:
    import gc

    try:
        app._on_close()
    except Exception:
        pass
    gc.collect()
