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


class Overflow(Exception):
    """Der neue Text passt nicht in den Block – die Oberfläche fragt, wie weiter
    (``overflow="grow"``: weitere Zeilen, ``"shrink"``: kleinere Schrift)."""

    def __init__(self, needed: int, available: int) -> None:
        super().__init__(f"Der Text braucht {needed} Zeilen, der Platz reicht für {available}.")
        self.needed = needed
        self.available = available


# Arten von Speicherfehlern (``SaveFailed.kind``) – für Protokoll, Tests und die Oberfläche
SERIALIZE_FAILED = "SERIALIZE_FAILED"  # der bearbeitete Stand ließ sich nicht als PDF schreiben
VALIDATION_FAILED = "VALIDATION_FAILED"  # Prüfung vor dem Schreiben: Inhalte fehlten, nicht darstellbar …
TARGET_READ_ONLY = "TARGET_READ_ONLY"  # die Zieldatei ist schreibgeschützt
DIRECTORY_NOT_WRITABLE = "DIRECTORY_NOT_WRITABLE"  # keine Schreibberechtigung am Speicherort
DIRECTORY_MISSING = "DIRECTORY_MISSING"  # der Zielordner existiert nicht (mehr)
FILE_LOCKED = "FILE_LOCKED"  # ein anderes Programm hält die Datei offen
TEMP_WRITE_FAILED = "TEMP_WRITE_FAILED"  # temporäre Datei nicht geschrieben (z. B. Datenträger voll)
BACKUP_FAILED = "BACKUP_FAILED"  # Sicherung des bisherigen Stands nicht möglich
REPLACE_FAILED = "REPLACE_FAILED"  # Original nicht ersetzt (sonstiger Grund)
REOPEN_FAILED = "REOPEN_FAILED"  # gespeicherte Datei ließ sich danach nicht wieder öffnen
SAVE_FAILED = "SAVE_FAILED"  # sonstiger Fehler


class SaveFailed(EditorError):
    """Speichern fehlgeschlagen – das Original ist unverändert (nur bei ``REOPEN_FAILED`` wurde es
    schon ersetzt; dann liegt eine Sicherung des vorherigen Stands vor).

    ``kind``: Art des Fehlers (siehe oben), ``phase``: Schritt des Speicherns, ``save_as``: in der
    Oberfläche »Speichern unter« anbieten. ``detail``, ``errno``, ``winerror`` und ``backend`` sind
    technische Angaben für das Protokoll – ohne Pfade und ohne Inhalte des Dokuments."""

    def __init__(self, reason: str, detail: str = "", *, kind: str = SAVE_FAILED, phase: str = "", save_as: bool = False, backend: str = "", error: BaseException | None = None) -> None:
        super().__init__(reason)
        self.detail = detail
        self.kind = kind
        self.phase = phase
        self.save_as = save_as
        self.backend = backend
        self.errno = getattr(error, "errno", None) if isinstance(error, OSError) else None
        self.winerror = getattr(error, "winerror", None) if isinstance(error, OSError) else None
        self.error_type = type(error).__name__ if error is not None else ""

    def log_text(self) -> str:
        """Eine Zeile für das Protokoll: Art, Schritt, Komponente, Fehlertyp und -nummern."""
        parts = [f"Art={self.kind}", f"Schritt={self.phase or '-'}", f"Komponente={self.backend or '-'}"]
        if self.error_type:
            parts.append(f"Fehler={self.error_type}")
        if self.errno is not None:
            parts.append(f"errno={self.errno}")
        if self.winerror is not None:
            parts.append(f"WinError={self.winerror}")
        if self.detail:
            parts.append(f"Details={self.detail}")
        return " · ".join(parts)


class ExternalChange(EditorError):
    """Die Datei wurde seit dem Öffnen von einem anderen Programm verändert."""

    def __init__(self) -> None:
        super().__init__("Die Datei wurde seit dem Öffnen von einem anderen Programm verändert.")
