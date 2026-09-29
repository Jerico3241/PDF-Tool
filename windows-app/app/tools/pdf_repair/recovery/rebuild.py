"""Neuaufbau einer PDF aus den Objekten der Rohanalyse.

1. ``write_classic``: alle gültigen Objekte unverändert übernehmen und eine neue
   klassische Querverweistabelle (exakte Offsets), einen neuen Trailer (``/Size``,
   ``/Root`` – ``/Info`` und ``/ID`` nur, wenn sicher vorhanden), ``startxref`` und
   ``%%EOF`` schreiben. Verschlüsselte Dateien werden nicht angefasst.
2. ``fix_page_tree``: Ist der Seitenbaum nicht lesbar, entsteht aus den gefundenen
   Seitenobjekten ein neuer ``/Pages``-Knoten. Eltern-Verweise werden gesetzt,
   geerbte Eigenschaften (MediaBox, CropBox, Resources, Rotate) vorher auf die Seiten
   übertragen, damit nichts verschwindet.

Das Ergebnis ist nur ein Kandidat: Er wird danach mit qpdf normalisiert und wie jede
andere Ausgabe hart geprüft.
"""

from __future__ import annotations

import mmap
import re
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .scanner import RawScan

CHUNK = 1 << 20
INHERITABLE = ("/Resources", "/MediaBox", "/CropBox", "/Rotate")
A4 = (0, 0, 595.28, 841.89)
_PAGES_REF = re.compile(rb"/Pages\s+(\d+)\s+(\d+)\s+R")
_REF = re.compile(rb"(\d+)\s+(\d+)\s+R")

Progress = Callable[..., None]


@dataclass
class ClassicResult:
    catalog: tuple[int, int]
    catalog_created: bool = False
    objects: int = 0
    info: bool = False
    file_id: bool = False
    truncated: set[int] = field(default_factory=set)  # abgeschnittene Objekte (nur geschlossen, nicht vollständig)


@dataclass
class TreeResult:
    rebuilt: bool = False
    pages: int = 0
    appended: int = 0  # Seiten außerhalb des alten Seitenbaums (nach Objektnummer angefügt)
    inherited: list[str] = field(default_factory=list)  # z. B. »MediaBox«, »Resources«
    notes: list[str] = field(default_factory=list)  # Hinweise für das Ergebnis (verständlich)
    doubtful: bool = False  # Seitengröße oder Ressourcen nur angenommen


def choose_catalog(scan: RawScan) -> tuple[int, int] | None:
    """Dokumentkatalog: vom neuesten Trailer genannt, sonst einer mit gültigem Seitenbaum, sonst der neueste."""
    catalogs = scan.of_kind("Catalog")
    if not catalogs:
        return None
    for trailer in sorted(scan.trailers, key=lambda t: t.offset, reverse=True):
        if trailer.root is not None:
            found = scan.objects.get(trailer.root[0])
            if found is not None and found.kind == "Catalog":
                return found.number, found.generation
    for catalog in reversed(catalogs):
        ref = _PAGES_REF.search(catalog.dict_head)
        if ref:
            target = scan.objects.get(int(ref.group(1)))
            if target is not None and target.kind == "Pages":
                return catalog.number, catalog.generation
    newest = catalogs[-1]
    return newest.number, newest.generation


