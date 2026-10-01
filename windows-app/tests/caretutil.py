"""Messhilfen für die Einfügemarke der Kopf-/Fußzeilen-Editoren (``PTextCaret``).

Gemeinsam genutzt von ``test_qt_caret.py`` (im Testprozess, 100 %) und ``caret_geometry.py``
(eigener Prozess je Bildschirmskalierung).
"""

from __future__ import annotations

import math
from contextlib import contextmanager

from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, QPointF, QRectF
from PySide6.QtGui import QFontMetricsF, QImage

KOPF = "headerEditor"
FUSS = "footerEditor"


def js_round(value: float) -> int:
    """``Math.round`` aus JavaScript (halbe Werte aufwärts) – Python rundet halbe Werte zur geraden Zahl."""
    return math.floor(value + 0.5)


def elemente(wurzel) -> list:
    alle, stapel = [], [wurzel]
    while stapel:
        aktuell = stapel.pop()
        alle.append(aktuell)
        stapel.extend(aktuell.childItems())
    return alle


def textfeld(h, editor: str):
    return next(e for e in elemente(h.item(editor)) if e.inherits("QQuickTextEdit"))


def platzhalter(h, editor: str):
    return next(e for e in elemente(h.item(editor)) if e.objectName() == "placeholder")


def marke(h, editor: str):
    """Die Einfügemarke (Delegate des Textfelds) und ihr Strich – ``(None, None)``, solange das
    Textfeld noch nie den Fokus hatte (Qt legt die Marke erst dann an)."""
    feld = textfeld(h, editor)
    caret = next((e for e in feld.childItems() if e.objectName() == "caret"), None)
    if caret is None:
        return None, None
    strich = next(e for e in caret.childItems() if e.objectName() == "caretBar")
    return caret, strich


def marke_sichtbar(h, editor: str) -> bool:
    _caret, strich = marke(h, editor)
    return strich is not None and strich.isVisible()


def dokument_von(h, editor: str):
    """Das Python-Modell des Editors (``RichTextDocument``)."""
    return h.overview.header if editor == KOPF else h.overview.footer


def rechteck(feld, position: int) -> QRectF:
    return QMetaObject.invokeMethod(feld, "positionToRectangle", Q_RETURN_ARG("QRectF"), Q_ARG(int, position))


def zeile(feld, position: int):
    """Textzeile des Dokuments an ``position`` (``QTextLine``) oder ``None``."""
    doc = feld.property("textDocument").textDocument()
    block = doc.findBlock(position)
    layout = block.layout()
    if layout.lineCount() == 0:
        return None
    line = layout.lineForTextPosition(position - block.position())
    return line if line.isValid() else None


def geometrie(h, editor: str) -> dict:
    """Lage und Maße der Einfügemarke am Cursor – logisch und in Gerätepixeln."""
    feld = textfeld(h, editor)
    _caret, strich = marke(h, editor)
    modell = dokument_von(h, editor)
    dpr = h.window.devicePixelRatio()
    position = feld.property("cursorPosition")
    r = feld.property("cursorRectangle")
    oben = feld.mapToScene(QPointF(r.x(), r.y()))
    p = strich.mapToScene(QPointF(0, 0))
    metriken = QFontMetricsF(modell.caretFont)
    line = zeile(feld, position)
    return {
        "dpr": dpr,
        "position": position,
        "cursor": (oben.x(), oben.y(), r.height()),
        "strich": (p.x(), p.y(), strich.width(), strich.height()),
        "strich_geraet": (p.x() * dpr, p.y() * dpr, strich.width() * dpr, strich.height() * dpr),
        "sichtbar": strich.isVisible(),
        "ascent": modell.caretAscent,
        "descent": modell.caretDescent,
        "grundlinie": modell.caretBaseline,
        "schrift": (modell.caretFont.family(), modell.caretFont.pointSizeF(), metriken.ascent(), metriken.descent()),
        "zeile": None if line is None else (line.ascent(), line.descent(), line.height()),
        "groesse": modell.fontSize,
    }


