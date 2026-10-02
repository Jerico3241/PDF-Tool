"""Seiten organisieren: drehen, löschen, duplizieren, leere Seite einfügen, verschieben, Seiten aus
einer anderen PDF einfügen bzw. anhängen (Zusammenführen), Seiten als neue PDF speichern
(Extrahieren) und eine PDF in mehrere Dateien teilen.

* Jede Änderung am Dokument läuft über ``commands.record`` (Rückgängig/Wiederholen).
* Beim Löschen werden Verweise auf die entfernten Seiten aufgelöst: Lesezeichen, Links und die
  Startansicht verlieren nur ihr Ziel, Sprungziele und Formularfelder dieser Seiten werden entfernt.
  So schleppt die gespeicherte Datei keine verwaisten Seiten mit.
* Extrahieren und Teilen schreiben **neue** Dateien (nie über eine bestehende Datei und nie über
  das geöffnete Dokument); das Dokument selbst bleibt unverändert.
* Die Berechtigungen der Datei gelten: Seiten organisieren braucht »Zusammenstellen«, Seiten
  herauslösen zusätzlich »Kopieren«.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name

from pdfium_lock import PDFIUM_LOCK

from . import commands, save
from .commands import History, PageOrder
from .document import EditorDocument, inherited
from .errors import EditorError, PasswordRequired, ReadOnlyDocument, SaveFailed, UnsupportedEdit

INHERITED = ("/Resources", "/MediaBox", "/CropBox", "/Rotate")
MAX_SPLIT_FILES = 1000


# --- Hilfen -----------------------------------------------------------------------------------------
def _indexes(document: EditorDocument, pages) -> list[int]:
    chosen = sorted({int(index) for index in pages})
    if not chosen:
        raise UnsupportedEdit("Es ist keine Seite ausgewählt.")
    if chosen[0] < 0 or chosen[-1] >= document.page_count:
        raise UnsupportedEdit("Die Auswahl enthält eine Seite, die es nicht gibt.")
    return chosen


def _title(one: str, many: str, count: int) -> str:
    return one if count == 1 else many


def parse_pages(text: str, count: int) -> list[int]:
    """Seitenangabe wie »1-3, 5, 8-« (1-basiert) → Seitenindizes (0-basiert, in Reihenfolge der
    Angabe, ohne Doppelte). Wirft ``ValueError`` mit einem verständlichen Satz."""
    result: list[int] = []
    seen: set[int] = set()
    parts = [part.strip() for part in re.split(r"[,;]", text or "") if part.strip()]
    if not parts:
        raise ValueError("Bitte Seiten angeben, z. B. »1-3, 5«.")
    for part in parts:
        match = re.fullmatch(r"(\d*)\s*[-–]\s*(\d*)|(\d+)", part)
        if not match:
            raise ValueError(f"»{part}« ist keine gültige Seitenangabe.")
        if match.group(3):
            first = last = int(match.group(3))
        else:
            first = int(match.group(1)) if match.group(1) else 1
            last = int(match.group(2)) if match.group(2) else count
        if first < 1 or last > count or first > last:
            raise ValueError(f"»{part}« liegt außerhalb der Seiten 1 bis {count}.")
        for number in range(first, last + 1):
            if number - 1 not in seen:
                seen.add(number - 1)
                result.append(number - 1)
    return result


def unique_path(folder: Path, name: str) -> Path:
    """Freier Dateiname im Ordner: »Name.pdf«, sonst »Name (2).pdf« … – nie eine bestehende Datei."""
    stem, suffix = os.path.splitext(name)
    candidate = folder / name
    number = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({number}){suffix}"
        number += 1
    return candidate


# --- Drehen ------------------------------------------------------------------------------------------
def rotate(document: EditorDocument, history: History, pages, degrees: int) -> None:
    """Seiten um ``degrees`` (Vielfaches von 90, positiv = im Uhrzeigersinn) drehen."""
    document.ensure_editable("assemble")
    if degrees % 90:
        raise ValueError("Seiten lassen sich nur in Schritten von 90° drehen.")
    chosen = _indexes(document, pages)
    with commands.record(document, history, _title("Seite drehen", "Seiten drehen", len(chosen)), pages=tuple(chosen)) as rec:
        for index in chosen:
            current = document.geometry(index).rotation
            obj = rec.page(index, ("/Rotate",))
            obj.Rotate = (current + degrees) % 360


# --- Löschen -----------------------------------------------------------------------------------------
def delete(document: EditorDocument, history: History, pages) -> list[str]:
    """Seiten löschen. Mindestens eine Seite bleibt. Liefert Hinweise (z. B. entfernte Felder)."""
    document.ensure_editable("assemble")
    chosen = _indexes(document, pages)
    if len(chosen) >= document.page_count:
        raise UnsupportedEdit("Mindestens eine Seite muss im Dokument bleiben.")
    pdf = document.pdf
    with commands.record(document, history, _title("Seite löschen", "Seiten löschen", len(chosen))) as rec:
        rec.page_order()
        removed = {pdf.pages[index].obj.objgen for index in chosen}
        removed_annots = set()
        for index in chosen:
            annots = pdf.pages[index].obj.get("/Annots")
            if isinstance(annots, Array):
                removed_annots.update(annot.objgen for annot in annots if isinstance(annot, Dictionary) and annot.is_indirect)
        notes = _detach(document, rec, removed, removed_annots)
        for index in reversed(chosen):
            del pdf.pages[index]
    return notes


def _dest_target(dest) -> tuple[int, int] | None:
    """Seite (objgen), auf die ein explizites Ziel zeigt – sonst ``None``."""
    if isinstance(dest, Dictionary):
        dest = dest.get("/D")
    if isinstance(dest, Array) and len(dest):
        first = dest[0]
        if isinstance(first, Dictionary) and first.is_indirect:
            return first.objgen
    return None


def _action_target(action) -> tuple[int, int] | None:
    if isinstance(action, Dictionary) and action.get("/S") == Name.GoTo:
        return _dest_target(action.get("/D"))
    return None


def _detach(document: EditorDocument, rec, removed: set, removed_annots: set) -> list[str]:
    """Verweise auf entfernte Seiten auflösen (vor dem Entfernen, damit Rückgängig alles kennt)."""
    pdf = document.pdf
    root = pdf.Root
    notes: list[str] = []
    detached = 0
    # Lesezeichen
    outlines = root.get("/Outlines")
    stack = [outlines.get("/First")] if isinstance(outlines, Dictionary) else []
    seen: set = set()
    while stack:
        item = stack.pop()
        while isinstance(item, Dictionary) and item.objgen not in seen and len(seen) < 200_000:
            seen.add(item.objgen)
            if _dest_target(item.get("/Dest")) in removed or _action_target(item.get("/A")) in removed:
                rec.object(item, ("/Dest", "/A"))
                for key in ("/Dest", "/A"):
                    if key in item:
                        del item[key]
                detached += 1
            stack.append(item.get("/First"))
            item = item.get("/Next")
    # Links auf den übrigen Seiten
    for page in pdf.pages:
        if page.obj.objgen in removed:
            continue
        annots = page.obj.get("/Annots")
        if not isinstance(annots, Array):
            continue
        for annot in annots:
            if isinstance(annot, Dictionary) and annot.get("/Subtype") == Name.Link and (_dest_target(annot.get("/Dest")) in removed or _action_target(annot.get("/A")) in removed):
                rec.object(annot, ("/Dest", "/A"))
                for key in ("/Dest", "/A"):
                    if key in annot:
                        del annot[key]
                detached += 1
    # Startansicht
    opening = root.get("/OpenAction")
    if _dest_target(opening) in removed or _action_target(opening) in removed:
        rec.root(("/OpenAction",))
        del root["/OpenAction"]
    # Benannte Sprungziele: /Dests (PDF 1.1) und Namensbaum /Names /Dests
    old_dests = root.get("/Dests")
    if isinstance(old_dests, Dictionary):
        gone = [str(key) for key, value in old_dests.items() if _dest_target(value) in removed]
        if gone:
            rec.object(old_dests, tuple(gone))
            for key in gone:
                del old_dests[key]
    names = root.get("/Names")
    if isinstance(names, Dictionary) and isinstance(names.get("/Dests"), Dictionary):
        _prune_name_tree(rec, names.Dests, removed)
    if detached:
        notes.append(f"{detached} Lesezeichen bzw. Links zeigten auf gelöschte Seiten und haben kein Ziel mehr.")
    # Formularfelder, deren Widgets nur auf entfernten Seiten liegen
    form = root.get("/AcroForm")
    if isinstance(form, Dictionary):
        before = sum(1 for _ in save._walk_fields(form.get("/Fields")))  # noqa: SLF001
        _prune_fields(rec, form, "/Fields", removed, removed_annots)
        after = sum(1 for _ in save._walk_fields(form.get("/Fields")))  # noqa: SLF001
        if after < before:
            notes.append("Formularfelder der gelöschten Seiten wurden entfernt.")
    return notes


def _prune_name_tree(rec, node: Dictionary, removed: set, depth: int = 0) -> None:
    if depth > 32:
        return
    entries = node.get("/Names")
    if isinstance(entries, Array):
        kept = []
        items = list(entries)
        for i in range(0, len(items) - 1, 2):
            if _dest_target(items[i + 1]) in removed:
                continue
            kept += [items[i], items[i + 1]]
        if len(kept) != len(items) - (len(items) % 2):
            rec.object(node, ("/Names", "/Limits"))
            node.Names = Array(kept)
            if "/Limits" in node and kept:
                node.Limits = Array([kept[0], kept[-2]])
    kids = node.get("/Kids")
    if isinstance(kids, Array):
        for kid in kids:
            if isinstance(kid, Dictionary):
                _prune_name_tree(rec, kid, removed, depth + 1)


def _page_of(annot: Dictionary):
    page = annot.get("/P")
    return page.objgen if isinstance(page, Dictionary) and page.is_indirect else None


def _prune_fields(rec, holder: Dictionary, key: str, removed: set, removed_annots: set, depth: int = 0) -> int:
    """Aus ``holder[key]`` (Felder bzw. Widgets) entfernen, was nur auf entfernten Seiten liegt.
    Liefert die Zahl der verbleibenden Einträge."""
    array = holder.get(key)
    if not isinstance(array, Array) or depth > 32:
        return 0
    kept = []
    changed = False
    for item in array:
        if not isinstance(item, Dictionary):
            kept.append(item)
            continue
        widget = item.get("/Subtype") == Name.Widget
        kids = item.get("/Kids")
        if isinstance(kids, Array) and len(kids):
            if _prune_fields(rec, item, "/Kids", removed, removed_annots, depth + 1) == 0 and not widget:
                changed = True
                continue
            kept.append(item)
            continue
        if widget and (item.objgen in removed_annots or _page_of(item) in removed):
            changed = True
            continue
        kept.append(item)
    if changed:
        rec.object(holder, (key,))
        holder[key] = Array(kept)
    return len(kept)


# --- Duplizieren, leere Seite, verschieben -----------------------------------------------------------------
def duplicate(document: EditorDocument, history: History, pages) -> list[str]:
    """Seiten verdoppeln (die Kopie folgt jeweils direkt auf ihre Seite). Anmerkungen werden
    mitkopiert; Formularfelder nicht (ein Feld gehört genau zu einer Stelle im Formular)."""
    document.ensure_editable("assemble")
    chosen = _indexes(document, pages)
    pdf = document.pdf
    notes: list[str] = []
    skipped = 0
    with commands.record(document, history, _title("Seite duplizieren", "Seiten duplizieren", len(chosen))) as rec:
        rec.page_order()
        for offset, index in enumerate(chosen):
            source = pdf.pages[index + offset].obj
            copy = Dictionary({str(key): value for key, value in source.items() if key not in ("/Parent", "/Annots")})
            for key in INHERITED:
                if key not in copy:
                    value = inherited(source, key)
                    if value is not None:
                        copy[key] = value
            copy = pdf.make_indirect(copy)
            annots, dropped = _copy_annotations(pdf, source.get("/Annots"), copy)
            skipped += dropped
            if annots:
                copy.Annots = annots
            pdf.pages.insert(index + offset + 1, pikepdf.Page(copy))
    if skipped:
        notes.append("Formularfelder wurden nicht dupliziert – sie bleiben auf der ursprünglichen Seite.")
    return notes


def _copy_annotations(pdf: pikepdf.Pdf, annots, page: Dictionary) -> tuple[Array | None, int]:
    if not isinstance(annots, Array):
        return None, 0
    mapping: dict = {}
    copies = []
    dropped = 0
    for annot in annots:
        if not isinstance(annot, Dictionary):
            continue
        if annot.get("/Subtype") == Name.Widget:
            dropped += 1
            continue
        copy = pdf.make_indirect(Dictionary({str(key): value for key, value in annot.items()}))
        copy.P = page
        mapping[annot.objgen] = copy
        copies.append(copy)
    for copy in copies:  # Verweise innerhalb der Seite (Notiz-Popups, Antworten) auf die Kopien umlenken
        for key in ("/Popup", "/Parent", "/IRT"):
            target = copy.get(key)
            if isinstance(target, Dictionary) and target.objgen in mapping:
                copy[key] = mapping[target.objgen]
            elif key in ("/Popup", "/Parent") and isinstance(target, Dictionary):
                del copy[key]  # verweist auf etwas außerhalb der Seite
    return (Array(copies) if copies else None), dropped


def insert_blank(document: EditorDocument, history: History, index: int, size: tuple[float, float] | None = None) -> None:
    """Leere Seite an Position ``index`` einfügen – im Format der benachbarten Seite (wie angezeigt)."""
    document.ensure_editable("assemble")
    if not 0 <= index <= document.page_count:
        raise UnsupportedEdit("Diese Position gibt es nicht.")
    if size is None:
        geo = document.geometry(min(index, document.page_count - 1))
        size = (geo.width, geo.height)
    width, height = (max(36.0, min(14400.0, float(v))) for v in size)
    pdf = document.pdf
    with commands.record(document, history, "Leere Seite einfügen") as rec:
        rec.page_order()
        page = pdf.make_indirect(Dictionary(Type=Name.Page, MediaBox=Array([0, 0, width, height]), Resources=Dictionary(), Contents=pdf.make_stream(b"")))
        pdf.pages.insert(index, pikepdf.Page(page))


def move(document: EditorDocument, history: History, pages, target: int) -> list[int]:
    """Seiten vor die Seite ``target`` verschieben (Index im aktuellen Stand; ``page_count`` = ans
    Ende). Die Reihenfolge der verschobenen Seiten bleibt. Liefert ihre neuen Indizes."""
    document.ensure_editable("assemble")
    chosen = _indexes(document, pages)
    if not 0 <= target <= document.page_count:
        raise UnsupportedEdit("Diese Position gibt es nicht.")
    pdf = document.pdf
    order = [page.obj for page in pdf.pages]
    picked = set(chosen)
    moving = [order[i] for i in chosen]
    rest = [obj for i, obj in enumerate(order) if i not in picked]
    at = sum(1 for i in range(target) if i not in picked)
    new_order = rest[:at] + moving + rest[at:]
    if [obj.objgen for obj in new_order] == [obj.objgen for obj in order]:
        return chosen
    with commands.record(document, history, _title("Seite verschieben", "Seiten verschieben", len(chosen))) as rec:
        rec.page_order()
        PageOrder(new_order).restore(pdf)
    return list(range(at, at + len(moving)))


# --- Aus einer anderen PDF einfügen, Zusammenführen ---------------------------------------------------------------
def open_source(path: str | os.PathLike, password: str | None = None) -> pikepdf.Pdf:
    """Andere PDF zum Einfügen öffnen (nur lesen) – mit Passwort, Berechtigungen werden geprüft."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise EditorError(f"Die Datei kann nicht gelesen werden ({exc.strerror or 'Zugriff verweigert'}).") from exc
    if b"%PDF-" not in data[:1024]:
        raise EditorError(f"»{Path(path).name}« ist keine PDF-Datei.")
    try:
        source = pikepdf.open(io.BytesIO(data), password=password or "")
    except pikepdf.PasswordError as exc:
        raise PasswordRequired(wrong=bool(password)) from exc
    except (pikepdf.PdfError, ValueError, RuntimeError) as exc:
        raise EditorError(f"»{Path(path).name}« lässt sich nicht öffnen – sie ist vermutlich beschädigt. »PDF reparieren« kann helfen.") from exc
    if source.is_encrypted and not getattr(source, "owner_password_matched", False) and not source.allow.extract:
        source.close()
        raise ReadOnlyDocument(f"Die Berechtigungen von »{Path(path).name}« erlauben nicht, Seiten zu übernehmen.")
    return source


