"""PDF-Engine für die Vertragsübersicht – gleiche Regeln wie das Originalskript."""

from __future__ import annotations

import os
import re
import tempfile
import html
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

pd = None
pdfcanvas = None
mm = None
colors = None
PILImage = None
Paragraph = None
SimpleDocTemplate = None
Spacer = None
Table = None
TableStyle = None
Image = None
HRFlowable = None
ParagraphStyle = None
getSampleStyleSheet = None
TA_CENTER = TA_LEFT = TA_RIGHT = None
A4 = None
landscape = None
PRIMARY = ROW_ALT = HEADER_BG = GRID = TEXT_DARK = None
_NummernCanvas = None


def _lade_pandas():
    global pd
    if pd is None:
        import pandas as geladen

        pd = geladen


def _lade_pdf():
    global pdfcanvas, mm, colors, PILImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    global Image, HRFlowable, ParagraphStyle, getSampleStyleSheet, TA_CENTER, TA_LEFT, TA_RIGHT
    global A4, landscape, PRIMARY, ROW_ALT, HEADER_BG, GRID, TEXT_DARK, _NummernCanvas
    _lade_pandas()
    if pdfcanvas is not None:
        return
    from PIL import Image as _pil
    from reportlab.lib import colors as _colors
    from reportlab.lib.enums import TA_CENTER as _c, TA_LEFT as _l, TA_RIGHT as _r
    from reportlab.lib.pagesizes import A4 as _a4, landscape as _land
    from reportlab.lib.styles import ParagraphStyle as _ps, getSampleStyleSheet as _sheet
    from reportlab.lib.units import mm as _mm
    from reportlab.pdfgen import canvas as _pdfcanvas
    from reportlab.platypus import (
        HRFlowable as _hr,
        Image as _image,
        Paragraph as _para,
        SimpleDocTemplate as _doc,
        Spacer as _spacer,
        Table as _table,
        TableStyle as _tstyle,
    )

    PILImage = _pil
    colors = _colors
    TA_CENTER, TA_LEFT, TA_RIGHT = _c, _l, _r
    A4, landscape = _a4, _land
    ParagraphStyle, getSampleStyleSheet = _ps, _sheet
    mm = _mm
    pdfcanvas = _pdfcanvas
    HRFlowable, Image, Paragraph = _hr, _image, _para
    SimpleDocTemplate, Spacer, Table, TableStyle = _doc, _spacer, _table, _tstyle
    PRIMARY = colors.HexColor("#B51F1F")
    ROW_ALT = colors.HexColor("#FDF2F2")
    HEADER_BG = PRIMARY
    GRID = colors.HexColor("#CCCCCC")
    TEXT_DARK = colors.HexColor("#333333")

    class _Canvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._states: list[dict] = []

        def showPage(self):
            self._states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            states = list(self._states)
            total = len(states)
            for state in states:
                self.__dict__.update(state)
                self._zeichne_seitenzahl(total)
                pdfcanvas.Canvas.showPage(self)
            pdfcanvas.Canvas.save(self)

        def _zeichne_seitenzahl(self, total: int) -> None:
            text = f"Seite {self._pageNumber} von {total}"
            self.saveState()
            self.setFont("Helvetica", 8)
            self.setFillColor(TEXT_DARK)
            width, _height = self._pagesize
            self.drawRightString(width - 14 * mm, 5 * mm, text)
            self.restoreState()

    _NummernCanvas = _Canvas

ZAHLUNGSART_MAP = {
    "Lastschr": "Lastschrift",
    "Lastschrift": "Lastschrift",
    "Sofort": "Sofort",
    "Überweisung": "Überweisung",
    "Ueberweisung": "Überweisung",
}


def clean_bemerkung(text: str) -> str:
    if pd.isna(text):
        return ""
    text = str(text).strip()
    if text.lower().startswith("x "):
        text = text[2:].strip()
    text = re.sub(r"(?i)^sw[\s\-]?pflege\s*", "", text)
    return text.strip()


