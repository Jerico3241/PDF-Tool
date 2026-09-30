"""Texte und Angaben des Werkzeugs »PDF reparieren« – unabhängig von der Oberfläche.

Aus Analyse und Ergebnis entstehen hier die Zeilen, Hinweise und Beschriftungen, die die
Oberfläche zeigt. Die Entscheidungen fallen anhand der Statusklassen (``Condition``,
``RepairStatus``), nie anhand von Texten. Das technische Protokoll ``pdf-repair.log``
enthält weder PDF-Inhalte noch Passwörter.
"""

from __future__ import annotations

import time
from pathlib import Path

from .models import Condition, Method, PdfAnalysis, PdfRepairResult, RepairStatus

HINT = "Strg+O  PDF auswählen   ·   Strg+Enter  PDF reparieren"
PRIVACY = "Die Verarbeitung erfolgt vollständig lokal auf diesem PC. Keine Datei wird hochgeladen."
LOG_FILE = "pdf-repair.log"
LOG_LIMIT = 1_000_000  # Byte, danach wird das Protokoll einmal rotiert
OUT_ORIGINAL = "original"
OUT_FOLDER = "ordner"
OUT_NAME_EMPTY = "Ausgabe: <Name>_repariert.pdf – die Originaldatei wird nie überschrieben."
HELP_STEPS = (
    "Eine PDF wählen (Strg+O) oder in das Fenster ziehen – sie wird sofort analysiert.",
    "Die Analyse lesen: Keine Fehler, reparierbare Probleme, schwer beschädigt oder erweiterte Wiederherstellung möglich.",
    "Verschlüsselte PDFs erst mit dem richtigen Passwort entsperren.",
    "Auf »PDF reparieren« klicken oder Strg+Enter drücken. Ein laufender Vorgang lässt sich abbrechen.",
    "Das Ergebnis öffnen, den Ordner anzeigen oder den Pfad kopieren.",
)
HELP_NOTES = (
    "Die Originaldatei wird nie verändert. Die reparierte Datei heißt »<Name>_repariert.pdf« (bei Bedarf »_2«, »_3« …).",
    "Nicht jede Datei lässt sich vollständig wiederherstellen; teilweise gerettete Dateien werden deutlich gekennzeichnet.",
    "Öffnet keine PDF-Engine die Datei, sucht PDF Tool die noch vorhandenen PDF-Objekte direkt in der Datei und baut Querverweise, Trailer und Seitenbaum neu auf (»PDF-Struktur rekonstruieren«).",
    "Der Rettungsmodus überträgt lesbare Seiten als Bilder – nur nach Bestätigung, weil Text- und Vektorinformationen verloren gehen.",
    "Passwörter werden nicht gespeichert. Technische Details stehen im Protokoll pdf-repair.log im Datenordner.",
)

CONDITION_TEXT = {
    Condition.HEALTHY: ("success", "Keine Fehler gefunden", "Die PDF scheint strukturell in Ordnung zu sein. Eine Reparatur ist nicht nötig."),
    Condition.REPAIRABLE: ("warning", "Reparierbare Probleme erkannt", "PDF Tool hat beschädigte Strukturen gefunden, die möglicherweise repariert werden können."),
    Condition.DAMAGED: ("warning", "Schwer beschädigt", "Teile der PDF können nicht gelesen werden. PDF Tool versucht, so viele Seiten und Inhalte wie möglich wiederherzustellen."),
    Condition.RAW_RECOVERABLE: (
        "warning",
        "Erweiterte Wiederherstellung möglich",
        "Die Standard-PDF-Engines können die Datei nicht öffnen. Es wurden jedoch noch PDF-Objekte gefunden. PDF Tool versucht, die noch vorhandenen Inhalte wiederherzustellen.",
    ),
    Condition.UNREADABLE: ("error", "Keine Reparatur möglich", "Die Datei lässt sich mit keiner der eingebauten Engines lesen."),
    Condition.ENCRYPTED: ("info", "Die PDF ist verschlüsselt", "Zum Öffnen wird ein Passwort benötigt."),
}
STATUS_TONE = {"success": "success", "warning": "caution", "error": "critical", "info": "", "neutral": ""}
SEVERITY_STATUS = {"success": "success", "warning": "warning", "error": "error"}
REBUILD_METHODS = (Method.RAW_REBUILD, Method.PAGE_TREE_REBUILD)