def insert_from(document: EditorDocument, history: History, index: int, source: pikepdf.Pdf, pages=None, *, title: str = "Seiten einfügen") -> list[str]:
    """Seiten einer anderen PDF (``open_source``) an Position ``index`` einfügen. Anmerkungen und
    Formularfelder kommen mit; Lesezeichen der anderen Datei werden nicht übernommen."""
    document.ensure_editable("assemble")
    if not 0 <= index <= document.page_count:
        raise UnsupportedEdit("Diese Position gibt es nicht.")
    chosen = list(range(len(source.pages))) if pages is None else [int(i) for i in pages]
    if not chosen or min(chosen) < 0 or max(chosen) >= len(source.pages):
        raise UnsupportedEdit("Die Auswahl enthält eine Seite, die es nicht gibt.")
    pdf = document.pdf
    notes: list[str] = []
    fields = False
    with commands.record(document, history, title) as rec:
        rec.page_order()
        _prepare_form(rec, pdf)
        source_form = source.acroform if source.Root.get("/AcroForm") is not None else None
        for offset, number in enumerate(chosen):
            pdf.pages.insert(index + offset, source.pages[number])
            if source_form is not None:
                copied = pdf.pages[index + offset]
                added = pdf.acroform.fix_copied_annotations(copied, source.pages[number], source_form)
                fields = fields or bool(added)
    document.adopt(source)
    if fields:
        notes.append("Formularfelder der eingefügten Seiten wurden übernommen; gleichnamige Felder wurden umbenannt.")
    if source.Root.get("/Outlines") is not None:
        notes.append("Lesezeichen der eingefügten Datei werden nicht übernommen.")
    return notes


