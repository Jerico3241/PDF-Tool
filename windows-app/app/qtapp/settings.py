"""Seite »Einstellungen«: Design, Akzentfarbe, Mica, Animationsprofil, PDF Reader und Kundenakte.

Der SettingsController verbindet die Schalter der Seite mit den zuständigen Controllern
(Design → ``ThemeController``, Kundenakte → ``CustomerController``) und sorgt für Rückmeldung
und Speichern. Jede Änderung wirkt sofort – ohne Neustart.

PDF Reader: Standardzoom und Seitenleiste für neu geöffnete Dokumente. Der Standard »Zuletzt
verwendet« (``last``) übernimmt wie bisher die zuletzt eingestellte Ansicht bzw. Seitenleiste;
der Reader fragt beim Öffnen ``reader_start_view`` und ``reader_start_panel``. Dazu »PDFs der letzten
Sitzung beim Start wieder öffnen« (Standard: aus) – die Liste selbst führt der Reader.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from .base import Observable, prop
from .theme import PROFILE_LABELS, PROFILES, THEME_LABELS, THEMES, ThemeController

CUSTOMER_RECORDS_TITLE = "Kundenakte verwenden"
CUSTOMER_RECORDS_TEXT = "Speichert Kundendaten lokal und ermöglicht die Wiedererkennung bekannter Rechnungsempfänger."
CUSTOMER_RECORDS_NOTE = "Alle Kundendaten werden ausschließlich lokal auf diesem PC gespeichert."
PROFILE_TEXTS = {
    "full": "Übergänge, Einblendungen, Bewegungen und Rückmeldungen beim Bedienen.",
    "reduced": "Nur kurze Überblendungen und Farbwechsel – keine größeren Bewegungen.",
    "off": "Zustände wechseln sofort, ohne Animation.",
}
# PDF Reader: Ansicht beim Öffnen (Schlüssel in gui-config.json; fehlt er: »last« wie bisher)
READER_ZOOM_KEY = "reader_zoom_beim_oeffnen"
READER_PANEL_KEY = "reader_leiste_beim_oeffnen"
READER_SESSION_KEY = "reader_sitzung_wiederherstellen"  # PDFs der letzten Sitzung beim Start (fehlt er: aus)
READER_ZOOMS = (("last", "Zuletzt verwendet"), ("width", "Seitenbreite"), ("page", "Ganze Seite"), ("100", "100 %"))
READER_PANELS = (("last", "Zuletzt verwendet"), ("thumbs", "Seiten"), ("outline", "Lesezeichen"), ("none", "Keine"))


def _choice(value: object, options: tuple[tuple[str, str], ...]) -> str:
    """Gespeicherter Wert, wenn er eine der Möglichkeiten ist – sonst »last« (wie bisher)."""
    return value if isinstance(value, str) and value in dict(options) else "last"


class SettingsController(Observable):
    """In QML: ``Settings``."""

    customerRecordsChanged, customerRecords = prop(bool, "customerRecords", False)
    readerZoomChanged, readerZoom = prop(str, "readerZoom", "last")  # Standardzoom beim Öffnen
    readerPanelChanged, readerPanel = prop(str, "readerPanel", "last")  # Seitenleiste beim Öffnen
    readerRestoreSessionChanged, readerRestoreSession = prop(bool, "readerRestoreSession", False)  # letzte Sitzung beim Start

    def __init__(self, app, theme: ThemeController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.theme = theme
        self.customers = None  # CustomerController, sobald das Werkzeug eingerichtet ist
        self.set_quietly("readerZoom", _choice(app.cfg.get(READER_ZOOM_KEY), READER_ZOOMS))
        self.set_quietly("readerPanel", _choice(app.cfg.get(READER_PANEL_KEY), READER_PANELS))
        self.set_quietly("readerRestoreSession", app.cfg.get(READER_SESSION_KEY) is True)
        app.register_config(self.config)

    def attach_customers(self, customers) -> None:
        self.customers = customers
        self.customerRecords = bool(customers.enabled)
        customers.enabledChanged.connect(lambda: setattr(self, "customerRecords", bool(customers.enabled)))

    # Auswahllisten ------------------------------------------------------------------------------
    def _themes(self) -> list[dict]:
        return [{"value": key, "label": THEME_LABELS[key]} for key in THEMES]

    def _profiles(self) -> list[dict]:
        return [{"value": key, "label": PROFILE_LABELS[key], "text": PROFILE_TEXTS[key]} for key in PROFILES]

    def _reader_zooms(self) -> list[dict]:
        return [{"value": value, "label": label} for value, label in READER_ZOOMS]

    def _reader_panels(self) -> list[dict]:
        return [{"value": value, "label": label} for value, label in READER_PANELS]

    _constant = Signal()
    themes = Property(list, _themes, notify=_constant)
    profiles = Property(list, _profiles, notify=_constant)
    readerZooms = Property(list, _reader_zooms, notify=_constant)
    readerPanels = Property(list, _reader_panels, notify=_constant)

    def _texts(self) -> dict:
        return {"customerTitle": CUSTOMER_RECORDS_TITLE, "customerText": CUSTOMER_RECORDS_TEXT, "customerNote": CUSTOMER_RECORDS_NOTE}

    texts = Property("QVariantMap", _texts, notify=_constant)

    # Design ----------------------------------------------------------------------------------------
    @Slot(str)
    def setTheme(self, mode: str) -> None:  # noqa: N802 - QML-Schreibweise
        if mode not in THEMES:
            return
        self.theme.setMode(mode)
        self.app.persist()
        labels = {"system": "wie Windows", "light": "hell", "dark": "dunkel"}
        self.app.set_status(f"App-Design: {labels.get(mode, mode)}", "success")

    @Slot(str)
    def setAccent(self, value: str) -> None:  # noqa: N802
        self.theme.setAccent(value)
        self.app.persist()

    @Slot(bool)
    def setMica(self, enabled: bool) -> None:  # noqa: N802
        self.theme.setMica(enabled)
        self.app.apply_chrome()
        self.app.persist()

    @Slot(str)
    def setProfile(self, profile: str) -> None:  # noqa: N802
        if profile not in PROFILES:
            return
        self.theme.setProfile(profile)
        self.app.persist()
        self.app.set_status(f"Animationen: {PROFILE_LABELS[profile]}", "success")

    # PDF Reader: Ansicht beim Öffnen ------------------------------------------------------------------
    @Slot(str)
    def setReaderZoom(self, value: str) -> None:  # noqa: N802
        labels = dict(READER_ZOOMS)
        if value not in labels or value == self.readerZoom:
            return
        self.readerZoom = value
        self.app.persist()
        self.app.set_status(f"Standardzoom beim Öffnen: {labels[value]}", "success")

    @Slot(str)
    def setReaderPanel(self, value: str) -> None:  # noqa: N802
        labels = dict(READER_PANELS)
        if value not in labels or value == self.readerPanel:
            return
        self.readerPanel = value
        self.app.persist()
        self.app.set_status(f"Seitenleiste beim Öffnen: {labels[value]}", "success")

    def reader_start_view(self, last: dict) -> dict:
        """Ansicht eines neu geöffneten Dokuments (``fit``, ``zoom``, ``mode``): die zuletzt
        verwendete (``last``) oder die gewählte Vorgabe; der Ansichtsmodus bleibt der zuletzt verwendete."""
        choice = self.readerZoom
        if choice in ("width", "page"):
            return {**last, "fit": choice}
        if choice == "100":
            return {**last, "fit": "", "zoom": 100.0}
        return dict(last)

    def reader_start_panel(self, last: str) -> str:
        """Linke Seitenleiste eines neu geöffneten Dokuments: die zuletzt verwendete (``last``) oder
        die gewählte – ``thumbs`` (Seiten), ``outline`` (Lesezeichen), ``""`` (keine)."""
        return {"thumbs": "thumbs", "outline": "outline", "none": ""}.get(self.readerPanel, last)

    @Slot(bool)
    def setReaderRestoreSession(self, enabled: bool) -> None:  # noqa: N802
        """PDFs der letzten Sitzung beim Start wieder öffnen. Aus: die gemerkte Liste wird entfernt."""
        enabled = bool(enabled)
        if enabled == self.readerRestoreSession:
            return
        self.readerRestoreSession = enabled
        self.app.persist()
        self.app.set_status("PDFs der letzten Sitzung werden beim Start wieder geöffnet." if enabled else "PDFs der letzten Sitzung werden beim Start nicht mehr geöffnet.", "success")

    def config(self) -> dict:
        return {READER_ZOOM_KEY: self.readerZoom, READER_PANEL_KEY: self.readerPanel, READER_SESSION_KEY: self.readerRestoreSession}

    # Kundenakte -------------------------------------------------------------------------------------
    @Slot(bool)
    def setCustomerRecords(self, enabled: bool) -> None:  # noqa: N802
        if self.customers is not None:
            self.customers.set_enabled(bool(enabled))
