"""PDF Editor – Objekt bearbeiten: Segmentierung (Zeile, Segment, Wort), Treffer, Ändern, Löschen,
Verschieben, Formatieren, Duplizieren, Ausrichten, Rückgängig und Speichern.

Testfälle A–L der Anforderung (künstliche PDFs aus ``editorsamples``), dazu die Regressionstests
»Hottgenroth Software GmbH«, Tabelle und Speichern → Schließen → Öffnen. Geprüft wird jeweils, dass
nur das gewählte Objekt anders ist: Text der Seite, Lage aller übrigen Zeichen und die Darstellung
außerhalb des Objekts bleiben gleich.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pikepdf
import pypdfium2
import pytest
from PIL import ImageChops

import editorsamples as samples
from tools.pdf_editor import commands, fonts, objects, render, save, textlayer
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import UnsupportedEdit
from tools.pdf_editor.objects import NATIVE, NO_TEXT, OVERLAY, RECONSTRUCTED


@pytest.fixture(autouse=True)
def runtime_like(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wie in der installierten App: ohne lxml; Ersatzschrift Bitstream Vera (``PDFTOOL_FONT_DIRS``)."""
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)
    monkeypatch.setenv("PDFTOOL_FONT_DIRS", str(samples.vera_path().parent))
    fonts.find_system_font.cache_clear()
    yield
    fonts.find_system_font.cache_clear()


@pytest.fixture
def opened():
    """``opened(path)`` öffnet ein Dokument samt eigener Bearbeitungshistorie; geschlossen wird am Ende."""
    docs: list[EditorDocument] = []

    def open_(path: Path) -> tuple[EditorDocument, commands.History]:
        doc = EditorDocument.open(path)
        docs.append(doc)
        return doc, commands.History()

    yield open_
    for doc in docs:
        doc.close()


# --- Hilfen ----------------------------------------------------------------------------------------------------
def texts(doc: EditorDocument, page: int = 0) -> list[str]:
    return [segment.text for segment in objects.analyze(doc, page).segments]


def segment(found: objects.PageObjects, text: str) -> objects.Segment:
    return next(item for item in found.segments if item.text == text)


def origins(found: objects.PageObjects, *, skip: tuple[str, ...] = ()) -> dict[str, list[tuple[float, float]]]:
    """Lage jedes sichtbaren Zeichens je Segment (Seitenkoordinaten, auf 0,01 pt)."""
    result = {}
    for item in found.segments:
        if item.text in skip:
            continue
        result[item.text] = [tuple(round(value, 2) for value in found.glyphs[i].origin) for i in range(item.first, item.last + 1) if not found.glyphs[i].space]
    return result


def picture(doc: EditorDocument, page: int = 0):
    return render.to_pil(render.render_page(doc, page, 900)).convert("L")


def changed_box(doc: EditorDocument, before, page: int = 0):
    """Bereich der Seite (Seitenpunkte, Ursprung oben links), dessen Darstellung sich geändert hat."""
    after = picture(doc, page)
    box = ImageChops.difference(before, after).point(lambda value: 255 if value > 40 else 0).getbbox()
    if box is None:
        return None
    scale = before.width / doc.geometry(page).width
    return tuple(value / scale for value in box)


def inside(box, rect, pad: float = 4.0) -> bool:
    return box[0] >= rect[0] - pad and box[1] >= rect[1] - pad and box[2] <= rect[2] + pad and box[3] <= rect[3] + pad


def view(doc: EditorDocument, rect, page: int = 0):
    return doc.geometry(page).rect_to_view(rect)


def reopened(doc: EditorDocument, tmp_path: Path, name: str = "gespeichert.pdf") -> Path:
    """Über den normalen Speicherweg sichern und die Datei unabhängig prüfen (pikepdf, PDFium)."""
    target = tmp_path / name
    save.save(doc, target)
    with pikepdf.open(target) as pdf:
        pages = len(pdf.pages)
    view_doc = pypdfium2.PdfDocument(str(target))
    try:
        assert len(view_doc) == pages
        assert view_doc[0].render(scale=0.3).to_pil().getextrema() != ((255, 255), (255, 255), (255, 255))
    finally:
        view_doc.close()
    return target


