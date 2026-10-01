"""Einfügemarke (Caret) der Kopf- und Fußzeilen-Editoren – Lage, Höhe, Schärfe, Fokus.

Vorher (2.7.0 vor dieser Korrektur):

* In einem leeren Editor (leere Kopfzeile, geleerte Fußzeile) war die Marke fest 10 px hoch und
  stand oben links – auch in der zentrierten Fußzeile. Ursache: ``setBlockCharFormat`` auf einem
  leeren Absatz verwirft dessen Zeilen-Layout, ohne es neu zu berechnen; ohne Zeile nimmt Qt
  ersatzweise 10 px. Der Platzhalter stand in der Oberflächenschrift (14 px) daneben – größer und
  tiefer als die Schrift, die beim Tippen entsteht: Die Marke »schwebte« über ihm.
* Qt zeichnete die Marke 1 logisches Pixel breit: bei 125 … 175 % 1,25 … 1,75 Gerätepixel, je
  nach Lage über ein bis vier Pixel verteilt; ihre Höhe war die ganze Zeilenhöhe.

Jetzt (``PTextCaret``): Höhe aus den Font Metrics der Schrift am Cursor, auf der Grundlinie der
Zeile, Breite, Höhe und Lage in ganzen Gerätepixeln; Platzhalter in derselben Schrift und
Ausrichtung wie der Text, der beim Tippen entsteht.

Die Tests laufen mit dem Software-Renderer von Qt (``offscreen``). Er rundet Rechtecke auf ganze
*logische* Pixel; pixelgenau im Bild geprüft wird deshalb bei 100 %. Für 125 … 200 % prüft
``test_caret_on_device_pixels_at_every_scale`` die Geometrie in Gerätepixeln (je Skalierung ein
eigener Prozess – Qt liest die Skalierung nur beim Start).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFontMetricsF, QGuiApplication

from caretutil import FUSS, KOPF, dokument_von, geometrie, js_round, marke_sichtbar, ohne_marke, platzhalter, pruefe_geraetepixel, rechteck, strich_pixel, textfeld, tinte, zeile
from conftest import pump, wait_until
from test_qt_richtext import auswahl, klick, klick_in_text, konfig, oeffne_darstellung, rich_konfig, tippe, waehle_eintrag, zeige  # noqa: F401

from qtapp.contracts.richtext import ZOOM, char_format
from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText

HERE = Path(__file__).resolve().parent
GROESSEN = (8, 10, 12, 14, 18, 24)
LEER = {"kopfzeile": "", "fusszeile": "", "fusszeile_explizit": True}


@pytest.fixture
def dauerhaft():
    """Marke ohne Blinken (für Bildvergleiche); danach wieder die Einstellung des Systems."""
    hints = QGuiApplication.styleHints()
    vorher = hints.cursorFlashTime()
    hints.setCursorFlashTime(0)
    yield
    hints.setCursorFlashTime(vorher)


def schrift_metriken(groesse: float, style=FOOTER_STYLE) -> QFontMetricsF:
    return QFontMetricsF(char_format(style.with_(size=groesse)).font())


def in_feld_klicken(h, editor: str) -> None:
    """In den freien Bereich des Papiers klicken (setzt den Cursor ans Textende)."""
    feld = textfeld(h, editor)
    zeige(h.item(editor))
    klick(h, feld, feld.width() - 30, feld.height() - 6, scrollen=False)
    assert feld.hasActiveFocus()


def setze_cursor(h, editor: str, position: int) -> None:
    """Cursor an ``position`` (Textfeld hat den Fokus) – wie mit den Pfeiltasten, ohne Mausklick
    auf eine Zeichenkante (Klicks dicht hintereinander zählten als Doppelklick)."""
    feld = textfeld(h, editor)
    if not feld.hasActiveFocus():
        in_feld_klicken(h, editor)
    feld.setProperty("cursorPosition", position)
    pump(0.05)
    assert feld.property("cursorPosition") == position


def groessen_fusszeile() -> tuple[RichText, list[str]]:
    """Fußzeile mit je einer Zeile in 8, 10, 12, 14, 18 und 24 pt (linksbündig)."""
    zeilen = [f"Größe {groesse} Hxg" for groesse in GROESSEN]
    styles = []
    for index, (groesse, text) in enumerate(zip(GROESSEN, zeilen)):
        style = FOOTER_STYLE.with_(size=groesse)
        if index:
            styles.append(style)
        styles += [style] * len(text)
    return RichText("\n".join(zeilen), styles, ["left"] * len(zeilen), FOOTER_STYLE, FOOTER_ALIGN), zeilen


# --- 1. Leerer Editor: Marke so hoch wie die Schrift, Platzhalter an derselben Stelle --------------


@pytest.mark.parametrize("konfig", [LEER], indirect=True)
def test_empty_editors_caret_and_placeholder_match_the_text_to_come(konfig, ui_app, dauerhaft) -> None:
    h = ui_app
    oeffne_darstellung(h)
    erwartet = schrift_metriken(HEADER_STYLE.size, HEADER_STYLE)
    for editor, ausrichtung in ((KOPF, Qt.AlignmentFlag.AlignLeft), (FUSS, Qt.AlignmentFlag.AlignHCenter)):
        in_feld_klicken(h, editor)
        feld = textfeld(h, editor)
        # Der leere Absatz hat eine gesetzte Zeile – sonst nähme Qt ersatzweise 10 px oben links
        line = zeile(feld, 0)
        assert line is not None and line.height() > 10
        r = feld.property("cursorRectangle")
        assert r.height() == line.height()
        innen = feld.property("leftPadding")
        textbreite = feld.width() - innen - feld.property("rightPadding")
        if editor == FUSS:  # zentriert: Marke in der Mitte, wo der getippte Text entsteht
            assert abs(r.x() - (innen + textbreite / 2)) <= 1
        else:
            assert r.x() == innen
        # Marke: Schrift des Absatzes (8 pt → im Editor 10 pt), so hoch wie Ober- plus Unterlänge
        g = geometrie(h, editor)
        assert g["ascent"] == pytest.approx(erwartet.ascent()) and g["descent"] == pytest.approx(erwartet.descent())
        assert g["grundlinie"] == pytest.approx(line.ascent())
        pruefe_geraetepixel(g)
        assert g["sichtbar"]
        # Platzhalter: dieselbe Schrift, Ausrichtung und Grundlinie, beginnt an der Marke
        ph = platzhalter(h, editor)
        assert ph.isVisible()
        schrift = ph.property("font")
        assert (schrift.family(), schrift.pointSizeF()) == (dokument_von(h, editor).caretFont.family(), HEADER_STYLE.size * ZOOM)
        oben = ph.mapToScene(QPointF(0, 0))
        assert oben.y() + ph.property("baselineOffset") == pytest.approx(g["cursor"][1] + g["grundlinie"])
        if editor == KOPF:
            assert oben.x() == pytest.approx(g["cursor"][0])
        # Im Bild: 1 px breiter Strich über die ganze Schrifthöhe; der Platzhalter liegt darin
        pixel = strich_pixel(h, editor, pump)
        assert pixel is not None
        assert pixel["x1"] - pixel["x0"] == 1
        assert pixel["y0"] == js_round(g["cursor"][1]) and pixel["y1"] - pixel["y0"] == js_round(erwartet.ascent() + erwartet.descent())
        links = feld.mapToScene(QPointF(innen, 0)).x()
        with ohne_marke(h, editor, pump):
            text = tinte(h, links, g["cursor"][1] - 4, links + textbreite, g["cursor"][1] + 24, hell=230)
        assert text is not None
        assert pixel["y0"] < text["y0"] and text["y1"] <= pixel["y1"]  # innerhalb der Markenhöhe
        if ausrichtung == Qt.AlignmentFlag.AlignLeft:
            assert pixel["x0"] <= text["x0"] <= pixel["x0"] + 3  # beginnt an der Marke
        else:  # zentriert wie der Text, der hier entsteht: Mitte des Platzhalters an der Marke
            assert abs((text["x0"] + text["x1"]) / 2 - pixel["x0"]) <= 3


@pytest.mark.parametrize("konfig", [LEER], indirect=True)
def test_typed_text_appears_exactly_where_the_placeholder_was(konfig, ui_app, dauerhaft) -> None:
    h = ui_app
    oeffne_darstellung(h)
    in_feld_klicken(h, KOPF)
    g = geometrie(h, KOPF)
    ph = platzhalter(h, KOPF)
    ursprung = ph.mapToScene(QPointF(0, ph.property("baselineOffset")))  # Anfang der Grundlinie
    bereich = (g["cursor"][0] - 2, g["cursor"][1] - 4, g["cursor"][0] + 40, g["cursor"][1] + 24)
    with ohne_marke(h, KOPF, pump):
        vorher = tinte(h, *bereich, hell=230)  # Platzhalter »Keine …« (grau)
    tippe(h, "Keine")
    assert not ph.isVisible()
    feld = textfeld(h, KOPF)
    erstes = feld.mapToScene(rechteck(feld, 0).topLeft())
    assert (erstes.x(), erstes.y() + zeile(feld, 0).ascent()) == (pytest.approx(ursprung.x()), pytest.approx(ursprung.y()))
    with ohne_marke(h, KOPF, pump):
        nachher = tinte(h, *bereich, hell=230)  # getippter Text (dunkel), gleiche Schrift
    assert vorher is not None and nachher is not None
    # gleiche Glyphen an gleicher Stelle; ±1 Pixel nur durch die Kantenglättung (grau statt dunkel)
    for kante in ("x0", "y0", "y1"):
        assert abs(nachher[kante] - vorher[kante]) <= 1, (kante, vorher, nachher)


# --- 2. Schriftgrößen: Höhe aus den Font Metrics, auf der Grundlinie ------------------------------


@pytest.mark.parametrize("konfig", [rich_konfig(fuss=groessen_fusszeile()[0])], indirect=True)
def test_caret_height_and_baseline_follow_each_font_size(konfig, ui_app, dauerhaft) -> None:
    h = ui_app
    oeffne_darstellung(h)
    _rich, zeilen = groessen_fusszeile()
    start = 0
    for groesse, text in zip(GROESSEN, zeilen):
        m = schrift_metriken(groesse)
        for position in (start, start + len(text)):
            setze_cursor(h, FUSS, position)
            g = geometrie(h, FUSS)
            assert g["groesse"] == str(groesse)
            assert (g["ascent"], g["descent"]) == (pytest.approx(m.ascent()), pytest.approx(m.descent()))
            assert g["grundlinie"] == pytest.approx(g["zeile"][0])  # Grundlinie der Zeile
            pruefe_geraetepixel(g)
            assert g["strich"][3] <= g["cursor"][2]  # nie höher als die Zeile
            pixel = strich_pixel(h, FUSS, pump)
            assert pixel is not None and pixel["x1"] - pixel["x0"] == 1, (groesse, position, pixel)
            assert pixel["y1"] - pixel["y0"] == js_round(m.ascent() + m.descent()), (groesse, position, pixel)
            # Die Schrift der Zeile (Großbuchstaben bis Unterlänge) liegt innerhalb der Marke. Geprüft
            # werden nur Pixelreihen, die ganz zu dieser Zeile gehören: Liegt die Zeilenkante zwischen
            # zwei Pixeln (Windows), reicht die kantengeglättete Unterlänge der Zeile darüber in die
            # gemeinsame Reihe. Unten ±1 Pixel: Lage und Höhe der Marke sind auf ganze Pixel gerundet.
            links = g["cursor"][0] + 2 if position == start else g["cursor"][0] - 40
            with ohne_marke(h, FUSS, pump):
                text_tinte = tinte(h, links, math.ceil(g["cursor"][1]), links + 38, g["cursor"][1] + g["cursor"][2])
            assert text_tinte is not None
            assert pixel["y0"] < text_tinte["y0"] and text_tinte["y1"] <= pixel["y1"] + 1, (groesse, position, pixel, text_tinte)
        start += len(text) + 1


@pytest.mark.parametrize("konfig", [LEER], indirect=True)
def test_size_chosen_without_selection_resizes_the_caret_at_once(konfig, ui_app, dauerhaft) -> None:
    h = ui_app
    oeffne_darstellung(h)
    in_feld_klicken(h, KOPF)
    waehle_eintrag(h, auswahl(h, KOPF, "Schriftgröße"), "18")  # größte Größe der Formatleiste
    in_feld_klicken(h, KOPF)  # zurück ins Textfeld (Cursor bleibt, die gewählte Größe auch)
    m = schrift_metriken(18, HEADER_STYLE)
    g = geometrie(h, KOPF)
    assert g["groesse"] == "18" and g["ascent"] == pytest.approx(m.ascent())
    pruefe_geraetepixel(g)
    assert js_round(g["strich_geraet"][3]) == js_round(m.ascent() + m.descent())
    # Platzhalter in der gewählten Größe – so, wie der Text gleich aussieht
    assert platzhalter(h, KOPF).property("font").pointSizeF() == 18 * ZOOM
    tippe(h, "X")
    assert h.overview.header_rich().styles[0].size == 18
    g = geometrie(h, KOPF)
    assert g["ascent"] == pytest.approx(m.ascent()) and g["grundlinie"] == pytest.approx(g["zeile"][0])
    pruefe_geraetepixel(g)


# Leerer Absatz zwischen zwei Absätzen: eigenes Format (18 pt), nicht das des nächsten (8 pt)
ABSATZ = RichText(
    "Oben\n\nUnten",
    [FOOTER_STYLE] * 4 + [FOOTER_STYLE.with_(size=18)] + [FOOTER_STYLE] * 6,
    ["left"] * 3,
    FOOTER_STYLE,
    FOOTER_ALIGN,
)


@pytest.mark.parametrize("konfig", [rich_konfig(fuss=ABSATZ)], indirect=True)
def test_empty_paragraph_shows_its_own_format_in_toolbar_and_caret(konfig, ui_app, dauerhaft) -> None:
    h = ui_app
    oeffne_darstellung(h)
    setze_cursor(h, FUSS, 5)  # in die Leerzeile
    m = schrift_metriken(18)
    g = geometrie(h, FUSS)
    assert g["groesse"] == "18" and g["ascent"] == pytest.approx(m.ascent())
    assert g["zeile"][0] == pytest.approx(m.ascent())  # so hat das Textfeld die Leerzeile gesetzt
    pruefe_geraetepixel(g)
    tippe(h, "x")
    assert h.overview.footer_rich().styles[5].size == 18  # getippt wird, was Leiste und Marke zeigen


# --- 3. Fokus und Blinken --------------------------------------------------------------------------


@pytest.mark.parametrize("konfig", [rich_konfig(RichText.plain("Kopf", HEADER_STYLE, HEADER_ALIGN))], indirect=True)
def test_caret_only_while_the_editor_has_text_focus(konfig, ui_app) -> None:
    h = ui_app
    hints = QGuiApplication.styleHints()
    vorher = hints.cursorFlashTime()
    try:
        hints.setCursorFlashTime(0)
        oeffne_darstellung(h)
        assert not marke_sichtbar(h, KOPF) and not marke_sichtbar(h, FUSS)  # ohne Fokus keine Marke
        in_feld_klicken(h, KOPF)
        assert marke_sichtbar(h, KOPF) and not marke_sichtbar(h, FUSS)
        in_feld_klicken(h, FUSS)  # Wechsel: keine veraltete Marke in der Kopfzeile
        assert marke_sichtbar(h, FUSS) and not marke_sichtbar(h, KOPF)
        in_feld_klicken(h, KOPF)
        assert marke_sichtbar(h, KOPF) and not marke_sichtbar(h, FUSS)
        textfeld(h, KOPF).setFocus(False)
        pump(0.1)
        assert not marke_sichtbar(h, KOPF) and not marke_sichtbar(h, FUSS)
        # Blinken wie eingestellt; nach einer Bewegung sofort sichtbar
        hints.setCursorFlashTime(300)
        in_feld_klicken(h, KOPF)
        zustaende = set()
        for _ in range(40):
            pump(0.02)
            zustaende.add(marke_sichtbar(h, KOPF))
        assert zustaende == {True, False}
        assert wait_until(lambda: not marke_sichtbar(h, KOPF), 2)
        klick_in_text(h, KOPF, 1)
        assert marke_sichtbar(h, KOPF)
        assert not marke_sichtbar(h, FUSS)
    finally:
        hints.setCursorFlashTime(vorher)


# --- 4. 100 … 200 %: ganze Gerätepixel ----------------------------------------------------------------


@pytest.mark.parametrize("skalierung", ["1.25", "1.5", "1.75", "2"])
def test_caret_on_device_pixels_at_every_scale(skalierung: str, tmp_path: Path) -> None:
    """Je Skalierung ein eigener Prozess (``caret_geometry.py``): Kopfzeile mit 8 … 24 pt, Marke an
    Zeilenanfang und -ende; leere, zentrierte Fußzeile. 100 % prüfen die Tests oben im Bild."""
    ziel = tmp_path / "geometrie.json"
    env = {**os.environ, "QT_SCALE_FACTOR": skalierung, "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen")}
    lauf = subprocess.run([sys.executable, str(HERE / "caret_geometry.py"), str(ziel)], env=env, capture_output=True, text=True, timeout=180)
    assert lauf.returncode == 0, lauf.stdout + lauf.stderr
    ergebnis = json.loads(ziel.read_text(encoding="utf-8"))
    assert ergebnis["dpr"] == pytest.approx(float(skalierung))
    assert not ergebnis["meldungen"], ergebnis["meldungen"]
    messungen = ergebnis["messungen"]
    assert len(messungen) == 2 * len(GROESSEN) + 1
    for index, g in enumerate(messungen[:-1]):
        groesse = GROESSEN[index // 2]
        m = schrift_metriken(groesse, HEADER_STYLE)
        assert g["groesse"] == str(groesse)
        assert (g["ascent"], g["descent"]) == (pytest.approx(m.ascent()), pytest.approx(m.descent()))
        pruefe_geraetepixel(g)
    leer = messungen[-1]  # leere Fußzeile: Mitte, Schrifthöhe des Absatzes
    pruefe_geraetepixel(leer)
    innen_links, innen_rechts = leer["innen"]
    mitte = leer["szene_feld_x"] + innen_links + (leer["breite_feld"] - innen_links - innen_rechts) / 2
    assert abs(leer["cursor"][0] - mitte) <= 1
