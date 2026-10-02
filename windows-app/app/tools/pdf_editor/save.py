"""Speichern – sicher oder gar nicht.

1. Wurde die Datei seit dem Öffnen von einem anderen Programm verändert? → nicht überschreiben
   (``ExternalChange``; »Speichern unter« bleibt möglich).
2. Stand serialisieren (qpdf, komprimiert; vorhandene Verschlüsselung samt Besitzerpasswort und
   Berechtigungen bleibt erhalten).
3. **Prüfen**, bevor irgendetwas auf der Platte ersetzt wird: mit pikepdf und PDFium neu öffnen,
   Seitenzahl, Darstellbarkeit der Seiten und Erhalt der Struktur (Lesezeichen, Links,
   Anmerkungen, Formularfelder, Anhänge, Metadaten, Ebenen) mit dem Stand im Speicher vergleichen.
4. In eine temporäre Datei im Zielordner schreiben, auf den Datenträger zwingen, zurücklesen und
   vergleichen.
5. Vor dem ersten Überschreiben des Originals eine Sicherung anlegen (``backup_dir``; begrenzt).
6. Atomar ersetzen (``os.replace``, mit kurzen Wiederholungen bei gesperrten Dateien).

Schlägt ein Schritt fehl, bleibt das Original unverändert und die temporäre Datei wird entfernt.
"""

from __future__ import annotations

import hashlib
import io
import os
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf

from pdfium_lock import PDFIUM_LOCK

from .document import EditorDocument, FileStamp
from .errors import ExternalChange, SaveFailed

RENDER_CHECK_PAGES = 200  # bis zu so vielen Seiten werden alle geprüft, darüber eine Auswahl
BACKUPS_PER_FILE = 3
BACKUP_MAX_AGE = 7 * 24 * 3600


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
    try:
        reopened = pikepdf.open(io.BytesIO(data), password=password or "")
    except (pikepdf.PdfError, pikepdf.PasswordError) as exc:
        raise SaveFailed("Die gespeicherte Datei ließ sich nicht wieder öffnen.", str(exc)[:200]) from exc
    try:
        actual = structure_of(reopened)
    finally:
        reopened.close()
    lost = expected.differences(actual)
    if lost:
        raise SaveFailed("Beim Speichern wären Inhalte verloren gegangen: " + ", ".join(lost) + ".", repr((expected, actual))[:400])
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        try:
            view = pdfium.PdfDocument(data, password=password or None)
        except pdfium.PdfiumError as exc:
            raise SaveFailed("Die gespeicherte Datei lässt sich nicht darstellen.", str(exc)[:200]) from exc
        try:
            if len(view) != expected.pages:
                raise SaveFailed("Die gespeicherte Datei hat eine falsche Seitenzahl.")
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
    try:
        expected = structure_of(document.pdf)
        data = document.serialize(keep_encryption=True)
    except (pikepdf.PdfError, RuntimeError, ValueError) as exc:
        raise SaveFailed("Das Dokument konnte nicht geschrieben werden.", str(exc)[:200]) from exc
    checked = validate(data, document.password, expected)
    folder = target.parent
    if not folder.is_dir():
        raise SaveFailed("Der Zielordner existiert nicht.")
    temp = folder / f".{target.stem[:40]}.pdftool-{secrets.token_hex(4)}.tmp"
    backup: Path | None = None
    try:
        digest = hashlib.sha256(data).hexdigest()
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if hashlib.sha256(temp.read_bytes()).hexdigest() != digest:
            raise SaveFailed("Die Datei wurde fehlerhaft auf den Datenträger geschrieben.")
        if same_file and target.exists() and backup_dir is not None:
            backup = _backup(target, backup_dir)
        _replace(temp, target)
    except SaveFailed:
        _remove(temp)
        raise
    except OSError as exc:
        _remove(temp)
        reason = "Keine Berechtigung für diesen Ordner oder die Datei ist in einem anderen Programm geöffnet." if isinstance(exc, PermissionError) else f"Die Datei konnte nicht geschrieben werden ({exc.strerror or 'Ein-/Ausgabefehler'})."
        raise SaveFailed(reason, str(exc)[:200]) from exc
    document.mark_saved(target, FileStamp.of(target))
    return SaveResult(target, len(data), checked, backup)


def write_copy(document: EditorDocument, data_source: bytes | None, target: Path) -> None:
    """Fertige Bytes (z. B. ausgewählte Seiten) atomar als neue Datei schreiben."""
    data = data_source if data_source is not None else document.serialize(keep_encryption=True)
    temp = target.parent / f".{target.stem[:40]}.pdftool-{secrets.token_hex(4)}.tmp"
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _replace(temp, target)
    except OSError as exc:
        _remove(temp)
        raise SaveFailed("Die Datei konnte nicht geschrieben werden.", str(exc)[:200]) from exc


def cleanup_backups(backup_dir: Path, now: float | None = None) -> int:
    """Sicherungen älter als ``BACKUP_MAX_AGE`` entfernen (beim Start)."""
    now = time.time() if now is None else now
    removed = 0
    try:
        entries = list(backup_dir.glob("*.pdf"))
    except OSError:
        return 0
    for entry in entries:
        try:
            if now - entry.stat().st_mtime > BACKUP_MAX_AGE:
                entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed


# Hilfen ---------------------------------------------------------------------------------------
def _backup(target: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    key = hashlib.sha256(str(target.resolve()).encode("utf-8", "replace")).hexdigest()[:10]
    destination = backup_dir / f"{target.stem[:60]}-{key}-{stamp}.pdf"
    shutil.copy2(target, destination)
    olds = sorted(backup_dir.glob(f"*-{key}-*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in olds[BACKUPS_PER_FILE:]:
        _remove(old)
    return destination


def _replace(source: Path, target: Path) -> None:
    from storage import replace_file

    replace_file(source, target)


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
