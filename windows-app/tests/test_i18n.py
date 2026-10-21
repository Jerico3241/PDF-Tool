"""Englische Oberfläche (4.0 Beta 6): Katalog vollständig, jede QML-Textbindung übersetzt, Umschalten in den
Einstellungen ohne Neustart. Alle übrigen Tests laufen deutsch (``PDFTOOL_SPRACHE=de`` in ``conftest``)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import pump, wait_until

import i18n

ROOT = Path(__file__).resolve().parents[1]


def _tool(name: str):
    """Skript aus ``windows-app/tools`` laden (``tools`` ist in der App schon ein anderes Paket)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


i18n_extract = _tool("i18n_extract")


@pytest.fixture
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("de")


def test_catalog_covers_every_text() -> None:
    """Jeder Oberflächentext aus QML und Python steht im Katalog (neue Texte: ``python tools/i18n_extract.py``)."""
    assert i18n_extract.missing() == {"exact": [], "patterns": []}


def test_catalog_keeps_placeholders() -> None:
    data = json.loads(i18n.CATALOG.read_text(encoding="utf-8"))
    for source, target in data["patterns"].items():
        assert sorted(i18n._PLACEHOLDER.findall(source)) == sorted(i18n._PLACEHOLDER.findall(target)), source


def test_every_qml_text_binding_is_translated() -> None:
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "i18n_qml.py"), "--check"], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout


def test_german_is_the_text_itself() -> None:
    i18n.set_language("de")
    assert i18n.tr("Speichern") == "Speichern" and i18n.tr(3) == 3


def test_english_texts_patterns_and_pieces(english) -> None:
    assert i18n.tr("Speichern") == "Save"
    assert i18n.tr("Seite 3 von 10") == "Page 3 of 10"
    assert i18n.tr("  Speichern ") == "  Save "
    assert i18n.tr("Speichern\nAbbrechen") == "Save\nCancel"
    # Unbekanntes (Dateinamen, Kundennamen, Inhalte) bleibt, wie es ist
    assert i18n.tr("Vertrag Müller GmbH.pdf") == "Vertrag Müller GmbH.pdf"


def test_language_follows_windows_unless_chosen(monkeypatch) -> None:
    monkeypatch.delenv(i18n.FORCE_VARIABLE, raising=False)
    monkeypatch.setattr(i18n, "system_language", lambda: "en")
    assert i18n.resolve("system") == "en" and i18n.resolve("de") == "de"
    monkeypatch.setattr(i18n, "system_language", lambda: "de")
    assert i18n.resolve("system") == "de" and i18n.resolve("en") == "en"


def test_switch_to_english_in_settings_without_restart(ui_app, monkeypatch) -> None:
    h = ui_app
    monkeypatch.delenv(i18n.FORCE_VARIABLE, raising=False)
    language = h.runtime.language
    h.navigate("settings", 0.3)
    card = h.item("languageCard")
    assert card is not None and card.property("title") == "Sprache"
    try:
        language.setChoice("en")
        assert wait_until(lambda: card.property("title") == "Language", 5)
        assert language.language == "en" and i18n.language() == "en"
        pump(0.2)
    finally:
        language.setChoice("de")
    assert wait_until(lambda: card.property("title") == "Sprache", 5)


def test_user_texts_stay_and_whole_messages_translate(english) -> None:
    """Eigene Texte (Fragen, Datei- und Firmennamen) blieben bis 4.0 Beta 7 nicht unverändert (»Contract kündigen: …«),
    zusammengesetzte Meldungen erschienen halb deutsch."""
    for own in ("Vertrag kündigen: welche Frist?", "Vertrag Müller.pdf wurde gespeichert.", "Vertrag GmbH"):
        assert i18n.tr(own) == own
    assert i18n.tr("Vertrag 3") == "Contract 3" and i18n.tr("Seiten 1–3") == "Pages 1–3"
    assert i18n.tr("Seiten 1–3 ins Französische übersetzen") == "Translate pages 1–3 into French"
    assert i18n.tr("3 Seiten gespeichert als X.docx. Seite 2, 5 ohne Text als Bild übernommen – für Scans vorher »Text erkennen (OCR)« verwenden.") == (
        "3 pages saved as X.docx. Page 2, 5 without text was added as an image – for scans, run “Recognize text (OCR)” first.")
    assert i18n.tr("Übersetzung ins Englische gespeichert: **a.pdf** (3 Seiten). 2 Seiten ohne Text blieben leer.") == (
        "Translation into English saved: **a.pdf** (3 pages). 2 pages without text stayed empty.")
    assert i18n.tr("Brief.docx wurde in PDF umgewandelt.") == "Brief.docx was converted to PDF."
