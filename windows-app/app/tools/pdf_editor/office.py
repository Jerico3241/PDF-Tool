"""Word-, Excel- und PowerPoint-Dateien in PDF umwandeln – zum Ansehen in Novadesk und für »In PDF umwandeln«.

Seit 5.0 (Novadesk) über das mitgelieferte LibreOffice (``office\\`` im Programmordner, unverändert eingebunden):
``soffice --headless --convert-to pdf`` mit einem eigenen Profil unter ``%LOCALAPPDATA%\\PDF-Tool-Office`` – ohne
Fenster, ohne Makros, ohne Rückfragen. Fehlt LibreOffice (Quellbaum, unvollständige Installation), übernimmt wie bis 4.0
das installierte Microsoft Office: unsichtbar über COM (comtypes), Datei schreibgeschützt öffnen, »Als PDF
exportieren«, schließen. Lief das Programm schon vorher mit offenen Dateien des Nutzers, bleibt es offen – beendet wird
nur, was Novadesk selbst gestartet hat. Dateien mit Kennwort lehnen beide ohne Rückfrage ab.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable

from .errors import EditorError


class OfficeError(EditorError):
    pass


KINDS = {
    ".doc": "word", ".docx": "word", ".docm": "word", ".rtf": "word", ".odt": "word",
    ".xls": "excel", ".xlsx": "excel", ".xlsm": "excel", ".ods": "excel", ".csv": "excel",
    ".ppt": "powerpoint", ".pptx": "powerpoint", ".pptm": "powerpoint", ".odp": "powerpoint",
}
PROGIDS = {"word": "Word.Application", "excel": "Excel.Application", "powerpoint": "PowerPoint.Application"}
NAMES = {"word": "Word", "excel": "Excel", "powerpoint": "PowerPoint"}
# Dateiart in Novadesk: Name, Symbol (app/qml/images/<symbol>-<px>.png) und Farbe – wie im Explorer
LABELS = {"word": "Text-Dokument", "excel": "Tabelle", "powerpoint": "Präsentation"}
FILTER = "Office-Dateien (" + " ".join(f"*{suffix}" for suffix in KINDS) + ");;Alle Dateien (*.*)"
LIBREOFFICE = "LibreOffice"

INSTALL_DIR = Path(__file__).resolve().parents[3]  # wie appstate.INSTALL_DIR (…\app\tools\pdf_editor\office.py)
BUNDLED_DIR = INSTALL_DIR / "office"  # build.py: LibreOffice aus dem offiziellen MSI, unverändert
ENGINE_VARIABLE = "NOVADESK_LIBREOFFICE"  # Pfad zu soffice(.exe) – Entwicklung und Tests
PROFILE_VARIABLE = "NOVADESK_OFFICE_PROFIL"
PROFILE_FOLDER = "PDF-Tool-Office"
TIMEOUT = 300.0  # große Präsentationen brauchen eine Weile; danach wird LibreOffice beendet
CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # verschlüsselte .docx/.xlsx/.pptx sind OLE-Container

# Tests: ``TEST_BACKEND(kind, source, target)`` statt LibreOffice/Office; ``TEST_INSTALLED`` = Menge der »installierten«
# Programme (``word``, ``excel``, ``powerpoint`` für Microsoft Office, ``libreoffice`` für das mitgelieferte)
TEST_BACKEND: Callable[[str, Path, Path], None] | None = None
TEST_INSTALLED: set[str] | None = None

_LOCK = threading.Lock()  # ein Profil – LibreOffice wandelt nacheinander um (ein zweiter Start gäbe nur weiter)


def kind_of(path: str | os.PathLike) -> str | None:
    return KINDS.get(Path(path).suffix.lower())


def symbol(path: str | os.PathLike) -> str:
    """Dateiart für Symbol und Farbe in der Oberfläche (app/qml/images): pdf, text, tabelle, praesentation, csv – sonst leer."""
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".csv":
        return "csv"
    return {"word": "text", "excel": "tabelle", "powerpoint": "praesentation"}.get(KINDS.get(suffix, ""), "")


def libreoffice() -> Path | None:
    """``soffice`` von LibreOffice: mitgeliefert im Programmordner, sonst ``NOVADESK_LIBREOFFICE``, sonst im PATH."""
    if TEST_INSTALLED is not None:
        return Path("soffice") if "libreoffice" in TEST_INSTALLED else None
    names = ("soffice.com", "soffice.exe") if os.name == "nt" else ("soffice",)
    for name in names:
        bundled = BUNDLED_DIR / "program" / name
        if bundled.is_file():
            return bundled
    configured = os.environ.get(ENGINE_VARIABLE, "").strip().strip('"')
    if configured and Path(configured).is_file():
        return Path(configured)
    found = shutil.which("soffice") or shutil.which("libreoffice")
    return Path(found) if found else None


def microsoft_installed(kind: str) -> bool:
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


def engine(kind: str) -> str | None:
    """Wer umwandelt: »LibreOffice« (mitgeliefert), sonst »Word«/»Excel«/»PowerPoint« (Microsoft Office) – oder keiner."""
    if libreoffice() is not None:
        return LIBREOFFICE
    if microsoft_installed(kind):
        return NAMES[kind]
    return None


def installed(kind: str) -> bool:
    return engine(kind) is not None


def missing_text(kind: str) -> str:
    return (f"Zum Umwandeln fehlt LibreOffice, und Microsoft {NAMES[kind]} ist auf diesem PC nicht installiert. "
            "Bitte Novadesk neu installieren.")


def encrypted(path: Path) -> bool:
    """Mit Kennwort geschützte Word-, Excel- oder PowerPoint-Datei (ab 2007: OLE-Container statt ZIP)."""
    if path.suffix.lower() not in (".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"):
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(8) == OLE_SIGNATURE
    except OSError:
        return False


def to_pdf(source: str | os.PathLike, target: str | os.PathLike) -> Path:
    """``source`` (Word, Excel, PowerPoint, OpenDocument, CSV) als PDF nach ``target`` – eine neue Datei, nie über eine
    bestehende."""
    source, target = Path(source), Path(target)
    kind = kind_of(source)
    if kind is None:
        raise OfficeError("Diese Datei ist keine Word-, Excel- oder PowerPoint-Datei.")
    if not source.is_file():
        raise OfficeError("Die Datei gibt es nicht mehr.")
    if target.exists():
        raise OfficeError("Es gibt bereits eine Datei mit diesem Namen.")
    which = engine(kind)
    if which is None:
        raise OfficeError(missing_text(kind))
    if encrypted(source):
        raise OfficeError("Die Datei ist mit einem Kennwort geschützt. Bitte in Office öffnen und dort als PDF speichern.")
    if TEST_BACKEND is not None:
        TEST_BACKEND(kind, source, target)
    elif which == LIBREOFFICE:
        _libreoffice_export(libreoffice(), source.resolve(), target.resolve())
    else:
        _com_export(kind, str(source.resolve()), str(target.resolve()))
    if not target.is_file() or target.stat().st_size == 0:
        raise OfficeError(f"{which} hat keine PDF erstellt.")
    return target


def profile_dir() -> Path:
    """Eigenes LibreOffice-Profil von Novadesk (nicht das eines installierten LibreOffice)."""
    configured = os.environ.get(PROFILE_VARIABLE, "").strip()
    if configured:
        return Path(configured).resolve()  # als URI muss der Pfad absolut sein
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".cache"
    return root / PROFILE_FOLDER / "profil"


def _flags() -> int:
    return CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0


def _stop(process: subprocess.Popen) -> None:
    """LibreOffice samt ``soffice.bin`` beenden (``soffice.com`` startet es als eigenen Prozess)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, creationflags=CREATE_NO_WINDOW, check=False)
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.communicate(timeout=10)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def csv_options(source: Path) -> str:
    """CSV: Trennzeichen (Semikolon wie aus deutschem Excel, Komma, Tabulator) und Zeichensatz (UTF-8, sonst
    Windows-1252) selbst erkennen – als Filteroptionen von LibreOffice (»59,34,76,1«); LibreOffice nähme sonst immer das
    Komma. Keine CSV-Datei: ""."""
    if source.suffix.lower() != ".csv":
        return ""
    try:
        with source.open("rb") as handle:
            sample = handle.read(64 * 1024)
    except OSError:
        return ""
    try:
        text, charset = sample.decode("utf-8"), 76  # RTL_TEXTENCODING_UTF8
    except UnicodeDecodeError as exc:
        # abgeschnittenes Zeichen am Ende der Stichprobe zählt nicht – nur wenn die Datei länger ist als die Stichprobe
        cut = len(sample) == 64 * 1024 and exc.start >= len(sample) - 3
        text, charset = (sample[:exc.start].decode("utf-8"), 76) if cut else (sample.decode("cp1252", "replace"), 1)
    line = next((row for row in text.splitlines() if row.strip()), "")
    separator = max((";", ",", "\t"), key=line.count) if line else ","
    return f"{ord(separator)},34,{charset},1"


