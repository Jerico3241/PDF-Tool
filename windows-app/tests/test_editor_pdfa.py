"""Als PDF/A speichern (4.0): PDF/A-2b-Kopie mit eingebetteten Schriften, sRGB-Ausgabebedingung und XMP.

Wie in der installierten App ohne lxml; als Ersatzschrift dient Bitstream Vera (``PDFTOOL_FONT_DIRS``).
Geprüft wird mit ``pdfa.check`` und direkt in der Datei – die vollständige Prüfung mit veraPDF lief bei
der Entwicklung über dieselben Beispiele.
"""

from __future__ import annotations

import io
import sys

import pikepdf
import pytest

import editorsamples as samples
from tools.pdf_editor import fonts, pdfa
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import EditorError


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)
    monkeypatch.setenv("PDFTOOL_FONT_DIRS", str(samples.vera_path().parent))
    fonts.find_system_font.cache_clear()
    yield
    fonts.find_system_font.cache_clear()


def convert(path):
    return pdfa.convert(path.read_bytes())


def embedded_fonts(data: bytes) -> list[str]:
    names = []
    with pikepdf.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for _name, font in (page.Resources.get("/Font") or {}).items():
                descriptor = font.get("/FontDescriptor")
                if font.get("/Subtype") == "/Type0":
                    descriptor = font.DescendantFonts[0].get("/FontDescriptor")
                assert descriptor is not None and any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3")), str(font.get("/BaseFont"))
                names.append(str(font.BaseFont))
    return names


def test_standard_fonts_are_replaced_by_embedded_subsets(tmp_path):
    data, result = convert(samples.standard_text(tmp_path / "a.pdf"))
    assert pdfa.check(data) == []
    assert result.fonts >= 1
    assert len(embedded_fonts(data)) == 3


def test_text_stays_readable_after_conversion(tmp_path):
    source = samples.standard_text(tmp_path / "a.pdf", lines=("Rechnung 2026-0815", "Summe: 1.234,50 €"))
    data, _ = convert(source)
    document = EditorDocument.from_bytes(data, name="a.pdf")
    try:
        import pypdfium2

        page = pypdfium2.PdfDocument(data)[0]
        text = page.get_textpage().get_text_range()
    finally:
        document.close()
    assert "Rechnung 2026-0815" in text
    assert "1.234,50 €" in text


def test_output_intent_and_xmp_identification(tmp_path):
    data, _ = convert(samples.with_xmp(tmp_path / "a.pdf"))
    with pikepdf.open(io.BytesIO(data)) as pdf:
        intent = pdf.Root.OutputIntents[0]
        assert intent.S == "/GTS_PDFA1"
        assert "/DestOutputProfile" in intent
        packet = pdf.Root.Metadata.read_bytes().decode("utf-8")
        assert pdf.docinfo.Producer == "Novadesk"
        assert pdf.pdf_version >= "1.7"
    assert "<pdfaid:part>2</pdfaid:part>" in packet
    assert "<pdfaid:conformance>B</pdfaid:conformance>" in packet
    assert "Novadesk" in packet


def test_signature_and_attachments_are_removed_with_a_note(tmp_path):
    data, result = convert(samples.signed(tmp_path / "s.pdf"))
    assert pdfa.check(data) == []
    assert any("Signatur" in note for note in result.notes)
    data, result = convert(samples.structured(tmp_path / "t.pdf"))
    assert pdfa.check(data) == []
    assert "Eingebettete Dateien entfernt" in result.notes


def test_cid_and_form_documents_convert(tmp_path):
    for source in (samples.cid_font(tmp_path / "c.pdf"), samples.form(tmp_path / "f.pdf"), samples.object_fonts(tmp_path / "o.pdf")):
        data, _ = convert(source)
        assert pdfa.check(data) == [], source.name


def test_each_font_is_embedded_only_once(tmp_path):
    data, _ = convert(samples.standard_text(tmp_path / "a.pdf", pages=5))
    with pikepdf.open(io.BytesIO(data)) as pdf:
        files = {font.FontDescriptor.FontFile2.objgen for page in pdf.pages for _n, font in page.Resources.Font.items() if "/FontFile2" in font.get("/FontDescriptor", {})}
    assert 1 <= len(files) <= 3  # je Ersatzschrift einmal – nicht einmal je Seite (5 Seiten × 3)


def test_without_a_substitute_font_the_reason_is_named(tmp_path, monkeypatch):
    empty = tmp_path / "keine-schriften"
    empty.mkdir()
    monkeypatch.setenv("PDFTOOL_FONT_DIRS", str(empty))
    fonts.find_system_font.cache_clear()
    with pytest.raises(pdfa.PdfaError) as caught:
        convert(samples.standard_text(tmp_path / "a.pdf"))
    assert any("Helvetica" in problem for problem in caught.value.problems)


def test_check_finds_a_plain_pdf_lacking(tmp_path):
    problems = pdfa.check(samples.standard_text(tmp_path / "a.pdf").read_bytes())
    assert "keine Ausgabebedingung" in problems
    assert "keine PDF/A-Kennung in den Metadaten" in problems
    assert any("nicht eingebettet" in problem for problem in problems)


def test_save_copy_removes_encryption_and_never_overwrites_the_original(tmp_path):
    source = samples.encrypted(tmp_path / "geheim.pdf")
    original = source.read_bytes()
    document = EditorDocument.open(source, password="geheim")
    try:
        with pytest.raises(EditorError):
            pdfa.save_copy(document, source)
        result = pdfa.save_copy(document, tmp_path / "geheim_pdfa.pdf")
    finally:
        document.close()
    assert source.read_bytes() == original
    assert "Kennwortschutz entfernt" in result.notes
    assert pdfa.check((tmp_path / "geheim_pdfa.pdf").read_bytes()) == []