# --- Segmentierung -------------------------------------------------------------------------------------------
def test_a_single_line_is_one_segment_with_words(tmp_path: Path, opened) -> None:
    doc, _history = opened(samples.object_line(tmp_path / "a.pdf"))
    found = objects.analyze(doc, 0)
    assert [item.text for item in found.segments] == ["Rechnung Nr. 4711"]
    line = found.segments[0]
    assert [word.text for word in line.words] == ["Rechnung", "Nr.", "4711"]
    assert line.native and line.font == "Helvetica" and line.size == pytest.approx(14.0)


def test_b_f_address_in_one_text_object_becomes_four_lines(tmp_path: Path, opened) -> None:
    """Ein BT … ET mit vier sichtbaren Zeilen: vier Segmente, jedes mit seinen Wörtern."""
    doc, _history = opened(samples.object_address(tmp_path / "b.pdf"))
    found = objects.analyze(doc, 0)
    assert [item.text for item in found.segments] == ["Firma", "Hottgenroth Software AG", "Von-Hünefeld-Str. 3", "50829 Köln"]
    assert [word.text for word in segment(found, "Hottgenroth Software AG").words] == ["Hottgenroth", "Software", "AG"]
    assert len({item.line for item in found.segments}) == 4
    # Granularität: Ebene Objekt → Segment → Wort; Kennungen der Wörter hängen am Segment
    line = segment(found, "Hottgenroth Software AG")
    seg, first, last = found.target(line.words[1].id)
    assert seg is line and found.text_of(first, last) == "Software"


def test_c_word_from_several_text_runs_is_one_word(tmp_path: Path, opened) -> None:
    """»Hott« + »genroth« sind zwei Operatoren, sichtbar aber ein Wort."""
    doc, _history = opened(samples.object_split_word(tmp_path / "c.pdf"))
    found = objects.analyze(doc, 0)
    line = found.segments[0]
    assert line.text == "Hottgenroth Software AG"
    assert [word.text for word in line.words] == ["Hottgenroth", "Software", "AG"]
    runs = {found.glyphs[i].run for i in range(line.words[0].first, line.words[0].last + 1)}
    assert len(runs) == 2  # das Wort besteht aus zwei Text-Runs


def test_d_words_in_different_fonts_are_separate_segments(tmp_path: Path, opened) -> None:
    doc, _history = opened(samples.object_fonts(tmp_path / "d.pdf"))
    found = objects.analyze(doc, 0)
    assert [(item.text, item.font) for item in found.segments] == [("Normal", "Helvetica"), ("Fett", "Helvetica-Bold"), ("Kursiv", "Times-Italic")]


def test_kerned_words_without_spaces_are_found_geometrically(tmp_path: Path, opened) -> None:
    """Wortabstände als TJ-Verschiebung ohne Leerzeichen: Wörter trotzdem einzeln."""
    doc, _history = opened(samples.object_kerned_words(tmp_path / "kerning.pdf"))
    found = objects.analyze(doc, 0)
    assert len(found.segments) == 1
    assert [word.text for word in found.segments[0].words] == ["Hottgenroth", "Software", "AG"]


def test_e_table_cells_are_separate_objects_also_in_a_single_operator(tmp_path: Path, opened) -> None:
    doc, _history = opened(samples.object_table(tmp_path / "e.pdf"))
    assert texts(doc) == ["Pos.", "Anz.", "Leistung", "Stückpreis", "Gesamtpreis", "1", "2", "Wartung Software", "120,00", "240,00"]
    one, _history = opened(samples.object_table_one_operator(tmp_path / "e-tj.pdf"))
    assert texts(one) == ["Pos.", "Anz.", "Leistung", "Gesamt"]  # Spalten nur durch große TJ-Verschiebungen getrennt


def test_l_repeated_words_are_separate(tmp_path: Path, opened) -> None:
    doc, _history = opened(samples.object_repeated(tmp_path / "l.pdf"))
    line = objects.analyze(doc, 0).segments[0]
    assert [word.text for word in line.words] == ["Test", "Test", "Test"]
    assert line.words[0].bounds[2] < line.words[1].bounds[0] < line.words[1].bounds[2] < line.words[2].bounds[0]