def _csv_filter(source: Path) -> list[str]:
    options = csv_options(source)
    return [f"--infilter=Text - txt - csv (StarCalc):{options}"] if options else []


def _libreoffice_export(executable: Path | None, source: Path, target: Path) -> None:
    if executable is None:
        raise OfficeError(missing_text(kind_of(source) or "word"))
    profile = profile_dir()
    with _LOCK:
        profile.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="novadesk-office-"))
        try:
            command = [
                str(executable), "--headless", "--invisible", "--nologo", "--norestore", "--nodefault", "--nolockcheck",
                "--nofirststartwizard", f"-env:UserInstallation={profile.as_uri()}",
                *_csv_filter(source), "--convert-to", "pdf", "--outdir", str(work), str(source),
            ]
            environment = {**os.environ, "SAL_USE_VCLPLUGIN": "svp"} if os.name != "nt" else None
            process = subprocess.Popen(command, cwd=str(work), env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_flags())
            try:
                output, errors = process.communicate(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                _stop(process)
                raise OfficeError("LibreOffice hat die Datei nicht rechtzeitig umgewandelt (länger als 5 Minuten).") from None
            produced = work / f"{source.stem}.pdf"
            if not produced.is_file():
                found = sorted(work.glob("*.pdf"))
                produced = found[0] if len(found) == 1 else produced
            if not produced.is_file() or produced.stat().st_size == 0:
                detail = (errors or output or b"").decode("utf-8", "replace").strip().splitlines()
                text = detail[-1] if detail else f"Code {process.returncode}"
                raise OfficeError(f"LibreOffice konnte die Datei nicht umwandeln ({text[:200]}). Ist sie beschädigt oder mit einem Kennwort geschützt?")
            shutil.move(str(produced), str(target))
        finally:
            shutil.rmtree(work, ignore_errors=True)


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
