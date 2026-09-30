"""Seite »Einstellungen«: Design, Akzentfarbe, Mica, Animationsprofil und Kundenakte.

Der SettingsController verbindet die Schalter der Seite mit den zuständigen Controllern
(Design → ``ThemeController``, Kundenakte → ``CustomerController``) und sorgt für Rückmeldung
und Speichern. Jede Änderung wirkt sofort – ohne Neustart.
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


class SettingsController(Observable):
    """In QML: ``Settings``."""

    customerRecordsChanged, customerRecords = prop(bool, "customerRecords", False)

    def __init__(self, app, theme: ThemeController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.theme = theme
        self.customers = None  # CustomerController, sobald das Werkzeug eingerichtet ist

    def attach_customers(self, customers) -> None:
        self.customers = customers
        self.customerRecords = bool(customers.enabled)
        customers.enabledChanged.connect(lambda: setattr(self, "customerRecords", bool(customers.enabled)))

    # Auswahllisten ------------------------------------------------------------------------------
    def _themes(self) -> list[dict]:
        return [{"value": key, "label": THEME_LABELS[key]} for key in THEMES]

    def _profiles(self) -> list[dict]:
        return [{"value": key, "label": PROFILE_LABELS[key], "text": PROFILE_TEXTS[key]} for key in PROFILES]

    _constant = Signal()
    themes = Property(list, _themes, notify=_constant)
    profiles = Property(list, _profiles, notify=_constant)

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

    # Kundenakte -------------------------------------------------------------------------------------
    @Slot(bool)
    def setCustomerRecords(self, enabled: bool) -> None:  # noqa: N802
        if self.customers is not None:
            self.customers.set_enabled(bool(enabled))
