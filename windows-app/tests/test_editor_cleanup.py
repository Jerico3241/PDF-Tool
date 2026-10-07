"""Dokument bereinigen und Reduzieren (Formulare und Kommentare fest übernehmen).

Bereinigen entfernt nur, was gewählt ist – Links, Lesezeichen und Sprungziele bleiben. Reduzieren
übernimmt Felder und Kommentare so in die Seite, dass sie gleich aussehen (Vergleich der gerenderten
Seite vorher/nachher), und entfernt danach die Anmerkungen und das Formular. Beides ist ein Schritt
für Rückgängig und übersteht das sichere Speichern (Strukturprüfung, Neuöffnen).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pikepdf
import pypdfium2
import pytest
from pikepdf import Array, Dictionary, Name, String

import editorsamples as samples
from tools.pdf_editor import annotations, commands, flatten, forms, sanitize, save
from tools.pdf_editor.document import EditorDocument


@pytest.fixture(autouse=True)
def no_lxml(monkeypatch):
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)


def with_scripts(path: Path) -> Path:
    """Wie ``structured``, dazu JavaScript (Dokument, beim Öffnen, Seitenereignis, Link),
    Miniaturbild und private Programmdaten."""
    samples.structured(path)
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        script = pdf.make_indirect(Dictionary(S=Name.JavaScript, JS=String("app.alert('Test');")))
        names = pdf.Root.Names
        names.JavaScript = Dictionary(Names=Array([String("hallo"), script]))
        pdf.Root.OpenAction = Dictionary(S=Name.JavaScript, JS=String("this.print();"))
        pdf.pages[1].AA = Dictionary(O=Dictionary(S=Name.JavaScript, JS=String("1;")))
        js_link = pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([72, 100, 200, 120]), Border=Array([0, 0, 0]), A=Dictionary(S=Name.JavaScript, JS=String("2;"))))
        pdf.pages[1].Annots = pdf.make_indirect(Array([js_link]))
        pdf.pages[0].Thumb = pdf.make_stream(b"\x00" * 12, Width=2, Height=2, ColorSpace=Name.DeviceRGB, BitsPerComponent=8)
        pdf.Root.PieceInfo = Dictionary(Programm=Dictionary(LastModified=String("D:20260101000000")))
        pdf.save(path, fix_metadata_version=False)
    return path


def render(doc: EditorDocument, page: int = 0):
    from tools.pdf_editor import render as render_mod

    return render_mod.to_pil(render_mod.render_page(doc, page, 300))


def difference(a, b) -> float:
    """Mittlere Abweichung zweier Seitenbilder (0 = gleich, 255 = völlig verschieden)."""
    from PIL import ImageChops, ImageStat

    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


# --- Bereinigen ---------------------------------------------------------------------------------------------------
def test_clean_removes_scripts_metadata_attachments_and_hidden_data_but_keeps_navigation(tmp_path: Path) -> None:
    path = with_scripts(tmp_path / "Weitergabe.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        found = sanitize.inspect(doc)
        assert found.metadata >= 2 and found.javascript >= 4 and found.attachments == 1 and found.comments == 1 and found.hidden >= 2
        before = save.structure_of(doc.pdf)
        removed = sanitize.clean(doc, history, sanitize.CleanOptions())
        assert removed.javascript == found.javascript and removed.attachments == 1 and removed.comments == 0
        assert history.undo_title == "Dokument bereinigen" and doc.dirty
        root = doc.pdf.Root
        assert "/Metadata" not in root and "/OpenAction" not in root and "/PieceInfo" not in root
        assert "/JavaScript" not in root.Names and "/EmbeddedFiles" not in root.Names and "/Dests" in root.Names
        assert not len(doc.pdf.docinfo.keys()) and len(doc.pdf.attachments) == 0
        assert "/AA" not in doc.pdf.pages[1].obj and "/Thumb" not in doc.pdf.pages[0].obj
        links = [a for a in doc.pdf.pages[1].obj.Annots if a.Subtype == Name.Link]
        assert len(links) == 1 and "/A" not in links[0]  # Link bleibt, nur ohne Skript
        after = save.structure_of(doc.pdf)
        assert (after.outline, after.links, after.named_dests, after.annotations) == (before.outline, before.links, before.named_dests, before.annotations)
        save.save(doc, tmp_path / "bereinigt.pdf")
        history.undo(doc)
        assert save.structure_of(doc.pdf) == before and doc.dirty  # wieder wie vorher – anders als die gespeicherte Datei
    finally:
        doc.close()
    with pikepdf.open(tmp_path / "bereinigt.pdf") as pdf:
        assert "/Metadata" not in pdf.Root and len(pdf.attachments) == 0 and "/OpenAction" not in pdf.Root
        assert len(pdf.Root.Names.Dests.Names) == 2


def test_clean_comments_only_when_chosen_and_nothing_to_do_is_no_step(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.structured(tmp_path / "s.pdf"))
    history = commands.History()
    try:
        removed = sanitize.clean(doc, history, sanitize.CleanOptions(metadata=False, javascript=False, attachments=False, comments=True, hidden=False))
        assert removed.comments == 1 and removed.total == 1
        subtypes = [str(a.Subtype) for a in doc.pdf.pages[0].obj.Annots]
        assert subtypes == ["/Link"]
    finally:
        doc.close()
    plain = EditorDocument.open(samples.standard_text(tmp_path / "leer.pdf"))
    history = commands.History()
    try:
        removed = sanitize.clean(plain, history, sanitize.CleanOptions(metadata=False))
        assert removed.total == 0 and not history.can_undo and not plain.dirty
    finally:
        plain.close()


# --- Reduzieren -----------------------------------------------------------------------------------------------------
def test_flatten_form_keeps_the_look_removes_fields_and_survives_saving(tmp_path: Path) -> None:
    path = samples.form(tmp_path / "Antrag.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        fields = {info.name: info for info in forms.list_fields(doc)}
        forms.set_value(doc, history, fields["name"].key, "Erika Mustermann")
        forms.set_value(doc, history, fields["ok"].key, True)
        before = render(doc)
        assert flatten.count(doc)["fields"] == 6
        result = flatten.flatten(doc, history, fields=True, comments=False)
        assert result.fields == 6 and result.skipped == 0
        assert history.undo_title == "Reduzieren"
        assert "/AcroForm" not in doc.pdf.Root and "/Annots" not in doc.pdf.pages[0].obj
        assert difference(before, render(doc)) < 1.0  # sieht aus wie vorher
        save.save(doc, tmp_path / "Antrag reduziert.pdf")
        history.undo(doc)
        assert forms.list_fields(doc) and doc.dirty
    finally:
        doc.close()
    with pikepdf.open(tmp_path / "Antrag reduziert.pdf") as pdf:
        assert "/AcroForm" not in pdf.Root and "/Annots" not in pdf.pages[0].obj
    view = pypdfium2.PdfDocument(str(tmp_path / "Antrag reduziert.pdf"))
    try:
        assert "Erika Mustermann" in view[0].get_textpage().get_text_range()
    finally:
        view.close()


def test_flatten_comments_with_opacity_keeps_links_and_skips_annotations_without_appearance(tmp_path: Path) -> None:
    path = samples.structured(tmp_path / "Kommentiert.pdf")  # Notiz ohne Erscheinungsbild, Link
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        annotations.add_shape(doc, history, 0, annotations.SQUARE, (300.0, 600.0, 420.0, 660.0), style=annotations.Style(color=(229, 57, 53), width=3.0, fill=(255, 235, 59)))
        annotations.add_markup(doc, history, 0, annotations.HIGHLIGHT, [(72.0, 755.0, 300.0, 775.0)])
        before = render(doc)
        result = flatten.flatten(doc, history, fields=False, comments=True)
        assert result.comments == 2 and result.skipped == 1
        left = [str(a.Subtype) for a in doc.pdf.pages[0].obj.Annots]
        assert sorted(left) == ["/Link", "/Text"]
        assert difference(before, render(doc)) < 1.5
    finally:
        doc.close()


def test_hidden_annotations_are_removed_and_signature_fields_stay(tmp_path: Path) -> None:
    path = samples.signed(tmp_path / "signiert.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        hidden = pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Square, Rect=Array([10, 10, 50, 50]), F=2))
        annots = pdf.pages[0].obj.get("/Annots")
        pdf.pages[0].Annots = pdf.make_indirect(Array([*(list(annots) if annots is not None else []), hidden]))
        pdf.save(path)
    doc = EditorDocument.open(path)
    try:
        result = flatten.flatten(doc, commands.History(), fields=True, comments=True)
        assert result.hidden == 1 and result.skipped >= 1
        assert any(a.get("/Subtype") == Name.Widget for a in doc.pdf.pages[0].obj.Annots)
        assert "/AcroForm" in doc.pdf.Root
    finally:
        doc.close()