def test_analysis_does_not_change_the_document(tmp_path: Path, opened) -> None:
    """Den Modus aktivieren (analysieren, beschreiben) ändert die Datei nicht."""
    doc, _history = opened(samples.object_address(tmp_path / "unveraendert.pdf"))
    revision = doc.revision
    buffer = io.BytesIO()
    doc.pdf.save(buffer, deterministic_id=True, fix_metadata_version=False)
    for page in range(len(doc.pdf.pages)):
        objects.describe(doc, objects.analyze(doc, page))
    again = io.BytesIO()
    doc.pdf.save(again, deterministic_id=True, fix_metadata_version=False)
    assert doc.revision == revision and not doc.dirty and buffer.getvalue() == again.getvalue()


def test_scanned_page_offers_no_text_objects_but_its_image(tmp_path: Path, opened) -> None:
    """Bild mit unsichtbarer Texterkennung: kein vorgetäuschter Text, aber das Bild als Objekt."""
    doc, _history = opened(samples.scanned_with_ocr(tmp_path / "scan.pdf"))
    data = objects.describe(doc, objects.analyze(doc, 0))
    assert data["segments"] == [] and data["message"] == NO_TEXT == "Auf dieser Seite wurde kein bearbeitbarer PDF-Text erkannt."
    assert len(data["images"]) == 1 and data["images"][0]["kind"] == "image"


def test_hit_testing_picks_the_segment_and_word_under_the_point(tmp_path: Path, opened) -> None:
    doc, _history = opened(samples.object_address(tmp_path / "treffer.pdf"))
    found = objects.analyze(doc, 0)
    line = segment(found, "Hottgenroth Software AG")
    x = (line.words[1].bounds[0] + line.words[1].bounds[2]) / 2
    y = (line.bounds[1] + line.bounds[3]) / 2
    assert objects.segment_at(found, x, y) is line
    assert objects.word_at(line, x, y).text == "Software"
    # Zwischen den Zeilen (außerhalb der Toleranz) und weit daneben: nichts
    assert objects.segment_at(found, x, line.bounds[3] + 0.6).text in ("Hottgenroth Software AG", "Firma")
    assert objects.segment_at(found, 400, 400) is None


def test_i_rotated_pages_and_cropbox_map_to_the_view(tmp_path: Path, opened) -> None:
    """90°, 180°, 270°, CropBox und CropBox + 90°: dieselbe Zeile liegt in der Anzeige dort, wo PDFium
    sie zeichnet (Prüfung über die Darstellung: dunkle Pixel innerhalb des gemeldeten Rechtecks)."""
    doc, _history = opened(samples.object_rotated(tmp_path / "i.pdf"))
    for page in range(5):
        data = objects.describe(doc, objects.analyze(doc, page))
        line = next(item for item in data["segments"] if item["text"] == "Hottgenroth Software AG")
        geo = doc.geometry(page)
        image = picture(doc, page)
        scale = image.width / geo.width
        u0, v0, u1, v1 = (round(value * scale) for value in line["view"])
        inner = image.crop((u0, v0, u1 + 1, v1 + 1))
        assert inner.getextrema()[0] < 100, page  # Schrift innerhalb des Rechtecks
        assert line["angle"] == pytest.approx((geo.rotation) % 360), page
        assert 0 <= line["view"][0] < line["view"][2] <= geo.width and 0 <= line["view"][1] < line["view"][3] <= geo.height


# --- Ändern ----------------------------------------------------------------------------------------------------
def test_hottgenroth_regression_only_the_chosen_line_changes(tmp_path: Path, opened) -> None:
    """Regression 50: nur »Hottgenroth Software AG« → »… GmbH«; Straße, Ort und alle übrigen Zeichen
    bleiben, wo sie waren; die Darstellung ändert sich nur in dieser Zeile; nach Speichern,
    Schließen und Öffnen ist alles erhalten."""
    doc, history = opened(samples.object_address(tmp_path / "adresse.pdf"))
    found = objects.analyze(doc, 0)
    line = segment(found, "Hottgenroth Software AG")
    before_pixels = picture(doc)
    before = origins(found, skip=("Hottgenroth Software AG",))
    outcome = objects.edit_text(doc, history, found, line.id, "Hottgenroth Software GmbH")
    assert outcome.mode == NATIVE and outcome.label == "Direkt im PDF geändert (Originalschrift)"
    after_found = objects.analyze(doc, 0)
    assert [item.text for item in after_found.segments] == ["Firma", "Hottgenroth Software GmbH", "Von-Hünefeld-Str. 3", "50829 Köln"]
    assert origins(after_found, skip=("Hottgenroth Software GmbH",)) == before
    assert segment(after_found, "Hottgenroth Software GmbH").bounds[0] == pytest.approx(line.bounds[0], abs=0.01)
    assert segment(after_found, "Hottgenroth Software GmbH").font == "Helvetica"  # Schrift erhalten
    assert inside(changed_box(doc, before_pixels), view(doc, outcome.bounds))
    assert history.undo_title == "Text ändern"
    # Speichern → schließen → öffnen
    path = reopened(doc, tmp_path)
    again, _history = opened(path)
    assert texts(again) == ["Firma", "Hottgenroth Software GmbH", "Von-Hünefeld-Str. 3", "50829 Köln"]
    assert origins(objects.analyze(again, 0), skip=("Hottgenroth Software GmbH",)) == before
    assert len(again.pdf.pages) == 1


