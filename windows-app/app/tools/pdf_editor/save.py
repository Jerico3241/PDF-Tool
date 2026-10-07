"""Speichern – sicher oder gar nicht.

1. Wurde die Datei seit dem Öffnen von einem anderen Programm verändert? → nicht überschreiben
   (``ExternalChange``; »Speichern unter« bleibt möglich).
2. Vorab: Zielordner vorhanden, Zieldatei nicht schreibgeschützt. Die temporäre Datei im
   Zielordner wird zuerst angelegt – fehlt die Schreibberechtigung, zeigt sich das sofort.
3. Stand serialisieren (qpdf, komprimiert; vorhandene Verschlüsselung samt Besitzerpasswort und
   Berechtigungen bleibt erhalten; XMP-Metadaten unverändert – ohne lxml).
4. **Prüfen**, bevor irgendetwas auf der Platte ersetzt wird: mit pikepdf und PDFium neu öffnen,
   Seitenzahl, Darstellbarkeit der Seiten und Erhalt der Struktur (Lesezeichen, Links,
   Anmerkungen, Formularfelder, Anhänge, Metadaten, Ebenen) mit dem Stand im Speicher vergleichen.
5. In die temporäre Datei schreiben, auf den Datenträger zwingen, zurücklesen und vergleichen.
6. Vor dem ersten Überschreiben des Originals eine Sicherung anlegen (``backup_dir``; begrenzt).
7. Atomar ersetzen (``os.replace`` = ``MoveFileEx`` im selben Ordner, mit kurzen Wiederholungen
   bei Dateien, die ein Virenscanner oder die Suche gerade kurz offen hält).
8. Nachprüfen: die gespeicherte Datei wie beim Öffnen lesen – dieselben Bytes wie geprüft, pikepdf
   und PDFium öffnen sie, gleiche Seitenzahl. Erst dann gilt das Dokument als gespeichert.

Schlägt ein Schritt fehl, bleibt das Original unverändert und die temporäre Datei wird entfernt
(``SaveFailed`` mit Art, Schritt und technischen Angaben fürs Protokoll; Ausnahme: scheitert erst
die Nachprüfung, ist das Original schon ersetzt – die Sicherung enthält den vorherigen Stand).

Dateihandles: Ein geöffnetes Dokument hält seine Datei nie offen – ``EditorDocument`` liest sie
beim Öffnen vollständig, PDFium und pikepdf arbeiten auf Bytes im Speicher (auch Darstellung,
Miniaturen und Suche). Das Ersetzen kann deshalb nur an anderen Programmen scheitern.
"""

from __future__ import annotations

import errno
import hashlib
import io
import os
import secrets
import shutil
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf

from pdfium_lock import PDFIUM_LOCK

from .document import EditorDocument, FileStamp
from .errors import (
    BACKUP_FAILED,
    DIRECTORY_MISSING,
    DIRECTORY_NOT_WRITABLE,
    FILE_LOCKED,
    REOPEN_FAILED,
    REPLACE_FAILED,
    SERIALIZE_FAILED,
    TARGET_READ_ONLY,
    TEMP_WRITE_FAILED,
    VALIDATION_FAILED,
    EditorError,
    ExternalChange,
    SaveFailed,
)
from .recovery import BACKUP_MAX_AGE, cleanup_backups  # noqa: F401 - Aufräumen beim Start (ohne pikepdf)

RENDER_CHECK_PAGES = 200  # bis zu so vielen Seiten werden alle geprüft, darüber eine Auswahl
BACKUPS_PER_FILE = 3
REPLACE_ATTEMPTS = 10  # etwa 1 s: Virenscanner und Suche halten eine neue Datei manchmal kurz offen
UNCHANGED = "Die Originaldatei ist unverändert."
READ_ONLY_TEXT = "Die Datei ist schreibgeschützt. Verwenden Sie »Speichern unter«, um eine bearbeitete Kopie zu erstellen."
NO_PERMISSION_TEXT = "PDF Tool hat keine Schreibberechtigung für diesen Speicherort. Verwenden Sie »Speichern unter«, um einen anderen Ort zu wählen."
LOCKED_TEXT = "Die Datei wird möglicherweise von einem anderen Programm verwendet. Schließen Sie sie dort und speichern Sie erneut – oder verwenden Sie »Speichern unter«."
FILESYSTEM = "Dateisystem"