def _xref_runs(numbers: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for number in numbers:
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    return runs


def write_classic(scan: RawScan, source: str | Path, target: str | Path, progress: Progress | None = None) -> ClassicResult | None:
    """Neue Datei mit allen gültigen Objekten und neuer Querverweistabelle schreiben."""
    progress = progress or (lambda *_args: None)
    if scan.stats.encrypted or not scan.objects:
        return None
    catalog = choose_catalog(scan)
    created: dict[int, bytes] = {}
    top = max(scan.objects)
    if catalog is None:
        if not scan.stats.pages:
            return None
        # Kein Katalog mehr vorhanden: neuer Katalog mit leerem Seitenbaum (wird danach neu aufgebaut)
        pages_number, catalog_number = top + 1, top + 2
        created[pages_number] = b"<< /Type /Pages /Kids [ ] /Count 0 >>"
        created[catalog_number] = f"<< /Type /Catalog /Pages {pages_number} 0 R >>".encode()
        catalog = (catalog_number, 0)
    result = ClassicResult(catalog, catalog_created=bool(created))
    offsets: dict[int, tuple[int, int]] = {}
    source = Path(source)
    total = len(scan.objects)
    with open(source, "rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data, open(target, "wb") as out:
        out.write(f"%PDF-{scan.version or '1.4'}\n".encode() + b"%\xe2\xe3\xcf\xd3\n")
        for index, number in enumerate(sorted(scan.objects)):
            obj = scan.objects[number]
            offsets[number] = (out.tell(), obj.generation)
            if obj.text is not None:  # aus einem Objektstrom entpackt
                out.write(f"{number} 0 obj\n".encode() + obj.text + b"\nendobj\n")
                continue
            position = obj.start
            while position < obj.end:
                size = min(CHUNK, obj.end - position)
                out.write(data[position : position + size])
                position += size
            if not obj.complete:
                # Abgeschnittenes Objekt schließen – qpdf liest davon, was lesbar ist; Seiten,
                # die es brauchen, gelten später als unvollständig
                out.write(b"\nendstream\nendobj\n" if obj.stream is not None else b"\nendobj\n")
                result.truncated.add(number)
            else:
                out.write(b"\n")
            if index % 500 == 0:
                progress("xref_rebuild", index / max(1, total))
        for number, body in created.items():
            offsets[number] = (out.tell(), 0)
            out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
        result.objects = len(offsets)
        # Querverweistabelle: Objekt 0 frei, sonst je zusammenhängendem Bereich ein Abschnitt
        xref = out.tell()
        lines = [b"xref\n", b"0 1\n", b"0000000000 65535 f\r\n"]
        for run in _xref_runs(sorted(offsets)):
            lines.append(f"{run[0]} {len(run)}\n".encode())
            lines += [f"{offsets[n][0]:010d} {offsets[n][1]:05d} n\r\n".encode() for n in run]
        out.write(b"".join(lines))
        progress("trailer_rebuild")
        parts = [f"/Size {max(offsets) + 1}", f"/Root {catalog[0]} {catalog[1]} R"]
        for trailer in sorted(scan.trailers, key=lambda t: t.offset, reverse=True):
            if trailer.info is not None and trailer.info[0] in scan.objects:
                parts.append(f"/Info {trailer.info[0]} {trailer.info[1]} R")
                result.info = True
                break
        file_id = next((t.id_bytes for t in sorted(scan.trailers, key=lambda t: t.offset, reverse=True) if t.id_bytes), None)
        trailer_bytes = ("trailer\n<< " + " ".join(parts)).encode()
        if file_id:
            trailer_bytes += b" /ID " + file_id
            result.file_id = True
        out.write(trailer_bytes + b" >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n")
    return result


# --- Seitenbaum ---------------------------------------------------------------------------------------------------


def open_raw(path: str | Path):
    """Zwischenstand der Rekonstruktion öffnen – ohne dass pikepdf geerbte Seiteneigenschaften
    selbst verteilt (das scheitert an Verweisen ins Leere; der Neuaufbau übernimmt es gezielt)."""
    import pikepdf

    return pikepdf.open(path, attempt_recovery=True, inherit_page_attributes=False)


def _is_dict(obj) -> bool:
    import pikepdf

    return isinstance(obj, pikepdf.Dictionary)


def _type(obj) -> str:
    try:
        value = obj.get("/Type")
        return str(value) if value is not None else ""
    except Exception:
        return ""


def _looks_like_page(obj) -> bool:
    kind = _type(obj)
    if kind == "/Page":
        return True
    return not kind and "/Kids" not in obj and ("/Contents" in obj or "/MediaBox" in obj)


def _walk(node, depth: int, visited: set, pages: list, damaged: list) -> None:
    """Seitenbaum ablaufen: Seiten sammeln, Verweise ins Leere als Schaden zählen."""
    if depth > 64:
        damaged.append("zu tief verschachtelt")
        return
    if not _is_dict(node):
        damaged.append("Knoten fehlt")
        return
    if node.objgen in visited:
        damaged.append("Schleife")
        return
    visited.add(node.objgen)
    try:
        kids = node.get("/Kids")
        items = list(kids) if kids is not None else None
    except Exception:  # noqa: BLE001
        items = None
    if items is None:
        damaged.append("Knoten ohne /Kids")
        return
    for kid in items:
        try:
            if not _is_dict(kid):
                damaged.append("Verweis ins Leere")
            elif _type(kid) == "/Pages" or "/Kids" in kid:
                _walk(kid, depth + 1, visited, pages, damaged)
            elif _looks_like_page(kid):
                pages.append(kid)
            else:
                damaged.append("kein Seitenobjekt")
        except Exception:  # noqa: BLE001
            damaged.append("nicht lesbar")


_KIDS = re.compile(rb"/Kids\s*\[([^\]]*)\]")


def raw_tree(scan: RawScan) -> tuple[int, list[str]]:
    """Seitenbaum direkt in den Rohdaten ablaufen: (erreichbare Seiten, Schäden wie »Verweis ins Leere«).

    qpdf entfernt Verweise ins Leere beim Öffnen einer beschädigten Datei stillschweigend aus
    dem Seitenbaum – danach sähe er heil aus. Die Rohdaten zeigen, was wirklich in der Datei steht.
    """
    catalog = choose_catalog(scan)
    if catalog is None:
        return 0, ["Dokumentkatalog fehlt"] if scan.stats.pages else []
    ref = _PAGES_REF.search(scan.objects[catalog[0]].dict_head)
    if ref is None:
        return 0, ["Katalog ohne Seitenbaum"]
    pages = 0
    damaged: set[str] = set()
    visited: set[int] = set()
    stack = [(int(ref.group(1)), 0)]
    while stack:
        number, depth = stack.pop()
        node = scan.objects.get(number)
        if node is None:
            damaged.add("Verweis ins Leere")
            continue
        if number in visited:
            damaged.add("Schleife")
            continue
        visited.add(number)
        if not node.dict_head:
            damaged.add("kein Seitenobjekt")
            continue
        kids = _KIDS.search(node.dict_head) if node.kind != "Page" else None
        if kids is None:
            if node.kind == "Pages" or b"/Kids" in node.dict_head:
                damaged.add("Knoten ohne lesbare /Kids")
            else:
                pages += 1
            continue
        if depth >= 64:
            damaged.add("zu tief verschachtelt")
            continue
        stack.extend((int(match.group(1)), depth + 1) for match in _REF.finditer(kids.group(1)))
    return pages, sorted(damaged)


def tree_is_broken(path: str | Path, page_objects: int) -> tuple[bool, int, list[str]]:
    """Ist der Seitenbaum der neu geschriebenen Datei unbrauchbar? (kaputt, lesbare Seiten, Befunde)

    Kaputt heißt: kein lesbarer Baum, keine Seiten, oder Verweise ins Leere, während noch
    Seitenobjekte außerhalb des Baums liegen. Ein intakter Baum mit übrigen Seitenobjekten
    (z. B. gelöschte Seiten eines inkrementellen Updates) bleibt, wie er ist.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with open_raw(path) as pdf:
                pages: list = []
                damaged: list[str] = []
                _walk(pdf.Root.get("/Pages"), 0, set(), pages, damaged)
    except Exception as exc:  # noqa: BLE001 - jede Störung bedeutet: Seitenbaum nicht lesbar
        return True, 0, [f"Seitenbaum nicht lesbar: {exc}"]
    count = len(pages)
    broken = (count == 0 and page_objects > 0) or (bool(damaged) and count < page_objects)
    return broken, count, [f"Seitenbaum: {reason}" for reason in sorted(set(damaged))]


def rebuild_tree(pdf, scan: RawScan, technical: list[str]) -> TreeResult | None:
    """Neuen Seitenbaum aus den gefundenen Seitenobjekten aufbauen (im geöffneten Dokument)."""
    import pikepdf

    result = TreeResult(rebuilt=True)
    pages: list = []
    seen: set[tuple[int, int]] = set()

    def add(page) -> None:
        key = page.objgen
        if key not in seen and key != (0, 0):
            seen.add(key)
            pages.append(page)

    # Reihenfolge: zuerst, was die alten Seitenbaum-Knoten noch hergeben, dann übrige Seiten nach Objektnummer
    roots = []
    try:
        root_pages = pdf.Root.get("/Pages")
        if _is_dict(root_pages):
            roots.append(root_pages)
    except Exception:  # noqa: BLE001
        pass
    for raw in scan.of_kind("Pages"):
        try:
            node = pdf.get_object((raw.number, raw.generation))
        except Exception:  # noqa: BLE001
            continue
        if _is_dict(node):
            roots.append(node)
    visited: set = set()
    for node in roots:
        found: list = []
        _walk(node, 0, visited, found, [])
        for page in found:
            add(page)
    from_tree = len(pages)
    for raw in sorted(scan.of_kind("Page"), key=lambda obj: obj.number):
        try:
            page = pdf.get_object((raw.number, raw.generation))
        except Exception:  # noqa: BLE001
            continue
        if _is_dict(page) and _looks_like_page(page):
            add(page)
    if not pages:
        technical.append("Seitenbaum: keine lesbaren Seitenobjekte")
        return None

    # Geerbte Eigenschaften auf die Seiten übertragen, bevor der alte Baum wegfällt
    inherited: Counter = Counter()
    for page in pages:
        missing = [key for key in INHERITABLE if key not in page]
        parent, depth, chain = page.get("/Parent"), 0, set()
        while missing and _is_dict(parent) and depth < 32 and parent.objgen not in chain:
            chain.add(parent.objgen)
            for key in list(missing):
                try:
                    if key in parent:
                        page[key] = parent[key]
                        inherited[key[1:]] += 1
                        missing.remove(key)
                except Exception:  # noqa: BLE001
                    continue
            parent, depth = parent.get("/Parent"), depth + 1
    # Fehlt die Seitengröße noch: die häufigste vorhandene, sonst A4 (als Hinweis vermerkt)
    boxes = Counter(tuple(round(float(v), 2) for v in page.MediaBox) for page in pages if "/MediaBox" in page)
    missing_box = [page for page in pages if "/MediaBox" not in page]
    if missing_box:
        box = boxes.most_common(1)[0][0] if boxes else A4
        for page in missing_box:
            page.MediaBox = pikepdf.Array(box)
        result.notes.append(
            f"Bei {len(missing_box)} Seite(n) fehlte die Seitengröße – übernommen von den übrigen Seiten."
            if boxes
            else f"Bei {len(missing_box)} Seite(n) fehlte die Seitengröße – A4 angenommen."
        )
        result.doubtful = result.doubtful or not boxes
    # Fehlende Ressourcen: nur übernehmen, wenn es genau einen eindeutigen Kandidaten gibt
    without = [page for page in pages if "/Resources" not in page]
    if without:
        candidates = []
        for raw in scan.of_kind("Pages"):
            try:
                node = pdf.get_object((raw.number, raw.generation))
                if _is_dict(node) and "/Resources" in node:
                    candidates.append(node.Resources)
            except Exception:  # noqa: BLE001
                continue
        if len(candidates) == 1:
            for page in without:
                page.Resources = candidates[0]
            inherited["Resources"] += len(without)
        else:
            result.notes.append(f"Bei {len(without)} Seite(n) fehlen Schriften und Bilder (Ressourcen) – Inhalte können unvollständig sein.")
            result.doubtful = True

    node = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Pages, Kids=pikepdf.Array(pages), Count=len(pages)))
    for page in pages:
        page.Parent = node
    root = pdf.Root
    if not _is_dict(root):
        technical.append("Seitenbaum: Dokumentkatalog nicht lesbar")
        return None
    root.Pages = node
    result.pages = len(pages)
    result.appended = len(pages) - from_tree
    result.inherited = [name for name, _count in inherited.most_common()]
    return result


# --- Fehlende Schriften ----------------------------------------------------------------------------------------------


@dataclass
class FontResult:
    replaced: list[str] = field(default_factory=list)  # Ressourcennamen, z. B. »/F1«
    pages: list[int] = field(default_factory=list)  # betroffene Seiten (0-basiert)
    skipped: list[str] = field(default_factory=list)  # nicht ersetzbar (z. B. 2-Byte-Codes)


RESOURCE_OPERATORS = {"Tf": "/Font", "Do": "/XObject", "gs": "/ExtGState", "sh": "/Shading"}


def missing_resources(page) -> list[str]:
    """Namen, die der Seiteninhalt verwendet (Schriften, Bilder/Formulare, Grafikzustände,
    Schattierungen), die in den Ressourcen der Seite aber fehlen – z. B. weil die Objekte
    abgeschnitten sind (qpdf blendet Einträge mit fehlendem Ziel aus)."""
    import pikepdf

    try:
        instructions = pikepdf.parse_content_stream(page)
    except Exception:  # noqa: BLE001
        return ["Inhalt nicht lesbar"]
    resources = page.obj.get("/Resources")
    missing: list[str] = []
    for operands, operator in instructions:
        category = RESOURCE_OPERATORS.get(str(operator))
        if category is None or not operands or not isinstance(operands[0], pikepdf.Name):
            continue
        name = str(operands[0])
        group = resources.get(category) if _is_dict(resources) else None
        if not _is_dict(group) or name not in group:
            label = f"{category}{name}"
            if label not in missing:
                missing.append(label)
    return missing


def lost_contents(page, scan: RawScan) -> bool:
    """Verweist die Seite in der Originaldatei mit /Contents auf Objekte, die es nicht mehr gibt?"""
    raw = scan.objects.get(page.objgen[0])
    if raw is None:
        return False
    match = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)", raw.dict_head)
    if match is None:
        return False
    return any(int(ref.group(1)) not in scan.objects for ref in _REF.finditer(match.group(1)))


def _text_strings(page) -> dict[str, list[bytes]]:
    """Welche Zeichenketten mit welcher Schrift gesetzt werden (Operatoren Tf, Tj, TJ, ', ")."""
    import pikepdf

    used: dict[str, list[bytes]] = {}
    current = None
    try:
        instructions = pikepdf.parse_content_stream(page)
    except Exception:  # noqa: BLE001 - Inhalt nicht lesbar: dann auch nichts ersetzen
        return used
    for operands, operator in instructions:
        name = str(operator)
        if name == "Tf" and operands:
            current = str(operands[0])
            used.setdefault(current, [])
        elif current and name in ("Tj", "'", '"', "TJ"):
            for operand in operands:
                items = list(operand) if isinstance(operand, pikepdf.Array) else [operand]
                for item in items:
                    if isinstance(item, pikepdf.String):
                        used[current].append(bytes(item))
    return used


def substitute_missing_fonts(pdf) -> FontResult:
    """Schriften, die eine Seite verwendet, die in der Datei aber fehlen (z. B. abgeschnitten),
    durch die Standardschrift Helvetica ersetzen – nur bei Text mit 1-Byte-Zeichencodes, bei
    dem das sicher lesbar bleibt. Zwei-Byte-Codes (CID-Schriften) werden nie geraten."""
    import pikepdf

    result = FontResult()
    standard = None
    for index, page in enumerate(pdf.pages):
        used = _text_strings(page)
        if not used:
            continue
        obj = page.obj
        resources = obj.get("/Resources")
        if not _is_dict(resources):
            resources = pikepdf.Dictionary()
            obj.Resources = resources
        fonts = resources.get("/Font")
        if not _is_dict(fonts):
            fonts = pikepdf.Dictionary()
            resources.Font = fonts
        changed = False
        for name, strings in used.items():
            try:
                present = fonts.get(name)
            except Exception:  # noqa: BLE001
                present = None
            if _is_dict(present):
                continue
            if any(b"\x00" in text for text in strings):
                if name not in result.skipped:
                    result.skipped.append(name)
                continue
            if standard is None:
                standard = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica, Encoding=pikepdf.Name.WinAnsiEncoding))
            fonts[name] = standard
            changed = True
            if name not in result.replaced:
                result.replaced.append(name)
        if changed:
            result.pages.append(index)
    return result


# --- Abschluss: Seitenbaum, Schriften, fehlende Inhalte -------------------------------------------------------------


@dataclass
class FinishResult:
    pages: int
    tree: TreeResult | None  # nur, wenn der Seitenbaum neu aufgebaut wurde
    fonts: FontResult
    incomplete: list[int]  # Seiten (0-basiert), die auf fehlende Objekte verweisen


def finish(source: str | Path, target: str | Path, scan: RawScan, technical: list[str], rebuild_pages: bool, page_refs: Callable[[object], tuple[set[int], bool]], truncated: set[int] | None = None) -> FinishResult | None:
    """Neu geschriebene Datei vervollständigen: bei Bedarf Seitenbaum, fehlende Schriften,
    und – bevor qpdf beim Speichern Verweise auf fehlende Objekte verwirft – die Seiten
    ermitteln, denen Inhalte fehlen. ``page_refs`` liefert je Seite die benötigten Objekte
    und ob Verweise ins Leere führen; ``truncated`` sind abgeschnittene Objekte."""
    truncated = truncated or set()
    import pikepdf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            pdf = open_raw(source)
        except Exception as exc:  # noqa: BLE001
            technical.append(f"Neuaufbau: Datei nicht lesbar: {exc}")
            return None
        with pdf:
            tree = None
            if rebuild_pages:
                tree = rebuild_tree(pdf, scan, technical)
                if tree is None:
                    return None
            fonts = substitute_missing_fonts(pdf)
            incomplete = []
            for index, page in enumerate(pdf.pages):
                try:
                    lost = missing_resources(page)
                    if lost:
                        technical.append(f"Seite {index + 1}: fehlende Ressourcen {', '.join(lost[:6])}")
                    refs, missing = page_refs(page.obj)
                    cut = refs & truncated
                    if cut:
                        technical.append(f"Seite {index + 1}: braucht abgeschnittene Objekte {', '.join(str(n) for n in sorted(cut)[:6])}")
                    if lost or cut or missing or lost_contents(page, scan):
                        incomplete.append(index)
                except Exception:  # noqa: BLE001
                    incomplete.append(index)
            pages = len(pdf.pages)
            pdf.save(target, fix_metadata_version=False)
    return FinishResult(pages, tree, fonts, incomplete)
