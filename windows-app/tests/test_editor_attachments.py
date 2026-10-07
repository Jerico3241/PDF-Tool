"""PDF Editor – Anhänge: auflisten (Dokument und Seiten), speichern, zum Öffnen bereitstellen (nur sichere
Dateitypen), hinzufügen und entfernen – mit Rückgängig, Speichern und erneutem Öffnen. Alle Dokumente
sind künstlich (``editorsamples``)."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from pikepdf import Array, Dictionary, Name, String

import editorsamples as samples
from tools.pdf_editor import attachments, commands, save
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import ReadOnlyDocument, UnsupportedEdit


def names(doc: EditorDocument) -> list[str]:
    return [item.name for item in attachments.list_attachments(doc)]


def test_lists_document_attachment_with_size(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.structured(tmp_path / "s.pdf"))
    items = attachments.list_attachments(doc)
    assert [(item.name, item.page, item.size, item.openable) for item in items] == [("notiz.txt", -1, len(b"Anhang zum Test"), True)]
    assert attachments.read(doc, items[0].key) == ("notiz.txt", b"Anhang zum Test")


def test_page_file_attachment_annotation_is_listed(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "a.pdf", pages=2)
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        spec = pikepdf.AttachedFileSpec(pdf, b"x,y\n1,2\n", filename="werte.csv", mime_type="text/csv")
        annot = pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.FileAttachment, Rect=Array([50, 50, 70, 70]), FS=spec.obj, Contents=String("Tabelle")))
        pdf.pages[1].Annots = pdf.make_indirect(Array([annot]))
        pdf.save(path)
    doc = EditorDocument.open(path)
    items = attachments.list_attachments(doc)
    assert [(item.name, item.page) for item in items] == [("werte.csv", 1)]
    assert attachments.read(doc, items[0].key)[1] == b"x,y\n1,2\n"
    with pytest.raises(UnsupportedEdit):
        attachments.remove(doc, commands.History(), items[0].key)  # Kommentar: dort löschen


def test_save_to_writes_exact_bytes(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.structured(tmp_path / "s.pdf"))
    key = attachments.list_attachments(doc)[0].key
    target = attachments.save_to(doc, key, tmp_path / "out.txt")
    assert target.read_bytes() == b"Anhang zum Test"
    assert not list(tmp_path.glob(".pdftool-*.tmp"))


def test_programs_are_never_prepared_for_opening(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "p.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.attachments["setup.exe"] = pikepdf.AttachedFileSpec(pdf, b"MZ\x90\x00", filename="setup.exe")
        pdf.attachments["bild.png"] = pikepdf.AttachedFileSpec(pdf, b"\x89PNG\r\n", filename="bild.png")
        pdf.save(path)
    doc = EditorDocument.open(path)
    items = {item.name: item for item in attachments.list_attachments(doc)}
    assert items["setup.exe"].openable is False and items["bild.png"].openable is True
    with pytest.raises(UnsupportedEdit):
        attachments.export_for_opening(doc, items["setup.exe"].key, tmp_path)
    opened = attachments.export_for_opening(doc, items["bild.png"].key, tmp_path)
    assert opened.name == "bild.png" and opened.read_bytes() == b"\x89PNG\r\n"


def test_file_names_from_attachments_cannot_escape_the_folder(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "p.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.attachments["boese"] = pikepdf.AttachedFileSpec(pdf, b"text", filename="..\\..\\Windows\\notiz.txt")
        pdf.save(path)
    doc = EditorDocument.open(path)
    item = attachments.list_attachments(doc)[0]
    assert item.name == "notiz.txt"
    folder = tmp_path / "ziel"
    folder.mkdir()
    opened = attachments.export_for_opening(doc, item.key, folder)
    assert folder in opened.parents and opened.name == "notiz.txt"


def test_add_remove_undo_redo_and_save(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.structured(tmp_path / "s.pdf"))
    history = commands.History()
    extra = tmp_path / "Rechnung.pdf"
    extra.write_bytes(b"%PDF-1.4 Testinhalt")
    key = attachments.add(doc, history, extra, "Beleg")
    assert key == "n:Rechnung.pdf"
    assert names(doc) == ["Rechnung.pdf", "notiz.txt"]
    same_name = attachments.add(doc, history, extra)
    assert same_name == "n:Rechnung (2).pdf"
    history.undo(doc)
    history.undo(doc)
    assert names(doc) == ["notiz.txt"]
    history.redo(doc)
    assert names(doc) == ["Rechnung.pdf", "notiz.txt"]
    attachments.remove(doc, history, "n:notiz.txt")
    assert names(doc) == ["Rechnung.pdf"]
    target = tmp_path / "gespeichert.pdf"
    save.save(doc, target)
    again = EditorDocument.open(target)
    items = attachments.list_attachments(again)
    assert [(item.name, item.description) for item in items] == [("Rechnung.pdf", "Beleg")]
    assert attachments.read(again, items[0].key)[1] == b"%PDF-1.4 Testinhalt"
    with pikepdf.open(target) as pdf:  # auch andere Programme sehen genau diesen Anhang
        assert list(pdf.attachments) == ["Rechnung.pdf"]
    history.undo(doc)
    assert names(doc) == ["Rechnung.pdf", "notiz.txt"]


def test_removing_the_last_attachment_keeps_other_name_trees(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.structured(tmp_path / "s.pdf"))
    history = commands.History()
    attachments.remove(doc, history, "n:notiz.txt")
    assert names(doc) == []
    assert "/Dests" in doc.pdf.Root.Names  # Sprungziele bleiben
    target = tmp_path / "ohne.pdf"
    save.save(doc, target)
    with pikepdf.open(target) as pdf:
        assert len(pdf.attachments) == 0 and "/Dests" in pdf.Root.Names


def test_read_only_document_cannot_get_attachments(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.encrypted(tmp_path / "e.pdf", allow_edit=False), password="geheim")
    extra = tmp_path / "x.txt"
    extra.write_text("x")
    with pytest.raises(ReadOnlyDocument):
        attachments.add(doc, commands.History(), extra)
