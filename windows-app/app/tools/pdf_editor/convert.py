"""PDF umwandeln (seit 4.0 Beta 6): in Text (.txt), Word (.docx) und Excel (.xlsx) – in neue Dateien, nie über bestehende.

Grundlage ist der Text von PDFium mit Lage, Schriftgröße und Schriftstärke je Zeichen. Daraus entstehen Zeilen (Zeichen
auf gleicher Höhe), Absätze (Zeilen mit üblichem Abstand und gleicher Schrift) und Überschriften (deutlich größer als
der Fließtext). Word bekommt Absätze, Überschriften, Fettdruck und Seitenumbrüche; Seiten ohne Text (Scans ohne
Texterkennung) kommen als Bild hinein. Excel bekommt je Seite ein Blatt: Zeilen werden Tabellenzeilen, große Lücken
trennen Zellen, Zellen mit ähnlicher Lage teilen sich eine Spalte, Zahlen (auch »1.234,56« und »12 %«) werden Zahlen.

Das .docx schreibt Novadesk selbst (WordprocessingML, nur die Standardbibliothek), das .xlsx mit openpyxl. Die
Berechtigung »Kopieren« der Datei gilt auch hier.
"""

from __future__ import annotations

import io
import os
import re
import secrets
import statistics
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from pdfium_lock import PDFIUM_LOCK

from . import render
from .document import EditorDocument
from .errors import ReadOnlyDocument, SaveFailed, UnsupportedEdit

FORMATS = {"txt": ".txt", "docx": ".docx", "xlsx": ".xlsx"}
MAX_PAGES = 2000


@dataclass
class Line:
    text: str
    top: float  # Anzeige-Punkte, Ursprung oben links
    bottom: float
    left: float
    right: float
    size: float
    bold: bool
    words: list[tuple[str, float, float]] = field(default_factory=list)  # Text, links, rechts


@dataclass
class Paragraph:
    text: str
    size: float
    bold: bool
    style: str = ""  # "", "Heading1", "Heading2"
    row: list[tuple[str, float]] | None = None  # Tabellenzeile: Zellen (Text, linker Rand)


@dataclass
class PageLayout:
    width: float
    height: float
    lines: list[Line]


def _chars(document: EditorDocument, index: int) -> list[tuple[str, tuple[float, float, float, float], float, bool]]:
    """Zeichen der Seite: Text, Rechteck (Anzeige-Punkte), Schriftgröße, fett."""
    import ctypes

    import pypdfium2.raw as raw

    geo = document.geometry(index)
    result = []
    with PDFIUM_LOCK:
        textpage = document.textpage(index)
        total = textpage.count_chars()
        name = ctypes.create_string_buffer(128)
        flags = ctypes.c_int(0)
        for i in range(total):
            char = textpage.get_text_range(i, 1)
            if char in ("\x02", "\ufffe"):  # Trennstrich am Zeilenende (PDFium)
                char = "-"
            if not char or char in "\r\n":
                result.append((" ", (0, 0, 0, 0), 0.0, False))
                continue
            left, bottom, right, top = textpage.get_charbox(i, loose=True)
            size = float(raw.FPDFText_GetFontSize(textpage.raw, i))
            weight = int(raw.FPDFText_GetFontWeight(textpage.raw, i))
            bold = weight >= 600
            if not bold and raw.FPDFText_GetFontInfo(textpage.raw, i, name, len(name), ctypes.byref(flags)) > 0:
                font = name.value.decode("latin-1", "replace").lower()
                bold = "bold" in font or "black" in font or "heavy" in font or (flags.value & (1 << 18)) != 0
            u0, v0, u1, v1 = geo.rect_to_view((min(left, right), min(bottom, top), max(left, right), max(bottom, top)))
            result.append((char, (u0, v0, u1, v1), size, bold))
    return result