def fmt_date(d) -> str:
    if pd.isna(d):
        return "–"
    if not hasattr(d, "strftime"):
        d = pd.to_datetime(d, errors="coerce")
        if pd.isna(d):
            return "–"
    return d.strftime("%d.%m.%Y")


def fmt_euro(v) -> str:
    if pd.isna(v):
        return "–"
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


DEFAULT_REGELN = [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}]


def regeln_lesen(raw) -> list[dict]:
    if not isinstance(raw, list):
        return [dict(eintrag) for eintrag in DEFAULT_REGELN]
    regeln = []
    for eintrag in raw:
        if not isinstance(eintrag, dict):
            continue
        nadel = str(eintrag.get("enthaelt") or "").strip()
        ziel = str(eintrag.get("zyklus") or "").strip()
        if nadel and ziel:
            regeln.append({"enthaelt": nadel, "zyklus": ziel})
    return regeln


def _regel_passt(bemerkung, nadel: str) -> bool:
    text = "" if pd.isna(bemerkung) else str(bemerkung).lower()
    such = nadel.strip().lower()
    if not such:
        return False
    if such in text:
        return True
    kompakt = re.sub(r"[^a-z0-9]+", "", text)
    such_kompakt = re.sub(r"[^a-z0-9]+", "", such)
    return len(such_kompakt) >= 4 and such_kompakt in kompakt


def fmt_zyklus(wert, bemerkung, regeln=None) -> str:
    """Regeln ersetzen falsche Monats-/Jahresangaben. Das Datum dahinter bleibt stehen."""
    if pd.isna(wert):
        text = "–"
    else:
        text = str(wert).strip() or "–"
    aktiv = DEFAULT_REGELN if regeln is None else regeln
    for regel in aktiv:
        if not _regel_passt(bemerkung, regel["enthaelt"]):
            continue
        ziel = regel["zyklus"]
        if text == "–":
            text = ziel
            continue
        text = re.sub(r"(?i)jeden\s+monat", ziel, text)
        text = re.sub(r"(?i)\bmonatlich\b", ziel, text)
        text = re.sub(r"(?i)\bmtl\.?\b", ziel, text)
        text = re.sub(r"(?i)jedes\s+jahr", ziel, text)
        text = re.sub(r"(?i)\bjährlich\b", ziel, text)
        text = re.sub(r"(?i)\bjaehrlich\b", ziel, text)
    return text


def fmt_zahlungsart(v) -> str:
    if pd.isna(v):
        return "–"
    raw = str(v).strip()
    return ZAHLUNGSART_MAP.get(raw, raw)


def vertrag_art(bemerkung) -> str:
    text = "" if pd.isna(bemerkung) else str(bemerkung).lower()
    if "hotline" in text:
        return "Supportvertrag"
    return "Software-<br/>pflegevertrag"


def _col(df: pd.DataFrame, *namen: str, required: bool = True) -> str:
    wanted = {re.sub(r"[^a-z0-9]+", "", n.lower()) for n in namen}
    for col in df.columns:
        key = re.sub(r"[^a-z0-9]+", "", str(col).lower())
        if key in wanted:
            return str(col)
    if required:
        raise ValueError(
            "In der Excel fehlt die Spalte "
            + " / ".join(namen)
            + ".\nGefundene Spalten: "
            + ", ".join(str(c) for c in df.columns)
        )
    return ""


@dataclass
class PdfAuftrag:
    excel: Path
    logo: Path
    kundennummer: str
    firmenname: str = ""
    rechnungsempfaenger: str = ""
    zielordner: Path | None = None
    dateiname: str = "Vertragsuebersicht_Kd{kd}.pdf"
    seitenformat: str = "hoch"
    logo_breite: float = 62
    titel: str = "Vertragsübersicht"
    untertitel: str = "Wartungs- und Nutzungsverträge"
    fusszeile: str = ""
    kopfzeile: str = ""
    regeln: list | None = None
    pdf_oeffnen: bool = False
    status: Callable[[str], None] | None = None


