"""PDF Editor – Bilder: auswählen, verschieben, skalieren, drehen, löschen, ersetzen, einfügen (PNG
mit Transparenz, JPEG unverändert), Ebene, auf gedrehten Seiten aufrecht, Rückgängig, Speichern."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

import editorsamples as samples
from tools.pdf_editor import commands, images, render, save
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import UnsupportedEdit


def rounded(rect) -> tuple[int, ...]:
    return tuple(round(v) for v in rect)


def pixel(doc: EditorDocument, page: int, x: float, y: float) -> tuple[int, int, int]:
    """Farbe an einem Punkt der Seite (Seitenkoordinaten) bei 2 px/pt."""
    geo = doc.geometry(page)
    image = render.to_pil(render.render_page(doc, page, int(geo.width * 2)))
    scale = image.width / geo.width
    u, v = geo.to_view(x, y)
    return image.getpixel((int(u * scale), int(v * scale)))


def view_pixel(doc: EditorDocument, page: int, u: float, v: float) -> tuple[int, int, int]:
    geo = doc.geometry(page)
    image = render.to_pil(render.render_page(doc, page, int(geo.width * 2)))
    scale = image.width / geo.width
    return image.getpixel((int(u * scale), int(v * scale)))


def close(a, b, tolerance: int = 40) -> bool:
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


GREEN = (30, 160, 60)
WHITE = (255, 255, 255)


# --- Erkennen -------------------------------------------------------------------------------------------
def test_images_drawn_directly_inline_and_as_image_forms_are_found(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.direct_image(tmp_path / "d.pdf"))
    try:
        (item,) = images.list_images(doc, 0)
        assert (item.kind, item.pixels, rounded(item.bounds), item.editable, item.ours) == ("image", (40, 20), (100, 500, 300, 600), True, False)
    finally:
        doc.close()
    doc = EditorDocument.open(samples.with_images(tmp_path / "w.pdf"))  # ReportLab: JPEG und PNG mit Maske
    try:
        found = images.list_images(doc, 0)
        assert [(it.kind, it.pixels, rounded(it.bounds)) for it in found] == [("image", (120, 80), (72, 600, 252, 720)), ("image", (64, 64), (320, 600, 416, 696))]
        assert all(it.editable for it in found)
    finally:
        doc.close()
    doc = EditorDocument.open(samples.image_in_form(tmp_path / "f.pdf"))
    try:
        (form,) = images.list_images(doc, 0)
        assert (form.kind, form.pixels, rounded(form.bounds), form.editable) == ("form", (30, 20), (72, 600, 252, 720), True)
    finally:
        doc.close()
    doc = EditorDocument.open(samples.complex_content(tmp_path / "k.pdf"))
    try:
        (inline,) = images.list_images(doc, 0)
        assert inline.kind == "inline" and rounded(inline.bounds) == (72, 600, 172, 650)
    finally:
        doc.close()
    doc = EditorDocument.open(samples.form_xobject_text(tmp_path / "x.pdf"))  # Formular mit Text: kein Bild
    try:
        assert images.list_images(doc, 0) == []
    finally:
        doc.close()


# --- Verschieben, Größe, Drehen ------------------------------------------------------------------------
def test_move_resize_rotate_and_undo(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.direct_image(tmp_path / "d.pdf"))
    history = commands.History()
    try:
        images.move_by(doc, history, 0, 0, 50, -100)
        assert rounded(images.list_images(doc, 0)[0].bounds) == (150, 400, 350, 500)
        assert close(pixel(doc, 0, 250, 450), GREEN) and close(pixel(doc, 0, 120, 580), WHITE)
        images.fit(doc, history, 0, 0, (150, 400, 250, 450))
        assert rounded(images.list_images(doc, 0)[0].bounds) == (150, 400, 250, 450)
        images.rotate_by(doc, history, 0, 0, 90)
        assert rounded(images.list_images(doc, 0)[0].bounds) == (175, 375, 225, 475)
        assert "Bildunterschrift" in render_text(doc)
        for _ in range(3):
            history.undo(doc)
        assert rounded(images.list_images(doc, 0)[0].bounds) == (100, 500, 300, 600)
        history.redo(doc)
        assert rounded(images.list_images(doc, 0)[0].bounds) == (150, 400, 350, 500)
    finally:
        doc.close()


def render_text(doc: EditorDocument) -> str:
    from tools.pdf_editor import textlayer

    return textlayer.text(doc, 0)


def test_repeated_moves_reuse_the_placement_instead_of_nesting(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.direct_image(tmp_path / "d.pdf"))
    history = commands.History()
    try:
        for _ in range(20):
            images.move_by(doc, history, 0, 0, 1, 1)
        ops = [str(i.operator) for i in pikepdf.parse_content_stream(doc.pdf.pages[0]) if not isinstance(i, pikepdf.ContentStreamInlineImage)]
        assert ops.count("q") == 1 and ops.count("cm") == 1
        assert rounded(images.list_images(doc, 0)[0].bounds) == (120, 520, 320, 620)
    finally:
        doc.close()


def test_image_forms_and_inline_images_can_be_moved(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.with_images(tmp_path / "w.pdf"))
    history = commands.History()
    try:
        images.move_by(doc, history, 0, 1, -200, 0)
        assert rounded(images.list_images(doc, 0)[1].bounds) == (120, 600, 216, 696)
    finally:
        doc.close()
    doc = EditorDocument.open(samples.image_in_form(tmp_path / "f.pdf"))
    history = commands.History()
    try:
        images.fit(doc, history, 0, 0, (100, 100, 190, 160))
        assert rounded(images.list_images(doc, 0)[0].bounds) == (100, 100, 190, 160)
        images.delete(doc, history, 0, 0)
        assert images.list_images(doc, 0) == [] and "/Fm1" not in doc.pdf.pages[0].Resources.XObject
    finally:
        doc.close()
    doc = EditorDocument.open(samples.complex_content(tmp_path / "k.pdf"))
    history = commands.History()
    try:
        images.move_by(doc, history, 0, 0, 0, -100)
        assert rounded(images.list_images(doc, 0)[0].bounds) == (72, 500, 172, 550)
        assert sum(isinstance(i, pikepdf.ContentStreamInlineImage) for i in pikepdf.parse_content_stream(doc.pdf.pages[0])) == 1
    finally:
        doc.close()


# --- Löschen, Ersetzen -------------------------------------------------------------------------------------
def test_delete_removes_drawing_and_unused_resource(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.direct_image(tmp_path / "d.pdf"))
    history = commands.History()
    try:
        images.delete(doc, history, 0, 0)
        assert images.list_images(doc, 0) == [] and close(pixel(doc, 0, 200, 550), WHITE)
        assert "/Im1" not in doc.pdf.pages[0].Resources.XObject
        assert "Bildunterschrift" in render_text(doc)
        history.undo(doc)
        assert len(images.list_images(doc, 0)) == 1 and close(pixel(doc, 0, 200, 550), GREEN)
    finally:
        doc.close()


def test_replace_keeps_place_layer_and_aspect_ratio(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.direct_image(tmp_path / "d.pdf"))  # Platz 200 × 100
    history = commands.History()
    try:
        images.replace(doc, history, 0, 0, samples.photo_jpeg(tmp_path / "p.jpg", (80, 80)))  # quadratisch
        (item,) = images.list_images(doc, 0)
        assert rounded(item.bounds) == (150, 500, 250, 600) and item.pixels == (80, 80)
        assert "/Im1" not in doc.pdf.pages[0].Resources.XObject
        assert close(pixel(doc, 0, 200, 550), (200, 120, 40)) and close(pixel(doc, 0, 120, 550), WHITE)
        history.undo(doc)
        assert images.list_images(doc, 0)[0].pixels == (40, 20)
    finally:
        doc.close()
    doc = EditorDocument.open(samples.image_in_form(tmp_path / "f.pdf"))  # Bild-Formular 180 × 120
    history = commands.History()
    try:
        images.replace(doc, history, 0, 0, samples.two_tone_png(tmp_path / "t.png"))  # 3:2 – füllt den Platz
        (item,) = images.list_images(doc, 0)
        assert (item.kind, rounded(item.bounds), item.pixels) == ("image", (72, 600, 252, 720), (60, 40))
        assert close(pixel(doc, 0, 160, 700), (255, 0, 0)) and close(pixel(doc, 0, 160, 620), (0, 0, 255))
        images.move_by(doc, history, 0, 0, 0, -300)
        assert rounded(images.list_images(doc, 0)[0].bounds) == (72, 300, 252, 420)
    finally:
        doc.close()


# --- Einfügen -------------------------------------------------------------------------------------------------
def test_insert_png_with_transparency(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.direct_image(tmp_path / "d.pdf"))
    history = commands.History()
    try:
        geo = doc.geometry(0)
        # über das grüne Bild legen: rechtes Drittel durchsichtig → dort bleibt Grün sichtbar
        u0, v0 = geo.to_view(100, 600)
        index = images.insert(doc, history, 0, samples.two_tone_png(tmp_path / "t.png", alpha=True), (u0, v0, u0 + 150, v0 + 100))
        item = images.list_images(doc, 0)[index]
        assert item.ours and item.pixels == (60, 40) and rounded(item.bounds) == (100, 500, 250, 600)
        assert close(pixel(doc, 0, 120, 590), (255, 0, 0)) and close(pixel(doc, 0, 120, 510), (0, 0, 255))
        assert close(pixel(doc, 0, 240, 550), GREEN)  # durchsichtig
        stream = doc.pdf.pages[0].Resources.XObject["/PTI1"]
        assert "/SMask" in stream and stream.Filter == "/FlateDecode"
        history.undo(doc)
        assert len(images.list_images(doc, 0)) == 1 and "/PTI1" not in doc.pdf.pages[0].Resources.XObject
    finally:
        doc.close()


def test_insert_jpeg_keeps_the_original_data(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    try:
        photo = samples.photo_jpeg(tmp_path / "p.jpg")
        images.insert(doc, commands.History(), 0, photo, (100, 100, 260, 220))
        stream = doc.pdf.pages[0].Resources.XObject["/PTI1"]
        assert stream.Filter == "/DCTDecode" and stream.read_raw_bytes() == photo.read_bytes()
    finally:
        doc.close()


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_inserted_image_is_upright_on_rotated_pages(tmp_path: Path, rotation: int) -> None:
    doc = EditorDocument.open(samples.direct_image(tmp_path / "d.pdf", rotate=rotation))
    try:
        images.insert(doc, commands.History(), 0, samples.two_tone_png(tmp_path / "t.png"), (300, 100, 420, 180))
        assert close(view_pixel(doc, 0, 360, 110), (255, 0, 0))  # oben rot
        assert close(view_pixel(doc, 0, 360, 170), (0, 0, 255))  # unten blau
        item = images.list_images(doc, 0)[-1]
        assert rounded(doc.geometry(0).rect_to_view(item.bounds)) == (300, 100, 420, 180)
    finally:
        doc.close()


def test_only_png_and_jpeg_are_accepted(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    try:
        gif = tmp_path / "x.gif"
        from PIL import Image

        Image.new("RGB", (10, 10)).save(gif, "GIF")
        with pytest.raises(UnsupportedEdit, match="PNG"):
            images.insert(doc, commands.History(), 0, gif, (0, 0, 50, 50))
        broken = tmp_path / "kaputt.png"
        broken.write_bytes(b"\x89PNG kaputt")
        with pytest.raises(UnsupportedEdit):
            images.insert(doc, commands.History(), 0, broken, (0, 0, 50, 50))
    finally:
        doc.close()


def test_arrange_only_inserted_images(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.direct_image(tmp_path / "d.pdf"))
    history = commands.History()
    try:
        geo = doc.geometry(0)
        u0, v0 = geo.to_view(100, 600)
        index = images.insert(doc, history, 0, samples.photo_jpeg(tmp_path / "p.jpg"), (u0, v0, u0 + 200, v0 + 100))
        assert close(pixel(doc, 0, 200, 550), (200, 120, 40))  # eingefügtes Bild liegt oben
        images.arrange(doc, history, 0, index, front=False)
        assert close(pixel(doc, 0, 200, 550), GREEN)  # jetzt dahinter
        moved = [it for it in images.list_images(doc, 0) if it.ours][0]
        images.arrange(doc, history, 0, moved.index, front=True)
        assert close(pixel(doc, 0, 200, 550), (200, 120, 40))
        original = [it for it in images.list_images(doc, 0) if not it.ours][0]
        with pytest.raises(UnsupportedEdit, match="eingefügte"):
            images.arrange(doc, history, 0, original.index, front=True)
    finally:
        doc.close()


def test_image_edits_save_and_validate(tmp_path: Path) -> None:
    path = samples.with_images(tmp_path / "w.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        images.move_by(doc, history, 0, 0, 10, 10)
        images.delete(doc, history, 0, 1)
        images.insert(doc, history, 0, samples.two_tone_png(tmp_path / "t.png", alpha=True), (300, 300, 420, 380))
        save.save(doc, path)
    finally:
        doc.close()
    again = EditorDocument.open(path)
    try:
        assert len(images.list_images(again, 0)) == 2
        with pikepdf.open(path) as pdf:
            assert pdf.check_pdf_syntax() == []
    finally:
        again.close()