def page_layout(document: EditorDocument, index: int) -> PageLayout:
    """Zeilen einer Seite in Lesereihenfolge (oben nach unten, links nach rechts)."""
    geo = document.geometry(index)
    chars = [entry for entry in _chars(document, index) if entry[0].strip() or entry[2] > 0]
    # Zeichen zu Zeilen: gleiche Höhe (Mitte innerhalb der halben Zeichenhöhe)
    rows: list[list] = []
    for entry in sorted((c for c in chars if c[0].strip()), key=lambda c: ((c[1][1] + c[1][3]) / 2, c[1][0])):
        box = entry[1]
        middle, height = (box[1] + box[3]) / 2, max(1.0, box[3] - box[1])
        if rows:
            last = rows[-1]
            last_middle = statistics.fmean((c[1][1] + c[1][3]) / 2 for c in last[-3:])
            if abs(middle - last_middle) <= height * 0.45:
                last.append(entry)
                continue
        rows.append([entry])
    lines = []
    for row in rows:
        row.sort(key=lambda c: c[1][0])
        sizes = [c[2] for c in row if c[2] > 0] or [max(1.0, row[0][1][3] - row[0][1][1])]
        size = statistics.median(sizes)
        words: list[list] = []  # [Text, links, rechts]
        gap_limit = max(1.0, size * 0.25)
        for char, box, _size, _bold in row:
            if words and box[0] - words[-1][2] <= gap_limit:
                words[-1][0] += char
                words[-1][2] = max(words[-1][2], box[2])
            else:
                words.append([char, box[0], box[2]])
        text = " ".join(word[0] for word in words)
        lines.append(Line(text=text, top=min(c[1][1] for c in row), bottom=max(c[1][3] for c in row), left=row[0][1][0],
                          right=max(c[1][2] for c in row), size=round(size, 1), bold=sum(c[3] for c in row) * 2 > len(row),
                          words=[(w[0], w[1], w[2]) for w in words]))
    return PageLayout(geo.width, geo.height, lines)


def paragraphs(layout: PageLayout, body_size: float) -> list[Paragraph]:
    """Zeilen zu Absätzen: gleiche Schrift und üblicher Zeilenabstand; Überschriften nach Schriftgröße."""
    result: list[Paragraph] = []
    previous: Line | None = None
    for line in layout.lines:
        row = cells(line)
        if len(row) >= 2:  # Tabellenzeile: eigene Zeile, Zellen getrennt
            result.append(Paragraph(line.text, line.size, line.bold, row=row))
            previous = None
            continue
        joined = False
        if previous is not None and result and result[-1].row is None:
            gap = line.top - previous.bottom
            same_font = abs(line.size - previous.size) < 0.6 and line.bold == previous.bold
            if same_font and gap < max(previous.size, line.size) * 0.75 and not previous.text.endswith(":"):
                last = result[-1]
                if last.text.endswith("-") and len(last.text) > 1 and last.text[-2].isalpha() and line.text[:1].islower():
                    last.text = last.text[:-1] + line.text  # Silbentrennung am Zeilenende
                else:
                    last.text += " " + line.text
                joined = True
        if not joined:
            style = ""
            if body_size > 0 and len(line.text) < 160:
                if line.size >= body_size * 1.45:
                    style = "Heading1"
                elif line.size >= body_size * 1.15 or (line.bold and line.size >= body_size and len(line.text) < 80 and not line.text.endswith(".")):
                    style = "Heading2"
            result.append(Paragraph(line.text, line.size, line.bold, style))
        previous = line
    return result


def _body_size(layouts: list[PageLayout]) -> float:
    """Schriftgröße des Fließtexts: die häufigste, gewichtet nach Textmenge."""
    weights: dict[float, int] = {}
    for layout in layouts:
        for line in layout.lines:
            weights[round(line.size)] = weights.get(round(line.size), 0) + len(line.text)
    return float(max(weights, key=weights.get)) if weights else 0.0


def _check(document: EditorDocument, pages) -> list[int]:
    if not document.permissions.copy:
        raise ReadOnlyDocument("Die Berechtigungen dieses PDFs erlauben keinen Export von Inhalten.")
    chosen = list(range(document.page_count)) if not pages else sorted({int(i) for i in pages})
    if not chosen or min(chosen) < 0 or max(chosen) >= document.page_count:
        raise UnsupportedEdit("Die Auswahl enthält eine Seite, die es nicht gibt.")
    if len(chosen) > MAX_PAGES:
        raise UnsupportedEdit(f"Höchstens {MAX_PAGES} Seiten auf einmal umwandeln.")
    return chosen


