"""Stapel-Aktionen (4.0): Plan, feste Reihenfolge und Bearbeitung einer Datei – ohne Oberfläche.

Die Schritte sind die Werkzeuge des PDF Editors; hier wird geprüft, dass sie zusammen laufen, in der
festen Reihenfolge, auf eine neue Datei, ohne das Original zu verändern, und dass ein Kennwort nie in
den gespeicherten Einstellungen landet.
"""

from __future__ import annotations

import io
import sys
import threading

import pikepdf
import pytest

import editorsamples as samples
from tools.pdf_actions import actions, runner
from tools.pdf_actions.actions import Plan
from tools.pdf_editor import fonts, pdfa
from tools.pdf_editor.errors import EditorError


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)
    monkeypatch.setenv("PDFTOOL_FONT_DIRS", str(samples.vera_path().parent))
    fonts.find_system_font.cache_clear()
    yield
    fonts.find_system_font.cache_clear()


def text_of(path, password=None):
    import pypdfium2

    document = pypdfium2.PdfDocument(str(path), password=password)
    try:
        return [page.get_textpage().get_text_range() for page in document]
    finally:
        document.close()


def test_order_is_fixed_whatever_the_click_order():
    plan = Plan(steps=[actions.PROTECT, actions.NUMBERS, actions.OCR, actions.WATERMARK])
    assert plan.ordered() == [actions.OCR, actions.WATERMARK, actions.NUMBERS, actions.PROTECT]
    assert plan.summary() == "Text erkennen (OCR) → Wasserzeichen → Seitenzahlen → Kennwortschutz"


def test_problems_are_named():
    assert actions.problem(Plan()) == "Bitte mindestens eine Aktion wählen."
    assert "nicht kombinieren" in actions.problem(Plan(steps=[actions.PDFA, actions.PROTECT], password="geheim"))
    assert "Wasserzeichen" in actions.problem(Plan(steps=[actions.WATERMARK], watermark_text="  "))
    assert "Kennwort" in actions.problem(Plan(steps=[actions.PROTECT], password="abc"))
    assert actions.problem(Plan(steps=[actions.PROTECT], password="abcd")) == ""


def test_settings_round_trip_without_password():
    plan = Plan(steps=[actions.WATERMARK, actions.PROTECT, actions.NUMBERS], watermark_text="ENTWURF", watermark_opacity=0.4, number_format="zahl_von", number_position="br", optimize_level="hoch", password="geheim123")
    stored = plan.settings()
    assert "geheim123" not in repr(stored)
    again = Plan.from_settings(stored)
    assert again.ordered() == [actions.WATERMARK, actions.NUMBERS]  # Kennwortschutz wird jedes Mal neu gewählt
    assert (again.watermark_text, again.watermark_opacity, again.number_format, again.number_position, again.optimize_level) == ("ENTWURF", 0.4, "zahl_von", "br", "hoch")
    assert again.password == ""


def test_broken_settings_fall_back_to_defaults():
    plan = Plan.from_settings({"schritte": ["format_c", 7, actions.OPTIMIZE], "deckkraft": "viel", "seitenzahl": "römisch", "stufe": "extrem", "ocr_sprachen": ["deu", "../../x" * 5]})
    assert plan.ordered() == [actions.OPTIMIZE]
    assert plan.watermark_opacity == 0.25 and plan.number_format == "seite_von" and plan.optimize_level == "mittel"
    assert plan.ocr_languages == ["deu"]
    assert Plan.from_settings(None).ordered() == []


def test_watermark_and_numbers_land_on_every_page(tmp_path):
    source = samples.standard_text(tmp_path / "brief.pdf", pages=3)
    original = source.read_bytes()
    result = runner.process(source, tmp_path / "brief_bearbeitet.pdf", Plan(steps=[actions.WATERMARK, actions.NUMBERS], watermark_text="ENTWURF"))
    assert source.read_bytes() == original
    texts = text_of(result.target)
    assert all("ENTWURF" in text for text in texts)
    assert [("Seite %d von 3" % n) in text for n, text in enumerate(texts, start=1)] == [True, True, True]
    assert result.before == len(original) and result.after == result.target.stat().st_size


def test_full_chain_ends_as_valid_pdfa(tmp_path):
    source = samples.structured(tmp_path / "akte.pdf")
    steps = [actions.CLEAN, actions.FLATTEN, actions.WATERMARK, actions.NUMBERS, actions.OPTIMIZE, actions.PDFA]
    progress: list[str] = []
    result = runner.process(source, tmp_path / "akte_a.pdf", Plan(steps=steps), progress=progress.append)
    assert pdfa.check(result.target.read_bytes()) == []
    assert progress[0] == "Dokument bereinigen …" and progress[-1] == "Als PDF/A speichern …"
    assert any("eingebettet" in note for note in result.notes)


def test_protect_encrypts_the_result(tmp_path):
    source = samples.standard_text(tmp_path / "a.pdf")
    result = runner.process(source, tmp_path / "a_geschuetzt.pdf", Plan(steps=[actions.NUMBERS, actions.PROTECT], password="geheim"))
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(result.target)
    assert "Seite 1 von 1" in text_of(result.target, password="geheim")[0]


def test_encrypted_source_needs_its_password(tmp_path):
    source = samples.encrypted(tmp_path / "geheim.pdf")
    with pytest.raises(EditorError):
        runner.process(source, tmp_path / "x.pdf", Plan(steps=[actions.NUMBERS]))
    result = runner.process(source, tmp_path / "x.pdf", Plan(steps=[actions.NUMBERS]), password="geheim")
    assert "Seite 1 von 1" in text_of(result.target, password="geheim")[0]


def test_never_writes_over_the_original_and_cancel_leaves_nothing(tmp_path):
    source = samples.standard_text(tmp_path / "a.pdf")
    with pytest.raises(EditorError):
        runner.process(source, source, Plan(steps=[actions.NUMBERS]))
    stop = threading.Event()
    stop.set()
    with pytest.raises(runner.Cancelled):
        runner.process(source, tmp_path / "b.pdf", Plan(steps=[actions.NUMBERS]), cancel=stop)
    assert not (tmp_path / "b.pdf").exists()
    with pytest.raises(EditorError):
        runner.process(source, tmp_path / "c.pdf", Plan())


def test_ocr_without_engine_is_a_clear_error(tmp_path, monkeypatch):
    from tools.pdf_editor import ocr

    monkeypatch.setattr(ocr, "find_engine", lambda: None)
    with pytest.raises(EditorError, match="Texterkennung"):
        runner.process(samples.scanned_with_ocr(tmp_path / "scan.pdf"), tmp_path / "x.pdf", Plan(steps=[actions.OCR]))