def _prepare_form(rec, pdf: pikepdf.Pdf) -> None:
    """Vor dem Übernehmen fremder Formularfelder: qpdf ergänzt ``/Fields`` und ``/DR`` direkt –
    deshalb erhalten sie vorher eigene Kopien (das alte Formular bleibt für Rückgängig unverändert)."""
    rec.root(("/AcroForm",))
    form = pdf.Root.get("/AcroForm")
    if not isinstance(form, Dictionary):
        return
    rec.object(form, ("/Fields", "/DR", "/DA", "/NeedAppearances"))
    fields = form.get("/Fields")
    form.Fields = Array(list(fields)) if isinstance(fields, Array) else Array()
    if isinstance(form.get("/DR"), Dictionary):
        resources = commands.own_dict(form, "/DR", pdf)
        for category in ("/Font", "/XObject", "/ColorSpace", "/ExtGState"):
            if isinstance(resources.get(category), Dictionary):
                commands.own_dict(resources, category, pdf)


def merge(document: EditorDocument, history: History, sources: list[pikepdf.Pdf]) -> list[str]:
    """Andere PDFs hinten anhängen (in der angegebenen Reihenfolge) – ein Schritt für Rückgängig."""
    document.ensure_editable("assemble")
    notes: list[str] = []
    pdf = document.pdf
    with commands.record(document, history, _title("PDF anhängen", "PDFs anhängen", len(sources))) as rec:
        rec.page_order()
        _prepare_form(rec, pdf)
        for source in sources:
            source_form = source.acroform if source.Root.get("/AcroForm") is not None else None
            for number in range(len(source.pages)):
                pdf.pages.append(source.pages[number])
                if source_form is not None:
                    pdf.acroform.fix_copied_annotations(pdf.pages[-1], source.pages[number], source_form)
    for source in sources:
        document.adopt(source)
    if any(source.Root.get("/Outlines") is not None for source in sources):
        notes.append("Lesezeichen der angehängten Dateien werden nicht übernommen.")
    return notes


