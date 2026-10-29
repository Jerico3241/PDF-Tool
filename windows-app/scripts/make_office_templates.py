"""Erzeugt die Vorlagen von Novadesk (seit 5.0 Beta 6) für Texte, Tabellen und Präsentationen.

* ``app/vorlagen/<name>.fodt|.fods|.fodp`` – die Vorlagen als OpenDocument in einer Datei (XML, lesbar im
  Repository). Novadesk öffnet sie als neues, noch nicht gespeichertes Dokument; gespeichert wird als .docx, .xlsx
  bzw. .pptx (oder was man wählt).
* ``app/qml/images/vorlagen/<name>.png`` – das Vorschaubild für die Seite »Vorlagen« (erste Seite bzw. Folie,
  gemalt von LibreOffice).

Die Ergebnisse liegen im Repository – der Build braucht dieses Skript nicht. Aufruf (aus dem Repository-Hauptordner,
LibreOffice als ``soffice`` im PATH nötig, Pillow für die Vorschaubilder):
    python windows-app/scripts/make_office_templates.py
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / "windows-app"
TARGET = APP_ROOT / "app" / "vorlagen"
PREVIEWS = APP_ROOT / "app" / "qml" / "images" / "vorlagen"
PREVIEW_WIDTH = 480  # doppelt so breit wie die Karte auf der Seite »Vorlagen«

ACCENT = "#0f6cbd"  # Blau aus Novadesk
ACCENT_LIGHT = "#e8f1fb"
GREY = "#605e5c"
LINE = "#d1d1d1"
FONT = "Calibri"  # unter Windows immer da; LibreOffice nimmt sonst das maßgleiche Carlito

NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
    'xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0" '
    'xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:loext="urn:org:documentfoundation:names:experimental:office:xmlns:loext:1.0"'
)


def x(value: str) -> str:
    return escape(str(value), {'"': "&quot;"})


def document(mimetype: str, title: str, font_decls: str, styles: str, automatic: str, masters: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<office:document {NS} office:version="1.3" office:mimetype="{mimetype}">\n'
        f'<office:meta><dc:title>{x(title)}</dc:title><meta:generator>Novadesk</meta:generator></office:meta>\n'
        f'<office:font-face-decls>{font_decls}</office:font-face-decls>\n'
        f'<office:styles>{styles}</office:styles>\n'
        f'<office:automatic-styles>{automatic}</office:automatic-styles>\n'
        f'<office:master-styles>{masters}</office:master-styles>\n'
        f'<office:body>{body}</office:body>\n'
        '</office:document>\n'
    )


FONTS = f'<style:font-face style:name="{FONT}" svg:font-family="{FONT}" style:font-family-generic="swiss"/>'


# Texte ---------------------------------------------------------------------------------------------------------------
def text_styles() -> str:
    def paragraph(name: str, size: float, *, bold: bool = False, color: str = "#242424", before: float = 0,
                  after: float = 0.2, display: str = "", outline: int = 0, extra: str = "", keep: bool = False) -> str:
        outline_attr = f' style:default-outline-level="{outline}"' if outline else ""
        return (
            f'<style:style style:name="{name}" style:display-name="{display or name}" style:family="paragraph" '
            f'style:parent-style-name="Standard"{outline_attr}>'
            f'<style:paragraph-properties fo:margin-top="{before}cm" fo:margin-bottom="{after}cm"'
            f'{" fo:keep-with-next=\"always\"" if keep else ""}{extra}/>'
            f'<style:text-properties style:font-name="{FONT}" fo:font-size="{size}pt" fo:color="{color}"'
            f'{" fo:font-weight=\"bold\"" if bold else ""}/></style:style>'
        )

    return (
        '<style:default-style style:family="paragraph"><style:paragraph-properties fo:line-height="115%"/>'
        f'<style:text-properties style:font-name="{FONT}" fo:font-size="11pt" fo:language="de" fo:country="DE"/>'
        '</style:default-style>'
        f'<style:style style:name="Standard" style:family="paragraph" style:class="text">'
        f'<style:paragraph-properties fo:margin-top="0cm" fo:margin-bottom="0.2cm"/>'
        f'<style:text-properties style:font-name="{FONT}" fo:font-size="11pt" fo:color="#242424"/></style:style>'
        + paragraph("Title", 26, bold=True, color=ACCENT, after=0.1, display="Titel")
        + paragraph("Subtitle", 13, color=GREY, after=0.5, display="Untertitel")
        + paragraph("Heading_20_1", 15, bold=True, color=ACCENT, before=0.5, after=0.15, display="Überschrift 1", outline=1, keep=True,
                    extra=f' fo:border-bottom="0.75pt solid {LINE}" fo:padding-bottom="0.08cm"')
        + paragraph("Heading_20_2", 12, bold=True, color="#242424", before=0.3, after=0.1, display="Überschrift 2", outline=2, keep=True)
        + paragraph("Right", 11, display="Rechtsbündig", extra=' fo:text-align="end"')
        + paragraph("Small", 9, color=GREY, after=0.05, display="Klein")
        + paragraph("Table_20_Contents", 10.5, after=0.05, display="Tabelleninhalt")
        + paragraph("Table_20_Heading", 10.5, bold=True, color="#ffffff", after=0.05, display="Tabellenüberschrift")
        + '<style:style style:name="Strong" style:display-name="Fett" style:family="text"><style:text-properties fo:font-weight="bold"/></style:style>'
        + f'<style:style style:name="Accent" style:display-name="Akzent" style:family="text"><style:text-properties fo:color="{ACCENT}" fo:font-weight="bold"/></style:style>'
        + '<text:list-style style:name="Bullets" style:display-name="Aufzählung">'
        + '<text:list-level-style-bullet text:level="1" text:bullet-char="•"><style:list-level-properties text:list-level-position-and-space-mode="label-alignment">'
        + '<style:list-level-label-alignment text:label-followed-by="listtab" text:list-tab-stop-position="0.635cm" fo:text-indent="-0.4cm" fo:margin-left="0.635cm"/>'
        + f'</style:list-level-properties><style:text-properties fo:color="{ACCENT}"/></text:list-level-style-bullet></text:list-style>'
    )


def page_layout(top: float = 2.0, bottom: float = 2.0, left: float = 2.5, right: float = 2.0) -> str:
    return (
        '<style:page-layout style:name="Seite"><style:page-layout-properties fo:page-width="21cm" fo:page-height="29.7cm" '
        f'fo:margin-top="{top}cm" fo:margin-bottom="{bottom}cm" fo:margin-left="{left}cm" fo:margin-right="{right}cm" '
        'style:print-orientation="portrait"/>'
        '<style:footer-style><style:header-footer-properties fo:min-height="0.6cm" fo:margin-top="0.4cm"/></style:footer-style>'
        '</style:page-layout>'
    )


def table_automatic(name: str, widths: list[float], *, header: bool = True, lines: bool = True, shade_first: bool = False) -> str:
    total = sum(widths)
    parts = [f'<style:style style:name="{name}" style:family="table"><style:table-properties style:width="{total}cm" '
             'table:align="left" fo:margin-top="0.1cm" fo:margin-bottom="0.3cm"/></style:style>']
    for index, width in enumerate(widths):
        parts.append(f'<style:style style:name="{name}.C{index}" style:family="table-column">'
                     f'<style:table-column-properties style:column-width="{width}cm"/></style:style>')
    border = f'0.5pt solid {LINE}' if lines else "none"
    parts.append(f'<style:style style:name="{name}.H" style:family="table-cell"><style:table-cell-properties '
                 f'fo:background-color="{ACCENT}" fo:padding="0.12cm" fo:border="none"/></style:style>')
    parts.append(f'<style:style style:name="{name}.D" style:family="table-cell"><style:table-cell-properties '
                 f'fo:padding="0.12cm" fo:border-left="none" fo:border-right="none" fo:border-top="none" fo:border-bottom="{border}"/></style:style>')
    parts.append(f'<style:style style:name="{name}.S" style:family="table-cell"><style:table-cell-properties '
                 f'fo:background-color="{ACCENT_LIGHT}" fo:padding="0.12cm" fo:border-left="none" fo:border-right="none" '
                 f'fo:border-top="none" fo:border-bottom="{border}"/></style:style>')
    del header, shade_first
    return "".join(parts)


def p(text: str = "", style: str = "Standard") -> str:
    return f'<text:p text:style-name="{style}">{inline(text)}</text:p>'


def h(text: str, level: int = 1) -> str:
    return f'<text:h text:style-name="Heading_20_{level}" text:outline-level="{level}">{inline(text)}</text:h>'


def inline(text: str) -> str:
    """**fett** und [Platzhalter] (blau) im Fließtext."""
    out, rest = [], str(text)
    while rest:
        bold, slot = rest.find("**"), rest.find("[")
        starts = [pos for pos in (bold, slot) if pos >= 0]
        if not starts:
            out.append(x(rest))
            break
        first = min(starts)
        out.append(x(rest[:first]))
        if first == bold:
            end = rest.find("**", bold + 2)
            if end < 0:
                out.append(x(rest[bold:]))
                break
            out.append(f'<text:span text:style-name="Strong">{x(rest[bold + 2:end])}</text:span>')
            rest = rest[end + 2:]
        else:
            end = rest.find("]", slot)
            if end < 0:
                out.append(x(rest[slot:]))
                break
            out.append(f'<text:span text:style-name="Accent">{x(rest[slot:end + 1])}</text:span>')
            rest = rest[end + 1:]
    return "".join(out)


def bullets(items: list[str]) -> str:
    return ('<text:list text:style-name="Bullets">'
            + "".join(f'<text:list-item>{p(item)}</text:list-item>' for item in items) + '</text:list>')


def table(name: str, columns: int, rows: list[list[str]], *, header: bool = True, shade: bool = False) -> str:
    out = [f'<table:table table:name="{name}" table:style-name="{name}">']
    out += [f'<table:table-column table:style-name="{name}.C{index}"/>' for index in range(columns)]
    for number, row in enumerate(rows):
        is_header = header and number == 0
        if is_header:
            out.append('<table:table-header-rows>')
        out.append('<table:table-row>')
        for index, cell in enumerate(row):
            kind = "H" if is_header else ("S" if shade and index == 0 else "D")
            style = "Table_20_Heading" if is_header else "Table_20_Contents"
            content = "".join(p(line, style) for line in str(cell).split("\n"))
            out.append(f'<table:table-cell table:style-name="{name}.{kind}" office:value-type="string">{content}</table:table-cell>')
        out.append('</table:table-row>')
        if is_header:
            out.append('</table:table-header-rows>')
    out.append('</table:table>')
    return "".join(out)


def text_document(title: str, automatic: str, body: str, footer: str = "", left: float = 2.5) -> str:
    footer_xml = (f'<style:footer>{p(footer, "Small")}</style:footer>' if footer else "")
    masters = f'<style:master-page style:name="Standard" style:page-layout-name="Seite">{footer_xml}</style:master-page>'
    return document("application/vnd.oasis.opendocument.text", title, FONTS, text_styles(), page_layout(left=left) + automatic,
                    masters, f'<office:text>{body}</office:text>')


def cv() -> str:
    automatic = (table_automatic("Kopf", [11.0, 5.5], lines=False) + table_automatic("Lauf", [4.0, 12.5], lines=False)
                 + table_automatic("Kenntnisse", [4.0, 12.5], lines=False))
    body = (
        table("Kopf", 2, [[
            "[Vorname Nachname]\n[Berufsbezeichnung, z. B. Kaufmännische Angestellte]",
            "[Straße Nr.]\n[PLZ Ort]\n[Telefon]\n[E-Mail]",
        ]], header=False)
        + h("Profil")
        + p("[Zwei bis drei Sätze über Sie: was Sie können, was Sie suchen und was Sie auszeichnet – zum Beispiel "
            "»Zuverlässige Kauffrau mit acht Jahren Erfahrung in Buchhaltung und Kundenservice.«]")
        + h("Berufserfahrung")
        + table("Lauf", 2, [
            ["[MM/JJJJ] – heute", "**[Position]**\n[Firma, Ort]\n[Aufgaben und Erfolge in einem Satz]"],
            ["[MM/JJJJ] – [MM/JJJJ]", "**[Position]**\n[Firma, Ort]\n[Aufgaben und Erfolge in einem Satz]"],
            ["[MM/JJJJ] – [MM/JJJJ]", "**[Position]**\n[Firma, Ort]\n[Aufgaben und Erfolge in einem Satz]"],
        ], header=False)
        + h("Ausbildung")
        + table("Lauf", 2, [
            ["[MM/JJJJ] – [MM/JJJJ]", "**[Abschluss]**\n[Schule, Hochschule oder Betrieb, Ort]"],
            ["[MM/JJJJ] – [MM/JJJJ]", "**[Abschluss]**\n[Schule, Ort]"],
        ], header=False).replace('table:name="Lauf"', 'table:name="Lauf2"')
        + h("Kenntnisse")
        + table("Kenntnisse", 2, [
            ["Sprachen", "[Deutsch (Muttersprache), Englisch (fließend)]"],
            ["EDV", "[Novadesk, Word, Excel, DATEV]"],
            ["Führerschein", "[Klasse B]"],
        ], header=False)
        + p("") + p("[Ort], [Datum]", "Small")
    )
    # Kopf: Name groß und blau
    body = body.replace(
        f'<text:p text:style-name="Table_20_Contents"><text:span text:style-name="Accent">[Vorname Nachname]</text:span></text:p>',
        '<text:p text:style-name="Title"><text:span text:style-name="Accent">[Vorname Nachname]</text:span></text:p>', 1)
    return text_document("Lebenslauf", automatic, body)


def letter() -> str:
    automatic = table_automatic("Absender", [8.5, 8.0], lines=False)
    body = (
        p("[Ihre Firma] · [Straße Nr.] · [PLZ Ort]", "Small")
        + p("") + p("[Firma des Empfängers]") + p("[Frau/Herrn Vorname Nachname]") + p("[Straße Nr.]") + p("[PLZ Ort]")
        + p("") + p("") + p("[Ort], [TT.MM.JJJJ]", "Right")
        + p("") + p("**[Betreff: worum es geht, in einer Zeile]**")
        + p("") + p("Sehr geehrte [Frau/Herr Nachname],")
        + p("[Erster Absatz: der Anlass Ihres Schreibens.]")
        + p("[Zweiter Absatz: die Einzelheiten – was Sie anbieten, erklären oder erbitten.]")
        + p("[Dritter Absatz: der nächste Schritt, z. B. ein Termin oder eine Frist.]")
        + p("") + p("Mit freundlichen Grüßen") + p("") + p("") + p("[Vorname Nachname]") + p("[Funktion]", "Small")
    )
    return text_document("Geschäftsbrief", automatic, body,
                         footer="[Ihre Firma] · [Telefon] · [E-Mail] · [Website] · IBAN [DE00 0000 0000 0000 0000 00]")


def report() -> str:
    automatic = table_automatic("Kennzahlen", [6.0, 3.5, 3.5, 3.5])
    body = (
        p("Bericht", "Title") + p("[Thema des Berichts] · [Abteilung] · [Monat JJJJ]", "Subtitle")
        + h("Zusammenfassung")
        + p("[Das Wichtigste in drei bis fünf Sätzen: Ausgangslage, Ergebnis und Empfehlung. Wer nur diesen Abschnitt "
            "liest, soll Bescheid wissen.]")
        + h("Ausgangslage")
        + p("[Warum gibt es diesen Bericht? Was war das Ziel, welcher Zeitraum ist betrachtet?]")
        + h("Ergebnisse")
        + h("Kennzahlen", 2)
        + table("Kennzahlen", 4, [
            ["Kennzahl", "Vorjahr", "Aktuell", "Veränderung"],
            ["[Umsatz]", "[0 €]", "[0 €]", "[+0 %]"],
            ["[Kunden]", "[0]", "[0]", "[+0 %]"],
            ["[Aufträge]", "[0]", "[0]", "[+0 %]"],
        ], shade=True)
        + h("Beobachtungen", 2)
        + bullets(["[Erste Beobachtung]", "[Zweite Beobachtung]", "[Dritte Beobachtung]"])
        + h("Empfehlung")
        + p("[Was soll als Nächstes geschehen – von wem und bis wann?]")
        + h("Anhang")
        + p("[Quellen, Tabellen oder weitere Unterlagen]", "Small")
    )
    return text_document("Bericht", automatic, body, footer="[Thema des Berichts] · [Verfasser] · [Datum]")


def minutes() -> str:
    automatic = table_automatic("Rahmen", [4.0, 12.5], lines=False) + table_automatic("Aufgaben", [8.5, 4.5, 3.5])
    body = (
        p("Besprechungsprotokoll", "Title") + p("[Name der Besprechung]", "Subtitle")
        + table("Rahmen", 2, [
            ["Datum", "[TT.MM.JJJJ], [10:00] – [11:00] Uhr"],
            ["Ort", "[Raum oder Online]"],
            ["Teilnehmende", "[Namen]"],
            ["Protokoll", "[Name]"],
        ], header=False, shade=True)
        + h("Tagesordnung")
        + bullets(["[Punkt 1]", "[Punkt 2]", "[Punkt 3]"])
        + h("Ergebnisse")
        + h("[Punkt 1]", 2) + p("[Was besprochen und entschieden wurde.]")
        + h("[Punkt 2]", 2) + p("[Was besprochen und entschieden wurde.]")
        + h("Aufgaben")
        + table("Aufgaben", 3, [
            ["Aufgabe", "Wer", "Bis wann"],
            ["[Aufgabe]", "[Name]", "[TT.MM.]"],
            ["[Aufgabe]", "[Name]", "[TT.MM.]"],
            ["[Aufgabe]", "[Name]", "[TT.MM.]"],
        ])
        + p("Nächste Besprechung: [TT.MM.JJJJ]", "Small")
    )
    return text_document("Besprechungsprotokoll", automatic, body)


# Tabellen ------------------------------------------------------------------------------------------------------------
def sheet_document(title: str, automatic: str, tables: str) -> str:
    styles = (
        '<number:currency-style style:name="Euro0" style:volatile="true" number:language="de" number:country="DE"><number:number number:decimal-places="2" '
        'number:min-decimal-places="2" number:min-integer-digits="1" number:grouping="true"/><number:text> </number:text>'
        '<number:currency-symbol number:language="de" number:country="DE">€</number:currency-symbol></number:currency-style>'
        '<number:currency-style style:name="Euro" number:language="de" number:country="DE"><style:text-properties fo:color="#c50f1f"/><number:text>-</number:text>'
        '<number:number number:decimal-places="2" number:min-decimal-places="2" number:min-integer-digits="1" number:grouping="true"/>'
        '<number:text> </number:text><number:currency-symbol number:language="de" number:country="DE">€</number:currency-symbol>'
        '<style:map style:condition="value()&gt;=0" style:apply-style-name="Euro0"/></number:currency-style>'
        '<number:percentage-style style:name="Prozent" number:language="de" number:country="DE"><number:number number:decimal-places="0" number:min-decimal-places="0" '
        'number:min-integer-digits="1"/><number:text>%</number:text></number:percentage-style>'
        '<number:date-style style:name="Datum" number:language="de" number:country="DE"><number:day number:style="long"/><number:text>.</number:text>'
        '<number:month number:style="long"/><number:text>.</number:text><number:year number:style="long"/></number:date-style>'
        f'<style:default-style style:family="table-cell"><style:text-properties style:font-name="{FONT}" fo:font-size="11pt" '
        'fo:language="de" fo:country="DE"/></style:default-style>'
        f'<style:style style:name="Default" style:family="table-cell"><style:text-properties style:font-name="{FONT}" fo:font-size="11pt"/></style:style>'
    )
    automatic += ('<style:page-layout style:name="Druck"><style:page-layout-properties fo:page-width="21cm" fo:page-height="29.7cm" '
                  'fo:margin-top="1.5cm" fo:margin-bottom="1.5cm" fo:margin-left="1.5cm" fo:margin-right="1.5cm"/></style:page-layout>')
    masters = ('<style:master-page style:name="Default" style:page-layout-name="Druck">'
               '<style:header style:display="false"/><style:footer style:display="false"/></style:master-page>')
    return document("application/vnd.oasis.opendocument.spreadsheet", title, FONTS, styles, automatic, masters,
                    f'<office:spreadsheet>{tables}</office:spreadsheet>')


def cell_styles() -> str:
    def style(name: str, *, size: float = 11, bold: bool = False, color: str = "#242424", background: str = "",
              border: str = "", number: str = "", align: str = "", indent: bool = False) -> str:
        data = f' style:data-style-name="{number}"' if number else ""
        props = []
        if background:
            props.append(f'fo:background-color="{background}"')
        if border:
            props.append(border)
        props.append('style:vertical-align="middle"')
        if indent:
            props.append('fo:padding-left="0.1cm"')
        para = f'<style:paragraph-properties fo:text-align="{align}"/>' if align else ""
        return (f'<style:style style:name="{name}" style:family="table-cell" style:parent-style-name="Default"{data}>'
                f'<style:table-cell-properties {" ".join(props)}/>{para}'
                f'<style:text-properties fo:font-size="{size}pt" fo:color="{color}"{" fo:font-weight=\"bold\"" if bold else ""}/></style:style>')

    bottom = f'fo:border-bottom="0.5pt solid {LINE}"'
    return (
        style("Titel", size=22, bold=True, color=ACCENT)
        + style("Grau", size=10, color=GREY)
        + style("Fett", bold=True)
        + style("Kopf", bold=True, color="#ffffff", background=ACCENT, indent=True)
        + style("KopfRechts", bold=True, color="#ffffff", background=ACCENT, align="end")
        + style("Zeile", border=bottom, indent=True)
        + style("ZeileZahl", border=bottom, align="end")
        + style("ZeileEuro", border=bottom, number="Euro")
        + style("ZeileProzent", border=bottom, number="Prozent")
        + style("Euro", number="Euro")
        + style("EuroFett", bold=True, number="Euro")
        + style("Summe", bold=True, background=ACCENT_LIGHT, indent=True)
        + style("SummeEuro", bold=True, background=ACCENT_LIGHT, number="Euro")
        + style("Gesamt", bold=True, size=13, color="#ffffff", background=ACCENT, indent=True)
        + style("GesamtEuro", bold=True, size=13, color="#ffffff", background=ACCENT, number="Euro")
        + style("Datum", number="Datum", align="start")
    )


def columns(name: str, widths: list[float]) -> str:
    return "".join(f'<style:style style:name="{name}{index}" style:family="table-column">'
                   f'<style:table-column-properties style:column-width="{width}cm"/></style:style>'
                   for index, width in enumerate(widths))


def row_style(name: str, height: float) -> str:
    return (f'<style:style style:name="{name}" style:family="table-row"><style:table-row-properties '
            f'style:row-height="{height}cm" style:use-optimal-row-height="false"/></style:style>')


def c(value="", style: str = "", formula: str = "", kind: str = "") -> str:
    """Eine Zelle: Text, Zahl (int/float) oder Formel (``formula`` in OpenFormula, z. B. ``of:=[.B2]*[.C2]``)."""
    style_attr = f' table:style-name="{style}"' if style else ""
    if formula:
        # Ohne gespeicherten Wert: LibreOffice rechnet beim Öffnen (gespeicherte Werte nähme es sonst ungeprüft)
        return f'<table:table-cell{style_attr} table:formula="{x(formula)}"/>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value_type = kind or "float"
        extra = f' office:currency="EUR"' if value_type == "currency" else ""
        return (f'<table:table-cell{style_attr} office:value-type="{value_type}"{extra} office:value="{value}">'
                f'<text:p>{value}</text:p></table:table-cell>')
    if value == "":
        return f'<table:table-cell{style_attr}/>'
    return f'<table:table-cell{style_attr} office:value-type="string"><text:p>{x(value)}</text:p></table:table-cell>'


def row(cells: list[str], style: str = "") -> str:
    style_attr = f' table:style-name="{style}"' if style else ""
    return f'<table:table-row{style_attr}>{"".join(cells)}</table:table-row>'


def invoice() -> str:
    widths = [1.2, 6.8, 1.7, 1.9, 2.8, 3.2]
    automatic = (cell_styles() + columns("rc", widths) + row_style("hoch", 1.1) + row_style("zeile", 0.75)
                 + '<style:style style:name="blatt" style:family="table"><style:table-properties table:display="true"/></style:style>')
    rows = [
        row([c("Rechnung", "Titel")] + [c()] * 5, "hoch"),
        row([c("[Ihre Firma] · [Straße Nr.] · [PLZ Ort] · [Telefon] · [E-Mail]", "Grau")] + [c()] * 5),
        row([c()] * 6),
        row([c("[Firma des Kunden]", "Fett"), c(), c(), c(), c("Rechnungsnummer", "Grau"), c("[2026-001]")]),
        row([c("[Vorname Nachname]"), c(), c(), c(), c("Rechnungsdatum", "Grau"), c("[TT.MM.JJJJ]")]),
        row([c("[Straße Nr.]"), c(), c(), c(), c("Kundennummer", "Grau"), c("[K-1000]")]),
        row([c("[PLZ Ort]")] + [c()] * 5),
        row([c()] * 6),
        row([c("Pos.", "Kopf"), c("Beschreibung", "Kopf"), c("Menge", "KopfRechts"), c("Einheit", "Kopf"),
             c("Einzelpreis", "KopfRechts"), c("Gesamt", "KopfRechts")], "zeile"),
    ]
    items = [("[Leistung oder Artikel]", 1, "Stk.", 100), ("[Leistung oder Artikel]", 2, "Std.", 65),
             ("[Leistung oder Artikel]", 1, "Pausch.", 49.9), ("", "", "", ""), ("", "", "", "")]
    first = len(rows) + 1
    for number, (text, amount, unit, price) in enumerate(items, start=1):
        line = len(rows) + 1
        rows.append(row([
            c(number if text else "", "ZeileZahl"), c(text, "Zeile"), c(amount, "ZeileZahl"), c(unit, "Zeile"),
            c(price, "ZeileEuro", kind="currency") if price != "" else c("", "ZeileEuro"),
            c(formula=f"of:=IF(OR([.C{line}]=\"\";[.E{line}]=\"\");\"\";[.C{line}]*[.E{line}])", style="ZeileEuro", kind="currency"),
        ], "zeile"))
    last = len(rows)
    net, tax = last + 2, last + 3
    rows += [
        row([c()] * 6),
        row([c(), c(), c(), c(), c("Netto", "Summe"), c(formula=f"of:=SUM([.F{first}:.F{last}])", style="SummeEuro", kind="currency")], "zeile"),
        row([c(), c(), c(), c(), c("USt. 19 %", "Summe"), c(formula=f"of:=ROUND([.F{net}]*0.19;2)", style="SummeEuro", kind="currency")], "zeile"),
        row([c(), c(), c(), c(), c("Gesamt", "Gesamt"), c(formula=f"of:=[.F{net}]+[.F{tax}]", style="GesamtEuro", kind="currency")], "hoch"),
        row([c()] * 6),
        row([c("Bitte überweisen Sie den Betrag innerhalb von 14 Tagen auf das Konto unten. Vielen Dank für Ihren Auftrag!")] + [c()] * 5),
        row([c()] * 6),
        row([c("[Bank] · IBAN [DE00 0000 0000 0000 0000 00] · BIC [XXXXDEXX] · USt-IdNr. [DE000000000]", "Grau")] + [c()] * 5),
    ]
    table_xml = (f'<table:table table:name="Rechnung" table:style-name="blatt">'
                 + "".join(f'<table:table-column table:style-name="rc{index}"/>' for index in range(len(widths)))
                 + "".join(rows) + '</table:table>')
    return sheet_document("Rechnung", automatic, table_xml)


def budget() -> str:
    widths = [6.0, 3.2, 3.2, 3.2]
    automatic = cell_styles() + columns("bc", widths) + row_style("hoch", 1.1) + row_style("zeile", 0.7)
    rows = [
        row([c("Haushaltsbudget", "Titel"), c(), c(), c()], "hoch"),
        row([c("[Monat JJJJ] · Beträge in Euro – die blauen Summen rechnen von selbst", "Grau"), c(), c(), c()]),
        row([c()] * 4),
        row([c("Einnahmen", "Kopf"), c("Geplant", "KopfRechts"), c("Tatsächlich", "KopfRechts"), c("Differenz", "KopfRechts")], "zeile"),
    ]

    def block(entries: list[tuple[str, float, float]], income: bool) -> tuple[int, int]:
        start = len(rows) + 1
        for name, plan, actual in entries:
            line = len(rows) + 1
            difference = f"of:=[.C{line}]-[.B{line}]" if income else f"of:=[.B{line}]-[.C{line}]"
            rows.append(row([c(name, "Zeile"), c(plan, "ZeileEuro", kind="currency"), c(actual, "ZeileEuro", kind="currency"),
                             c(formula=difference, style="ZeileEuro", kind="currency")], "zeile"))
        return start, len(rows)

    start, end = block([("Gehalt", 2800, 2800), ("Nebenjob", 450, 380), ("Kindergeld", 255, 255), ("Sonstiges", 0, 60)], True)
    income_row = len(rows) + 1
    rows.append(row([c("Summe Einnahmen", "Summe"), c(formula=f"of:=SUM([.B{start}:.B{end}])", style="SummeEuro", kind="currency"),
                     c(formula=f"of:=SUM([.C{start}:.C{end}])", style="SummeEuro", kind="currency"),
                     c(formula=f"of:=[.C{income_row}]-[.B{income_row}]", style="SummeEuro", kind="currency")], "zeile"))
    rows.append(row([c()] * 4))
    rows.append(row([c("Ausgaben", "Kopf"), c("Geplant", "KopfRechts"), c("Tatsächlich", "KopfRechts"), c("Differenz", "KopfRechts")], "zeile"))
    start, end = block([("Miete und Nebenkosten", 1100, 1100), ("Strom und Internet", 120, 118), ("Lebensmittel", 450, 486),
                        ("Auto und Fahrkarten", 220, 195), ("Versicherungen", 140, 140), ("Freizeit", 150, 172),
                        ("Sparen", 300, 300), ("Sonstiges", 100, 64)], False)
    spend_row = len(rows) + 1
    rows.append(row([c("Summe Ausgaben", "Summe"), c(formula=f"of:=SUM([.B{start}:.B{end}])", style="SummeEuro", kind="currency"),
                     c(formula=f"of:=SUM([.C{start}:.C{end}])", style="SummeEuro", kind="currency"),
                     c(formula=f"of:=[.B{spend_row}]-[.C{spend_row}]", style="SummeEuro", kind="currency")], "zeile"))
    rows.append(row([c()] * 4))
    rows.append(row([c("Übrig am Monatsende", "Gesamt"), c(formula=f"of:=[.B{income_row}]-[.B{spend_row}]", style="GesamtEuro", kind="currency"),
                     c(formula=f"of:=[.C{income_row}]-[.C{spend_row}]", style="GesamtEuro", kind="currency"), c("", "Gesamt")], "hoch"))
    table_xml = (f'<table:table table:name="Budget">'
                 + "".join(f'<table:table-column table:style-name="bc{index}"/>' for index in range(len(widths)))
                 + "".join(rows) + '</table:table>')
    return sheet_document("Haushaltsbudget", automatic, table_xml)


# Präsentation --------------------------------------------------------------------------------------------------------
def presentation() -> str:
    width, height = 28.0, 15.75
    styles = (
        f'<style:default-style style:family="graphic"><style:text-properties style:font-name="{FONT}" fo:language="de" fo:country="DE"/></style:default-style>'
        '<draw:gradient draw:name="Novadesk" draw:style="linear" draw:start-color="#1f4e79" draw:end-color="#2e75b6" '
        'draw:start-intensity="100%" draw:end-intensity="100%" draw:angle="450" draw:border="0%"/>'
    )
    automatic = (
        '<style:page-layout style:name="Folie"><style:page-layout-properties fo:margin-top="0cm" fo:margin-bottom="0cm" '
        f'fo:margin-left="0cm" fo:margin-right="0cm" fo:page-width="{width}cm" fo:page-height="{height}cm" style:print-orientation="landscape"/></style:page-layout>'
        '<style:style style:name="hell" style:family="drawing-page"><style:drawing-page-properties draw:fill="solid" '
        'draw:fill-color="#ffffff" presentation:background-visible="true" presentation:background-objects-visible="true"/></style:style>'
        '<style:style style:name="dunkel" style:family="drawing-page"><style:drawing-page-properties draw:fill="gradient" '
        'draw:fill-gradient-name="Novadesk" presentation:background-visible="true" presentation:background-objects-visible="true"/></style:style>'
        '<style:style style:name="leiste" style:family="graphic"><style:graphic-properties draw:fill="solid" '
        'draw:fill-color="#ffc000" draw:stroke="none"/></style:style>'
        f'<style:style style:name="band" style:family="graphic"><style:graphic-properties draw:fill="solid" draw:fill-color="{ACCENT}" draw:stroke="none"/></style:style>'
        '<style:style style:name="rahmen" style:family="graphic"><style:graphic-properties draw:fill="none" draw:stroke="none" '
        'fo:padding="0.2cm" draw:textarea-vertical-align="top" draw:auto-grow-height="false"/></style:style>'
        '<style:style style:name="mitte" style:family="graphic"><style:graphic-properties draw:fill="none" draw:stroke="none" '
        'fo:padding="0.2cm" draw:textarea-vertical-align="middle" draw:auto-grow-height="false"/></style:style>'
        f'<style:style style:name="kachel" style:family="graphic"><style:graphic-properties draw:fill="solid" draw:fill-color="{ACCENT_LIGHT}" '
        'draw:stroke="none" fo:padding="0.4cm" draw:textarea-vertical-align="top" draw:auto-grow-height="false"/></style:style>'
        + "".join(
            f'<style:style style:name="{name}" style:family="paragraph"><style:paragraph-properties fo:text-align="{align}" '
            f'fo:margin-bottom="{after}cm"/><style:text-properties style:font-name="{FONT}" fo:font-size="{size}pt" fo:color="{color}"'
            f'{" fo:font-weight=\"bold\"" if bold else ""}/></style:style>'
            for name, size, color, bold, align, after in (
                ("gross", 44, "#ffffff", True, "start", 0.2), ("unter", 20, "#ddebf7", False, "start", 0.1),
                ("titel", 30, ACCENT, True, "start", 0.1), ("text", 18, "#242424", False, "start", 0.25),
                ("zahl", 40, ACCENT, True, "start", 0.0), ("klein", 14, "#605e5c", False, "start", 0.1),
                ("weiss", 30, "#ffffff", True, "start", 0.1), ("weissklein", 18, "#ddebf7", False, "start", 0.1),
            ))
        + f'<text:list-style style:name="punkte"><text:list-level-style-bullet text:level="1" text:bullet-char="•">'
        '<style:list-level-properties text:space-before="0cm" text:min-label-width="0.8cm"/>'
        f'<style:text-properties fo:color="{ACCENT}" fo:font-size="18pt"/></text:list-level-style-bullet></text:list-style>'
    )
    masters = ('<style:master-page style:name="Novadesk" style:page-layout-name="Folie" draw:style-name="hell">'
               f'<draw:rect draw:style-name="leiste" svg:x="0cm" svg:y="0cm" svg:width="0.5cm" svg:height="{height}cm"/>'
               '</style:master-page>')

    def frame(x_cm: float, y_cm: float, w: float, h_cm: float, paragraphs: str, style: str = "rahmen") -> str:
        return (f'<draw:frame draw:style-name="{style}" svg:x="{x_cm}cm" svg:y="{y_cm}cm" svg:width="{w}cm" svg:height="{h_cm}cm">'
                f'<draw:text-box>{paragraphs}</draw:text-box></draw:frame>')

    def para(text: str, style: str) -> str:
        return f'<text:p text:style-name="{style}">{x(text)}</text:p>'

    def points(items: list[str]) -> str:
        return ('<text:list text:style-name="punkte">'
                + "".join(f'<text:list-item>{para(item, "text")}</text:list-item>' for item in items) + '</text:list>')

    def slide(name: str, content: str, dark: bool = False) -> str:
        return (f'<draw:page draw:name="{name}" draw:style-name="{"dunkel" if dark else "hell"}" '
                f'draw:master-page-name="Novadesk">{content}</draw:page>')

    def title(text: str) -> str:
        return frame(1.6, 0.9, 24.8, 1.8, para(text, "titel"))

    slides = [
        slide("Titel", frame(1.6, 4.6, 22.0, 3.0, para("[Projektname]", "gross"), "mitte")
              + frame(1.6, 7.7, 22.0, 2.6, para("[Worum es geht, in einem Satz]", "unter") + para("[Name] · [Datum]", "unter"))
              + f'<draw:rect draw:style-name="leiste" svg:x="1.8cm" svg:y="7.4cm" svg:width="4cm" svg:height="0.15cm"/>', dark=True),
        slide("Ausgangslage", title("Ausgangslage")
              + frame(1.6, 3.0, 24.8, 11.0, points(["[Was ist heute das Problem?]", "[Wen betrifft es?]",
                                                    "[Was kostet es, wenn nichts geschieht?]"]))),
        slide("Ziele", title("Ziele")
              + frame(1.6, 3.3, 7.6, 9.5, para("1", "zahl") + para("[Erstes Ziel]", "text") + para("[Woran man den Erfolg misst]", "klein"), "kachel")
              + frame(10.2, 3.3, 7.6, 9.5, para("2", "zahl") + para("[Zweites Ziel]", "text") + para("[Woran man den Erfolg misst]", "klein"), "kachel")
              + frame(18.8, 3.3, 7.6, 9.5, para("3", "zahl") + para("[Drittes Ziel]", "text") + para("[Woran man den Erfolg misst]", "klein"), "kachel")),
        slide("Zeitplan", title("Zeitplan")
              + f'<draw:rect draw:style-name="band" svg:x="1.8cm" svg:y="7.2cm" svg:width="24.4cm" svg:height="0.2cm"/>'
              + "".join(
                  f'<draw:rect draw:style-name="leiste" svg:x="{1.8 + index * 8.1}cm" svg:y="6.85cm" svg:width="0.9cm" svg:height="0.9cm"/>'
                  + frame(1.6 + index * 8.1, 8.2, 7.6, 4.0, para(when, "titel").replace('"titel"', '"text"') + para(what, "klein"))
                  for index, (when, what) in enumerate((("[Monat 1]", "[Start und Planung]"), ("[Monat 2]", "[Umsetzung]"),
                                                        ("[Monat 3]", "[Abschluss und Übergabe]"))))),
        slide("Nächste Schritte", frame(1.6, 3.0, 24.8, 2.2, para("Nächste Schritte", "weiss"))
              + frame(1.6, 5.4, 24.8, 7.0, para("[Was wir heute entscheiden möchten]", "weissklein")
                      + para("[Wer macht was bis wann]", "weissklein") + para("Fragen? [E-Mail]", "weissklein")), dark=True),
    ]
    return document("application/vnd.oasis.opendocument.presentation", "Projektvorstellung", FONTS, styles, automatic, masters,
                    f'<office:presentation>{"".join(slides)}</office:presentation>')


TEMPLATES = {
    "lebenslauf.fodt": cv,
    "geschaeftsbrief.fodt": letter,
    "bericht.fodt": report,
    "protokoll.fodt": minutes,
    "rechnung.fods": invoice,
    "budget.fods": budget,
    "projektvorstellung.fodp": presentation,
}


def render_preview(source: Path, target: Path) -> None:
    """Erste Seite bzw. Folie als PNG (LibreOffice), auf ``PREVIEW_WIDTH`` verkleinert."""
    with tempfile.TemporaryDirectory() as work:
        profile = Path(work) / "profil"
        subprocess.run(["soffice", f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", "png",
                        "--outdir", work, str(source)], check=True, capture_output=True, timeout=120)
        image = Image.open(Path(work) / (source.stem + ".png")).convert("RGB")
        image = image.resize((PREVIEW_WIDTH, round(image.height * PREVIEW_WIDTH / image.width)), Image.LANCZOS)
        image.save(target, optimize=True)


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    if shutil.which("soffice") is None:
        raise SystemExit("LibreOffice (soffice) fehlt im PATH")
    for name, build in TEMPLATES.items():
        path = TARGET / name
        path.write_text(build(), encoding="utf-8")
        render_preview(path, PREVIEWS / (path.stem + ".png"))
        print(f"{name}: {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