def _mehrzeilig(text: str | None) -> str:
    """Mehrzeiligen Text (Fußzeile) unverändert übernehmen – Absätze bleiben erhalten.

    Vereinheitlicht werden nur die Zeilenenden; entfernt werden lediglich Leerraum und
    Zeilenumbrüche ganz am Ende. Text nur aus Leerzeichen gilt als leer.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip() if text.strip() else ""


def _zelltext(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def nur_aktive(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Nur Zeilen mit Anwenderstatus Aktiv. Fehlt die Spalte, bleibt die Liste unverändert."""
    col = _col(df, "Anwenderstatus", "Status", required=False)
    if not col:
        return df, 0
    status = df[col].astype(str).str.strip().str.casefold()
    aktiv = df.loc[status.eq("aktiv")].copy()
    return aktiv, int(len(df) - len(aktiv))


def _eindeutig(df: pd.DataFrame, spalte: str) -> list[str]:
    if not spalte or spalte not in df.columns:
        return []
    werte: list[str] = []
    for raw in df[spalte].dropna().tolist():
        text = _zelltext(raw)
        if text and text not in werte:
            werte.append(text)
    return werte


def pruefe_excel(pfad: Path, regeln=None) -> dict:
    """Liest die Liste nur zur Kontrolle, ohne ein PDF zu schreiben."""
    _lade_pandas()
    leer = {"ok": False, "text": "", "kunden": [], "mails": [], "firmen": [], "zeilen": []}
    pfad = Path(pfad)
    if not pfad.is_file():
        return {**leer, "text": "Datei nicht gefunden."}
    try:
        df = pd.read_excel(pfad)
        col_vertrag = _col(df, "Vertrag-Nr.", "VertragNr", "Vertragsnummer")
    except Exception as exc:
        return {**leer, "text": str(exc)}
    daten = df.dropna(subset=[col_vertrag]).copy()
    daten, ausgeblendet = nur_aktive(daten)
    col_beginn = _col(df, "Beginnt am", "Beginn", "Startdatum", required=False)
    if col_beginn:
        daten["_sort"] = pd.to_datetime(daten[col_beginn], errors="coerce")
        daten = daten.sort_values("_sort")
    anzahl = int(len(daten))
    kunden = _eindeutig(daten, _col(df, "Kundennummer", "Kd-Nr.", "KdNr", required=False))
    mails = _eindeutig(
        daten,
        _col(df, "Rechnungsempfänger Email", "Rechnungsempfaenger Email", required=False),
    )
    firmen = _eindeutig(daten, _col(df, "Firmenname", "Firma", "Kunde", required=False))
    col_bem = _col(df, "Bemerkung", "Beschreibung", required=False)
    col_zyk = _col(df, "Abrechnungszyklus", required=False)
    col_netto = _col(df, "Netto [€]", "Netto", "Netto €", "Netto EUR", required=False)
    zeilen = []
    for _, row in daten.iterrows():
        bem = row[col_bem] if col_bem else ""
        zyk = row[col_zyk] if col_zyk else ""
        zeilen.append(
            {
                "nr": _zelltext(row[col_vertrag]),
                "text": clean_bemerkung(bem),
                "zyklus": fmt_zyklus(zyk, bem, regeln),
                "netto": fmt_euro(row[col_netto]) if col_netto else "–",
            }
        )
    if anzahl == 0:
        text = "Keine aktiven Verträge"
    elif anzahl == 1:
        text = "1 aktiver Vertrag"
    else:
        text = f"{anzahl} aktive Verträge"
    if ausgeblendet:
        text += f" · {ausgeblendet} inaktiv ausgeblendet"
    if len(kunden) == 1:
        text += f" · Kd {kunden[0]}"
    elif len(kunden) > 1:
        text += f" · {len(kunden)} Kundennummern"
    if len(firmen) == 1:
        text += f" · {firmen[0]}"
    elif len(firmen) > 1:
        text += f" · {len(firmen)} Firmen"
    if len(mails) == 1:
        text += f" · {mails[0]}"
    elif len(mails) > 1:
        text += f" · {len(mails)} Rechnungsempfänger"
    return {"ok": True, "text": text, "kunden": kunden, "mails": mails, "firmen": firmen, "zeilen": zeilen}


