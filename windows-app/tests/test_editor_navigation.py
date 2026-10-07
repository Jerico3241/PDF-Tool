"""Lesezeichen bearbeiten, Links setzen und auflösen, Seiten zuschneiden.

Lesezeichen: hinzufügen, umbenennen, verschieben, Ebene ändern, löschen – PDFium sieht danach
dieselbe Gliederung (Titel, Ebenen, Ziele). Links: Seitenziel und Webadresse, benannte Ziele
fremder PDFs, nur sichere Adressen. Zuschneiden: Ränder in der Anzeige, auch auf gedrehten Seiten.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Array, Dictionary, Name, String

import editorsamples as samples
from tools.pdf_editor import commands, crop, links, outline, save
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import EditorError


@pytest.fixture(autouse=True)
def no_lxml(monkeypatch):
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)


def entries(doc: EditorDocument) -> list[tuple[int, str, int]]:
    return [(entry.level, entry.title, entry.page) for entry in outline.read_outline(doc)]


# --- Lesezeichen ----------------------------------------------------------------------------------------------------
def test_bookmarks_add_rename_move_indent_and_delete_like_pdfium_sees_them(tmp_path: Path) -> None:
    path = samples.structured(tmp_path / "Handbuch.pdf")  # Kapitel 1 (→ Abschnitt 1.1), Kapitel 2
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        assert entries(doc) == [(0, "Kapitel 1", 0), (1, "Abschnitt 1.1", 1), (0, "Kapitel 2", 2)]
        new = outline.add_bookmark(doc, history, "Anhang", 2, after=2)
        assert new == 3 and entries(doc)[-1] == (0, "Anhang", 2)
        outline.rename_bookmark(doc, history, 3, "Anhang A")
        assert outline.move_bookmark(doc, history, 3, "up") == 2
        assert entries(doc)[2] == (0, "Anhang A", 2)
        assert outline.move_bookmark(doc, history, 2, "in") == 2  # Unterpunkt von Kapitel 1
        assert entries(doc) == [(0, "Kapitel 1", 0), (1, "Abschnitt 1.1", 1), (1, "Anhang A", 2), (0, "Kapitel 2", 2)]
        outline.set_bookmark_page(doc, history, 2, 0)
        assert entries(doc)[2] == (1, "Anhang A", 0)
        assert outline.move_bookmark(doc, history, 2, "out") == 2  # direkt hinter Kapitel 1 samt Abschnitt
        outline.delete_bookmark(doc, history, 0)  # Kapitel 1 samt Abschnitt 1.1
        assert entries(doc) == [(0, "Anhang A", 0), (0, "Kapitel 2", 2)]
        assert history.undo_title == "Lesezeichen löschen"
        save.save(doc, path)
        for _ in range(7):
            history.undo(doc)
        assert entries(doc) == [(0, "Kapitel 1", 0), (1, "Abschnitt 1.1", 1), (0, "Kapitel 2", 2)]
    finally:
        doc.close()
    reopened = EditorDocument.open(path)
    try:
        assert entries(reopened) == [(0, "Anhang A", 0), (0, "Kapitel 2", 2)]
    finally:
        reopened.close()


def test_first_bookmark_in_a_document_without_outline(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "ohne.pdf", pages=2))
    history = commands.History()
    try:
        assert outline.add_bookmark(doc, history, "", 1) == 0
        assert entries(doc) == [(0, "Seite 2", 1)]
        outline.delete_bookmark(doc, history, 0)
        assert entries(doc) == [] and "/Outlines" not in doc.pdf.Root
        with pytest.raises(EditorError):
            outline.rename_bookmark(doc, history, 5, "x")
    finally:
        doc.close()


# --- Links ------------------------------------------------------------------------------------------------------------
def test_links_to_pages_and_web_addresses_and_named_destinations(tmp_path: Path) -> None:
    path = samples.structured(tmp_path / "Links.pdf")  # vorhandener Link → Seite 3 (Index 2)
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        named = pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([72, 100, 200, 120]), A=Dictionary(S=Name.GoTo, D=String("ende"))))
        script = pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([72, 140, 200, 160]), A=Dictionary(S=Name.URI, URI=String("javascript:alert(1)"))))
        pdf.pages[1].Annots = pdf.make_indirect(Array([named, script]))
        pdf.save(path, fix_metadata_version=False)
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        existing = links.list_links(doc, 0)
        assert [(link.target_page, link.uri) for link in existing] == [(2, "")]
        foreign = links.list_links(doc, 1)
        assert [(link.target_page, link.uri) for link in foreign] == [(2, ""), (-1, "")]  # benanntes Ziel; Skript ohne Ziel
        key = links.add_link(doc, history, 0, (300.0, 700.0, 450.0, 720.0), uri="www.example.org/preise")
        web = next(link for link in links.list_links(doc, 0) if link.key == key)
        assert web.uri == "https://www.example.org/preise" and web.ours
        assert links.link_at(doc, 0, 310, 710).key == key and links.link_at(doc, 0, 10, 10) is None
        links.update_link(doc, history, key, target_page=1)
        assert links.link_at(doc, 0, 310, 710).target_page == 1
        mail = links.add_link(doc, history, 0, (300.0, 600.0, 450.0, 620.0), uri="info@example.org")
        assert next(link for link in links.list_links(doc, 0) if link.key == mail).uri == "mailto:info@example.org"
        links.delete_link(doc, history, mail)
        assert len(links.list_links(doc, 0)) == 2
        for bad in ("file:///C:/Windows/system32/cmd.exe", "javascript:alert(1)", "https://a b"):
            with pytest.raises(EditorError):
                links.add_link(doc, history, 0, (10.0, 10.0, 50.0, 50.0), uri=bad)
        save.save(doc, path)
    finally:
        doc.close()
    assert save.structure_of(pikepdf.open(path)).links == 4  # Seite 1: zwei, Seite 2: zwei


# --- Zuschneiden --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("rotate", [0, 90])
def test_crop_margins_apply_in_the_view_and_can_be_reset(tmp_path: Path, rotate: int) -> None:
    path = samples.direct_image(tmp_path / "Scan.pdf", rotate=rotate)
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        before = doc.geometry(0)
        assert crop.crop_pages(doc, history, [0], (50.0, 20.0, 10.0, 30.0)) == 1
        after = doc.geometry(0)
        assert abs(after.width - (before.width - 60)) < 0.01 and abs(after.height - (before.height - 50)) < 0.01
        margins = crop.content_margins(doc, 0)
        assert all(value >= 0 for value in margins) and margins[0] > 0
        with pytest.raises(EditorError):
            crop.crop_pages(doc, history, [0], (400.0, 0.0, 400.0, 0.0))
        assert crop.reset_crop(doc, history, [0]) == 1
        assert abs(doc.geometry(0).width - before.width) < 0.01
        history.undo(doc)
        assert abs(doc.geometry(0).width - after.width) < 0.01
    finally:
        doc.close()