def _write(target: Path, data: bytes) -> Path:
    """Neue Datei schreiben (erst eine temporäre, dann umbenennen) – nie über eine bestehende."""
    target = Path(target)
    if not target.parent.is_dir():
        raise SaveFailed("Der Zielordner existiert nicht.")
    temp = target.parent / f".{target.stem[:40]}.pdftool-{secrets.token_hex(4)}.tmp"
    try:
        temp.write_bytes(data)
        os.replace(temp, target)
    except OSError as exc:
        raise SaveFailed(f"Die Datei konnte nicht gespeichert werden ({exc.strerror or 'Ein-/Ausgabefehler'}).") from exc
    finally:
        temp.unlink(missing_ok=True)
    return target


@dataclass
class Result:
    path: Path
    pages: int
    empty: list[int]  # Seiten ohne Text (0-basiert)


def convert(document: EditorDocument, target: str | os.PathLike, fmt: str, pages=None, *, progress=None, cancelled=None) -> Result:
    """Seiten ``pages`` (alle, wenn leer) als ``fmt`` (txt, docx, xlsx) nach ``target`` schreiben."""
    if fmt not in FORMATS:
        raise UnsupportedEdit("Unbekanntes Format.")
    chosen = _check(document, pages)
    layouts: list[PageLayout] = []
    for done, index in enumerate(chosen):
        if cancelled is not None and cancelled():
            raise UnsupportedEdit("Abgebrochen.")
        layouts.append(page_layout(document, index))
        if progress is not None:
            progress(done + 1, len(chosen))
    empty = [index for index, layout in zip(chosen, layouts) if not layout.lines]
    if fmt == "txt":
        data = to_text(layouts).encode("utf-8-sig")  # mit BOM: der Windows-Editor erkennt UTF-8 sicher
    elif fmt == "docx":
        images = {index: _page_jpeg(document, index) for index in empty}
        data = to_docx(layouts, [images.get(index) for index in chosen], title=document.path.stem if getattr(document, "path", None) else "")
    else:
        data = to_xlsx(layouts, chosen)
    return Result(_write(Path(target), data), len(chosen), empty)


def to_text(layouts: list[PageLayout]) -> str:
    """Absätze mit Leerzeilen, Tabellenzeilen mit Tabulatoren, Seiten durch einen Seitenvorschub getrennt."""
    body = _body_size(layouts)
    pages = []
    for layout in layouts:
        text, last = "", None
        for block in paragraphs(layout, body):
            if text:
                text += "\n" if block.row is not None and last is not None and last.row is not None else "\n\n"
            text += "\t".join(cell for cell, _left in block.row) if block.row is not None else block.text
            last = block
        pages.append(text)
    return "\n\n\f".join(pages).rstrip() + "\n"


# Word ---------------------------------------------------------------------------------------------------------------

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_PIC = ('xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _xml_text(value: str) -> str:
    return escape(_CONTROL.sub("", value))


def _page_jpeg(document: EditorDocument, index: int) -> tuple[bytes, float, float]:
    geo = document.geometry(index)
    image = render.to_pil(render.render_page(document, index, max(8, int(geo.width * 150 / 72)))).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85, optimize=True)
    return buffer.getvalue(), geo.width, geo.height


def _run(text: str, bold: bool, size: float | None) -> str:
    props = ("<w:b/>" if bold else "") + (f'<w:sz w:val="{max(2, round(size * 2))}"/>' if size else "")
    return f'<w:r>{"<w:rPr>" + props + "</w:rPr>" if props else ""}<w:t xml:space="preserve">{_xml_text(text)}</w:t></w:r>'


def _table(rows: list[Paragraph], page_width: float) -> str:
    starts = columns([row.row for row in rows])
    grid = [[""] * len(starts) for _ in rows]
    bold = [row.bold for row in rows]
    for number, row in enumerate(rows):
        for text, left in row.row:
            column = max(i for i, start in enumerate(starts) if start <= left + 0.01)
            while column < len(starts) - 1 and grid[number][column]:
                column += 1
            grid[number][column] = (grid[number][column] + " " + text).strip()
    # Spaltenbreiten nach Lage auf der Seite (in Twips, zusammen höchstens die Satzbreite von 16 cm)
    edges = [*starts, max(starts[-1] + 40, page_width * 0.92)]
    spans = [max(20.0, edges[i + 1] - edges[i]) for i in range(len(starts))]
    scale = 9072 / sum(spans)
    widths = [max(400, int(span * scale)) for span in spans]
    out = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders>'
           + "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>' for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
           + '</w:tblBorders><w:tblLook w:val="04A0"/></w:tblPr><w:tblGrid>' + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"]
    for number, row in enumerate(grid):
        out.append("<w:tr>")
        for column, text in enumerate(row):
            out.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[column]}" w:type="dxa"/></w:tcPr><w:p><w:pPr><w:spacing w:after="0"/></w:pPr>'
                       + (_run(text, bold[number], None) if text else "") + "</w:p></w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl><w:p/>")
    return "".join(out)


