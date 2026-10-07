"""Schwärzen: markierte Inhalte sind danach wirklich weg – nicht nur überdeckt.

Geprüft wird mit PDFium (Textschicht), an den Rohdaten der gespeicherten Datei (kein Text im
Klartext mehr) und an den Bildpunkten. Der übrige Text bleibt an seiner Stelle. Fälle: normaler Text,
TJ mit Abständen, CID-Schrift, Text in einem Formular-XObject, Scan mit unsichtbarer Texterkennung,
gedrehte Seite, Anmerkungen, Mustersuche (IBAN mit Prüfziffer, E-Mail, Telefon, Datum) und der
Rückfall »Seite als Bild« (Inline-Bild).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pikepdf
import pytest

import editorsamples as samples
from pdfium_lock import PDFIUM_LOCK
from tools.pdf_editor import commands, redact, render, save
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.geometry import normalize


@pytest.fixture(autouse=True)
def no_lxml(monkeypatch):
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)


def text(doc: EditorDocument, page: int = 0) -> str:
    with PDFIUM_LOCK:
        return doc.textpage(page).get_text_range()


def box_of(doc: EditorDocument, needle: str, page: int = 0):
    """Seitenkoordinaten eines Textes (erste Fundstelle) – wie die Markierung aus der Suche."""
    hits = [m for m in redact.find_matches(doc, [], [needle], [page], match_case=True)]
    assert hits, needle
    return hits[0].rects


def char_x(doc: EditorDocument, needle: str, page: int = 0) -> float:
    with PDFIUM_LOCK:
        textpage = doc.textpage(page)
        index = textpage.get_text_range().find(needle)
        return normalize(textpage.get_charbox(index, loose=False))[0]


def raw_streams(path: Path) -> bytes:
    """Alle Datenströme der Datei dekodiert aneinander (für die Suche nach Resten)."""
    out = b""
    with pikepdf.open(path) as pdf:
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Stream):
                try:
                    out += obj.read_bytes()
                except pikepdf.PdfError:
                    out += obj.read_raw_bytes()
    return out


def test_text_is_removed_from_the_file_and_neighbours_stay_in_place(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "Rechnung.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        x_before = char_x(doc, "vom")
        marks = [redact.Mark(0, rect) for rect in box_of(doc, "4711")]
        result = redact.apply_marks(doc, history, marks)
        assert result.chars == 4 and not result.rasterized and history.undo_title == "Schwärzen"
        after = text(doc)
        assert "4711" not in after and "Rechnung Nr." in after and "vom 01.10.2026" in after
        assert abs(char_x(doc, "vom") - x_before) < 0.05  # Rest der Zeile bleibt, wo er war
        region = render.to_pil(render.render_region(doc, 0, doc.geometry(0).rect_to_view(marks[0].rect), 2.0)).convert("L")
        assert region.getextrema()[1] < 40  # deckend schwarz
        save.save(doc, path)
        history.undo(doc)
        assert "4711" in text(doc)
    finally:
        doc.close()
    assert b"4711" not in raw_streams(path)


def test_kerned_tj_cid_font_and_form_xobject_text(tmp_path: Path) -> None:
    kerned = EditorDocument.open(samples.complex_content(tmp_path / "kerning.pdf"))
    try:
        redact.apply_marks(kerned, commands.History(), [redact.Mark(0, r) for r in box_of(kerned, "trag")])
        content = text(kerned)
        assert "trag" not in content and "Ver" in content and "Nr. 9" in content
    finally:
        kerned.close()
    cid = EditorDocument.open(samples.cid_font(tmp_path / "cid.pdf"))
    try:
        redact.apply_marks(cid, commands.History(), [redact.Mark(0, r) for r in box_of(cid, "2026-0042")])
        assert "2026-0042" not in text(cid) and "Lieferschein" in text(cid)
    finally:
        cid.close()
    form_path = samples.form_xobject_text(tmp_path / "briefkopf.pdf")
    form = EditorDocument.open(form_path)
    try:
        original = form.pdf.pages[0].Resources.XObject.X1
        result = redact.apply_marks(form, commands.History(), [redact.Mark(0, r) for r in box_of(form, "Muster AG")])
        assert result.chars == 8 and "Muster AG" not in text(form) and "Briefkopf" in text(form)
        assert form.pdf.pages[0].Resources.XObject.X1.objgen != original.objgen  # eigene Kopie
        save.save(form, form_path)
    finally:
        form.close()
    assert b"Muster AG" not in raw_streams(form_path)


def test_scan_with_invisible_ocr_text_loses_pixels_and_text(tmp_path: Path) -> None:
    path = samples.scanned_with_ocr(tmp_path / "scan.pdf")
    doc = EditorDocument.open(path)
    try:
        marks = [redact.Mark(0, r) for r in box_of(doc, "123")]
        result = redact.apply_marks(doc, commands.History(), marks)
        assert result.images == 1 and result.chars == 3 and not result.rasterized
        assert "123" not in text(doc) and "Rechnung" in text(doc)
        image = doc.pdf.pages[0].Resources.XObject.Im1
        picture = pikepdf.PdfImage(image).as_pil_image()
        # Mitte des Bereichs in Bildpunkten: dort ist das Bild selbst schwarz (nicht nur überdeckt)
        rect = marks[0].rect
        u = ((rect[0] + rect[2]) / 2 - 72) / 300
        v = ((rect[1] + rect[3]) / 2 - 700) / 50
        assert picture.getpixel((int(u * 600), int((1 - v) * 100))) == 0
    finally:
        doc.close()


def test_rotated_page_and_annotations_in_the_area(tmp_path: Path) -> None:
    rotated = EditorDocument.open(samples.rotated(tmp_path / "gedreht.pdf"))
    try:
        result = redact.apply_marks(rotated, commands.History(), [redact.Mark(1, r) for r in box_of(rotated, "1.234,56", page=1)])
        assert result.chars >= 8 and "1.234,56" not in text(rotated, 1) and "1.234,56" in text(rotated, 0)
    finally:
        rotated.close()
    structured = EditorDocument.open(samples.structured(tmp_path / "kommentar.pdf"))
    try:
        result = redact.apply_marks(structured, commands.History(), [redact.Mark(0, (390.0, 750.0, 430.0, 790.0))])
        assert result.annotations == 1
        assert [str(a.Subtype) for a in structured.pdf.pages[0].obj.Annots] == ["/Link"]
    finally:
        structured.close()


def test_pattern_search_finds_iban_email_phone_and_dates(tmp_path: Path) -> None:
    lines = (
        "IBAN DE89 3704 0044 0532 0130 00 und DE00 1234 5678 9012 3456 78",
        "Kontakt: erika.muster@example.org, Tel. +49 30 1234567",
        "geboren am 01.02.1980, Vertrag 4711",
    )
    doc = EditorDocument.open(samples.standard_text(tmp_path / "daten.pdf", lines=lines))
    try:
        found = redact.find_matches(doc, ["iban", "email", "phone", "date"], ["Vertrag"])
        kinds = {(m.kind, m.text) for m in found}
        assert ("iban", "DE89 3704 0044 0532 0130 00") in kinds
        assert not any(m.text.startswith("DE00") for m in found)  # falsche Prüfziffer
        assert ("email", "erika.muster@example.org") in kinds
        assert any(m.kind == "phone" and "1234567" in m.text for m in found)
        assert ("date", "01.02.1980") in kinds and ("term", "Vertrag") in kinds
        result = redact.apply_marks(doc, commands.History(), [redact.Mark(m.page, r) for m in found for r in m.rects])
        remaining = text(doc)
        assert "3704" not in remaining and "example.org" not in remaining and "1980" not in remaining and "Vertrag" not in remaining
        assert "Kontakt:" in remaining and result.areas >= 5
    finally:
        doc.close()


def test_inline_image_in_the_area_falls_back_to_a_page_image(tmp_path: Path) -> None:
    path = samples.complex_content(tmp_path / "inline.pdf")  # Inline-Bild bei 72/600 (100 × 50)
    doc = EditorDocument.open(path)
    try:
        result = redact.apply_marks(doc, commands.History(), [redact.Mark(0, (80.0, 610.0, 120.0, 640.0))])
        assert result.rasterized == [0] and "als Bild geschwärzt" in result.notes[0]
        assert text(doc).strip() == ""  # Seite ist ein Bild – kein Text mehr
        save.save(doc, path)
    finally:
        doc.close()
    data = raw_streams(path)
    assert b"Kopfzeile" not in data and b"Nr. 9" not in data
