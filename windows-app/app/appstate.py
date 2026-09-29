"""Version, Pfade und gespeicherte Einstellungen – ohne Abhängigkeit von der Oberfläche."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText

APP_DIR = Path(__file__).resolve().parent
INSTALL_DIR = APP_DIR.parent
ASSETS_DIR = INSTALL_DIR / "assets"
DEFAULT_LOGO = ASSETS_DIR / "hott_logo_final.png"
ICON_FILE = ASSETS_DIR / "icon.ico"
APP_NAME = "PDF Tool"
DEVELOPER = "Jerico"
DATA_FOLDER = "PDF-Tool"
# Datenordner bis Version 2.2 (»Übersichten-Ersteller«) – wird beim ersten Start übernommen
LEGACY_DATA_FOLDER = "Uebersichten-Ersteller"
MIGRATION_MARKER = "migration.json"


def _read_version() -> str:
    """Die Version steht zentral in der Datei VERSION (Repository: windows-app/VERSION)."""
    try:
        text = (INSTALL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return text or "0.0.0"


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def migrate_user_data(legacy: Path, target: Path, version: str = "") -> bool:
    """Übernimmt die Daten des Übersichten-Erstellers (bis 2.2) einmalig und verlustfrei.

    1. Nur wenn der neue Ordner noch keine Einstellungen hat und keine Übernahme vermerkt ist.
    2. Sicherung: vollständiges ZIP des alten Ordners im neuen Ordner
       (``migration-backup-<Version>.zip``).
    3. Alle Dateien kopieren (Zeitstempel bleiben), danach Größe und SHA-256 jeder Datei
       sowie die Einstellungen (JSON) vergleichen.
    4. Vermerk ``migration.json`` schreiben. Der alte Ordner bleibt unverändert erhalten.

    Schlägt ein Schritt fehl, werden nur die neu kopierten Dateien entfernt – die Sicherung
    und der alte Ordner bleiben. Rückgabe: ``True``, wenn die Daten übernommen wurden.
    """
    legacy, target = Path(legacy), Path(target)
    if not legacy.is_dir() or (target / "gui-config.json").is_file() or (target / MIGRATION_MARKER).is_file():
        return False
    files = [path for path in legacy.rglob("*") if path.is_file()]
    if not files:
        return False
    old_config = legacy / "gui-config.json"
    seen = ""
    try:
        seen = str(json.loads(old_config.read_text(encoding="utf-8")).get("gesehen") or "")
    except (OSError, ValueError, AttributeError):
        pass
    label = seen if seen and all(part.isdigit() for part in seen.split(".")) else "alt"
    created: list[Path] = []
    try:
        target.mkdir(parents=True, exist_ok=True)
        backup = target / f"migration-backup-{label}.zip"
        with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(legacy).as_posix())
        with zipfile.ZipFile(backup) as archive:
            if archive.testzip() is not None or len(archive.namelist()) != len(files):
                raise OSError("Sicherung unvollständig")
        for path in files:
            destination = target / path.relative_to(legacy)
            destination.parent.mkdir(parents=True, exist_ok=True)
            existed = destination.exists()
            shutil.copy2(path, destination)
            if not existed:
                created.append(destination)
        for path in files:
            destination = target / path.relative_to(legacy)
            if destination.stat().st_size != path.stat().st_size or _file_hash(destination) != _file_hash(path):
                raise OSError(f"Kopie weicht ab: {path.name}")
        if old_config.is_file():
            if json.loads((target / "gui-config.json").read_text(encoding="utf-8")) != json.loads(old_config.read_text(encoding="utf-8")):
                raise OSError("Einstellungen weichen ab")
        marker = {
            "von": str(legacy),
            "am": time.strftime("%Y-%m-%d %H:%M:%S"),
            "version": version,
            "zuletzt_gesehen": seen,
            "dateien": len(files),
            "sicherung": backup.name,
        }
        (target / MIGRATION_MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except (OSError, ValueError, zipfile.BadZipFile):
        for path in created:
            try:
                path.unlink()
            except OSError:
                pass
        return False


def data_dir() -> Path:
    """Benutzerdaten liegen getrennt von den Programmdateien.

    Windows: %APPDATA%\\PDF-Tool – bleibt bei Updates und Neuinstallationen unberührt.
    Daten der Vorversion (%APPDATA%\\Uebersichten-Ersteller) werden beim ersten Start
    übernommen; misslingt das, arbeitet die App weiter mit dem alten Ordner.
    UE_DATA_DIR überschreibt den Ort (Tests).
    """
    override = os.environ.get("UE_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    target = root / DATA_FOLDER
    legacy = root / LEGACY_DATA_FOLDER
    if (target / "gui-config.json").is_file() or (target / MIGRATION_MARKER).is_file() or not legacy.is_dir():
        return target
    if migrate_user_data(legacy, target, _read_version()):
        return target
    return legacy if (legacy / "gui-config.json").is_file() else target


VERSION = _read_version()
DATA_DIR = data_dir()
LEGACY_CONFIG_FILE = INSTALL_DIR / "gui-config.json"  # Ablageort bis Version 2.0.5
CONFIG_FILE = Path(os.environ.get("UE_CONFIG_FILE") or DATA_DIR / "gui-config.json")
ERROR_LOG = DATA_DIR / "fehler.log"

NEUERUNGEN = (
    "Neue Stapelverarbeitung in »Vertragsübersichten« (Ansicht »Stapel«): mehrere Excel-Dateien gleichzeitig vorbereiten und in einem Durchlauf als PDF erstellen.",
    "Jede Datei wird sofort geprüft; bekannte Kunden werden über die gespeicherten E-Mail-Zuordnungen erkannt – wie im Einzelmodus.",
    "Status je Datei, Filter, Massenaktionen und Fortschritt; ein Fehler bei einer Datei unterbricht den Stapel nicht.",
    "»Fehlgeschlagene erneut versuchen«, »Stapel abbrechen« ohne halbe PDFs und vorhandene PDFs werden nie unbeabsichtigt überschrieben.",
    "Kompaktere Excel-Karte: Die Vertragszahlen stehen nur noch in der Statuszeile, darunter nur zusätzliche Angaben.",
    "Alles bleibt lokal auf diesem PC – keine Cloud, keine Uploads.",
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
    """Alle Listen und Werte, die zwischen Starts erhalten bleiben (kompatibel zu 2.0.5).

    Die Kundenhistorie bis 2.3 (``kunden``) übernimmt die Kundenakte 2.0 beim ersten Start
    (``tools/contract_overview/customers/migration.py``).
    """

    def __init__(self, cfg: dict) -> None:
        self.raw = dict(cfg)
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
