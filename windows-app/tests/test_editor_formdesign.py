"""PDF Editor – Formulare gestalten: Felder anlegen (Textfeld, Kontrollkästchen, Optionsgruppe, Dropdown,
Liste), verschieben, Größe ändern, duplizieren, löschen und Eigenschaften ändern – mit Rückgängig, Ausfüllen,
Speichern und erneutem Öffnen. Alle Dokumente sind künstlich (``editorsamples``)."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

import editorsamples as samples
from tools.pdf_editor import commands, formdesign, forms, render, save
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import ReadOnlyDocument, UnsupportedEdit


def widgets(doc: EditorDocument) -> dict[str, list[formdesign.DesignWidget]]:
    found: dict[str, list] = {}
    for item in formdesign.list_widgets(doc):
        found.setdefault(item.name, []).append(item)
    return found


def fields(doc: EditorDocument) -> dict[str, forms.FieldInfo]:
    return {info.name: info for info in forms.list_fields(doc)}


def dark_pixels(doc: EditorDocument, rect, page: int = 0) -> int:
    geo = doc.geometry(page)
    picture = render.to_pil(render.render_page(doc, page, int(geo.width * 2))).convert("L")
    scale = picture.width / geo.width
    u0, v0, u1, v1 = geo.rect_to_view(rect)
    crop = picture.crop((int(u0 * scale) + 2, int(v0 * scale) + 2, int(u1 * scale) - 2, int(v1 * scale) - 2))
    return sum(1 for value in crop.tobytes() if value < 100)


def reopen(doc: EditorDocument, path: Path) -> EditorDocument:
    save.save(doc, path)
    return EditorDocument.open(path)


# --- Anlegen ----------------------------------------------------------------------------------------------------
def test_create_every_kind_in_a_pdf_without_form_then_fill_save_and_reopen(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "leer.pdf"))
    history = commands.History()
    try:
        assert formdesign.list_widgets(doc) == [] and "/AcroForm" not in doc.pdf.Root
        text = formdesign.create(doc, history, 0, "text", (72, 600, 272, 622))
        assert history.undo_title == "Textfeld hinzufügen"
        check = formdesign.create(doc, history, 0, "checkbox", (72, 560, 86, 574))
        radio = formdesign.create(doc, history, 0, "radio", (72, 520, 86, 534))
        second = formdesign.add_option(doc, history, radio)
        combo = formdesign.create(doc, history, 0, "combo", (72, 470, 222, 492))
        listbox = formdesign.create(doc, history, 0, "list", (72, 380, 222, 444), options=["Rot", "Grün", "Blau"])
        found = widgets(doc)
        assert {name: [item.kind for item in items] for name, items in found.items()} == {
            "Textfeld 1": ["text"], "Kontrollkästchen 1": ["checkbox"], "Optionsgruppe 1": ["radio", "radio"], "Auswahl 1": ["combo"], "Liste 1": ["list"]}
        assert [item.export for item in found["Optionsgruppe 1"]] == ["Option 1", "Option 2"]
        assert found["Optionsgruppe 1"][1].rect[3] < found["Optionsgruppe 1"][0].rect[1]  # neue Option darunter
        assert found["Auswahl 1"][0].options == formdesign.DEFAULT_OPTIONS and found["Liste 1"][0].options == ("Rot", "Grün", "Blau")
        assert found["Kontrollkästchen 1"][0].export == "Ja" and all(item.ours for items in found.values() for item in items)
        assert {text, check, radio, second, combo, listbox} == {item.key for items in found.values() for item in items}
        # Die neuen Felder lassen sich ausfüllen wie jedes andere Formular
        info = fields(doc)
        assert all(entry.editable for entry in info.values())
        assert info["Optionsgruppe 1"].on_values == ("/Option 1", "/Option 2")
        forms.set_value(doc, history, info["Textfeld 1"].key, "Erika Musterfrau")
        forms.set_value(doc, history, info["Kontrollkästchen 1"].key, True)
        forms.set_value(doc, history, info["Optionsgruppe 1"].key, "/Option 2")
        forms.set_value(doc, history, info["Auswahl 1"].key, "Option 2")
        forms.set_value(doc, history, info["Liste 1"].key, "Blau")
        assert dark_pixels(doc, found["Textfeld 1"][0].rect) > 20
        assert dark_pixels(doc, found["Kontrollkästchen 1"][0].rect) > 4
        assert dark_pixels(doc, found["Optionsgruppe 1"][1].rect) > dark_pixels(doc, found["Optionsgruppe 1"][0].rect)
        again = reopen(doc, tmp_path / "formular.pdf")
        try:
            values = {name: entry.value for name, entry in fields(again).items()}
            assert values == {"Textfeld 1": "Erika Musterfrau", "Kontrollkästchen 1": True, "Optionsgruppe 1": "/Option 2", "Auswahl 1": "Option 2", "Liste 1": "Blau"}
        finally:
            again.close()
        with pikepdf.open(tmp_path / "formular.pdf") as pdf:
            assert pdf.check_pdf_syntax() == []  # strukturell einwandfrei
            fonts_in_form = pdf.Root.AcroForm.DR.Font
            assert "/Helv" in fonts_in_form and "/ZaDb" in fonts_in_form
            assert len(pdf.Root.AcroForm.Fields) == 5
        # Rückgängig bis zum Anfang: kein Formular mehr
        while history.can_undo:
            history.undo(doc)
        assert formdesign.list_widgets(doc) == [] and "/AcroForm" not in doc.pdf.Root
        assert doc.dirty  # gespeichert wurde der Stand mit den Feldern
    finally:
        doc.close()


def test_new_fields_get_free_names_and_valid_sizes(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    history = commands.History()
    try:
        first = formdesign.create(doc, history, 0, "text", (300, 300, 400, 320))
        formdesign.create(doc, history, 0, "text", (300, 260, 400, 280), name="Telefon")
        names = set(widgets(doc))
        assert {"Textfeld 1", "Telefon", "name", "ok", "versand", "land", "farben"} <= names
        with pytest.raises(UnsupportedEdit, match="gibt es schon"):
            formdesign.create(doc, history, 0, "text", (300, 200, 400, 220), name="name")
        with pytest.raises(UnsupportedEdit, match="Punkt"):
            formdesign.create(doc, history, 0, "text", (300, 200, 400, 220), name="a.b")
        with pytest.raises(UnsupportedEdit, match="zu klein"):
            formdesign.create(doc, history, 0, "checkbox", (300, 200, 303, 203))
        with pytest.raises(UnsupportedEdit):
            formdesign.create(doc, history, 0, "signature", (300, 200, 400, 220))
        assert first in {item.key for items in widgets(doc).values() for item in items}
    finally:
        doc.close()


def test_rotated_page_gets_upright_fields(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "quer.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.pages[0].Rotate = 90
        pdf.save(path)
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        key = formdesign.create(doc, history, 0, "text", (100, 100, 130, 300))
        _item, annot, _annots, _kind, _page = formdesign._locate(doc, key)
        assert int(annot.MK.R) == 90
        bbox = [float(v) for v in annot.AP.N.BBox]
        assert bbox[2] == pytest.approx(200) and bbox[3] == pytest.approx(30)  # Breite und Höhe wie angezeigt
    finally:
        doc.close()


# --- Verschieben, Größe, Duplizieren, Löschen -----------------------------------------------------------------------
def test_move_and_resize_with_undo(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    history = commands.History()
    try:
        name = widgets(doc)["name"][0]
        formdesign.move(doc, history, [name.key], 10, -20)
        assert history.undo_title == "Feld verschieben"
        assert widgets(doc)["name"][0].rect == pytest.approx((150, 725, 350, 745))
        formdesign.resize(doc, history, name.key, (150, 700, 450, 745))
        moved = widgets(doc)["name"][0]
        assert moved.rect == pytest.approx((150, 700, 450, 745))
        _item, annot, _annots, _kind, _page = formdesign._locate(doc, name.key)
        assert [float(v) for v in annot.AP.N.BBox] == pytest.approx([0, 0, 300, 45])  # Erscheinungsbild passt
        forms.set_value(doc, history, fields(doc)["name"].key, "Breit")
        assert dark_pixels(doc, moved.rect) > 10
        history.undo(doc)
        history.undo(doc)
        history.undo(doc)
        assert widgets(doc)["name"][0].rect == pytest.approx(name.rect)
        with pytest.raises(UnsupportedEdit, match="zu klein"):
            formdesign.resize(doc, history, name.key, (150, 700, 152, 745))
    finally:
        doc.close()


def test_duplicate_makes_an_independent_field_and_a_new_radio_option(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    history = commands.History()
    try:
        forms.set_value(doc, history, fields(doc)["name"].key, "Original")
        source = widgets(doc)["name"][0]
        [copy] = formdesign.duplicate(doc, history, [source.key], 0, -40)
        assert history.undo_title == "Feld duplizieren"
        found = widgets(doc)
        assert found["name 2"][0].key == copy and found["name 2"][0].rect == pytest.approx((source.rect[0], source.rect[1] - 40, source.rect[2], source.rect[3] - 40))
        info = fields(doc)
        assert info["name 2"].value == "Original"  # Wert und Aussehen wie das Original
        forms.set_value(doc, history, info["name 2"].key, "Kopie")
        assert fields(doc)["name"].value == "Original"  # unabhängig
        # Optionsfeld: neue Option in derselben Gruppe
        post = next(item for item in widgets(doc)["versand"] if item.export == "post")
        [option] = formdesign.duplicate(doc, history, [post.key], 60, 0)
        group = widgets(doc)["versand"]
        assert [item.export for item in group] == ["post", "mail", "Option 3"] and group[2].key == option
        forms.set_value(doc, history, fields(doc)["versand"].key, "/Option 3")
        assert fields(doc)["versand"].value == "/Option 3"
        again = reopen(doc, tmp_path / "kopiert.pdf")
        try:
            assert {name: entry.value for name, entry in fields(again).items() if name in ("name", "name 2", "versand")} == {"name": "Original", "name 2": "Kopie", "versand": "/Option 3"}
        finally:
            again.close()
    finally:
        doc.close()


def test_delete_option_whole_group_and_field_with_undo(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    history = commands.History()
    try:
        mail = next(item for item in widgets(doc)["versand"] if item.export == "mail")
        formdesign.delete(doc, history, [mail.key])
        assert history.undo_title == "Feld löschen"
        assert [item.export for item in widgets(doc)["versand"]] == ["post"]
        land = widgets(doc)["land"][0]
        formdesign.delete(doc, history, [land.key, widgets(doc)["versand"][0].key])
        assert history.undo_title == "Felder löschen"
        assert "land" not in widgets(doc) and "versand" not in widgets(doc) and set(fields(doc)) == {"name", "ok", "farben"}
        annots = doc.pdf.pages[0].Annots
        assert all(entry.objgen != (int(land.key.split("-")[0]), int(land.key.split("-")[1])) for entry in annots)
        again = reopen(doc, tmp_path / "geloescht.pdf")
        try:
            assert set(fields(again)) == {"name", "ok", "farben"}
        finally:
            again.close()
        history.undo(doc)
        history.undo(doc)
        assert set(fields(doc)) == {"name", "ok", "versand", "land", "farben"}
        assert [item.export for item in widgets(doc)["versand"]] == ["post", "mail"]
    finally:
        doc.close()


def test_selected_radio_option_deleted_clears_the_value(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    history = commands.History()
    try:
        assert fields(doc)["versand"].value == "/post"
        post = next(item for item in widgets(doc)["versand"] if item.export == "post")
        formdesign.delete(doc, history, [post.key])
        assert fields(doc)["versand"].value == ""
    finally:
        doc.close()


# --- Eigenschaften ----------------------------------------------------------------------------------------------
def test_text_field_properties(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    history = commands.History()
    try:
        key = widgets(doc)["name"][0].key
        formdesign.set_properties(doc, history, key, {"name": "Vorname", "tooltip": "Bitte den Vornamen eintragen", "required": True, "fontSize": 14, "align": "center"})
        assert history.undo_title == "Feldeigenschaften ändern"
        item = widgets(doc)["Vorname"][0]
        assert (item.tooltip, item.required, item.font_size, item.align) == ("Bitte den Vornamen eintragen", True, 14.0, "center")
        assert fields(doc)["Vorname"].required
        forms.set_value(doc, history, fields(doc)["Vorname"].key, "Zeile eins\nZeile zwei")
        assert fields(doc)["Vorname"].value == "Zeile eins Zeile zwei"  # einzeilig
        formdesign.set_properties(doc, history, key, {"multiline": True})
        forms.set_value(doc, history, fields(doc)["Vorname"].key, "Zeile eins\nZeile zwei")
        assert fields(doc)["Vorname"].value == "Zeile eins\nZeile zwei" and widgets(doc)["Vorname"][0].multiline
        with pytest.raises(UnsupportedEdit, match="länger als 5 Zeichen"):
            formdesign.set_properties(doc, history, key, {"maxLength": 5})
        formdesign.set_properties(doc, history, key, {"multiline": False, "maxLength": 40})
        assert fields(doc)["Vorname"].value == "Zeile eins Zeile zwei" and fields(doc)["Vorname"].max_length == 40
        formdesign.set_properties(doc, history, key, {"readOnly": True})
        assert not fields(doc)["Vorname"].editable and widgets(doc)["Vorname"][0].read_only
        with pytest.raises(UnsupportedEdit, match="gibt es schon"):
            formdesign.set_properties(doc, history, key, {"name": "ok"})
        with pytest.raises(UnsupportedEdit):
            formdesign.set_properties(doc, history, key, {"options": ["a"]})
        with pytest.raises(UnsupportedEdit):
            formdesign.set_properties(doc, history, key, {"farbe": "rot"})
        while history.can_undo:
            history.undo(doc)
        assert "name" in widgets(doc) and not widgets(doc)["name"][0].required and not doc.dirty
    finally:
        doc.close()


def test_choice_options_export_values_border_and_background(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    history = commands.History()
    try:
        land = widgets(doc)["land"][0].key
        formdesign.set_properties(doc, history, land, {"options": ["Deutschland", "Frankreich", "  ", "Deutschland"]})
        assert widgets(doc)["land"][0].options == ("Deutschland", "Frankreich") and fields(doc)["land"].value == "Deutschland"
        formdesign.set_properties(doc, history, land, {"options": ["Italien", "Spanien"]})
        assert fields(doc)["land"].value == ""  # bisheriger Wert gibt es nicht mehr
        forms.set_value(doc, history, fields(doc)["land"].key, "Spanien")
        with pytest.raises(UnsupportedEdit, match="mindestens eine Option"):
            formdesign.set_properties(doc, history, land, {"options": [" "]})
        # Kontrollkästchen: Exportwert
        ok = widgets(doc)["ok"][0].key
        formdesign.set_properties(doc, history, ok, {"export": "Zustimmung"})
        assert widgets(doc)["ok"][0].export == "Zustimmung"
        forms.set_value(doc, history, fields(doc)["ok"].key, True)
        assert str(doc.pdf.get_object(*map(int, ok.split("-"))).V) == "/Zustimmung"
        with pytest.raises(UnsupportedEdit, match="Off"):
            formdesign.set_properties(doc, history, ok, {"export": "Off"})
        # Optionsfeld: Exportwerte bleiben in der Gruppe eindeutig
        post, mail = widgets(doc)["versand"]
        with pytest.raises(UnsupportedEdit, match="andere Option"):
            formdesign.set_properties(doc, history, mail.key, {"export": "post"})
        formdesign.set_properties(doc, history, post.key, {"export": "Brief"})
        assert fields(doc)["versand"].value == "/Brief" and [item.export for item in widgets(doc)["versand"]] == ["Brief", "mail"]
        # Rahmen und Hintergrund
        name = widgets(doc)["name"][0].key
        formdesign.set_properties(doc, history, name, {"border": False, "background": False})
        assert not widgets(doc)["name"][0].border and not widgets(doc)["name"][0].background
        formdesign.set_properties(doc, history, name, {"border": True})
        assert widgets(doc)["name"][0].border
        again = reopen(doc, tmp_path / "eigenschaften.pdf")
        try:
            values = {entry.name: entry.value for entry in forms.list_fields(again)}
            assert values["land"] == "Spanien" and values["ok"] is True and values["versand"] == "/Brief"
        finally:
            again.close()
    finally:
        doc.close()


# --- Grenzen -----------------------------------------------------------------------------------------------------
def test_permissions_and_xfa_block_the_designer(tmp_path: Path) -> None:
    locked = EditorDocument.open(samples.encrypted(tmp_path / "e.pdf", allow_edit=False), password="geheim")
    try:
        with pytest.raises(ReadOnlyDocument):
            formdesign.create(locked, commands.History(), 0, "text", (72, 600, 272, 622))
    finally:
        locked.close()
    path = samples.form(tmp_path / "xfa.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.Root.AcroForm.XFA = pdf.make_stream(b"<xdp:xdp xmlns:xdp='http://ns.adobe.com/xdp/'/>")
        pdf.save(path)
    xfa = EditorDocument.open(path)
    try:
        with pytest.raises(UnsupportedEdit, match="XFA"):
            formdesign.create(xfa, commands.History(), 0, "text", (72, 300, 272, 322))
    finally:
        xfa.close()


def test_signature_fields_can_be_moved_but_not_duplicated(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.signed(tmp_path / "s.pdf"))
    history = commands.History()
    try:
        signature = next(item for items in widgets(doc).values() for item in items if item.kind == "signature")
        with pytest.raises(UnsupportedEdit, match="nicht duplizieren"):
            formdesign.duplicate(doc, history, [signature.key], 0, -30)
        formdesign.move(doc, history, [signature.key], 0, -30)
        assert next(item for items in widgets(doc).values() for item in items if item.kind == "signature").rect[1] == pytest.approx(signature.rect[1] - 30)
    finally:
        doc.close()