@dataclass(frozen=True)
class Structure:
    """Was beim Speichern nie verloren gehen darf (Anzahl je Art)."""

    pages: int
    outline: int
    annotations: int
    links: int
    fields: int
    attachments: int
    info_keys: tuple[str, ...]
    xmp: bool
    layers: bool
    named_dests: int

    def differences(self, other: "Structure") -> list[str]:
        labels = {"pages": "Seiten", "outline": "Lesezeichen", "annotations": "Anmerkungen", "links": "Links", "fields": "Formularfelder", "attachments": "Anhänge", "info_keys": "Metadaten", "xmp": "XMP-Metadaten", "layers": "Ebenen", "named_dests": "Sprungziele"}
        return [label for key, label in labels.items() if getattr(self, key) != getattr(other, key)]


@dataclass
class SaveResult:
    path: Path
    size: int
    checked_pages: int
    backup: Path | None = None
    notes: list[str] = field(default_factory=list)


def structure_of(pdf: pikepdf.Pdf) -> Structure:
    annotations = links = 0
    for page in pdf.pages:
        annots = page.obj.get("/Annots")
        if isinstance(annots, pikepdf.Array):
            for annot in annots:
                if isinstance(annot, pikepdf.Dictionary):
                    annotations += 1
                    links += annot.get("/Subtype") == pikepdf.Name.Link
    root = pdf.Root
    form = root.get("/AcroForm")
    fields = sum(1 for _ in _walk_fields(form.get("/Fields") if isinstance(form, pikepdf.Dictionary) else None))
    try:
        attachments = len(pdf.attachments)
    except (pikepdf.PdfError, TypeError, ValueError):
        attachments = 0
    try:
        info_keys = tuple(sorted(str(key) for key in pdf.docinfo.keys())) if "/Info" in pdf.trailer else ()
    except (pikepdf.PdfError, TypeError):
        info_keys = ()
    names = root.get("/Names")
    dests = names.get("/Dests") if isinstance(names, pikepdf.Dictionary) else None
    return Structure(
        pages=len(pdf.pages),
        outline=_count_outline(root.get("/Outlines")),
        annotations=annotations,
        links=links,
        fields=fields,
        attachments=attachments,
        info_keys=info_keys,
        xmp="/Metadata" in root,
        layers="/OCProperties" in root,
        named_dests=_count_name_tree(dests) + (len(root.Dests.keys()) if isinstance(root.get("/Dests"), pikepdf.Dictionary) else 0),
    )


def validate(data: bytes, password: str | None, expected: Structure) -> int:
    """Gespeicherte Bytes prüfen; liefert die Zahl der dargestellten Seiten. Wirft ``SaveFailed``."""

    def failed(reason: str, detail: str = "", backend: str = "pikepdf/qpdf", error: BaseException | None = None) -> SaveFailed:
        return SaveFailed(f"{reason} {UNCHANGED}", detail, kind=VALIDATION_FAILED, phase="validate", backend=backend, error=error)

    try:
        reopened = pikepdf.open(io.BytesIO(data), password=password or "")
    except (pikepdf.PdfError, pikepdf.PasswordError) as exc:
        raise failed("Der bearbeitete Stand ließ sich zur Prüfung nicht wieder öffnen.", str(exc)[:200], error=exc) from exc
    try:
        actual = structure_of(reopened)
    finally:
        reopened.close()
    lost = expected.differences(actual)
    if lost:
        raise failed("Beim Speichern wären Inhalte verloren gegangen: " + ", ".join(lost) + ".", repr((expected, actual))[:400])
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        try:
            view = pdfium.PdfDocument(data, password=password or None)
        except pdfium.PdfiumError as exc:
            raise failed("Der bearbeitete Stand lässt sich nicht darstellen.", str(exc)[:200], "PDFium", exc) from exc
        try:
            if len(view) != expected.pages:
                raise failed("Der bearbeitete Stand hat eine falsche Seitenzahl.", f"{len(view)} statt {expected.pages}", "PDFium")
            indexes = list(range(len(view)))
            if len(indexes) > RENDER_CHECK_PAGES:
                step = len(indexes) / RENDER_CHECK_PAGES
                indexes = sorted({int(i * step) for i in range(RENDER_CHECK_PAGES)} | {len(view) - 1})
            for index in indexes:
                page = view[index]
                try:
                    width, height = page.get_size()
                    bitmap = page.render(scale=min(1.0, 48 / max(1.0, width, height)), may_draw_forms=False)
                    bitmap.close()
                except pdfium.PdfiumError as exc:
                    raise failed(f"Seite {index + 1} des bearbeiteten Stands lässt sich nicht darstellen.", str(exc)[:200], "PDFium", exc) from exc
                finally:
                    page.close()
        finally:
            view.close()
    return len(indexes)


