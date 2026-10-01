"""Hilfsprogramm für ``test_qt_caret.py``: Geometrie der Einfügemarke bei einer Bildschirmskalierung.

Qt liest die Skalierung (``QT_SCALE_FACTOR``) nur beim Start – je Skalierung läuft deshalb ein
eigener Prozess. Kopfzeile: je eine Zeile in 8, 10, 12, 14, 18 und 24 pt; Fußzeile leer (zentriert).

Aufruf: ``QT_SCALE_FACTOR=1.5 python caret_geometry.py <ergebnis.json>``
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "app"), str(HERE)]
ARBEIT = Path(tempfile.mkdtemp(prefix="pdf-tool-caret-"))
os.environ["UE_DATA_DIR"] = str(ARBEIT / "daten")
os.environ["UE_CONFIG_FILE"] = str(ARBEIT / "gui-config.json")

GROESSEN = (8, 10, 12, 14, 18, 24)


def kopfzeile():
    from richtext import HEADER_ALIGN, HEADER_STYLE, RichText

    zeilen = [f"Größe {groesse} Hxg" for groesse in GROESSEN]
    styles = []
    for index, (groesse, zeile) in enumerate(zip(GROESSEN, zeilen)):
        style = HEADER_STYLE.with_(size=groesse)
        if index:
            styles.append(style)  # Absatzzeichen davor: Format des Absatzes
        styles += [style] * len(zeile)
    return RichText("\n".join(zeilen), styles, [HEADER_ALIGN] * len(zeilen), HEADER_STYLE, HEADER_ALIGN), zeilen


def main(ziel: Path) -> int:
    import appstate

    kopf, zeilen = kopfzeile()
    daten = {"gesehen": appstate.VERSION, "theme": "light", "accent": "#005FB8", "kopfzeile": kopf.text, "kopfzeile_format": kopf.to_dict(), "fusszeile": "", "fusszeile_explizit": True}
    Path(os.environ["UE_CONFIG_FILE"]).write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QGuiApplication

    from caretutil import FUSS, KOPF, geometrie, textfeld
    from qtutil import Harness, pump, qt_application

    qt_application()
    QGuiApplication.styleHints().setCursorFlashTime(0)  # Marke dauerhaft sichtbar
    h = Harness(ui=True, size=(1100, 900))
    h.navigate("layout", 0.5)
    ergebnis = {"dpr": h.window.devicePixelRatio(), "messungen": []}
    for editor, positionen in ((KOPF, None), (FUSS, [0])):
        feld = textfeld(h, editor)
        # Editor oben ins Bild scrollen
        flick, aktuell = None, feld.parentItem()
        while aktuell is not None:
            if aktuell.inherits("QQuickFlickable"):
                flick = aktuell
            aktuell = aktuell.parentItem()
        oben = h.item(editor).mapToItem(flick.property("contentItem"), QPointF(0, 0)).y()
        flick.setProperty("contentY", max(0.0, oben - 40))
        feld.forceActiveFocus()
        pump(0.2)
        if positionen is None:
            positionen, start = [], 0
            for zeile in zeilen:
                positionen += [start, start + len(zeile)]
                start += len(zeile) + 1
        for position in positionen:
            feld.setProperty("cursorPosition", position)
            pump(0.1)
            g = geometrie(h, editor)
            g["editor"] = editor
            g["breite_feld"] = feld.width()
            g["innen"] = (feld.property("leftPadding"), feld.property("rightPadding"))
            g["szene_feld_x"] = feld.mapToScene(QPointF(0, 0)).x()
            ergebnis["messungen"].append(g)
    ergebnis["meldungen"] = h.messages()
    h.close()
    ziel.write_text(json.dumps(ergebnis, ensure_ascii=False, default=list), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
