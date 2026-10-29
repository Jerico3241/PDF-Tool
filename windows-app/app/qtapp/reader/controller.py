"""Werkzeug »PDF Reader & Editor« (in QML: ``Reader``): Tabs, Öffnen (Dialog, Ziehen, zuletzt
geöffnet, »Öffnen mit«), Schließen mit Rückfrage, Passwörter, beschädigte PDFs, Sitzungs-
wiederherstellung nach einem Absturz und die Bildquelle der Seiten.

Tabs: Kontextmenü (schließen, andere bzw. rechts schließen), Reihenfolge per Ziehen (``moveTab``),
»Geschlossenen Tab wieder öffnen« (Strg+Umschalt+T, zuletzt geschlossene Dokumente mit Pfad und Seite).
Mit der Einstellung »PDFs der letzten Sitzung beim Start wieder öffnen« merkt sich das Beenden die
geöffneten PDFs (nur Pfade, Seite und das aktive) in ``gui-config.json``; der nächste Start öffnet sie im
Hintergrund wieder. Dazu Nachtmodus der Seitenbilder, Schnellwerkzeuge der Startseite und »Per E-Mail
senden«.

Passwörter bleiben nur im Arbeitsspeicher (nie in Einstellungen, Protokoll oder Sicherung). Die
Liste »Zuletzt geöffnet« enthält nur Pfade und lässt sich leeren. Inhalte von PDFs werden nie
protokolliert.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

import winsys

from tools.pdf_editor import compare as comparing
from tools.pdf_editor import imagepdf, office, recovery, scan
from tools.pdf_editor.errors import DamagedDocument, EditorError, NotAPdf, PasswordRequired
from tools.registry import CONTRACTS, READER

from .. import files, mail
from ..base import Observable, prop
from ..models import KeyedListModel
from .document import DocumentController
from tools.pdf_editor.limits import MAX_PIXELS

from .engine import BACKGROUND, NIGHT_TAG, THUMB, THUMB_WIDTH, VIEW, Engine, PageImageProvider, RenderCache, night_image

RECENT_LIMIT = 12
TAB_LIMIT = 24
CLOSED_LIMIT = 10  # »Geschlossenen Tab wieder öffnen«: so viele zuletzt geschlossene Dokumente
NIGHT_KEY = "reader_nachtmodus"  # Nachtmodus (gui-config.json)
CONTRACT_LISTS = (".xlsx", ".xlsm", ".xls")  # Startseite: Excel-Listen gehören den »Vertragsübersichten« (wie dort)
SHEET_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".ods", ".csv")  # Tabellen zum Bearbeiten (seit 5.0 Beta 2)
TEXT_SUFFIXES = (".docx", ".doc", ".odt", ".rtf")  # Texte zum Bearbeiten (seit 5.0 Beta 3)
SLIDE_SUFFIXES = (".pptx", ".ppt", ".odp")  # Präsentationen zum Bearbeiten (seit 5.0 Beta 4)
# Vorlagen (seit 5.0 Beta 6, ``scripts/make_office_templates.py``): OpenDocument in einer Datei, gespeichert wird im
# Format von ``suffix``. ``name`` ergibt den Namen des neuen Dokuments (»Rechnung1.xlsx«)
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "vorlagen"
OFFICE_TEMPLATES = (
    {"key": "lebenslauf", "title": "Lebenslauf", "name": "Lebenslauf", "kind": "text", "file": "lebenslauf.fodt", "suffix": ".docx",
     "description": "Klar gegliedert: Profil, Stationen, Ausbildung, Kenntnisse"},
    {"key": "geschaeftsbrief", "title": "Geschäftsbrief", "name": "Brief", "kind": "text", "file": "geschaeftsbrief.fodt",
     "suffix": ".docx", "description": "Nach DIN 5008, mit Fußzeile für Bank und Kontakt"},
    {"key": "bericht", "title": "Bericht", "name": "Bericht", "kind": "text", "file": "bericht.fodt", "suffix": ".docx",
     "description": "Zusammenfassung, Ergebnisse mit Kennzahlen, Empfehlung"},
    {"key": "protokoll", "title": "Besprechungsprotokoll", "name": "Protokoll", "kind": "text", "file": "protokoll.fodt",
     "suffix": ".docx", "description": "Rahmen, Tagesordnung, Ergebnisse und Aufgaben"},
    {"key": "rechnung", "title": "Rechnung", "name": "Rechnung", "kind": "tabelle", "file": "rechnung.fods", "suffix": ".xlsx",
     "description": "Rechnet Netto, Umsatzsteuer und Gesamtbetrag selbst"},
    {"key": "budget", "title": "Haushaltsbudget", "name": "Budget", "kind": "tabelle", "file": "budget.fods", "suffix": ".xlsx",
     "description": "Einnahmen und Ausgaben, geplant und tatsächlich"},
    {"key": "projektvorstellung", "title": "Projektvorstellung", "name": "Projekt", "kind": "praesentation",
     "file": "projektvorstellung.fodp", "suffix": ".pptx", "description": "Fünf Folien: Ausgangslage, Ziele, Zeitplan, nächste Schritte"},
)
SESSION_KEY = "reader_sitzung"  # PDFs der letzten Sitzung – nur mit der Einstellung, nur Pfade und Seiten
UPDATE_SESSION_KEY = "reader_sitzung_update"  # einmal: nach einem automatischen Update die PDFs wieder öffnen
# Schnellwerkzeuge der Startseite: Aktion (DocumentController.runAction; »merge«: PDFs anhängen), Titel,
# Beschreibung (Tooltip), Symbol
QUICK_TOOLS = (
    ("optimize", "PDF verkleinern", "Verkleinerte Kopie speichern – das Original bleibt unverändert", "arrow_minimize"),
    ("pdfa", "Als PDF/A speichern", "Archivfähige Kopie (PDF/A-2b) mit eingebetteten Schriften speichern", "library"),
    ("images", "PDF aus Bildern", "Fotos und Scans (JPG, PNG, TIFF …) zu einer PDF zusammenfügen", "image_add"),
    ("scan", "Scannen", "Vom Scanner direkt in eine PDF – auf Wunsch durchsuchbar", "scan_text"),
    ("office", "Office in PDF", "Word-, Excel- oder PowerPoint-Datei in PDF umwandeln (mit Microsoft Office)", "document_pdf"),
    ("redact", "Schwärzen", "Text und Bereiche dauerhaft unkenntlich machen", "eye_off"),
    ("protect", "Kennwortschutz", "Kennwort zum Öffnen oder Einschränkungen festlegen", "lock_closed"),
    ("watermark", "Wasserzeichen", "Wasserzeichen auf die Seiten legen", "layer"),
    ("headerFooter", "Seitenzahlen", "Seitenzahlen, Kopf- und Fußzeilen einfügen", "document_page_number"),
    ("clean", "Dokument bereinigen", "Vor dem Weitergeben: Daten entfernen, die man auf den Seiten nicht sieht", "eraser"),
    ("sign", "Unterschreiben", "Unterschrift einfügen", "signature"),
    ("merge", "Zusammenführen", "Weitere PDFs an ein Dokument anhängen", "merge"),
)
# Schnellwerkzeuge der Startseite (seit 5.0 Beta 2, wie im Design): Aktion, Titel, Beschreibung, Symbol
START_TOOLS = (
    ("office", "In PDF umwandeln", "Word-, Excel- oder PowerPoint-Datei in eine PDF umwandeln", "arrow_export"),
    ("merge", "Zusammenfügen", "Mehrere PDFs zu einer zusammenfügen", "merge"),
    ("split", "Teilen", "Eine PDF in mehrere Dateien teilen", "cut"),
    ("images", "Bilder zu PDF", "Fotos und Scans (JPG, PNG, TIFF …) zu einer PDF zusammenfügen", "image"),
    ("compare", "Vergleichen", "Zwei Fassungen einer PDF vergleichen – Unterschiede farbig markiert", "branch_compare"),
    ("overview", "Vertragsübersicht", "Aus einer Excel-Liste eine Vertragsübersicht erstellen", "document"),
)
LEFT_PANELS = ("thumbs", "outline", "search", "attachments", "")
RIGHT_PANELS = ("comments", "properties", "assistant", "compare", "")
CLIP_FORMAT = "application/x-pdftool-objects"  # Kennung kopierter Objekte in der Zwischenablage des Systems
_OCR_PROBE: dict = {"done": False, "engine": None}  # Texterkennung: einmal je Programmlauf gesucht
MAX_WIDTH = 12000  # Pixel – breitere Seitenbilder gibt es nicht (der Ausschnitt bleibt scharf)
# Farben der Werkzeuge (Text, Zeichnen, Markieren, Kommentare) – Farben auf dem Papier
TOOL_COLORS = (
    ("#000000", "Schwarz"), ("#5F6368", "Grau"), ("#E53935", "Rot"), ("#FB8C00", "Orange"), ("#FFEB3B", "Gelb"),
    ("#43A047", "Grün"), ("#00897B", "Petrol"), ("#1E88E5", "Blau"), ("#3949AB", "Indigo"), ("#8E24AA", "Lila"),
)
FONT_FAMILIES = (("Helvetica", "Serifenlos (Helvetica/Arial)"), ("Times", "Serif (Times)"), ("Courier", "Festbreite (Courier)"))
HELP_STEPS = (
    "PDF öffnen: »Öffnen« (Strg+O), eine Datei in das Fenster ziehen oder eine Datei aus »Zuletzt geöffnet« wählen.",
    "Lesen: Seiten blättern (Bild ↑/↓), zoomen (Strg+Mausrad, Strg++ / Strg+−), Miniaturen und Lesezeichen links, Suchen mit Strg+F.",
    "Bearbeiten: Werkzeug links neben dem Dokument wählen – Text ändern oder hinzufügen, Kommentare, Zeichnen, Unterschreiben; jedes weitere Werkzeug mit Namen unter »Alle Werkzeuge«. Rückgängig mit Strg+Z.",
    "Speichern: Strg+S (die Datei wird erst nach erfolgreicher Prüfung ersetzt), Speichern unter: Strg+Umschalt+S. Drucken: Strg+P.",
    "Vergleichen und Präsentieren: »Alle Werkzeuge« → »Mit anderer Fassung vergleichen …« zeigt Unterschiede farbig; »Geteilte Ansicht« zeigt zwei PDFs nebeneinander; F5 startet die Präsentation.",
    "Archivieren und Umwandeln: »Alle Werkzeuge« → »Als PDF/A speichern …«; Bilder (Fotos, Scans) in das Fenster ziehen oder im Explorer über »Senden an« → »Novadesk (Bilder zu PDF)« zu einer PDF zusammenfügen.",
)
HELP_NOTES = (
    "Textänderungen nennen ihren Weg: »Direkt im PDF geändert«, »Neu gesetzt« oder »Kompatibilitätsmodus« (Überlagerung – keine Schwärzung, der Originaltext bleibt in der Datei).",
    "Ungespeicherte Änderungen werden regelmäßig lokal gesichert und nach einem Absturz zum Wiederherstellen angeboten.",
    "PDF-JavaScript wird nie ausgeführt. Alle Dateien bleiben auf diesem PC.",
)
HINT = "Strg+O Öffnen   ·   Strg+F Suchen   ·   Strg+S Speichern   ·   Strg+P Drucken   ·   Strg+Z Rückgängig"


class ReaderController(Observable):
    hasDocumentChanged, hasDocument = prop(bool, "hasDocument", False)
    currentKeyChanged, currentKey = prop(str, "currentKey", "")
    recentChanged, recent = prop(list, "recent", [])
    dropHighlightChanged, dropHighlight = prop(bool, "dropHighlight", False)
    # Seitenleisten und »Seiten organisieren« des aktuellen Tabs – jeder Tab merkt sich seine eigenen
    leftPanelChanged, leftPanel = prop(str, "leftPanel", "thumbs")  # thumbs, outline, search, attachments oder ""
    rightPanelChanged, rightPanel = prop(str, "rightPanel", "")  # comments, properties, assistant oder ""
    organizeChanged, organize = prop(bool, "organize", False)  # Ansicht »Seiten organisieren«
    openingChanged, opening = prop(int, "opening", 0)  # Dateien, die gerade geöffnet werden
    fullScreenChanged, fullScreen = prop(bool, "fullScreen", False)  # Vollbild (nur das Dokument)
    presentingChanged, presenting = prop(bool, "presenting", False)  # Präsentation: Vollbild, Seite für Seite, schwarz
    splitKeyChanged, splitKey = prop(str, "splitKey", "")  # geteilte Ansicht: Dokument rechts neben dem aktuellen ("" = aus)
    # Vergleichen: läuft, Ergebnis (Text), Änderungen [{key, kind, before, after, oldPage, newPage}], gewählte Änderung
    compareActiveChanged, compareActive = prop(bool, "compareActive", False)
    compareRunningChanged, compareRunning = prop(bool, "compareRunning", False)
    compareSummaryChanged, compareSummary = prop(str, "compareSummary", "")
    compareItemsChanged, compareItems = prop(list, "compareItems", [])
    compareIndexChanged, compareIndex = prop(int, "compareIndex", -1)
    compareNamesChanged, compareNames = prop(list, "compareNames", [])  # [alte Fassung, neue Fassung]
    canPasteChanged, canPaste = prop(bool, "canPaste", False)  # Zwischenablage: Objekte, Bild oder Text
    pageClipChanged, pageClip = prop(int, "pageClip", 0)  # kopierte Seiten (Anzahl; über Tabs hinweg)
    # Texterkennung: "" (noch nicht gesucht), "pruefen", "bereit" oder "fehlt"; installierte Sprachen
    ocrStateChanged, ocrState = prop(str, "ocrState", "")
    ocrLanguagesChanged, ocrLanguages = prop(list, "ocrLanguages", [])
    canReopenChanged, canReopen = prop(bool, "canReopen", False)  # »Geschlossenen Tab wieder öffnen« möglich
    nightModeChanged, nightMode = prop(bool, "nightMode", False)  # Seiten dunkel, Schrift hell (nur die Anzeige)

    currentChanged = Signal()

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.engine = Engine(self, on_exception=app.report_exception)
        self.cache = RenderCache()
        self._tabs = KeyedListModel(("key", "name", "dirty", "path", "tip", "kind"), key="key", parent=self)
        self._docs: dict[str, DocumentController] = {}
        self._current: DocumentController | None = None
        self._ids = 0
        self._calc = None  # Rechenkern der Tabellen (``CalcService``) – erst mit der ersten Tabelle
        self._sheets_made = 0  # neue Tabellen: »Mappe1«, »Mappe2« …
        self._text = None  # Textkern (``TextService``) – erst mit dem ersten Text
        self._texts_made = 0  # neue Texte: »Dokument1«, »Dokument2« …
        self._slides_made = 0  # neue Präsentationen: »Präsentation1«, »Präsentation2« …
        self._templates_made: dict[str, int] = {}  # aus Vorlagen: »Rechnung1«, »Rechnung2« …
        recent = cfg.get("reader_zuletzt")
        self._recent_paths = [str(p) for p in recent if isinstance(p, str)][:RECENT_LIMIT] if isinstance(recent, list) else []
        # Wann zuletzt geöffnet (Startseite »Zuletzt verwendet«); Einträge aus älteren Versionen haben keine Zeit
        opened = cfg.get("reader_zuletzt_zeit")
        self._recent_opened = {str(k): str(v) for k, v in opened.items() if isinstance(k, str) and isinstance(v, str) and k in self._recent_paths} if isinstance(opened, dict) else {}
        self._recent_stat: dict[str, tuple[bool, int]] = {}  # Pfad → (vorhanden, Größe) beim letzten Prüfen
        self._conversions: list[Callable[[], None]] = []  # Office-Dateien zum Ansehen: die erste läuft, die übrigen warten
        view = cfg.get("reader_ansicht") if isinstance(cfg.get("reader_ansicht"), dict) else {}
        self._view = {"fit": view.get("fit", "width") if view.get("fit") in ("width", "page", "") else "width", "zoom": float(view.get("zoom", 100) or 100), "mode": view.get("mode", "continuous")}
        if view.get("links") in LEFT_PANELS:
            self.set_quietly("leftPanel", view.get("links"))
        self._window_before_full = None  # Fensterzustand vor dem Vollbild
        self._split_pending = False  # geteilte Ansicht: das nächste geöffnete PDF kommt neben das bisherige
        self._compare_pending: str = ""  # Vergleichen: Kennung der neuen Fassung, bis die alte geöffnet ist
        self._compare: tuple | None = None  # (alte Fassung, neue Fassung, Ergebnis)
        self._compare_serial = 0
        self._before_presentation: tuple | None = None  # (Dokument, Ansicht, Einpassen, Zoom, Werkzeug) vor der Präsentation
        self._watching_window = False
        self._attachment_dir: str | None = None  # eigener Ordner für geöffnete Anhänge (beim Beenden gelöscht)
        self._clip = None  # kopierte Objekte (objectops.Clip) – gilt für alle Tabs
        self._ocr_engine = None  # ocr.OcrEngine, sobald gefunden
        chosen = cfg.get("reader_ocr_sprachen")
        self._ocr_chosen = [str(code) for code in chosen if isinstance(code, str)][:6] if isinstance(chosen, list) else []
        self._clip_cut = False
        self._page_data: bytes | None = None  # kopierte Seiten als kleine PDF
        stored_sign = cfg.get("reader_signieren")
        self.sign_defaults: dict = dict(stored_sign) if isinstance(stored_sign, dict) else {}  # Grund, Ort, sichtbar, Zertifikat
        self._paste_counts: dict[tuple[str, int], int] = {}  # wie oft je Dokument und Seite eingefügt
        self._clipboard_watched = False
        self.source_dir = str(cfg.get("ordner_reader") or "")
        images = cfg.get("reader_bilder") if isinstance(cfg.get("reader_bilder"), dict) else {}
        self._image_options = {
            "pageSize": images.get("seite") if images.get("seite") in ("auto", *imagepdf.PAGE_SIZES) else "auto",
            "margin": images.get("rand") if images.get("rand") in imagepdf.MARGINS else "none",
            "folder": str(images.get("ordner") or ""),
        }
        stored = cfg.get("reader_scan") if isinstance(cfg.get("reader_scan"), dict) else {}
        settings = scan.Settings.of({"source": stored.get("quelle"), "color": stored.get("farbe"), "dpi": stored.get("dpi")})
        self._scan_options = {
            "source": settings.source, "color": settings.color, "dpi": settings.dpi, "ocr": stored.get("ocr") is not False,
            "scanner": str(stored.get("scanner") or ""), "folder": str(stored.get("ordner") or ""),
        }
        self._scanning = False
        self._external: list[str] = []
        self._preloaded = False  # PDF-Engine vorab geladen (bzw. angestoßen)
        self._opening_paths: list[str] = []  # Dateien, die gerade geöffnet werden
        self._closed: list[dict] = []  # zuletzt geschlossene Dokumente mit Pfad: {"path", "page"} – das neueste zuletzt
        self.set_quietly("nightMode", cfg.get(NIGHT_KEY) is True)
        # Letzte Sitzung (nur mit der Einstellung): gilt bis zum Beenden, das sie neu festhält; der Start öffnet sie einmal
        self._session = _session_from(cfg.get(SESSION_KEY))
        self._session_pending = self._session
        # Automatisches Update (seit 4.0 Beta 7): die PDFs vor dem Neustart einmal wieder öffnen, auch ohne Einstellung
        self.restore_after_update = False
        self._update_once = cfg.get(UPDATE_SESSION_KEY) is True
        self._restoring = False  # Wiederherstellung läuft (Beenden währenddessen: die gemerkte Liste bleibt)
        self._quit_active = ""  # beim Beenden: der aktive Tab vor den Rückfragen zu ungespeicherten Dokumenten
        self._refresh_recent()
        app.observe("ready", self._ready)
        app.observe("pagesLoaded", self._pages_loaded)
        app.observe("currentPage", self._page_changed)
        app.documents_open = lambda: self.hasDocument
        if app.settings is not None:
            app.settings.observe("readerRestoreSession", self._restore_setting)

    # QML: aktuelles Dokument ---------------------------------------------------------------------------------
    def _get_current(self):
        return self._current

    current = Property(QObject, _get_current, notify=currentChanged)

    def _get_split(self):
        return self._docs.get(self.splitKey)

    splitDoc = Property(QObject, _get_split, notify=splitKeyChanged)

    def provider(self) -> PageImageProvider:
        return PageImageProvider(self._render, self.cache)

    def _render(self, ident: str, page: int, width: int, revision: int, kind: str, region: tuple, deliver, night: bool = False):
        """Seitenbild für die Anzeige (``night``: im Nachtmodus umgekehrt und abgemildert). Drucken und Export
        rendern selbst über die Sitzung – nie über diesen Weg."""
        controller = self._docs.get(ident)
        if controller is None:
            return None
        cache = self.cache

        def work():
            session = controller.session
            if session is None or session.closed:
                deliver(None, "Dokument geschlossen")
                return None
            try:
                image = session.render(page, max(8, min(int(width), MAX_WIDTH)), kind, region)
                if image is not None and night:
                    image = night_image(image)
            except Exception as exc:  # noqa: BLE001 - eine Seite ohne Bild statt Absturz
                _log("render").warning("Seite %d ließ sich nicht darstellen (%s): %s", page + 1, kind, type(exc).__name__)
                deliver(None, type(exc).__name__)
                return None
            if image is not None:
                cache.put((ident, page, width, session.document.revision, kind, region, bool(night)), image)
            deliver(image, "" if image is not None else "Seite nicht vorhanden")
            return None

        return self.engine.submit(work, priority=THUMB if kind == "thumb" else VIEW, label="seite")

    def _image_tag(self) -> str:
        return NIGHT_TAG if self.nightMode else ""

    # Kennung der Seitenbilder hinter der Dokumentkennung: »image://pdfpage/<docId><imageTag>/<Seite>/…«
    imageTag = Property(str, _image_tag, notify=nightModeChanged)

    # QML-Konstanten: Grenze eines ganzen Seitenbilds (darüber zeigt die Ansicht den sichtbaren
    # Ausschnitt zusätzlich scharf) und Breite der Miniaturen
    def _max_pixels(self) -> int:
        return MAX_PIXELS

    def _thumb_width(self) -> int:
        return THUMB_WIDTH

    def _tool_colors(self) -> list:
        return [{"value": value, "name": name} for value, name in TOOL_COLORS]

    def _font_families(self) -> list:
        return [{"value": value, "label": label} for value, label in FONT_FAMILIES]

    def _tabs_model(self) -> KeyedListModel:
        return self._tabs

    def _quick_tools(self) -> list:
        return [{"action": action, "title": title, "description": description, "icon": icon} for action, title, description, icon in QUICK_TOOLS]

    def _start_tools(self) -> list:
        return [{"action": action, "title": title, "description": description, "icon": icon} for action, title, description, icon in START_TOOLS]

    _constant = Signal()
    tabs = Property(QObject, _tabs_model, notify=_constant)  # geöffnete Dokumente (Tabs)
    maxPagePixels = Property(int, _max_pixels, notify=_constant)
    thumbWidth = Property(int, _thumb_width, notify=_constant)
    toolColors = Property(list, _tool_colors, notify=_constant)
    fontFamilies = Property(list, _font_families, notify=_constant)
    quickTools = Property(list, _quick_tools, notify=_constant)  # Schnellwerkzeuge (Reader, »Alle Werkzeuge«)
    officeTemplates = Property(list, lambda self: [dict(entry) for entry in OFFICE_TEMPLATES], notify=_constant)  # Seite »Vorlagen«
    startTools = Property(list, _start_tools, notify=_constant)  # Schnellwerkzeuge oben auf der Startseite

    # Öffnen -----------------------------------------------------------------------------------------------
    @Slot()
    def openDialog(self) -> None:  # noqa: N802
        self.openKind("")

    @Slot(str)
    def openKind(self, kind: str) -> None:  # noqa: N802
        """Dateiauswahl: alle Dateiarten (leer) oder nur eine (»text«, »tabelle«, »praesentation«, »pdf« – Startseite)."""
        titles = {"text": "Text öffnen", "tabelle": "Tabelle öffnen", "praesentation": "Präsentation öffnen", "pdf": "PDF öffnen"}
        paths = files.open_files(titles.get(kind, "Datei öffnen"), self.app.initial_dir("reader", self.source_dir), files.OPEN_FILTERS.get(kind, files.OPEN_FILTER))
        if paths:
            self.source_dir = str(Path(paths[0]).parent)
            self.app.schedule_save()
            self.open_paths(paths)

    @Slot("QVariantList")
    def openPaths(self, paths: list) -> None:  # noqa: N802
        self.open_paths([str(p) for p in paths])

    @Slot(str)
    def openRecent(self, path: str) -> None:  # noqa: N802
        if not Path(path).is_file():
            self.app.notify("reader", "warning", f"Die Datei »{Path(path).name}« gibt es nicht mehr.", title="Nicht gefunden")
            self._recent_paths = [p for p in self._recent_paths if p != path]
            self._refresh_recent()
            return
        self.open_paths([path])

    def open_external(self, paths: list[str]) -> None:
        """PDFs aus der Befehlszeile oder von einem weiteren Start (»Öffnen mit«) – nach dem Start."""
        if self.app.ready:
            self.open_paths(paths)
        else:
            self._external.extend(paths)
            self._preload()  # die PDF-Engine lädt schon, während das erste Bild entsteht

    def _ready(self, ready: bool) -> None:
        if not ready:
            return
        waiting, self._external = self._external, []
        if waiting:
            self.open_paths(waiting)
        # Erst die Frage nach ungesicherten Bearbeitungen (Absturz), danach – mit der Einstellung – die PDFs der letzten
        # Sitzung: ein wiederhergestelltes Dokument öffnet sich so nicht ein zweites Mal
        self.offer_recovery(then=self._restore_session)
        # Sicherungskopien vor dem Überschreiben: älter als 7 Tage entfernen (je Datei bleiben höchstens 3)
        self.engine.submit(lambda: recovery.cleanup_backups(recovery.backups_dir()), None, lambda _exc, _details: None, priority=BACKGROUND, label="aufräumen")

    def _pages_loaded(self, loaded: bool) -> None:
        if loaded:
            self._preload()

    def _preload(self) -> None:
        """PDF-Engine im Arbeitsthread vorab laden (einmal) – das erste Öffnen wartet dann nicht darauf."""
        if not self._preloaded:
            self._preloaded = True
            self.engine.submit(_preload_engine, None, lambda _exc, _details: None, priority=BACKGROUND, label="vorladen")

    def open_paths(self, paths: list[str], then: Callable[[DocumentController | None], None] | None = None) -> None:
        """PDFs öffnen (je Datei ein Tab; schon geöffnete werden aktiv). ``then(Dokument)``: sobald das jeweilige
        Dokument geöffnet und aktiv ist – ``then(None)``, wenn es sich nicht öffnen ließ."""
        images = [p for p in paths if imagepdf.is_image(p)]
        documents = [p for p in paths if p not in images and office.kind_of(p) is not None]
        pdfs = [p for p in paths if p not in images and p not in documents and (p.lower().endswith(".pdf") or _looks_like_pdf(p))]
        if images:
            # Bilder (Ziehen, »Senden an« im Explorer): zu einer PDF zusammenfügen
            self.images_to_pdf(images)
            if not pdfs and not documents:
                return
        # Tabellen (seit 5.0 Beta 2): zum Bearbeiten im eigenen Tab, sobald LibreOffice da ist
        sheets = [p for p in documents if self.edits_sheet(p)]
        # Texte (seit 5.0 Beta 3) ebenso
        texts = [p for p in documents if self.edits_text(p) or self.edits_slides(p)]
        documents = [p for p in documents if p not in sheets and p not in texts]
        missing = [p for p in documents if not office.installed(office.kind_of(p) or "word")]
        if missing:
            # Ohne LibreOffice nur mit Microsoft Office – je Art (Word, Excel, PowerPoint) einzeln geprüft
            self.app.notify("reader", "warning", office.missing_text(office.kind_of(missing[0]) or "word"), title="Office-Datei ansehen")
            documents = [p for p in documents if p not in missing]
        # Word, Excel, PowerPoint (seit 5.0): eine Ansicht als PDF in einem eigenen Tab – in der Reihenfolge der Auswahl
        pdfs = [p for p in paths if p in pdfs or p in documents or p in sheets or p in texts]
        if not pdfs:
            if not documents and not images and not missing:
                self.app.notify("reader", "warning", "Bitte eine PDF- oder Office-Datei wählen.", title="Nicht geöffnet")
            if then is not None:
                then(None)
            return
        # Mit geöffneten Dokumenten sofort zum Reader – sonst erst, wenn das Dokument da ist (kein leerer Reader)
        if self.app.currentPage != "reader" and self._docs:
            self.app.navigate(READER.key)
        for path in pdfs:
            existing = next((doc for doc in self._docs.values() if _shows(doc, path)), None)
            if existing is not None:
                self.activate(existing.ident)
                if then is not None:
                    then(existing)
                continue
            if then is None and any(_same(opening, path) for opening in self._opening_paths):
                continue  # wird schon geöffnet (z. B. Doppelklick zweimal kurz hintereinander)
            if len(self._docs) >= TAB_LIMIT:
                self.app.notify("reader", "warning", f"Höchstens {TAB_LIMIT} Dokumente gleichzeitig – bitte erst ein Dokument schließen.", title="Zu viele Dokumente")
                return
            if path in sheets:
                self._open_sheet(path, then=then)
            elif path in texts:
                self._open_text(path, then=then, kind="praesentation" if self.edits_slides(path) else "text")
            else:
                self._open(path, None, then=then)

    # Tabellen bearbeiten (seit 5.0 Beta 2) ----------------------------------------------------------------------
    def edits_sheet(self, path: str) -> bool:
        """Excel-, OpenDocument- und CSV-Dateien öffnen sich zum Bearbeiten (mit dem mitgelieferten LibreOffice)."""
        return Path(path).suffix.lower() in SHEET_SUFFIXES and office.libreoffice() is not None

    def edits_text(self, path: str) -> bool:
        """Word-, OpenDocument- und RTF-Texte öffnen sich zum Bearbeiten (mit dem mitgelieferten LibreOffice)."""
        return Path(path).suffix.lower() in TEXT_SUFFIXES and office.libreoffice() is not None

    def edits_slides(self, path: str) -> bool:
        """PowerPoint- und OpenDocument-Präsentationen öffnen sich zum Bearbeiten (mit dem mitgelieferten LibreOffice)."""
        return Path(path).suffix.lower() in SLIDE_SUFFIXES and office.libreoffice() is not None

    def edits_office(self, path: str) -> bool:
        return self.edits_sheet(path) or self.edits_text(path) or self.edits_slides(path)

    def text_service(self):
        """Textkern (startet beim ersten Befehl)."""
        if self._text is None:
            from ..text.service import TextService

            self._text = TextService(self.app, self)
            self._text.startingChanged.connect(self._text_starting)
        return self._text

    def _text_starting(self, starting: bool) -> None:
        if starting:
            self.app.set_status("Texte werden vorbereitet …", "busy")

    @Slot()
    def newText(self) -> None:  # noqa: N802
        """Neuer, leerer Text (Startseite »Neuer Text«)."""
        if office.libreoffice() is None:
            self.app.notify("reader", "warning", "Für Texte fehlt der Office-Teil von Novadesk. Bitte Novadesk neu installieren.", title="Neuer Text")
            return
        if len(self._docs) >= TAB_LIMIT:
            self.app.notify("reader", "warning", f"Höchstens {TAB_LIMIT} Dokumente gleichzeitig – bitte erst ein Dokument schließen.", title="Zu viele Dokumente")
            return
        self._texts_made += 1
        self._open_text("", name=f"Dokument{self._texts_made}.docx")

    @Slot()
    def newSlides(self) -> None:  # noqa: N802
        """Neue, leere Präsentation (Startseite »Neue Präsentation«, seit 5.0 Beta 4)."""
        if office.libreoffice() is None:
            self.app.notify("reader", "warning", "Für Präsentationen fehlt der Office-Teil von Novadesk. Bitte Novadesk neu installieren.", title="Neue Präsentation")
            return
        if len(self._docs) >= TAB_LIMIT:
            self.app.notify("reader", "warning", f"Höchstens {TAB_LIMIT} Dokumente gleichzeitig – bitte erst ein Dokument schließen.", title="Zu viele Dokumente")
            return
        self._slides_made += 1
        self._open_text("", name=f"Präsentation{self._slides_made}.pptx", kind="praesentation")

    def calc(self):
        """Rechenkern der Tabellen (startet beim ersten Befehl)."""
        if self._calc is None:
            from ..sheet.service import CalcService

            self._calc = CalcService(self.app, self)
            self._calc.startingChanged.connect(self._calc_starting)
        return self._calc

    def _calc_starting(self, starting: bool) -> None:
        if starting:
            self.app.set_status("Tabellen werden vorbereitet …", "busy")

    @Slot()
    def newSheet(self) -> None:  # noqa: N802
        """Neue, leere Tabelle (Startseite »Neue Tabelle«, Strg+N)."""
        if office.libreoffice() is None:
            self.app.notify("reader", "warning", "Für Tabellen fehlt der Office-Teil von Novadesk. Bitte Novadesk neu installieren.", title="Neue Tabelle")
            return
        if len(self._docs) >= TAB_LIMIT:
            self.app.notify("reader", "warning", f"Höchstens {TAB_LIMIT} Dokumente gleichzeitig – bitte erst ein Dokument schließen.", title="Zu viele Dokumente")
            return
        self._sheets_made += 1
        self._open_sheet("", name=f"Mappe{self._sheets_made}.xlsx")

    @Slot(str)
    def newFromTemplate(self, key: str) -> None:  # noqa: N802
        """Neues Dokument aus einer Vorlage (Seite »Vorlagen«, seit 5.0 Beta 6): öffnet sich wie neu und noch nicht
        gespeichert, z. B. »Rechnung1.xlsx«; Speichern fragt nach Ort und Namen."""
        entry = next((entry for entry in OFFICE_TEMPLATES if entry["key"] == key), None)
        if entry is None:
            return
        source = TEMPLATE_DIR / entry["file"]
        if office.libreoffice() is None or not source.is_file():
            self.app.notify("reader", "warning", "Für Vorlagen fehlt der Office-Teil von Novadesk. Bitte Novadesk neu installieren.", title=entry["title"])
            return
        if len(self._docs) >= TAB_LIMIT:
            self.app.notify("reader", "warning", f"Höchstens {TAB_LIMIT} Dokumente gleichzeitig – bitte erst ein Dokument schließen.", title="Zu viele Dokumente")
            return
        number = self._templates_made.get(key, 0) + 1
        self._templates_made[key] = number
        name = f"{entry['name']}{number}{entry['suffix']}"
        if entry["kind"] == "tabelle":
            self._open_sheet(str(source), name=name, untitled=True, changed=False)
        else:
            self._open_text(str(source), name=name, kind=entry["kind"], untitled=True, changed=False)

    @Slot(str)
    def newOffice(self, kind: str) -> None:  # noqa: N802
        """»Neuer Text« bzw. »Neue Präsentation«: beide öffnen sich neu und leer in Novadesk (Texte seit Beta 3,
        Präsentationen seit Beta 4)."""
        if kind == "text":
            self.newText()
        elif kind == "praesentation":
            self.newSlides()

    def open_in_program(self, path: str) -> None:
        """Datei im Standardprogramm öffnen – ist das Novadesk selbst, »Öffnen mit« (sonst öffnete sie sich hier)."""
        program = PureWindowsPath(winsys.default_program(path)).name.lower()
        if program in ("pdf-tool.exe", "pythonw.exe", "python.exe"):
            try:
                winsys.open_with(path)
            except OSError as exc:
                self.app.notify("reader", "error", str(exc) or "Kein Programm zum Öffnen gefunden.", title="Nicht geöffnet")
            return
        self.openExternal(path)

    def _open_text(self, path: str, *, then: Callable | None = None, background: bool = False, name: str = "",
                   password: str | None = None, kind: str = "text", untitled: bool = False, changed: bool = True) -> None:
        self._open_sheet(path, then=then, background=background, name=name, password=password, text=True, kind=kind,
                         untitled=untitled, changed=changed)

    def open_text_copy(self, path: str, name: str, then: Callable | None = None) -> None:
        """Text aus einer vorbereiteten Datei als neues, noch nicht gespeichertes Dokument öffnen (Serienbrief): Speichern
        fragt nach Ort und Namen, die Datei selbst kommt nicht in »Zuletzt verwendet«."""
        if len(self._docs) >= TAB_LIMIT:
            self.app.notify("reader", "warning", f"Höchstens {TAB_LIMIT} Dokumente gleichzeitig – bitte erst ein Dokument schließen.", title="Zu viele Dokumente")
            if then is not None:
                then(None)
            return
        self._open_text(path, name=name, then=then, untitled=True)

    def _open_sheet(self, path: str, *, then: Callable | None = None, background: bool = False, name: str = "",
                    password: str | None = None, text: bool = False, kind: str = "text", untitled: bool = False,
                    changed: bool = True) -> None:
        """Tabelle (bzw. mit ``text`` einen Text oder eine Präsentation) zum Bearbeiten in einem eigenen Tab öffnen;
        ``path`` leer: neu. ``untitled``: aus ``path`` laden, aber als neues Dokument mit dem Namen ``name`` (mit
        ``changed`` als geändert – eine Vorlage, die niemand ändert, fragt beim Schließen nicht)."""
        from ..sheet.document import SheetController
        from ..text.document import TextController
        from ..text.slides import SlidesController

        if path and password is None and office.encrypted(Path(path)):
            if background:
                if then is not None:
                    then(None)
                return
            password = self.ask_password(Path(path).name, False)
            if password is None:
                self.app.set_status("Öffnen abgebrochen.", "neutral")
                if then is not None:
                    then(None)
                return
        self._ids += 1
        ident = f"d{self._ids}"
        if text:
            editor = SlidesController if kind == "praesentation" else TextController
            controller = editor(self, self.text_service(), ident, self)
        else:
            controller = SheetController(self, self.calc(), ident, self)
        controller.name = name or Path(path).name
        self.opening = self.opening + 1
        if path:
            self._opening_paths.append(path)
        self.app.set_status(f"Wird geöffnet: {controller.name} …", "busy")

        def done() -> None:
            self.opening = max(0, self.opening - 1)
            self._forget_opening(path)
            if untitled:
                controller.path, controller.name, controller.dirty = "", name, changed
            self._docs[ident] = controller
            controller.panels = {"left": "", "right": "", "organize": False}
            self.tabs.set_items([*self.tabs.items(), self._tab_item(controller)])
            if not background or self._current is None:
                self.activate(ident)
            if not background and self.app.currentPage != "reader":
                self.app.navigate(READER.key)
            if path and not untitled:
                self.remember_recent(path)
            if text:
                self.app.set_status(f"Geöffnet: {controller.name}", "success")
            else:
                count = len(controller.sheets)
                self.app.set_status(f"Geöffnet: {controller.name} – {count} {'Blatt' if count == 1 else 'Blätter'}", "success")
            if then is not None:
                then(controller)

        def failed(exc: BaseException) -> None:
            from tools.sheet.engine import CalcError
            from tools.text.engine import TextError

            self.opening = max(0, self.opening - 1)
            self._forget_opening(path)
            controller.shutdown()
            controller.deleteLater()
            try:
                if then is not None:
                    then(None)
                if background:
                    _log().info("Letzte Sitzung: eine Tabelle ließ sich nicht öffnen (%s)", type(exc).__name__)
                    return
                if isinstance(exc, (CalcError, TextError)) and exc.code == "kennwort" and path:
                    secret = self.ask_password(Path(path).name, True)
                    if secret is not None:
                        self._open_sheet(path, then=None, password=secret, text=text, kind=kind)
                    return
                message = str(exc) if isinstance(exc, (CalcError, TextError)) else f"»{controller.name}« konnte nicht geöffnet werden."
                self.app.notify("reader", "error", message, title="Öffnen nicht möglich")
                self.app.set_status("Nicht geöffnet.", "neutral")
            finally:
                self._leave_if_empty()

        controller.open(path, done, failed, password)

    def _open(self, path: str, password: str | None, recovered: recovery.SessionInfo | None = None, *,
              then: Callable[[DocumentController | None], None] | None = None, background: bool = False,
              converted: bytes | None = None) -> None:
        """Dokument im Arbeitsthread öffnen. ``then`` wie bei ``open_paths``. ``background`` (letzte Sitzung): als Tab
        dazu, ohne den aktiven Tab oder die Seite zu wechseln und ohne Rückfragen (Passwort, beschädigt) – was sich
        so nicht öffnen lässt, entfällt."""
        viewing = recovered is None and office.kind_of(path) is not None
        if viewing and converted is None:
            # Office-Datei: erst in einem eigenen Thread umwandeln (LibreOffice braucht Sekunden) – die PDF-Engine
            # rendert derweil die offenen Dokumente weiter; danach öffnet sie nur noch die fertige PDF
            from .session import office_pdf

            self.opening = self.opening + 1
            self._opening_paths.append(path)
            self.app.set_status(f"Wird zum Ansehen vorbereitet: {Path(path).name} …", "busy")

            def converted_ok(data: bytes) -> None:
                self.opening = max(0, self.opening - 1)
                self._forget_opening(path)
                self._next_conversion()
                self._open(path, None, then=then, background=background, converted=data)

            def converted_failed(exc: BaseException, details: str) -> None:
                self.opening = max(0, self.opening - 1)
                self._forget_opening(path)
                self._next_conversion()
                if then is not None:
                    then(None)
                if background:
                    _log().info("Letzte Sitzung: eine Office-Datei ließ sich nicht umwandeln (%s)", type(exc).__name__)
                else:
                    if not isinstance(exc, (EditorError, OSError)):
                        self.app.report_exception(details)
                    message = str(exc) if isinstance(exc, EditorError) else f"»{Path(path).name}« ließ sich nicht zum Ansehen umwandeln."
                    self.app.notify("reader", "error", message, title="Office-Datei ansehen")
                    self.app.set_status("Nicht geöffnet.", "neutral")
                self._leave_if_empty()

            # nacheinander in der Reihenfolge der Auswahl – so entstehen die Tabs auch in dieser Reihenfolge
            self._conversions.append(lambda: self.app.worker.run(lambda: office_pdf(path), converted_ok, converted_failed))
            if len(self._conversions) == 1:
                self._conversions[0]()
            return
        self._ids += 1
        ident = f"d{self._ids}"
        controller = DocumentController(self, self.engine, ident, self)
        self.opening = self.opening + 1
        self._opening_paths.append(path)
        name = recovered.name if recovered is not None else Path(path).name
        self.app.set_status(f"Wird geöffnet: {name} …", "busy")

        def work():
            from .session import Session  # PDF-Engine (pikepdf, PDFium) erst beim ersten Öffnen – im Arbeitsthread

            if recovered is not None:
                session = Session.from_recovery(ident, recovered, password)
            elif viewing:
                session = Session.from_office(ident, path, converted)  # Ansicht einer Office-Datei (schon umgewandelt)
            else:
                session = Session.open(ident, path, password)
            controller.session = session
            return session.state()

        def done(state) -> None:
            self.opening = max(0, self.opening - 1)
            self._forget_opening(path)
            self._docs[ident] = controller
            # Zuletzt verwendete Ansicht vorher merken: apply_state passt die Seitenbreite ein und meldet diese
            # Ansicht als zuletzt verwendet – sonst ginge die gemerkte verloren
            remembered = dict(self._view)
            controller.apply_state(state)
            # Ansicht und linke Seitenleiste: zuletzt verwendet (Standard) oder die Vorgabe der Einstellungen
            settings = self.app.settings
            view = settings.reader_start_view(remembered) if settings is not None else remembered
            fit = view["fit"]
            controller.viewMode = view["mode"] if view["mode"] in ("continuous", "single", "two", "continuousTwo") else "continuous"
            if fit:
                controller.fit = fit
            else:
                controller.fit = ""
                controller.setZoom(view["zoom"])
            left = settings.reader_start_panel(self.leftPanel) if settings is not None else self.leftPanel
            if not background:
                self.leftPanel = left  # im Hintergrund geöffnet: die Leisten des sichtbaren Tabs bleiben
            controller.opening_notice()
            controller.load_outline()
            controller.loadAnnotations()
            controller.loadFields()
            controller.loadAttachments()
            controller.check_scanned()
            self.watch_clipboard()
            self.probe_ocr()
            # Seitenleisten wie im bisher aktiven Tab (bzw. wie zuletzt verwendet)
            controller.panels = {"left": left, "right": self.rightPanel, "organize": False}
            self.tabs.set_items([*self.tabs.items(), self._tab_item(controller)])
            if not background or self._current is None:
                self.activate(ident)
            if not background and self.app.currentPage != "reader":
                self.app.navigate(READER.key)
            if recovered is None:
                self.remember_recent(path)
            else:
                # Sofort neu sichern: die neue Sitzung gehört diesem Prozess, die alte wird entfernt –
                # so bietet ein weiterer Start dieselbe Sitzung nicht noch einmal an
                controller.write_recovery_now()
            self.app.set_status(f"Geöffnet: {controller.name} – {controller.pageCount} {'Seite' if controller.pageCount == 1 else 'Seiten'}", "success")
            if then is not None:
                then(controller)

        def failed(exc: BaseException, _details: str) -> None:
            self.opening = max(0, self.opening - 1)
            self._forget_opening(path)
            controller.deleteLater()
            try:
                if background:
                    # Letzte Sitzung: keine Rückfragen beim Start – das Dokument bleibt zu (ohne Pfad im Protokoll)
                    _log().info("Letzte Sitzung: ein Dokument ließ sich nicht öffnen (%s)", type(exc).__name__)
                    if then is not None:
                        then(None)
                    return
                if isinstance(exc, PasswordRequired):
                    secret = self.ask_password(name, exc.wrong)
                    if secret is not None:
                        self._open(path, secret, recovered, then=then)
                    else:
                        self.app.set_status("Öffnen abgebrochen.", "neutral")
                        if then is not None:
                            then(None)
                    return
                if then is not None:
                    then(None)
                if viewing:
                    # Die umgewandelte PDF ließ sich nicht öffnen: kein »PDF reparieren« für eine Office-Datei
                    if not isinstance(exc, (EditorError, OSError)):
                        self.app.report_exception(_details)
                    self.app.notify("reader", "error", f"»{name}« ließ sich nicht zum Ansehen öffnen.", title="Office-Datei ansehen")
                    return
                if isinstance(exc, DamagedDocument):
                    self._offer_repair(path)
                    return
                if isinstance(exc, NotAPdf):
                    self.app.notify("reader", "error", f"»{name}« ist keine PDF-Datei.", title="Öffnen nicht möglich")
                    return
                message = str(exc) if isinstance(exc, EditorError) else f"»{name}« konnte nicht geöffnet werden."
                if not isinstance(exc, (EditorError, OSError)):
                    self.app.report_exception(_details)
                self.app.notify("reader", "error", message, title="Öffnen nicht möglich")
            finally:
                self._leave_if_empty()

        self.engine.submit(work, done, failed, label="öffnen")

    def _next_conversion(self) -> None:
        """Eine Umwandlung ist fertig: die nächste wartende starten."""
        if self._conversions:
            self._conversions.pop(0)
        if self._conversions:
            self._conversions[0]()

    def _forget_opening(self, path: str) -> None:
        if path in self._opening_paths:
            self._opening_paths.remove(path)

    def _offer_repair(self, path: str) -> None:
        name = Path(path).name
        answer, _data = self.app.dialogs.ask(
            "confirm", "Dieses Dokument scheint beschädigt zu sein.",
            f"»{name}« lässt sich nicht öffnen. »PDF reparieren« kann lesbare Inhalte in eine neue Datei übertragen – das Original bleibt unverändert. Danach lässt sich die reparierte Datei hier öffnen.",
            primary="Mit »PDF reparieren« öffnen", close="Abbrechen",
        )
        if answer == "primary":
            repair = getattr(self.app, "repair_tool", None)
            self.app.navigate("repair")
            if repair is not None:
                repair.drop([path], "repair")

    def ask_password(self, name: str, wrong: bool) -> str | None:
        answer, data = self.app.dialogs.ask(
            "password", "Passwort erforderlich",
            ("Das Passwort ist falsch. " if wrong else "") + f"»{name}« ist mit einem Passwort geschützt.",
            primary="Öffnen", close="Abbrechen", data={"label": "Passwort"},
        )
        if answer != "primary":
            return None
        return str(data.get("value") or "")

    # Tabs ---------------------------------------------------------------------------------------------------
    def _tab_item(self, controller: DocumentController) -> dict:
        if getattr(controller, "isText", False):
            return {"key": controller.ident, "name": controller.name, "dirty": controller.dirty, "path": controller.path,
                    "tip": controller.path or controller.name, "kind": getattr(controller, "KIND", "text")}
        if getattr(controller, "isSheet", False):
            kind = office.symbol(Path(controller.path)) if controller.path else "tabelle"
            return {"key": controller.ident, "name": controller.name, "dirty": controller.dirty, "path": controller.path,
                    "tip": controller.path or controller.name, "kind": kind or "tabelle"}
        if controller.sourcePath:
            # Ansicht einer Office-Datei: Name, Symbol und Farbe der Office-Datei
            source = Path(controller.sourcePath)
            return {"key": controller.ident, "name": source.name, "dirty": controller.dirty, "path": "", "tip": f"{controller.sourcePath} (Ansicht als PDF)", "kind": office.symbol(source)}
        return {"key": controller.ident, "name": controller.name, "dirty": controller.dirty, "path": controller.path, "tip": controller.path or controller.name, "kind": "pdf"}

    def tab_changed(self, controller: DocumentController) -> None:
        if controller.ident in self._docs:
            self.tabs.update_item(controller.ident, **self._tab_item(controller))

    @Slot(str)
    def activate(self, key: str) -> None:
        controller = self._docs.get(key)
        if controller is None or controller is self._current:
            return
        self._remember_panels()
        previous = self._current
        self._current = controller
        # Seitenleisten und »Seiten organisieren« des Tabs (Tabs beeinflussen sich nicht gegenseitig)
        panels = controller.panels or {}
        self.leftPanel = panels.get("left", self.leftPanel)
        self.rightPanel = panels.get("right", self.rightPanel)
        self.organize = bool(panels.get("organize", False))
        self.currentKey = key
        self.hasDocument = True
        self.currentChanged.emit()
        # Geteilte Ansicht: das Dokument rechts wird angeklickt → die beiden tauschen; ein eben für die geteilte
        # Ansicht geöffnetes PDF kommt neben das bisherige
        if _office(controller) or _office(previous):
            # Tabellen und Texte stehen nie in der geteilten Ansicht
            if self.splitKey and (_office(controller) or key == self.splitKey):
                self.splitKey = ""
        elif previous is not None and previous.ident in self._docs:
            if key == self.splitKey or self._split_pending:
                self.splitKey = previous.ident
        self._split_pending = False
        if self._compare_pending and self._compare_pending in self._docs and self._compare_pending != key:
            newer = self._docs[self._compare_pending]
            self._compare_pending = ""
            self.splitKey = newer.ident
            self.start_compare(controller, newer)

    # Geteilte Ansicht ---------------------------------------------------------------------------------------
    @Slot()
    def toggleSplit(self) -> None:  # noqa: N802
        """Zwei PDFs nebeneinander: rechts ein anderes geöffnetes PDF (das zuletzt benutzte), sonst eines zum
        Öffnen wählen. Noch einmal: wieder nur das aktuelle."""
        if self.splitKey:
            self.splitKey = ""
            if self.compareActive:
                self.endCompare()
            return
        if not self.hasDocument:
            return
        if self._current is not None and _office(self._current):
            return
        others = [key for key in self.tabs.keys() if key != self.currentKey and not _office(self._docs.get(key))]
        if others:
            self.splitKey = others[-1]
            return
        self.openSplitDialog()

    @Slot()
    def openSplitDialog(self) -> None:  # noqa: N802
        """Ein PDF wählen, das rechts neben dem aktuellen erscheint."""
        paths = files.open_files("PDF für die geteilte Ansicht öffnen", self.app.initial_dir("reader", self.source_dir), files.PDF_FILTER)
        if paths:
            self.open_beside(paths[0])

    def open_beside(self, path: str) -> None:
        existing = next((doc for doc in self._docs.values() if _shows(doc, path)), None)
        if existing is not None:
            if existing is not self._current:
                self.splitKey = existing.ident
            return
        self._split_pending = self._current is not None

        def opened(controller: DocumentController | None) -> None:
            if controller is None:
                self._split_pending = False  # nicht geöffnet (beschädigt, Passwort abgebrochen): kein späterer Tab rückt daneben

        self.open_paths([str(path)], then=opened)

    # Vergleichen ----------------------------------------------------------------------------------------------
    def compare_with(self, newer: DocumentController) -> None:
        """»Mit anderer Fassung vergleichen«: die ältere Fassung wählen; sie erscheint links, ``newer`` rechts, die
        Unterschiede sind in beiden markiert und rechts als Liste."""
        paths = files.open_files("Ältere Fassung zum Vergleichen wählen", self.app.initial_dir("reader", self.source_dir), files.PDF_FILTER)
        if paths:
            self.compare_paths(newer, paths[0])

    def compare_paths(self, newer: DocumentController, path: str) -> None:
        if newer.path and _same(newer.path, path):
            self.app.notify("reader", "info", "Bitte eine andere Datei wählen – ein PDF mit sich selbst zu vergleichen zeigt keine Unterschiede.", title="Gleiche Datei")
            return
        existing = next((doc for doc in self._docs.values() if _shows(doc, path)), None)
        if existing is not None:
            self.activate(existing.ident)
            self.splitKey = newer.ident
            self.start_compare(existing, newer)
            return
        self._compare_pending = newer.ident
        ident = newer.ident

        def opened(controller: DocumentController | None) -> None:
            if controller is None and self._compare_pending == ident:
                self._compare_pending = ""  # nicht geöffnet: sonst startet ein späterer Tabwechsel den Vergleich

        self.open_paths([str(path)], then=opened)

    def start_compare(self, older: DocumentController, newer: DocumentController) -> None:
        self.end_compare()
        self._compare_serial += 1
        serial = self._compare_serial
        self._compare = (older, newer, None)
        self.compareActive = True
        self.compareRunning = True
        self.compareSummary = "Vergleich läuft …"
        self.compareNames = [older.name, newer.name]
        self.showRightPanel("compare")
        found: dict = {}

        def cancelled() -> bool:
            return serial != self._compare_serial

        def got(which: str, payload) -> None:
            if cancelled():
                return
            found[which] = payload
            if len(found) == 2:
                (old_words, old_empty), (new_words, new_empty) = found["old"], found["new"]
                self.engine.submit(lambda: comparing.compare(old_words, new_words, old_empty, new_empty, cancelled), lambda result: self._compare_done(serial, result), lambda exc, details: self._compare_failed(serial, exc, details), priority=BACKGROUND, label="vergleichen")

        def failed(exc: BaseException) -> None:
            self._compare_failed(serial, exc, "")

        older.run(lambda session: session.compare_words(cancelled), lambda payload: got("old", payload), refresh=False, failed=failed, priority=BACKGROUND)
        newer.run(lambda session: session.compare_words(cancelled), lambda payload: got("new", payload), refresh=False, failed=failed, priority=BACKGROUND)

    def _compare_failed(self, serial: int, exc: BaseException, details: str) -> None:
        if serial != self._compare_serial:
            return
        _log().warning("Vergleich fehlgeschlagen: %s %s", type(exc).__name__, details)
        self.compareRunning = False
        self.compareSummary = "Der Vergleich ist fehlgeschlagen. Bitte beide PDFs prüfen (beschädigt oder kennwortgeschützt?)."

    def _compare_done(self, serial: int, result) -> None:
        if serial != self._compare_serial or self._compare is None:
            return
        older, newer, _ = self._compare
        self._compare = (older, newer, result)
        self.compareRunning = False
        self.compareSummary = comparing.summary(result)
        codes = {"changed": 0, "added": 1, "removed": 2}
        marks: dict[str, dict[str, list]] = {"old": {}, "new": {}}
        items = []
        for number, change in enumerate(result.changes):
            for side, places in (("old", change.old), ("new", change.new)):
                for page, rects in places.items():
                    marks[side].setdefault(str(page), []).extend([round(value, 2) for value in rect] + [codes[change.kind]] for rect in rects)
            items.append({"key": str(number), "kind": change.kind, "before": change.before, "after": change.after, "oldPage": change.old_at[0], "newPage": change.new_at[0]})
        older.compareRects = marks["old"]
        newer.compareRects = marks["new"]
        self.compareItems = items
        if items:
            self.showCompare(0)

    @Slot(int)
    def showCompare(self, index: int) -> None:  # noqa: N802
        """Änderung ``index`` in beiden Fassungen zeigen und hervorheben."""
        if self._compare is None or self._compare[2] is None or not self._compare[2].changes:
            return
        older, newer, result = self._compare
        index %= len(result.changes)
        change = result.changes[index]
        self.compareIndex = index
        for doc, places, at in ((older, change.old, change.old_at), (newer, change.new, change.new_at)):
            if doc not in self._docs.values():
                continue
            page = at[0]
            doc.currentCompare = {"page": page, "rects": [list(rect) for rect in places.get(page, [])]} if page >= 0 else {}
            if page >= 0:
                doc.currentPage = page
                doc.reveal(page, at[1], at[2])

    @Slot()
    def nextCompare(self) -> None:  # noqa: N802
        self.showCompare(self.compareIndex + 1)

    @Slot()
    def previousCompare(self) -> None:  # noqa: N802
        self.showCompare(self.compareIndex - 1 if self.compareIndex > 0 else len(self.compareItems) - 1)

    @Slot()
    def recompare(self) -> None:
        if self._compare is not None:
            older, newer, _ = self._compare
            if older in self._docs.values() and newer in self._docs.values():
                self.start_compare(older, newer)

    @Slot()
    def endCompare(self) -> None:  # noqa: N802
        self.end_compare()
        if self.rightPanel == "compare":
            self.rightPanel = ""
            self._remember_panels()

    def end_compare(self) -> None:
        self._compare_serial += 1
        if self._compare is not None:
            for doc in self._compare[:2]:
                if doc in self._docs.values():
                    doc.compareRects = {}
                    doc.currentCompare = {}
        self._compare = None
        self.compareActive = False
        self.compareRunning = False
        self.compareSummary = ""
        self.compareItems = []
        self.compareIndex = -1
        self.compareNames = []

    @Slot(str)
    def setSplit(self, key: str) -> None:  # noqa: N802
        if key in self._docs and key != self.currentKey and not _office(self._docs[key]):
            self.splitKey = key

    @Slot()
    def swapSplit(self) -> None:  # noqa: N802
        if self.splitKey in self._docs:
            self.activate(self.splitKey)

    def _remember_panels(self) -> None:
        if self._current is not None:
            self._current.panels = {"left": self.leftPanel, "right": self.rightPanel, "organize": self.organize}

    @Slot(str)
    def showTab(self, key: str) -> None:  # noqa: N802
        """Klick auf den Tab eines Dokuments – auch von der Startseite oder einem anderen Werkzeug aus."""
        if key in self._docs:
            self.activate(key)
            self.app.navigate(READER.key)

    def _leave_if_empty(self) -> None:
        """Ohne Dokument gibt es im Reader nichts zu sehen: zurück zur Startseite (wie das letzte Dokument einer
        Sitzung schließen) – nicht, solange noch ein Dokument geöffnet wird, und nicht beim Beenden."""
        if not self._docs and self.opening == 0 and self.app.currentPage == "reader" and not self.app.closing:
            self.app.navigate("home")

    @Slot(int)
    def activateIndex(self, offset: int) -> None:  # noqa: N802 - Strg+Tab / Strg+Umschalt+Tab
        keys = self.tabs.keys()
        if not keys:
            return
        index = keys.index(self.currentKey) if self.currentKey in keys else 0
        self.activate(keys[(index + offset) % len(keys)])

    @Slot(str, result=bool)
    def closeTab(self, key: str) -> bool:  # noqa: N802
        controller = self._docs.get(key)
        if controller is None:
            return True
        if controller.dirty:
            answer, _data = self.app.dialogs.ask(
                "confirm", f"Änderungen an »{controller.name}« speichern?",
                "Ohne Speichern gehen die Änderungen verloren.",
                primary="Speichern", secondary="Nicht speichern", close="Abbrechen",
            )
            if answer == "primary":
                controller.save(then=lambda ok, key=key: self._finish_close(key, True) if ok else None)
                return False
            if answer != "secondary":
                return False
        self._finish_close(key, True)
        return True

    @Slot()
    def closeCurrent(self) -> None:  # noqa: N802
        if self.currentKey:
            self.closeTab(self.currentKey)

    @Slot(str)
    def closeOtherTabs(self, key: str) -> None:  # noqa: N802
        """Kontextmenü eines Tabs: alle übrigen Dokumente schließen – danach ist dieses aktiv."""
        if key not in self._docs:
            return
        self._close_tabs([other for other in self.tabs.keys() if other != key])
        if key in self._docs:
            self.activate(key)

    @Slot(str)
    def closeTabsRight(self, key: str) -> None:  # noqa: N802
        """Kontextmenü eines Tabs: die Dokumente rechts davon schließen."""
        keys = self.tabs.keys()
        if key in keys:
            self._close_tabs(keys[keys.index(key) + 1:])

    def _close_tabs(self, keys: list[str]) -> bool:
        """Mehrere Tabs nacheinander schließen – je ungespeichertem Dokument die übliche Rückfrage. »Speichern«
        schließt nach dem Speichern; »Abbrechen« (oder ein abgebrochenes »Speichern unter«) hört auf."""
        for key in keys:
            controller = self._docs.get(key)
            if controller is None or self.closeTab(key):
                continue
            if controller.saving:
                continue  # wird nach dem Speichern geschlossen
            return False
        return True

    @Slot(int, int)
    def moveTab(self, source: int, target: int) -> None:  # noqa: N802
        """Dokument-Tab an eine andere Stelle ziehen – nur die Reihenfolge der Tabs ändert sich."""
        items = self.tabs.items()
        if not 0 <= source < len(items):
            return
        target = max(0, min(len(items) - 1, int(target)))
        if target == source:
            return
        items.insert(target, items.pop(source))
        self.tabs.set_items(items)

    def _remember_closed(self, controller: DocumentController) -> None:
        """Für »Geschlossenen Tab wieder öffnen«: nur Dokumente mit Pfad (gespeichert), mit der gezeigten Seite."""
        path = controller.path
        if not path:
            return
        self._closed = [entry for entry in self._closed if _key(entry["path"]) != _key(path)]
        self._closed.append({"path": path, "page": int(controller.currentPage)})
        del self._closed[:-CLOSED_LIMIT]
        self.canReopen = True

    @Slot()
    def reopenClosed(self) -> None:  # noqa: N802
        """Strg+Umschalt+T: zuletzt geschlossenes Dokument wieder öffnen – auf der Seite, die zu sehen war."""
        if not self._closed:
            return
        entry = self._closed.pop()
        self.canReopen = bool(self._closed)
        path, page = entry["path"], entry["page"]
        if not Path(path).is_file():
            self.app.notify("reader", "warning", f"Die Datei »{Path(path).name}« gibt es nicht mehr.", title="Nicht gefunden")
            return
        self.open_paths([path], then=lambda controller: controller.goTo(page) if controller is not None else None)

    def _finish_close(self, key: str, discard_recovery: bool, remember: bool = True) -> None:
        controller = self._docs.pop(key, None)
        if controller is None:
            return
        if key == self.splitKey:
            self.splitKey = ""
        if self._compare is not None and controller in self._compare[:2]:
            self.endCompare()
        if remember:
            self._remember_closed(controller)
        keys = self.tabs.keys()
        position = keys.index(key) if key in keys else 0
        self.tabs.set_items([item for item in self.tabs.items() if item["key"] != key])
        controller.shutdown(discard_recovery)
        self.cache.drop(key)
        if self._current is controller:
            remaining = self.tabs.keys()
            self._current = None
            self.currentKey = ""
            if remaining:
                self.activate(remaining[min(position, len(remaining) - 1)])
            else:
                self.hasDocument = False
                self.organize = False
                self.leaveFullScreen()
                self._leave_if_empty()
                self.currentChanged.emit()
        controller.deleteLater()

    # Zuletzt geöffnet, Ansicht ---------------------------------------------------------------------------------
    def remember_recent(self, path: str) -> None:
        path = str(path)
        self._recent_paths = [path] + [p for p in self._recent_paths if not _same(p, path)]
        del self._recent_paths[RECENT_LIMIT:]
        self._recent_opened = {p: when for p, when in self._recent_opened.items() if p in self._recent_paths}
        self._recent_opened[path] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        self._recent_stat.pop(path, None)
        self._refresh_recent()
        self.app.schedule_save()

    def _refresh_recent(self, probe: bool = True) -> None:
        """Liste »Zuletzt verwendet«: Name, Ordner, wann geöffnet, Größe. ``probe=False``: nur die Zeitangaben neu
        (»Heute« wird nach Mitternacht zu »Gestern«), ohne die Dateien erneut zu prüfen."""
        items = []
        for path in self._recent_paths:
            if probe or path not in self._recent_stat:
                self._recent_stat[path] = _file_info(path)
            exists, size = self._recent_stat[path]
            p = Path(path)
            items.append({
                "path": path, "name": p.name, "folder": str(p.parent), "place": place_text(str(p.parent)), "missing": not exists, "kind": office.symbol(p),
                "size": size_text(size) if exists else "", "opened": opened_text(self._recent_opened.get(path, "")),
            })
        self._recent_stat = {path: info for path, info in self._recent_stat.items() if path in self._recent_paths}
        self.recent = items

    @Slot()
    def clearRecent(self) -> None:  # noqa: N802
        self._recent_paths = []
        self._recent_opened = {}
        self._refresh_recent()
        self.app.schedule_save()
        self.app.set_status("Liste »Zuletzt geöffnet« geleert.", "success")

    @Slot(str)
    def showInFolder(self, path: str) -> None:  # noqa: N802
        if path and Path(path).parent.is_dir():
            self.app.open_folder_of(path, "reader")

    @Slot(str)
    def removeRecent(self, path: str) -> None:  # noqa: N802
        self._recent_paths = [p for p in self._recent_paths if p != path]
        self._recent_opened.pop(path, None)
        self._refresh_recent()
        self.app.schedule_save()

    def remember_view(self, controller: DocumentController) -> None:
        self._view = {"fit": controller.fit, "zoom": controller.zoom, "mode": controller.viewMode}
        self.app.schedule_save()

    @Slot(str)
    def setLeftPanel(self, panel: str) -> None:  # noqa: N802
        if panel not in LEFT_PANELS:
            return
        self.leftPanel = "" if panel == self.leftPanel else panel
        self._remember_panels()
        self.app.schedule_save()

    @Slot(str)
    def showLeftPanel(self, panel: str) -> None:  # noqa: N802
        """Linke Seitenleiste zeigen (ohne Umschalten): ``thumbs``, ``outline``, ``search`` oder ``attachments``."""
        if panel in LEFT_PANELS and panel and panel != self.leftPanel:
            self.leftPanel = panel
            self._remember_panels()
            self.app.schedule_save()

    @Slot(str)
    def setRightPanel(self, panel: str) -> None:  # noqa: N802
        if panel in RIGHT_PANELS:
            self.rightPanel = "" if panel == self.rightPanel else panel
            self._remember_panels()

    @Slot(str)
    def showRightPanel(self, panel: str) -> None:  # noqa: N802
        """Rechte Seitenleiste zeigen (ohne Umschalten): ``comments``, ``properties`` oder ``assistant``."""
        if panel in RIGHT_PANELS and panel:
            self.rightPanel = panel
            self._remember_panels()

    def close_right_panel(self, panel: str) -> None:
        """Eine rechte Seitenleiste in allen Tabs schließen (KI-Assistent ausgeschaltet) – auch in Tabs im Hintergrund."""
        if self.rightPanel == panel:
            self.rightPanel = ""
        for controller in self._docs.values():
            panels = controller.panels or {}
            if panels.get("right") == panel:
                controller.panels = {**panels, "right": ""}
        self._remember_panels()

    @Slot(bool)
    def setOrganize(self, value: bool) -> None:  # noqa: N802
        self.organize = bool(value) and self.hasDocument
        self._remember_panels()

    # Vollbild ----------------------------------------------------------------------------------------------
    @Slot()
    def toggleFullScreen(self) -> None:  # noqa: N802
        """F11: Vollbild mit dem Dokument (Tab-Leiste und Leisten ausgeblendet) bzw. zurück."""
        if self.fullScreen:
            self.leaveFullScreen()
            return
        window = getattr(self.app, "window", None)
        if window is None or not self.hasDocument:
            return
        self._window_before_full = window.visibility()
        self.fullScreen = True
        if not self._watching_window:
            window.visibilityChanged.connect(self._window_visibility)
            self._watching_window = True
        window.showFullScreen()

    @Slot()
    def startPresentation(self) -> None:  # noqa: N802
        """F5: Präsentation – Vollbild auf schwarzem Grund, eine ganze Seite nach der anderen (Pfeiltasten,
        Leertaste, Bild auf/ab); Esc beendet sie und stellt Ansicht und Zoom wieder her."""
        doc = self._current
        if doc is None or self.presenting or _office(doc):
            return
        self._before_presentation = (doc, doc.viewMode, doc.fit, doc.zoom, doc.tool)
        self.organize = False
        doc.setTool("select")
        doc.setViewMode("single")
        doc.fitPage()
        self.presenting = True
        if not self.fullScreen:
            self.toggleFullScreen()

    def _end_presentation(self) -> None:
        if not self.presenting:
            return
        self.presenting = False
        before, self._before_presentation = self._before_presentation, None
        if before is None:
            return
        doc, mode, fit, zoom, tool = before
        if doc not in self._docs.values():
            return  # inzwischen geschlossen
        doc.setViewMode(mode)
        if fit == "width":
            doc.fitWidth()
        elif fit == "page":
            doc.fitPage()
        else:
            doc.setZoom(zoom)
        doc.setTool(tool)

    @Slot()
    def leaveFullScreen(self) -> None:  # noqa: N802
        self._end_presentation()
        if not self.fullScreen:
            return
        self.fullScreen = False
        window = getattr(self.app, "window", None)
        if window is None:
            return
        from PySide6.QtGui import QWindow

        before, self._window_before_full = self._window_before_full, None
        if before == QWindow.Visibility.Maximized:
            window.showMaximized()
        else:
            window.showNormal()

    def _window_visibility(self, visibility) -> None:
        """Vollbild außerhalb der App beendet (z. B. Fenster minimiert): Zustand nachziehen."""
        from PySide6.QtGui import QWindow

        if self.fullScreen and visibility not in (QWindow.Visibility.FullScreen, QWindow.Visibility.Hidden):
            self.fullScreen = False
            self._window_before_full = None
            self._end_presentation()

    def _page_changed(self, page: str) -> None:
        if page != "reader":
            self.leaveFullScreen()
        if page == "home":
            self._refresh_recent(probe=False)

    def config(self) -> dict:
        # Letzte Sitzung nur mit der Einstellung – sonst wird der Schlüssel entfernt (``None``)
        session = self._session if self._restore_wanted() else None
        return {
            "reader_zuletzt": list(self._recent_paths), "reader_zuletzt_zeit": dict(self._recent_opened), "reader_ansicht": {**self._view, "links": self.leftPanel},
            "ordner_reader": self.source_dir, "reader_ocr_sprachen": list(self._ocr_chosen), "reader_signieren": dict(self.sign_defaults) or None, NIGHT_KEY: bool(self.nightMode), SESSION_KEY: session,
            UPDATE_SESSION_KEY: True if self.restore_after_update else None,
            "reader_bilder": {"seite": self._image_options["pageSize"], "rand": self._image_options["margin"], "ordner": self._image_options["folder"]},
            "reader_scan": {
                "quelle": self._scan_options["source"], "farbe": self._scan_options["color"], "dpi": self._scan_options["dpi"],
                "ocr": self._scan_options["ocr"], "scanner": self._scan_options["scanner"], "ordner": self._scan_options["folder"],
            },
        }

    # Nachtmodus --------------------------------------------------------------------------------------------------
    @Slot(bool)
    def setNightMode(self, enabled: bool) -> None:  # noqa: N802
        """Nachtmodus: Seiten dunkelgrau mit heller Schrift – nur die Anzeige; Datei, Drucken und Export bleiben
        unverändert. Gilt für alle Tabs und bleibt nach einem Neustart."""
        enabled = bool(enabled)
        if enabled == self.nightMode:
            return
        self.nightMode = enabled
        self.app.schedule_save()
        self.app.set_status("Nachtmodus ein – nur die Anzeige ist dunkel, die Datei bleibt unverändert." if enabled else "Nachtmodus aus.", "success")

    # Schnellwerkzeuge der Startseite --------------------------------------------------------------------------------
    @Slot(str)
    def quickTool(self, action: str) -> None:  # noqa: N802
        """PDF wählen, im Tab öffnen und das Werkzeug starten, sobald das Dokument geöffnet und aktiv ist
        (»Zusammenführen«: danach die PDFs wählen, die angehängt werden)."""
        tool = next((entry for entry in (*QUICK_TOOLS, *START_TOOLS) if entry[0] == action), None)
        if tool is None:
            return
        if action == "overview":
            self.app.openTool(CONTRACTS.key)
            return
        if action == "images":
            self.imagesToPdf()
            return
        if action == "scan":
            self.scanToPdf()
            return
        if action == "office":
            self.officeToPdf()
            return
        titles = {"merge": f"{tool[1]} – erste PDF wählen", "compare": "Vergleichen – neuere Fassung wählen"}
        path = self.pick_pdf(titles.get(action, f"{tool[1]} – PDF wählen"))
        if not path:
            return
        self.source_dir = str(Path(path).parent)
        self.app.schedule_save()
        self.open_paths([path], then=lambda controller: self._start_quick(controller, action))

    def _start_quick(self, controller: DocumentController | None, action: str) -> None:
        if controller is None:
            return

        def start() -> None:
            # Inzwischen geschlossen oder ein anderer Tab aktiv: nichts starten
            if controller.ident not in self._docs or self._current is not controller or _office(controller):
                return
            if action == "merge":
                controller.mergeFiles()
            else:
                controller.runAction(action)

        # Im nächsten Durchlauf: Tab und Reader stehen, bevor ein Dialog oder Werkzeug erscheint
        self.app.timers.later(f"reader:quick:{controller.ident}", 0, start)

    # PDF aus Bildern -------------------------------------------------------------------------------------------------
    @Slot()
    def imagesToPdf(self) -> None:  # noqa: N802
        self.images_to_pdf([])

    def images_to_pdf(self, paths: list[str]) -> None:
        """Bilder wählen (oder die gezogenen bzw. aus dem Explorer gesendeten), Reihenfolge, Seitengröße und Rand
        festlegen, als neue PDF speichern und im Reader öffnen."""
        if not paths:
            paths = files.open_files("PDF aus Bildern – Bilder wählen", self.app.initial_dir("bilder", self._image_options["folder"] or self.source_dir), imagepdf.FILTER)
        images = [str(p) for p in paths if imagepdf.is_image(p)][: imagepdf.MAX_IMAGES]
        if not images:
            if paths:
                self.app.notify("reader", "warning", "Bitte Bilder wählen (JPG, PNG, TIFF, BMP, GIF oder WebP).", title="Keine Bilder")
            return
        self._image_options["folder"] = str(Path(images[0]).parent)
        answer, data = self.app.dialogs.ask(
            "images", "PDF aus Bildern", "", primary="PDF erstellen", close="Abbrechen", width=620,
            data={"files": [{"name": Path(p).name, "path": p} for p in images], "pageSize": self._image_options["pageSize"], "margin": self._image_options["margin"]},
        )
        if answer != "primary":
            return
        data = data or {}
        order = [str(p) for p in data.get("order") or [] if str(p) in images]
        if not order:
            return
        page_size = data.get("pageSize") if data.get("pageSize") in ("auto", *imagepdf.PAGE_SIZES) else "auto"
        margin = data.get("margin") if data.get("margin") in imagepdf.MARGINS else "none"
        self._image_options.update(pageSize=page_size, margin=margin)
        self.app.schedule_save()
        name = f"{Path(order[0]).stem}.pdf" if len(order) == 1 else f"{Path(order[0]).parent.name or 'Bilder'}.pdf"
        target = files.save_file("PDF aus Bildern speichern", str(Path(order[0]).parent / name), files.PDF_FILTER)
        if not target:
            return
        if not target.lower().endswith(".pdf"):
            target += ".pdf"
        if any(_same(target, p) for p in order):
            self.app.notify("reader", "warning", "Die PDF braucht einen eigenen Namen.", title="Nicht gespeichert")
            return
        self.app.set_status(f"PDF aus {len(order)} {'Bild' if len(order) == 1 else 'Bildern'} wird erstellt …", "busy")

        def done(result) -> None:
            skipped = f" Nicht lesbar und ausgelassen: {', '.join(result.skipped[:5])}{' …' if len(result.skipped) > 5 else ''}." if result.skipped else ""
            pages = f"{result.pages} {'Seite' if result.pages == 1 else 'Seiten'}."
            self.app.notify("reader", "warning" if skipped else "success", pages + skipped, title="PDF aus Bildern erstellt", auto_hide=12000)
            self.open_paths([str(result.path)])

        def failed(exc: BaseException, _details: str) -> None:
            message = str(exc) if isinstance(exc, EditorError) else "Die PDF ließ sich nicht erstellen."
            self.app.notify("reader", "error", message, title="PDF aus Bildern")

        self.engine.submit(lambda: imagepdf.create(order, target, page_size=page_size, margin=margin), done, failed, label="bilder")

    # Office in PDF -----------------------------------------------------------------------------------------------------
    @Slot()
    def officeToPdf(self) -> None:  # noqa: N802
        path = files.open_file("Office in PDF – Datei wählen", self.app.initial_dir("reader", self.source_dir), office.FILTER)
        if path:
            self.office_to_pdf(path)

    def office_to_pdf(self, path: str) -> None:
        """Word-, Excel- oder PowerPoint-Datei in eine neue PDF umwandeln (LibreOffice, sonst Microsoft Office) und öffnen."""
        kind = office.kind_of(path)
        if kind is None:
            return
        engine = office.engine(kind)
        if engine is None:
            self.app.notify("reader", "warning", office.missing_text(kind), title="Office in PDF")
            return
        target = files.save_file("PDF speichern", str(Path(path).with_suffix(".pdf")), files.PDF_FILTER)
        if not target:
            return
        if not target.lower().endswith(".pdf"):
            target += ".pdf"
        if Path(target).exists():
            # Die Dateiauswahl hat das Überschreiben bestätigt: erst nach erfolgreicher Umwandlung ersetzen
            final, target = target, str(Path(target).with_name(f".{Path(target).stem[:40]}.pdftool-office.pdf"))
            Path(target).unlink(missing_ok=True)
        else:
            final = target
        self.source_dir = str(Path(path).parent)
        self.app.set_status(f"{Path(path).name} wird mit {engine} in PDF umgewandelt …", "busy")

        def work() -> str:
            office.to_pdf(path, target)
            if final != target:
                os.replace(target, final)
            return final

        def done(result: str) -> None:
            self.app.notify("reader", "success", f"{Path(path).name} wurde in PDF umgewandelt.", title="Office in PDF", auto_hide=8000)
            self.open_paths([result])

        def failed(exc: BaseException, _details: str) -> None:
            if final != target:
                Path(target).unlink(missing_ok=True)
            message = str(exc) if isinstance(exc, EditorError) else f"{engine} konnte die Datei nicht umwandeln."
            self.app.notify("reader", "error", message, title="Office in PDF")

        self.engine.submit(work, done, failed, label="office")

    @Slot(str)
    def officeAction(self, action: str) -> None:  # noqa: N802
        """Hinweis über der Ansicht einer Office-Datei: »overview« – aus der Tabelle eine Vertragsübersicht erstellen,
        »external« – die Office-Datei im Standardprogramm öffnen (z. B. zum Bearbeiten in Word)."""
        current = self._current
        if current is None or not current.sourcePath:
            return
        if action == "overview":
            self.app.open_with_tool(CONTRACTS.key, [current.sourcePath])
        elif action == "external":
            # Ist Novadesk selbst das Standardprogramm, öffnete sich nur wieder dieser Tab: dann »Öffnen mit«
            self.open_in_program(current.sourcePath)

    @Slot(str)
    def openExternal(self, path: str) -> None:  # noqa: N802
        """Umgewandelte Datei (Word, Excel, Text) mit dem Standardprogramm öffnen."""
        try:
            files.open_path(path)
        except OSError as exc:
            self.app.notify("reader", "error", str(exc) or "Kein Programm zum Öffnen gefunden.", title="Nicht geöffnet")

    # Scannen -----------------------------------------------------------------------------------------------------------
    @Slot()
    def scanToPdf(self) -> None:  # noqa: N802
        """Vom Scanner (WIA) in eine neue PDF: Scanner, Quelle, Farbe und Auflösung wählen, Seite für Seite (Vorlagenglas)
        oder alle auf einmal (Einzug) scannen, als PDF speichern, im Reader öffnen und auf Wunsch Text erkennen."""
        if self._scanning:
            return
        self._scanning = True
        self.probe_ocr()
        self.app.set_status("Scanner werden gesucht …", "busy")

        def failed(exc: BaseException, _details: str) -> None:
            self._scanning = False
            self.app.set_status("", "neutral")
            self.app.notify("reader", "error", str(exc) if isinstance(exc, scan.ScanError) else "Die Scanner ließen sich nicht abfragen.", title="Scannen")

        self.app.worker.run(scan.scanners, self._scan_choose, failed)

    def _scan_choose(self, found: list) -> None:
        self.app.set_status("", "neutral")
        if not found:
            self._scanning = False
            self.app.notify(
                "reader", "warning",
                "Novadesk findet Scanner über die Scanner-Schnittstelle von Windows. Bitte den Scanner einschalten und verbinden; "
                "bei manchen Geräten ist dafür der Treiber des Herstellers nötig.",
                title="Kein Scanner gefunden",
            )
            return
        options = self._scan_options
        chosen = options["scanner"] if any(item.ident == options["scanner"] for item in found) else found[0].ident
        data = {
            "scanners": [{"id": item.ident, "name": item.name} for item in found], "scanner": chosen,
            "source": options["source"], "color": options["color"], "dpi": options["dpi"], "resolutions": list(scan.RESOLUTIONS),
            "ocr": options["ocr"] and self.ocrState != "fehlt", "ocrAvailable": self.ocrState != "fehlt",
        }
        answer, result = self.app.dialogs.ask("scan", "Scannen", "", primary="Scannen", data=data, width=520)
        if answer != "primary":
            self._scanning = False
            return
        result = result or {}
        ident = str(result.get("scanner") or chosen)
        if not any(item.ident == ident for item in found):
            ident = chosen
        settings = scan.Settings.of(result)
        with_ocr = bool(result.get("ocr")) and self.ocrState != "fehlt"
        options.update(scanner=ident, source=settings.source, color=settings.color, dpi=settings.dpi, ocr=with_ocr)
        self.app.schedule_save()
        folder = Path(tempfile.mkdtemp(prefix="pdf-tool-scan-"))
        self._scan_more(ident, settings, folder, [], with_ocr)

    def _scan_more(self, ident: str, settings, folder: Path, pages: list, with_ocr: bool) -> None:
        self.app.set_status(f"Seite {len(pages) + 1} wird gescannt …" if settings.source == "flatbed" else "Einzug wird gescannt …", "busy")

        def done(_new: list) -> None:
            self.app.set_status("", "neutral")
            if settings.source == "flatbed":
                count = f"{len(pages)} {'Seite' if len(pages) == 1 else 'Seiten'} gescannt"
                answer, _data = self.app.dialogs.ask(
                    "confirm", count, "Für die nächste Seite das Blatt wenden oder ein neues auflegen.",
                    primary="Nächste Seite scannen", secondary="Fertig", close="Abbrechen", default="secondary",
                )
                if answer == "primary":
                    self._scan_more(ident, settings, folder, pages, with_ocr)
                    return
                if answer != "secondary":
                    self._scan_cancelled(folder)
                    return
            self._scan_finish(pages, folder, with_ocr)

        def failed(exc: BaseException, _details: str) -> None:
            self.app.set_status("", "neutral")
            message = str(exc) if isinstance(exc, scan.ScanError) else "Der Scan ist fehlgeschlagen."
            if not isinstance(exc, scan.ScanError):
                _log("scan").warning("Scannen fehlgeschlagen: %s", type(exc).__name__)
            if pages:
                answer, _data = self.app.dialogs.ask(
                    "confirm", "Scan fehlgeschlagen", f"{message}\n\n{len(pages)} {'Seite ist' if len(pages) == 1 else 'Seiten sind'} schon gescannt.",
                    primary="Erneut versuchen", secondary="Mit diesen Seiten fertigstellen", close="Abbrechen",
                )
                if answer == "primary":
                    self._scan_more(ident, settings, folder, pages, with_ocr)
                elif answer == "secondary":
                    self._scan_finish(pages, folder, with_ocr)
                else:
                    self._scan_cancelled(folder)
                return
            self._scan_cancelled(folder, quiet=True)
            self.app.notify("reader", "error", message, title="Scannen")

        start = len(pages)
        self.app.worker.run(lambda: scan.scan(ident, settings, folder, start=start, into=pages), done, failed)

    def _scan_cancelled(self, folder: Path, quiet: bool = False) -> None:
        self._scanning = False
        shutil.rmtree(folder, ignore_errors=True)
        if not quiet:
            self.app.set_status("Scannen abgebrochen.", "info")

    def _scan_finish(self, pages: list, folder: Path, with_ocr: bool) -> None:
        default_dir = self._scan_options["folder"] or str(Path.home() / "Documents")
        name = time.strftime("Scan %Y-%m-%d %H-%M.pdf")
        target = files.save_file("Scan speichern", str(Path(default_dir) / name), files.PDF_FILTER)
        if not target:
            self._scan_cancelled(folder)
            return
        if not target.lower().endswith(".pdf"):
            target += ".pdf"
        self._scan_options["folder"] = str(Path(target).parent)
        self.app.schedule_save()
        self.app.set_status(f"PDF aus {len(pages)} gescannten {'Seite' if len(pages) == 1 else 'Seiten'} wird erstellt …", "busy")
        languages = self.ocr_languages()

        def done(result) -> None:
            self._scanning = False
            shutil.rmtree(folder, ignore_errors=True)
            pages_text = f"{result.pages} {'Seite' if result.pages == 1 else 'Seiten'}"
            self.app.notify("reader", "success", f"{pages_text} gescannt und gespeichert." + (" Der Text wird jetzt erkannt." if with_ocr else ""), title="Scan gespeichert", auto_hide=10000)

            def recognize(controller: DocumentController | None) -> None:
                if controller is not None and with_ocr and languages and self.ocr_engine() is not None:
                    controller.start_ocr_all(languages)

            self.open_paths([str(result.path)], then=recognize)

        def failed(exc: BaseException, _details: str) -> None:
            self._scanning = False
            self.app.notify("reader", "error", str(exc) if isinstance(exc, EditorError) else "Die PDF ließ sich nicht erstellen.", title="Scannen")
            shutil.rmtree(folder, ignore_errors=True)

        self.engine.submit(lambda: imagepdf.create([str(p) for p in pages], target, page_size="auto"), done, failed, label="scan")

    # Per E-Mail senden ---------------------------------------------------------------------------------------------
    @Slot()
    def sendByMail(self) -> None:  # noqa: N802
        """Aktuelles Dokument per E-Mail senden: Das E-Mail-Programm zeigt eine neue Nachricht mit der PDF als Anhang –
        gesendet wird dort, nie von Novadesk. Ungespeicherte Änderungen: vorher speichern oder ohne sie senden; ein nie
        gespeichertes Dokument wird zuerst gespeichert."""
        controller = self._current
        if controller is None:
            return
        if _office(controller) and (not controller.path or controller.dirty):
            # Tabelle: erst speichern (ein nie gespeicherte fragt nach Name und Ort), dann die Datei senden
            controller.save(then=lambda ok: self._mail_document(controller) if ok else None)
            return
        if not controller.path:
            target = self.pick_save_pdf(controller.name or "Dokument.pdf", "Vor dem Senden speichern unter")
            if target:
                controller.save(target, then=lambda ok: self._mail_document(controller) if ok else None)
            return
        if controller.dirty:
            answer, _data = self.app.dialogs.ask(
                "confirm", f"Änderungen an »{controller.name}« vor dem Senden speichern?",
                "Gesendet wird die gespeicherte Datei. Ohne Speichern enthält die E-Mail den zuletzt gespeicherten Stand.",
                primary="Speichern und senden", secondary="Ohne Änderungen senden", close="Abbrechen",
            )
            if answer == "primary":
                controller.save(then=lambda ok: self._mail_document(controller) if ok else None)
                return
            if answer != "secondary":
                return
        self._mail_document(controller)

    def _mail_document(self, controller: DocumentController) -> None:
        if controller.path:
            mail.send_and_report(self.app, controller.path, "reader")

    # Letzte Sitzung (Einstellung »PDFs der letzten Sitzung beim Start wieder öffnen«) -------------------------------
    def _restore_wanted(self) -> bool:
        if self.restore_after_update or self._update_once:
            return True
        settings = self.app.settings
        return settings is not None and bool(getattr(settings, "readerRestoreSession", False))

    def still_opening(self) -> bool:
        """PDFs werden noch geöffnet oder warten auf den Start (»Öffnen mit«) – ein Update wartet darauf."""
        return bool(self.opening or self._external)

    def unsaved(self) -> list[str]:
        """Namen der Dokumente mit ungespeicherten Änderungen (ein automatisches Update wartet darauf)."""
        return [controller.name for controller in self._docs.values() if controller.dirty]

    def _restore_setting(self, enabled: bool) -> None:
        if not enabled:
            self._session = None  # ausgeschaltet: die gemerkte Liste wird beim nächsten Speichern entfernt

    def _session_snapshot(self) -> dict | None:
        """Beim Beenden: geöffnete Dokumente mit Pfad (gespeichert) in der Reihenfolge der Tabs, je mit der gezeigten
        Seite, und das aktive. Ohne Dateizugriff – fehlende Dateien übergeht der nächste Start."""
        documents = []
        for key in self.tabs.keys():
            controller = self._docs.get(key)
            if controller is not None and (controller.path or controller.sourcePath):
                # Ansicht einer Office-Datei: beim nächsten Start wieder die Office-Datei (neu umgewandelt)
                documents.append({"pfad": controller.path or controller.sourcePath, "seite": int(controller.currentPage)})
        if not documents:
            return None
        current = self._docs.get(self._quit_active) or self._current
        active = (current.path or current.sourcePath) if current is not None else ""
        return {"dokumente": documents, "aktiv": active}

    def _restore_session(self, recovered: list[str] | None = None) -> None:
        """Nach dem Start: die PDFs der letzten Sitzung im Hintergrund wieder öffnen – nur vorhandene Dateien, ohne
        Rückfragen; der Start wartet nie darauf. ``recovered``: schon wiederhergestellte Dokumente (Absturz)."""
        session = self._session_pending
        wanted_now = self._restore_wanted()
        self._update_once = False  # nach dem Update nur dieses eine Mal
        if session is None or not wanted_now or self.app.closing:
            self._session_pending = None
            return
        self._session_pending = None
        self._restoring = True
        skip = {_key(path) for path in recovered or []}
        wanted = [entry for entry in session["dokumente"] if _key(entry["pfad"]) not in skip]

        def check() -> list[dict]:
            # Im Hintergrund: ein nicht erreichbares Netzlaufwerk lässt die Oberfläche nicht warten
            return [entry for entry in wanted if _file_info(entry["pfad"])[0]]

        def found(existing: list[dict]) -> None:
            if self.app.closing:
                return
            busy = {_key(doc.path or doc.sourcePath) for doc in self._docs.values() if doc.path or doc.sourcePath} | {_key(path) for path in self._opening_paths}
            entries = [entry for entry in existing if _key(entry["pfad"]) not in busy][: max(0, TAB_LIMIT - len(self._docs) - self.opening)]
            state = {"left": len(entries), "idents": [], "active": session["aktiv"], "missing": sum(1 for entry in wanted if entry not in existing and not _temporary(entry["pfad"])), "failed": 0}
            if not entries:
                self._restoring = False
                if state["missing"]:
                    self.app.set_status("Die PDFs der letzten Sitzung gibt es nicht mehr.", "warning")
                return
            for entry in entries:
                restored = lambda controller, page=entry["seite"]: self._restored(state, controller, page)  # noqa: E731
                if self.edits_sheet(entry["pfad"]):
                    self._open_sheet(entry["pfad"], then=restored, background=True)
                elif self.edits_text(entry["pfad"]):
                    self._open_text(entry["pfad"], then=restored, background=True)
                elif self.edits_slides(entry["pfad"]):
                    self._open_text(entry["pfad"], then=restored, background=True, kind="praesentation")
                else:
                    self._open(entry["pfad"], None, then=restored, background=True)

        def failed(_exc: BaseException, _details: str) -> None:
            self._restoring = False

        self.app.worker.run(check, found, failed)

    def _restored(self, state: dict, controller: DocumentController | None, page: int) -> None:
        state["left"] -= 1
        if controller is None:
            state["failed"] += 1
        else:
            state["idents"].append(controller.ident)
            controller.goTo(page)
        if state["left"] > 0 or self.app.closing:
            return
        self._restoring = False
        opened = [self._docs[ident] for ident in state["idents"] if ident in self._docs]
        # Das zuletzt aktive zeigen – nicht, wenn inzwischen ein anderes Dokument geöffnet wurde (»Öffnen mit«, von Hand)
        if opened and (self._current is None or self._current.ident in state["idents"]):
            remembered = _key(state["active"]) if state["active"] else ""
            self.activate(next((doc for doc in opened if remembered and _key(doc.path or doc.sourcePath) == remembered), opened[0]).ident)
            if self.app.currentPage == "home":
                self.app.navigate(READER.key)
        count, skipped = len(opened), state["missing"] + state["failed"]
        text = f"Letzte Sitzung: {count} {'PDF' if count == 1 else 'PDFs'} wieder geöffnet"
        if skipped:
            text += f" – {skipped} nicht (nicht mehr vorhanden oder nicht lesbar)"
        self.app.set_status(text + ".", "warning" if skipped else "success")

    # Dateiauswahl -------------------------------------------------------------------------------------------------
    def pick_pdf(self, title: str) -> str:
        return files.open_file(title, self.app.initial_dir("reader", self.source_dir), files.PDF_FILTER)

    def pick_pdfs(self, title: str) -> list[str]:
        return files.open_files(title, self.app.initial_dir("reader", self.source_dir), files.PDF_FILTER)

    def pick_file(self, title: str) -> str:
        return files.open_file(title, self.app.initial_dir("reader", self.source_dir), "Alle Dateien (*.*)")

    def pick_save_file(self, name: str, title: str) -> str:
        folder = self.app.initial_dir("reader", self.source_dir)
        suffix = Path(name).suffix.lower()
        pattern = f"{suffix[1:].upper()}-Datei (*{suffix});;Alle Dateien (*.*)" if suffix else "Alle Dateien (*.*)"
        return files.save_file(title, str(Path(folder) / name), pattern)

    def pick_image(self) -> str:
        return files.open_file("Bild wählen", self.app.initial_dir("logo", ""), "Bilder (*.png *.jpg *.jpeg);;Alle Dateien (*.*)")

    def pick_folder(self, title: str) -> str:
        return files.pick_folder(title, self.app.initial_dir("reader", self.source_dir))

    def pick_save_pdf(self, name: str, title: str) -> str:
        current = (self._current.path or self._current.sourcePath) if self._current is not None else ""
        folder = str(Path(current).parent) if current else self.app.initial_dir("reader", self.source_dir)
        target = files.save_file(title, str(Path(folder) / name), files.PDF_FILTER)
        if target and not target.lower().endswith(".pdf"):
            target += ".pdf"
        return target

    # Absturz: ungespeicherte Bearbeitungen ------------------------------------------------------------------
    def offer_recovery(self, then: Callable[[list[str]], None] | None = None) -> None:
        """Nach dem Start: verwaiste Sitzungen (Absturz) zum Wiederherstellen anbieten. ``then(Originale)`` danach –
        mit den Pfaden der wiederhergestellten Dokumente."""
        def find():
            return recovery.orphaned_sessions()

        def done(found) -> None:
            restored: list[str] = []
            for info in found[:5]:
                when = time.strftime("%d.%m.%Y %H:%M", time.localtime(info.saved_at))
                origin = f"Original: {info.original}" if info.original else "Neues Dokument"
                answer, _data = self.app.dialogs.ask(
                    "confirm", "Eine nicht gespeicherte Bearbeitung wurde gefunden.",
                    f"»{info.name}« – zuletzt gesichert am {when}. {origin}. Wiederhergestellt wird ein ungespeicherter Stand; die Originaldatei bleibt unverändert, bis Sie speichern.",
                    primary="Wiederherstellen", secondary="Verwerfen", close="Später",
                )
                if answer == "primary":
                    if self.app.currentPage != "reader":
                        self.app.navigate(READER.key)
                    self._open(info.original or info.name, None, recovered=info)
                    if info.original:
                        restored.append(info.original)
                elif answer == "secondary":
                    recovery.discard_session(info)
            if then is not None:
                then(restored)

        def failed(_exc: BaseException, _details: str) -> None:
            if then is not None:
                then([])

        self.engine.submit(find, done, failed, label="wiederherstellung", priority=3)

    # Beenden -----------------------------------------------------------------------------------------------------
    def confirm_close(self, reason: str = "Novadesk wird beendet.") -> bool:
        # Aktiver Tab vor den Rückfragen (sie zeigen das jeweilige Dokument) – für die letzte Sitzung
        self._quit_active = self.currentKey
        for controller in list(self._docs.values()):
            if not controller.dirty:
                continue
            self.activate(controller.ident)
            answer, _data = self.app.dialogs.ask(
                "confirm", f"Änderungen an »{controller.name}« speichern?", f"{reason} Ohne Speichern gehen die Änderungen verloren.",
                primary="Speichern", secondary="Nicht speichern", close="Abbrechen",
            )
            if answer == "primary":
                if not self._save_now(controller):
                    self._quit_active = ""
                    return False
            elif answer != "secondary":
                self._quit_active = ""
                return False
        return True

    def _save_now(self, controller: DocumentController) -> bool:
        if _office(controller):
            return controller.save_and_wait()
        target = controller.path or self.pick_save_pdf(controller.name or "Dokument.pdf", "Speichern unter")
        if not target:
            return False
        task = self.engine.submit(lambda: controller.session.save(target), label="speichern")
        try:
            self.engine.wait(task, timeout=600)
        except Exception as exc:  # noqa: BLE001 - Fehler anzeigen (mit Protokoll), Beenden abbrechen
            controller._report_save_error(exc)  # noqa: SLF001
            return False
        return True

    def running_work(self) -> str:
        return "PDF speichern" if any(controller.busy or controller.saving for controller in self._docs.values()) else ""

    def release_documents(self) -> bool:
        """Fenster schließt, Novadesk bleibt im Hintergrund: wie beim Beenden nach ungespeicherten Änderungen fragen und
        alle Dokumente schließen (die Engine bleibt geladen). Mit »letzte Sitzung« öffnet das nächste Zeigen sie wieder.
        Wird gerade gespeichert, bleiben die Dokumente offen (nichts wird abgebrochen)."""
        if self.running_work():
            return True
        if not self.confirm_close("Das Fenster wird geschlossen."):
            return False
        if self._docs and self._restore_wanted() and self._session_pending is None and not self._restoring:
            self._session = self._session_snapshot()
            self._session_pending = self._session
        for key in list(self._docs):
            self._finish_close(key, discard_recovery=True, remember=False)
        self._quit_active = ""
        return True

    def window_shown(self) -> None:
        """Fenster nach dem Verstecken wieder gezeigt: die beim Schließen gemerkten PDFs wieder öffnen (Einstellung)."""
        if self.app.ready and self._session_pending is not None and not self._docs:
            self._restore_session()

    def close_all(self) -> None:
        # Vor dem Schließen: die PDFs dieser Sitzung (nur Pfade und Seiten) – beendet, bevor die letzte Sitzung wieder
        # offen war, bleibt die gemerkte Liste, statt nur einen Teil davon zu behalten
        if self._restore_wanted() and self._session_pending is None and not self._restoring:
            self._session = self._session_snapshot()
        for key in list(self._docs):
            self._finish_close(key, discard_recovery=True, remember=False)
        self.engine.shutdown()
        self._remove_attachment_dir()
        self._unwatch_clipboard()
        self._release_clipboard()

    # Geöffnete Anhänge ------------------------------------------------------------------------------------
    def attachment_dir(self) -> str:
        """Eigener Ordner für Anhänge, die mit ihrem Programm geöffnet werden (beim Beenden entfernt)."""
        if self._attachment_dir is None or not Path(self._attachment_dir).is_dir():
            import tempfile

            self._attachment_dir = tempfile.mkdtemp(prefix="pdf-tool-anhaenge-")
        return self._attachment_dir

    def _remove_attachment_dir(self) -> None:
        folder, self._attachment_dir = self._attachment_dir, None
        if folder is None:
            return
        import shutil

        def failed(_function, _path, exc) -> None:
            # Noch in einem anderen Programm geöffnet: bleibt im Temp-Ordner (Windows räumt ihn auf)
            _log().info("Geöffneter Anhang ließ sich nicht entfernen: %s", type(exc).__name__)

        shutil.rmtree(folder, onexc=failed)

    # Zwischenablage für Objekte -----------------------------------------------------------------------------
    # Kopierte Objekte bleiben als kleine PDF im Arbeitsspeicher (über Tabs hinweg); die Zwischenablage des
    # Systems erhält ihren Text, bei Bildern das Bild und eine Kennung. Steht dort inzwischen etwas anderes,
    # fügt Strg+V das ein (Bild bzw. Text) – nie veraltete Objekte.
    def watch_clipboard(self) -> None:
        from PySide6.QtGui import QGuiApplication

        board = QGuiApplication.clipboard()
        if board is not None and not self._clipboard_watched:
            board.dataChanged.connect(self._clipboard_changed)
            self._clipboard_watched = True
        self._clipboard_changed()

    def _unwatch_clipboard(self) -> None:
        """Beim Beenden: die Zwischenablage meldet sich beim Abbau der Anwendung noch einmal – dann darf
        sie kein schon abgebautes Objekt mehr erreichen."""
        if not self._clipboard_watched:
            return
        from PySide6.QtGui import QGuiApplication

        self._clipboard_watched = False
        board = QGuiApplication.clipboard()
        if board is not None:
            try:
                board.dataChanged.disconnect(self._clipboard_changed)
            except (RuntimeError, TypeError) as exc:  # nicht (mehr) verbunden
                _log("ui").info("Zwischenablage war nicht verbunden: %s", type(exc).__name__)

    def _release_clipboard(self) -> None:
        """Vor dem Beenden: Unsere Daten in der Zwischenablage (in Python angelegt) durch Qt-eigene ersetzen –
        Text bzw. Bild bleiben für andere Programme erhalten, nur die interne Kennung entfällt. Sonst würde Qt sie
        erst nach dem Ende von Python abbauen, und das Programm stürzt beim Beenden ab (PySide6). Das gilt auch für
        Kopien aus Texten (``TEXT_CLIP_FORMAT``); deren Formatierung (HTML) entfällt dabei, der Text bleibt."""
        from PySide6.QtGui import QGuiApplication

        board = QGuiApplication.clipboard()
        data = board.mimeData() if board is not None else None
        from ..text.document import TEXT_CLIP_FORMAT

        if data is None or not (data.hasFormat(CLIP_FORMAT) or data.hasFormat(TEXT_CLIP_FORMAT)):
            return
        text = data.text() if data.hasText() else ""
        if text:
            board.setText(text)
            return
        image = board.image() if data.hasImage() else None
        if image is not None and not image.isNull():
            board.setImage(image)
        else:
            board.clear()

    def _clipboard_changed(self) -> None:
        if not self._clipboard_watched:
            return
        self.canPaste = self.paste_source(peek=True)[0] is not None

    def set_clip(self, clip, picture=None, *, cut: bool = False) -> None:
        from PySide6.QtCore import QByteArray, QMimeData
        from PySide6.QtGui import QGuiApplication

        self._clip = clip
        self._clip_cut = cut  # ausgeschnitten: das erste Einfügen auf der Quellseite kommt an die alte Stelle
        self._paste_counts = {}
        mime = QMimeData()
        if clip.text:
            mime.setText(clip.text)
        if picture is not None and not picture.isNull():
            mime.setImageData(picture)
        mime.setData(CLIP_FORMAT, QByteArray(clip.token.encode("ascii")))
        board = QGuiApplication.clipboard()
        if board is None:
            self.app.set_status("Die Zwischenablage ist nicht verfügbar.", "error")
            return
        board.setMimeData(mime)
        self._clipboard_changed()
        count = max(1, clip.count)
        self.app.set_status("1 Objekt kopiert." if count == 1 else f"{count} Objekte kopiert.", "success")

    def paste_source(self, *, peek: bool = False) -> tuple[str | None, object]:
        """Was Strg+V einfügt: ``("clip", Clip)``, ``("image", QImage)``, ``("text", str)`` oder nichts."""
        from PySide6.QtGui import QGuiApplication

        board = QGuiApplication.clipboard()
        data = board.mimeData() if board is not None else None
        if data is None:
            return None, None
        if self._clip is not None and data.hasFormat(CLIP_FORMAT) and bytes(data.data(CLIP_FORMAT).data()).decode("ascii", "replace") == self._clip.token:
            return "clip", self._clip
        if data.hasImage():
            if peek:
                return "image", None
            image = board.image()
            if not image.isNull():
                return "image", image
        text = data.text() if data.hasText() else ""
        if text.strip():
            return "text", text
        return None, None

    def set_page_clip(self, data: bytes, count: int) -> None:
        self._page_data = data
        self.pageClip = count
        self.app.set_status("1 Seite kopiert." if count == 1 else f"{count} Seiten kopiert.", "success")

    def page_clip(self) -> bytes | None:
        return self._page_data

    def paste_nudge(self, ident: str, page: int, clip) -> int:
        """Wiederholtes Einfügen an derselben Stelle versetzt die Kopien – auf der Quellseite schon die erste."""
        key = (ident, page)
        count = self._paste_counts.get(key, 1 if tuple(clip.source) == key and not self._clip_cut else 0)
        self._paste_counts[key] = count + 1
        return count


    # Texterkennung (OCR) -------------------------------------------------------------------------------------
    def probe_ocr(self) -> None:
        """Tesseract einmal je Programmlauf im Hintergrund suchen (der erste Start prüft unter Windows der
        Virenscanner); danach gilt das Ergebnis für alle Tabs."""
        if self.ocrState in ("pruefen", "bereit"):
            return
        from tools.pdf_editor import ocr

        def found(engine) -> None:
            _OCR_PROBE["done"], _OCR_PROBE["engine"] = True, engine
            self._ocr_engine = engine
            self.ocrLanguages = [{"code": code, "label": ocr.language_label(code)} for code in ocr.display_order(engine.languages)] if engine is not None else []
            self.ocrState = "bereit" if engine is not None else "fehlt"
            if engine is None:
                _log("ocr").info("Texterkennung: keine Engine gefunden")

        if _OCR_PROBE["done"]:
            found(_OCR_PROBE["engine"])
            return
        self.ocrState = "pruefen"

        def failed(exc: BaseException, _details: str) -> None:
            _log("ocr").warning("Texterkennung: Suche fehlgeschlagen (%s)", type(exc).__name__)
            self.ocrState = "fehlt"

        self.app.worker.run(ocr.find_engine, found, failed)

    def ocr_engine(self):
        return self._ocr_engine

    def ocr_languages(self) -> list[str]:
        """Zuletzt gewählte Sprachen (sofern installiert), sonst Deutsch bzw. die erste installierte."""
        installed = [entry["code"] for entry in self.ocrLanguages]
        chosen = [code for code in self._ocr_chosen if code in installed]
        if chosen:
            return chosen
        return ["deu"] if "deu" in installed else installed[:1]

    def remember_sign_defaults(self, values: dict) -> None:
        if values != self.sign_defaults:
            self.sign_defaults = dict(values)
            self.app.schedule_save()

    def remember_ocr_languages(self, codes: list[str]) -> None:
        if codes and codes != self._ocr_chosen:
            self._ocr_chosen = list(codes)
            self.app.schedule_save()


class ReaderTool:
    """Anbindung an den AppController (Tastenkürzel, Ziehen und Ablegen, Beenden)."""

    def __init__(self, app, cfg: dict) -> None:
        self.app = app
        self.controller = ReaderController(app, cfg, app)
        app.register_tool(READER.key, self)

    def primary_action(self, page: str) -> None:
        current = self.controller.current
        if current is not None:
            current.saveDocument()

    def open_action(self, page: str) -> None:
        self.controller.openDialog()

    def find_action(self, page: str) -> None:
        current = self.controller.current
        if current is not None:
            if not _office(current):
                self.controller.leftPanel = "search"
            current.requestSearch()

    def show_help(self, page: str) -> None:
        self.app.show_steps("Kurzanleitung – PDF Reader & Editor", HELP_STEPS, HELP_NOTES)

    def hint(self, page: str) -> str:
        return HINT

    def accepts(self, paths: list[str], page: str) -> bool:
        # Office-Dateien zeigt der Reader als PDF – Excel-Listen aber nur im Reader selbst (auf der Startseite gehören sie
        # zu den »Vertragsübersichten«; die Ansicht einer Tabelle bietet dafür »Vertragsübersicht erstellen« an)
        return any(p.lower().endswith(".pdf") or imagepdf.is_image(p) or office.kind_of(p) in ("word", "powerpoint") or (office.kind_of(p) == "excel" and (page == READER.key or not p.lower().endswith(CONTRACT_LISTS))) for p in paths)

    def drag_enter(self, accepted: bool, page: str) -> None:
        self.controller.dropHighlight = accepted

    def drag_leave(self) -> None:
        self.controller.dropHighlight = False

    def drop(self, paths: list[str], page: str) -> None:
        self.controller.open_paths(paths)

    def page_prepare(self, page: str) -> None:
        pass

    def page_left(self, page: str) -> None:
        pass

    def config(self) -> dict:
        return self.controller.config()

    def autosave(self) -> None:
        pass

    def changed(self) -> None:
        pass

    def confirm_close(self) -> bool:
        return self.controller.confirm_close()

    def running_work(self) -> str:
        return self.controller.running_work()

    def close(self) -> None:
        self.controller.close_all()

    def release(self) -> bool:
        return self.controller.release_documents()

    def holds_documents(self) -> bool:
        return bool(self.controller._docs)  # noqa: SLF001

    def shown(self) -> None:
        self.controller.window_shown()


# Bekannte Ordner im Benutzerordner: so heißen sie im Explorer (Startseite »Zuletzt verwendet«, Spalte »Ordner«)
KNOWN_FOLDERS = {"documents": "Dokumente", "desktop": "Desktop", "downloads": "Downloads", "pictures": "Bilder",
                 "music": "Musik", "videos": "Videos", "onedrive": "OneDrive"}


def place_text(folder: str) -> str:
    """Ordner kurz wie im Design: »Dokumente\\Kunden« statt »C:\\Users\\Name\\Documents\\Kunden«; außerhalb des
    Benutzerordners der Pfad selbst."""
    home = os.path.expanduser("~")
    try:
        relative = os.path.relpath(folder, home)
    except ValueError:  # anderes Laufwerk
        return folder
    if relative.startswith("..") or os.path.isabs(relative):
        return folder
    if relative == ".":
        return Path(home).name
    parts = Path(relative).parts
    first = KNOWN_FOLDERS.get(parts[0].lower(), parts[0])
    return "\\".join([first, *parts[1:]]) if os.sep == "\\" else "/".join([first, *parts[1:]])


def _office(doc) -> bool:
    """Tabelle oder Text zum Bearbeiten (eigene Ansicht, kein PDF)?"""
    return bool(getattr(doc, "isSheet", False) or getattr(doc, "isText", False))


def _shows(doc: DocumentController, path: str) -> bool:
    """Zeigt dieser Tab die Datei – als PDF oder als Ansicht einer Office-Datei?"""
    return bool(doc.path and _same(doc.path, path)) or bool(doc.sourcePath and _same(doc.sourcePath, path))


def _same(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _key(path: str) -> str:
    """Vergleichsschlüssel eines Pfads ohne Dateizugriff (unter Windows ohne Groß-/Kleinschreibung)."""
    try:
        return os.path.normcase(os.path.abspath(str(path)))
    except (OSError, ValueError):
        return str(path)


def _session_from(value) -> dict | None:
    """Gespeicherte letzte Sitzung robust lesen: ``{"dokumente": [{"pfad", "seite"}], "aktiv": Pfad}`` – fehlerhafte
    Einträge entfallen, nie eine Ausnahme."""
    if not isinstance(value, dict) or not isinstance(value.get("dokumente"), list):
        return None
    documents = []
    for entry in value["dokumente"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("pfad"), str) or not entry["pfad"].strip():
            continue
        page = entry.get("seite")
        documents.append({"pfad": entry["pfad"], "seite": page if isinstance(page, int) and not isinstance(page, bool) and page >= 0 else 0})
    if not documents:
        return None
    active = value.get("aktiv")
    return {"dokumente": documents[:TAB_LIMIT], "aktiv": active if isinstance(active, str) else ""}


def _looks_like_pdf(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            return b"%PDF-" in handle.read(1024)
    except OSError:
        return False


def _preload_engine() -> None:
    """PDF-Engine (pikepdf, PDFium, Bearbeiten, Speichern) vorab laden – im Arbeitsthread, wenn die Oberfläche
    fertig ist. Das erste Öffnen wartet dann nicht auf das Laden der Module."""
    from . import session  # noqa: F401


def _log(category: str = "pdf"):
    """Logger eines festen Protokollbereichs (``diagnostics.applog``: pdf, render, ocr, ui …) – ohne Inhalte."""
    from diagnostics.applog import get

    return get(category)


def _file_info(path: str) -> tuple[bool, int]:
    """(vorhanden, Größe in Byte) – ein einziger Zugriff auf das Dateisystem je Eintrag."""
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return False, 0
    return stat.S_ISREG(info.st_mode), int(info.st_size)


def size_text(size: int) -> str:
    """Dateigröße wie im Explorer: »850 Byte«, »120 KB«, »1,2 MB«, »1,1 GB«."""
    if size < 1024:
        return f"{size} Byte"
    value, unit = size / 1024, "KB"
    for bigger in ("MB", "GB"):
        if round(value) < 1024:  # gerundet noch keine 1024 (sonst »1,0 MB« statt »1024 KB«)
            break
        value, unit = value / 1024, bigger
    text = f"{value:.0f}" if unit == "KB" or round(value, 1) >= 100 else f"{value:.1f}"
    return f"{text.replace('.', ',')} {unit}"


def opened_text(stamp: str, now: datetime | None = None) -> str:
    """Wann zuletzt geöffnet (Ortszeit): »Heute, 14:05«, »Gestern, 09:12«, sonst »03.10.2026«; ohne Zeitangabe
    leer."""
    try:
        when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return ""
    today = (now or datetime.now()).date()
    if when.date() == today:
        return f"Heute, {when:%H:%M}"
    if when.date() == today - timedelta(days=1):
        return f"Gestern, {when:%H:%M}"
    return f"{when:%d.%m.%Y}"


def _temporary(path: str) -> bool:
    """Kopie eines Outlook-Anhangs (``INetCache\\Content.Outlook``). Outlook löscht seine Kopien später wieder; dass sie
    in der letzten Sitzung fehlen, ist kein Fehler."""
    return "\\content.outlook\\" in str(path).replace("/", "\\").lower()