def _status(auftrag: PdfAuftrag, text: str) -> None:
    if auftrag.status:
        auftrag.status(text)


def erstelle_pdf(auftrag: PdfAuftrag) -> Path:
    _lade_pdf()
    excel = Path(auftrag.excel)
    logo_datei = Path(auftrag.logo)
    if not excel.is_file():
        raise FileNotFoundError(f"Excel-Datei nicht gefunden:\n{excel}")
    if not logo_datei.is_file():
        raise FileNotFoundError(f"Logo-Datei nicht gefunden:\n{logo_datei}")

    kundennummer = str(auftrag.kundennummer or "").strip()
    if not kundennummer:
        raise ValueError("Bitte eine Kundennummer eintragen.")

    _status(auftrag, "Excel wird gelesen …")
    df = pd.read_excel(excel)
    col_vertrag = _col(df, "Vertrag-Nr.", "VertragNr", "Vertragsnummer")
    col_beginn = _col(df, "Beginnt am", "Beginn", "Startdatum")
    col_zyklus = _col(df, "Abrechnungszyklus")
    col_netto = _col(df, "Netto [€]", "Netto", "Netto €", "Netto EUR")
    col_zahlung = _col(df, "Zahlungsart")
    col_bemerkung = _col(df, "Bemerkung", "Beschreibung")
    col_mail = _col(df, "Rechnungsempfänger Email", "Rechnungsempfaenger Email", required=False)

    df = df.dropna(subset=[col_vertrag]).copy()
    df, _ausgeblendet = nur_aktive(df)
    if df.empty:
        raise ValueError("Die Excel enthält keine aktiven Verträge.")
    df[col_beginn] = pd.to_datetime(df[col_beginn], errors="coerce")
    df = df.sort_values(col_beginn).reset_index(drop=True)

    emails = []
    if col_mail:
        emails = (
            df[col_mail].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()
        )
    angegeben = auftrag.rechnungsempfaenger.strip()
    if angegeben:
        rechnungsempfaenger = angegeben
    elif len(emails) == 1:
        rechnungsempfaenger = emails[0]
    else:
        rechnungsempfaenger = "–"
    zyklus_regeln = DEFAULT_REGELN if auftrag.regeln is None else auftrag.regeln

    firmenname = auftrag.firmenname.strip()
    jetzt = datetime.now()
    tokens = {
        "kd": kundennummer,
        "kundennummer": kundennummer,
        "datum": jetzt.strftime("%Y-%m-%d"),
        "datumkurz": jetzt.strftime("%d.%m.%Y"),
        "kunde": re.sub(r"[^\w\-]+", "_", firmenname, flags=re.UNICODE).strip("_") or kundennummer,
        "firma": re.sub(r"[^\w\-]+", "_", firmenname, flags=re.UNICODE).strip("_") or kundennummer,
    }
    muster = auftrag.dateiname.strip() or "Vertragsuebersicht_Kd{kd}.pdf"
    if not muster.lower().endswith(".pdf"):
        muster += ".pdf"
    dateiname = muster.format(**tokens)
    dateiname = re.sub(r"(?i)(?<=Kd)\d+", kundennummer, dateiname)

    ordner = Path(auftrag.zielordner) if auftrag.zielordner else excel.parent
    if ordner.suffix.lower() == ".pdf":
        ordner = ordner.parent
    ordner.mkdir(parents=True, exist_ok=True)
    ausgabe_pdf = ordner / dateiname

    _status(auftrag, "Logo wird vorbereitet …")
    img = PILImage.open(logo_datei)
    if img.mode in ("RGBA", "LA"):
        prepared = PILImage.new("RGB", img.size, (255, 255, 255))
        prepared.paste(img, mask=img.split()[-1])
    else:
        prepared = img.convert("RGB")
    w_px, h_px = prepared.size
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    logo_path = tmp.name
    tmp.close()
    prepared.save(logo_path, "PNG")

    try:
        _status(auftrag, "PDF wird gesetzt …")
        quer = str(auftrag.seitenformat).lower() in {"quer", "querformat", "landscape", "q"}
        logo_mm = float(auftrag.logo_breite)

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "TitleDE",
            parent=styles["Title"],
            fontSize=15,
            leading=18,
            alignment=TA_CENTER,
            spaceAfter=2,
            textColor=PRIMARY,
            fontName="Helvetica-Bold",
        )
        subtitle_style = ParagraphStyle(
            "SubtitleDE",
            parent=styles["Normal"],
            fontSize=10,
            leading=13,
            alignment=TA_CENTER,
            spaceAfter=6,
            textColor=TEXT_DARK,
            fontName="Helvetica",
        )
        header_info_style = ParagraphStyle(
            "HeaderInfo",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            alignment=TA_LEFT,
            fontName="Helvetica",
        )
        header_info_right = ParagraphStyle(
            "HeaderInfoRight",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            alignment=TA_RIGHT,
            fontName="Helvetica",
        )
        cell_style = ParagraphStyle(
            "Cell",
            parent=styles["Normal"],
            fontSize=7.5,
            leading=9.5,
            fontName="Helvetica",
        )
        cell_style_bold = ParagraphStyle(
            "CellBold",
            parent=styles["Normal"],
            fontSize=7.5,
            leading=9.5,
            fontName="Helvetica-Bold",
            textColor=colors.white,
            alignment=TA_CENTER,
        )

        seitenmass = landscape(A4) if quer else A4
        nutzbreite = 269 * mm if quer else 182 * mm
        fuss_text = _mehrzeilig(auftrag.fusszeile)
        kopf_text = (auftrag.kopfzeile or "").strip()
        try:
            if fuss_text:
                fuss_text = fuss_text.format(**tokens)
        except (KeyError, ValueError, IndexError):
            pass
        try:
            if kopf_text:
                kopf_text = kopf_text.format(**tokens)
        except (KeyError, ValueError, IndexError):
            pass
        fuss_html = html.escape(fuss_text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")
        kopf_html = html.escape(kopf_text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")
        fuss_style = ParagraphStyle(
            "FooterDE",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
            textColor=TEXT_DARK,
            fontName="Helvetica",
        )
        kopf_style = ParagraphStyle(
            "HeaderDE",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            alignment=TA_LEFT,
            textColor=TEXT_DARK,
            fontName="Helvetica",
        )
        kopf_h = 0
        kopf_para = None
        if kopf_text:
            kopf_para = Paragraph(kopf_html, kopf_style)
            _w, kopf_h = kopf_para.wrap(nutzbreite, 24 * mm)
        fuss_h = 0
        fuss_para = None
        if fuss_text:
            fuss_para = Paragraph(fuss_html, fuss_style)
            _w, fuss_h = fuss_para.wrap(nutzbreite, 60 * mm)
        # Der untere Rand richtet sich nach der tatsächlichen Höhe der Fußzeile:
        # Auch mehrzeilige Fußzeilen überdecken nie die Tabelle.
        unten = max(24 * mm, 10 * mm + fuss_h + 2.2 * mm + 4 * mm) if fuss_text else 14 * mm
        oben = 12 * mm + (kopf_h + 4 * mm if kopf_text else 0)
        doc = SimpleDocTemplate(
            str(ausgabe_pdf),
            pagesize=seitenmass,
            leftMargin=14 * mm,
            rightMargin=14 * mm,
            topMargin=oben,
            bottomMargin=unten,
        )
        story = []

        logo_w = logo_mm * mm
        logo_h = logo_w * (h_px / float(w_px))
        logo = Image(logo_path, width=logo_w, height=logo_h)
        logo.hAlign = "CENTER"
        story.append(logo)
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(auftrag.titel, title_style))
        story.append(Paragraph(auftrag.untertitel, subtitle_style))
        story.append(HRFlowable(width="100%", thickness=1.8, color=PRIMARY, spaceAfter=6))

        left_lines = []
        if firmenname:
            left_lines.append(Paragraph(f"<b>Firmenname:</b> {firmenname}", header_info_style))
        left_lines.append(Paragraph(f"<b>Kundennummer:</b> {kundennummer}", header_info_style))
        left_lines.append(
            Paragraph(f"<b>Rechnungsempfänger:</b> {rechnungsempfaenger}", header_info_style)
        )
        right_lines = [
            Paragraph(f"<b>Erstellt am:</b> {jetzt.strftime('%d.%m.%Y')}", header_info_right),
            Paragraph("&nbsp;", header_info_right),
        ]
        while len(right_lines) < len(left_lines):
            right_lines.append(Paragraph("&nbsp;", header_info_right))
        info_data = [[l, r] for l, r in zip(left_lines, right_lines)]
        links_b = 150 * mm if quer else 95 * mm
        info_table = Table(info_data, colWidths=[links_b, nutzbreite - links_b])
        info_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )
        story.append(info_table)
        story.append(Spacer(1, 4 * mm))

        header = [
            Paragraph("<b>Art</b>", cell_style_bold),
            Paragraph("<b>Vertrag-Nr.</b>", cell_style_bold),
            Paragraph("<b>Beschreibung</b>", cell_style_bold),
            Paragraph("<b>Beginn</b>", cell_style_bold),
            Paragraph("<b>Abrechnungszyklus</b>", cell_style_bold),
            Paragraph("<b>Netto €</b>", cell_style_bold),
            Paragraph("<b>Zahlungsart</b>", cell_style_bold),
        ]
        table_data = [header]
        for _, row in df.iterrows():
            table_data.append(
                [
                    Paragraph(vertrag_art(row[col_bemerkung]), cell_style),
                    Paragraph(str(row[col_vertrag]), cell_style),
                    Paragraph(clean_bemerkung(row[col_bemerkung]), cell_style),
                    Paragraph(fmt_date(row[col_beginn]), cell_style),
                    Paragraph(fmt_zyklus(row[col_zyklus], row[col_bemerkung], zyklus_regeln), cell_style),
                    Paragraph(fmt_euro(row[col_netto]), cell_style),
                    Paragraph(fmt_zahlungsart(row[col_zahlung]), cell_style),
                ]
            )

        if quer:
            col_widths = [42 * mm, 34 * mm, 76 * mm, 24 * mm, 53 * mm, 20 * mm, 20 * mm]
        else:
            col_widths = [28 * mm, 26 * mm, 42 * mm, 18 * mm, 34 * mm, 16 * mm, 18 * mm]
        tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 7.5),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.4, GRID),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.8),
                    ("ALIGN", (3, 1), (3, -1), "CENTER"),
                    ("ALIGN", (5, 1), (5, -1), "RIGHT"),
                    ("ALIGN", (6, 1), (6, -1), "CENTER"),
                ]
            )
        )
        story.append(tbl)

        def _seite(canvas, _doc) -> None:
            if kopf_para is not None:
                canvas.saveState()
                y = _doc.pagesize[1] - 8 * mm - kopf_h
                kopf_para.drawOn(canvas, _doc.leftMargin, y)
                canvas.setStrokeColor(PRIMARY)
                canvas.setLineWidth(0.4)
                canvas.line(_doc.leftMargin, y - 1.4 * mm, _doc.leftMargin + _doc.width, y - 1.4 * mm)
                canvas.restoreState()
            if fuss_para is None:
                return
            canvas.saveState()
            y = 10 * mm
            canvas.setStrokeColor(PRIMARY)
            canvas.setLineWidth(0.5)
            canvas.line(_doc.leftMargin, y + fuss_h + 2.2 * mm, _doc.leftMargin + _doc.width, y + fuss_h + 2.2 * mm)
            fuss_para.drawOn(canvas, _doc.leftMargin, y)
            canvas.restoreState()

        doc.build(story, onFirstPage=_seite, onLaterPages=_seite, canvasmaker=_NummernCanvas)
    finally:
        if os.path.exists(logo_path):
            os.remove(logo_path)

    _status(auftrag, f"PDF gespeichert: {ausgabe_pdf}")
    if auftrag.pdf_oeffnen:
        try:
            if hasattr(os, "startfile"):
                os.startfile(ausgabe_pdf)  # type: ignore[attr-defined]
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(ausgabe_pdf)])
        except OSError:
            pass
    return ausgabe_pdf
