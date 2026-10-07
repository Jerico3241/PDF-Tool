"""PDF Editor – Objekte gemeinsam bearbeiten (seit 3.1): Vektorobjekte, gemischte Auswahl (Text, Bild,
Vektor) als ein Rückgängig-Schritt, Drehen, Deckkraft, Schrift, Duplizieren, Ebene, Zwischenablage
(Kopieren/Einfügen zwischen Seiten und Dokumenten) und »unverändert« nach Rückgängig zum gespeicherten Stand.
Alle Dokumente sind künstlich (``editorsamples``)."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

import editorsamples as samples
from tools.pdf_editor import commands, objectops, objects, render, save, textlayer, vectors
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import UnsupportedEdit


def analyzed(doc: EditorDocument, page: int = 0) -> objects.PageObjects:
    return objects.analyze(doc, page)


def segment_id(found: objects.PageObjects, text: str) -> str:
    return next(segment.id for segment in found.segments if segment.text.strip() == text)


def pixel(doc: EditorDocument, page: int, x: float, y: float) -> tuple[int, int, int]:
    """Farbe der Seite an einem Punkt (Seitenkoordinaten) – gerendert mit 1 Pixel je Punkt."""
    raster = render.render_page(doc, page, int(doc.geometry(page).width))
    image = render.to_pil(raster).convert("RGB")
    u, v = doc.geometry(page).to_view(x, y)
    return image.getpixel((int(u), int(v)))


def path_ids(doc: EditorDocument, page: int = 0) -> list[str]:
    return [f"{page}-v{item.index}" for item in vectors.list_paths(doc, page)]


# --- Vektorobjekte --------------------------------------------------------------------------------------------
def test_paths_are_listed_without_background(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.mixed_objects(tmp_path / "m.pdf"))
    items = vectors.list_paths(doc, 0)
    assert len(items) == 3  # Rahmen, Kreisfläche, Linie – die Hintergrundfläche nicht
    frame = next(item for item in items if item.stroke == (230, 26, 26))
    assert frame.fill is None and abs(frame.width - 2) < 0.01 and frame.editable
    assert frame.bounds[0] <= 300 <= frame.bounds[0] + 2 and frame.bounds[2] >= 420
    circle = next(item for item in items if item.fill is not None)
    assert circle.fill == (26, 77, 230) and circle.stroke is None


def test_move_recolor_width_opacity_and_delete_a_path_with_undo(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.mixed_objects(tmp_path / "m.pdf"))
    history = commands.History()
    circle = next(f"0-v{item.index}" for item in vectors.list_paths(doc, 0) if item.fill is not None)
    assert pixel(doc, 0, 510, 580)[2] > 200  # blau
    objectops.move_each(doc, history, analyzed(doc), {circle: (0.0, -100.0)})
    assert pixel(doc, 0, 510, 480)[2] > 200 and pixel(doc, 0, 510, 580)[2] < 250 and pixel(doc, 0, 510, 580) != pixel(doc, 0, 510, 480)
    objectops.style(doc, history, analyzed(doc), [circle], "color", (0, 160, 0))
    red, green, blue = pixel(doc, 0, 510, 480)
    assert green > 120 and blue < 60
    objectops.style(doc, history, analyzed(doc), [circle], "opacity", 0.5)
    red, green, blue = pixel(doc, 0, 510, 480)
    assert 150 < green < 220 and red > 100  # halbdurchsichtig über dem hellgrauen Hintergrund
    frame = next(f"0-v{item.index}" for item in vectors.list_paths(doc, 0) if item.stroke == (230, 26, 26))
    objectops.style(doc, history, analyzed(doc), [frame], "width", 6.0)
    assert any(abs(item.width - 6.0) < 0.01 for item in vectors.list_paths(doc, 0))
    objectops.delete(doc, history, analyzed(doc), [frame])
    assert len(vectors.list_paths(doc, 0)) == 2
    for _step in range(5):
        history.undo(doc)
    items = vectors.list_paths(doc, 0)
    assert len(items) == 3 and pixel(doc, 0, 510, 580)[2] > 200
    assert textlayer.text(doc, 0).count("Hottgenroth") == 1


def test_mixed_move_is_one_undo_step_and_survives_save(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.mixed_objects(tmp_path / "m.pdf"))
    history = commands.History()
    found = analyzed(doc)
    text = segment_id(found, "Rechnung Nr. 4711")
    line = next(f"0-v{item.index}" for item in vectors.list_paths(doc, 0) if item.bounds[2] - item.bounds[0] > 400)
    ids = [text, "0-i0", line]
    before = objectops.bounds_of(doc, found, ids)
    objectops.move_each(doc, history, found, {ident: (40.0, -30.0) for ident in ids})
    after = objectops.bounds_of(doc, analyzed(doc), ids)
    for ident in ids:
        assert abs(after[ident][0] - before[ident][0] - 40) < 1.5 and abs(after[ident][1] - before[ident][1] + 30) < 1.5
    assert history.undo_title == "Verschieben"
    target = tmp_path / "gespeichert.pdf"
    save.save(doc, target)
    again = EditorDocument.open(target)
    moved = objectops.bounds_of(again, analyzed(again), ids)
    assert abs(moved["0-i0"][0] - before["0-i0"][0] - 40) < 1.5
    history.undo(doc)  # ein Schritt für alle drei
    restored = objectops.bounds_of(doc, analyzed(doc), ids)
    for ident in ids:
        assert abs(restored[ident][0] - before[ident][0]) < 0.5
    assert not history.can_undo


def test_failed_part_rolls_back_the_whole_group(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.mixed_objects(tmp_path / "m.pdf"))
    history = commands.History()
    found = analyzed(doc)
    text = segment_id(found, "Rechnung Nr. 4711")
    before_text = textlayer.text(doc, 0)
    with pytest.raises(UnsupportedEdit):
        objectops.move_each(doc, history, found, {text: (10.0, 0.0), "0-v99": (10.0, 0.0)})
    assert not history.can_undo and textlayer.text(doc, 0) == before_text
    assert not doc.dirty


def test_rotate_text_natively_and_image_and_path(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.mixed_objects(tmp_path / "m.pdf"))
    history = commands.History()
    found = analyzed(doc)
    text = segment_id(found, "Rechnung Nr. 4711")
    box = found.bounds_of(*found.target(text)[1:])
    center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    objectops.transform(doc, history, found, [text], vectors.rotation(center, 90))
    again = analyzed(doc)
    rotated = next(segment for segment in again.segments if segment.text.strip() == "Rechnung Nr. 4711")
    assert abs(rotated.angle - 90) < 1 and rotated.native  # nativ gedreht, Text bleibt lesbar und bearbeitbar
    assert "Rechnung Nr. 4711" in textlayer.text(doc, 0)
    objectops.transform(doc, history, analyzed(doc), ["0-i0"], vectors.rotation((132, 590), 180))
    assert history.undo_title == "Drehen"
    history.undo(doc)
    history.undo(doc)
    assert abs(next(s for s in analyzed(doc).segments if s.text.strip() == "Rechnung Nr. 4711").angle) < 1


def darkest(doc: EditorDocument, box) -> int:
    """Dunkelster Pixel (Summe R+G+B) im Bereich ``box`` (Seitenkoordinaten)."""
    raster = render.render_page(doc, 0, int(doc.geometry(0).width * 2))
    image = render.to_pil(raster).convert("RGB")
    geo = doc.geometry(0)
    u0, v0, u1, v1 = geo.rect_to_view(box)
    crop = image.crop((int(u0 * 2), int(v0 * 2), int(u1 * 2) + 1, int(v1 * 2) + 1))
    return min(sum(crop.getpixel((x, y))) for x in range(crop.width) for y in range(crop.height))


def test_text_opacity_restores_following_text(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.object_address(tmp_path / "a.pdf"))
    history = commands.History()
    found = analyzed(doc)
    target = segment_id(found, "Hottgenroth Software AG")
    street = next(segment for segment in found.segments if "Hünefeld" in segment.text)
    target_box = found.bounds_of(*found.target(target)[1:])
    before_target, before_street = darkest(doc, target_box), darkest(doc, street.bounds)
    objectops.style(doc, history, found, [target], "opacity", 0.4)
    data = doc.serialize().replace(b"\n", b" ")
    assert b"/ca 0.4" in data or b"/ca .4" in data
    text = textlayer.text(doc, 0)
    assert "Hottgenroth Software AG" in text and "Von-Hünefeld-Str. 3" in text
    assert darkest(doc, target_box) > before_target + 150  # deutlich heller (40 % Deckkraft)
    assert abs(darkest(doc, street.bounds) - before_street) <= 6  # folgende Zeile wieder voll deckend
    history.undo(doc)
    assert abs(darkest(doc, target_box) - before_target) <= 6


def test_bold_and_family_are_set_new_honestly(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.object_line(tmp_path / "l.pdf"))
    history = commands.History()
    found = analyzed(doc)
    target = found.segments[0].id
    objectops.style(doc, history, found, [target], "bold", True)
    assert history.last.info.get("mode") == objects.RECONSTRUCTED
    again = analyzed(doc)
    assert "Bold" in again.segments[0].font and again.segments[0].text.strip() == "Rechnung Nr. 4711"
    objectops.style(doc, history, again, [again.segments[0].id], "family", "Times")
    assert "Times" in analyzed(doc).segments[0].font


def test_duplicate_mixed_selection_once(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.mixed_objects(tmp_path / "m.pdf"))
    history = commands.History()
    found = analyzed(doc)
    text = segment_id(found, "Rechnung Nr. 4711")
    frame = next(f"0-v{item.index}" for item in vectors.list_paths(doc, 0) if item.stroke == (230, 26, 26))
    objectops.duplicate(doc, history, found, [text, "0-i0", frame], (12.0, -12.0))
    assert textlayer.text(doc, 0).count("Rechnung Nr. 4711") == 2
    from tools.pdf_editor import images

    assert len(images.list_images(doc, 0)) == 2 and len(vectors.list_paths(doc, 0)) == 4
    history.undo(doc)
    assert textlayer.text(doc, 0).count("Rechnung Nr. 4711") == 1 and len(vectors.list_paths(doc, 0)) == 3


def test_arrange_to_back_stays_above_the_page_background(tmp_path: Path) -> None:
    """»Ganz nach hinten« legt hinter alle Objekte – aber nicht unter die seitenfüllende Hintergrundfläche
    (sonst wäre das Objekt unsichtbar). »Ganz nach vorn« legt über alle. Je ein Schritt, Text unverändert."""
    doc = EditorDocument.open(samples.mixed_objects(tmp_path / "m.pdf"))
    history = commands.History()

    def circle() -> str:
        return next(f"0-v{item.index}" for item in vectors.list_paths(doc, 0) if item.fill is not None)

    def green(x: float, y: float) -> bool:  # Bild (30, 160, 60)
        red, g, blue = pixel(doc, 0, x, y)
        return g > 120 and red < 100 and blue < 100

    def blue(x: float, y: float) -> bool:  # Kreisfläche (26, 77, 230)
        red, _g, b = pixel(doc, 0, x, y)
        return b > 200 and red < 100

    # Das Bild teilweise über die Kreisfläche schieben: es liegt oben (zuletzt gezeichnet)
    objectops.move_each(doc, history, analyzed(doc), {"0-i0": (440.0, 0.0)})
    assert green(530, 580) and green(575, 580) and blue(490, 580)
    objectops.arrange(doc, history, analyzed(doc), ["0-i0"], front=False)
    assert blue(530, 580)  # die Kreisfläche liegt jetzt über dem Bild …
    assert green(575, 580)  # … das Bild bleibt über dem grauen Hintergrund sichtbar
    assert textlayer.text(doc, 0).count("Hottgenroth") == 1
    history.undo(doc)
    assert green(530, 580)
    # Kreisfläche nach hinten: bleibt sichtbar, liegt aber unter dem Bild; nach vorn: über dem Bild
    objectops.arrange(doc, history, analyzed(doc), [circle()], front=False)
    assert blue(490, 580) and green(530, 580)
    objectops.arrange(doc, history, analyzed(doc), [circle()], front=True)
    assert blue(530, 580) and green(575, 580)
    assert textlayer.text(doc, 0).count("Hottgenroth") == 1


def test_back_position_skips_backgrounds_but_never_enters_groups_or_text() -> None:
    def ops(*names: str) -> list:
        return [pikepdf.ContentStreamInstruction([], pikepdf.Operator(name)) for name in names]

    # Hintergrund (Farbe, Fläche) auf oberster Ebene, dann ein Objekt in q … Q: davor einfügen
    assert objectops._back_position(ops("rg", "re", "f", "q", "re", "S", "Q"), 4) == 3  # noqa: SLF001
    # Mitten im Text oder im Pfadaufbau nie
    assert objectops._back_position(ops("BT", "Tf", "Tj", "ET", "q"), 2) == 0  # noqa: SLF001
    assert objectops._back_position(ops("m", "l", "S", "re"), 3) == 3  # noqa: SLF001
    # Ein cm, Zuschnitt oder gs auf oberster Ebene ändert alles Folgende: nur Stellen davor
    assert objectops._back_position(ops("re", "f", "cm", "re", "f", "q"), 5) == 2  # noqa: SLF001
    assert objectops._back_position(ops("re", "W", "n", "q"), 3) == 0  # noqa: SLF001


# --- Zwischenablage -------------------------------------------------------------------------------------------
def test_copy_paste_between_documents_and_rotated_pages(tmp_path: Path) -> None:
    source = EditorDocument.open(samples.mixed_objects(tmp_path / "quelle.pdf"))
    found = analyzed(source)
    text = segment_id(found, "Hottgenroth Software AG")
    frame = next(f"0-v{item.index}" for item in vectors.list_paths(source, 0) if item.stroke == (230, 26, 26))
    clip = objectops.copy(source, found, [text, "0-i0", frame], "quelle")
    assert clip.text == "Hottgenroth Software AG" and clip.count == 3 and clip.data.startswith(b"%PDF")
    assert not source.dirty  # Kopieren ändert nichts
    target = EditorDocument.open(samples.direct_image(tmp_path / "ziel.pdf", rotate=90))
    history = commands.History()
    placed = objectops.paste(target, history, 0, clip, at=(40.0, 40.0))
    assert abs(placed[0] - 40) < 0.01 and abs(placed[1] - 40) < 0.01
    assert "Hottgenroth Software AG" in textlayer.text(target, 0)
    # in der Anzeige aufrecht wie im Original: auf der um 90° gedrehten Seite läuft der Text entlang +y
    pasted = next(segment for segment in analyzed(target).segments if "Hottgenroth" in segment.text)
    assert abs(pasted.angle - 90) < 1
    shown = next(item for item in objects.describe(target, analyzed(target))["segments"] if "Hottgenroth" in item["text"])
    assert shown["angle"] in (0.0, 360.0)
    saved = tmp_path / "ziel_gespeichert.pdf"
    save.save(target, saved)
    again = EditorDocument.open(saved)
    assert "Hottgenroth Software AG" in textlayer.text(again, 0)
    from tools.pdf_editor import images

    assert len(images.list_images(again, 0)) == 2
    history.undo(target)
    assert "Hottgenroth" not in textlayer.text(target, 0)


def test_paste_same_place_is_nudged_and_resources_do_not_collide(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.mixed_objects(tmp_path / "m.pdf"))
    history = commands.History()
    found = analyzed(doc)
    text = segment_id(found, "Rechnung Nr. 4711")
    clip = objectops.copy(doc, found, [text, "0-i0"], "d1")
    first = objectops.paste(doc, history, 0, clip, nudge=1)
    second = objectops.paste(doc, history, 0, clip, nudge=2)
    assert abs(second[0] - first[0] - objectops.NUDGE) < 0.01  # jede weitere Kopie ein Stück weiter
    assert textlayer.text(doc, 0).count("Rechnung Nr. 4711") == 3
    names = [str(name) for name in doc.pdf.pages[0].obj.Resources.XObject.keys()]
    assert len(names) == len(set(names)) == 3


def test_copy_works_in_read_only_documents(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.encrypted(tmp_path / "e.pdf", allow_edit=False), password="geheim")
    found = analyzed(doc)
    if not found.segments:
        pytest.skip("kein Text")
    clip = objectops.copy(doc, found, [found.segments[0].id], "e")
    assert clip.text


# --- Unverändert nach Rückgängig -------------------------------------------------------------------------------
def test_undo_back_to_the_saved_state_is_not_dirty(tmp_path: Path) -> None:
    path = samples.mixed_objects(tmp_path / "m.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    assert not doc.dirty
    circle = next(f"0-v{item.index}" for item in vectors.list_paths(doc, 0) if item.fill is not None)
    objectops.move_each(doc, history, analyzed(doc), {circle: (5.0, 5.0)})
    assert doc.dirty
    history.undo(doc)
    assert not doc.dirty  # wieder der Stand der Datei
    history.redo(doc)
    assert doc.dirty
    save.save(doc, path)
    assert not doc.dirty
    history.undo(doc)
    assert doc.dirty  # jetzt weicht der Stand von der gespeicherten Datei ab
    history.redo(doc)
    assert not doc.dirty
    with pikepdf.open(path) as pdf:
        assert len(pdf.pages) == 1
