"""Gliederung (Lesezeichen) eines PDFs lesen – zur Navigation; Lesezeichen bleiben beim
Speichern unverändert erhalten (pikepdf schreibt sie mit, solange sie niemand ändert)."""

from __future__ import annotations

from dataclasses import dataclass

from pdfium_lock import PDFIUM_LOCK

from .document import EditorDocument

MAX_ITEMS = 5000
MAX_DEPTH = 16


@dataclass(frozen=True)
class OutlineEntry:
    level: int  # 0 = oberste Ebene
    title: str
    page: int  # Seitenindex oder -1 (Ziel außerhalb des Dokuments / andere Aktion)
    children: int  # Anzahl direkter und offener Unterpunkte (PDF /Count, ohne Vorzeichen)
    open: bool


def read_outline(document: EditorDocument) -> list[OutlineEntry]:
    entries: list[OutlineEntry] = []
    with PDFIUM_LOCK:
        view = document.view()
        try:
            for bookmark in view.get_toc(max_depth=MAX_DEPTH):
                if len(entries) >= MAX_ITEMS:
                    break
                title = (bookmark.get_title() or "").replace("\r", " ").replace("\n", " ").strip() or "(ohne Titel)"
                count = bookmark.get_count()
                entries.append(OutlineEntry(bookmark.level, title, _target(view, bookmark), abs(count), count >= 0))
        except Exception:  # noqa: BLE001 - eine beschädigte Gliederung verhindert nie das Lesen
            return entries
    return entries


def _target(view, bookmark) -> int:
    import pypdfium2.raw as r

    dest = bookmark.get_dest()
    index = dest.get_index() if dest is not None else None
    if index is None:
        action = r.FPDFBookmark_GetAction(bookmark.raw)
        if action and r.FPDFAction_GetType(action) == r.PDFACTION_GOTO:
            raw_dest = r.FPDFAction_GetDest(view.raw, action)
            if raw_dest:
                index = r.FPDFDest_GetDestPageIndex(view.raw, raw_dest)
    return index if index is not None and 0 <= index < len(view) else -1