def test_one_text_object_keeps_other_lines_when_postcode_changes(tmp_path: Path, opened) -> None:
    """Abschnitt 19: »50829 Köln« → »50823 Köln«; andere Zeilen im selben Textobjekt bleiben."""
    doc, history = opened(samples.object_address(tmp_path / "ort.pdf"))
    found = objects.analyze(doc, 0)
    before = origins(found, skip=("50829 Köln",))
    assert objects.edit_text(doc, history, found, segment(found, "50829 Köln").id, "50823 Köln").mode == NATIVE
    after = objects.analyze(doc, 0)
    assert [item.text for item in after.segments] == ["Firma", "Hottgenroth Software AG", "Von-Hünefeld-Str. 3", "50823 Köln"]
    assert origins(after, skip=("50823 Köln",)) == before


@pytest.mark.parametrize("sample", ["object_table", "object_table_one_operator"])
def test_table_regression_one_cell_changes_and_the_row_stays(tmp_path: Path, opened, sample: str) -> None:
    doc, history = opened(getattr(samples, sample)(tmp_path / f"{sample}.pdf"))
    found = objects.analyze(doc, 0)
    before = origins(found, skip=("Leistung",))
    others = [item.text for item in found.segments]
    outcome = objects.edit_text(doc, history, found, segment(found, "Leistung").id, "Dienstleistung")
    assert outcome.mode == NATIVE
    after = objects.analyze(doc, 0)
    assert [item.text for item in after.segments] == [("Dienstleistung" if text == "Leistung" else text) for text in others]
    assert origins(after, skip=("Dienstleistung",)) == before


def test_c_word_from_two_runs_changes_and_the_rest_of_the_line_follows(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.object_split_word(tmp_path / "c.pdf"))
    found = objects.analyze(doc, 0)
    line = found.segments[0]
    gap = line.words[1].bounds[0] - line.words[0].bounds[2]
    assert objects.edit_text(doc, history, found, line.words[0].id, "Muster").mode == NATIVE
    after = objects.analyze(doc, 0).segments[0]
    assert after.text == "Muster Software AG"
    assert after.words[1].bounds[0] - after.words[0].bounds[2] == pytest.approx(gap, abs=0.3)  # keine Lücke, keine Überlappung


def test_d_one_font_segment_changes_in_its_own_font(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.object_fonts(tmp_path / "d.pdf"))
    found = objects.analyze(doc, 0)
    assert objects.edit_text(doc, history, found, segment(found, "Fett").id, "Stark").mode == NATIVE
    after = objects.analyze(doc, 0)
    assert [(item.text, item.font) for item in after.segments] == [("Normal", "Helvetica"), ("Stark", "Helvetica-Bold"), ("Kursiv", "Times-Italic")]


def test_g_text_on_colored_background_changes_without_a_white_box(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.object_colored_background(tmp_path / "g.pdf"))
    found = objects.analyze(doc, 0)
    line = segment(found, "Auf blauer Fläche")
    assert objects.edit_text(doc, history, found, line.words[1].id, "roter").mode == NATIVE
    assert texts(doc) == ["Auf roter Fläche", "Daneben"]
    # Die blaue Fläche bleibt überall blau – auch dort, wo der alte Text stand (kein weißes Rechteck)
    image = render.to_pil(render.render_page(doc, 0, 900))
    scale = image.width / doc.geometry(0).width
    u0, v0, u1, v1 = view(doc, line.words[1].bounds)
    for u, v in ((u0 + 1, v0 - 2), ((u0 + u1) / 2, v1 + 2), (u1 + 1, (v0 + v1) / 2)):
        r, g, b = image.getpixel((round(u * scale), round(v * scale)))
        assert b > 200 and r < 230, (u, v, (r, g, b))


