"""Kennwortschutz: festlegen, ändern, entfernen – nur mit allen Rechten, wirksam beim Speichern.

Geprüft wird an echten Dateien: Nach dem Speichern öffnet sich das PDF nur mit dem Kennwort, die
Berechtigungen stehen in der Datei, Rückgängig vor dem Speichern lässt die Datei, wie sie war. Ein
eingeschränktes PDF lässt sich erst nach dem richtigen Berechtigungskennwort ändern.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pikepdf
import pytest

import editorsamples as samples
from tools.pdf_editor import commands, protect, save
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import EditorError


@pytest.fixture(autouse=True)
def no_lxml(monkeypatch):
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)


def test_password_and_restrictions_apply_on_save_and_undo_before_saving_keeps_the_file(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "Angebot.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        assert protect.can_change(doc) and not doc.encrypted
        wanted = protect.Protection(user_password="Lese-2026", owner_password="Chef-2026", print=True, copy=False, edit=False)
        title = protect.set_protection(doc, history, wanted)
        assert title == "Kennwortschutz festlegen" and doc.dirty and doc.encrypted
        assert history.undo_title == "Kennwortschutz festlegen"
        history.undo(doc)
        assert not doc.dirty and not doc.encrypted and doc.protection is None
        history.redo(doc)
        save.save(doc, path, backup_dir=tmp_path / "sicherungen")
        assert not doc.dirty
    finally:
        doc.close()
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(path)
    with pikepdf.open(path, password="Lese-2026") as pdf:
        assert pdf.is_encrypted and pdf.encryption.R == 6
        assert not pdf.owner_password_matched
        assert pdf.allow.print_highres and not pdf.allow.extract and not pdf.allow.modify_other
    with pikepdf.open(path, password="Chef-2026") as pdf:
        assert pdf.owner_password_matched
    reopened = EditorDocument.open(path, password="Lese-2026")
    try:
        assert reopened.read_only and not protect.can_change(reopened)
        assert reopened.permissions.print and not reopened.permissions.copy
    finally:
        reopened.close()


def test_opening_password_alone_also_guards_the_owner_rights(tmp_path: Path) -> None:
    """Ohne eigenes Berechtigungskennwort gilt das Kennwort zum Öffnen – ein leeres Besitzerkennwort
    würde die Datei sonst ohne Kennwort öffnen."""
    path = samples.standard_text(tmp_path / "Vertrag.pdf")
    doc = EditorDocument.open(path)
    try:
        protect.set_protection(doc, commands.History(), protect.Protection(user_password="nur-ich"))
        save.save(doc, tmp_path / "Vertrag geschützt.pdf")
    finally:
        doc.close()
    for attempt in ("", None):
        with pytest.raises(pikepdf.PasswordError):
            pikepdf.open(tmp_path / "Vertrag geschützt.pdf", password=attempt or "")
    with pikepdf.open(tmp_path / "Vertrag geschützt.pdf", password="nur-ich") as pdf:
        assert pdf.owner_password_matched


def test_removing_the_protection_needs_the_owner_password_and_writes_an_open_file(tmp_path: Path) -> None:
    path = samples.encrypted(tmp_path / "geheim.pdf", allow_edit=False)
    doc = EditorDocument.open(path, password="geheim")  # nur Kennwort zum Öffnen: eingeschränkt
    history = commands.History()
    try:
        assert doc.read_only and not protect.can_change(doc)
        assert not protect.current(doc)["changeable"]
        with pytest.raises(EditorError):
            protect.set_protection(doc, history, protect.NO_PROTECTION)
        assert not protect.unlock(doc, "falsch") and doc.read_only
        assert protect.unlock(doc, "besitzer")
        assert protect.can_change(doc) and not doc.read_only
        assert protect.set_protection(doc, history, protect.NO_PROTECTION) == "Kennwortschutz entfernen"
        assert not doc.encrypted
        save.save(doc, tmp_path / "offen.pdf")
    finally:
        doc.close()
    with pikepdf.open(tmp_path / "offen.pdf") as pdf:
        assert not pdf.is_encrypted and len(pdf.pages) == 1


def test_changed_password_holds_for_later_saves_and_the_recovery_copy(tmp_path: Path) -> None:
    path = samples.encrypted(tmp_path / "alt.pdf")
    doc = EditorDocument.open(path, password="besitzer")
    history = commands.History()
    try:
        assert protect.can_change(doc)
        protect.set_protection(doc, history, protect.Protection(user_password="neu-1234"))
        save.save(doc, path)
        # Weitere Änderung und erneutes Speichern: weiter das neue Kennwort, nie wieder das alte
        from tools.pdf_editor import pages

        pages.rotate(doc, history, [0], 90)
        save.save(doc, path)
        recovery_copy = doc.serialize(keep_encryption=True)
    finally:
        doc.close()
    for data in (path.read_bytes(), recovery_copy):
        with pytest.raises(pikepdf.PasswordError):
            pikepdf.open(__import__("io").BytesIO(data), password="geheim")
        with pikepdf.open(__import__("io").BytesIO(data), password="neu-1234") as pdf:
            assert pdf.is_encrypted
    with pikepdf.open(path, password="neu-1234") as pdf:
        assert int(pdf.pages[0].obj.get("/Rotate", 0)) == 90


@pytest.mark.parametrize(
    ("wanted", "reason"),
    [
        (protect.Protection(user_password="abc"), "mindestens 4"),
        (protect.Protection(owner_password="x" * 200), "zu lang"),
        (protect.Protection(user_password="lesen", copy=False), "Berechtigungskennwort nötig"),
        (protect.Protection(user_password="gleich", owner_password="gleich", print=False), "unterscheiden"),
    ],
)
def test_impossible_protection_is_explained(wanted: protect.Protection, reason: str) -> None:
    assert reason in (protect.problem(wanted) or "")


def test_summary_and_dialog_state_do_not_contain_passwords(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    try:
        protect.set_protection(doc, commands.History(), protect.Protection(user_password="Geheim-99", owner_password="Chef-99", print=False))
        state = protect.current(doc)
        assert state["protected"] and state["restricted"] and state["pending"]
        assert not state["rights"]["print"] and state["rights"]["copy"]
        text = repr(state) + doc.protection.summary()
        assert "Geheim-99" not in text and "Chef-99" not in text
        assert "eingeschränkt: Drucken" in doc.protection.summary()
    finally:
        doc.close()
