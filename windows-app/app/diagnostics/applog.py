"""Protokoll der App: ``pdf-tool.log`` im Datenordner (INFO, WARNING, ERROR), mit Rotation.

Höchstens 1 MB je Datei, drei ältere Dateien (``pdf-tool.log.1`` … ``.3``) – danach fällt die
älteste weg. Protokolliert werden Abläufe (Start, Sicherung, Wiederherstellung, Updates, Fehler),
nie Inhalte: keine Passwörter, keine PDF- oder Excel-Inhalte, keine Kundendaten.

Feste Kategorien – je Kategorie ein Logger ``pdftool.<Kategorie>`` (``get(UPDATE)``):

* ``pdf`` – PDFs öffnen, lesen und bearbeiten
* ``save`` – Dokumente speichern
* ``render`` – Seitenbilder und Vorschau
* ``repair`` – PDF reparieren
* ``ocr`` – Texterkennung
* ``ui`` – Programmstart, Beenden und Oberfläche (auch unerwartete Fehler in Rückmeldungen)
* ``update`` – Updates prüfen, herunterladen und verifizieren, Kanal
* ``installer`` – Start des Setups durch den Updater

``get()`` nimmt weiterhin jeden Bereichsnamen an (z. B. ``"sicherung"``, ``"diagnose"``).
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE = "pdf-tool.log"
MAX_BYTES = 1_000_000
BACKUPS = 3
ROOT = "pdftool"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Kategorien (siehe oben)
PDF = "pdf"
SAVE = "save"
RENDER = "render"
REPAIR = "repair"
OCR = "ocr"
UI = "ui"
UPDATE = "update"
INSTALLER = "installer"
CATEGORIES = (PDF, SAVE, RENDER, REPAIR, OCR, UI, UPDATE, INSTALLER)


def setup(folder: str | os.PathLike, level: int = logging.INFO) -> logging.Logger:
    """Protokoll in ``folder`` einrichten (mehrfacher Aufruf: der erste gilt; Tests: neuer Ordner ersetzt)."""
    logger = logging.getLogger(ROOT)
    path = Path(folder) / LOG_FILE
    for handler in list(logger.handlers):
        if getattr(handler, "pdftool", None) == str(path):
            return logger
        if getattr(handler, "pdftool", None) is not None:
            logger.removeHandler(handler)
            handler.close()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8", delay=True)
    except OSError:
        return logger  # ohne Protokoll weiterarbeiten
    handler.setFormatter(logging.Formatter(_FORMAT, "%Y-%m-%d %H:%M:%S"))
    handler.pdftool = str(path)
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get(area: str) -> logging.Logger:
    """Logger einer Kategorie bzw. eines Bereichs, z. B. ``get(UPDATE).info("…")`` oder ``get("sicherung")``."""
    return logging.getLogger(f"{ROOT}.{area}")


def log_files(folder: str | os.PathLike) -> list[Path]:
    """Protokolldateien im Datenordner (eigene, samt Rotation)."""
    folder = Path(folder)
    names = ("fehler.log", LOG_FILE, "stapel.log", "pdf-repair.log")
    found = []
    for name in names:
        for path in sorted(folder.glob(name + "*")):
            suffix = path.name[len(name):]
            if path.is_file() and (suffix == "" or (suffix.startswith(".") and suffix[1:].isdigit()) or suffix == ".alt"):
                found.append(path)
    return found


def close() -> None:
    logger = logging.getLogger(ROOT)
    for handler in list(logger.handlers):
        if getattr(handler, "pdftool", None) is not None:
            logger.removeHandler(handler)
            handler.close()
