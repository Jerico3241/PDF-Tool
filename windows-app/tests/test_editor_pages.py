"""PDF Editor – Seiten organisieren: drehen, löschen (mit aufgelösten Verweisen), duplizieren, leere
Seite, verschieben, aus PDF einfügen, anhängen, extrahieren, teilen – mit Rückgängig und Speichern.
Alle Dokumente sind künstlich (``editorsamples``)."""

from __future__ import annotations

import io
from pathlib import Path

import pikepdf
import pytest

import editorsamples as samples
from tools.pdf_editor import commands, pages, save, textlayer
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import EditorError, PasswordRequired, ReadOnlyDocument, SaveFailed, UnsupportedEdit


def texts(doc: EditorDocument) -> list[str]:
    return [textlayer.text(doc, index).split("\n")[0] for index in range(doc.page_count)]


def numbered(path: Path, count: int, prefix: str = "Seite") -> Path:
    return samples.standard_text(path, pages=count, lines=(f"{prefix}-Dokument", "Zweite Zeile", "Dritte Zeile")) if count else path


def footers(doc: EditorDocument) -> list[str]:
    return [textlayer.text(doc, index).strip().split("\n")[-1] for index in range(doc.page_count)]


def page_objects_in(data: bytes) -> int:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return sum(1 for obj in pdf.objects if isinstance(obj, pikepdf.Dictionary) and obj.get("/Type") == pikepdf.Name.Page)


# --- Seitenangaben -----------------------------------------------------------------------------------
def test_parse_pages() -> None:
    assert pages.parse_pages("1-3, 5", 10) == [0, 1, 2, 4]
    assert pages.parse_pages("8-", 10) == [7, 8, 9]
    assert pages.parse_pages("-2; 2", 10) == [0, 1]
    for bad in ("", "0", "11", "3-2", "a"):
        with pytest.raises(ValueError):
            pages.parse_pages(bad, 10)
    assert pages.every(5, 2) == [[0, 1], [2, 3], [4]]


# --- Drehen ------------------------------------------------------------------------------------------
def test_rotate_selected_pages_and_undo(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.rotated(tmp_path / "r.pdf"))
    history = commands.History()
    try:
        pages.rotate(doc, history, [0, 1], 90)
        assert [doc.geometry(i).rotation for i in range(4)] == [90, 180, 180, 270]
        pages.rotate(doc, history, [3], -90)
        assert doc.geometry(3).rotation == 180
        history.undo(doc)
        history.undo(doc)
        assert [doc.geometry(i).rotation for i in range(4)] == [0, 90, 180, 270]
        with pytest.raises(ValueError):
            pages.rotate(doc, history, [0], 45)
    finally:
        doc.close()


