"""Zwei Fassungen eines PDFs vergleichen (seit 4.0): Wörter beider Dokumente in Lesereihenfolge, verglichen
mit ``difflib``. Ergebnis ist eine Liste der Änderungen – geändert, neu, entfernt – mit den Stellen in beiden
Dokumenten (Seite und Rechtecke in Anzeige-Punkten), zum Markieren und Durchklicken.

Verglichen wird nur der Text. Seiten ohne Text (Scans) werden gezählt und im Ergebnis genannt; für sie hilft
vorher die Texterkennung.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

Rect = tuple[float, float, float, float]

MAX_WORDS = 400_000  # je Dokument; darüber dauert der Vergleich zu lange
EXCERPT = 80  # Zeichen je Seite einer Änderung in der Liste
BLOCK_LIMIT = 4_000_000  # Wörter alt × neu in einem geänderten Abschnitt; darüber gilt er als Ganzes geändert


@dataclass(frozen=True)
class Word:
    page: int
    text: str
    rect: Rect


@dataclass
class Change:
    kind: str  # "changed", "added" (nur in der neuen Fassung), "removed" (nur in der alten)
    before: str  # Text der alten Fassung ("" bei »added«)
    after: str  # Text der neuen Fassung ("" bei »removed«)
    old: dict[int, list[Rect]] = field(default_factory=dict)  # Seite → Rechtecke in der alten Fassung
    new: dict[int, list[Rect]] = field(default_factory=dict)
    old_at: tuple[int, float, float] = (-1, 0.0, 0.0)  # Stelle zum Hinspringen (Seite, u, v)
    new_at: tuple[int, float, float] = (-1, 0.0, 0.0)


@dataclass
class Result:
    changes: list[Change]
    old_words: int
    new_words: int
    old_empty: list[int]  # Seiten ohne Text
    new_empty: list[int]
    truncated: bool = False


def words_from_chars(page: int, chars: list[tuple[str, Rect]]) -> list[Word]:
    """Zeichen einer Seite (Text, Rechteck in Anzeige-Punkten) zu Wörtern: getrennt an Leerraum und an
    Zeilenwechseln (ein Zeichen deutlich unter dem vorigen)."""
    result: list[Word] = []
    text, box = "", None

    def flush() -> None:
        nonlocal text, box
        if text and box is not None:
            result.append(Word(page, text, box))
        text, box = "", None

    for char, rect in chars:
        if not char.strip():
            flush()
            continue
        if box is not None:
            height = max(1.0, box[3] - box[1])
            if rect[1] > box[3] - height * 0.3 or rect[0] < box[0] - height:  # neue Zeile
                flush()
        text += char
        box = rect if box is None else (min(box[0], rect[0]), min(box[1], rect[1]), max(box[2], rect[2]), max(box[3], rect[3]))
    flush()
    return result


def _merge(rects: list[Rect]) -> list[Rect]:
    """Rechtecke derselben Zeile zu einem zusammenfassen (Markierung wie eine Textauswahl)."""
    merged: list[list[float]] = []
    for rect in rects:
        if merged:
            last = merged[-1]
            height = max(1.0, last[3] - last[1])
            same_line = abs(rect[1] - last[1]) < height * 0.5 and abs(rect[3] - last[3]) < height * 0.5
            if same_line and rect[0] >= last[0] - 1 and rect[0] - last[2] < height * 3:
                last[0], last[1] = min(last[0], rect[0]), min(last[1], rect[1])
                last[2], last[3] = max(last[2], rect[2]), max(last[3], rect[3])
                continue
        merged.append(list(rect))
    return [tuple(rect) for rect in merged]  # type: ignore[misc]


def _places(words: list[Word]) -> tuple[dict[int, list[Rect]], tuple[int, float, float]]:
    pages: dict[int, list[Rect]] = {}
    for word in words:
        pages.setdefault(word.page, []).append(word.rect)
    places = {page: _merge(rects) for page, rects in pages.items()}
    first = words[0] if words else None
    return places, ((first.page, first.rect[0], first.rect[1]) if first else (-1, 0.0, 0.0))


def _excerpt(words: list[Word]) -> str:
    text = " ".join(word.text for word in words)
    return text if len(text) <= EXCERPT else text[: EXCERPT - 1].rstrip() + "…"


def _anchor(words: list[Word], index: int) -> tuple[int, float, float]:
    """Stelle für eine Änderung, die in diesem Dokument keinen Text hat (eingefügt bzw. entfernt): der Platz
    zwischen den Nachbarwörtern."""
    if not words:
        return (-1, 0.0, 0.0)
    word = words[min(index, len(words) - 1)] if index < len(words) else words[-1]
    return (word.page, word.rect[0], word.rect[1])


def _key(word: Word) -> str:
    # Silbentrennung am Zeilenende und typografische Varianten sind keine inhaltliche Änderung
    return word.text.replace("­", "").replace("’", "'").replace("„", '"').replace("“", '"').replace("”", '"')


def _lines(words: list[Word]) -> list[tuple[int, int]]:
    """Wörter zu Zeilen (Anfang, Ende als Indizes): gleiche Seite, etwa gleiche Höhe, nacheinander."""
    lines: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(words) + 1):
        if index == len(words):
            lines.append((start, index))
            break
        before, word = words[index - 1], words[index]
        height = max(1.0, before.rect[3] - before.rect[1])
        if word.page != before.page or abs(word.rect[1] - before.rect[1]) > height * 0.5:
            lines.append((start, index))
            start = index
    return lines if words else []


def _opcodes(old_keys: list[str], new_keys: list[str], old: list[Word], new: list[Word], cancelled=None):
    """Unterschiede Wort für Wort – in zwei Stufen, damit lange Dokumente nicht minutenlang rechnen: erst ganze
    Zeilen vergleichen (gleiche Zeilen fallen weg), dann nur in den geänderten Abschnitten die Wörter."""
    old_lines, new_lines = _lines(old), _lines(new)
    line_matcher = difflib.SequenceMatcher(None, [" ".join(old_keys[a:b]) for a, b in old_lines], [" ".join(new_keys[a:b]) for a, b in new_lines], autojunk=False)
    for tag, la0, la1, lb0, lb1 in line_matcher.get_opcodes():
        if cancelled is not None and cancelled():
            raise CompareCancelled()
        a0 = old_lines[la0][0] if la0 < la1 else (old_lines[la0][0] if la0 < len(old_lines) else len(old))
        a1 = old_lines[la1 - 1][1] if la0 < la1 else a0
        b0 = new_lines[lb0][0] if lb0 < lb1 else (new_lines[lb0][0] if lb0 < len(new_lines) else len(new))
        b1 = new_lines[lb1 - 1][1] if lb0 < lb1 else b0
        if tag == "equal":
            continue
        if tag != "replace" or (a1 - a0) * (b1 - b0) > BLOCK_LIMIT:
            yield ("replace" if a1 > a0 and b1 > b0 else ("delete" if a1 > a0 else "insert")), a0, a1, b0, b1
            continue
        words = difflib.SequenceMatcher(None, old_keys[a0:a1], new_keys[b0:b1], autojunk=False)
        for inner, x0, x1, y0, y1 in words.get_opcodes():
            if inner != "equal":
                yield inner, a0 + x0, a0 + x1, b0 + y0, b0 + y1


class CompareCancelled(Exception):
    pass


def compare(old: list[Word], new: list[Word], old_empty: list[int] | None = None, new_empty: list[int] | None = None, cancelled=None) -> Result:
    truncated = len(old) > MAX_WORDS or len(new) > MAX_WORDS
    old, new = old[:MAX_WORDS], new[:MAX_WORDS]
    changes: list[Change] = []
    for tag, a0, a1, b0, b1 in _opcodes([_key(word) for word in old], [_key(word) for word in new], old, new, cancelled):
        before, after = old[a0:a1], new[b0:b1]
        kind = "changed" if before and after else ("removed" if before else "added")
        old_places, old_at = _places(before)
        new_places, new_at = _places(after)
        if not before:
            old_at = _anchor(old, a0)
        if not after:
            new_at = _anchor(new, b0)
        changes.append(Change(kind, _excerpt(before), _excerpt(after), old_places, new_places, old_at, new_at))
    return Result(changes, len(old), len(new), list(old_empty or []), list(new_empty or []), truncated)


def summary(result: Result) -> str:
    counts = {kind: sum(1 for change in result.changes if change.kind == kind) for kind in ("changed", "added", "removed")}
    if not result.changes:
        text = "Keine Unterschiede im Text gefunden."
    else:
        parts = []
        if counts["changed"]:
            parts.append(f"{counts['changed']} geändert")
        if counts["added"]:
            parts.append(f"{counts['added']} neu")
        if counts["removed"]:
            parts.append(f"{counts['removed']} entfernt")
        total = len(result.changes)
        text = f"{total} {'Unterschied' if total == 1 else 'Unterschiede'}: " + ", ".join(parts) + "."
    empty = len(result.old_empty) + len(result.new_empty)
    if empty:
        text += f" {empty} {'Seite' if empty == 1 else 'Seiten'} ohne Text (Scan) – dort hilft vorher »Text erkennen«."
    if result.truncated:
        text += " Sehr langes Dokument: verglichen wurde nur der Anfang."
    return text