SIGNATURE_TITLE = "Digital signierte PDF"
SIGNATURE_TEXT = (
    "Die PDF enthält digitale Signaturen. Eine Reparatur kann deren Gültigkeit aufheben.\n\n"
    "Die Originaldatei bleibt unverändert; die Signaturen der reparierten Kopie sind danach möglicherweise ungültig."
)
SIGNATURE_CONFIRM = "Trotzdem reparieren"
RASTER_TITLE = "Lesbare Seiten als Bilder retten?"
RASTER_TEXT = (
    "Im Rettungsmodus werden die lesbaren Seiten als Bilder in eine neue PDF übertragen.\n\n"
    "Text- und Vektorinformationen gehen dabei verloren: Text ist nicht mehr durchsuchbar oder kopierbar, "
    "Links, Formulare und Lesezeichen fehlen. Die Originaldatei bleibt unverändert."
)
RASTER_CONFIRM = "Seiten retten"
RESCUE_TITLE = "Rettungsmodus"
RESCUE_TEXT = "Die lesbaren Seiten können als Bilder in eine neue PDF übertragen werden. Text- und Vektorinformationen können dabei teilweise verloren gehen."
RESCUE_ACTION = "Lesbare Seiten als neue PDF retten"
RESCUE_ACTION_SHORT = "Lesbare Seiten retten"


def crash_text(code) -> str:
    """Meldung, wenn der Arbeitsprozess ohne Ergebnis endet (z. B. Absturz einer PDF-Bibliothek)."""
    return (
        f"Die Verarbeitung wurde unerwartet beendet (Code {code}). Die Datei ist möglicherweise so stark "
        "beschädigt oder so groß, dass die PDF-Engine abgebrochen hat. Es wurde keine Datei gespeichert; "
        "die Originaldatei ist unverändert."
    )


