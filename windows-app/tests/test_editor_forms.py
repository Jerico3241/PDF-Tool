"""PDF Editor – Formulare ausfüllen: Text, Kontrollkästchen, Optionsfeld, Auswahl- und Listenfeld,
Erscheinungsbild, Schreibschutz, Berechtigungen, Rückgängig und Speichern (künstliches Formular)."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pikepdf.form
import pytest

import editorsamples as samples
from tools.pdf_editor import commands, fonts, forms, render, save
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import ReadOnlyDocument, UnsupportedEdit


@pytest.fixture(autouse=True)
def vera_as_system_font(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDFTOOL_FONT_DIRS", str(samples.vera_path().parent))
    fonts.find_system_font.cache_clear()
    yield
    fonts.find_system_font.cache_clear()


def by_name(doc: EditorDocument) -> dict[str, forms.FieldInfo]:
    return {info.name: info for info in forms.list_fields(doc)}


def dark_pixels(doc: EditorDocument, rect, page: int = 0) -> int:
    geo = doc.geometry(page)
    picture = render.to_pil(render.render_page(doc, page, int(geo.width * 2))).convert("L")
    scale = picture.width / geo.width
    u0, v0, u1, v1 = geo.rect_to_view(rect)
    crop = picture.crop((int(u0 * scale) + 3, int(v0 * scale) + 3, int(u1 * scale) - 3, int(v1 * scale) - 3))
    return sum(1 for value in crop.tobytes() if value < 100)


def test_fields_are_listed_with_kind_value_options_and_place(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    try:
        fields = by_name(doc)
        assert {name: info.kind for name, info in fields.items()} == {"name": "text", "ok": "checkbox", "versand": "radio", "land": "combo", "farben": "list"}
        assert fields["ok"].value is False and fields["versand"].value == "/post" and fields["land"].value == "Deutschland"
        assert [display for _export, display in fields["land"].options] == ["Deutschland", "Österreich", "Schweiz"]
        assert fields["versand"].on_values == ("/post", "/mail")
        assert fields["name"].widgets[0].page == 0 and [round(v) for v in fields["name"].widgets[0].rect] == [140, 745, 340, 765]
        assert all(info.editable for info in fields.values())
    finally:
        doc.close()


def test_fill_all_kinds_and_undo(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    history = commands.History()
    try:
        fields = by_name(doc)
        empty = dark_pixels(doc, fields["name"].widgets[0].rect)
        forms.set_value(doc, history, fields["name"].key, "Erika Musterfrau")
        forms.set_value(doc, history, fields["ok"].key, True)
        forms.set_value(doc, history, fields["versand"].key, "mail")
        forms.set_value(doc, history, fields["land"].key, "Schweiz")
        forms.set_value(doc, history, fields["farben"].key, "Blau")
        after = by_name(doc)
        assert (after["name"].value, after["ok"].value, after["versand"].value, after["land"].value, after["farben"].value) == ("Erika Musterfrau", True, "/mail", "Schweiz", "Blau")
        assert dark_pixels(doc, fields["name"].widgets[0].rect) > empty + 50  # Text sichtbar
        kids = doc.pdf.Root.AcroForm.Fields
        radio = next(f for f in kids if str(f.get("/T")) == "versand")
        assert [str(kid.AS) for kid in radio.Kids] == ["/Off", "/mail"]
        assert "/NeedAppearances" not in doc.pdf.Root.AcroForm or not doc.pdf.Root.AcroForm.NeedAppearances
        for _ in range(5):
            history.undo(doc)
        before = by_name(doc)
        assert (before["name"].value, before["ok"].value, before["versand"].value, before["land"].value) == ("", False, "/post", "Deutschland")
    finally:
        doc.close()


def test_values_survive_saving_and_are_read_by_other_libraries(tmp_path: Path) -> None:
    path = samples.form(tmp_path / "f.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        fields = by_name(doc)
        forms.set_value(doc, history, fields["name"].key, "Łukasz Beispiel")  # außerhalb von WinAnsi
        forms.set_value(doc, history, fields["ok"].key, True)
        save.save(doc, path)
    finally:
        doc.close()
    with pikepdf.open(path) as pdf:
        values = {name: field.value for name, field in pikepdf.form.Form(pdf).items()}
        assert str(values["name"]) == "Łukasz Beispiel" and str(values["ok"]) == "/Yes"
        widget = next(f for f in pdf.Root.AcroForm.Fields if str(f.get("/T")) == "name")
        assert "/PTF1" in widget.AP.N.Resources.Font  # eingebettete Teilmenge für »Ł«
        assert pdf.check_pdf_syntax() == []


def test_read_only_password_and_limits(tmp_path: Path) -> None:
    path = samples.form(tmp_path / "f.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        for item in pdf.Root.AcroForm.Fields:
            if str(item.get("/T")) == "land":
                item.Ff = int(item.get("/Ff", 0)) | forms.FLAG_READ_ONLY
            if str(item.get("/T")) == "name":
                item.MaxLen = 5
        pdf.save(path)
    doc = EditorDocument.open(path)
    try:
        fields = by_name(doc)
        assert not fields["land"].editable and "schreibgeschützt" in fields["land"].reason
        with pytest.raises(UnsupportedEdit):
            forms.set_value(doc, commands.History(), fields["land"].key, "Schweiz")
        with pytest.raises(UnsupportedEdit, match="Höchstens 5"):
            forms.set_value(doc, commands.History(), fields["name"].key, "zu lang")
        with pytest.raises(UnsupportedEdit, match="gibt es"):
            forms.set_value(doc, commands.History(), fields["farben"].key, "Lila")
    finally:
        doc.close()


def test_filling_respects_permissions(tmp_path: Path) -> None:
    source = samples.form(tmp_path / "f.pdf")
    locked = tmp_path / "gesperrt.pdf"
    with pikepdf.open(source) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(user="geheim", owner="besitzer", R=6, allow=pikepdf.Permissions(modify_form=False, modify_annotation=False, modify_other=False)))
    doc = EditorDocument.open(locked, password="geheim")
    try:
        fields = by_name(doc)
        assert not fields["name"].editable
        with pytest.raises(ReadOnlyDocument):
            forms.set_value(doc, commands.History(), fields["name"].key, "x")
    finally:
        doc.close()


def test_document_without_form(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    try:
        assert forms.list_fields(doc) == []
    finally:
        doc.close()
