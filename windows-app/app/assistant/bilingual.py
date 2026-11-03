"""Übersetzung nebeneinander (seit 5.0 Beta 8): Original und Übersetzung Absatz für Absatz in zwei Spalten, als neues
Text-Dokument (OpenDocument in einer Datei, .fodt). Novadesk öffnet es als neues, noch nicht gespeichertes Dokument –
man kann es lesen, bearbeiten, als Word-Datei speichern oder drucken.

``Block`` ist ein Abschnitt des Originals (eine Seite eines PDFs, eine Folie oder der ganze Text) mit seinen Absätzen;
``rows`` ordnet jedem Absatz seine Übersetzung zu. Übersetzt wird in Stücken aus mehreren Absätzen – damit die
Zuordnung stimmt, schickt Novadesk jeden Absatz mit einer Nummer (»[3] …«) und liest die Nummern in der Antwort
zurück (``numbered``/``split_numbered``). Fehlt eine Nummer, wird dieser Absatz einzeln nachübersetzt.
"""

from __future__ import annotations

I18N_CALLS = ()  # Anweisungen an das Sprachmodell und Dokumentinhalt – keine Oberflächentexte (tools/i18n_extract.py)

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

ACCENT, LINE, LIGHT, GREY = "#0f6cbd", "#d1d1d1", "#eef5fc", "#605e5c"
FONT = "Calibri"
MAX_PARAGRAPHS = 1500  # so viele Absätze höchstens (sonst dauert es Stunden)
CHUNK_CHARS = 2000
_NUMBER = re.compile(r"^\s*\[(\d{1,4})\]\s?", re.MULTILINE)


@dataclass
class Block:
    label: str  # »Seite 3«, »Folie 2« – leer beim ganzen Text
    paragraphs: list[str] = field(default_factory=list)
    translated: list[str] = field(default_factory=list)


