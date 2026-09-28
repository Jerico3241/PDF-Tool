"""Version, Pfade und gespeicherte Einstellungen – ohne Abhängigkeit von der Oberfläche."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText

APP_DIR = Path(__file__).resolve().parent
INSTALL_DIR = APP_DIR.parent
ASSETS_DIR = INSTALL_DIR / "assets"
DEFAULT_LOGO = ASSETS_DIR / "hott_logo_final.png"
ICON_FILE = ASSETS_DIR / "icon.ico"
APP_NAME = "Übersichten-Ersteller"
DEVELOPER = "Jerico"
DATA_FOLDER = "Uebersichten-Ersteller"


def _read_version() -> str:
    """Die Version steht zentral in der Datei VERSION (Repository: windows-app/VERSION)."""
    try:
        text = (INSTALL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return text or "0.0.0"


def data_dir() -> Path:
    """Benutzerdaten liegen getrennt von den Programmdateien.

    Windows: %APPDATA%\\Uebersichten-Ersteller – bleibt bei Updates und
    Neuinstallationen unberührt. UE_DATA_DIR überschreibt den Ort (Tests).
    """
    override = os.environ.get("UE_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / DATA_FOLDER
    return Path.home() / ".config" / DATA_FOLDER


VERSION = _read_version()
DATA_DIR = data_dir()
LEGACY_CONFIG_FILE = INSTALL_DIR / "gui-config.json"  # Ablageort bis Version 2.0.5
CONFIG_FILE = Path(os.environ.get("UE_CONFIG_FILE") or DATA_DIR / "gui-config.json")
ERROR_LOG = DATA_DIR / "fehler.log"

NEUERUNGEN = (
    "Fettschrift aus der Excel-Liste wird jetzt zellgenau in die PDF übernommen.",
    "Kopf- und Fußzeile lassen sich formatieren: Schriftart, Größe, Farbe, fett, kursiv, unterstrichen und Ausrichtung je Absatz.",
    "Übersichtlichere Excel-Prüfung: aktive und ausgeblendete Verträge, Rechnungsempfänger und fehlende Spalten auf einen Blick.",
    "»Bereit zum Erstellen« zeigt schon vor dem Klick, was noch fehlt.",
    "Nach dem Erstellen: Öffnen, Ordner öffnen, Pfad kopieren oder direkt eine neue Übersicht beginnen.",
    "Eingaben werden automatisch gespeichert; zahlreiche Verbesserungen bei Speicherung und Stabilität.",
)

DEFAULT_REGELN = [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}]
DEFAULT_DATEINAME = "Vertragsuebersicht_Kd{kd}.pdf"
DEFAULT_TITEL = "Vertragsübersicht"
DEFAULT_UNTERTITEL = "Wartungs- und Nutzungsverträge"
DEFAULT_LOGO_BREITE = "62"

# Standard-Fußzeile der App – die einzige Stelle, an der dieser Text steht.
DEFAULT_FOOTER = (
    "Die oben aufgeführte Auflistung gibt den aktuellen Stand Ihrer Verträge sowie "
    "die derzeit geltenden Vertragspreise wieder.\n"
    "Alle genannten Preise verstehen sich zuzüglich der jeweils geltenden "
    "gesetzlichen Mehrwertsteuer.\n\n"
    "Die Angaben erfolgen gemäß Ihren abgeschlossenen Verträgen sowie den jeweils "
    "geltenden Vertragsbedingungen und berücksichtigen gegebenenfalls bereits "
    "erfolgte Preisanpassungen."
)
# Markiert eine bewusst gespeicherte Fußzeile (ab 2.1.0). Fehlt die Markierung, stammt
# der Wert aus einer älteren Version, in der eine leere Fußzeile der Normalfall war.
FOOTER_EXPLICIT = "fusszeile_explizit"
# Formatierung (neu in Version 2.2) neben dem weiterhin gespeicherten reinen Text – siehe richtext.py
HEADER_FORMAT = "kopfzeile_format"
FOOTER_FORMAT = "fusszeile_format"
BAUSTEIN_FORMAT = "format"

MAX_KUNDEN = 12
MAX_PDFS = 8
MAX_VORLAGEN = 20
MAX_BAUSTEINE = 20


def major_minor(version: str) -> tuple[str, ...]:
    return tuple(str(version).split(".")[:2])


def desktop_dir() -> Path:
    home = Path.home()
    for name in ("Desktop", "Schreibtisch"):
        candidate = home / name
        if candidate.is_dir():
            return candidate
    return home


def filename_of(path: str) -> str:
    if not path:
        return "Keine Datei gewählt"
    name = Path(path).name
    return name or path


# --- Fußzeile ------------------------------------------------------------------


def footer_from(entry: dict | None, fallback: str = DEFAULT_FOOTER) -> str:
    """Fußzeile aus der Konfiguration oder einer Vorlage – mit Übernahme alter Stände.

    * bewusst gespeicherte Fußzeile (``fusszeile_explizit``): exakt übernehmen, auch leer
    * ältere Stände mit eigenem Text: exakt übernehmen (keine Datenverluste)
    * Wert fehlt, ist ``null``/ungültig oder leer aus älteren Versionen: Standard
    """
    if not isinstance(entry, dict):
        return fallback
    value = entry.get("fusszeile")
    if not isinstance(value, str):
        return fallback
    if entry.get(FOOTER_EXPLICIT) is True:
        return value
    return value if value.strip() else fallback


def customer_footer(entry: dict | None) -> str | None:
    """Fußzeile einer Kundenakte oder ``None``, wenn sie keine sinnvolle eigene Fußzeile hat.

    Die Kundenakte merkt sich die Fußzeile automatisch. Ein leerer Wert aus älteren
    Versionen darf die aktuell gültige Fußzeile deshalb nicht ersetzen.
    """
    if not isinstance(entry, dict):
        return None
    value = entry.get("fusszeile")
    if isinstance(value, str) and value.strip():
        return value
    return None


# --- Formatierte Kopf- und Fußzeile (Rich Text) ---------------------------------------
#
# Der reine Text bleibt unter »kopfzeile«/»fusszeile« gespeichert (kompatibel zu älteren
# Versionen). Die Formatierung steht daneben unter »kopfzeile_format«/»fusszeile_format«.
# Fehlt sie oder passt sie nicht zum Text, gilt die Standardformatierung.


def default_footer_rich() -> RichText:
    """Standard-Fußzeile mit Standardformatierung (Helvetica 8 pt, dunkelgrau, zentriert)."""
    return RichText.plain(DEFAULT_FOOTER, FOOTER_STYLE, FOOTER_ALIGN)


def footer_rich_from(entry: dict | None) -> RichText:
    """Fußzeile samt Formatierung aus Konfiguration oder Vorlage (Migration wie ``footer_from``)."""
    text = footer_from(entry)
    fmt = entry.get(FOOTER_FORMAT) if isinstance(entry, dict) else None
    return RichText.from_storage(text, fmt, FOOTER_STYLE, FOOTER_ALIGN)


def header_rich_from(entry: dict | None) -> RichText:
    """Kopfzeile samt Formatierung; ohne gespeicherten Text ist sie leer."""
    text = entry.get("kopfzeile") if isinstance(entry, dict) else None
    fmt = entry.get(HEADER_FORMAT) if isinstance(entry, dict) else None
    return RichText.from_storage(text if isinstance(text, str) else "", fmt, HEADER_STYLE, HEADER_ALIGN)


def customer_footer_rich(entry: dict | None) -> RichText | None:
    """Eigene Fußzeile einer Kundenakte mit Formatierung – ``None`` bei leeren Altwerten."""
    text = customer_footer(entry)
    if text is None:
        return None
    return RichText.from_storage(text, entry.get(FOOTER_FORMAT), FOOTER_STYLE, FOOTER_ALIGN)  # type: ignore[union-attr]


def customer_header_rich(entry: dict | None) -> RichText | None:
    """Kopfzeile einer Kundenakte (auch bewusst leer); ``None``, wenn sie keine gespeichert hat."""
    if not isinstance(entry, dict) or "kopfzeile" not in entry:
        return None
    text = entry.get("kopfzeile")
    return RichText.from_storage(text if isinstance(text, str) else "", entry.get(HEADER_FORMAT), HEADER_STYLE, HEADER_ALIGN)


def baustein_rich(entry: dict | None) -> RichText:
    """Textbaustein mit Formatierung; alte Bausteine (nur Text) erhalten das Standardformat."""
    text = entry.get("text") if isinstance(entry, dict) else None
    fmt = entry.get(BAUSTEIN_FORMAT) if isinstance(entry, dict) else None
    return RichText.from_storage(text if isinstance(text, str) else "", fmt, FOOTER_STYLE, FOOTER_ALIGN)


# --- Konfiguration --------------------------------------------------------------


def normalize_regeln(raw) -> list[dict]:
    regeln = []
    for eintrag in raw or []:
        if not isinstance(eintrag, dict):
            continue
        nadel = str(eintrag.get("enthaelt") or "").strip()
        ziel = str(eintrag.get("zyklus") or "").strip()
        if nadel and ziel:
            regeln.append({"enthaelt": nadel, "zyklus": ziel})
    return regeln


def migrate_legacy_config(target: Path | None = None, legacy: Path | None = None) -> bool:
    """Übernimmt die Einstellungen aus dem Programmordner (bis 2.0.5) in den Datenordner."""
    target = Path(target or CONFIG_FILE)
    legacy = Path(legacy or LEGACY_CONFIG_FILE)
    if target.is_file() or not legacy.is_file():
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
        return True
    except OSError:
        return False


def load_config(path: Path | None = None) -> dict:
    """Liest die Einstellungen. Beschädigte Dateien liefern leere Einstellungen."""
    target = Path(path or CONFIG_FILE)
    if path is None:
        migrate_legacy_config(target)
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict, path: Path | None = None) -> bool:
    """Schreibt atomar (temporäre Datei + Umbenennen), damit ein Absturz keine halbe Datei hinterlässt."""
    target = Path(path or CONFIG_FILE)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".gui-config-", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.remove(temp)
        return True
    except OSError:
        return False


class State:
    """Alle Listen und Werte, die zwischen Starts erhalten bleiben (kompatibel zu 2.0.5)."""

    def __init__(self, cfg: dict) -> None:
        self.raw = dict(cfg)
        self.kunden = [c for c in cfg.get("kunden", []) if isinstance(c, dict)][:MAX_KUNDEN]
        self.bausteine = [b for b in cfg.get("bausteine", []) if isinstance(b, dict) and b.get("name")]
        if "regeln" in cfg:
            self.regeln = normalize_regeln(cfg.get("regeln"))
        else:
            self.regeln = [dict(r) for r in DEFAULT_REGELN]
        self.pdfs = [p for p in cfg.get("pdfs", []) if isinstance(p, str)][:MAX_PDFS]
        self.vorlagen = [v for v in cfg.get("vorlagen", []) if isinstance(v, dict) and v.get("name")]
        staende = cfg.get("staende", {})
        self.staende = staende if isinstance(staende, dict) else {}
        self.gesehen = str(cfg.get("gesehen", ""))

    # Kundenakte ---------------------------------------------------------------
    def remember_customer(
        self,
        firma: str,
        kd: str,
        mail: str,
        excel: str,
        logo: str,
        fusszeile: str,
        kopfzeile: str,
        pdf: str | None = None,
        fusszeile_format: dict | None = None,
        kopfzeile_format: dict | None = None,
    ) -> bool:
        firma, kd = firma.strip(), kd.strip()
        if not firma and not kd:
            return False
        key = (firma.casefold(), kd)
        previous_pdf = ""
        for alt in self.kunden:
            if (str(alt.get("firmenname", "")).casefold(), str(alt.get("kundennummer", ""))) == key:
                previous_pdf = str(alt.get("pdf") or "")
                break
        self.kunden = [alt for alt in self.kunden if (str(alt.get("firmenname", "")).casefold(), str(alt.get("kundennummer", ""))) != key]
        eintrag = {
            "firmenname": firma,
            "kundennummer": kd,
            "rechnungsempfaenger": mail.strip(),
            "excel": excel.strip(),
            "logo": logo.strip(),
            "fusszeile": fusszeile,
            "kopfzeile": kopfzeile,
            "pdf": previous_pdf if pdf is None else pdf,
        }
        if fusszeile_format is not None:
            eintrag[FOOTER_FORMAT] = fusszeile_format
        if kopfzeile_format is not None:
            eintrag[HEADER_FORMAT] = kopfzeile_format
        self.kunden.insert(0, eintrag)
        self.kunden = self.kunden[:MAX_KUNDEN]
        return True

    @staticmethod
    def customer_label(eintrag: dict) -> str:
        return f"{eintrag.get('firmenname') or 'Ohne Name'} · {eintrag.get('kundennummer') or '–'}"

    def customer_labels(self) -> dict[str, dict]:
        labels: dict[str, dict] = {}
        for eintrag in self.kunden:
            label = self.customer_label(eintrag)
            while label in labels:
                label += " "
            labels[label] = eintrag
        return labels

    # PDFs -------------------------------------------------------------------------
    def remember_pdf(self, path: str) -> None:
        self.pdfs = [path] + [alt for alt in self.pdfs if alt != path]
        self.pdfs = self.pdfs[:MAX_PDFS]

    def existing_pdfs(self) -> dict[str, str]:
        self.pdfs = [p for p in self.pdfs if Path(p).is_file()][:MAX_PDFS]
        labels: dict[str, str] = {}
        for pfad in self.pdfs:
            label = Path(pfad).name
            if label in labels:
                label = f"{Path(pfad).name} · {Path(pfad).parent.name}"
            labels[label] = pfad
        return labels

    # Vorlagen und Textbausteine ------------------------------------------------------
    @staticmethod
    def _upsert(items: list[dict], entry: dict, limit: int) -> list[dict]:
        name = str(entry.get("name", ""))
        rest = [alt for alt in items if str(alt.get("name", "")) != name]
        return ([entry] + rest)[:limit]

    def save_vorlage(self, entry: dict) -> None:
        self.vorlagen = self._upsert(self.vorlagen, entry, MAX_VORLAGEN)

    def delete_vorlage(self, name: str) -> bool:
        before = len(self.vorlagen)
        self.vorlagen = [alt for alt in self.vorlagen if str(alt.get("name", "")) != name]
        return len(self.vorlagen) != before

    def find_vorlage(self, name: str) -> dict | None:
        return next((v for v in self.vorlagen if str(v.get("name", "")) == name), None)

    def save_baustein(self, name: str, text: str, fmt: dict | None = None) -> None:
        entry = {"name": name, "text": text}
        if fmt is not None:
            entry[BAUSTEIN_FORMAT] = fmt
        self.bausteine = self._upsert(self.bausteine, entry, MAX_BAUSTEINE)

    def delete_baustein(self, name: str) -> bool:
        before = len(self.bausteine)
        self.bausteine = [alt for alt in self.bausteine if str(alt.get("name", "")) != name]
        return len(self.bausteine) != before

    def find_baustein(self, name: str) -> dict | None:
        return next((b for b in self.bausteine if str(b.get("name", "")) == name), None)

    # Zyklus-Regeln ----------------------------------------------------------------------
    def add_regel(self, nadel: str, zyklus: str) -> None:
        nadel, zyklus = nadel.strip(), zyklus.strip()
        self.regeln = [alt for alt in self.regeln if str(alt.get("enthaelt", "")).lower() != nadel.lower()]
        self.regeln.append({"enthaelt": nadel, "zyklus": zyklus})

    def delete_regel(self, index: int) -> dict | None:
        if 0 <= index < len(self.regeln):
            return self.regeln.pop(index)
        return None
