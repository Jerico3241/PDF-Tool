"""PDF-Engine für die Vertragsübersicht – gleiche Regeln wie das Originalskript.

pandas liest Werte und Spalten der Excel-Liste. Die Formatierung (Fettschrift)
liefert die Schicht ``excelstyle``, formatierte Kopf- und Fußzeilen das Modell
``richtext`` mit den Schriften aus ``pdffonts``.
"""

from __future__ import annotations

import errno
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from excelstyle import SOURCE_ROW, ExcelStyles, cell_key, read_styles
from richtext import (
    FOOTER_ALIGN,
    FOOTER_STYLE,
    HEADER_ALIGN,
    HEADER_STYLE,
    LINE_FACTOR,
    RichText,
    escape_markup,
    paragraph_markup,
    paragraph_size,
)

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

# Spaltenüberschriften (flexible Erkennung: Groß-/Kleinschreibung und Sonderzeichen egal)
SPALTE_VERTRAG = ("Vertrag-Nr.", "VertragNr", "Vertragsnummer")
SPALTE_BEGINN = ("Beginnt am", "Beginn", "Startdatum")
SPALTE_ZYKLUS = ("Abrechnungszyklus",)
SPALTE_NETTO = ("Netto [€]", "Netto", "Netto €", "Netto EUR")
SPALTE_ZAHLUNG = ("Zahlungsart",)
SPALTE_BEMERKUNG = ("Bemerkung", "Beschreibung")
SPALTE_MAIL = ("Rechnungsempfänger Email", "Rechnungsempfaenger Email")
SPALTE_KUNDE = ("Kundennummer", "Kd-Nr.", "KdNr")
SPALTE_FIRMA = ("Firmenname", "Firma", "Kunde")
SPALTE_STATUS = ("Anwenderstatus", "Status")
# Für die PDF zusätzlich zur Vertragsnummer erforderlich (Anzeigename, Varianten)
PDF_SPALTEN = (
    ("Beginnt am", SPALTE_BEGINN),
    ("Abrechnungszyklus", SPALTE_ZYKLUS),
    ("Netto [€]", SPALTE_NETTO),
    ("Zahlungsart", SPALTE_ZAHLUNG),
    ("Bemerkung", SPALTE_BEMERKUNG),
)
KOPF_SUCHE_ZEILEN = 30  # so weit wird nach der Überschriftenzeile gesucht, falls sie nicht in Zeile 1 steht


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


def _betrag(text: str) -> float | None:
    """Betrag aus Text wie »1.234,50 €« oder »49.90«."""
    cleaned = re.sub(r"[^\d,.\-]", "", text)
    if not re.search(r"\d", cleaned):
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def fmt_euro(v) -> str:
    if pd.isna(v):
        return "–"
    if isinstance(v, str):
        zahl = _betrag(v)
        if zahl is None:
            return v.strip() or "–"
        v = zahl
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(v)


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


def _schluessel(name) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _col(df: pd.DataFrame, *namen: str, required: bool = True) -> str:
    wanted = {_schluessel(n) for n in namen}
    for col in df.columns:
        if _schluessel(col) in wanted:
            return str(col)
    if required:
        raise ValueError(
            "In der Excel fehlt die Spalte "
            + " / ".join(namen)
            + ".\nGefundene Spalten: "
            + ", ".join(str(c) for c in df.columns if str(c) != SOURCE_ROW)
        )
    return ""


class Abgebrochen(Exception):
    """Die Erstellung wurde auf Wunsch abgebrochen – es bleibt keine (halbe) PDF zurück."""

    def __init__(self) -> None:
        super().__init__("Die Erstellung wurde abgebrochen.")


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
    # Formatierung (richtext.RichText.to_dict()); ohne passende Angabe gilt das Standardformat
    fusszeile_format: dict | None = None
    kopfzeile_format: dict | None = None
    regeln: list | None = None
    pdf_oeffnen: bool = False
    status: Callable[[str], None] | None = None
    # Genaue Ausgabedatei (statt Zielordner + Dateiname), z. B. nach einer Namenskonflikt-Prüfung
    ausgabe: Path | None = None
    # False: eine vorhandene Datei nie ersetzen (FileExistsError) – True wie bisher: ersetzen
    ueberschreiben: bool = True
    # Wird an festen Stellen gefragt; True bricht ab (Abgebrochen), bevor die PDF entsteht
    abbrechen: Callable[[], bool] | None = None


