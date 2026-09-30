"""Kopf- und Fußzeile in der Qt-Oberfläche – so bedient und geprüft, wie ein Benutzer sie sieht.

Ursache des Fehlers in 2.7.0 (vor dieser Korrektur): Das Textfeld des Editors (``T.TextArea`` aus
QtQuick.Templates) hatte keine aus dem Inhalt berechnete Größe. Die Vorlage schaltet das bewusst ab
(das übernimmt sonst ein Stil) – das Feld blieb 14 px hoch. Qt zeichnet den Text nur innerhalb des
Felds: Kopf- und Fußzeile erschienen leer, obwohl sie geladen waren; Klicks unterhalb der ersten
Zeile erreichten das Feld nicht (kein Cursor, keine Markierung mit der Maus); längere Texte ließen
sich nicht scrollen. Zusätzlich fügte Umschalt+Eingabe keinen Absatz ein (»\\n« wurde als HTML
eingefügt und verschwand). Die bisherigen Tests lasen nur das Dokument (``toPlainText``) und
bedienten die Leiste über Signale – sie merkten davon nichts.

Diese Tests prüfen deshalb:

* das tatsächlich gezeichnete Bild (dunkle Pixel an jeder Textzeile, auch der letzten),
* echte Mausklicks und -züge ins Textfeld, auf die Formatleiste, in Auswahllisten und Farbfelder,
* Tastatur (Tippen, Strg+A, Umschalt+Eingabe),
* Speichern über die Schaltflächen, Seitenwechsel, Neustart, Vorschau und erzeugte PDF.

Nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben (Fixture ``ui_app``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, QPoint, QPointF, QRectF, Qt
from PySide6.QtTest import QTest

from conftest import neustart, pump, wait_until
from qtutil import qml_type

import appstate
from appstate import DEFAULT_FOOTER, default_footer_rich
from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText

KOPF = "headerEditor"
FUSS = "footerEditor"
ROT = "#B51F1F"
PDF_NAME = "Vertragsuebersicht_Kd10042.pdf"
# »Test {firma}«: »Test « normal, »{firma}« fett, alles 10 pt, zentriert (Prüfung aus dem Fix-Auftrag)
TEST_FIRMA = RichText(
    "Test {firma}",
    [HEADER_STYLE.with_(size=10)] * 5 + [HEADER_STYLE.with_(size=10, bold=True)] * 7,
    ["center"],
    HEADER_STYLE,
    HEADER_ALIGN,
)


# --- Hilfen: Elemente ----------------------------------------------------------------------------


def elemente(wurzel) -> list:
    """Alle QML-Elemente unter ``wurzel`` (Elementbaum, auch aus Loadern)."""
    alle, stapel = [], [wurzel]
    while stapel:
        aktuell = stapel.pop()
        alle.append(aktuell)
        stapel.extend(aktuell.childItems())
    return alle


def element(wurzel, **werte):
    treffer = [e for e in elemente(wurzel) if all(e.property(k) == v for k, v in werte.items())]
    assert treffer, f"Kein Element mit {werte}"
    return treffer[0]


def textfeld(h, editor: str):
    return next(e for e in elemente(h.item(editor)) if e.inherits("QQuickTextEdit"))


def papier(h, editor: str):
    """Das weiße »Papier« um das Textfeld (Rahmen, Hintergrund)."""
    feld = textfeld(h, editor)
    return feld.parentItem().parentItem().parentItem()  # Textfeld → Inhalt → Flickable → Papier


def dokument(h, editor: str):
    return textfeld(h, editor).property("textDocument").textDocument()


def leistenknopf(h, editor: str, tip: str):
    return element(h.item(editor), tip=tip)


def auswahl(h, editor: str, label: str):
    return element(h.item(editor), label=label)


def seitenknopf(h, text: str):
    return next(e for e in elemente(h.item("page_layout")) if qml_type(e) == "PButton" and e.property("text") == text)


# --- Hilfen: echte Eingaben ------------------------------------------------------------------------


def seite(item):
    """Äußerste Flickable über ``item`` (die scrollende Seite)."""
    gefunden, aktuell = None, item.parentItem()
    while aktuell is not None:
        if aktuell.inherits("QQuickFlickable"):
            gefunden = aktuell
        aktuell = aktuell.parentItem()
    return gefunden


def zeige(item) -> None:
    """Seite so scrollen, dass ``item`` im oberen Drittel sichtbar ist (wie der Benutzer es tut)."""
    flick = seite(item)
    if flick is None:
        return
    oben = item.mapToItem(flick.property("contentItem"), QPointF(0, 0)).y()
    hoehe = flick.height()
    groesste = max(0.0, flick.property("contentHeight") - hoehe)
    flick.setProperty("contentY", min(groesste, max(0.0, oben - hoehe / 3)))
    pump(0.05)


def fensterpunkt(item, x: float, y: float) -> QPoint:
    p = item.mapToScene(QPointF(x, y))
    return QPoint(round(p.x()), round(p.y()))


def klick(h, item, x: float | None = None, y: float | None = None, scrollen: bool = True) -> None:
    """Echter Mausklick (Drücken + Loslassen) auf ``item`` – standardmäßig in die Mitte."""
    if scrollen:
        zeige(item)
    x = item.width() / 2 if x is None else x
    y = item.height() / 2 if y is None else y
    QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, fensterpunkt(item, x, y))
    pump(0.08)


def zeichenrechteck(feld, position: int) -> QRectF:
    """Cursor-Rechteck vor dem Zeichen ``position`` (Koordinaten des Textfelds)."""
    return QMetaObject.invokeMethod(feld, "positionToRectangle", Q_RETURN_ARG("QRectF"), Q_ARG(int, position))


def markiere_mit_maus(h, editor: str, von: int, bis: int) -> None:
    """Text mit gedrückter Maustaste markieren (von Zeichen ``von`` bis vor Zeichen ``bis``)."""
    feld = textfeld(h, editor)
    zeige(h.item(editor))
    start, ende = zeichenrechteck(feld, von), zeichenrechteck(feld, bis)
    a = fensterpunkt(feld, start.x() + 0.5, start.y() + start.height() / 2)
    b = fensterpunkt(feld, ende.x() + 0.5, ende.y() + ende.height() / 2)
    QTest.mousePress(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    for schritt in range(1, 11):
        QTest.mouseMove(h.window, QPoint(a.x() + (b.x() - a.x()) * schritt // 10, a.y() + (b.y() - a.y()) * schritt // 10))
        pump(0.01)
    QTest.mouseRelease(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    pump(0.05)
    assert (feld.property("selectionStart"), feld.property("selectionEnd")) == (von, bis)


def klick_in_text(h, editor: str, position: int) -> None:
    """Mit der Maus vor das Zeichen ``position`` klicken."""
    feld = textfeld(h, editor)
    zeige(h.item(editor))
    r = zeichenrechteck(feld, position)
    klick(h, feld, r.x() + 0.5, r.y() + r.height() / 2, scrollen=False)
    assert feld.property("cursorPosition") == position


def tippe(h, text: str) -> None:
    """Tastatureingabe Zeichen für Zeichen; Umlaute und ß als echte Tastenereignisse mit Text
    (``QTest.keyClick`` mit einem Zeichen kennt nur ASCII)."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QGuiApplication, QKeyEvent

    for zeichen in text:
        if zeichen.isascii():
            QTest.keyClick(h.window, zeichen)
            continue
        for art in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QGuiApplication.sendEvent(h.window, QKeyEvent(art, 0, Qt.KeyboardModifier.NoModifier, zeichen))
    pump(0.05)