def to_docx(layouts: list[PageLayout], images: list[tuple[bytes, float, float] | None], title: str = "") -> bytes:
    body = _body_size(layouts)
    parts: list[str] = []
    media: list[bytes] = []
    for number, layout in enumerate(layouts):
        if number:
            parts.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        image = images[number] if number < len(images) else None
        if image is not None and not layout.lines:
            data, width, height = image
            media.append(data)
            ident = len(media)
            # Breite höchstens 16 cm (Satzspiegel A4), Seitenverhältnis bleibt
            cx = int(min(width / 72 * 914400, 16 / 2.54 * 914400))
            cy = int(cx * height / max(1.0, width))
            parts.append(
                f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{ident}" name="Seite {number + 1}"/>'
                f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
                f'<pic:nvPicPr><pic:cNvPr id="{ident}" name="seite{ident}.jpg"/><pic:cNvPicPr/></pic:nvPicPr>'
                f'<pic:blipFill><a:blip r:embed="rIdImage{ident}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
                f'</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
            continue
        blocks = paragraphs(layout, body)
        position = 0
        while position < len(blocks):
            if blocks[position].row is not None:  # aufeinanderfolgende Tabellenzeilen: eine Word-Tabelle
                end = position
                while end < len(blocks) and blocks[end].row is not None:
                    end += 1
                parts.append(_table(blocks[position:end], layout.width))
                position = end
                continue
            paragraph = blocks[position]
            position += 1
            style = f'<w:pPr><w:pStyle w:val="{paragraph.style}"/></w:pPr>' if paragraph.style else ""
            size = None if paragraph.style or abs(paragraph.size - body) < 0.6 or paragraph.size <= 0 else paragraph.size
            parts.append(f"<w:p>{style}{_run(paragraph.text, paragraph.bold and not paragraph.style, size)}</w:p>")
    if not parts:
        parts.append("<w:p/>")
    body_pt = body if 6 <= body <= 30 else 11
    document_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {_W} {_PIC}><w:body>{"".join(parts)}'
                    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
                    'w:header="709" w:footer="709" w:gutter="0"/></w:sectPr></w:body></w:document>')
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:styles {_W}>'
              f'<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri" w:eastAsia="Calibri"/>'
              f'<w:sz w:val="{round(body_pt * 2)}"/><w:lang w:val="de-DE"/></w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
              f'<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="{round(body_pt * 3.2)}"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
              f'<w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="{round(body_pt * 2.5)}"/></w:rPr></w:style>'
              '</w:styles>')
    images_rels = "".join(f'<Relationship Id="rIdImage{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/seite{i}.jpg"/>'
                          for i in range(1, len(media) + 1))
    rels_header = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    document_rels = (rels_header + '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                     + images_rels + "</Relationships>")
    package_rels = (rels_header + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/><Default Extension="jpg" ContentType="image/jpeg"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                     '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + _xml_text(title) + '</dc:title><dc:creator>Novadesk</dc:creator></cp:coreProperties>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", package_rels)
        package.writestr("docProps/core.xml", core)
        package.writestr("word/document.xml", document_xml)
        package.writestr("word/styles.xml", styles)
        package.writestr("word/_rels/document.xml.rels", document_rels)
        for i, data in enumerate(media, start=1):
            package.writestr(f"word/media/seite{i}.jpg", data, compress_type=zipfile.ZIP_STORED)
    return buffer.getvalue()


# Excel --------------------------------------------------------------------------------------------------------------

_NUMBER = re.compile(r"^[-+−]?(\d{1,3}([.   ]\d{3})+|\d+)(,\d+)?$")
_ENGLISH = re.compile(r"^[-+]?(\d{1,3}(,\d{3})+|\d+)\.\d+$")


def number(text: str) -> tuple[float | None, str]:
    """Zahl aus einer Zelle: »1.234,56«, »-12«, »12,5 %«, »1.234,00 €« → (Wert, Zahlenformat); sonst (None, "")."""
    value = text.strip()
    percent = value.endswith("%")
    currency = value.endswith("€") or value.startswith("€")
    value = value.strip("%€  ").replace("−", "-")
    # Postleitzahl, Kundennummer (»01067«, »007«) und Telefonnummer (»+49 221 …«) bleiben Text
    if value.startswith("+") or re.match(r"^-?0\d", value):
        return None, ""
    if _NUMBER.match(value):
        decimals = len(value.split(",")[1]) if "," in value else 0
        integer = value.split(",")[0]
        parsed = float(re.sub(r"[.   ]", "", value).replace(",", "."))
    elif _ENGLISH.match(value) and value.count(".") == 1:
        decimals = len(value.split(".")[1])
        integer = value.split(".")[0]
        parsed = float(value.replace(",", ""))
    else:
        return None, ""
    places = "0" if not decimals else "0." + "0" * decimals
    if percent:
        return parsed / 100, places + "%"
    # Tausenderpunkte nur, wenn die Zahl sie schon hatte – eine Jahreszahl »2026« bleibt »2026«, nicht »2.026«
    grouped = "#,##" + places if currency or not integer.lstrip("-+").isdigit() else places
    return parsed, (grouped + ' "€"') if currency else (grouped if decimals or grouped != places else "General")


_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")


def _date(text: str):
    """Datum »31.12.2026« → ``datetime.date``; sonst ``None``."""
    import datetime

    found = _DATE.match(text.strip())
    if not found:
        return None
    try:
        return datetime.date(int(found.group(3)), int(found.group(2)), int(found.group(1)))
    except ValueError:
        return None


def cells(line: Line) -> list[tuple[str, float]]:
    """Wörter einer Zeile zu Zellen: eine Lücke von mehr als zwei Zeichenbreiten trennt Zellen."""
    result: list[list] = []
    limit = max(4.0, line.size * 1.1)
    for text, left, right in line.words:
        if result and left - result[-1][2] <= limit:
            result[-1][0] += " " + text
            result[-1][2] = right
        else:
            result.append([text, left, right])
    return [(entry[0], entry[1]) for entry in result]


def columns(rows: list[list[tuple[str, float]]], tolerance: float = 14.0) -> list[float]:
    """Spaltenanfänge: Zellanfänge, die nah beieinander liegen, teilen sich eine Spalte."""
    starts = sorted(left for row in rows for _text, left in row)
    groups: list[list[float]] = []
    for value in starts:
        if groups and value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [min(group) for group in groups]


def to_xlsx(layouts: list[PageLayout], numbers: list[int]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    book = Workbook()
    book.remove(book.active)
    for layout, index in zip(layouts, numbers):
        sheet = book.create_sheet(f"Seite {index + 1}")
        rows = [cells(line) for line in layout.lines]
        starts = columns([row for row in rows if len(row) >= 2]) or [0.0]  # Spalten nur aus Tabellenzeilen
        widths: dict[int, int] = {}
        for row_number, (line, row) in enumerate(zip(layout.lines, rows), start=1):
            used: set[int] = set()
            for text, left in row:
                # Textzeilen (eine Zelle) beginnen in Spalte A, Tabellenzellen in ihrer Spalte
                column = 1 if len(row) == 1 else max([i for i, start in enumerate(starts) if start <= left + 0.01] or [0]) + 1
                while column in used:  # zwei Zellen in derselben Spalte: die zweite rückt nach rechts
                    column += 1
                used.add(column)
                cell = sheet.cell(row=row_number, column=column)
                value, fmt = number(text)
                moment = _date(text) if value is None else None
                if moment is not None:
                    cell.value = moment
                    cell.number_format = "DD.MM.YYYY"
                elif value is not None:
                    cell.value = value
                    cell.number_format = fmt
                else:
                    cell.value = _CONTROL.sub("", text)
                    cell.data_type = "s"  # Text wie »=== Summe ===« ist keine Formel
                if line.bold:
                    cell.font = Font(bold=True)
                if len(row) >= 2:  # lange Textzeilen dürfen über die Spalte hinauslaufen
                    widths[column] = max(widths.get(column, 0), len(text))
        for column, width in widths.items():
            sheet.column_dimensions[get_column_letter(column)].width = min(60, max(8, width + 2))
    if not book.worksheets:
        book.create_sheet("Seite 1")
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