# --- Neue Dateien: Extrahieren, Teilen ----------------------------------------------------------------------------
def extract(document: EditorDocument, pages, target: str | os.PathLike) -> Path:
    """Seiten als **neue** PDF speichern (geprüft, atomar). Das Dokument bleibt unverändert."""
    if not document.permissions.copy or not document.permissions.assemble:
        raise ReadOnlyDocument("Die Berechtigungen dieses PDFs erlauben nicht, Seiten herauszulösen.")
    chosen = [int(i) for i in pages]
    if not chosen or min(chosen) < 0 or max(chosen) >= document.page_count:
        raise UnsupportedEdit("Die Auswahl enthält eine Seite, die es nicht gibt.")
    target = Path(target)
    if target.exists():
        raise SaveFailed("Es gibt bereits eine Datei mit diesem Namen.")
    if document.path is not None and save._same(document.path, target):  # noqa: SLF001
        raise SaveFailed("Das geöffnete Dokument kann nicht als Ziel dienen.")
    out = pikepdf.new()
    try:
        source_form = document.pdf.acroform if document.pdf.Root.get("/AcroForm") is not None else None
        for number in chosen:
            out.pages.append(document.pdf.pages[number])
            if source_form is not None:
                out.acroform.fix_copied_annotations(out.pages[-1], document.pdf.pages[number], source_form)
        info = document.pdf.trailer.get("/Info")
        if isinstance(info, Dictionary):
            for key in ("/Title", "/Author", "/Subject", "/Keywords"):
                if key in info:
                    out.docinfo[key] = info[key]
        buffer = io.BytesIO()
        out.save(buffer, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        data = buffer.getvalue()
    except (pikepdf.PdfError, RuntimeError, ValueError) as exc:
        raise SaveFailed("Die Seiten konnten nicht geschrieben werden.", str(exc)[:200]) from exc
    finally:
        out.close()
    _check_new_file(data, len(chosen))
    save.write_copy(document, data, target)
    return target


def split(document: EditorDocument, ranges: list[list[int]], folder: str | os.PathLike, stem: str) -> list[Path]:
    """Dokument in mehrere neue Dateien teilen (je Bereich eine Datei: »Name_Teil1.pdf« …)."""
    if not ranges:
        raise UnsupportedEdit("Es ist kein Bereich angegeben.")
    if len(ranges) > MAX_SPLIT_FILES:
        raise UnsupportedEdit(f"Höchstens {MAX_SPLIT_FILES} Dateien auf einmal.")
    folder = Path(folder)
    if not folder.is_dir():
        raise SaveFailed("Der Zielordner existiert nicht.")
    safe = re.sub(r'[\\/:*?"<>|]+', "_", stem).strip(" .") or "Dokument"
    written: list[Path] = []
    for number, chosen in enumerate(ranges, 1):
        target = unique_path(folder, f"{safe}_Teil{number}.pdf")
        written.append(extract(document, chosen, target))
    return written


def every(count: int, size: int) -> list[list[int]]:
    """Bereiche für »alle n Seiten teilen«."""
    size = max(1, int(size))
    return [list(range(start, min(count, start + size))) for start in range(0, count, size)]


def _check_new_file(data: bytes, pages: int) -> None:
    import pypdfium2 as pdfium

    try:
        with pikepdf.open(io.BytesIO(data)) as reopened:
            if len(reopened.pages) != pages:
                raise SaveFailed("Die neue Datei hat eine falsche Seitenzahl.")
    except pikepdf.PdfError as exc:
        raise SaveFailed("Die neue Datei ließ sich nicht wieder öffnen.", str(exc)[:200]) from exc
    with PDFIUM_LOCK:
        try:
            view = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise SaveFailed("Die neue Datei lässt sich nicht darstellen.", str(exc)[:200]) from exc
        try:
            if len(view) != pages:
                raise SaveFailed("Die neue Datei hat eine falsche Seitenzahl.")
        finally:
            view.close()
