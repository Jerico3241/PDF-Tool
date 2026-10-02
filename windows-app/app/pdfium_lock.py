"""Eine Sperre für alle PDFium-Aufrufe im Prozess der App.

PDFium (pypdfium2) ist nicht threadsicher – auch nicht für verschiedene Dokumente, weil
Schriften und Zwischenspeicher global sind. Vorschau der Vertragsübersichten, Erzeugen der PDF
und der PDF Reader/Editor rufen PDFium deshalb nur unter dieser Sperre auf. Sie ist wieder-
eintrittsfähig: Ein Aufruf, der sie schon hält, darf sie erneut nehmen.

»PDF reparieren« braucht sie nicht – die Reparatur läuft in einem eigenen Prozess.
"""

from __future__ import annotations

import threading

PDFIUM_LOCK = threading.RLock()