def paragraphs(text: str) -> list[str]:
    """Absätze eines Textes: Leerzeilen trennen; innerhalb eines Absatzes werden Zeilenumbrüche zu Leerzeichen
    (Seitentext aus PDFs bricht mitten im Satz um)."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    result = []
    for part in re.split(r"\n\s*\n", text):
        joined = " ".join(line.strip() for line in part.split("\n") if line.strip())
        if joined:
            result.append(joined)
    return result


def chunks(items: list[str], size: int = CHUNK_CHARS) -> list[list[int]]:
    """Absätze (ihre Nummern) in Stücke von höchstens etwa ``size`` Zeichen."""
    result: list[list[int]] = []
    current: list[int] = []
    used = 0
    for index, item in enumerate(items):
        if current and used + len(item) > size:
            result.append(current)
            current, used = [], 0
        current.append(index)
        used += len(item) + 6
    if current:
        result.append(current)
    return result


def numbered(items: list[str], indexes: list[int]) -> str:
    return "\n\n".join(f"[{number}] {items[index]}" for number, index in enumerate(indexes, start=1))


def split_numbered(answer: str, count: int) -> list[str | None]:
    """Antwort mit »[1] … [2] …« in ``count`` Teile; fehlende Nummern ergeben ``None``."""
    result: list[str | None] = [None] * count
    matches = list(_NUMBER.finditer(str(answer or "")))
    for position, match in enumerate(matches):
        number = int(match.group(1))
        end = matches[position + 1].start() if position + 1 < len(matches) else len(answer)
        text = " ".join(answer[match.end():end].split())
        if 1 <= number <= count and text and result[number - 1] is None:
            result[number - 1] = text
    if count == 1 and result[0] is None and str(answer or "").strip():
        result[0] = " ".join(str(answer).split())  # ein Absatz ohne Nummer zurück
    return result


def _p(text: str, style: str) -> str:
    return f'<text:p text:style-name="{style}">{escape(text)}</text:p>'


def write_fodt(blocks: list[Block], target: str | Path, *, title: str, source: str, language: str) -> Path:
    """Tabelle »Original | Übersetzung« als Text-Dokument. Abschnitte (Seiten, Folien) bekommen eine Zwischenzeile."""
    rows = []
    for block in blocks:
        if block.label:
            rows.append(
                '<table:table-row><table:table-cell table:style-name="T.B" table:number-columns-spanned="2" office:value-type="string">'
                f'{_p(block.label, "Abschnitt")}</table:table-cell><table:covered-table-cell/></table:table-row>'
            )
        for index, original in enumerate(block.paragraphs):
            translated = block.translated[index] if index < len(block.translated) else ""
            rows.append(
                '<table:table-row>'
                f'<table:table-cell table:style-name="T.D" office:value-type="string">{_p(original, "Zelle")}</table:table-cell>'
                f'<table:table-cell table:style-name="T.D" office:value-type="string">{_p(translated or "–", "Zelle")}</table:table-cell>'
                '</table:table-row>'
            )
    header = (
        '<table:table-header-rows><table:table-row>'
        f'<table:table-cell table:style-name="T.H" office:value-type="string">{_p("Original", "Kopf")}</table:table-cell>'
        f'<table:table-cell table:style-name="T.H" office:value-type="string">{_p("Übersetzung (" + language + ")", "Kopf")}</table:table-cell>'
        '</table:table-row></table:table-header-rows>'
    )
    table = ('<table:table table:name="Übersetzung" table:style-name="T"><table:table-column table:style-name="T.C"/>'
             '<table:table-column table:style-name="T.C"/>' + header + "".join(rows) + "</table:table>")
    styles = (
        '<style:default-style style:family="paragraph"><style:paragraph-properties fo:line-height="115%"/>'
        f'<style:text-properties style:font-name="{FONT}" fo:font-size="10.5pt" fo:language="de" fo:country="DE"/></style:default-style>'
        f'<style:style style:name="Standard" style:family="paragraph"><style:text-properties style:font-name="{FONT}" fo:font-size="10.5pt" fo:color="#242424"/></style:style>'
        f'<style:style style:name="Title" style:display-name="Titel" style:family="paragraph"><style:paragraph-properties fo:margin-bottom="0.1cm"/>'
        f'<style:text-properties style:font-name="{FONT}" fo:font-size="20pt" fo:font-weight="bold" fo:color="{ACCENT}"/></style:style>'
        f'<style:style style:name="Klein" style:family="paragraph"><style:paragraph-properties fo:margin-bottom="0.4cm"/>'
        f'<style:text-properties style:font-name="{FONT}" fo:font-size="9pt" fo:color="{GREY}"/></style:style>'
        f'<style:style style:name="Kopf" style:family="paragraph"><style:text-properties style:font-name="{FONT}" fo:font-size="10.5pt" fo:font-weight="bold" fo:color="#ffffff"/></style:style>'
        f'<style:style style:name="Abschnitt" style:family="paragraph"><style:text-properties style:font-name="{FONT}" fo:font-size="10pt" fo:font-weight="bold" fo:color="{ACCENT}"/></style:style>'
        f'<style:style style:name="Zelle" style:family="paragraph"><style:paragraph-properties fo:margin-bottom="0cm"/><style:text-properties style:font-name="{FONT}" fo:font-size="10.5pt"/></style:style>'
    )
    automatic = (
        '<style:page-layout style:name="Seite"><style:page-layout-properties fo:page-width="29.7cm" fo:page-height="21cm" '
        'fo:margin-top="1.6cm" fo:margin-bottom="1.6cm" fo:margin-left="1.8cm" fo:margin-right="1.8cm" style:print-orientation="landscape"/></style:page-layout>'
        '<style:style style:name="T" style:family="table"><style:table-properties style:width="26.1cm" table:align="left"/></style:style>'
        '<style:style style:name="T.C" style:family="table-column"><style:table-column-properties style:column-width="13.05cm"/></style:style>'
        f'<style:style style:name="T.H" style:family="table-cell"><style:table-cell-properties fo:background-color="{ACCENT}" fo:padding="0.15cm" fo:border="none"/></style:style>'
        f'<style:style style:name="T.B" style:family="table-cell"><style:table-cell-properties fo:background-color="{LIGHT}" fo:padding="0.12cm" fo:border="none"/></style:style>'
        f'<style:style style:name="T.D" style:family="table-cell"><style:table-cell-properties fo:padding="0.15cm" fo:border-left="none" fo:border-right="none" fo:border-top="none" fo:border-bottom="0.5pt solid {LINE}"/></style:style>'
    )
    namespaces = (
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
        'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/"'
    )
    body = (_p(title, "Title") + _p(f"Übersetzt mit dem KI-Assistenten von Novadesk aus »{source}«. Bitte wichtige Stellen im Original prüfen.", "Klein")
            + table)
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<office:document {namespaces} office:version="1.3" office:mimetype="application/vnd.oasis.opendocument.text">'
        f'<office:meta><dc:title>{escape(title)}</dc:title><meta:generator>Novadesk</meta:generator></office:meta>'
        f'<office:font-face-decls><style:font-face style:name="{FONT}" svg:font-family="{FONT}" style:font-family-generic="swiss"/></office:font-face-decls>'
        f'<office:styles>{styles}</office:styles><office:automatic-styles>{automatic}</office:automatic-styles>'
        '<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="Seite"/></office:master-styles>'
        f'<office:body><office:text>{body}</office:text></office:body></office:document>\n'
    )
    target = Path(target)
    target.write_text(document, encoding="utf-8")
    return target
