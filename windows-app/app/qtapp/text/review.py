"""Kommentare und nachverfolgte Änderungen eines Textes (seit 5.0 Beta 5) – aufbereitet für die Seitenleisten.

LibreOfficeKit malt Kommentare nicht in die Seiten (``FEATURE_NO_TILED_ANNOTATIONS`` im Textkern); die Liste kommt
aus ».uno:ViewAnnotations«, die Änderungen aus ».uno:AcceptTrackedChanges«. Beide melden Datum und Stelle im Text
(Twips); hier werden daraus Einträge mit deutschem Datum, Art der Änderung und Antworten unter ihrem Kommentar.
"""

from __future__ import annotations

import getpass
import os
import re

# Arten nachverfolgter Änderungen (wie LibreOffice sie meldet) → Wort in der Oberfläche
CHANGE_KINDS = {"Insert": "Eingefügt", "Delete": "Gelöscht", "Format": "Formatiert", "ParagraphFormat": "Absatz formatiert",
                "Attributes": "Formatiert", "TableRowInsert": "Zeile eingefügt", "TableRowDelete": "Zeile gelöscht",
                "TableCellInsert": "Zelle eingefügt", "TableCellDelete": "Zelle gelöscht", "Move": "Verschoben"}


def author_name() -> str:
    """Name für Kommentare und Änderungen: der angezeigte Name des Windows-Kontos, sonst der Anmeldename."""
    if os.name == "nt":
        try:
            import ctypes

            size = ctypes.c_ulong(0)
            secur32 = ctypes.windll.secur32
            secur32.GetUserNameExW(3, None, ctypes.byref(size))  # NameDisplay
            if size.value:
                buffer = ctypes.create_unicode_buffer(size.value + 1)
                if secur32.GetUserNameExW(3, buffer, ctypes.byref(size)) and buffer.value.strip():
                    return buffer.value.strip()
        except (AttributeError, OSError):
            pass
    try:
        return getpass.getuser() or "Novadesk"
    except (KeyError, OSError):
        return "Novadesk"


def german_date(value: str) -> str:
    """»2026-10-28T10:49:58,374« → »28.10.2026, 10:49«; Unlesbares bleibt leer."""
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", str(value or ""))
    if not match or match.group(1) == "0000":
        return ""
    year, month, day, hour, minute = match.groups()
    return f"{day}.{month}.{year}, {hour}:{minute}"


def _first_rect(value: str) -> list[int]:
    for part in str(value or "").split(";"):
        numbers = [item.strip() for item in part.split(",")]
        if len(numbers) >= 4:
            try:
                rect = [int(float(item)) for item in numbers[:4]]
            except ValueError:
                continue
            return rect
    return []


def _rects(value: str) -> list[list[int]]:
    rects = []
    for part in str(value or "").split(";"):
        rect = _first_rect(part)
        if rect and rect[3] > 0:
            rects.append(rect)
    return rects


def comments(data) -> list[dict]:
    """Kommentare in Lesereihenfolge (nach Stelle im Text), Antworten direkt unter ihrem Kommentar (``reply``)."""
    items = data.get("comments") if isinstance(data, dict) else None
    entries = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        entries.append({
            "id": str(item.get("id") or ""),
            "parent": str(item.get("parentId") or "0"),
            "author": str(item.get("author") or "Unbekannt"),
            "text": str(item.get("text") or ""),
            "date": german_date(str(item.get("dateTime") or "")),
            "resolved": str(item.get("resolved") or "false") == "true",
            "anchor": _first_rect(str(item.get("anchorPos") or "")) or _first_rect(str(item.get("textRange") or "")),
            "ranges": _rects(str(item.get("textRange") or "")) or [rect for rect in [_first_rect(str(item.get("anchorPos") or ""))] if rect],
        })
    known = {entry["id"] for entry in entries}
    roots = [entry for entry in entries if entry["parent"] in ("", "0") or entry["parent"] not in known]
    roots.sort(key=lambda entry: (entry["anchor"][1], entry["anchor"][0]) if entry["anchor"] else (1 << 40, 0))
    children: dict[str, list[dict]] = {}
    for entry in entries:
        if entry not in roots:
            children.setdefault(entry["parent"], []).append(entry)
    ordered: list[dict] = []

    def add(entry: dict, depth: int) -> None:
        ordered.append({**entry, "reply": depth > 0})
        for child in children.get(entry["id"], []):
            add(child, depth + 1)

    for root in roots:
        add(root, 0)
    return ordered


def changes(data) -> list[dict]:
    """Nachverfolgte Änderungen in Lesereihenfolge: Nummer (für Annehmen/Ablehnen), Art, Wer, Wann, Beschreibung."""
    items = data.get("redlines") if isinstance(data, dict) else None
    entries = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        description = str(item.get("description") or "")
        # »„ Neu dazu.“ einfügen« → »Neu dazu.« (das Wort am Ende sagt schon die Art)
        quoted = re.search(r"[„\"](.*)[“\"]", description, re.S)
        entries.append({
            "index": int(item.get("index") or 0),
            "kind": CHANGE_KINDS.get(kind, kind or "Geändert"),
            "type": kind,
            "author": str(item.get("author") or "Unbekannt"),
            "date": german_date(str(item.get("dateTime") or "")),
            "text": (quoted.group(1).strip() if quoted else description).strip(),
            "comment": str(item.get("comment") or ""),
            "rect": _first_rect(str(item.get("textRange") or "")),
        })
    entries.sort(key=lambda entry: (entry["rect"][1], entry["rect"][0]) if entry["rect"] else (1 << 40, 0))
    return entries
