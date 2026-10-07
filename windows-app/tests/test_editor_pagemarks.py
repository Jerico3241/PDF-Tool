"""Wasserzeichen, Kopf- und Fußzeile, Seitenzahlen und Bates-Nummern.

Geprüft mit PDFium wie in der Anzeige: Der Text steht auf jeder gewählten Seite, aufrecht und an der
gewählten Stelle – auch auf gedrehten Seiten. Entfernen nimmt nur die Markierungen von PDF Tool
heraus; alles ist ein Schritt für Rückgängig und übersteht das Speichern.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pikepdf
import pytest

import editorsamples as samples
from tools.pdf_editor import commands, pagemarks, save
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.geometry import normalize
from pdfium_lock import PDFIUM_LOCK


@pytest.fixture(autouse=True)
def no_lxml(monkeypatch):
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)


def find_text(doc: EditorDocument, page: int, needle: str):
    """Rechteck (Anzeige-Punkte) eines Textes auf der Seite – oder ``None``."""
    geo = doc.geometry(page)
    with PDFIUM_LOCK:
        textpage = doc.textpage(page)
        text = textpage.get_text_range()
        start = text.find(needle)
        if start < 0:
            return None
        boxes = [geo.rect_to_view(normalize(textpage.get_charbox(i, loose=False))) for i in range(start, start + len(needle)) if text[i].strip()]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def test_page_numbers_bates_and_header_on_every_chosen_page(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "Akte Müller.pdf", pages=3)
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        spec = pagemarks.HeaderFooter(
            items=[pagemarks.TextMark("Blatt {seite} von {seiten}", "bc"), pagemarks.TextMark("{bates}", "br"), pagemarks.TextMark("{datei} · {datum}", "tl")],
            bates_prefix="AKTE-", bates_digits=5, bates_start=41,
        )
        result = pagemarks.add_header_footer(doc, history, spec)
        assert result.pages == 3 and result.replaced == []  # »·« gibt es in WinAnsi
        assert history.undo_title == "Kopf- und Fußzeile hinzufügen"
        geo = doc.geometry(1)
        box = find_text(doc, 1, "Blatt 2 von 3")
        assert box is not None
        assert geo.height - 40 < box[3] <= geo.height and abs((box[0] + box[2]) / 2 - geo.width / 2) < 2  # unten Mitte
        bates = find_text(doc, 2, "AKTE-00043")
        assert bates is not None and bates[2] > geo.width - 40  # rechts unten, dritte Seite → 41 + 2
        header = find_text(doc, 0, "Akte M")
        assert header is not None and header[1] < 40 and header[0] < 40  # oben links, Dateiname ohne .pdf
        assert pagemarks.present(doc) == {"Header": 3, "Watermark": 0}
        save.save(doc, path)
    finally:
        doc.close()
    reopened = EditorDocument.open(path)
    try:
        assert find_text(reopened, 0, "Blatt 1 von 3") is not None
    finally:
        reopened.close()


@pytest.mark.parametrize("rotate", [90, 180, 270])
def test_marks_stand_upright_where_you_see_them_on_rotated_pages(tmp_path: Path, rotate: int) -> None:
    path = samples.direct_image(tmp_path / "gedreht.pdf", rotate=rotate)
    doc = EditorDocument.open(path)
    try:
        pagemarks.add_header_footer(doc, commands.History(), pagemarks.HeaderFooter(items=[pagemarks.TextMark("Seite {seite}", "br")], size=12))
        geo = doc.geometry(0)
        box = find_text(doc, 0, "Seite 1")
        assert box is not None
        assert box[2] - box[0] > (box[3] - box[1]) * 2  # waagerecht lesbar, nicht hochkant
        assert box[2] <= geo.width - 20 and box[3] > geo.height - 40  # rechts unten in der Anzeige
    finally:
        doc.close()


def test_watermark_with_opacity_behind_and_removal_keeps_everything_else(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "Entwurf.pdf", pages=2)
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        pagemarks.add_header_footer(doc, history, pagemarks.HeaderFooter(items=[pagemarks.TextMark("Seite {seite}", "bc")]))
        result = pagemarks.add_watermark(doc, history, pagemarks.Watermark("VERTRAULICH", opacity=0.3, behind=True, pages=[1]))
        assert result.pages == 1
        page = doc.pdf.pages[1].obj
        assert str(page.Contents[0].get("/PDFToolMark")) == "/Watermark"  # unter dem Inhalt
        states = [value for key, value in page.Resources.ExtGState.items() if str(key).startswith("/PTMarkGS")]
        assert states and abs(float(states[0].ca) - 0.3) < 1e-6
        assert find_text(doc, 1, "VERTRAULICH") is not None and find_text(doc, 0, "VERTRAULICH") is None
        assert pagemarks.present(doc) == {"Header": 2, "Watermark": 1}
        assert pagemarks.remove_marks(doc, history, (pagemarks.WATERMARK,)) == 1
        assert find_text(doc, 1, "VERTRAULICH") is None and find_text(doc, 1, "Seite 2") is not None
        assert find_text(doc, 1, "Rechnung Nr. 4711") is not None
        assert not any(str(key).startswith("/PTMarkGS") for key in doc.pdf.pages[1].obj.Resources.get("/ExtGState", {}).keys())
        history.undo(doc)
        assert find_text(doc, 1, "VERTRAULICH") is not None
        save.save(doc, tmp_path / "Entwurf markiert.pdf")
    finally:
        doc.close()
    with pikepdf.open(tmp_path / "Entwurf markiert.pdf") as pdf:
        assert len(pdf.pages) == 2


def test_text_outside_winansi_is_replaced_and_reported(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "a.pdf"))
    try:
        result = pagemarks.add_watermark(doc, commands.History(), pagemarks.Watermark("Prüfung ✓ €"))
        assert result.replaced == ["✓"]
        assert find_text(doc, 0, "Prüfung ? €") is not None
    finally:
        doc.close()