def test_h_text_on_an_image_changes_and_the_image_stays(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.object_text_on_image(tmp_path / "h.pdf"))
    found = objects.analyze(doc, 0)
    assert objects.edit_text(doc, history, found, found.segments[0].words[2].id, "Foto").mode == NATIVE
    data = objects.describe(doc, objects.analyze(doc, 0))
    assert [item["text"] for item in data["segments"]] == ["Text auf Foto"] and len(data["images"]) == 1


@pytest.mark.parametrize(("sample", "line", "word", "new"), [
    ("subset_font", "Preis: 99 EUR netto", 1, "98"),        # J: Teilschrift (Subset)
    ("cid_font", "Lieferschein 2026-0042", 1, "2026-0043"),  # K: CID-Schrift (Identity-H)
])
def test_j_k_subset_and_cid_fonts_change_natively(tmp_path: Path, opened, sample: str, line: str, word: int, new: str) -> None:
    doc, history = opened(getattr(samples, sample)(tmp_path / f"{sample}.pdf"))
    found = objects.analyze(doc, 0)
    target = segment(found, line)
    assert target.native, target.native_reason
    before = origins(found, skip=(line,))
    outcome = objects.edit_text(doc, history, found, target.words[word].id, new)
    assert outcome.mode == NATIVE
    changed = line.split(" ")
    changed[word] = new
    after = objects.analyze(doc, 0)
    assert " ".join(changed) in [item.text for item in after.segments]
    assert origins(after, skip=(" ".join(changed),)) == before


def test_missing_glyphs_are_reconstructed_and_named(tmp_path: Path, opened) -> None:
    """»Č« gibt es in der WinAnsi-Originalschrift nicht: neu gesetzt (RECONSTRUCTED), Original entfernt."""
    doc, history = opened(samples.object_address(tmp_path / "neu.pdf"))
    found = objects.analyze(doc, 0)
    outcome = objects.edit_text(doc, history, found, segment(found, "Firma").id, "Firma Čech")
    assert outcome.mode == RECONSTRUCTED and outcome.label == "Neu gesetzt (Originaltext entfernt)"
    page = textlayer.text(doc, 0)
    assert "Firma Čech" in page and "Hottgenroth Software AG" in page and page.count("Firma") == 1


def test_text_in_a_form_xobject_is_overlaid_as_last_resort_and_said_so(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.form_xobject_text(tmp_path / "formular.pdf"))
    found = objects.analyze(doc, 0)
    target = segment(found, "Briefkopf Muster AG")
    assert not target.native and "Formular-Objekt" in target.native_reason
    with pytest.raises(UnsupportedEdit):
        objects.move(doc, history, found, [target.id], 10, 0)  # Verschieben nur nativ
    outcome = objects.edit_text(doc, history, objects.analyze(doc, 0), target.id, "Briefkopf Beispiel AG")
    assert outcome.mode == OVERLAY and "keine Schwärzung" in outcome.label
    assert any("Formular-Objekt" in note for note in outcome.notes)


# --- Löschen, Verschieben, Formatieren, Duplizieren, Ausrichten -----------------------------------------------------
def test_l_delete_only_the_middle_word(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.object_repeated(tmp_path / "l.pdf"))
    found = objects.analyze(doc, 0)
    first = found.segments[0].words[0].bounds
    assert objects.delete(doc, history, found, [found.segments[0].words[1].id]).mode == NATIVE
    after = objects.analyze(doc, 0).segments[0]
    assert after.text == "Test Test" and after.words[0].bounds[0] == pytest.approx(first[0], abs=0.01)


def test_delete_several_cells_at_once(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.object_table(tmp_path / "loeschen.pdf"))
    found = objects.analyze(doc, 0)
    before = origins(found, skip=("Stückpreis", "120,00"))
    outcome = objects.delete(doc, history, found, [segment(found, "Stückpreis").id, segment(found, "120,00").id])
    assert outcome.mode == NATIVE and history.undo_title == "Objekte löschen"
    after = objects.analyze(doc, 0)
    assert [item.text for item in after.segments] == ["Pos.", "Anz.", "Leistung", "Gesamtpreis", "1", "2", "Wartung Software", "240,00"]
    assert origins(after) == before