def pruefe_geraetepixel(g: dict) -> None:
    """Strich auf ganzen Gerätepixeln: linke Kante an der Einfügestelle, Oberkante auf der
    Grundlinie minus Oberlänge, ≈ 1 px breit, so hoch wie die Schrift (Ober- plus Unterlänge)."""
    dpr = g["dpr"]
    x, y, w, hoehe = g["strich_geraet"]
    cursor_x, zeile_oben, _ = g["cursor"]
    for kante in (x, y, x + w, y + hoehe):
        abstand = abs(kante - js_round(kante))
        assert abstand <= 0.02, f"Kante {kante:.3f} liegt nicht auf dem Gerätepixelraster ({g})"
    assert js_round(x) == js_round(cursor_x * dpr), g
    assert js_round(y) == js_round((zeile_oben + g["grundlinie"] - g["ascent"]) * dpr), g
    assert js_round(w) == max(1, js_round(dpr)), g
    assert js_round(hoehe) == max(1, js_round((g["ascent"] + g["descent"]) * dpr)), g


def bild(h) -> QImage:
    return h.window.grabWindow().convertToFormat(QImage.Format.Format_RGB32)


def strich_pixel(h, editor: str, pump) -> dict | None:
    """Gezeichnete Pixel der Marke: Unterschied zweier Aufnahmen mit und ohne Marke (Gerätepixel)."""
    feld = textfeld(h, editor)
    feld.setProperty("cursorVisible", True)
    pump(0.1)
    mit = bild(h)
    feld.setProperty("cursorVisible", False)
    pump(0.1)
    ohne = bild(h)
    feld.setProperty("cursorVisible", True)
    pump(0.1)
    dpr = h.window.devicePixelRatio()
    r = feld.property("cursorRectangle")
    oben = feld.mapToScene(QPointF(r.x(), r.y()))
    x0, x1 = int((oben.x() - 10) * dpr), int((oben.x() + 10) * dpr)
    y0, y1 = int((oben.y() - 10) * dpr), int((oben.y() + max(r.height(), 50) + 10) * dpr)
    pixel = [(px, py) for py in range(max(0, y0), min(mit.height(), y1)) for px in range(max(0, x0), min(mit.width(), x1)) if mit.pixel(px, py) != ohne.pixel(px, py)]
    if not pixel:
        return None
    xs, ys = [p[0] for p in pixel], [p[1] for p in pixel]
    return {"x0": min(xs), "x1": max(xs) + 1, "y0": min(ys), "y1": max(ys) + 1, "anzahl": len(pixel)}


@contextmanager
def ohne_marke(h, editor: str, pump):
    """Marke kurz ausblenden – um den Text darunter zu messen."""
    feld = textfeld(h, editor)
    feld.setProperty("cursorVisible", False)
    pump(0.1)
    try:
        yield
    finally:
        feld.setProperty("cursorVisible", True)
        pump(0.1)


def tinte(h, links: float, oben: float, rechts: float, unten: float, hell: int = 200) -> dict | None:
    """Gezeichneter Text (Pixel dunkler als ``hell``) in einem Fensterbereich (logische Koordinaten)."""
    aufnahme = bild(h)
    dpr = h.window.devicePixelRatio()
    pixel = []
    for py in range(max(0, int(oben * dpr)), min(aufnahme.height(), int(unten * dpr))):
        for px in range(max(0, int(links * dpr)), min(aufnahme.width(), int(rechts * dpr))):
            farbe = aufnahme.pixelColor(px, py)
            if (farbe.red() + farbe.green() + farbe.blue()) / 3 < hell:
                pixel.append((px, py))
    if not pixel:
        return None
    xs, ys = [p[0] for p in pixel], [p[1] for p in pixel]
    return {"x0": min(xs), "x1": max(xs) + 1, "y0": min(ys), "y1": max(ys) + 1}
