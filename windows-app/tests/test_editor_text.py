"""PDF Editor – Text bearbeiten: Blöcke erkennen, nativ ändern, neu setzen (Ersatzschrift),
überlagern (ehrlich gekennzeichnet), neuen Text hinzufügen, Rückgängig/Wiederholen, Speichern.

Alle Dokumente sind künstlich (``editorsamples``). Als Systemschrift dient Bitstream Vera aus
ReportLab (``PDFTOOL_FONT_DIRS``) – so verhalten sich die Tests auf jedem Rechner gleich."""

from __future__ import annotations

import io
from pathlib import Path

import pikepdf
import pytest

import editorsamples as samples
from tools.pdf_editor import commands, fonts, render, save, textedit, textlayer
from tools.pdf_editor.content import PageContent, page_fonts
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import ReadOnlyDocument, UnsupportedEdit
from tools.pdf_editor.textedit import NATIVE, OVERLAY, RECONSTRUCTED, TextStyle


@pytest.fixture(autouse=True)
def vera_as_system_font(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDFTOOL_FONT_DIRS", str(samples.vera_path().parent))
    fonts.find_system_font.cache_clear()
    yield
    fonts.find_system_font.cache_clear()


def open_doc(path: Path) -> EditorDocument:
    return EditorDocument.open(path)


def blocks(doc: EditorDocument, page: int = 0) -> list[textedit.Block]:
    return textedit.analyze(doc, page)


def block_with(doc: EditorDocument, text: str, page: int = 0) -> textedit.Block:
    for block in blocks(doc, page):
        if text in block.text:
            return block
    raise AssertionError(f"kein Block mit {text!r}")


def page_text(doc: EditorDocument, page: int = 0) -> str:
    return textlayer.text(doc, page)


def reopen(doc: EditorDocument, tmp_path: Path, name: str = "gespeichert.pdf") -> EditorDocument:
    target = tmp_path / name
    target.write_bytes(doc.serialize(keep_encryption=True))
    return open_doc(target)


def snapshot(doc: EditorDocument) -> bytes:
    """Stand als Bytes mit festem /ID (``serialize`` erzeugt je Sekunde eine neue Datei-ID)."""
    buffer = io.BytesIO()
    doc.pdf.save(buffer, deterministic_id=True, compress_streams=False)
    return buffer.getvalue()


def max_q_depth(page: pikepdf.Page) -> int:
    depth = deepest = 0
    for ins in pikepdf.parse_content_stream(page):
        if isinstance(ins, pikepdf.ContentStreamInlineImage):
            continue
        op = str(ins.operator)
        if op == "q":
            depth += 1
            deepest = max(deepest, depth)
        elif op == "Q" and depth:
            depth -= 1
    return deepest


# --- Analyse -------------------------------------------------------------------------------------
def test_blocks_report_text_font_size_and_native_editability(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    try:
        found = [(b.text, b.font, b.size, b.editable_natively) for b in blocks(doc)]
        assert found == [
            ("Rechnung Nr. 4711 vom 01.10.2026", "Helvetica", 14.0, True),
            ("Gesamtbetrag: 1.234,56 EUR", "Helvetica-Bold", 12.0, True),
            ("Zahlbar innerhalb von 14 Tagen.", "Times-Roman", 11.0, True),
            ("Seite 1 von 1", "Helvetica", 9.0, True),
        ]
        info = blocks(doc)[1].describe()
        assert info["bold"] and not info["italic"] and info["native"] and info["lines"] == 1
    finally:
        doc.close()


def test_paragraph_lines_form_one_block_but_distant_lines_do_not(tmp_path: Path) -> None:
    doc = open_doc(samples.paragraph(tmp_path / "p.pdf"))
    try:
        found = blocks(doc)
        assert [len(b.lines) for b in found] == [3, 1]
        assert found[0].text.startswith("Dies ist ein Absatz") and found[0].align == "left"
    finally:
        doc.close()
    # Zeilen mit großem Abstand (über 1,7 × Schriftgröße) sind eigene Blöcke
    doc = open_doc(samples.cid_font(tmp_path / "c.pdf"))
    try:
        assert [b.text for b in blocks(doc)] == ["Lieferschein 2026-0042", "Menge: 3 Stück"]
    finally:
        doc.close()


def test_effective_size_includes_text_matrix_and_rotation_is_detected(tmp_path: Path) -> None:
    doc = open_doc(samples.scaled_text(tmp_path / "s.pdf"))
    try:
        assert [b.size for b in blocks(doc)] == [12.0, 10.0]
    finally:
        doc.close()
    doc = open_doc(samples.vertical_text(tmp_path / "v.pdf"))
    try:
        assert [(b.text, b.angle) for b in blocks(doc)] == [("Senkrechter Rand", 90.0), ("Waagerecht", 0.0)]
    finally:
        doc.close()


def test_text_in_form_xobject_and_invisible_ocr_text_are_not_native(tmp_path: Path) -> None:
    doc = open_doc(samples.form_xobject_text(tmp_path / "x.pdf"))
    try:
        head, body = blocks(doc)
        assert head.nested and not head.editable_natively and "Formular-Objekt" in head.native_reason
        assert body.editable_natively
    finally:
        doc.close()
    doc = open_doc(samples.scanned_with_ocr(tmp_path / "o.pdf"))
    try:
        (ocr,) = blocks(doc)
        assert ocr.invisible and not ocr.editable_natively and "Texterkennung" in ocr.describe()["reason"]
    finally:
        doc.close()


# --- Nativ -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("new_text", ["Rechnung Nr. 4712 vom 02.10.2026", "Rechnung 1", "Rechnung Nr. 4711 vom 01.10.2026 – Kopie für die Ablage"])
def test_native_edit_same_shorter_and_longer_text_in_standard_font(tmp_path: Path, new_text: str) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        outcome = textedit.edit_block(doc, history, blocks(doc)[0], new_text)
        assert outcome.mode == NATIVE and outcome.font == "Helvetica" and outcome.notes == []
        text = page_text(doc)
        assert new_text in text and "4711 vom 01.10.2026\n" not in text.replace(new_text, "")
        # übrige Texte unverändert; Formatierung der geänderten Zeile bleibt (Schrift, Größe)
        assert "Gesamtbetrag: 1.234,56 EUR" in text and "Seite 1 von 1" in text
        changed = block_with(doc, new_text)
        assert (changed.font, changed.size, changed.lines[0].baseline) == ("Helvetica", 14.0, (72.0, 760.0))
        assert doc.dirty and history.undo_title == "Text bearbeiten"
    finally:
        doc.close()


def test_native_edit_in_embedded_subset_and_cid_font(tmp_path: Path) -> None:
    doc = open_doc(samples.subset_font(tmp_path / "s.pdf"))
    history = commands.History()
    try:
        outcome = textedit.edit_block(doc, history, blocks(doc)[0], "Angebot fuer Muster AG")
        assert outcome.mode == NATIVE and "Vera" in outcome.font
        assert "Angebot fuer Muster AG" in page_text(doc)
    finally:
        doc.close()
    doc = open_doc(samples.cid_font(tmp_path / "c.pdf"))
    history = commands.History()
    try:
        first = textedit.edit_block(doc, history, blocks(doc)[0], "Lieferschein 2026-0043")
        second = textedit.edit_block(doc, history, block_with(doc, "Menge"), "Menge: 5 Stück")
        assert (first.mode, second.mode) == (NATIVE, NATIVE)
        assert page_text(doc).split("\n") == ["Lieferschein 2026-0043", "Menge: 5 Stück"]
    finally:
        doc.close()


def test_native_edit_keeps_marked_content_inline_image_and_shapes(tmp_path: Path) -> None:
    doc = open_doc(samples.complex_content(tmp_path / "k.pdf"))
    history = commands.History()
    try:
        before_ops = [str(i.operator) for i in pikepdf.parse_content_stream(doc.pdf.pages[0]) if not isinstance(i, pikepdf.ContentStreamInlineImage)]
        outcome = textedit.edit_block(doc, history, block_with(doc, "Vertrag"), "Vertrag Nr. 10")
        assert outcome.mode == NATIVE
        instructions = list(pikepdf.parse_content_stream(doc.pdf.pages[0]))
        after_ops = [str(i.operator) for i in instructions if not isinstance(i, pikepdf.ContentStreamInlineImage)]
        assert after_ops == before_ops  # nur Operanden geändert – BDC/EMC, Flächen bleiben
        assert sum(isinstance(i, pikepdf.ContentStreamInlineImage) for i in instructions) == 1
        assert page_text(doc).split("\n") == ["Kopfzeile Artefakt", "Vertrag Nr. 10"]
    finally:
        doc.close()


def test_delete_text_removes_it_from_the_content(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        outcome = textedit.edit_block(doc, history, block_with(doc, "Zahlbar"), "")
        assert outcome.mode == NATIVE and history.undo_title == "Text löschen"
        assert "Zahlbar" not in page_text(doc)
        saved = reopen(doc, tmp_path)
        try:
            assert "Zahlbar" not in page_text(saved)
            assert b"Zahlbar" not in saved.pdf.pages[0].Contents.read_bytes() if isinstance(saved.pdf.pages[0].Contents, pikepdf.Stream) else True
        finally:
            saved.close()
    finally:
        doc.close()


# --- Absätze und Überlauf ---------------------------------------------------------------------------
LONG = "Dies ist ein deutlich längerer Absatz, der nun sehr viel mehr Platz braucht als vorher, weil er viele zusätzliche Wörter enthält und deshalb nicht mehr in drei Zeilen passt."


def test_paragraph_rewraps_within_its_width(tmp_path: Path) -> None:
    doc = open_doc(samples.paragraph(tmp_path / "p.pdf"))
    history = commands.History()
    try:
        paragraph = blocks(doc)[0]
        width = paragraph.bounds[2] - paragraph.bounds[0]
        outcome = textedit.edit_block(doc, history, paragraph, "Kurzer neuer Absatz, der umbrochen wird, sobald er breiter als der alte Block ist.")
        assert outcome.mode == NATIVE
        changed = blocks(doc)[0]
        assert len(changed.lines) >= 2 and all(line.bounds[2] - line.bounds[0] <= width + 1 for line in changed.lines)
        assert blocks(doc)[1].text == "Ein zweiter Block weiter unten."
    finally:
        doc.close()


def test_overflow_asks_then_grows_or_shrinks(tmp_path: Path) -> None:
    doc = open_doc(samples.paragraph(tmp_path / "p.pdf"))
    history = commands.History()
    try:
        revision = doc.revision
        with pytest.raises(textedit.Overflow) as asked:
            textedit.edit_block(doc, history, blocks(doc)[0], LONG)
        assert asked.value.needed > asked.value.available == 3
        assert not history.can_undo and LONG not in page_text(doc) and doc.revision > revision  # nichts übernommen
        grown = textedit.edit_block(doc, history, blocks(doc)[0], LONG, overflow="grow")
        assert grown.mode == NATIVE and grown.lines == asked.value.needed
        assert textedit._squash(LONG) in textedit._squash(page_text(doc))
        history.undo(doc)
        shrunk = textedit.edit_block(doc, history, blocks(doc)[0], LONG, overflow="shrink")
        assert shrunk.mode == RECONSTRUCTED and shrunk.lines <= 3 and any("verkleinert" in note for note in shrunk.notes)
        assert block_with(doc, "Dies ist").size < 12.0
    finally:
        doc.close()


def test_single_line_that_would_leave_the_page_counts_as_overflow(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        too_long = "Rechnung " + "sehr lang " * 30
        with pytest.raises(textedit.Overflow):
            textedit.edit_block(doc, history, blocks(doc)[0], too_long)
        outcome = textedit.edit_block(doc, history, blocks(doc)[0], too_long, overflow="grow")
        assert outcome.lines >= 2 and outcome.bounds[2] <= doc.geometry(0).crop[2]
    finally:
        doc.close()


# --- Neu setzen, Ersatzschrift ---------------------------------------------------------------------------
def test_missing_character_falls_back_to_embedded_substitute_font(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        outcome = textedit.edit_block(doc, history, blocks(doc)[0], "Rechnung Łódka Ω")
        assert outcome.mode == RECONSTRUCTED and "Vera" in outcome.font
        assert any("Ersatzschrift" in note for note in outcome.notes)
        assert "Rechnung Łódka Ω" in page_text(doc) and "4711" not in page_text(doc)
        # Teilmenge eingebettet (FontFile2), mit ToUnicode – Text bleibt kopierbar
        added = [font for key, font in doc.pdf.pages[0].Resources.Font.items() if key.startswith("/PTF")]
        assert len(added) == 1 and added[0].Subtype == "/Type0" and "/ToUnicode" in added[0]
        assert "/FontFile2" in added[0].DescendantFonts[0].FontDescriptor
    finally:
        doc.close()


def test_character_without_any_font_is_refused_instead_of_broken_glyphs(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        data = snapshot(doc)
        with pytest.raises(UnsupportedEdit, match="»ő«"):
            textedit.edit_block(doc, history, blocks(doc)[0], "Rechnung ő")
        assert not history.can_undo and snapshot(doc) == data
    finally:
        doc.close()


def test_font_without_embedding_permission_is_never_embedded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fonts, "embedding_allowed", lambda data: False)
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        with pytest.raises(UnsupportedEdit):
            textedit.edit_block(doc, history, blocks(doc)[0], "Rechnung Ω")  # Ω gibt es nur in Vera
        # Zeichen der Standardschrift gehen weiterhin (ohne Einbetten)
        outcome = textedit.edit_block(doc, history, blocks(doc)[0], "Rechnung", style=TextStyle(family="Times"))
        assert outcome.mode == RECONSTRUCTED and outcome.font == "Times-Roman"
    finally:
        doc.close()


def test_format_change_reconstructs_with_new_size_color_and_bold(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        outcome = textedit.edit_block(doc, history, block_with(doc, "Gesamtbetrag"), "Gesamtbetrag: 1.234,56 EUR", style=TextStyle(size=16, color=(200, 0, 0)))
        assert outcome.mode == RECONSTRUCTED and outcome.font == "Helvetica-Bold"  # Originalschrift beibehalten
        changed = block_with(doc, "Gesamtbetrag")
        assert changed.size == 16.0 and changed.color == (200, 0, 0) and changed.font == "Helvetica-Bold"
        assert page_text(doc).count("Gesamtbetrag") == 1
        italic = textedit.edit_block(doc, history, block_with(doc, "Rechnung"), "Rechnung", style=TextStyle(italic=True))
        assert italic.font == "Helvetica-Oblique"
    finally:
        doc.close()


def test_right_alignment_keeps_the_right_edge(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        block = block_with(doc, "Gesamtbetrag")
        right = block.bounds[2]
        textedit.edit_block(doc, history, block, "Summe: 9 EUR", style=TextStyle(align="right"))
        changed = block_with(doc, "Summe")
        assert abs(changed.bounds[2] - right) < 1.5 and changed.bounds[0] > block.bounds[0] + 20
    finally:
        doc.close()


def test_vertical_text_stays_vertical(tmp_path: Path) -> None:
    doc = open_doc(samples.vertical_text(tmp_path / "v.pdf"))
    history = commands.History()
    try:
        native = textedit.edit_block(doc, history, blocks(doc)[0], "Senkrecht neu")
        rebuilt = textedit.edit_block(doc, history, block_with(doc, "Senkrecht"), "Senkrecht Ω")
        assert (native.mode, rebuilt.mode) == (NATIVE, RECONSTRUCTED)
        block = block_with(doc, "Senkrecht")
        assert block.angle == 90.0 and block.bounds[3] - block.bounds[1] > block.bounds[2] - block.bounds[0]
    finally:
        doc.close()


# --- Überlagerung (ehrlich gekennzeichnet) -----------------------------------------------------------------
def test_text_in_form_xobject_is_overlaid_and_labelled_as_not_a_redaction(tmp_path: Path) -> None:
    doc = open_doc(samples.form_xobject_text(tmp_path / "x.pdf"))
    history = commands.History()
    try:
        outcome = textedit.edit_block(doc, history, blocks(doc)[0], "Briefkopf Beispiel GmbH")
        assert outcome.mode == OVERLAY and "keine Schwärzung" in outcome.label and "bleibt in der Datei" in outcome.label
        text = page_text(doc)
        assert "Briefkopf Beispiel GmbH" in text
        assert "Briefkopf Muster AG" in text  # das Original ist weiterhin enthalten – keine Schwärzung
        # angeklickt wird der oben liegende (neue) Text
        top = textedit.block_at(blocks(doc), 80, 783)
        assert top is not None and top.text == "Briefkopf Beispiel GmbH" and top.editable_natively
    finally:
        doc.close()


def test_ocr_text_overlay_covers_the_visible_scan_text(tmp_path: Path) -> None:
    doc = open_doc(samples.scanned_with_ocr(tmp_path / "o.pdf"))
    history = commands.History()
    try:
        outcome = textedit.edit_block(doc, history, blocks(doc)[0], "Rechnung 456")
        assert outcome.mode == OVERLAY and "Texterkennung" in outcome.notes[0]
        # rechts neben dem neuen Text ist keine Schrift des Scans mehr zu sehen
        image = render.to_pil(render.render_page(doc, 0, 893)).convert("L")
        scale = image.width / doc.geometry(0).width
        new_right = block_with(doc, "456").bounds[2]
        strip = image.crop((int((new_right + 3) * scale), int((842 - 750) * scale), int(372 * scale), int((842 - 700) * scale)))
        assert strip.getextrema()[0] > 200
    finally:
        doc.close()


# --- Neuer Text ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_added_text_reads_upright_on_rotated_pages(tmp_path: Path, rotation: int) -> None:
    doc = open_doc(samples.rotated(tmp_path / "r.pdf"))
    history = commands.History()
    page = [0, 90, 180, 270].index(rotation)
    try:
        geo = doc.geometry(page)
        x, y = geo.to_page(100, 100)  # 100/100 pt von oben links in der Anzeige
        outcome = textedit.add_text(doc, history, page, x, y, "Neu ABC", style=TextStyle(size=14))
        assert outcome.mode == NATIVE and outcome.font == "Helvetica"
        hit = textlayer.search(doc, page, "Neu ABC")[0]
        boxes = [geo.rect_to_view(textlayer.char_box(doc, page, hit.start + i)) for i in range(hit.count)]
        lefts = [box[0] for box in boxes if box[2] > box[0]]
        assert lefts == sorted(lefts)  # in der Anzeige von links nach rechts
        assert all(abs(box[1] - boxes[0][1]) < 3 for box in boxes)  # auf einer Zeile
        top_left = (min(box[0] for box in boxes), min(box[1] for box in boxes))
        assert 99 <= top_left[0] <= 104 and 96 <= top_left[1] <= 106  # Oberkante ≈ 100 pt (Oberlänge der Schrift)
    finally:
        doc.close()


def test_added_text_wraps_aligns_and_undoes(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        before = snapshot(doc)
        outcome = textedit.add_text(doc, history, 0, 300, 500, "Ein neuer Hinweis, der in einem schmalen Rahmen umbrochen wird.", style=TextStyle(size=10, align="center"), width=120)
        assert outcome.lines >= 3 and history.undo_title == "Text hinzufügen"
        assert "Ein neuer Hinweis" in page_text(doc)
        history.undo(doc)
        assert "Ein neuer Hinweis" not in page_text(doc) and snapshot(doc) == before
        history.redo(doc)
        assert "Ein neuer Hinweis" in page_text(doc)
    finally:
        doc.close()


def test_added_text_with_characters_outside_winansi_embeds_a_subset(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        outcome = textedit.add_text(doc, history, 0, 72, 600, "Straße Łódka", style=TextStyle(size=12))
        assert "Vera" in outcome.font and "Straße Łódka" in page_text(doc)
        with pytest.raises(UnsupportedEdit, match="»ź«"):  # gibt es in keiner verfügbaren Schrift
            textedit.add_text(doc, history, 0, 72, 560, "Łódź", style=TextStyle(size=12))
    finally:
        doc.close()


# --- Rückgängig, Prüfung, Speichern -----------------------------------------------------------------------------
def test_undo_redo_restore_content_exactly(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        original = snapshot(doc)
        textedit.edit_block(doc, history, blocks(doc)[0], "Rechnung Nr. 1")
        textedit.edit_block(doc, history, block_with(doc, "Gesamtbetrag"), "Summe Łódka")
        edited = snapshot(doc)
        history.undo(doc)
        history.undo(doc)
        assert snapshot(doc) == original and "4711" in page_text(doc)
        history.redo(doc)
        history.redo(doc)
        assert snapshot(doc) == edited and "Summe Łódka" in page_text(doc)
    finally:
        doc.close()


def test_a_change_outside_the_block_is_detected_and_rolled_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sicherheitsnetz: Würde eine Änderung die Seite außerhalb des Blocks verändern, wird sie
    verworfen und der nächste Weg versucht – hier simuliert durch einen fehlerhaften nativen Weg."""
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    real_native = textedit._native

    def broken(document, block, new_text, content, overflow):
        footer = next(show for show in content.shows if content.text_of(show).startswith("Seite"))
        content.blank(footer)  # zerstört unbemerkt die Fußzeile
        return real_native(document, block, new_text, content, overflow)

    monkeypatch.setattr(textedit, "_native", broken)
    try:
        outcome = textedit.edit_block(doc, history, blocks(doc)[0], "Rechnung 2")
        assert outcome.mode == RECONSTRUCTED  # nativ verworfen, neu gesetzt
        assert "Seite 1 von 1" in page_text(doc) and "Rechnung 2" in page_text(doc)
        assert len(history._done) == 1
    finally:
        doc.close()


def test_read_only_documents_and_stale_blocks_are_refused(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.encrypted(tmp_path / "e.pdf", allow_edit=False), password="geheim")
    try:
        with pytest.raises(ReadOnlyDocument):
            textedit.edit_block(doc, commands.History(), blocks(doc)[0], "x")
        with pytest.raises(ReadOnlyDocument):
            textedit.add_text(doc, commands.History(), 0, 72, 500, "x")
    finally:
        doc.close()
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        old = blocks(doc)
        textedit.edit_block(doc, history, old[0], "Rechnung 1")
        with pytest.raises(UnsupportedEdit, match="nicht mehr aktuell"):
            textedit.edit_block(doc, history, old[1], "Summe")
    finally:
        doc.close()


def test_repeated_edits_do_not_nest_or_accumulate_fonts(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        first_size = len(doc.serialize())
        for number in range(25):
            textedit.edit_block(doc, history, block_with(doc, "Rechnung"), f"Rechnung Ω {number}")
        page = doc.pdf.pages[0]
        assert max_q_depth(page) <= 2
        assert sum(1 for key in page.Resources.Font.keys() if key.startswith("/PTF")) == 1
        assert page_text(doc).count("Rechnung") == 1
        final = len(doc.serialize())
        assert final < first_size + 60_000  # eine eingebettete Teilmenge, nicht 25
    finally:
        doc.close()


def test_edited_document_saves_validates_and_keeps_structure(tmp_path: Path) -> None:
    path = samples.structured(tmp_path / "s.pdf")
    doc = open_doc(path)
    history = commands.History()
    try:
        textedit.edit_block(doc, history, blocks(doc)[0], "Rechnung Nr. 5000")
        textedit.edit_block(doc, history, block_with(doc, "Gesamtbetrag"), "Summe Ω")
        textedit.add_text(doc, history, 0, 72, 500, "Geprüft")
        save.save(doc, path)
        assert not doc.dirty
    finally:
        doc.close()
    saved = open_doc(path)
    try:
        text = page_text(saved)
        assert "Rechnung Nr. 5000" in text and "Summe Ω" in text and "Geprüft" in text
        with pikepdf.open(path) as pdf:
            assert len(pdf.pages[0].Annots) == 2 and "notiz.txt" in pdf.attachments
            with pdf.open_outline() as outline:
                assert [item.title for item in outline.root] == ["Kapitel 1", "Kapitel 2"]
            assert pdf.check_pdf_syntax() == []
    finally:
        saved.close()


def test_content_of_untouched_pages_is_not_rewritten(tmp_path: Path) -> None:
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf", pages=3))
    history = commands.History()
    try:
        others = [doc.pdf.pages[i].obj.Contents.objgen for i in (0, 2)]
        textedit.edit_block(doc, history, blocks(doc, 1)[0], "Rechnung auf Seite 2", )
        assert [doc.pdf.pages[i].obj.Contents.objgen for i in (0, 2)] == others
    finally:
        doc.close()


def test_mapping_survives_blanked_operators(tmp_path: Path) -> None:
    """Gelöschter Text hinterlässt leere Operatoren – PDFium erzeugt dafür kein Textobjekt; die
    Zuordnung der übrigen Texte muss trotzdem stimmen (weitere native Änderungen möglich)."""
    doc = open_doc(samples.standard_text(tmp_path / "a.pdf"))
    history = commands.History()
    try:
        textedit.edit_block(doc, history, blocks(doc)[0], "")
        assert all(block.editable_natively for block in blocks(doc))
        outcome = textedit.edit_block(doc, history, block_with(doc, "Zahlbar"), "Zahlbar sofort.")
        assert outcome.mode == NATIVE
        content = PageContent(doc.pdf, doc.pdf.pages[0].obj, page_fonts(doc.pdf.pages[0].obj))
        assert sum(1 for show in content.shows if not show.raw) == 1
    finally:
        doc.close()


def test_saved_bytes_reopen_in_pikepdf_and_pdfium(tmp_path: Path) -> None:
    doc = open_doc(samples.cid_font(tmp_path / "c.pdf"))
    history = commands.History()
    try:
        textedit.edit_block(doc, history, blocks(doc)[0], "Lieferschein Ω-1")
        data = doc.serialize()
    finally:
        doc.close()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert pdf.check_pdf_syntax() == []
    again = EditorDocument.from_bytes(data, name="x.pdf")
    try:
        assert "Lieferschein Ω-1" in page_text(again)
    finally:
        again.close()