def test_move_is_exact_in_page_coordinates_and_undo_restores_the_file_state(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.object_address(tmp_path / "verschieben.pdf"))
    original = io.BytesIO()
    doc.pdf.save(original, deterministic_id=True, fix_metadata_version=False)
    found = objects.analyze(doc, 0)
    line = segment(found, "50829 Köln")
    before = origins(found, skip=("50829 Köln",))
    assert objects.move(doc, history, found, [line.id], 20.0, -10.0).mode == NATIVE
    after = objects.analyze(doc, 0)
    moved = segment(after, "50829 Köln")
    assert moved.bounds[0] - line.bounds[0] == pytest.approx(20.0, abs=0.01)
    assert moved.bounds[1] - line.bounds[1] == pytest.approx(-10.0, abs=0.01)
    assert origins(after, skip=("50829 Köln",)) == before
    history.undo(doc)
    restored = io.BytesIO()
    doc.pdf.save(restored, deterministic_id=True, fix_metadata_version=False)
    assert restored.getvalue() == original.getvalue()  # Rückgängig: exakt der vorige Stand
    history.redo(doc)
    assert segment(objects.analyze(doc, 0), "50829 Köln").bounds[0] == pytest.approx(moved.bounds[0], abs=0.01)


def test_restyle_size_color_and_spacing_of_one_segment(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.object_address(tmp_path / "format.pdf"))
    found = objects.analyze(doc, 0)
    before = origins(found, skip=("Firma",))
    assert objects.restyle(doc, history, found, [segment(found, "Firma").id], size=16).mode == NATIVE
    found = objects.analyze(doc, 0)
    assert segment(found, "Firma").size == pytest.approx(16.0) and segment(found, "50829 Köln").size == pytest.approx(11.0)
    objects.restyle(doc, history, found, [segment(found, "50829 Köln").id], color=(200, 0, 0))
    found = objects.analyze(doc, 0)
    assert segment(found, "50829 Köln").color == (200, 0, 0) and segment(found, "Firma").color == (0, 0, 0)
    width = segment(found, "Von-Hünefeld-Str. 3").bounds[2] - segment(found, "Von-Hünefeld-Str. 3").bounds[0]
    objects.restyle(doc, history, found, [segment(found, "Von-Hünefeld-Str. 3").id], spacing=1.0)
    found = objects.analyze(doc, 0)
    assert segment(found, "Von-Hünefeld-Str. 3").bounds[2] - segment(found, "Von-Hünefeld-Str. 3").bounds[0] > width + 10
    assert origins(found, skip=("Firma", "Von-Hünefeld-Str. 3", "50829 Köln")) == {key: value for key, value in before.items() if key not in ("Von-Hünefeld-Str. 3", "50829 Köln")}
    with pytest.raises(UnsupportedEdit):
        objects.restyle(doc, history, found, [segment(found, "Firma").id], size=12, spacing=1.0)  # immer genau eine Eigenschaft


def test_size_and_spacing_are_page_points_also_with_a_scaled_text_matrix(tmp_path: Path, opened) -> None:
    """»1 Tf« mit »11 0 0 11 … Tm«: Größe und Zeichenabstand sind sichtbare Punkte, nicht Werte des
    Operators – 16 pt bleibt 16 pt, nicht 176 pt."""
    doc, history = opened(samples.object_scaled_matrix(tmp_path / "skaliert.pdf"))
    found = objects.analyze(doc, 0)
    line = found.segments[0]
    assert line.size == pytest.approx(11.0, abs=0.01)
    data = objects.describe(doc, found)["segments"][0]
    assert data["spacing"] == pytest.approx(0.55, abs=0.001)  # 0,05 × 11
    objects.restyle(doc, history, found, [line.id], size=16)
    found = objects.analyze(doc, 0)
    assert found.segments[0].size == pytest.approx(16.0, abs=0.05)
    history.undo(doc)
    found = objects.analyze(doc, 0)
    width = found.segments[0].bounds[2] - found.segments[0].bounds[0]
    objects.restyle(doc, history, found, [found.segments[0].id], spacing=1.55)
    found = objects.analyze(doc, 0)
    assert objects.describe(doc, found)["segments"][0]["spacing"] == pytest.approx(1.55, abs=0.001)
    assert found.segments[0].bounds[2] - found.segments[0].bounds[0] == pytest.approx(width + 16 * 1.0, abs=1.2)  # 17 Zeichen, je 1 pt mehr


