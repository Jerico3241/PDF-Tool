"""Serienbrief (seit 5.0 Beta 5): ein Brief an viele Empfänger aus einer Tabelle.

Im Text stehen Felder als »«Spaltenname»« (so zeigt auch Word Seriendruckfelder an). ``read_table`` liest die
Empfänger aus einer Excel-Mappe (.xlsx, .xlsm, .xls) oder CSV-Datei: erste Zeile = Spaltennamen, leere Zeilen fallen
weg. ``merge_odt`` erzeugt aus dem Text (als OpenDocument gespeichert) ein Dokument mit einem Brief je Empfänger, jeder
auf einer neuen Seite; die Felder werden ersetzt – auch dann, wenn LibreOffice ein Feld beim Speichern in mehrere
Abschnitte geteilt hat (etwa weil ein Teil fett ist).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

OPEN, CLOSE = "«", "»"
MAX_RECIPIENTS = 5000
SUFFIXES = (".xlsx", ".xlsm", ".xls", ".csv", ".txt")
FILTER = "Tabellen (*.xlsx *.xlsm *.xls *.csv);;Alle Dateien (*.*)"
BREAK_STYLE = "NovadeskSerienbriefUmbruch"


class MergeError(Exception):
    """Fehler mit einem Text für die Oberfläche."""


def field(name: str) -> str:
    return OPEN + name + CLOSE


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Ja" if value else "Nein"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y") if (value.hour, value.minute, value.second) == (0, 0, 0) else value.strftime("%d.%m.%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.10g}".replace(".", ",")
    return str(value).strip()


def _rows_csv(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        class dialect(csv.excel):  # noqa: N801 - wie die Dialekte des Moduls csv
            delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), dialect)]


def _rows_excel(path: Path) -> list[list[str]]:
    if path.suffix.lower() == ".xls":
        import xlrd

        book = xlrd.open_workbook(str(path))
        sheet = book.sheet_by_index(0)
        rows = []
        for index in range(sheet.nrows):
            row = []
            for cell in sheet.row(index):
                if cell.ctype == xlrd.XL_CELL_DATE:
                    row.append(_cell(xlrd.xldate_as_datetime(cell.value, book.datemode)))
                else:
                    row.append(_cell(cell.value))
            rows.append(row)
        return rows
    import openpyxl

    book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        sheet = book.worksheets[0]
        return [[_cell(value) for value in row] for row in sheet.iter_rows(values_only=True)]
    finally:
        book.close()


def read_table(path: str) -> tuple[list[str], list[dict[str, str]]]:
    """Spalten (Namen aus der ersten Zeile) und Empfänger der Tabelle."""
    source = Path(path)
    try:
        rows = _rows_csv(source) if source.suffix.lower() in (".csv", ".txt") else _rows_excel(source)
    except MergeError:
        raise
    except Exception as exc:  # noqa: BLE001 - jede Lesefehler-Art als Hinweis
        raise MergeError(f"Die Tabelle ließ sich nicht lesen ({exc.__class__.__name__}).") from exc
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        raise MergeError("Die Tabelle ist leer.")
    header = rows[0]
    columns: list[str] = []
    for index, name in enumerate(header):
        name = re.sub(r"\s+", " ", str(name or "")).strip().replace(OPEN, "").replace(CLOSE, "") or f"Spalte {index + 1}"
        base, number = name, 2
        while name in columns:
            name = f"{base} {number}"
            number += 1
        columns.append(name)
    while columns and columns[-1].startswith("Spalte ") and not any(len(row) >= len(columns) and row[len(columns) - 1] for row in rows[1:]):
        columns.pop()
    if not columns:
        raise MergeError("Die erste Zeile der Tabelle braucht Spaltennamen.")
    records = [{name: (row[index] if index < len(row) else "") for index, name in enumerate(columns)} for row in rows[1:]]
    if not records:
        raise MergeError("Die Tabelle hat unter den Spaltennamen keine Empfänger.")
    if len(records) > MAX_RECIPIENTS:
        raise MergeError(f"Die Tabelle hat mehr als {MAX_RECIPIENTS} Empfänger.")
    return columns, records


def _field_pattern(name: str) -> re.Pattern:
    """»«Name»« im XML – zwischen zwei Zeichen dürfen Auszeichnungen stehen (Abschnitte mit anderem Format)."""
    tags = r"(?:<[^>]*>)*"
    chars = [re.escape(escape(char)) for char in OPEN + name + CLOSE]
    return re.compile(tags.join(chars))


def _replace(xml: str, record: dict[str, str], patterns: dict[str, re.Pattern]) -> str:
    for name, pattern in patterns.items():
        value = escape(record.get(name, ""))

        def keep_tags(match: re.Match, value=value) -> str:
            # Der Wert ersetzt die Zeichen des Feldes; Auszeichnungen dazwischen bleiben (sonst stimmt das XML nicht)
            return value + "".join(re.findall(r"<[^>]*>", match.group(0)))

        xml = pattern.sub(keep_tags, xml)
    return xml


def fields_in(xml: str, columns: list[str]) -> list[str]:
    return [name for name in columns if _field_pattern(name).search(xml)]


def merge_odt(template: str, records: list[dict[str, str]], columns: list[str], target: str) -> int:
    """Ein Brief je Empfänger in ``target`` (OpenDocument-Text); gibt die Zahl der Briefe zurück."""
    with zipfile.ZipFile(template) as source:
        names = source.namelist()
        files = {name: source.read(name) for name in names}
    content = files["content.xml"].decode("utf-8")
    start = re.search(r"<office:text\b[^>]*>", content)
    end = content.rfind("</office:text>")
    if not start or end < 0:
        raise MergeError("Der Text ließ sich nicht lesen.")
    head, body, tail = content[:start.end()], content[start.end():end], content[end:]
    # Vorspann (Formularfelder, Variablen, Verzeichnisse der Änderungen …) gehört nur einmal an den Anfang
    prelude = ""
    leading = re.match(r"(\s*(?:<text:(?:variable|sequence|user-field|dde-connection)-decls>.*?</text:(?:variable|sequence|user-field|dde-connection)-decls>|<text:tracked-changes[^>]*/>|<text:tracked-changes\b.*?</text:tracked-changes>|<office:forms\b[^>]*/>|<office:forms\b.*?</office:forms>)\s*)+", body, re.S)
    if leading:
        prelude, body = body[:leading.end()], body[leading.end():]
    patterns = {name: _field_pattern(name) for name in columns}
    letters = []
    for number, record in enumerate(records):
        letter = _replace(body, record, patterns)
        if number:
            letter = f'<text:p text:style-name="{BREAK_STYLE}"/>' + letter
        letters.append(letter)
    style = (f'<style:style style:name="{BREAK_STYLE}" style:family="paragraph"><style:paragraph-properties fo:break-before="page" '
             'fo:margin-top="0cm" fo:margin-bottom="0cm" fo:line-height="0.05cm"/><style:text-properties fo:font-size="1pt"/></style:style>')
    if "<office:automatic-styles/>" in head:
        head = head.replace("<office:automatic-styles/>", f"<office:automatic-styles>{style}</office:automatic-styles>", 1)
    elif "</office:automatic-styles>" in head:
        head = head.replace("</office:automatic-styles>", style + "</office:automatic-styles>", 1)
    else:
        head = head.replace("<office:body>", f"<office:automatic-styles>{style}</office:automatic-styles><office:body>", 1)
    files["content.xml"] = (head + prelude + "".join(letters) + tail).encode("utf-8")
    with zipfile.ZipFile(target, "w") as out:
        for name in names:
            # »mimetype« zuerst und unkomprimiert (so verlangt es OpenDocument)
            if name == "mimetype":
                out.writestr(zipfile.ZipInfo("mimetype"), files[name], compress_type=zipfile.ZIP_STORED)
        for name in names:
            if name != "mimetype":
                out.writestr(name, files[name], compress_type=zipfile.ZIP_DEFLATED)
    return len(records)
