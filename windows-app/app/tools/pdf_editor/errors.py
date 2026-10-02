"""Fehler des PDF Readers/Editors – mit Texten für die Oberfläche (nie mit Dokumentinhalten)."""

from __future__ import annotations


class EditorError(Exception):
    """Allgemeiner Fehler; ``str(error)`` ist ein verständlicher Satz für die Oberfläche."""


class PasswordRequired(EditorError):
    """Das PDF ist mit einem Passwort geschützt (``wrong``: das angegebene Passwort passt nicht)."""

    def __init__(self, wrong: bool = False) -> None:
        super().__init__("Das eingegebene Passwort ist falsch." if wrong else "Dieses PDF ist mit einem Passwort geschützt.")
        self.wrong = wrong


class DamagedDocument(EditorError):
    """Das PDF lässt sich nicht öffnen – vermutlich beschädigt (»PDF reparieren« anbieten)."""

    def __init__(self, detail: str = "") -> None:
        super().__init__("Dieses Dokument scheint beschädigt zu sein.")
        self.detail = detail  # technische Ursache (ohne Inhalte) für Protokoll und Details


class NotAPdf(EditorError):
    def __init__(self) -> None:
        super().__init__("Die Datei ist keine PDF-Datei.")


class ReadOnlyDocument(EditorError):
    """Bearbeiten ist für dieses Dokument nicht erlaubt (z. B. Berechtigungen der Datei)."""


class UnsupportedEdit(EditorError):
    """Diese Bearbeitung ist für das gewählte Objekt nicht sicher möglich."""


class SaveFailed(EditorError):
    """Speichern fehlgeschlagen – das Original ist unverändert."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.detail = detail


class ExternalChange(EditorError):
    """Die Datei wurde seit dem Öffnen von einem anderen Programm verändert."""

    def __init__(self) -> None:
        super().__init__("Die Datei wurde seit dem Öffnen von einem anderen Programm verändert.")
