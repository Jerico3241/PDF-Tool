"""Gemeinsame Hilfen für die Tests der Windows-App.

Die Tests laufen mit jedem Python ≥ 3.11 mit PySide6, pandas, openpyxl, reportlab und
Pillow. Oberflächentests laufen ohne Bildschirm (Qt-Plattform »offscreen«) – unter Linux,
Windows und in der CI gleich. ``qtutil.Harness`` startet die App wie beim echten Start.
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

# Tests schreiben nie in den echten Datenordner (Einstellungen, Protokolle, Datenübernahme).
if not os.environ.get("UE_DATA_DIR"):
    import tempfile

    os.environ["UE_DATA_DIR"] = tempfile.mkdtemp(prefix="pdf-tool-testdaten-")

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


@pytest.fixture(autouse=True)
def _windows_settings(monkeypatch):
    """Tests hängen nicht von den Windows-Einstellungen des Rechners ab: »Animationseffekte« an
    (auf CI-Rechnern oft aus), kein Mica (sonst würde je Test das Hintergrundbild geladen). Tests,
    die diese Einstellungen prüfen, setzen sie selbst."""
    import winsys

    monkeypatch.setattr(winsys, "client_area_animations", lambda: True)
    monkeypatch.setattr(winsys, "mica_supported", lambda: False)


class FakeHelper:
    """Statt des echten Hilfsprozesses (Tests starten nie ein Setup)."""

    def __init__(self) -> None:
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True


class FakeLauncher:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    def start(self, setup, sha256, wait_pid, log=None):
        helper = FakeHelper()
        self.calls.append({"setup": setup, "sha256": sha256, "pid": wait_pid, "log": log, "helper": helper})
        return helper


@pytest.fixture(autouse=True)
def _updates_offline(monkeypatch, tmp_path_factory):
    """Tests gehen nie ins Internet und starten nie ein Setup: Der Updater der App fragt eine nicht
    erreichbare lokale Adresse (offline), Downloads landen in einem eigenen Testordner, der
    Hilfsprozess ist eine Attrappe. Tests des Updaters setzen ``updates.create_service`` selbst."""
    folder = tmp_path_factory.mktemp("updates")
    monkeypatch.setenv("UE_UPDATE_DIR", str(folder))
    try:
        from qtapp import updates
    except ImportError:  # ohne PySide6 (reine Kerntests)
        return
    from updater.policy import UrlPolicy
    from updater.service import UpdateService
    from updater.store import UpdateStore
    from updater.transport import HttpClient

    def offline(app, installed):
        client = HttpClient(UrlPolicy.loopback(1), user_agent="PDF-Tool-Test", system_proxy=False)
        return UpdateService(installed, client, UpdateStore(folder), app.worker.run, releases_url="http://127.0.0.1:1/releases")

    calls: list = []
    monkeypatch.setattr(updates, "create_service", offline)
    monkeypatch.setattr(updates, "create_launcher", lambda: FakeLauncher(calls))
    monkeypatch.setattr(updates, "LAUNCHES", calls, raising=False)


@pytest.fixture(scope="session")
def qt_application():
    """Die eine QApplication des Testlaufs (Qt erlaubt nur eine je Prozess)."""
    from qtutil import qt_application as create

    return create()


def _prepare(config_file: Path, monkeypatch, profile: str, extra: dict | None = None) -> None:
    import json

    import appstate
    from qtapp import dialogs, files

    data = {"gesehen": appstate.VERSION, "theme": "light", "accent": "#005FB8", "kundenakte_verwenden": True, "animationsprofil": profile}
    data.update(extra or {})
    if not config_file.exists():
        config_file.write_text(json.dumps(data), encoding="utf-8")
    # Rückfragen: »primary«; Dateiauswahl: keine (ein echter Dialog öffnet sich in Tests nie).
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    monkeypatch.setattr(files, "RESPONSES", [])
    # Öffnen mit dem Standardprogramm nur protokollieren
    opened: list[str] = []
    monkeypatch.setattr(files, "open_path", lambda path: opened.append(str(path)))
    monkeypatch.setattr(files, "OPENED", opened, raising=False)
    # Links (Release Notes) nur protokollieren – nie einen Browser öffnen
    urls: list[str] = []
    monkeypatch.setattr(files, "open_url", lambda url: urls.append(str(url)) or True)
    monkeypatch.setattr(files, "URLS", urls, raising=False)


@pytest.fixture(params=["full", "off"], ids=["animationen", "ohne-animationen"])
def app(request, qt_application, config_file: Path, monkeypatch):
    """Gestartete App (Controller + QML im Fenster) mit frischer Konfiguration.

    Kundenakte eingeschaltet (den Standard »aus« prüft test_qt_customer_optional.py).
    Nach dem Test darf die QML-Engine keine Warnung gemeldet haben.
    """
    from qtutil import Harness

    _prepare(config_file, monkeypatch, request.param)
    harness = Harness(ui=True)
    holder = {"current": harness}
    harness.holder = holder
    yield harness
    current = holder["current"]
    messages = current.messages()
    current.close()
    assert not messages, "QML-Meldungen:\n" + "\n".join(messages)


@pytest.fixture
def ui_app(qt_application, config_file: Path, monkeypatch):
    """Wie ``app``, aber nur mit dem Standardprofil »Vollständig« (für Ablauf-Tests)."""
    from qtutil import Harness

    _prepare(config_file, monkeypatch, "full")
    harness = Harness(ui=True)
    holder = {"current": harness}
    harness.holder = holder
    yield harness
    current = holder["current"]
    messages = current.messages()
    current.close()
    assert not messages, "QML-Meldungen:\n" + "\n".join(messages)


@pytest.fixture
def backend(qt_application, config_file: Path, monkeypatch):
    """Nur die Controller (ohne QML) – für reine Ablauf-Tests."""
    from qtutil import Harness

    _prepare(config_file, monkeypatch, "off")
    harness = Harness(ui=False)
    holder = {"current": harness}
    harness.holder = holder
    yield harness
    holder["current"].close()


def neustart(harness):
    """App schließen (speichert wie beim Beenden) und mit derselben Konfiguration neu starten."""
    neu = harness.restart()
    holder = getattr(harness, "holder", None)
    if holder is not None:
        holder["current"] = neu
        neu.holder = holder
    return neu


from qtutil import pump, wait_until  # noqa: E402,F401 - für die Testmodule