def save(document: EditorDocument, target: str | os.PathLike, *, backup_dir: Path | None = None, force: bool = False) -> SaveResult:
    """Dokument nach ``target`` speichern (Original oder neue Datei). ``force`` überschreibt auch
    eine zwischenzeitlich von außen veränderte Datei (nur nach ausdrücklicher Rückfrage)."""
    target = Path(target)
    same_file = document.path is not None and _same(document.path, target)
    if same_file and not force and document.stamp is not None:
        now = FileStamp.of(target)
        if now is not None and now != document.stamp:
            raise ExternalChange()
    _preflight(target)
    temp, handle = _reserve_temp(target)
    backup: Path | None = None
    try:
        with handle:
            data, checked, pages = _prepare(document)
            _write_temp(handle, data)
        digest = hashlib.sha256(data).hexdigest()
        _verify_temp(temp, digest)
        if same_file and target.exists() and backup_dir is not None:
            backup = _backup_step(target, backup_dir)
        _replace_step(temp, target)
    except BaseException:
        _remove(temp)
        raise
    stamp = _reopen_check(target, digest, document.save_password, pages, backup)
    document.mark_saved(target, stamp)
    return SaveResult(target, len(data), checked, backup)


def write_copy(document: EditorDocument, data_source: bytes | None, target: Path) -> None:
    """Fertige Bytes (z. B. ausgewählte Seiten) atomar als neue Datei schreiben."""
    data = data_source if data_source is not None else document.serialize(keep_encryption=True)
    _preflight(target)
    temp, handle = _reserve_temp(target)
    try:
        with handle:
            _write_temp(handle, data)
        _verify_temp(temp, hashlib.sha256(data).hexdigest())
        _replace_step(temp, target)
    except BaseException:
        _remove(temp)
        raise


