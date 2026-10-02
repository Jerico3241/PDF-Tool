"""Text einer Seite (PDFium): Zeichen an einer Stelle, Auswahl, Kopieren, Wörter, Suche.

Alle Koordinaten sind Seitenkoordinaten (PDF-Punkte, Ursprung unten links); die Oberfläche
rechnet mit ``PageGeometry`` in die Anzeige um. Die Lesereihenfolge ist die von PDFium
(Inhaltsreihenfolge mit Zeilen- und Absatzerkennung) – wie beim Kopieren in anderen Readern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pdfium_lock import PDFIUM_LOCK

from .document import EditorDocument
from .geometry import Rect, normalize

WORD = re.compile(r"\w", re.UNICODE)


@dataclass(frozen=True)
class Hit:
    page: int
    start: int  # Zeichenindex auf der Seite
    count: int
    rects: tuple[Rect, ...]  # Seitenkoordinaten


def char_count(document: EditorDocument, page: int) -> int:
    with PDFIUM_LOCK:
        return document.textpage(page).count_chars()


def index_at(document: EditorDocument, page: int, x: float, y: float, tolerance: float = 6.0) -> int:
    """Zeichen an der Stelle (Seitenkoordinaten) oder ``-1``."""
    with PDFIUM_LOCK:
        index = document.textpage(page).get_index(x, y, tolerance, tolerance)
    return index if index is not None and index >= 0 else -1


def nearest_index(document: EditorDocument, page: int, x: float, y: float) -> int:
    """Nächstes Zeichen – auch neben dem Text (für das Ende einer Auswahl im Leeren)."""
    for tolerance in (4.0, 16.0, 48.0, 160.0):
        index = index_at(document, page, x, y, tolerance)
        if index >= 0:
            return index
    return -1


def char_box(document: EditorDocument, page: int, index: int) -> Rect:
    with PDFIUM_LOCK:
        left, bottom, right, top = document.textpage(page).get_charbox(index, loose=True)
    return normalize((left, bottom, right, top))


def rects(document: EditorDocument, page: int, start: int, count: int) -> list[Rect]:
    """Rechtecke einer Zeichenfolge (je Zeile zusammengefasst) – für Auswahl und Suchtreffer."""
    if count <= 0:
        return []
    with PDFIUM_LOCK:
        textpage = document.textpage(page)
        total = textpage.count_rects(start, count)
        return [normalize(textpage.get_rect(i)) for i in range(total)]


def text(document: EditorDocument, page: int, start: int = 0, count: int = -1) -> str:
    with PDFIUM_LOCK:
        textpage = document.textpage(page)
        if count < 0:
            count = textpage.count_chars() - start
        if count <= 0:
            return ""
        return _clean(textpage.get_text_range(start, count))


def selection(document: EditorDocument, page: int, anchor: int, focus: int) -> tuple[int, int]:
    """Auswahl zwischen zwei Zeichen (beliebige Richtung) als (Start, Anzahl)."""
    if anchor < 0 or focus < 0:
        return (0, 0)
    start, end = min(anchor, focus), max(anchor, focus)
    return (start, end - start + 1)


def word_at(document: EditorDocument, page: int, index: int) -> tuple[int, int]:
    """Wort um ein Zeichen (Doppelklick) als (Start, Anzahl)."""
    if index < 0:
        return (0, 0)
    with PDFIUM_LOCK:
        textpage = document.textpage(page)
        total = textpage.count_chars()
        start = end = index
        while start > 0 and WORD.match(textpage.get_text_range(start - 1, 1) or " "):
            start -= 1
        while end + 1 < total and WORD.match(textpage.get_text_range(end + 1, 1) or " "):
            end += 1
    return (start, end - start + 1)


def search(document: EditorDocument, page: int, query: str, *, match_case: bool = False, whole_word: bool = False, limit: int = 2000) -> list[Hit]:
    """Alle Treffer auf einer Seite (PDFium-Suche: Groß-/Kleinschreibung, ganze Wörter)."""
    if not query:
        return []
    found: list[Hit] = []
    with PDFIUM_LOCK:
        textpage = document.textpage(page)
        searcher = textpage.search(query, match_case=match_case, match_whole_word=whole_word)
        try:
            while len(found) < limit:
                result = searcher.get_next()
                if not result:
                    break
                start, count = result
                total = textpage.count_rects(start, count)
                found.append(Hit(page, start, count, tuple(normalize(textpage.get_rect(i)) for i in range(total))))
        finally:
            searcher.close()
    return found


def _clean(value: str) -> str:
    """Zeilenenden von PDFium (``\\r\\n``) vereinheitlichen, Nullzeichen entfernen."""
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
