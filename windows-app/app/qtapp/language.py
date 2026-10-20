"""Sprache der Oberfläche in QML (``I18n``): ``I18n.tr(text, I18n.revision)`` in jeder Textbindung, die Einstellung
»Sprache« (wie Windows, Deutsch, English) und das Umschalten ohne Neustart. Übersetzt wird in ``i18n``."""

from __future__ import annotations

from PySide6.QtCore import QObject, Slot

import i18n

from .base import Observable, prop

CONFIG_KEY = "sprache"  # gui-config.json: system, de oder en
LABELS = {"system": "Wie Windows", "de": "Deutsch", "en": "English"}


class LanguageController(Observable):
    """In QML: ``I18n``."""

    revisionChanged, revision = prop(int, "revision", 0)  # ändert sich beim Umschalten: alle Texte neu
    languageChanged, language = prop(str, "language", "de")  # gerade verwendet: de oder en
    choiceChanged, choice = prop(str, "choice", "system")  # Einstellung

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        choice = cfg.get(CONFIG_KEY)
        self.set_quietly("choice", choice if choice in i18n.CHOICES else "system")
        code = i18n.resolve(self.choice)
        i18n.set_language(code)
        self.set_quietly("language", code)
        app.register_config(self.config)

    def config(self) -> dict:
        return {CONFIG_KEY: self.choice}

    @Slot("QVariant", "QVariant", result="QVariant")
    def tr(self, text, _revision=None):
        return i18n.tr(text)

    @Slot("QVariant", result="QVariant")
    def tr1(self, text):  # noqa: D401 - ohne Abhängigkeit von ``revision`` (einmalige Texte in Funktionen)
        return i18n.tr(text)

    @Slot(result=list)
    def choices(self) -> list:
        return [{"value": key, "label": LABELS[key]} for key in i18n.CHOICES]

    @Slot(str)
    def setChoice(self, choice: str) -> None:  # noqa: N802
        if choice not in i18n.CHOICES or choice == self.choice:
            return
        self.choice = choice
        code = i18n.resolve(choice)
        if code != self.language:
            i18n.set_language(code)
            self.language = code
            self.revision += 1
        self.app.persist()
        self.app.set_status(i18n.tr("Sprache: ") + i18n.tr(LABELS[choice]), "success")
