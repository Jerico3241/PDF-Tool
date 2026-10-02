"""PDF Editor – Anmerkungen: markieren, unterstreichen, durchstreichen, Notiz, Freihand, Formen,
Linie/Pfeil, Textfeld – mit Erscheinungsbild, Ändern, Verschieben, Löschen, Rückgängig, Speichern.
Alle Dokumente sind künstlich (``editorsamples``)."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

import editorsamples as samples
from tools.pdf_editor import annotations as notes
from tools.pdf_editor import commands, fonts, render, save, textlayer
from tools.pdf_editor.annotations import Style
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import ReadOnlyDocument, UnsupportedEdit


@pytest.fixture(autouse=True)
def vera_as_system_font(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDFTOOL_FONT_DIRS", str(samples.vera_path().parent))
    fonts.find_system_font.cache_clear()
    yield
    fonts.find_system_font.cache_clear()


def image(doc: EditorDocument, page: int = 0):
    geo = doc.geometry(page)
    return render.to_pil(render.render_page(doc, page, int(geo.width * 2))), 2 * geo.width / geo.width


def pixel(doc: EditorDocument, x: float, y: float, page: int = 0) -> tuple[int, int, int]:
    geo = doc.geometry(page)
    picture = render.to_pil(render.render_page(doc, page, int(geo.width * 2)))
    scale = picture.width / geo.width
    u, v = geo.to_view(x, y)
    return picture.getpixel((int(u * scale), int(v * scale)))


def close(a, b, tolerance: int = 45) -> bool:
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def selection(doc: EditorDocument, text: str, page: int = 0):
    hit = textlayer.search(doc, page, text)[0]
    return list(hit.rects)


# --- Markieren, Unterstreichen, Durchstreichen ---------------------------------------------------------------
def test_highlight_keeps_text_readable_and_is_listed(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        rects = selection(doc, "Gesamtbetrag")
        key = notes.add_markup(doc, history, 0, notes.HIGHLIGHT, rects, contents="Prüfen")
        (info,) = notes.list_annotations(doc, 0)
        assert (info.key, info.label, info.contents, info.color, info.ours) == (key, "Markierung", "Prüfen", (255, 235, 59), True)
        x0, y0, x1, y1 = rects[0]
        assert close(pixel(doc, x0 + 1, y1 - 1), (255, 235, 59))  # gelb hinterlegt
        annot = doc.pdf.pages[0].Annots[0]
        assert len(annot.QuadPoints) == 8 and "/AP" in annot and annot.F == 4
        assert "/T" not in annot  # kein Autor ohne ausdrückliche Angabe
        history.undo(doc)
        assert notes.list_annotations(doc, 0) == []
        history.redo(doc)
        assert len(notes.list_annotations(doc, 0)) == 1
    finally:
        doc.close()


@pytest.mark.parametrize("kind,label", [(notes.UNDERLINE, "Unterstreichung"), (notes.STRIKEOUT, "Durchstreichung")])
def test_underline_and_strikeout(tmp_path: Path, kind: str, label: str) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    try:
        notes.add_markup(doc, commands.History(), 0, kind, selection(doc, "Rechnung"), style=Style(color=(0, 160, 0)))
        (info,) = notes.list_annotations(doc, 0)
        assert info.label == label and info.color == (0, 160, 0)
        with pytest.raises(UnsupportedEdit):
            notes.add_markup(doc, commands.History(), 0, kind, [])
    finally:
        doc.close()


# --- Notiz, Freihand, Formen, Linien ---------------------------------------------------------------------------------
def test_note_ink_shapes_and_arrow(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        notes.add_note(doc, history, 0, 400, 500, "Rückruf nötig")
        notes.add_ink(doc, history, 0, [[(100, 300), (150, 320), (200, 300)], [(100, 280), (200, 280)]], style=Style(color=(0, 0, 255), width=3))
        notes.add_shape(doc, history, 0, notes.SQUARE, (300, 300, 380, 360), style=Style(color=(255, 0, 0), fill=(0, 200, 0)))
        notes.add_shape(doc, history, 0, notes.CIRCLE, (420, 300, 500, 360))
        notes.add_line(doc, history, 0, (100, 200), (250, 200), arrow=True, style=Style(width=2))
        labels = [info.label for info in notes.list_annotations(doc, 0)]
        assert labels == ["Notiz", "Freihand", "Rechteck", "Ellipse", "Linie"]
        note = doc.pdf.pages[0].Annots[0]
        assert note.Name == "/Comment" and int(note.F) & 24 == 24  # nicht zoomen, nicht drehen
        assert close(pixel(doc, 100, 280), (0, 0, 255))  # Freihandstrich
        assert close(pixel(doc, 340, 330), (0, 200, 0))  # Füllung
        assert close(pixel(doc, 300, 330), (255, 0, 0))  # Rahmen (Mitte des Strichs)
        line = doc.pdf.pages[0].Annots[4]
        assert [str(v) for v in line.LE] == ["/None", "/OpenArrow"]
        assert history.undo_title == "Pfeil zeichnen"
    finally:
        doc.close()


# --- Textfeld ----------------------------------------------------------------------------------------------------------
def dark_box(doc: EditorDocument, view_box) -> tuple[int, int, int, int] | None:
    geo = doc.geometry(0)
    picture = render.to_pil(render.render_page(doc, 0, int(geo.width * 2))).convert("L")
    scale = picture.width / geo.width
    crop = picture.crop(tuple(int(v * scale) for v in view_box))
    return crop.point(lambda value: 255 if value < 100 else 0).getbbox()


def test_textbox_wraps_and_supports_characters_outside_winansi(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    try:
        notes.add_textbox(doc, commands.History(), 0, (100, 400, 250, 480), "Bitte bis Freitag zurück an Łukasz senden.", style=Style(width=1, font_size=11))
        annot = doc.pdf.pages[0].Annots[0]
        assert annot.Subtype == "/FreeText" and "/Helv" in str(annot.DA)
        ap = annot.AP.N
        assert "/PTF1" in ap.Resources.Font  # eingebettete Teilmenge für »Ł«
        assert "/Font" not in doc.pdf.pages[0].Resources or "/PTF1" not in doc.pdf.pages[0].Resources.Font
        geo = doc.geometry(0)
        u0, v0 = geo.to_view(100, 480)
        box = dark_box(doc, (u0 + 3, v0 + 3, u0 + 147, v0 + 77))  # innerhalb des Rahmens
        assert box is not None and box[3] - box[1] > 20  # mehrere Zeilen
    finally:
        doc.close()


@pytest.mark.parametrize("rotation", [90, 270])
def test_textbox_text_is_upright_on_rotated_pages(tmp_path: Path, rotation: int) -> None:
    doc = EditorDocument.open(samples.direct_image(tmp_path / "d.pdf", rotate=rotation))
    try:
        geo = doc.geometry(0)
        view = (300, 100, 500, 140)  # breit und flach in der Anzeige
        rect = geo.rect_to_page(view)
        notes.add_textbox(doc, commands.History(), 0, rect, "Waagerecht lesbar", style=Style(width=0, font_size=14))
        box = dark_box(doc, view)
        assert box is not None and (box[2] - box[0]) > 2 * (box[3] - box[1])  # breiter als hoch
    finally:
        doc.close()


# --- Ändern, Verschieben, Löschen ---------------------------------------------------------------------------------------
def test_update_move_delete_with_undo(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        key = notes.add_markup(doc, history, 0, notes.HIGHLIGHT, selection(doc, "Rechnung"))
        notes.update(doc, history, key, contents="Neu", color=(0, 200, 255))
        info = notes.list_annotations(doc, 0)[0]
        assert (info.contents, info.color) == ("Neu", (0, 200, 255))
        assert b"0.7843 1 rg" in doc.pdf.pages[0].Annots[0].AP.N.read_bytes()  # Erscheinungsbild neu
        before = info.rect
        notes.move(doc, history, key, 10, -20)
        after = notes.list_annotations(doc, 0)[0].rect
        assert [round(a - b) for a, b in zip(after, before)] == [10, -20, 10, -20]
        quads = [float(v) for v in doc.pdf.pages[0].Annots[0].QuadPoints]
        assert round(quads[0] - before[0]) == 10
        notes.delete(doc, history, key)
        assert notes.list_annotations(doc, 0) == [] and "/Annots" not in doc.pdf.pages[0].obj
        for _ in range(3):
            history.undo(doc)
        info = notes.list_annotations(doc, 0)[0]
        assert info.contents == "" and info.color == (255, 235, 59) and info.rect == before
    finally:
        doc.close()


def test_existing_annotations_are_kept_and_can_be_moved_and_deleted(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.structured(tmp_path / "s.pdf"))
    history = commands.History()
    try:
        (note,) = notes.list_annotations(doc, 0)  # der Link ist kein Kommentar
        assert (note.label, note.contents, note.ours) == ("Notiz", "Bitte prüfen", False)
        notes.move(doc, history, note.key, -100, 0)
        assert round(notes.list_annotations(doc, 0)[0].rect[0]) == 300
        notes.delete(doc, history, note.key)
        assert notes.list_annotations(doc, 0) == []
        assert [a.Subtype for a in doc.pdf.pages[0].Annots] == ["/Link"]
        history.undo(doc)
        history.undo(doc)
        assert round(notes.list_annotations(doc, 0)[0].rect[0]) == 400
    finally:
        doc.close()


def test_annotations_respect_permissions(tmp_path: Path) -> None:
    source = samples.standard_text(tmp_path / "offen.pdf")
    locked = tmp_path / "gesperrt.pdf"
    with pikepdf.open(source) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(user="geheim", owner="besitzer", R=6, allow=pikepdf.Permissions(modify_annotation=False, modify_other=False)))
    doc = EditorDocument.open(locked, password="geheim")
    try:
        with pytest.raises(ReadOnlyDocument):
            notes.add_note(doc, commands.History(), 0, 100, 100, "x")
    finally:
        doc.close()


def test_annotations_survive_saving(tmp_path: Path) -> None:
    path = samples.structured(tmp_path / "s.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        notes.add_markup(doc, history, 0, notes.HIGHLIGHT, selection(doc, "Rechnung"))
        notes.add_textbox(doc, history, 1, (100, 400, 300, 450), "Freigegeben")
        notes.add_ink(doc, history, 2, [[(100, 100), (200, 200)]])
        save.save(doc, path)
    finally:
        doc.close()
    again = EditorDocument.open(path)
    try:
        labels = [info.label for info in notes.list_annotations(again)]
        assert labels == ["Notiz", "Markierung", "Textfeld", "Freihand"]
        with pikepdf.open(path) as pdf:
            assert pdf.check_pdf_syntax() == []
    finally:
        again.close()