def taste(h, key, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    QTest.keyClick(h.window, key, modifiers)
    pump(0.03)


def waehle_eintrag(h, liste, text: str) -> None:
    """Auswahlliste mit der Maus öffnen und den Eintrag ``text`` anklicken."""
    klick(h, liste)
    pump(0.3)  # Einblendung der Liste
    wurzel = h.window.contentItem()  # Wurzel des Fensters samt Overlay der Aufklappliste
    eintraege = [e for e in elemente(wurzel) if e.property("itemText") == text and e.isVisible() and e.width() > 0]
    assert eintraege, f"Eintrag {text!r} nicht in der Liste"
    klick(h, eintraege[0], scrollen=False)
    pump(0.3)


def waehle_farbe(h, editor: str, name: str, wert: str) -> None:
    """Schriftfarbe über das »A« der Leiste und das Farbfeld ``name`` wählen."""
    klick(h, element(h.item(editor), objectName="colorButton"))
    pump(0.3)
    wurzel = h.window.contentItem()
    feld = next(e for e in elemente(wurzel) if e.property("tip") == f"{name} ({wert})" and e.isVisible())
    klick(h, feld, scrollen=False)
    pump(0.3)


# --- Hilfen: Bild -------------------------------------------------------------------------------


def tinte(h, editor: str, position: int, breite: float = 60.0) -> int:
    """Dunkle Pixel (Text) in der Zeile des Zeichens ``position`` – was tatsächlich gezeichnet ist.

    Gezählt wird nur innerhalb des sichtbaren Papiers: Liegt die Zeile außerhalb (abgeschnitten,
    nicht erreichbar), ist das Ergebnis 0.
    """
    feld = textfeld(h, editor)
    bild = h.window.grabWindow()
    faktor = bild.devicePixelRatio()
    r = zeichenrechteck(feld, position)
    zeile = QRectF(r.x() - breite / 2, r.y(), breite, r.height())
    blatt = papier(h, editor)
    sichtbar = QRectF(blatt.mapToScene(QPointF(1, 1)), blatt.mapToScene(QPointF(blatt.width() - 1, blatt.height() - 1)))
    bereich = QRectF(feld.mapToScene(zeile.topLeft()), feld.mapToScene(zeile.bottomRight())).intersected(sichtbar)
    if bereich.isEmpty():
        return 0
    dunkel = 0
    for py in range(int(bereich.top() * faktor), int(bereich.bottom() * faktor)):
        for px in range(int(bereich.left() * faktor), int(bereich.right() * faktor)):
            farbe = bild.pixelColor(px, py)
            if (farbe.red() + farbe.green() + farbe.blue()) / 3 < 140:
                dunkel += 1
    return dunkel


def tinte_mitte(h, editor: str) -> float:
    """Waagerechte Mitte der dunklen Pixel im Papier (für die Ausrichtung) – relativ 0 … 1."""
    blatt = papier(h, editor)
    bild = h.window.grabWindow()
    faktor = bild.devicePixelRatio()
    links, oben = blatt.mapToScene(QPointF(2, 2)).x(), blatt.mapToScene(QPointF(2, 2)).y()
    rechts, unten = blatt.mapToScene(QPointF(blatt.width() - 2, blatt.height() - 3)).x(), blatt.mapToScene(QPointF(2, blatt.height() - 3)).y()
    xs = []
    for py in range(int(oben * faktor), int(unten * faktor), 2):
        for px in range(int(links * faktor), int(rechts * faktor)):
            farbe = bild.pixelColor(px, py)
            if (farbe.red() + farbe.green() + farbe.blue()) / 3 < 140:
                xs.append(px / faktor)
    assert xs, "Kein Text im Papier gezeichnet"
    mitte = (min(xs) + max(xs)) / 2
    return (mitte - links) / (rechts - links)


def zeilenanfaenge(text: str) -> list[int]:
    """Erstes Zeichen jedes nicht leeren Absatzes."""
    anfaenge, start = [], 0
    for zeile in text.split("\n"):
        if zeile:
            anfaenge.append(start)
        start += len(zeile) + 1
    return anfaenge


def pruefe_sichtbar(h, editor: str) -> None:
    """Jeder nicht leere Absatz ist gezeichnet – vom ersten bis zum letzten Zeichen."""
    feld = textfeld(h, editor)
    text = dokument(h, editor).toPlainText()
    assert feld.height() >= feld.implicitHeight() - 0.5 or seite(feld) is not None
    for anfang in zeilenanfaenge(text):
        assert tinte(h, editor, anfang + 1) > 15, f"{editor}: Absatz ab Zeichen {anfang} nicht gezeichnet"
    if text.strip():
        assert tinte(h, editor, len(text.rstrip()) - 1) > 15, f"{editor}: Textende nicht gezeichnet"


# --- Hilfen: Konfiguration --------------------------------------------------------------------------


def lies(config_file: Path) -> dict:
    return json.loads(config_file.read_text(encoding="utf-8"))


@pytest.fixture
def konfig(request, config_file: Path) -> dict:
    """Gespeicherte Einstellungen, bevor die App startet (vor ``ui_app`` anfordern)."""
    daten = {"gesehen": appstate.VERSION, "theme": "light", "accent": "#005FB8", "kundenakte_verwenden": True, "animationsprofil": "full", **getattr(request, "param", {})}
    config_file.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    return daten


def rich_konfig(kopf: RichText | None = None, fuss: RichText | None = None) -> dict:
    daten: dict = {"firmenname": "Muster GmbH"}
    if kopf is not None:
        daten.update({"kopfzeile": kopf.text, "kopfzeile_format": kopf.to_dict()})
    if fuss is not None:
        daten.update({"fusszeile": fuss.text, "fusszeile_format": fuss.to_dict(), "fusszeile_explizit": True})
    return daten


def excel_pruefen(h, excel_file: Path, ziel: Path) -> None:
    """Excel-Liste wählen und die Prüfung abwarten (Kundennummer 10042, »Muster GmbH«)."""
    o = h.overview
    o.ziel, o.pdfOeffnen, o.excel = str(ziel), False, str(excel_file)
    o.inspect_excel(str(excel_file))
    assert wait_until(lambda: h.app.notices.get("info_excel").severity == "success", 60)
    assert o.kd == "10042" and o.firma == "Muster GmbH"


def oeffne_darstellung(h) -> None:
    h.navigate("layout", 0.5)
    zeige(h.item(KOPF))


# --- 1. Laden: gespeicherte Kopf- und Fußzeile werden angezeigt -------------------------------------


@pytest.mark.parametrize("konfig", [rich_konfig(TEST_FIRMA)], indirect=True)
def test_saved_header_and_footer_are_visible(konfig, ui_app) -> None:
    h = ui_app
    oeffne_darstellung(h)
    # Modell, Dokument des Textfelds und Bild stimmen überein
    assert h.overview.header_rich() == TEST_FIRMA
    assert dokument(h, KOPF).toPlainText() == "Test {firma}"
    pruefe_sichtbar(h, KOPF)
    assert abs(tinte_mitte(h, KOPF) - 0.5) < 0.05  # zentriert gezeichnet
    zeige(h.item(FUSS))
    assert dokument(h, FUSS).toPlainText() == DEFAULT_FOOTER
    pruefe_sichtbar(h, FUSS)  # alle drei Absätze, auch der letzte nach der Leerzeile
    # Das Textfeld füllt das Papier; das Papier wächst mit dem Inhalt
    for editor in (KOPF, FUSS):
        feld, blatt = textfeld(h, editor), papier(h, editor)
        assert feld.height() >= feld.implicitHeight() - 0.5
        assert feld.height() >= blatt.height() - 2.5
        assert blatt.height() >= min(feld.implicitHeight(), 14 * 20) + 1.5


@pytest.mark.parametrize("konfig", [rich_konfig(fuss=RichText.plain("\n".join(f"Zeile {n}" for n in range(1, 31)), FOOTER_STYLE, FOOTER_ALIGN))], indirect=True)
def test_long_footer_scrolls_and_every_line_is_reachable(konfig, ui_app) -> None:
    h = ui_app
    oeffne_darstellung(h)
    feld, blatt = textfeld(h, FUSS), papier(h, FUSS)
    flick = feld.parentItem().parentItem()
    assert blatt.height() == pytest.approx(14 * 20 + 2, abs=1)  # höchstens 14 Zeilen hoch …
    assert flick.property("interactive") is True  # … darüber scrollt das Textfeld
    zeige(h.item(FUSS))
    klick(h, feld, 20, blatt.height() - 12, scrollen=False)  # unten ins Papier
    taste(h, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    pump(0.2)
    text = dokument(h, FUSS).toPlainText()
    assert feld.property("cursorPosition") == len(text)
    assert flick.property("contentY") > 0  # zur letzten Zeile gescrollt
    assert tinte(h, FUSS, len(text) - 2) > 15  # »Zeile 30« ist zu sehen


def test_click_below_text_places_cursor_at_end(ui_app) -> None:
    h = ui_app
    oeffne_darstellung(h)
    zeige(h.item(FUSS))
    feld, blatt = textfeld(h, FUSS), papier(h, FUSS)
    klick(h, feld, feld.width() / 2, blatt.height() - 6, scrollen=False)  # freier Bereich unter dem Text
    assert feld.hasActiveFocus()
    assert feld.property("cursorPosition") == len(DEFAULT_FOOTER)


# --- 2. Kopfzeile »Test {firma}«: bearbeiten, speichern, neu laden ----------------------------------------


def test_header_test_firma_roundtrip(ui_app, config_file: Path) -> None:
    h = ui_app
    oeffne_darstellung(h)
    feld = textfeld(h, KOPF)
    assert h.overview.header_text() == ""
    klick(h, papier(h, KOPF))  # in das leere Papier klicken und tippen
    assert feld.hasActiveFocus()
    tippe(h, "Test {firma}")
    assert h.overview.header_text() == "Test {firma}"
    # alles markieren → Schriftgröße 10 in der Auswahlliste
    taste(h, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    waehle_eintrag(h, auswahl(h, KOPF, "Schriftgröße"), "10")
    # »{firma}« mit der Maus markieren → Fett
    markiere_mit_maus(h, KOPF, 5, 12)
    klick(h, leistenknopf(h, KOPF, "Fett (Strg+B)"))
    # zentrieren und speichern
    klick(h, leistenknopf(h, KOPF, "Zentriert (Strg+E)"))
    klick(h, seitenknopf(h, "Kopfzeile speichern"))
    assert h.app.notices.get("kopf_info").message == "Die Kopfzeile wurde gespeichert."
    assert h.overview.header_rich() == TEST_FIRMA
    gespeichert = lies(config_file)
    assert gespeichert["kopfzeile"] == "Test {firma}"
    assert RichText.from_storage(gespeichert["kopfzeile"], gespeichert["kopfzeile_format"], HEADER_STYLE, HEADER_ALIGN) == TEST_FIRMA
    assert gespeichert["kopfzeile_format"]["paragraphs"] == [{"start": 0, "end": 12, "alignment": "center"}]
    # neu laden: alle Werte identisch – im Modell, im Textfeld, im Bild und in der Formatleiste
    h = neustart(h)
    oeffne_darstellung(h)
    assert h.overview.header_rich() == TEST_FIRMA
    from qtapp.contracts.richtext import document_rich

    assert document_rich(dokument(h, KOPF), HEADER_STYLE, HEADER_ALIGN) == TEST_FIRMA
    pruefe_sichtbar(h, KOPF)
    klick_in_text(h, KOPF, 8)  # Cursor in »{firma}«
    kopf = h.overview.header
    assert (kopf.bold, kopf.italic, kopf.fontSize, kopf.fontFamily, kopf.alignment) == (True, False, "10", "Helvetica", "center")
    assert leistenknopf(h, KOPF, "Fett (Strg+B)").property("active") is True
    assert leistenknopf(h, KOPF, "Zentriert (Strg+E)").property("active") is True
    assert auswahl(h, KOPF, "Schriftgröße").property("displayText") == "10"
    klick_in_text(h, KOPF, 2)  # Cursor in »Test«
    assert (kopf.bold, kopf.fontSize) == (False, "10")
    assert leistenknopf(h, KOPF, "Fett (Strg+B)").property("active") is False


# --- 3. Standard-Fußzeile wiederherstellen, speichern, neu laden ----------------------------------------


def test_footer_restore_default_save_reload(ui_app, config_file: Path) -> None:
    h = ui_app
    oeffne_darstellung(h)
    zeige(h.item(FUSS))
    klick(h, papier(h, FUSS))
    taste(h, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    tippe(h, "Eigener Text")
    klick(h, leistenknopf(h, FUSS, "Fett (Strg+B)"))  # ohne Markierung: für den nächsten Text
    tippe(h, " fett")
    assert h.overview.footer_text() == "Eigener Text fett"
    klick(h, seitenknopf(h, "Standard wiederherstellen"))
    assert h.overview.footer_rich() == default_footer_rich()
    assert dokument(h, FUSS).toPlainText() == DEFAULT_FOOTER  # Editor sofort aktualisiert
    pruefe_sichtbar(h, FUSS)
    klick(h, seitenknopf(h, "Fußzeile speichern"))
    gespeichert = lies(config_file)
    assert gespeichert["fusszeile"] == DEFAULT_FOOTER and gespeichert["fusszeile_explizit"] is True
    h = neustart(h)
    oeffne_darstellung(h)
    fuss = h.overview.footer_rich()
    assert fuss == default_footer_rich()
    # Text und Absatzstruktur identisch: vier Absätze, der dritte ist die Leerzeile
    absaetze = [(fuss.text[s:e], a) for s, e, a in fuss.paragraphs()]
    assert [t for t, _a in absaetze] == DEFAULT_FOOTER.split("\n")
    assert absaetze[2] == ("", "center") and len(absaetze) == 4
    assert {a for _t, a in absaetze} == {"center"}
    assert dokument(h, FUSS).blockCount() == 4
    zeige(h.item(FUSS))
    pruefe_sichtbar(h, FUSS)


# --- 4. Kein Formatverlust: markieren → Fett, Kursiv, Farbe, Größe → speichern → Tab → Neustart ------------


def test_formatting_survives_tab_switch_and_restart(ui_app, config_file: Path) -> None:
    h = ui_app
    oeffne_darstellung(h)
    zeige(h.item(FUSS))
    wort = "Auflistung"
    start = DEFAULT_FOOTER.index(wort)
    markiere_mit_maus(h, FUSS, start, start + len(wort))
    klick(h, leistenknopf(h, FUSS, "Fett (Strg+B)"))
    klick(h, leistenknopf(h, FUSS, "Kursiv (Strg+I)"))
    waehle_farbe(h, FUSS, "Rot", ROT)
    waehle_eintrag(h, auswahl(h, FUSS, "Schriftgröße"), "12")
    erwartet = h.overview.footer_rich()
    stil = erwartet.styles[start]
    assert (stil.bold, stil.italic, stil.color, stil.size) == (True, True, ROT, 12)
    assert erwartet.styles[start - 1] == FOOTER_STYLE and erwartet.styles[start + len(wort)] == FOOTER_STYLE
    klick(h, seitenknopf(h, "Fußzeile speichern"))
    feld_vorher = shiboken6.getCppPointer(textfeld(h, FUSS))[0]
    # Seitenwechsel: Inhalt bleibt, das Textfeld wird nicht neu aufgebaut
    for ziel in ("create", "preview", "layout"):
        h.navigate(ziel, 0.3)
    assert shiboken6.getCppPointer(textfeld(h, FUSS))[0] == feld_vorher
    assert h.overview.footer.attached and h.overview.footer_rich() == erwartet
    # App schließen, neu starten
    h = neustart(h)
    oeffne_darstellung(h)
    assert h.overview.footer_rich() == erwartet
    from qtapp.contracts.richtext import document_rich

    assert document_rich(dokument(h, FUSS), FOOTER_STYLE, FOOTER_ALIGN) == erwartet
    zeige(h.item(FUSS))
    klick_in_text(h, FUSS, start + 3)
    fuss = h.overview.footer
    assert (fuss.bold, fuss.italic, fuss.color, fuss.fontSize) == (True, True, ROT, "12")


# --- 5. Ausrichtung ist Absatzformat; Formatleiste folgt dem Cursor ---------------------------------------


@pytest.mark.parametrize(
    "konfig",
    [rich_konfig(RichText("Normal\nFett", [HEADER_STYLE] * 7 + [HEADER_STYLE.with_(bold=True)] * 4, ["left", "right"], HEADER_STYLE, HEADER_ALIGN))],
    indirect=True,
)
def test_alignment_is_paragraph_format_and_toolbar_follows_cursor(konfig, ui_app) -> None:
    h = ui_app
    oeffne_darstellung(h)
    kopf = h.overview.header
    fett, rechts = leistenknopf(h, KOPF, "Fett (Strg+B)"), leistenknopf(h, KOPF, "Rechtsbündig (Strg+R)")
    klick_in_text(h, KOPF, 9)  # in »Fett«
    assert kopf.bold and kopf.alignment == "right"
    assert fett.property("active") is True and rechts.property("active") is True
    klick_in_text(h, KOPF, 3)  # in »Normal«
    assert not kopf.bold and kopf.alignment == "left"
    assert fett.property("active") is False and leistenknopf(h, KOPF, "Linksbündig (Strg+L)").property("active") is True
    # Zentrieren wirkt nur auf den Absatz des Cursors – als Absatzformat im Dokument und im Modell
    klick(h, leistenknopf(h, KOPF, "Zentriert (Strg+E)"))
    assert h.overview.header_rich().aligns == ["center", "right"]
    block = dokument(h, KOPF).begin()
    assert block.blockFormat().alignment() & Qt.AlignmentFlag.AlignHCenter
    assert block.next().blockFormat().alignment() & Qt.AlignmentFlag.AlignRight
    assert h.overview.header_rich().text == "Normal\nFett"  # Text unverändert


# --- 6. Rückgängig/Wiederholen: Schaltflächen nur aktiv, wenn verfügbar -----------------------------------


def test_undo_redo_buttons_follow_availability(ui_app) -> None:
    h = ui_app
    oeffne_darstellung(h)
    rueck, wieder = leistenknopf(h, KOPF, "Rückgängig (Strg+Z)"), leistenknopf(h, KOPF, "Wiederholen (Strg+Y)")
    assert not rueck.property("enabled") and not wieder.property("enabled")  # nach dem Laden
    klick(h, papier(h, KOPF))
    tippe(h, "Hallo")
    assert rueck.property("enabled") and not wieder.property("enabled")
    klick(h, rueck)
    assert h.overview.header_text() == ""
    assert wieder.property("enabled")
    klick(h, wieder)
    assert h.overview.header_text() == "Hallo"
    # Formatierung ist ebenfalls rückgängig machbar
    taste(h, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    klick(h, leistenknopf(h, KOPF, "Kursiv (Strg+I)"))
    assert all(s.italic for s in h.overview.header_rich().styles)
    klick(h, rueck)
    assert not any(s.italic for s in h.overview.header_rich().styles) and h.overview.header_text() == "Hallo"
    # Neu geladener Inhalt (Vorlage, Textbaustein) beginnt einen neuen Verlauf
    h.overview.set_header(RichText.plain("Neu", HEADER_STYLE, HEADER_ALIGN))
    pump(0.05)
    assert not rueck.property("enabled") and not wieder.property("enabled")


def test_shift_enter_starts_a_new_paragraph(ui_app) -> None:
    h = ui_app
    oeffne_darstellung(h)
    klick(h, papier(h, KOPF))
    tippe(h, "Oben")
    taste(h, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    tippe(h, "Unten")
    assert h.overview.header_text() == "Oben\nUnten"
    assert dokument(h, KOPF).blockCount() == 2
    pruefe_sichtbar(h, KOPF)


# --- 7. Textbausteine: speichern, benennen, auswählen, laden, überschreiben, löschen ------------------------


def test_text_blocks_full_cycle_with_formatting(ui_app, config_file: Path) -> None:
    h = ui_app
    o = h.overview
    oeffne_darstellung(h)
    zeige(h.item(FUSS))
    klick(h, papier(h, FUSS))
    taste(h, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    tippe(h, "Mit freundlichen Grüßen")
    markiere_mit_maus(h, FUSS, 4, 15)  # »freundlichen«
    klick(h, leistenknopf(h, FUSS, "Fett (Strg+B)"))
    gruss = o.footer_rich()
    # Namen vergeben (Eingabefeld) und speichern
    name = element(h.item("page_layout"), label="Name des Textbausteins")
    klick(h, name)
    tippe(h, "Gruß")
    assert o.baustein == "Gruß"
    klick(h, seitenknopf(h, "Fußzeile speichern"))
    eintrag = h.app.state.find_baustein("Gruß")
    # Format wie 2.6.1: Name, reiner Text und Formatierung unter »format«
    assert set(eintrag) == {"name", "text", "format"}
    assert eintrag["text"] == "Mit freundlichen Grüßen"
    assert RichText.from_storage(eintrag["text"], eintrag["format"], FOOTER_STYLE, FOOTER_ALIGN) == gruss
    assert lies(config_file)["bausteine"][0]["name"] == "Gruß"
    # Anderer Text, dann den Baustein in der Auswahlliste wählen → geladen samt Formatierung
    klick(h, seitenknopf(h, "Standard wiederherstellen"))
    assert o.footer_text() == DEFAULT_FOOTER
    waehle_eintrag(h, element(h.item("page_layout"), label="Textbaustein"), "Gruß")
    assert o.footer_rich() == gruss
    assert dokument(h, FUSS).toPlainText() == "Mit freundlichen Grüßen"
    pruefe_sichtbar(h, FUSS)
    # Überschreiben: geänderter Text unter demselben Namen – ein Eintrag, neuer Inhalt
    klick_in_text(h, FUSS, len("Mit freundlichen Grüßen"))
    tippe(h, "!")
    klick(h, seitenknopf(h, "Fußzeile speichern"))
    assert [b["name"] for b in h.app.state.bausteine].count("Gruß") == 1
    assert h.app.state.find_baustein("Gruß")["text"] == "Mit freundlichen Grüßen!"
    # nach dem Neustart vorhanden und wählbar
    h = neustart(h)
    o = h.overview
    oeffne_darstellung(h)
    waehle_eintrag(h, element(h.item("page_layout"), label="Textbaustein"), "Gruß")
    assert o.footer_text() == "Mit freundlichen Grüßen!" and o.footer_rich().styles[5].bold
    # löschen (Rückfrage wird bestätigt)
    klick(h, seitenknopf(h, "Textbaustein löschen"))
    assert h.app.state.find_baustein("Gruß") is None and o.baustein == ""
    assert "Gruß" not in [b.get("name") for b in lies(config_file).get("bausteine", [])]


@pytest.mark.parametrize("konfig", [{"bausteine": [{"name": "Alt", "text": "Alter Baustein\n\nZweiter Absatz"}]}], indirect=True)
def test_text_block_without_format_loads_with_default_formatting(konfig, ui_app) -> None:
    h = ui_app
    oeffne_darstellung(h)
    waehle_eintrag(h, element(h.item("page_layout"), label="Textbaustein"), "Alt")
    assert h.overview.footer_rich() == RichText.plain("Alter Baustein\n\nZweiter Absatz", FOOTER_STYLE, FOOTER_ALIGN)
    zeige(h.item(FUSS))
    pruefe_sichtbar(h, FUSS)
    # Das gespeicherte Format des Bausteins bleibt unverändert (keine stille Umstellung)
    assert h.app.state.find_baustein("Alt") == {"name": "Alt", "text": "Alter Baustein\n\nZweiter Absatz"}


# --- 8. Alte Daten: reiner Text und fehlende Formatangaben ------------------------------------------------


@pytest.mark.parametrize(
    "konfig",
    [
        {"kopfzeile": "Kopf {kd}\nZweite Zeile", "fusszeile": "Fuß alt\n\nletzte Zeile"},  # bis 2.1: nur Text
        {
            "kopfzeile": "Teilweise",
            "kopfzeile_format": {"version": 1, "text": "Teilweise", "spans": [{"start": 0, "end": 4, "bold": True}]},
            "fusszeile": "Fuß alt\n\nletzte Zeile",
            "fusszeile_format": {"text": "passt nicht"},  # Formatierung gehört zu einem anderen Text
        },
    ],
    indirect=True,
    ids=["nur-text", "unvollstaendig"],
)
def test_old_header_and_footer_data_load(konfig, ui_app) -> None:
    h = ui_app
    oeffne_darstellung(h)
    kopf, fuss = h.overview.header_rich(), h.overview.footer_rich()
    assert kopf.text == konfig["kopfzeile"] and fuss.text == "Fuß alt\n\nletzte Zeile"
    if "kopfzeile_format" in konfig:
        assert [s.bold for s in kopf.styles] == [True] * 4 + [False] * 5  # fehlende Felder: Standard
        assert {(s.font, s.size, s.color) for s in kopf.styles} == {("Helvetica", 8, "#333333")}
    else:
        assert kopf == RichText.plain(konfig["kopfzeile"], HEADER_STYLE, HEADER_ALIGN)
    assert fuss == RichText.plain("Fuß alt\n\nletzte Zeile", FOOTER_STYLE, FOOTER_ALIGN)
    pruefe_sichtbar(h, KOPF)
    zeige(h.item(FUSS))
    pruefe_sichtbar(h, FUSS)


# --- 9. Leere Kopfzeile ist erlaubt ---------------------------------------------------------------------------


@pytest.mark.parametrize("konfig", [rich_konfig(RichText.plain("Weg damit", HEADER_STYLE, HEADER_ALIGN))], indirect=True)
def test_empty_header_is_allowed(konfig, ui_app, config_file: Path, excel_file: Path, tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    h = ui_app
    oeffne_darstellung(h)
    klick(h, papier(h, KOPF))
    taste(h, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    taste(h, Qt.Key.Key_Delete)
    assert h.overview.header_text() == ""
    klick(h, seitenknopf(h, "Kopfzeile speichern"))
    assert h.app.notices.get("kopf_info").message == "Die Kopfzeile ist leer und erscheint nicht in der PDF."
    assert lies(config_file)["kopfzeile"] == ""
    h = neustart(h)
    oeffne_darstellung(h)
    assert h.overview.header_text() == ""  # kein automatisch eingesetzter Text
    hinweis = next(e for e in elemente(h.item(KOPF)) if qml_type(e) == "QQuickText" and str(e.property("text")).startswith("Keine Kopfzeile"))
    assert hinweis.isVisible()  # nur ein Hinweis im leeren Feld, kein Inhalt
    o = h.overview
    excel_pruefen(h, excel_file, tmp_path)
    o.start_pdf()
    assert wait_until(lambda: not o.busy, 90)
    text = pypdf.PdfReader(str(tmp_path / PDF_NAME)).pages[0].extract_text()
    assert "Weg damit" not in text and "Seite 1 von 1" in text


# --- 10. PDF und Vorschau: Kopf-/Fußzeile, Platzhalter, Formatierung, Seitenzahl --------------------------


def _pdf_texte(pfad: Path) -> list[tuple[str, str, float, float]]:
    """(Text, Schrift, x, y) aller Textstücke der ersten Seite."""
    import pypdf

    stuecke: list[tuple[str, str, float, float]] = []

    def besuch(text, cm, tm, font_dict, font_size):
        if text.strip():
            name = str((font_dict or {}).get("/BaseFont", ""))
            stuecke.append((text, name, tm[4], tm[5]))

    pypdf.PdfReader(str(pfad)).pages[0].extract_text(visitor_text=besuch)
    return stuecke


FUSS_PLATZHALTER = RichText(
    "Kd {kd} – {kunde}\n\nStand {datumkurz}",
    [FOOTER_STYLE] * 3 + [FOOTER_STYLE.with_(bold=True)] * 4 + [FOOTER_STYLE] * (len("Kd {kd} – {kunde}\n\nStand {datumkurz}") - 7),
    ["center", "center", "right"],
    FOOTER_STYLE,
    FOOTER_ALIGN,
)


@pytest.mark.parametrize("konfig", [rich_konfig(TEST_FIRMA, FUSS_PLATZHALTER)], indirect=True)
def test_pdf_and_preview_show_formatted_header_footer_with_placeholders(konfig, ui_app, excel_file: Path, tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    import pypdf
    from datetime import datetime

    h = ui_app
    o = h.overview
    excel_pruefen(h, excel_file, tmp_path)
    # Vorschau öffnen: dieselbe Erzeugung wie »PDF erstellen«
    h.navigate("preview", 0.2)
    assert wait_until(lambda: h.preview.state == "current", 90), h.preview.problem
    vorschau = pypdf.PdfReader(str(h.preview._doc.path)).pages[0].extract_text()
    o.start_pdf()
    assert wait_until(lambda: not o.busy, 90)
    assert h.app.notices.get("pdf_info").severity == "success", h.app.notices.get("pdf_info").message
    pdf = tmp_path / PDF_NAME
    text = pypdf.PdfReader(str(pdf)).pages[0].extract_text()
    heute = datetime.now().strftime("%d.%m.%Y")  # {datumkurz}
    for erwartet in ("Test Muster GmbH", "Kd 10042 – Muster GmbH", f"Stand {heute}", "Seite 1 von 1"):
        assert erwartet in text, erwartet
        assert erwartet in vorschau, erwartet  # Vorschau zeigt dieselben Daten wie der Export
    assert "{firma}" not in text and "{kd}" not in text and "{datumkurz}" not in text
    assert text == vorschau
    # Formatierung: eingesetzte Werte behalten die Formatierung ihres Platzhalters
    stuecke = _pdf_texte(pdf)
    breite = float(pypdf.PdfReader(str(pdf)).pages[0].mediabox.width)
    firma = [s for s in stuecke if "Muster GmbH" in s[0] and "Bold" in s[1]]
    assert firma, stuecke  # {firma} fett
    test = [s for s in stuecke if s[0].startswith("Test") and "Bold" not in s[1]]
    assert test, stuecke  # »Test « normal
    assert abs((test[0][2] + firma[0][2]) / 2 - breite / 2) < breite * 0.15  # zentriert
    kd = [s for s in stuecke if s[0].strip() == "10042" and "Bold" in s[1]]
    assert kd, stuecke  # {kd} fett in der Fußzeile


# --- 11. Vorschau folgt dem Speichern der Kopfzeile ---------------------------------------------------------


def test_preview_follows_saved_header(ui_app, excel_file: Path) -> None:
    pytest.importorskip("pypdf")
    import pypdf

    h = ui_app
    excel_pruefen(h, excel_file, excel_file.parent)
    h.navigate("preview", 0.2)
    assert wait_until(lambda: h.preview.state == "current", 90), h.preview.problem
    laeufe = h.preview.runs
    oeffne_darstellung(h)
    klick(h, papier(h, KOPF))
    tippe(h, "Neue Kopfzeile {kd}")
    klick(h, seitenknopf(h, "Kopfzeile speichern"))
    h.navigate("preview", 0.2)
    assert wait_until(lambda: h.preview.state == "current" and h.preview.runs > laeufe, 90), h.preview.problem
    assert "Neue Kopfzeile 10042" in pypdf.PdfReader(str(h.preview._doc.path)).pages[0].extract_text()


# --- 12. Kein Speichern bei jedem Tastendruck; das Modell ist trotzdem sofort aktuell -----------------------


def test_model_is_live_but_saving_is_debounced(ui_app, config_file: Path) -> None:
    h = ui_app
    oeffne_darstellung(h)
    aufrufe = []
    original = h.app.persist
    h.app.persist = lambda: (aufrufe.append(1), original())[1]
    pump(1.0)
    aufrufe.clear()
    klick(h, papier(h, KOPF))
    for zeichen in "Live":
        QTest.keyClick(h.window, zeichen)
        pump(0.05)
        # das Python-Modell folgt jedem Tastendruck (kein Zustand nur in QML) …
        assert h.overview.header.rich().text == dokument(h, KOPF).toPlainText()
    assert h.overview.header_text() == "Live"
    assert aufrufe == []  # … gespeichert wird erst nach einer Pause
    pump(1.2)
    assert len(aufrufe) == 1 and lies(config_file)["kopfzeile"] == "Live"