def size_text(size: int | None) -> str:
    if size is None:
        return "–"
    value = float(size)
    for unit in ("Byte", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "Byte":
                return f"{int(value)} Byte"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{size} Byte"


def is_pdf(path: str) -> bool:
    return str(path).lower().endswith(".pdf")


def fact(label: str, value: str, tone: str = "") -> dict:
    """Eine Zeile »Beschriftung · Wert« (Ton: success, caution, critical, muted oder leer)."""
    return {"label": label, "value": value, "tone": tone}


class RepairLog:
    """Technisches Protokoll ``pdf-repair.log`` im Datenordner – ohne PDF-Inhalte und Passwörter."""

    def __init__(self, folder: Path) -> None:
        self.path = folder / LOG_FILE

    def write(self, lines: list[str]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_file() and self.path.stat().st_size > LOG_LIMIT:
                self.path.replace(self.path.with_suffix(".log.1"))
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(self.path, "a", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(f"{stamp}  {line}\n")
        except OSError:
            pass


# Analyse --------------------------------------------------------------------------------------
def condition_text(analysis: PdfAnalysis) -> tuple[str, str, str]:
    """(Schweregrad, Titel, Meldung) für den Zustand einer Analyse."""
    severity, title, message = CONDITION_TEXT[analysis.condition]
    if analysis.condition is Condition.ENCRYPTED and analysis.password_rejected:
        severity, message = "error", "Das Passwort ist falsch. Bitte erneut eingeben."
    elif analysis.condition is Condition.UNREADABLE and analysis.error:
        message = f"{analysis.error} {message}"
    elif analysis.condition is Condition.RAW_RECOVERABLE and analysis.raw is not None and analysis.raw.streams:
        message = message.replace("noch PDF-Objekte gefunden", "noch PDF-Objekte und Datenströme gefunden")
    return severity, title, message


def analysis_facts(analysis: PdfAnalysis) -> list[dict]:
    """Die wichtigsten Angaben der Analyse (Größe, Seiten, Version, Verschlüsselung, Signaturen, Status)."""
    severity, title, _message = condition_text(analysis)
    facts = [fact("Größe", size_text(analysis.size))]
    if analysis.page_count or analysis.pages_expected:
        pages = analysis.page_count or analysis.pages_expected
        text = f"{pages}"
        if analysis.readable_pages is not None and analysis.readable_pages < pages:
            text += f" (davon {analysis.readable_pages} vollständig lesbar)"
        elif analysis.page_count and analysis.pages_expected and analysis.pages_expected > analysis.page_count:
            text = f"{analysis.page_count} lesbar, {analysis.pages_expected} gefunden"
        elif not analysis.page_count:
            text = f"{pages} gefunden"
        facts.append(fact("Seiten", text))
    if analysis.pdf_version:
        facts.append(fact("PDF-Version", analysis.pdf_version))
    facts.append(fact("Verschlüsselt", "ja" if analysis.encrypted else "nein"))
    if analysis.signatures:
        facts.append(fact("Digitale Signaturen", f"{analysis.signatures} – eine Reparatur kann sie ungültig machen", "caution"))
    facts.append(fact("Status", title, STATUS_TONE.get(severity, "")))
    return facts


def checking_facts(size: int | None) -> list[dict]:
    """Angaben, solange die Analyse läuft."""
    return [fact("Größe", size_text(size)), fact("Status", "Wird geprüft …", "muted")]


def analysis_details(analysis: PdfAnalysis) -> list[dict]:
    """Befunde und Diagnose (»Technische Details«)."""
    details = [
        fact(check.label, check.detail or ("in Ordnung" if check.ok else "–"), "success" if check.ok else ("critical" if check.ok is False else "muted"))
        for check in analysis.checks
    ]
    for finding in analysis.structural_errors:
        details.append(fact("Befund", finding, "caution"))
    for warning in analysis.warnings:
        details.append(fact("Hinweis", warning, "caution"))
    if analysis.forms:
        details.append(fact("Formular", f"{analysis.form_fields} Felder"))
    if analysis.attachments:
        details.append(fact("Dateianhänge", str(analysis.attachments)))
    details.append(fact("Engine", analysis.engine, "muted"))
    return details


def repair_label(analysis: PdfAnalysis | None) -> str:
    """Beschriftung der Hauptschaltfläche passend zum Zustand."""
    if analysis is not None and analysis.condition is Condition.HEALTHY:
        return "Trotzdem neu aufbauen"
    if analysis is not None and analysis.condition is Condition.RAW_RECOVERABLE:
        return "PDF-Struktur rekonstruieren"
    return "PDF reparieren"


def can_repair(analysis: PdfAnalysis | None) -> bool:
    return analysis is not None and analysis.condition not in (Condition.ENCRYPTED, Condition.UNREADABLE)


def analysis_log(analysis: PdfAnalysis) -> list[str]:
    name = Path(analysis.path).name
    return [f"Analyse {name} ({size_text(analysis.size)}): {analysis.condition.value}, Engine {analysis.engine}"] + [f"  {line}" for line in analysis.technical[:80]]


# Ergebnis ----------------------------------------------------------------------------------------
def result_summary(result: PdfRepairResult, analysis: PdfAnalysis | None, output: Path | None) -> tuple[str, str, str]:
    """(Schweregrad, Titel, Meldung) für das Ergebnis einer Reparatur."""
    status = result.status
    if status is RepairStatus.REPAIRED and output is not None:
        if analysis is not None and analysis.condition is Condition.HEALTHY:
            return "success", "PDF wurde neu aufgebaut.", "Die PDF wurde neu aufgebaut, geprüft und gespeichert."
        if result.method in REBUILD_METHODS:
            return "success", "PDF-Struktur wurde rekonstruiert.", "Die Dokumentstruktur wurde aus den noch vorhandenen PDF-Objekten neu aufgebaut, geprüft und gespeichert."
        return "success", "PDF wurde repariert.", "Die reparierte Datei wurde geprüft und gespeichert."
    if status is RepairStatus.PARTIALLY_RECOVERED and output is not None:
        first = result.warnings[0] if result.warnings else "Nicht alle Inhalte konnten wiederhergestellt werden."
        return "warning", "PDF teilweise wiederhergestellt", first
    if status is RepairStatus.ENCRYPTED:
        return "error", "PDF konnte nicht repariert werden.", result.error or "Das Passwort fehlt oder ist falsch."
    return "error", "PDF konnte nicht repariert werden.", result.error or "Es konnte keine lesbare PDF erzeugt werden."


def result_facts(result: PdfRepairResult, output: Path | None) -> list[dict]:
    facts = []
    if output is not None:
        facts.append(fact("Ausgabedatei", output.name))
        facts.append(fact("Ordner", str(output.parent), "muted"))
    facts.append(fact("Ursprüngliche Größe", size_text(result.size_before)))
    if output is not None:
        facts.append(fact("Neue Größe", size_text(result.size_after)))
    if result.pages_before is not None:
        facts.append(fact("Seiten vorher", str(result.pages_before)))
    if output is not None and result.pages_after is not None:
        tone = "success" if result.pages_after == result.pages_before and not result.incomplete_pages else "caution"
        facts.append(fact("Seiten nachher", str(result.pages_after), tone))
    return facts


def result_warnings(result: PdfRepairResult) -> list[str]:
    """Weitere Warnungen (die erste steht bei »teilweise wiederhergestellt« schon im Hinweis)."""
    return list(result.warnings[1:] if result.status is RepairStatus.PARTIALLY_RECOVERED else result.warnings)


def result_actions(result: PdfRepairResult) -> list[dict]:
    """Durchgeführte Reparaturschritte (»Details«)."""
    return [fact(str(index), action) for index, action in enumerate(result.repair_actions, start=1)] or [fact("–", "Keine Aktionen", "muted")]


def rescue_possible(result: PdfRepairResult, analysis: PdfAnalysis | None) -> bool:
    """Rettungsmodus anbieten: lesbare Seiten vorhanden und die Reparatur war (teilweise) erfolglos."""
    if analysis is None or analysis.rasterizable_pages <= 0:
        return False
    if result.status is RepairStatus.FAILED:
        return True
    return result.status is RepairStatus.PARTIALLY_RECOVERED and result.method is not None and result.method is not Method.RASTER


def result_log(result: PdfRepairResult) -> list[str]:
    name = Path(result.input_path).name
    lines = [f"Reparatur {name}: {result.status.value}" + (f" über {result.method.value}" if result.method else "")]
    lines += [f"  Aktion: {a}" for a in result.repair_actions] + [f"  Warnung: {w}" for w in result.warnings]
    lines += [f"  {line}" for line in result.technical[:120]]
    if result.error:
        lines.append(f"  Fehler: {result.error}")
    return lines
