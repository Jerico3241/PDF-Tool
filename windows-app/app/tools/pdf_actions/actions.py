"""Schritte einer Stapel-Aktion, ihre Einstellungen und die feste Reihenfolge.

Die Reihenfolge ist fest, damit das Ergebnis immer stimmt – gleich, in welcher Reihenfolge man die
Schritte anklickt: erst Text erkennen (die Seiten sind noch unverändert), dann bereinigen und
reduzieren, dann Wasserzeichen und Seitenzahlen, dann verkleinern, dann PDF/A (braucht eingebettete
Schriften – auch die der Seitenzahlen) und zuletzt der Kennwortschutz (Verschlüsselung am Ende).
PDF/A und Kennwortschutz schließen sich aus: PDF/A erlaubt keine Verschlüsselung.
"""

from __future__ import annotations

from dataclasses import dataclass, field

OCR = "ocr"
CLEAN = "clean"
FLATTEN = "flatten"
WATERMARK = "watermark"
NUMBERS = "numbers"
OPTIMIZE = "optimize"
PDFA = "pdfa"
PROTECT = "protect"
ORDER = (OCR, CLEAN, FLATTEN, WATERMARK, NUMBERS, OPTIMIZE, PDFA, PROTECT)
LABELS = {
    OCR: "Text erkennen (OCR)",
    CLEAN: "Dokument bereinigen",
    FLATTEN: "Reduzieren",
    WATERMARK: "Wasserzeichen",
    NUMBERS: "Seitenzahlen",
    OPTIMIZE: "PDF verkleinern",
    PDFA: "Als PDF/A speichern",
    PROTECT: "Kennwortschutz",
}
DESCRIPTIONS = {
    OCR: "Gescannte Seiten durchsuchbar machen – Seiten mit Text bleiben unverändert",
    CLEAN: "Metadaten, Skripte, Anhänge und versteckte Daten entfernen",
    FLATTEN: "Formularfelder und Kommentare fest in die Seiten übernehmen",
    WATERMARK: "Text schräg über jede Seite legen",
    NUMBERS: "Seitenzahl unten auf jede Seite setzen",
    OPTIMIZE: "Bilder neu berechnen – kleinere Dateien",
    PDFA: "Für die Archivierung: PDF/A-2b mit eingebetteten Schriften",
    PROTECT: "Kennwort zum Öffnen (AES-256)",
}
NUMBER_FORMATS = {
    "seite_von": "Seite {seite} von {seiten}",
    "seite": "Seite {seite}",
    "zahl": "{seite}",
    "zahl_von": "{seite} / {seiten}",
}
NUMBER_POSITIONS = ("bl", "bc", "br", "tl", "tc", "tr")
DEFAULT_SUFFIX = "_bearbeitet"
MAX_WATERMARK = 120


@dataclass
class Plan:
    steps: list[str] = field(default_factory=list)
    ocr_languages: list[str] = field(default_factory=lambda: ["deu", "eng"])
    watermark_text: str = "VERTRAULICH"
    watermark_opacity: float = 0.25
    number_format: str = "seite_von"
    number_position: str = "bc"
    optimize_level: str = "mittel"
    password: str = ""  # nur im Arbeitsspeicher – nie gespeichert oder protokolliert

    def ordered(self) -> list[str]:
        return [step for step in ORDER if step in self.steps]

    def summary(self) -> str:
        """»Text erkennen (OCR) → PDF verkleinern« – ohne Kennwörter."""
        return " → ".join(LABELS[step] for step in self.ordered())

    def settings(self) -> dict:
        """Zum Speichern der zuletzt gewählten Schritte (ohne Kennwort)."""
        return {
            "schritte": self.ordered(),
            "ocr_sprachen": list(self.ocr_languages),
            "wasserzeichen": self.watermark_text,
            "deckkraft": self.watermark_opacity,
            "seitenzahl": self.number_format,
            "seitenzahl_position": self.number_position,
            "stufe": self.optimize_level,
        }

    @classmethod
    def from_settings(cls, data) -> "Plan":
        plan = cls()
        if not isinstance(data, dict):
            return plan
        plan.steps = [step for step in data.get("schritte") or [] if step in ORDER and step != PROTECT]
        languages = [str(code) for code in data.get("ocr_sprachen") or [] if isinstance(code, str) and code.isascii() and 2 <= len(code) <= 12]
        plan.ocr_languages = languages or plan.ocr_languages
        text = str(data.get("wasserzeichen") or "").strip()
        plan.watermark_text = text[:MAX_WATERMARK] or plan.watermark_text
        try:
            plan.watermark_opacity = min(1.0, max(0.05, float(data.get("deckkraft", plan.watermark_opacity))))
        except (TypeError, ValueError):
            pass
        if data.get("seitenzahl") in NUMBER_FORMATS:
            plan.number_format = data["seitenzahl"]
        if data.get("seitenzahl_position") in NUMBER_POSITIONS:
            plan.number_position = data["seitenzahl_position"]
        if data.get("stufe") in ("klein", "mittel", "hoch"):
            plan.optimize_level = data["stufe"]
        return plan


def problem(plan: Plan) -> str:
    """Was am Plan fehlt – leer, wenn er sich ausführen lässt."""
    steps = plan.ordered()
    if not steps:
        return "Bitte mindestens eine Aktion wählen."
    if PDFA in steps and PROTECT in steps:
        return "PDF/A und Kennwortschutz lassen sich nicht kombinieren – PDF/A erlaubt keine Verschlüsselung."
    if WATERMARK in steps and not plan.watermark_text.strip():
        return "Bitte einen Text für das Wasserzeichen eingeben."
    if PROTECT in steps and len(plan.password) < 4:
        return "Bitte ein Kennwort mit mindestens 4 Zeichen eingeben."
    if OCR in steps and not plan.ocr_languages:
        return "Bitte mindestens eine Sprache für die Texterkennung wählen."
    return ""
