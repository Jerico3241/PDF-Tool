"""Messpunkte und Zähler für Entwicklung, Messungen und Tests.

Nichts davon landet in einem Protokoll oder auf der Oberfläche. Die Startmesspunkte werden
nur mit der Umgebungsvariablen ``PDF_TOOL_PROFILE=1`` auf der Konsole ausgegeben; die
Zähler sind einfache Ganzzahlen im Speicher (für Tests und Messskripte).

Startmesspunkte (Millisekunden seit dem Import dieses Moduls, also kurz nach Prozessstart):
``root`` Hauptfenster angelegt · ``theme`` Design und Schriften bereit · ``pages`` alle
Seiten aufgebaut (verdeckt) · ``navigation`` Navigation bereit · ``visible`` Fenster
sichtbar · ``interactive`` erste Ereignisschleife – die App ist bedienbar.

Zähler: ``page_create`` aufgebaute Seiten · ``canvas_redraw`` vollständige Neuzeichnungen
selbst gezeichneter Steuerelemente (Größe, Design) · ``preview_render`` erzeugte
Vorschau-PDFs · ``preview_decode`` dekodierte Vorschaubilder · ``customer_list_rebuild``
neu aufgebaute Kundenlisten · ``comparison`` berechnete Vertragsvergleiche.
"""

from __future__ import annotations

import os
import sys
import time

STARTED = time.perf_counter()
marks: dict[str, float] = {}
counters: dict[str, int] = {}


def mark(name: str) -> None:
    """Zeitpunkt festhalten (nur beim ersten Mal)."""
    marks.setdefault(name, round((time.perf_counter() - STARTED) * 1000, 1))


def count(name: str, amount: int = 1) -> None:
    counters[name] = counters.get(name, 0) + amount


def profiling() -> bool:
    return os.environ.get("PDF_TOOL_PROFILE") == "1"


def report_startup() -> None:
    """Startmesspunkte ausgeben – nur mit ``PDF_TOOL_PROFILE=1`` und nur auf der Konsole."""
    if not profiling():
        return
    line = " · ".join(f"{name} {value:.0f} ms" for name, value in marks.items())
    try:
        print(f"Start: {line}", file=sys.stderr, flush=True)
    except (OSError, ValueError, AttributeError):
        pass  # pythonw.exe hat keine Konsole