def test_a_larger_word_pushes_the_rest_of_its_line(tmp_path: Path, opened) -> None:
    """Ein Wort mitten in der Zeile größer: der Rest der Zeile rückt nach (keine Überlappung); andere
    Zeilen bleiben, wo sie sind."""
    doc, history = opened(samples.object_address(tmp_path / "wortgroesse.pdf"))
    found = objects.analyze(doc, 0)
    line = segment(found, "Hottgenroth Software AG")
    others = origins(found, skip=("Hottgenroth Software AG",))
    gap = line.words[2].bounds[0] - line.words[1].bounds[2]
    objects.restyle(doc, history, found, [line.words[1].id], size=16)
    found = objects.analyze(doc, 0)
    # Die Größe trennt die Zeile jetzt in drei Segmente (Schriftgröße ändert sich um mehr als 15 %)
    assert [item.text for item in found.segments][1:4] == ["Hottgenroth", "Software", "AG"]
    software, ag = segment(found, "Software"), segment(found, "AG")
    assert software.size == pytest.approx(16.0, abs=0.05) and ag.size == pytest.approx(11.0, abs=0.05)
    assert ag.bounds[0] - software.bounds[2] == pytest.approx(gap, abs=0.6)
    assert origins(found, skip=("Hottgenroth", "Software", "AG")) == others


def test_duplicate_and_align(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.object_address(tmp_path / "kopie.pdf"))
    found = objects.analyze(doc, 0)
    assert objects.duplicate(doc, history, found, segment(found, "Firma").id, (0.0, -40.0)).mode == NATIVE
    found = objects.analyze(doc, 0)
    copies = [item for item in found.segments if item.text == "Firma"]
    assert len(copies) == 2 and {item.font for item in copies} == {"Helvetica"}
    ids = [segment(found, "Hottgenroth Software AG").id, segment(found, "50829 Köln").id]
    objects.move_each(doc, history, found, objects.align(found, ids, "right"))
    found = objects.analyze(doc, 0)
    assert segment(found, "50829 Köln").bounds[2] == pytest.approx(segment(found, "Hottgenroth Software AG").bounds[2], abs=0.05)


def test_stale_model_is_rejected(tmp_path: Path, opened) -> None:
    """Ein Modell einer älteren Fassung der Seite darf nichts ändern (Kennungen wären falsch)."""
    doc, history = opened(samples.object_address(tmp_path / "alt.pdf"))
    found = objects.analyze(doc, 0)
    objects.edit_text(doc, history, found, segment(found, "Firma").id, "Kunde")
    with pytest.raises(UnsupportedEdit):
        objects.delete(doc, history, found, [segment(found, "50829 Köln").id])


def test_save_regression_after_several_object_changes(tmp_path: Path, opened) -> None:
    """Regression 52: Ändern, Verschieben, Löschen → speichern → schließen → öffnen: Änderungen und
    übrige Objekte erhalten, Seitenzahl gleich, Datei gültig und darstellbar."""
    doc, history = opened(samples.object_rotated(tmp_path / "mehrere.pdf"))
    for page in range(5):
        found = objects.analyze(doc, page)
        objects.edit_text(doc, history, found, segment(found, "Hottgenroth Software AG").id, "Hottgenroth Software GmbH")
    found = objects.analyze(doc, 1)
    objects.move(doc, history, found, [segment(found, "50829 Köln").id], 0.0, -20.0)
    found = objects.analyze(doc, 2)
    objects.delete(doc, history, found, [segment(found, "Firma").id])
    path = reopened(doc, tmp_path)
    again, _history = opened(path)
    assert len(again.pdf.pages) == 5
    for page in range(5):
        expected = ["Hottgenroth Software GmbH", "Von-Hünefeld-Str. 3", "50829 Köln"] + ([] if page == 2 else ["Firma"])
        assert sorted(texts(again, page)) == sorted(expected), page