DEFAULT_DATEINAME = "Vertragsuebersicht_Kd{kd}.pdf"
_UNGUELTIG_IM_NAMEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def platzhalter(kundennummer: str, firmenname: str = "", jetzt: datetime | None = None) -> dict[str, str]:
    """Werte der Platzhalter {kd}, {kundennummer}, {kunde}, {firma}, {datum}, {datumkurz} im Dateinamen."""
    jetzt = jetzt or datetime.now()
    kundennummer = str(kundennummer or "").strip()
    name = re.sub(r"[^\w\-]+", "_", str(firmenname or "").strip(), flags=re.UNICODE).strip("_") or kundennummer
    return {
        "kd": kundennummer,
        "kundennummer": kundennummer,
        "datum": jetzt.strftime("%Y-%m-%d"),
        "datumkurz": jetzt.strftime("%d.%m.%Y"),
        "kunde": name,
        "firma": name,
    }


def dateiname_fuer(muster: str, kundennummer: str, firmenname: str = "", jetzt: datetime | None = None) -> str:
    """Dateiname der PDF aus dem Muster – dieselbe Regel für Einzel- und Stapelerstellung.

    Zeichen, die Windows in Dateinamen nicht erlaubt (z. B. »/« in einer Kundennummer),
    werden durch »_« ersetzt, damit nie ein unbeabsichtigter Unterordner entsteht.
    """
    muster = str(muster or "").strip() or DEFAULT_DATEINAME
    if not muster.lower().endswith(".pdf"):
        muster += ".pdf"
    kundennummer = str(kundennummer or "").strip()
    name = muster.format(**platzhalter(kundennummer, firmenname, jetzt))
    if "{kd}" not in muster and "{kundennummer}" not in muster:
        # Muster mit fest eingetragener Nummer (z. B. »…_Kd10042.pdf«): aktuelle Kundennummer einsetzen
        name = re.sub(r"(?i)(?<=Kd)\d+", lambda _treffer: kundennummer, name)
    return _UNGUELTIG_IM_NAMEN.sub("_", name)


def zielordner_fuer(auftrag: "PdfAuftrag") -> Path:
    ordner = Path(auftrag.zielordner) if auftrag.zielordner else Path(auftrag.excel).parent
    if ordner.suffix.lower() == ".pdf":
        ordner = ordner.parent
    return ordner


def ausgabe_pfad(auftrag: "PdfAuftrag", jetzt: datetime | None = None) -> Path:
    """Die Datei, die ``erstelle_pdf`` für diesen Auftrag schreibt (ohne Ordner anzulegen)."""
    if auftrag.ausgabe:
        return Path(auftrag.ausgabe)
    return zielordner_fuer(auftrag) / dateiname_fuer(auftrag.dateiname, auftrag.kundennummer, auftrag.firmenname, jetzt)


def _pruefe_abbruch(auftrag: "PdfAuftrag") -> None:
    if auftrag.abbrechen is not None and auftrag.abbrechen():
        raise Abgebrochen()


def _veroeffentlichen(temp: Path, ziel: Path, ueberschreiben: bool) -> None:
    """Fertige PDF an ihren Platz bringen – in einem Schritt, nie als halbe Datei.

    ``ueberschreiben=False`` ersetzt eine vorhandene Datei nie (FileExistsError), auch
    wenn sie erst während der Erstellung entstanden ist.
    """
    try:
        if ueberschreiben:
            os.replace(temp, ziel)
        elif os.name == "nt":
            os.rename(temp, ziel)  # Windows: schlägt fehl, wenn das Ziel existiert
        else:
            try:
                os.link(temp, ziel)  # schlägt fehl, wenn das Ziel existiert
            except FileExistsError:
                raise
            except OSError:
                # Dateisystem ohne feste Verknüpfungen: prüfen und umbenennen
                if ziel.exists():
                    raise FileExistsError(errno.EEXIST, "Datei existiert bereits", str(ziel)) from None
                os.rename(temp, ziel)
            else:
                os.unlink(temp)
    except FileExistsError:
        raise
    except PermissionError as exc:
        raise PermissionError(f"Die PDF-Datei ist geöffnet oder schreibgeschützt und kann nicht ersetzt werden:\n{ziel}") from exc


