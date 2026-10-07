"""Kennwortschutz: Kennwort zum Öffnen und Berechtigungen setzen, ändern oder entfernen.

Die Einstellung gilt für das nächste Speichern (Strg+S oder »Speichern unter«) und alle weiteren –
bis dahin bleibt die Datei auf der Platte unverändert, und Rückgängig nimmt sie zurück. Geschrieben
wird mit AES-256 (PDF 2.0, Revision 6).

Regeln:

* Ändern darf nur, wer alle Rechte hat: ein unverschlüsseltes PDF, eines, das mit dem
  Besitzerkennwort (Berechtigungskennwort) geöffnet wurde, oder eines, für das das Besitzerkennwort
  nachträglich eingegeben wurde (``unlock``). Eine Einschränkung wird nie umgangen.
* Ein Kennwort zum Öffnen ohne eigenes Berechtigungskennwort gilt auch als Berechtigungskennwort –
  sonst ließe sich die Datei mit einem leeren Besitzerkennwort ohne Kennwort öffnen.
* Einschränkungen (Drucken, Kopieren …) brauchen ein eigenes Berechtigungskennwort.
* Kennwörter bleiben nur im Arbeitsspeicher – nie in Einstellungen, Protokoll oder Sicherungen.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field, replace

import pikepdf

from .document import RESTRICTED_REASON, EditorDocument, Permissions
from .errors import EditorError

MIN_LENGTH = 4
MAX_BYTES = 127  # Grenze der PDF-Norm für Kennwörter (UTF-8, Revision 6)


@dataclass(frozen=True)
class Protection:
    """Gewünschter Schutz beim Speichern. Ohne Kennwörter: unverschlüsselt."""

    user_password: str = ""  # zum Öffnen
    owner_password: str = ""  # für Berechtigungen
    print: bool = True
    copy: bool = True
    edit: bool = True
    annotate: bool = True
    fill_forms: bool = True
    assemble: bool = True

    @property
    def enabled(self) -> bool:
        return bool(self.user_password or self.owner_password)

    @property
    def restricted(self) -> bool:
        return not all((self.print, self.copy, self.edit, self.annotate, self.fill_forms, self.assemble))

    @property
    def effective_owner(self) -> str:
        """Besitzerkennwort beim Schreiben – ohne eigenes gilt das Kennwort zum Öffnen."""
        return self.owner_password or self.user_password

    def encryption(self) -> pikepdf.Encryption:
        allow = pikepdf.Permissions(
            accessibility=True,
            extract=self.copy,
            modify_annotation=self.annotate,
            modify_assembly=self.assemble,
            modify_form=self.fill_forms,
            modify_other=self.edit,
            print_lowres=self.print,
            print_highres=self.print,
        )
        return pikepdf.Encryption(owner=self.effective_owner, user=self.user_password, R=6, aes=True, metadata=True, allow=allow)

    def summary(self) -> str:
        if not self.enabled:
            return "kein Kennwortschutz"
        parts = ["Kennwort zum Öffnen" if self.user_password else "ohne Kennwort zum Öffnen"]
        if self.restricted:
            names = {"print": "Drucken", "copy": "Kopieren", "edit": "Ändern", "annotate": "Kommentieren", "fill_forms": "Formulare ausfüllen", "assemble": "Seiten organisieren"}
            parts.append("eingeschränkt: " + ", ".join(label for key, label in names.items() if not getattr(self, key)))
        return ", ".join(parts)


NO_PROTECTION = Protection()


def problem(protection: Protection) -> str | None:
    """Verständlicher Grund, warum dieser Schutz so nicht geht – sonst ``None``."""
    for label, password in (("Kennwort zum Öffnen", protection.user_password), ("Berechtigungskennwort", protection.owner_password)):
        if password and len(password) < MIN_LENGTH:
            return f"Das {label} muss mindestens {MIN_LENGTH} Zeichen lang sein."
        if len(password.encode("utf-8")) > MAX_BYTES:
            return f"Das {label} ist zu lang (höchstens {MAX_BYTES} Byte)."
    if protection.restricted and not protection.owner_password:
        return "Für Einschränkungen ist ein Berechtigungskennwort nötig – sonst könnte jeder sie wieder aufheben."
    if protection.restricted and protection.owner_password == protection.user_password:
        return "Das Berechtigungskennwort muss sich vom Kennwort zum Öffnen unterscheiden."
    return None


def current(document: EditorDocument) -> dict:
    """Stand für den Dialog (ohne Kennwörter): geschützt, eingeschränkt, darf geändert werden."""
    plan = document.protection
    if plan is not None:
        protected, restricted = plan.enabled, plan.restricted
        allowed = plan if plan.enabled else NO_PROTECTION
        rights = {key: getattr(allowed, key) for key in ("print", "copy", "edit", "annotate", "fill_forms", "assemble")}
    else:
        protected = document.encrypted
        rights = _file_rights(document.pdf)
        restricted = not all(rights.values())
    return {
        "protected": protected,
        "restricted": restricted,
        "rights": rights,
        "pending": plan is not None,  # geändert, noch nicht gespeichert bzw. vom Dateistand abweichend
        "changeable": can_change(document),
    }


def can_change(document: EditorDocument) -> bool:
    return document.permissions == Permissions()


def unlock(document: EditorDocument, owner_password: str) -> bool:
    """Besitzerkennwort nachträglich eingeben: Stimmt es, gelten danach alle Rechte (auch für das
    Ändern des Schutzes). ``False`` bei falschem Kennwort – nichts wird geraten oder umgangen."""
    data = document.original_bytes()
    try:
        probe = pikepdf.open(io.BytesIO(data), password=owner_password)
    except pikepdf.PasswordError:
        return False
    try:
        if not getattr(probe, "owner_password_matched", False):
            return False
    finally:
        probe.close()
    document.permissions = Permissions()
    if document.read_only_reason == RESTRICTED_REASON:
        document.read_only_reason = ""
    document.password = owner_password
    return True



@dataclass
class ProtectionCommand:
    """Rückgängig machbare Änderung des Schutzes (ändert keine PDF-Objekte)."""

    title: str
    before: Protection | None
    after: Protection | None
    pages: tuple[int, ...] = ()
    structure: bool = False
    info: dict = field(default_factory=dict)
    state: int = 0
    previous: int = 0

    def undo(self, document: EditorDocument) -> None:
        document.protection = self.before
        document.state = self.previous

    def redo(self, document: EditorDocument) -> None:
        document.protection = self.after
        document.state = self.state


def set_protection(document: EditorDocument, history, protection: Protection) -> str:
    """Schutz für das nächste Speichern festlegen; liefert den Titel für »Rückgängig«."""
    from .commands import _states  # gemeinsame Standnummern aller Schritte

    if not can_change(document):
        raise EditorError("Den Kennwortschutz kann nur ändern, wer das Berechtigungskennwort kennt.")
    reason = problem(protection)
    if reason:
        raise EditorError(reason)
    title = "Kennwortschutz entfernen" if not protection.enabled else ("Kennwortschutz ändern" if document.encrypted else "Kennwortschutz festlegen")
    command = ProtectionCommand(title, document.protection, replace(protection))
    command.previous, command.state = document.state, next(_states)
    document.protection = command.after
    document.state = command.state
    history.push(command)
    return title


def _file_rights(pdf: pikepdf.Pdf) -> dict:
    if not pdf.is_encrypted:
        return {key: True for key in ("print", "copy", "edit", "annotate", "fill_forms", "assemble")}
    allow = pdf.allow
    return {
        "print": bool(allow.print_lowres or allow.print_highres),
        "copy": bool(allow.extract),
        "edit": bool(allow.modify_other),
        "annotate": bool(allow.modify_annotation),
        "fill_forms": bool(allow.modify_form or allow.modify_annotation),
        "assemble": bool(allow.modify_assembly or allow.modify_other),
    }