# Schritte des Speicherns (jeder wirft ``SaveFailed`` mit seiner Art) ------------------------------------------
def read_only(path: Path) -> bool:
    """Schreibgeschützt: Windows-Attribut »Schreibgeschützt« bzw. keine Schreibrechte des Besitzers."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return not mode & stat.S_IWRITE or not os.access(path, os.W_OK)


def _preflight(target: Path) -> None:
    if not target.parent.is_dir():
        raise SaveFailed("Der Zielordner existiert nicht (mehr). Verwenden Sie »Speichern unter«, um einen anderen Ort zu wählen.", kind=DIRECTORY_MISSING, phase="preflight", save_as=True, backend=FILESYSTEM)
    if target.is_file() and read_only(target):
        raise SaveFailed(READ_ONLY_TEXT, kind=TARGET_READ_ONLY, phase="preflight", save_as=True, backend=FILESYSTEM)


def _reserve_temp(target: Path):
    """Temporäre Datei im Zielordner anlegen (gleiches Dateisystem → atomares Ersetzen)."""
    temp = target.parent / f".{target.stem[:40]}.pdftool-{secrets.token_hex(4)}.tmp"
    try:
        return temp, open(temp, "xb")
    except OSError as exc:
        raise _write_error(exc, "temp_create") from exc


def _prepare(document: EditorDocument) -> tuple[bytes, int, int]:
    """Stand serialisieren und prüfen: (Bytes, geprüfte Seiten, Seitenzahl)."""
    try:
        expected = structure_of(document.pdf)
        data = document.serialize(keep_encryption=True)
    except (pikepdf.PdfError, RuntimeError, ValueError) as exc:
        raise SaveFailed(f"Der bearbeitete Stand ließ sich nicht als PDF schreiben. {UNCHANGED}", str(exc)[:200], kind=SERIALIZE_FAILED, phase="serialize", backend="pikepdf/qpdf", error=exc) from exc
    return data, validate(data, document.save_password, expected), expected.pages


def _write_temp(handle, data: bytes) -> None:
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    except OSError as exc:
        raise _write_error(exc, "temp_write") from exc


def _verify_temp(temp: Path, digest: str) -> None:
    try:
        same = hashlib.sha256(temp.read_bytes()).hexdigest() == digest
    except OSError as exc:
        raise _write_error(exc, "temp_verify") from exc
    if not same:
        raise SaveFailed(f"Die Datei wurde fehlerhaft auf den Datenträger geschrieben. {UNCHANGED}", kind=TEMP_WRITE_FAILED, phase="temp_verify", save_as=True, backend=FILESYSTEM)


def _write_error(exc: OSError, phase: str) -> SaveFailed:
    """Fehler beim Schreiben der temporären Datei → verständliche Art (Berechtigung, Platz, sonst)."""
    winerror = getattr(exc, "winerror", None)
    if isinstance(exc, PermissionError) or exc.errno == errno.EROFS:
        return SaveFailed(NO_PERMISSION_TEXT, kind=DIRECTORY_NOT_WRITABLE, phase=phase, save_as=True, backend=FILESYSTEM, error=exc)
    if exc.errno == errno.ENOSPC or winerror in (39, 112):  # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
        return SaveFailed(f"Auf dem Datenträger ist nicht genug Speicherplatz frei. {UNCHANGED}", kind=TEMP_WRITE_FAILED, phase=phase, save_as=True, backend=FILESYSTEM, error=exc)
    return SaveFailed(f"Die Datei konnte nicht geschrieben werden ({exc.strerror or 'Ein-/Ausgabefehler'}). {UNCHANGED}", kind=TEMP_WRITE_FAILED, phase=phase, save_as=True, backend=FILESYSTEM, error=exc)


def _backup_step(target: Path, backup_dir: Path) -> Path:
    try:
        return _backup(target, backup_dir)
    except OSError as exc:
        if getattr(exc, "winerror", None) in (32, 33):
            raise SaveFailed(LOCKED_TEXT, kind=FILE_LOCKED, phase="backup", save_as=True, backend=FILESYSTEM, error=exc) from exc
        raise SaveFailed(f"Vor dem Überschreiben ließ sich keine Sicherung des bisherigen Stands anlegen ({exc.strerror or 'Ein-/Ausgabefehler'}). {UNCHANGED}", kind=BACKUP_FAILED, phase="backup", save_as=True, backend=FILESYSTEM, error=exc) from exc


def _replace_step(temp: Path, target: Path) -> None:
    try:
        _replace(temp, target)
    except OSError as exc:
        kind = replace_problem(exc, target)
        texts = {
            TARGET_READ_ONLY: READ_ONLY_TEXT,
            FILE_LOCKED: LOCKED_TEXT,
            DIRECTORY_NOT_WRITABLE: NO_PERMISSION_TEXT,
        }
        reason = texts.get(kind, f"Die Originaldatei konnte nicht ersetzt werden ({exc.strerror or 'Ein-/Ausgabefehler'}). Sie ist unverändert.")
        raise SaveFailed(reason, kind=kind, phase="replace", save_as=True, backend=FILESYSTEM, error=exc) from exc


def replace_problem(exc: OSError, target: Path) -> str:
    """Warum ließ sich ``target`` nicht ersetzen? Erst nach dem Fehler genau nachsehen – nie raten:
    schreibgeschützt, von einem anderen Programm geöffnet (eigene Handles gibt es nicht) oder
    keine Berechtigung."""
    winerror = getattr(exc, "winerror", None)
    if winerror in (32, 33):  # ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION
        return FILE_LOCKED
    if not (isinstance(exc, PermissionError) or exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS)):
        return REPLACE_FAILED
    if target.is_file() and read_only(target):
        return TARGET_READ_ONLY
    if exc.errno == errno.EROFS:
        return DIRECTORY_NOT_WRITABLE
    if sys.platform == "win32":
        import winsys

        # »Zugriff verweigert« beim Ersetzen: entweder hält ein anderes Programm die Datei offen
        # oder die Berechtigung fehlt – die Probe mit Löschrecht unterscheidet beides
        return DIRECTORY_NOT_WRITABLE if winsys.replace_access(target) == "denied" else FILE_LOCKED
    return DIRECTORY_NOT_WRITABLE  # POSIX: Umbenennen braucht Schreibrecht im Ordner


def _reopen_check(target: Path, digest: str, password: str | None, pages: int, backup: Path | None) -> FileStamp | None:
    """Gespeicherte Datei wie beim Öffnen lesen: dieselben Bytes wie geprüft, öffnet in pikepdf und
    PDFium, gleiche Seitenzahl. Liefert den Zeitstempel für die Erkennung späterer Fremdänderungen."""
    hint = f" Der vorherige Stand ist gesichert: {backup}" if backup is not None else " Bitte zusätzlich mit »Speichern unter« eine Kopie speichern."
    reason = "Die gespeicherte Datei ließ sich zur Kontrolle nicht wieder öffnen." + hint

    def failed(detail: str, backend: str, error: BaseException | None = None) -> SaveFailed:
        return SaveFailed(reason, detail, kind=REOPEN_FAILED, phase="reopen", save_as=True, backend=backend, error=error)

    try:
        written = target.read_bytes()
        stamp = FileStamp.of(target)
    except OSError as exc:
        raise failed("Datei nicht lesbar", FILESYSTEM, exc) from exc
    if hashlib.sha256(written).hexdigest() != digest:
        raise failed("Inhalt weicht vom geprüften Stand ab", FILESYSTEM)
    try:
        reopened = EditorDocument.from_bytes(written, name=target.name, path=target, password=password, stamp=stamp)
    except EditorError as exc:
        raise failed(f"{type(exc).__name__}: {getattr(exc, 'detail', '') or exc}"[:200], "pikepdf/PDFium", exc) from exc
    try:
        if reopened.page_count != pages:
            raise failed(f"{reopened.page_count} statt {pages} Seiten", "pikepdf")
    finally:
        reopened.close()
    return stamp


# Hilfen ---------------------------------------------------------------------------------------
def _backup(target: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    key = hashlib.sha256(str(target.resolve()).encode("utf-8", "replace")).hexdigest()[:10]
    destination = backup_dir / f"{target.stem[:60]}-{key}-{stamp}.pdf"
    shutil.copyfile(target, destination)
    # Zeitpunkt der Sicherung (nicht der der Originaldatei): danach richten sich Reihenfolge und Aufräumen
    os.utime(destination, None)
    olds = sorted(backup_dir.glob(f"*-{key}-*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in olds[BACKUPS_PER_FILE:]:
        _remove(old)
    return destination


def _replace(source: Path, target: Path) -> None:
    from storage import replace_file

    replace_file(source, target, attempts=REPLACE_ATTEMPTS)


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _count_outline(outlines, limit: int = 100_000) -> int:
    if not isinstance(outlines, pikepdf.Dictionary):
        return 0
    count, stack, seen = 0, [outlines.get("/First")], set()
    while stack and count < limit:
        item = stack.pop()
        while isinstance(item, pikepdf.Dictionary) and count < limit:
            key = item.objgen
            if key in seen and key != (0, 0):
                break
            seen.add(key)
            count += 1
            stack.append(item.get("/First"))
            item = item.get("/Next")
    return count


def _count_name_tree(node, depth: int = 0) -> int:
    if not isinstance(node, pikepdf.Dictionary) or depth > 32:
        return 0
    total = len(node.get("/Names", [])) // 2 if isinstance(node.get("/Names"), pikepdf.Array) else 0
    kids = node.get("/Kids")
    if isinstance(kids, pikepdf.Array):
        total += sum(_count_name_tree(kid, depth + 1) for kid in kids)
    return total


def _walk_fields(fields, depth: int = 0):
    if not isinstance(fields, pikepdf.Array) or depth > 32:
        return
    for item in fields:
        if isinstance(item, pikepdf.Dictionary):
            yield item
            yield from _walk_fields(item.get("/Kids"), depth + 1)