def _zelltext(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


# ---------------------------------------------------------------------------
# Excel lesen: Werte (pandas) mit ursprünglicher Zeilennummer
# ---------------------------------------------------------------------------


@dataclass
class ExcelTabelle:
    """Die Excel-Liste als DataFrame; jede Zeile kennt ihre Excel-Zeile (``_source_excel_row``)."""

    pfad: Path
    df: "pd.DataFrame"
    kopfzeile: int  # Excel-Zeile der Spaltenüberschriften (1-basiert)

    def excel_spalte(self, name: str) -> int | None:
        """Excel-Spaltennummer (1-basiert) einer erkannten Spalte – unabhängig von festen Buchstaben."""
        if not name or name not in self.df.columns:
            return None
        return int(self.df.columns.get_loc(name)) + 1


def _finde_kopfzeile(pfad: Path) -> int | None:
    """Überschriftenzeile suchen, falls sie nicht in der ersten Zeile steht (0-basiert)."""
    roh = pd.read_excel(pfad, header=None, nrows=KOPF_SUCHE_ZEILEN)
    gesucht = {_schluessel(name) for name in SPALTE_VERTRAG}
    for index in range(len(roh)):
        if any(isinstance(wert, str) and _schluessel(wert) in gesucht for wert in roh.iloc[index].tolist()):
            return index
    return None


def lies_tabelle(pfad: Path) -> ExcelTabelle:
    """Liest das erste Tabellenblatt. pandas behält Leerzeilen (``skip_blank_lines=False``):
    DataFrame-Zeile i entspricht damit der Excel-Zeile ``Überschrift + 1 + i``."""
    _lade_pandas()
    pfad = Path(pfad)
    df = pd.read_excel(pfad)
    kopf = 1
    if not _col(df, *SPALTE_VERTRAG, required=False):
        gefunden = _finde_kopfzeile(pfad)
        if gefunden is not None and gefunden > 0:
            df = pd.read_excel(pfad, header=gefunden)
            kopf = gefunden + 1
    df[SOURCE_ROW] = range(kopf + 1, kopf + 1 + len(df))
    return ExcelTabelle(pfad, df, kopf)


def excel_stile(tabelle: ExcelTabelle, daten: "pd.DataFrame", spalten: list[str], col_vertrag: str) -> ExcelStyles:
    """Formatierung der Zellen ``spalten`` für alle Zeilen in ``daten`` (einmal lesen, dann zuordnen).

    Die Vertragsnummern dienen als Probe: Nur wenn jede Zeile an der erwarteten
    Excel-Position ihre Vertragsnummer findet, werden Stile übernommen.
    """
    vertrag = tabelle.excel_spalte(col_vertrag)
    rows = [int(row) for row in daten[SOURCE_ROW].tolist()]
    cols = [tabelle.excel_spalte(name) for name in spalten if name]
    expected = {(int(row), vertrag): cell_key(wert) for row, wert in zip(daten[SOURCE_ROW].tolist(), daten[col_vertrag].tolist())}
    return read_styles(tabelle.pfad, rows, [c for c in cols if c] + [vertrag], expected)


def nur_aktive(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Nur Zeilen mit Anwenderstatus Aktiv. Fehlt die Spalte, bleibt die Liste unverändert."""
    col = _col(df, *SPALTE_STATUS, required=False)
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


def _lesefehler(exc: BaseException) -> str:
    if isinstance(exc, ValueError) and "fehlt die Spalte" in str(exc):
        return str(exc)
    if isinstance(exc, PermissionError):
        return "Die Datei ist gesperrt oder es fehlt die Berechtigung zum Lesen."
    text = str(exc).strip() or exc.__class__.__name__
    return f"Die Datei konnte nicht als Excel-Liste gelesen werden ({text})."


def pruefe_excel(pfad: Path, regeln=None) -> dict:
    """Liest die Liste nur zur Kontrolle, ohne ein PDF zu schreiben.

    Ergebnis: ``aktiv``/``inaktiv`` (Anzahl), ``mails``, ``kunden`` und ``firmen``
    (nur Werte, die tatsächlich in der Datei stehen), ``fehlend`` (für die PDF
    benötigte Spalten, die fehlen), ``hinweise``, ``fett`` (fett formatierte
    Zellen, die übernommen werden) und ``zeilen`` (Vorschau).
    """
    _lade_pandas()
    leer = {"ok": False, "text": "", "kunden": [], "mails": [], "firmen": [], "zeilen": [], "aktiv": 0, "inaktiv": 0, "fehlend": [], "hinweise": [], "fett": 0}
    pfad = Path(pfad)
    if not pfad.is_file():
        return {**leer, "text": "Datei nicht gefunden."}
    try:
        tabelle = lies_tabelle(pfad)
        df = tabelle.df
        col_vertrag = _col(df, *SPALTE_VERTRAG)
    except Exception as exc:  # noqa: BLE001 - jede Lesestörung wird verständlich gemeldet
        return {**leer, "text": _lesefehler(exc)}
    daten = df.dropna(subset=[col_vertrag]).copy()
    daten, ausgeblendet = nur_aktive(daten)
    col_beginn = _col(df, *SPALTE_BEGINN, required=False)
    if col_beginn:
        daten["_sort"] = pd.to_datetime(daten[col_beginn], errors="coerce")
        daten = daten.sort_values("_sort", kind="stable")
    anzahl = int(len(daten))
    col_kunde = _col(df, *SPALTE_KUNDE, required=False)
    col_mail = _col(df, *SPALTE_MAIL, required=False)
    col_firma = _col(df, *SPALTE_FIRMA, required=False)
    kunden = _eindeutig(daten, col_kunde)
    mails = _eindeutig(daten, col_mail)
    firmen = _eindeutig(daten, col_firma)
    col_bem = _col(df, *SPALTE_BEMERKUNG, required=False)
    col_zyk = _col(df, *SPALTE_ZYKLUS, required=False)
    col_netto = _col(df, *SPALTE_NETTO, required=False)
    col_zahlung = _col(df, *SPALTE_ZAHLUNG, required=False)
    fehlend = [anzeige for anzeige, namen in PDF_SPALTEN if not _col(df, *namen, required=False)]
    hinweise: list[str] = []
    if not _col(df, *SPALTE_STATUS, required=False):
        hinweise.append("Keine Spalte »Anwenderstatus«: Alle Verträge gelten als aktiv.")
    if not col_mail:
        hinweise.append("Keine Spalte »Rechnungsempfänger Email«: Empfänger bitte selbst eintragen.")
    fett = 0
    if anzahl:
        stile = excel_stile(tabelle, daten, [col_vertrag, col_bem, col_beginn, col_zyk, col_netto, col_zahlung], col_vertrag)
        spalten = [tabelle.excel_spalte(name) for name in (col_vertrag, col_bem, col_beginn, col_zyk, col_netto, col_zahlung) if name]
        fett = sum(1 for row in daten[SOURCE_ROW].tolist() for col in spalten if stile.bold(row, col))
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
    return {
        "ok": True,
        "text": text,
        "kunden": kunden,
        "mails": mails,
        "firmen": firmen,
        "zeilen": zeilen,
        "aktiv": anzahl,
        "inaktiv": int(ausgeblendet),
        "fehlend": fehlend,
        "hinweise": hinweise,
        "fett": fett,
        "kopfzeile": tabelle.kopfzeile,
    }


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _status(auftrag: PdfAuftrag, text: str) -> None:
    if auftrag.status:
        auftrag.status(text)


def _rich_text(text: str, fmt, style, align, werte: dict[str, str], trim_start: bool = False) -> RichText | None:
    """Kopf- bzw. Fußzeile als formatierter Text mit eingesetzten Platzhaltern (``None``, wenn leer)."""
    rich = RichText.from_storage(text or "", fmt, style, align).stripped()
    if trim_start:
        # wie bisher bei der Kopfzeile: führende Leerzeilen und Leerzeichen entfallen
        skip = len(rich.text) - len(rich.text.lstrip())
        if skip:
            rest = rich.text[skip:]
            first_paragraph = rich.text[:skip].count("\n")
            rich = RichText(rest, rich.styles[skip:], rich.aligns[first_paragraph:], rich.default, rich.align)
    if rich.is_blank():
        return None
    return rich.with_placeholders(werte)


def _rich_absaetze(rich: RichText, breite: float, name: str) -> list[tuple[object, float]]:
    """Ein ReportLab-Absatz je Textabsatz (eigene Ausrichtung), Leerzeilen als Abstand."""
    from pdffonts import pdf_font

    ausrichtung = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}
    teile: list[tuple[object, float]] = []
    for index, (start, end, align) in enumerate(rich.paragraphs()):
        groesse = paragraph_size(rich, start, end)
        zeile = groesse * LINE_FACTOR
        if start == end:
            teile.append((Spacer(breite, zeile), zeile))
            continue
        basis = rich.style_at(start)
        stil = ParagraphStyle(
            f"{name}{index}",
            fontName=pdf_font(basis.font, basis.bold, basis.italic),
            fontSize=groesse,
            leading=zeile,
            alignment=ausrichtung.get(align, TA_LEFT),
            textColor=colors.HexColor(basis.color),
            spaceBefore=0,
            spaceAfter=0,
        )
        absatz = Paragraph(paragraph_markup(rich, start, end, pdf_font), stil)
        _w, hoehe = absatz.wrap(breite, 100000)
        teile.append((absatz, hoehe))
    return teile


def _zeichne_block(canvas, teile: list[tuple[object, float]], x: float, oben: float) -> None:
    y = oben
    for flowable, hoehe in teile:
        y -= hoehe
        flowable.drawOn(canvas, x, y)


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

    _pruefe_abbruch(auftrag)
    _status(auftrag, "Excel wird gelesen …")
    tabelle = lies_tabelle(excel)
    df = tabelle.df
    col_vertrag = _col(df, *SPALTE_VERTRAG)
    col_beginn = _col(df, *SPALTE_BEGINN)
    col_zyklus = _col(df, *SPALTE_ZYKLUS)
    col_netto = _col(df, *SPALTE_NETTO)
    col_zahlung = _col(df, *SPALTE_ZAHLUNG)
    col_bemerkung = _col(df, *SPALTE_BEMERKUNG)
    col_mail = _col(df, *SPALTE_MAIL, required=False)

    # Filtern und Sortieren ändern die Werte in _source_excel_row nicht.
    df = df.dropna(subset=[col_vertrag]).copy()
    df, _ausgeblendet = nur_aktive(df)
    if df.empty:
        raise ValueError("Die Excel enthält keine aktiven Verträge.")
    df[col_beginn] = pd.to_datetime(df[col_beginn], errors="coerce")
    df = df.sort_values(col_beginn, kind="stable").reset_index(drop=True)

    _pruefe_abbruch(auftrag)
    _status(auftrag, "Formatierung wird gelesen …")
    stile = excel_stile(tabelle, df, [col_vertrag, col_bemerkung, col_beginn, col_zyklus, col_netto, col_zahlung], col_vertrag)
    excel_spalte = {name: tabelle.excel_spalte(name) for name in (col_vertrag, col_bemerkung, col_beginn, col_zyklus, col_netto, col_zahlung)}

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
    # In Kopf- und Fußzeile erscheint der Firmenname wie eingetragen (nicht dateinamentauglich umgeschrieben).
    text_werte = {**platzhalter(kundennummer, firmenname, jetzt), "kunde": firmenname or kundennummer, "firma": firmenname or kundennummer}
    ausgabe_pdf = ausgabe_pfad(auftrag, jetzt)
    ordner = ausgabe_pdf.parent
    ordner.mkdir(parents=True, exist_ok=True)
    if not auftrag.ueberschreiben and ausgabe_pdf.exists():
        raise FileExistsError(errno.EEXIST, "Datei existiert bereits", str(ausgabe_pdf))

    _pruefe_abbruch(auftrag)
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
    temp_pdf: Path | None = None

    try:
        prepared.save(logo_path, "PNG")
        # Die PDF entsteht zuerst als temporäre Datei im Zielordner und wird erst fertig an ihren
        # Platz gebracht: Ein Fehler oder Abbruch hinterlässt nie eine halbe PDF.
        handle, temp_name = tempfile.mkstemp(prefix="~pdf-tool-", suffix=".tmp", dir=str(ordner))
        os.close(handle)
        temp_pdf = Path(temp_name)
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
        # Fett aus der Excel: gleicher Stil, nur das Schriftgewicht ändert sich.
        cell_style_strong = ParagraphStyle("CellStrong", parent=cell_style, fontName="Helvetica-Bold")
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
        kopf_rich = _rich_text(auftrag.kopfzeile, auftrag.kopfzeile_format, HEADER_STYLE, HEADER_ALIGN, text_werte, trim_start=True)
        fuss_rich = _rich_text(auftrag.fusszeile, auftrag.fusszeile_format, FOOTER_STYLE, FOOTER_ALIGN, text_werte)
        kopf_teile = _rich_absaetze(kopf_rich, nutzbreite, "HeaderDE") if kopf_rich else []
        fuss_teile = _rich_absaetze(fuss_rich, nutzbreite, "FooterDE") if fuss_rich else []
        kopf_h = sum(hoehe for _teil, hoehe in kopf_teile)
        fuss_h = sum(hoehe for _teil, hoehe in fuss_teile)
        # Ränder richten sich nach der tatsächlichen Höhe von Kopf- und Fußzeile:
        # Auch mehrzeilige oder große Schrift überdeckt nie die Tabelle.
        unten = max(24 * mm, 10 * mm + fuss_h + 2.2 * mm + 4 * mm) if fuss_teile else 14 * mm
        oben = 12 * mm + (kopf_h + 4 * mm if kopf_teile else 0)
        if seitenmass[1] - oben - unten < 60 * mm:
            raise ValueError("Kopf- und Fußzeile sind zusammen zu hoch für die Seite. Bitte den Text kürzen oder eine kleinere Schrift wählen.")
        doc = SimpleDocTemplate(
            str(temp_pdf),
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
        story.append(Paragraph(escape_markup(auftrag.titel), title_style))
        story.append(Paragraph(escape_markup(auftrag.untertitel), subtitle_style))
        story.append(HRFlowable(width="100%", thickness=1.8, color=PRIMARY, spaceAfter=6))

        left_lines = []
        if firmenname:
            left_lines.append(Paragraph(f"<b>Firmenname:</b> {escape_markup(firmenname)}", header_info_style))
        left_lines.append(Paragraph(f"<b>Kundennummer:</b> {escape_markup(kundennummer)}", header_info_style))
        left_lines.append(
            Paragraph(f"<b>Rechnungsempfänger:</b> {escape_markup(rechnungsempfaenger)}", header_info_style)
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
            quelle = row[SOURCE_ROW]

            def zelle(markup: str, spalte: str) -> object:
                # Zellweise: fett nur, wenn genau diese Excel-Zelle fett ist.
                fett = stile.bold(quelle, excel_spalte.get(spalte))
                return Paragraph(markup, cell_style_strong if fett else cell_style)

            bemerkung = row[col_bemerkung]
            table_data.append(
                [
                    # Art wird aus der Bemerkung abgeleitet und übernimmt deren Formatierung.
                    zelle(vertrag_art(bemerkung), col_bemerkung),
                    zelle(escape_markup(_zelltext(row[col_vertrag])), col_vertrag),
                    zelle(escape_markup(clean_bemerkung(bemerkung)), col_bemerkung),
                    zelle(fmt_date(row[col_beginn]), col_beginn),
                    zelle(escape_markup(fmt_zyklus(row[col_zyklus], bemerkung, zyklus_regeln)), col_zyklus),
                    zelle(escape_markup(fmt_euro(row[col_netto])), col_netto),
                    zelle(escape_markup(fmt_zahlungsart(row[col_zahlung])), col_zahlung),
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
            _pruefe_abbruch(auftrag)
            if kopf_teile:
                canvas.saveState()
                oben_kopf = _doc.pagesize[1] - 8 * mm
                _zeichne_block(canvas, kopf_teile, _doc.leftMargin, oben_kopf)
                y = oben_kopf - kopf_h
                canvas.setStrokeColor(PRIMARY)
                canvas.setLineWidth(0.4)
                canvas.line(_doc.leftMargin, y - 1.4 * mm, _doc.leftMargin + _doc.width, y - 1.4 * mm)
                canvas.restoreState()
            if not fuss_teile:
                return
            canvas.saveState()
            y = 10 * mm
            canvas.setStrokeColor(PRIMARY)
            canvas.setLineWidth(0.5)
            canvas.line(_doc.leftMargin, y + fuss_h + 2.2 * mm, _doc.leftMargin + _doc.width, y + fuss_h + 2.2 * mm)
            _zeichne_block(canvas, fuss_teile, _doc.leftMargin, y + fuss_h)
            canvas.restoreState()

        _pruefe_abbruch(auftrag)
        doc.build(story, onFirstPage=_seite, onLaterPages=_seite, canvasmaker=_NummernCanvas)
        _pruefe_abbruch(auftrag)
        _veroeffentlichen(temp_pdf, ausgabe_pdf, auftrag.ueberschreiben)
    finally:
        if os.path.exists(logo_path):
            os.remove(logo_path)
        if temp_pdf is not None and temp_pdf.exists():
            try:
                temp_pdf.unlink()
            except OSError:
                pass

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
