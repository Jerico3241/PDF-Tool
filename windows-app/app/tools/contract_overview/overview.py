"""Gemeinsame Fachlogik von Einzel- und Stapelerstellung in »Vertragsübersichten«.

Beide Arbeitsweisen verwenden genau diese Bausteine – es gibt keine zweite Prüf-,
Validierungs- oder PDF-Logik für den Stapel:

* ``ExcelAnalysis`` – Ergebnis der Excel-Prüfung (``engine.pruefe_excel``) als Datentyp
* ``contract_summary`` – »5 aktive Verträge · 3 inaktiv ausgeblendet« (Einzahl/Mehrzahl)
* ``excel_issues`` / ``output_issues`` – was vor dem Erstellen noch fehlt
* ``pdf_fields`` – der Auftrag für ``engine.erstelle_pdf`` (PDF, Vorschau und Stapel)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from appstate import DEFAULT_TITEL, DEFAULT_UNTERTITEL
from richtext import RichText

EXCEL_SUFFIXES = (".xlsx", ".xlsm", ".xls")


@dataclass(frozen=True)
class ExcelAnalysis:
    """Was die Excel-Prüfung ergeben hat – nur Werte, die tatsächlich in der Datei stehen."""

    ok: bool
    error: str = ""
    active: int = 0
    inactive: int = 0
    emails: tuple[str, ...] = ()
    numbers: tuple[str, ...] = ()
    companies: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()
    bold: int = 0

    @classmethod
    def from_result(cls, result: dict | None) -> "ExcelAnalysis | None":
        """Aus dem Ergebnis von ``engine.pruefe_excel`` (``None`` bleibt ``None``)."""
        if result is None:
            return None

        def texts(key: str) -> tuple[str, ...]:
            return tuple(str(value) for value in result.get(key) or [])

        ok = bool(result.get("ok"))
        return cls(
            ok=ok,
            error="" if ok else str(result.get("text") or "Die Datei konnte nicht gelesen werden."),
            active=int(result.get("aktiv", 0) or 0),
            inactive=int(result.get("inaktiv", 0) or 0),
            emails=texts("mails"),
            numbers=texts("kunden"),
            companies=texts("firmen"),
            missing=texts("fehlend"),
            hints=texts("hinweise"),
            bold=int(result.get("fett", 0) or 0),
        )

    @property
    def usable(self) -> bool:
        """Lässt sich daraus eine PDF erstellen (gelesen, alle Spalten, aktive Verträge)?"""
        return self.ok and not self.missing and self.active > 0


def contract_summary(active: int, inactive: int = 0, short: bool = False) -> str:
    """»5 aktive Verträge · 3 inaktiv ausgeblendet«, »1 aktiver Vertrag« – ohne »0 inaktiv«.

    ``short``: kompakte Form für Listen, z. B. »5 aktive · 3 inaktiv ausgeblendet«.
    """
    if short:
        text = f"{active} aktiver" if active == 1 else f"{active} aktive"
    else:
        text = "1 aktiver Vertrag" if active == 1 else f"{active} aktive Verträge"
    if inactive:
        text += f" · {inactive} inaktiv ausgeblendet"
    return text


@dataclass(frozen=True)
class Issue:
    """Ein offener Punkt vor dem Erstellen. ``code`` ist stabil, ``text`` für die Anzeige."""

    area: str  # Bereich im Formular: excel, busy, kd, firma, mail, kunde, logo, breite, ziel, vorlage
    code: str
    text: str


# Offene Punkte, die in der Datei selbst liegen – Eingaben im Formular beheben sie nicht.
FILE_CODES = frozenset({"excel_missing", "file_missing", "unreadable", "columns_missing", "no_active"})


def excel_issues(excel: str, analysis: ExcelAnalysis | None) -> list[Issue]:
    """Ist die Excel-Datei vorhanden, geprüft und für eine PDF geeignet?"""
    if not excel:
        return [Issue("excel", "excel_missing", "Excel-Datei fehlt")]
    if not Path(excel).is_file():
        return [Issue("excel", "file_missing", "Excel-Datei nicht gefunden")]
    if analysis is None:
        return [Issue("busy", "pending", "Excel wird geprüft …")]
    if not analysis.ok:
        return [Issue("excel", "unreadable", "Excel-Datei konnte nicht gelesen werden")]
    if analysis.missing:
        missing = analysis.missing
        text = f"Spalte »{missing[0]}« fehlt in der Excel" if len(missing) == 1 else f"{len(missing)} Spalten fehlen in der Excel"
        return [Issue("excel", "columns_missing", text)]
    if not analysis.active:
        return [Issue("excel", "no_active", "Keine aktiven Verträge in der Excel")]
    return []


def output_issues(kd: str, emails: tuple[str, ...] | list[str], mail: str, logo: str, breite: str, target: str) -> list[Issue]:
    """Angaben für die PDF: Kundennummer, Empfängerwahl, Logo, Logo-Breite und Zielordner."""
    issues: list[Issue] = []
    if not str(kd).strip():
        issues.append(Issue("kd", "number_missing", "Kundennummer fehlt"))
    if len(emails) > 1 and not str(mail).strip():
        issues.append(Issue("mail", "mail_choice", "Bitte Rechnungsempfänger auswählen"))
    logo = str(logo).strip()
    if not logo:
        issues.append(Issue("logo", "logo_missing", "Logo fehlt"))
    elif not Path(logo).is_file():
        issues.append(Issue("logo", "logo_missing", "Logo-Datei nicht gefunden"))
    if not valid_width(breite):
        issues.append(Issue("breite", "width_invalid", "Logo-Breite ungültig"))
    if not target_reachable(target):
        issues.append(Issue("ziel", "target_unreachable", "Zielordner nicht erreichbar"))
    return issues


def pdf_fields(
    *,
    excel: str,
    logo: str,
    kd: str,
    firma: str,
    mail: str,
    dateiname: str,
    seitenformat: str,
    breite: float,
    titel: str,
    untertitel: str,
    header: RichText,
    footer: RichText,
    regeln: list[dict],
) -> dict:
    """Auftrag für ``engine.erstelle_pdf`` (ohne Zielordner) – für PDF, Vorschau und Stapel gleich."""
    return dict(
        excel=Path(excel),
        logo=Path(logo),
        kundennummer=kd,
        firmenname=firma.strip(),
        rechnungsempfaenger=mail,
        dateiname=dateiname.strip(),
        seitenformat=seitenformat if seitenformat in ("hoch", "quer") else "hoch",
        logo_breite=breite,
        titel=titel.strip() or DEFAULT_TITEL,
        untertitel=untertitel.strip() or DEFAULT_UNTERTITEL,
        fusszeile=footer.text,
        fusszeile_format=footer.to_dict(),
        kopfzeile=header.text,
        kopfzeile_format=header.to_dict(),
        regeln=[dict(eintrag) for eintrag in regeln],
    )


def template_layout(entry: dict) -> dict[str, str]:
    """Darstellungswerte einer Vorlage – nur die gesetzten (Logo nur, wenn die Datei existiert).

    Schlüssel wie in der Vorlage: ``logo``, ``format``, ``dateiname``, ``logo_breite``,
    ``titel``, ``untertitel``. Kopf-/Fußzeile: ``appstate.header_rich_from``/``footer_rich_from``,
    Zyklus-Regeln: ``template_rules``.
    """
    values: dict[str, str] = {}
    logo = str(entry.get("logo") or "").strip()
    if logo and Path(logo).is_file():
        values["logo"] = logo
    if entry.get("format") in ("hoch", "quer"):
        values["format"] = str(entry.get("format"))
    for key in ("dateiname", "logo_breite", "titel", "untertitel"):
        if entry.get(key):
            values[key] = str(entry.get(key))
    return values


def template_rules(entry: dict) -> list[dict]:
    """Zyklus-Regeln einer Vorlage (sie ersetzen die aktuellen Regeln – wie beim Laden der Vorlage)."""
    from appstate import normalize_regeln

    return normalize_regeln(entry.get("regeln") or [])


def parse_width(value) -> float | None:
    try:
        width = float(str(value).replace(",", "."))
    except ValueError:
        return None
    return width if 0 < width <= 400 else None


def valid_width(value) -> bool:
    return parse_width(value) is not None


def is_excel(path) -> bool:
    return str(path).lower().endswith(EXCEL_SUFFIXES)


def excel_files(files) -> list[str]:
    return [str(path) for path in files if is_excel(path)]


def target_reachable(path: str) -> bool:
    """Zielordner vorhanden und beschreibbar – oder anlegbar (nächster vorhandener Ordner beschreibbar)."""
    if not str(path).strip():
        return False
    folder = Path(path)
    if folder.is_dir():
        return os.access(folder, os.W_OK)
    if folder.exists():
        return False
    parent = folder.parent
    while not parent.exists() and parent.parent != parent:
        parent = parent.parent
    return parent.is_dir() and os.access(parent, os.W_OK)