# --- Löschen -----------------------------------------------------------------------------------------
def test_delete_pages_and_undo(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf", pages=5))
    history = commands.History()
    try:
        pages.delete(doc, history, [1, 3])
        assert footers(doc) == ["Seite 1 von 5", "Seite 3 von 5", "Seite 5 von 5"]
        history.undo(doc)
        assert footers(doc) == [f"Seite {n} von 5" for n in range(1, 6)]
        with pytest.raises(UnsupportedEdit):
            pages.delete(doc, history, range(5))
    finally:
        doc.close()


def test_delete_detaches_bookmarks_links_and_named_destinations(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.structured(tmp_path / "s.pdf"))
    history = commands.History()
    try:
        notes = pages.delete(doc, history, [2])  # Ziel von »Kapitel 2«, des Links und von »ende«
        assert any("kein Ziel mehr" in note for note in notes)
        data = doc.serialize()
        assert page_objects_in(data) == 2  # keine verwaiste Seite in der Datei
        with pikepdf.open(io.BytesIO(data)) as pdf:
            with pdf.open_outline() as outline:
                titles = [(item.title, item.destination) for item in outline.root]
            assert titles[0][0] == "Kapitel 1" and titles[0][1] is not None
            assert titles[1] == ("Kapitel 2", None)
            link = [annot for annot in pdf.pages[0].Annots if annot.Subtype == "/Link"][0]
            assert "/Dest" not in link and "/A" not in link
            assert len(pdf.Root.Names.Dests.Names) == 0
        history.undo(doc)
        with pikepdf.open(io.BytesIO(doc.serialize())) as pdf:
            with pdf.open_outline() as outline:
                assert outline.root[1].destination is not None
            assert len(pdf.Root.Names.Dests.Names) == 2 and "/Dest" in pdf.pages[0].Annots[0]
    finally:
        doc.close()


def test_delete_page_with_form_fields_removes_them(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        pages.insert_from(doc, history, 1, pages.open_source(samples.form(tmp_path / "f.pdf")))
        before = save.structure_of(doc.pdf).fields
        assert before > 0
        notes = pages.delete(doc, history, [1])
        assert save.structure_of(doc.pdf).fields == 0 and any("Formularfelder" in note for note in notes)
        history.undo(doc)
        assert save.structure_of(doc.pdf).fields == before
    finally:
        doc.close()


# --- Duplizieren, leere Seite, verschieben -------------------------------------------------------------
def test_duplicate_copies_annotations_but_not_form_fields(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.structured(tmp_path / "s.pdf"))
    history = commands.History()
    try:
        pages.duplicate(doc, history, [0])
        assert doc.page_count == 4 and footers(doc)[:2] == ["Seite 1 von 3", "Seite 1 von 3"]
        first, copy = doc.pdf.pages[0].obj, doc.pdf.pages[1].obj
        assert first.objgen != copy.objgen and first.Annots.objgen != copy.Annots.objgen
        assert all(annot.P.objgen == copy.objgen for annot in copy.Annots)
        assert all("/P" not in annot or annot.P.objgen == first.objgen for annot in first.Annots)  # Original unverändert
        history.undo(doc)
        assert doc.page_count == 3
    finally:
        doc.close()
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    try:
        notes = pages.duplicate(doc, commands.History(), [0])
        assert "/Annots" not in doc.pdf.pages[1].obj and any("Formularfelder" in note for note in notes)
    finally:
        doc.close()


def test_blank_page_takes_the_size_of_its_neighbour(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.rotated(tmp_path / "r.pdf"))
    history = commands.History()
    try:
        pages.insert_blank(doc, history, 2)  # Nachbar: Seite mit /Rotate 180 – Hochformat
        geo = doc.geometry(2)
        assert (round(geo.width), round(geo.height), geo.rotation) == (595, 842, 0)
        pages.insert_blank(doc, history, 0, (842, 595))
        assert (round(doc.geometry(0).width), round(doc.geometry(0).height)) == (842, 595)
        assert textlayer.text(doc, 0) == "" and doc.page_count == 7
    finally:
        doc.close()


def test_move_pages(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf", pages=5))
    history = commands.History()
    try:
        assert pages.move(doc, history, [0, 1], 5) == [3, 4]
        assert [f.split()[1] for f in footers(doc)] == ["3", "4", "5", "1", "2"]
        assert pages.move(doc, history, [4], 0) == [0]
        assert [f.split()[1] for f in footers(doc)] == ["2", "3", "4", "5", "1"]
        history.undo(doc)
        history.undo(doc)
        assert [f.split()[1] for f in footers(doc)] == ["1", "2", "3", "4", "5"]
    finally:
        doc.close()


# --- Einfügen, Anhängen --------------------------------------------------------------------------------
def test_insert_pages_from_another_pdf_and_save(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "a.pdf", pages=2)
    other = samples.standard_text(tmp_path / "b.pdf", pages=3, lines=("Andere Datei", "x", "y"))
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        source = pages.open_source(other)
        pages.insert_from(doc, history, 1, source, [0, 2])
        assert texts(doc) == ["Rechnung Nr. 4711 vom 01.10.2026", "Andere Datei", "Andere Datei", "Rechnung Nr. 4711 vom 01.10.2026"]
        assert footers(doc)[1:3] == ["Seite 1 von 3", "Seite 3 von 3"]
        source.close()  # das Dokument hält seine Quelle selbst offen
        save.save(doc, path)
    finally:
        doc.close()
    again = EditorDocument.open(path)
    try:
        assert again.page_count == 4 and texts(again)[1] == "Andere Datei"
    finally:
        again.close()


def test_inserted_form_fields_keep_working_and_conflicting_names_are_renamed(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    history = commands.History()
    try:
        own = save.structure_of(doc.pdf).fields
        pages.insert_from(doc, history, 1, pages.open_source(samples.form(tmp_path / "g.pdf")))
        names = [str(field.get("/T")) for field in doc.pdf.Root.AcroForm.Fields]
        assert save.structure_of(doc.pdf).fields == 2 * own
        assert len(names) == len(set(names))  # keine doppelten Feldnamen
        history.undo(doc)
        assert save.structure_of(doc.pdf).fields == own
    finally:
        doc.close()


def test_merge_appends_several_files_in_one_step(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        sources = [pages.open_source(samples.standard_text(tmp_path / f"{n}.pdf", pages=n, lines=(f"Datei {n}", "x", "y"))) for n in (1, 2)]
        pages.merge(doc, history, sources)
        assert texts(doc) == ["Rechnung Nr. 4711 vom 01.10.2026", "Datei 1", "Datei 2", "Datei 2"]
        assert history.undo_title == "PDFs anhängen"
        history.undo(doc)
        assert doc.page_count == 1
    finally:
        doc.close()


def test_open_source_requires_password_and_rejects_damaged_files(tmp_path: Path) -> None:
    locked = samples.encrypted(tmp_path / "e.pdf")
    with pytest.raises(PasswordRequired) as missing:
        pages.open_source(locked)
    assert not missing.value.wrong
    with pytest.raises(PasswordRequired) as wrong:
        pages.open_source(locked, "falsch")
    assert wrong.value.wrong
    pages.open_source(locked, "geheim").close()
    with pytest.raises(EditorError, match="beschädigt"):
        pages.open_source(samples.damaged(tmp_path / "d.pdf"))
    plain = tmp_path / "text.pdf"
    plain.write_text("kein PDF")
    with pytest.raises(EditorError, match="keine PDF"):
        pages.open_source(plain)


# --- Extrahieren, Teilen ---------------------------------------------------------------------------------
def test_extract_writes_a_new_file_and_leaves_the_document_unchanged(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "a.pdf", pages=4)
    doc = EditorDocument.open(path)
    try:
        original = path.read_bytes()
        target = pages.extract(doc, [1, 3], tmp_path / "auszug.pdf")
        with pikepdf.open(target) as out:
            assert len(out.pages) == 2 and str(out.docinfo.get("/Title")) == "Testdokument"
        assert not doc.dirty and doc.page_count == 4 and path.read_bytes() == original
        with pytest.raises(SaveFailed, match="bereits"):
            pages.extract(doc, [0], target)  # nie überschreiben
        with pytest.raises(SaveFailed):
            pages.extract(doc, [0], path)
    finally:
        doc.close()


def test_extract_respects_permissions(tmp_path: Path) -> None:
    source = samples.standard_text(tmp_path / "offen.pdf")
    locked = tmp_path / "gesperrt.pdf"
    with pikepdf.open(source) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(user="geheim", owner="besitzer", R=6, allow=pikepdf.Permissions(extract=False)))
    doc = EditorDocument.open(locked, password="geheim")
    try:
        with pytest.raises(ReadOnlyDocument):
            pages.extract(doc, [0], tmp_path / "x.pdf")
        assert not (tmp_path / "x.pdf").exists()
    finally:
        doc.close()


def test_split_into_files_without_overwriting(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf", pages=3))
    out = tmp_path / "teile"
    out.mkdir()
    (out / "Vertrag_Teil1.pdf").write_bytes(b"vorhanden")
    try:
        written = pages.split(doc, pages.every(3, 1), out, "Vertrag")
        assert [p.name for p in written] == ["Vertrag_Teil1 (2).pdf", "Vertrag_Teil2.pdf", "Vertrag_Teil3.pdf"]
        assert (out / "Vertrag_Teil1.pdf").read_bytes() == b"vorhanden"
        for number, path in enumerate(written, 1):
            check = EditorDocument.open(path)
            try:
                assert footers(check) == [f"Seite {number} von 3"]
            finally:
                check.close()
    finally:
        doc.close()


def test_organized_document_saves_with_validation(tmp_path: Path) -> None:
    path = samples.structured(tmp_path / "s.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        pages.rotate(doc, history, [1], 90)
        pages.duplicate(doc, history, [1])
        pages.move(doc, history, [0], 4)
        pages.insert_blank(doc, history, 0)
        pages.delete(doc, history, [0])
        result = save.save(doc, path)
        assert result.checked_pages == 4
    finally:
        doc.close()
    with pikepdf.open(path) as pdf:
        assert len(pdf.pages) == 4 and pdf.check_pdf_syntax() == []
        assert "notiz.txt" in pdf.attachments
