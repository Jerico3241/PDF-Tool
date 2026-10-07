"""Wasserzeichen, Kopf- und Fußzeile, Seitenzahlen und Bates-Nummern für beliebige PDFs.

Jede Markierung ist ein eigener, kleiner Inhaltsstrom der Seite – über dem Inhalt oder (beim
Wasserzeichen wählbar) darunter –, gekennzeichnet mit ``/PDFToolMark`` (``/Header`` bzw.
``/Watermark``). So lassen sich Markierungen von PDF Tool später gezielt wieder entfernen, ohne den
übrigen Inhalt anzufassen. Im Strom selbst ist der Text als Artefakt markiert (``/Artifact … BDC``):
Vorlese- und Barrierefreiheitsprogramme überspringen ihn.

Positionen gelten in der **Anzeige** (gedrehte Seiten, CropBox): Kopfzeile oben, Fußzeile unten, so
wie man die Seite sieht. Schrift: eine Standardschrift (Helvetica, Times, Courier – nicht
eingebettet, WinAnsi); Zeichen außerhalb von WinAnsi werden durch »?« ersetzt und gemeldet.

Platzhalter im Text: ``{seite}``, ``{seiten}``, ``{datum}``, ``{datei}``, ``{bates}``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date

import pikepdf
from pikepdf import Name

from .commands import History, own_resources, record
from .content import _depth_at_end, fmt, isolated
from .document import EditorDocument
from .fonts import standard_font, standard_width

HEADER = "Header"
WATERMARK = "Watermark"
KINDS = (HEADER, WATERMARK)
FONTS = ("Helvetica", "Helvetica-Bold", "Times-Roman", "Times-Bold", "Courier")
POSITIONS = ("tl", "tc", "tr", "bl", "bc", "br")
FONT_PREFIX = "/PTMarkF"
STATE_PREFIX = "/PTMarkGS"
ASCENT = 0.72  # Versalhöhe der Standardschriften (Anteil der Schriftgröße)


@dataclass(frozen=True)
class TextMark:
    text: str
    position: str  # tl, tc, tr (oben), bl, bc, br (unten)


@dataclass
class HeaderFooter:
    items: list[TextMark]
    font: str = "Helvetica"
    size: float = 9.0
    color: tuple[int, int, int] = (0, 0, 0)
    margin: float = 28.0  # Abstand vom Rand der sichtbaren Seite (Punkte)
    pages: list[int] | None = None
    start: int = 1  # Nummer der ersten Seite für {seite}
    bates_prefix: str = ""
    bates_digits: int = 6
    bates_start: int = 1
    bates_suffix: str = ""


@dataclass
class Watermark:
    text: str
    font: str = "Helvetica-Bold"
    size: float = 0.0  # 0 = an die Seite anpassen
    color: tuple[int, int, int] = (190, 30, 45)
    opacity: float = 0.25
    angle: float = 45.0  # gegen den Uhrzeigersinn, wie man die Seite sieht
    behind: bool = False  # unter dem Inhalt (auf Scans unsichtbar)
    pages: list[int] | None = None


@dataclass
class MarkResult:
    pages: int = 0
    replaced: list[str] = field(default_factory=list)  # nicht darstellbare Zeichen (durch »?« ersetzt)


def present(document: EditorDocument) -> dict:
    """Welche Markierungen von PDF Tool das Dokument hat (Seiten je Art)."""
    counts = {kind: 0 for kind in KINDS}
    for page in document.pdf.pages:
        kinds = {str(stream.get("/PDFToolMark", ""))[1:] for stream in _streams(page.obj)}
        for kind in KINDS:
            counts[kind] += kind in kinds
    return counts


def add_header_footer(document: EditorDocument, history: History, spec: HeaderFooter) -> MarkResult:
    document.ensure_editable()
    _check_font(spec.font)
    indexes = _pages(document, spec.pages)
    items = [item for item in spec.items if item.text.strip() and item.position in POSITIONS]
    result = MarkResult()
    if not items or not indexes:
        return result
    today = date.today().strftime("%d.%m.%Y")
    name = (document.name or "").removesuffix(".pdf").removesuffix(".PDF")
    title = "Seitenzahlen hinzufügen" if all("{seite" in item.text.lower() for item in items) else "Kopf- und Fußzeile hinzufügen"
    with record(document, history, title, pages=tuple(indexes)) as rec:
        for order, index in enumerate(indexes):
            page = rec.page(index)
            geo = document.geometry(index)
            resources = own_resources(page, document.pdf, "/Font")
            font = _font_name(document.pdf, resources, spec.font)
            values = {
                "seite": str(spec.start + order),
                "seiten": str(spec.start + len(indexes) - 1),
                "datum": today,
                "datei": name,
                "bates": f"{spec.bates_prefix}{str(spec.bates_start + order).zfill(max(1, int(spec.bates_digits)))}{spec.bates_suffix}",
            }
            parts = []
            for item in items:
                text, lost = _encode(_fill(item.text, values))
                result.replaced += [char for char in lost if char not in result.replaced]
                width = _width(spec.font, text, spec.size)
                top = item.position[0] == "t"
                v = spec.margin + spec.size * ASCENT if top else geo.height - spec.margin
                align = item.position[1]
                u = spec.margin if align == "l" else (geo.width - width) / 2 if align == "c" else geo.width - spec.margin - width
                parts.append(_text_ops(geo, font, spec.size, spec.color, text, u, v, 0.0))
            body = b"/Artifact <</Type /Pagination /Subtype /Header>> BDC\n" + b"\n".join(parts) + b"\nEMC"
            _attach(document.pdf, page, body, HEADER, behind=False)
            result.pages += 1
    return result


def add_watermark(document: EditorDocument, history: History, spec: Watermark) -> MarkResult:
    document.ensure_editable()
    _check_font(spec.font)
    indexes = _pages(document, spec.pages)
    result = MarkResult()
    text, lost = _encode(spec.text.strip())
    result.replaced = lost
    if not text or not indexes:
        return result
    opacity = max(0.05, min(1.0, float(spec.opacity)))
    angle = math.radians(float(spec.angle))
    with record(document, history, "Wasserzeichen hinzufügen", pages=tuple(indexes)) as rec:
        for index in indexes:
            page = rec.page(index)
            geo = document.geometry(index)
            resources = own_resources(page, document.pdf, "/Font", "/ExtGState")
            font = _font_name(document.pdf, resources, spec.font)
            state = _free(resources.ExtGState, STATE_PREFIX)
            resources.ExtGState[state] = pikepdf.Dictionary(Type=Name.ExtGState, ca=opacity, CA=opacity)
            unit = _width(spec.font, text, 1.0)
            size = float(spec.size) if spec.size > 0 else _fit_size(geo.width, geo.height, unit, angle)
            width = unit * size
            cos, sin = math.cos(angle), math.sin(angle)
            # Mitte der Seite; Text auf der Mitte seiner Versalhöhe zentriert (Anzeige: v nach unten)
            cu, cv = geo.width / 2, geo.height / 2
            right = (cos, -sin)
            up = (-sin, -cos)
            u = cu - right[0] * width / 2 - up[0] * size * ASCENT / 2
            v = cv - right[1] * width / 2 - up[1] * size * ASCENT / 2
            ops = _text_ops(geo, font, size, spec.color, text, u, v, float(spec.angle))
            body = b"/Artifact <</Type /Pagination /Subtype /Watermark>> BDC\nq " + state.encode() + b" gs\n" + ops + b"\nQ\nEMC"
            _attach(document.pdf, page, body, WATERMARK, behind=bool(spec.behind))
            result.pages += 1
    return result


def remove_marks(document: EditorDocument, history: History, kinds: tuple[str, ...] = KINDS) -> int:
    """Markierungen von PDF Tool (gewählte Arten) entfernen; liefert die Zahl der Seiten."""
    document.ensure_editable()
    wanted = {"/" + kind for kind in kinds}
    affected = [index for index, page in enumerate(document.pdf.pages) if any(str(s.get("/PDFToolMark", "")) in wanted for s in _streams(page.obj))]
    if not affected:
        return 0
    title = "Wasserzeichen entfernen" if kinds == (WATERMARK,) else "Kopf- und Fußzeile entfernen" if kinds == (HEADER,) else "Markierungen entfernen"
    with record(document, history, title, pages=tuple(affected)) as rec:
        for index in affected:
            page = rec.page(index)
            remaining = [s for s in _streams(page) if str(s.get("/PDFToolMark", "")) not in wanted]
            others = [s for s in page.get("/Contents") if not isinstance(s, pikepdf.Stream)] if isinstance(page.get("/Contents"), pikepdf.Array) else []
            page.Contents = pikepdf.Array(remaining + others)
            _prune(document.pdf, page)
    return len(affected)


# --- Hilfen ----------------------------------------------------------------------------------------------------
def _pages(document: EditorDocument, pages: list[int] | None) -> list[int]:
    if pages is None:
        return list(range(document.page_count))
    return sorted({int(p) for p in pages if 0 <= int(p) < document.page_count})


def _check_font(name: str) -> None:
    if name not in FONTS:
        raise ValueError(f"Unbekannte Schrift: {name}")


def _fill(text: str, values: dict) -> str:
    return re.sub(r"\{(seite|seiten|datum|datei|bates)\}", lambda m: values[m.group(1).lower()], text, flags=re.IGNORECASE)


def _encode(text: str) -> tuple[str, list[str]]:
    """Text auf WinAnsi (cp1252) begrenzen; nicht darstellbare Zeichen → »?«."""
    out, lost = [], []
    for char in text.replace("\n", " ").replace("\r", " "):
        try:
            char.encode("cp1252")
            out.append(char)
        except UnicodeEncodeError:
            out.append("?")
            if char not in lost:
                lost.append(char)
    return "".join(out), lost


def _width(font: str, text: str, size: float) -> float:
    return sum(standard_width(font, char) for char in text) / 1000.0 * size


def _fit_size(width: float, height: float, unit_width: float, angle: float) -> float:
    cos, sin = abs(math.cos(angle)), abs(math.sin(angle))
    limits = []
    if cos > 1e-6:
        limits.append(width / cos)
    if sin > 1e-6:
        limits.append(height / sin)
    length = 0.75 * min(limits) if limits else 0.75 * width
    return max(8.0, min(200.0, length / max(unit_width, 1e-6), min(width, height) * 0.25))


def _text_ops(geo, font: str, size: float, color, text: str, u: float, v: float, angle_deg: float) -> bytes:
    """Textoperator mit Textmatrix: Grundlinie beginnt bei (u, v) der Anzeige, aufrecht wie angezeigt
    (bzw. um ``angle_deg`` gegen den Uhrzeigersinn gedreht)."""
    angle = math.radians(angle_deg)
    right = (math.cos(angle), -math.sin(angle))
    up = (-math.sin(angle), -math.cos(angle))
    x, y = geo.to_page(u, v)
    rx, ry = geo.to_page(u + right[0], v + right[1])
    ux, uy = geo.to_page(u + up[0], v + up[1])
    matrix = (rx - x, ry - y, ux - x, uy - y, x, y)
    r, g, b = (value / 255.0 for value in color)
    string = pikepdf.String(text.encode("cp1252")).unparse()
    return (
        f"BT {font} {fmt(size)} Tf {fmt(r)} {fmt(g)} {fmt(b)} rg "
        + " ".join(fmt(value) for value in matrix)
        + " Tm "
    ).encode("latin-1") + string + b" Tj ET"


def _font_name(pdf: pikepdf.Pdf, resources: pikepdf.Dictionary, font: str) -> str:
    fonts = resources.Font
    for key, value in fonts.items():
        if str(key).startswith(FONT_PREFIX) and isinstance(value, pikepdf.Dictionary) and str(value.get("/BaseFont", "")) == "/" + font:
            return str(key)
    name = _free(fonts, FONT_PREFIX)
    fonts[name] = standard_font(pdf, font)
    return name


def _free(container: pikepdf.Dictionary, prefix: str) -> str:
    number = 1
    while f"{prefix}{number}" in container:
        number += 1
    return f"{prefix}{number}"


def _streams(page: pikepdf.Object) -> list[pikepdf.Stream]:
    contents = page.get("/Contents")
    if isinstance(contents, pikepdf.Stream):
        return [contents]
    if isinstance(contents, pikepdf.Array):
        return [item for item in contents if isinstance(item, pikepdf.Stream)]
    return []


def _attach(pdf: pikepdf.Pdf, page: pikepdf.Object, body: bytes, kind: str, *, behind: bool) -> None:
    """Markierung als eigenen Strom anhängen (darüber) bzw. voranstellen (darunter) – beides im
    Ausgangszustand der Seite; ändert der bisherige Inhalt den Zustand dauerhaft, wird er einmal in
    ``q … Q`` gefasst (wie ``content.append_content``)."""
    stream = pdf.make_stream(b"q\n" + body + b"\nQ\n")
    stream["/PDFToolMark"] = Name("/" + kind)
    existing = _streams(page)
    if behind or not existing:
        page.Contents = pikepdf.Array([stream, *existing])
        return
    if isolated(page):
        page.Contents = pikepdf.Array([*existing, stream])
        return
    prefix = pdf.make_stream(b"q\n")
    suffix = pdf.make_stream(b"\n" + b"Q\n" * (_depth_at_end(page) + 1))
    page.Contents = pikepdf.Array([prefix, *existing, suffix, stream])


def _prune(pdf: pikepdf.Pdf, page: pikepdf.Object) -> None:
    """Eigene Schriften und Zustände (``/PTMark…``), die kein Strom mehr nutzt, aus den (dafür
    kopierten) Ressourcen der Seite nehmen."""
    used = set()
    for ins in pikepdf.parse_content_stream(page):
        if not isinstance(ins, pikepdf.ContentStreamInlineImage) and str(ins.operator) in ("Tf", "gs") and ins.operands:
            used.add(str(ins.operands[0]))
    resources = page.get("/Resources")
    if not isinstance(resources, pikepdf.Dictionary):
        return
    stale = {category: [str(key) for key in resources[category].keys() if str(key).startswith(prefix) and str(key) not in used] for category, prefix in (("/Font", FONT_PREFIX), ("/ExtGState", STATE_PREFIX)) if isinstance(resources.get(category), pikepdf.Dictionary)}
    if not any(stale.values()):
        return
    own = own_resources(page, pdf, *[category for category, names in stale.items() if names])
    for category, names in stale.items():
        for key in names:
            del own[category][key]
