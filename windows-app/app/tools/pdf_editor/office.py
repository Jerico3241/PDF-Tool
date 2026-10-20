"""Word, Excel und PowerPoint in PDF umwandeln (seit 4.0 Beta 6) – über das installierte Microsoft Office.

PDF Tool steuert Office unsichtbar über COM (comtypes): Datei schreibgeschützt öffnen, »Als PDF exportieren«, schließen.
Lief das Programm schon vorher mit offenen Dateien des Nutzers, bleibt es offen – beendet wird nur, was PDF Tool selbst
gestartet hat. Ohne Office gibt es eine klare Meldung; Dateien mit Kennwort lehnt Office ohne Rückfrage ab.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

from .errors import EditorError


class OfficeError(EditorError):
    pass


KINDS = {
    ".doc": "word", ".docx": "word", ".docm": "word", ".rtf": "word", ".odt": "word",
    ".xls": "excel", ".xlsx": "excel", ".xlsm": "excel", ".ods": "excel",
    ".ppt": "powerpoint", ".pptx": "powerpoint", ".pptm": "powerpoint", ".odp": "powerpoint",
}
PROGIDS = {"word": "Word.Application", "excel": "Excel.Application", "powerpoint": "PowerPoint.Application"}
NAMES = {"word": "Word", "excel": "Excel", "powerpoint": "PowerPoint"}
FILTER = "Office-Dateien (" + " ".join(f"*{suffix}" for suffix in KINDS) + ");;Alle Dateien (*.*)"

# Tests: ``TEST_BACKEND(kind, source, target)`` statt Office; ``TEST_INSTALLED`` = Menge der »installierten« Programme
TEST_BACKEND: Callable[[str, Path, Path], None] | None = None
TEST_INSTALLED: set[str] | None = None


def kind_of(path: str | os.PathLike) -> str | None:
    return KINDS.get(Path(path).suffix.lower())


def installed(kind: str) -> bool:
    """Ist das Office-Programm registriert (Schlüssel ``HKEY_CLASSES_ROOT\\<ProgID>\\CLSID``)?"""
    if TEST_INSTALLED is not None:
        return kind in TEST_INSTALLED
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, PROGIDS[kind] + "\\CLSID"):
            return True
    except OSError:
        return False


def to_pdf(source: str | os.PathLike, target: str | os.PathLike) -> Path:
    """``source`` (Word, Excel, PowerPoint) als PDF nach ``target`` – eine neue Datei, nie über eine bestehende."""
    source, target = Path(source), Path(target)
    kind = kind_of(source)
    if kind is None:
        raise OfficeError("Diese Datei ist keine Word-, Excel- oder PowerPoint-Datei.")
    if not source.is_file():
        raise OfficeError("Die Datei gibt es nicht mehr.")
    if target.exists():
        raise OfficeError("Es gibt bereits eine Datei mit diesem Namen.")
    if not installed(kind):
        raise OfficeError(f"Zum Umwandeln braucht PDF Tool Microsoft {NAMES[kind]}. Es ist auf diesem PC nicht installiert.")
    if TEST_BACKEND is not None:
        TEST_BACKEND(kind, source, target)
    else:
        _com_export(kind, str(source.resolve()), str(target.resolve()))
    if not target.is_file() or target.stat().st_size == 0:
        raise OfficeError(f"{NAMES[kind]} hat keine PDF erstellt.")
    return target


def _com_export(kind: str, source: str, target: str) -> None:
    import comtypes
    import comtypes.client

    comtypes.CoInitialize()
    try:
        try:
            app = comtypes.client.CreateObject(PROGIDS[kind], dynamic=True)
        except (OSError, comtypes.COMError) as exc:
            raise OfficeError(f"Microsoft {NAMES[kind]} ließ sich nicht starten.") from exc
        collection = {"word": "Documents", "excel": "Workbooks", "powerpoint": "Presentations"}[kind]
        try:
            busy = int(getattr(app, collection).Count) > 0  # Nutzer arbeitet schon damit: Programm offen lassen
        except Exception:  # noqa: BLE001
            busy = True
        try:
            if kind == "word":
                app.DisplayAlerts = 0  # wdAlertsNone
                # FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, PasswordDocument (falsch: Fehler statt Rückfrage)
                document = app.Documents.Open(source, False, True, False, "⁣")
                try:
                    document.ExportAsFixedFormat(target, 17)  # wdExportFormatPDF
                finally:
                    document.Close(0)  # wdDoNotSaveChanges
            elif kind == "excel":
                app.DisplayAlerts = False
                # Filename, UpdateLinks, ReadOnly, Format, Password
                book = app.Workbooks.Open(source, 0, True, 1, "⁣")
                try:
                    book.ExportAsFixedFormat(0, target)  # xlTypePDF
                finally:
                    book.Close(False)
            else:
                # FileName, ReadOnly, Untitled, WithWindow
                presentation = app.Presentations.Open(source, True, False, False)
                try:
                    presentation.SaveAs(target, 32)  # ppSaveAsPDF
                finally:
                    presentation.Close()
        except comtypes.COMError as exc:
            detail = ""
            try:
                detail = str(exc.details[0] or "") if exc.details else ""
            except Exception:  # noqa: BLE001
                detail = ""
            text = f"{NAMES[kind]} konnte die Datei nicht umwandeln"
            if "password" in detail.lower() or "kennwort" in detail.lower():
                text += " – sie ist mit einem Kennwort geschützt. Bitte in Office öffnen und dort als PDF speichern."
            else:
                text += f"{f' ({detail.strip()})' if detail.strip() else ''}."
            raise OfficeError(text) from exc
        finally:
            if not busy:
                try:
                    app.Quit()
                except Exception:  # noqa: BLE001 - schon beendet
                    pass
    finally:
        comtypes.CoUninitialize()
