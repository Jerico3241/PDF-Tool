"""Eine PDF mit den Schritten eines Plans bearbeiten und als neue Datei speichern.

Gearbeitet wird im Arbeitsspeicher an einem ``EditorDocument`` – mit denselben Funktionen wie im
Reader. Schritte, die fertige Bytes liefern (verkleinern, PDF/A), öffnen das Ergebnis neu; so bleibt
jeder folgende Schritt auf dem Stand des vorigen. Gespeichert wird zum Schluss einmal, atomar und
geprüft (``save.write_copy``). Das Original wird nie geschrieben.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tools.pdf_editor import commands, flatten, ocr, optimize, pagemarks, pdfa, protect, sanitize, save
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import EditorError

from . import actions
from .actions import Plan


class Cancelled(Exception):
    """»Abbrechen« – die Datei wurde nicht gespeichert."""


@dataclass
class FileResult:
    source: Path
    target: Path
    before: int  # Bytes der Originaldatei
    after: int  # Bytes des Ergebnisses
    notes: list[str] = field(default_factory=list)  # »3 Seiten erkannt«, »Kennwortschutz entfernt« …


Progress = Callable[[str], None]  # »Text wird erkannt (Seite 2 von 5) …«


def process(source: str | Path, target: str | Path, plan: Plan, *, password: str | None = None, cancel: threading.Event | None = None, progress: Progress | None = None) -> FileResult:
    source, target = Path(source), Path(target)
    reason = actions.problem(plan)
    if reason:
        raise EditorError(reason)
    if save._same(source, target):  # noqa: SLF001
        raise EditorError("Das Ergebnis braucht einen eigenen Namen – das Original bleibt unverändert.")
    before = source.stat().st_size
    document = EditorDocument.open(source, password=password)
    notes: list[str] = []
    try:
        for step in plan.ordered():
            _check(cancel)
            if progress is not None:
                progress(actions.LABELS[step] + " …")
            document = _apply(step, document, plan, notes, cancel, progress)
        _check(cancel)
        data = document.serialize(keep_encryption=True)
        save.write_copy(document, data, target)
    finally:
        document.close()
    return FileResult(source, target, before, len(data), notes)


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def _reopen(document: EditorDocument, data: bytes, password: str | None = None) -> EditorDocument:
    fresh = EditorDocument.from_bytes(data, name=document.name, path=None, password=password)
    document.close()
    return fresh


def _apply(step: str, document: EditorDocument, plan: Plan, notes: list[str], cancel, progress) -> EditorDocument:
    history = commands.History()
    if step == actions.OCR:
        _ocr(document, history, plan, notes, cancel, progress)
    elif step == actions.CLEAN:
        found = sanitize.clean(document, history, sanitize.CleanOptions())
        if found.total:
            notes.append(f"{found.total} {'Eintrag' if found.total == 1 else 'Einträge'} bereinigt")
    elif step == actions.FLATTEN:
        result = flatten.flatten(document, history, fields=True, comments=True)
        if result.fields or result.comments:
            notes.append("Formulare und Kommentare reduziert")
    elif step == actions.WATERMARK:
        pagemarks.remove_marks(document, history, (pagemarks.WATERMARK,))
        pagemarks.add_watermark(document, history, pagemarks.Watermark(plan.watermark_text.strip()[: actions.MAX_WATERMARK], opacity=plan.watermark_opacity))
    elif step == actions.NUMBERS:
        text = actions.NUMBER_FORMATS.get(plan.number_format, actions.NUMBER_FORMATS["seite_von"])
        position = plan.number_position if plan.number_position in actions.NUMBER_POSITIONS else "bc"
        # nur alte Seitenzahlen ersetzen – Kopf-/Fußzeilen und Bates-Nummern bleiben
        pagemarks.remove_page_numbers(document, history, tuple(actions.NUMBER_FORMATS.values()))
        pagemarks.add_header_footer(document, history, pagemarks.HeaderFooter([pagemarks.TextMark(text, position)], role=pagemarks.PAGE_NUMBERS))
    elif step == actions.OPTIMIZE:
        data, before, images, _skipped = optimize.optimize_bytes(document, plan.optimize_level)
        if len(data) < before:
            notes.append(f"{images} {'Bild' if images == 1 else 'Bilder'} verkleinert" if images else "kompakter gespeichert")
        document = _reopen(document, data, document.save_password)
    elif step == actions.PDFA:
        data, result = pdfa.convert(document.serialize(keep_encryption=False), encrypted=document.encrypted)
        notes.extend(result.notes)
        if result.fonts:
            notes.append(f"{result.fonts} {'Schrift' if result.fonts == 1 else 'Schriften'} eingebettet")
        document = _reopen(document, data)
    elif step == actions.PROTECT:
        protect.set_protection(document, history, protect.Protection(user_password=plan.password))
    return document


def _ocr(document: EditorDocument, history, plan: Plan, notes: list[str], cancel, progress) -> None:
    engine = ocr.find_engine()
    if engine is None:
        raise EditorError("Die Texterkennung ist auf diesem PC nicht verfügbar.")
    pages = [scan.page for scan in ocr.scan_pages(document) if scan.needs_ocr]
    if not pages:
        return
    results = []
    for number, page in enumerate(pages, start=1):
        _check(cancel)
        if progress is not None:
            progress(f"Text wird erkannt (Seite {number} von {len(pages)}) …")
        png, dpi = ocr.render_page_image(document, page)
        try:
            results.append(ocr.recognize(engine, page, png, plan.ocr_languages, dpi, cancel=cancel))
        except ocr.OcrCancelled as exc:
            raise Cancelled() from exc
    ocr.apply_text_layers(document, history, results)
    notes.append(f"Text auf {len(pages)} {'Seite' if len(pages) == 1 else 'Seiten'} erkannt")
