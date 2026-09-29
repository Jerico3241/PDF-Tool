"""Erweiterte PDF-Wiederherstellung: pypdf als dritte Engine, Rohanalyse, Neuaufbau von
Querverweisen, Trailer, startxref, %%EOF und Seitenbaum.

Alle Test-PDFs entstehen programmatisch (``pdfsamples.py``). Geprüft wird nie nur das
Öffnen: Seitenzahl, Text, Seitengröße und Darstellbarkeit der Ausgabe.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
import pytest

import pdfsamples as samples
from tools.pdf_repair import engine
from tools.pdf_repair.models import STAGES, Condition, Method, RepairMode, RepairStatus
from tools.pdf_repair.recovery import lenient, rebuild, scanner

pypdf = pytest.importorskip("pypdf")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repair(path: Path, tmp_path: Path, password: str | None = None):
    work = tmp_path / "arbeit"
    work.mkdir(exist_ok=True)
    before = digest(path)
    stages = []
    result = engine.repair(path, work, password, RepairMode.AUTO, None, lambda stage, fraction=None: stages.append(stage))
    assert digest(path) == before, "Original wurde verändert"
    return result, stages


def texts(pdf_path: str) -> list[str]:
    reader = pypdf.PdfReader(pdf_path)
    return [" ".join((page.extract_text() or "").split()) for page in reader.pages]


def assert_usable(pdf_path: str, pages: int, contains: list[str] | None = None, size=(595, 842)) -> None:
    """Die Ausgabe öffnet ohne Wiederherstellung, hat die Seiten, den Text, die Größe und lässt sich darstellen."""
    with pikepdf.open(pdf_path, attempt_recovery=False) as pdf:
        assert pdf.get_warnings() == []
        assert len(pdf.pages) == pages
        for page in pdf.pages:
            assert [round(float(v)) for v in page.mediabox] == [0, 0, *size]
            assert page.obj.Parent.Type == "/Pages" and page.obj.Parent.Count == pages
    content = texts(pdf_path)
    for index, expected in enumerate(contains or []):
        assert expected in content[index], (index, content[index])
    doc = pdfium.PdfDocument(pdf_path)
    try:
        assert len(doc) == pages
        bitmap = doc[0].render(scale=0.3).to_pil()
        assert bitmap.getextrema() != ((255, 255), (255, 255), (255, 255))  # nicht leer
    finally:
        doc.close()


# --- 100: der reale Fall ----------------------------------------------------------------------------------------


def test_real_world_case_is_not_given_up(tmp_path: Path) -> None:
    damaged = samples.real_case(tmp_path / "Vertrag.pdf")
    analysis = engine.analyze(damaged)
    assert analysis.condition is Condition.RAW_RECOVERABLE and analysis.repairable and analysis.error is None
    assert analysis.pdf_version == "1.4" and analysis.pages_expected == 3
    checks = {check.key: check for check in analysis.checks}
    assert checks["eof"].ok is False and checks["xref"].ok is False and checks["trailer"].ok is False
    assert checks["objects"].ok and checks["objects"].detail == "9 gefunden"
    assert checks["pages"].detail == "nicht lesbar – 3 Seitenobjekte gefunden"
    assert checks["raw_catalog"].ok and checks["raw_pages"].detail == "3" and checks["second"].ok is False
    result, stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.method is Method.PAGE_TREE_REBUILD
    assert result.pages_before == result.pages_after == 3 and result.warnings == []
    assert {"lenient", "raw_scan", "xref_rebuild", "trailer_rebuild", "page_tree_rebuild", "normalize", "validate"} <= set(stages)
    assert any("Seitenbaum aus 3 Seitenobjekten neu aufgebaut" in action for action in result.repair_actions)
    assert_usable(result.output_path, 3, ["Seite 1 von 3", "Seite 2 von 3", "Seite 3 von 3"])


# --- 101–104: einzelne Strukturschäden -----------------------------------------------------------------------------


def test_only_eof_missing_is_repairable(tmp_path: Path) -> None:
    damaged = samples.only_eof_missing(tmp_path / "ohne-eof.pdf")
    analysis = engine.analyze(damaged)
    assert analysis.condition is Condition.REPAIRABLE and engine.FINDINGS["eof"] in analysis.structural_errors
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.method is Method.REWRITE
    assert b"%%EOF" in Path(result.output_path).read_bytes()[-64:]
    assert_usable(result.output_path, 2, ["Seite 1 von 2", "Seite 2 von 2"])


def test_wrong_startxref_is_repairable(tmp_path: Path) -> None:
    damaged = samples.xref_offset(tmp_path / "startxref.pdf")
    raw = scanner.scan(damaged).stats
    assert raw.startxref and not raw.startxref_valid
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.pages_after == 5


@pytest.mark.parametrize("make", [samples.xref_missing, samples.trailer_missing, samples.real_case], ids=["xref-fehlt", "trailer-fehlt", "beides"])
def test_xref_and_trailer_are_rebuilt_from_the_objects(tmp_path: Path, make) -> None:
    damaged = make(tmp_path / "kaputt.pdf")
    scan = scanner.scan(damaged)
    out = tmp_path / "neu.pdf"
    classic = rebuild.write_classic(scan, damaged, out)
    assert classic is not None and classic.catalog == (1, 0) and not classic.catalog_created
    data = out.read_bytes()
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    # startxref zeigt exakt auf die neue Querverweistabelle, jeder Eintrag exakt auf sein Objekt
    offset = int(data[data.rfind(b"startxref") + 9 :].split()[0])
    assert data[offset : offset + 4] == b"xref"
    for number, obj in scan.objects.items():
        entry = data.find(b"%010d 00000 n" % data.find(b"%d 0 obj" % number))
        assert entry > offset, number
    trailer = data[data.rfind(b"trailer") :]
    assert b"/Root 1 0 R" in trailer and b"/Size" in trailer
    with pikepdf.open(out, attempt_recovery=False) as pdf:
        assert pdf.get_warnings() == [] or make is samples.real_case  # beim realen Fall fehlt noch der Seitenbaum
        assert pdf.Root.Type == "/Catalog"


# --- 105–107: Seitenbaum -----------------------------------------------------------------------------------------------


def test_broken_parent_references_are_valid_afterwards(tmp_path: Path) -> None:
    damaged = samples.broken_parents(tmp_path / "eltern.pdf")
    assert engine.analyze(damaged).condition is Condition.RAW_RECOVERABLE
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.method is Method.PAGE_TREE_REBUILD
    assert_usable(result.output_path, 3, ["Seite 1 von 3", "Seite 2 von 3", "Seite 3 von 3"])
    with pikepdf.open(result.output_path) as pdf:
        root = pdf.Root.Pages
        assert all(page.obj.Parent.objgen == root.objgen for page in pdf.pages)


def test_inherited_resources_and_page_size_survive(tmp_path: Path) -> None:
    damaged = samples.inherited_resources(tmp_path / "geerbt.pdf")
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.warnings == []
    assert any("Geerbte Seiteneigenschaften übernommen" in action and "MediaBox" in action and "Resources" in action for action in result.repair_actions)
    assert_usable(result.output_path, 3, ["Seite 1 von 3", "Seite 2 von 3", "Seite 3 von 3"])
    with pikepdf.open(result.output_path) as pdf:
        assert all("/Font" in page.obj.Resources for page in pdf.pages)


def test_page_order_follows_the_remaining_tree_then_object_numbers(tmp_path: Path) -> None:
    objs = samples.classic_objects(4)
    objs[2] = b"<< /Type /Pages /Kids [ 8 0 R 99 0 R 4 0 R ] /Count 3 >>"  # teilweise lesbar: Seite 3, dann Seite 1
    damaged = tmp_path / "reihenfolge.pdf"
    damaged.write_bytes(samples._cut_structure(samples.classic_bytes(objs)))
    result, _stages = repair(damaged, tmp_path)
    assert result.pages_after == 4
    assert [text.split(" von")[0] for text in texts(result.output_path)] == ["Seite 3", "Seite 1", "Seite 2", "Seite 4"]


# --- 108–109: Rohanalyse --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("indirect", [False, True], ids=["Length-direkt", "Length-Verweis"])
def test_binary_stream_content_never_becomes_an_object(tmp_path: Path, indirect: bool) -> None:
    damaged = samples.binary_false_positive(tmp_path / "binaer.pdf", indirect_length=indirect)
    scan = scanner.scan(damaged)
    assert 20 not in scan.objects
    assert scan.objects[1].kind == "Catalog" and scan.objects[1].dict_head.count(b"/Pages") == 1  # der echte Katalog
    assert scan.stats.pages == 3 and scan.objects[30].stream is not None
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.pages_after == 3
    assert_usable(result.output_path, 3, ["Seite 1 von 3"])


def test_incremental_update_uses_the_newest_definition(tmp_path: Path) -> None:
    damaged = samples.incremental_update(tmp_path / "update.pdf")
    scan = scanner.scan(damaged)
    assert scan.stats.superseded == 1
    data = damaged.read_bytes()
    assert scan.objects[5].start == data.rfind(b"5 0 obj")
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED
    content = texts(result.output_path)
    assert "NEU 1 von 2" in content[0] and "ALT" not in content[0]
    assert any("neueste Fassung" in action for action in result.repair_actions)


def test_object_streams_are_unpacked(tmp_path: Path) -> None:
    damaged = samples.object_streams_damaged(tmp_path / "objstm.pdf")
    scan = scanner.scan(damaged)
    assert scan.stats.object_streams >= 1 and scan.stats.catalog and scan.stats.pages == 3
    assert engine.analyze(damaged).condition is Condition.RAW_RECOVERABLE
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.method is Method.RAW_REBUILD
    assert result.pages_after == 3
    assert all("Testdokument" in text for text in texts(result.output_path))
    assert any("Objektströme entpackt" in action for action in result.repair_actions)


# --- 98 und 110: keine falschen Erfolge ---------------------------------------------------------------------------------


def test_truly_unrepairable_file_gets_no_success(tmp_path: Path) -> None:
    garbage = samples.garbage(tmp_path / "zufall.pdf", size=200_000)
    analysis = engine.analyze(garbage)
    assert analysis.condition is Condition.UNREADABLE and not analysis.repairable
    assert analysis.raw is not None and analysis.raw.objects == 0
    result, _stages = repair(garbage, tmp_path)
    assert result.status is RepairStatus.FAILED and result.output_path is None
    assert list((tmp_path / "arbeit").iterdir()) == []


def test_encrypted_file_without_encryption_data_is_not_forced(tmp_path: Path) -> None:
    damaged = samples.encrypted_damaged(tmp_path / "geschuetzt.pdf")
    analysis = engine.analyze(damaged)
    assert analysis.raw is not None and analysis.raw.encrypted
    assert analysis.condition is Condition.UNREADABLE and "verschlüsselt" in analysis.error
    result, _stages = repair(damaged, tmp_path, password="geheim")
    assert result.status is RepairStatus.FAILED and result.output_path is None
    assert any("verschlüsselt" in line for line in result.technical)


def test_raw_stage_skips_encrypted_objects(tmp_path: Path) -> None:
    damaged = samples.encrypted_damaged(tmp_path / "geschuetzt.pdf")
    scan = scanner.scan(damaged)
    assert scan.stats.encrypted and rebuild.write_classic(scan, damaged, tmp_path / "x.pdf") is None
    assert not (tmp_path / "x.pdf").exists()


def test_signature_hint_survives_without_readable_forms(tmp_path: Path) -> None:
    source = samples.signed(tmp_path / "signiert.pdf").read_bytes()
    broken = source[: source.find(b"\nxref")] + b"\nxref\ngarbage\n"
    broken = broken.replace(b"/Type /Pages", b"/Type /Pages /Kids [ 99 0 R ]", 1) if b"/Kids" not in broken[: broken.find(b"/Type /Pages")] else broken
    damaged = tmp_path / "signiert-kaputt.pdf"
    damaged.write_bytes(broken)
    assert scanner.scan(damaged).stats.signatures >= 1


# --- 111 und Pipeline ------------------------------------------------------------------------------------------------------


def test_candidates_are_ranked_by_complete_pages(tmp_path: Path) -> None:
    faster = engine._Candidate(Method.PDFIUM, tmp_path / "a.pdf", 1)
    better = engine._Candidate(Method.PAGE_TREE_REBUILD, tmp_path / "b.pdf", 3)
    raster = engine._Candidate(Method.RASTER, tmp_path / "c.pdf", 3)
    partial = engine._Candidate(Method.REWRITE, tmp_path / "d.pdf", 3, incomplete=[1])
    assert max([faster, better, raster, partial], key=lambda c: c.score()) is better
    assert max([engine._Candidate(Method.REWRITE, tmp_path / "e.pdf", 3), better], key=lambda c: c.score()).method is Method.REWRITE


def test_pdfium_single_page_is_not_reported_as_success(tmp_path: Path) -> None:
    """PDFium öffnet den defekten Baum als eine leere Seite – die Rohrekonstruktion findet alle drei."""
    data = samples.classic_bytes(samples.classic_objects(3)).replace(b"/Kids [4 0 R 6 0 R 8 0 R] /Count 3", b"/Kids [ 99 0 R ] /Count 1")
    damaged = tmp_path / "pdfium-eine-seite.pdf"
    damaged.write_bytes(data)
    analysis = engine.analyze(damaged)
    assert analysis.pages_expected == 3
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.pages_after == 3 and result.method is Method.PAGE_TREE_REBUILD


def test_lenient_engine_transfers_readable_pages(tmp_path: Path) -> None:
    source = samples.healthy(tmp_path / "gesund.pdf", pages=3)
    technical: list[str] = []
    found = lenient.recover(source, tmp_path / "pypdf.pdf", None, technical)
    assert found is not None and found.pages == found.total == 3 and found.whole_document
    assert lenient.recover(samples.garbage(tmp_path / "muell.pdf"), tmp_path / "nichts.pdf", None, technical) is None
    assert any(line.startswith("pypdf:") for line in technical)
    assert STAGES["lenient"] == "Alternative PDF-Struktur wird geprüft …" and STAGES["raw_scan"] == "PDF-Objekte werden gesucht …"


def test_large_damaged_file_is_scanned_quickly(tmp_path: Path) -> None:
    source = samples.large(tmp_path / "gross.pdf", pages=120).read_bytes()
    start = source.find(b"/Type /Pages")
    damaged = tmp_path / "gross-kaputt.pdf"
    damaged.write_bytes(source[: source.rfind(b"\nxref")] + b"\n")
    begin = time.perf_counter()
    scan = scanner.scan(damaged)
    assert time.perf_counter() - begin < 5
    assert scan.stats.pages == 120 and scan.stats.rejected == 0 and start > 0
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.pages_after == 120


def test_repair_without_changes_leaves_original_untouched(tmp_path: Path) -> None:
    damaged = samples.real_case(tmp_path / "Original.pdf")
    before = damaged.read_bytes()
    repair(damaged, tmp_path)
    assert damaged.read_bytes() == before


# --- Nachbau einer realen, abgeschnittenen Datei ----------------------------------------------------------------------


def test_truncated_file_without_catalog_tree_and_fonts(tmp_path: Path) -> None:
    """Katalog, Seitenbaum-Knoten und alle Schriften fehlen (Datei nach den Seiten abgeschnitten)."""
    damaged = samples.truncated_generator(tmp_path / "abgeschnitten.pdf")
    analysis = engine.analyze(damaged)
    assert analysis.condition is Condition.RAW_RECOVERABLE and analysis.pages_expected == 3
    checks = {check.key: check for check in analysis.checks}
    assert checks["raw_catalog"].ok is False and checks["raw_nodes"].detail == "0" and checks["raw_eof"].ok is False
    result, _stages = repair(damaged, tmp_path)
    # Alle Seiten sind da, die Schriften aber ersetzt: ehrlich »teilweise«, nie »repariert«
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.method is Method.PAGE_TREE_REBUILD
    assert result.pages_before == result.pages_after == 3
    assert result.warnings[0].startswith("Alle 3 Seiten wurden übernommen.") and "Standardschrift" in result.warnings[0]
    assert any("Dokumentkatalog neu angelegt" in action for action in result.repair_actions)
    assert any("fehlende Schriften durch die Standardschrift Helvetica ersetzt" in action for action in result.repair_actions)
    with pikepdf.open(result.output_path, attempt_recovery=False) as pdf:
        assert pdf.get_warnings() == [] and len(pdf.pages) == 3
        assert all(str(font.BaseFont) == "/Helvetica" for page in pdf.pages for font in page.obj.Resources.Font.values())
        assert all("/img1" in page.obj.Resources.XObject for page in pdf.pages)  # Bilder bleiben erhalten
    content = texts(result.output_path)
    assert all(f"Vertrag Seite {n} von 3" in content[n - 1] for n in (1, 2, 3))
    assert "Kündigung" in content[0] and "außerordentlich" in content[0]  # Umlaute bleiben lesbar
    assert_usable(result.output_path, 3)


def test_two_byte_text_is_never_given_a_guessed_font(tmp_path: Path) -> None:
    objs = samples.classic_objects(1)
    text = b"BT /F9 12 Tf 72 700 Td <00480065006C006C006F> Tj ET"
    objs[5] = b"<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream"
    objs[4] = objs[4].replace(b"/Font << /F1 3 0 R >>", b"/Font << /F9 50 0 R >>")
    objs[2] = b"<< /Type /Pages /Kids [ 99 0 R ] /Count 1 >>"
    damaged = tmp_path / "cid.pdf"
    damaged.write_bytes(samples._cut_structure(samples.classic_bytes(objs)))
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.incomplete_pages == [1]
    assert not any("Standardschrift" in action for action in result.repair_actions)


@pytest.mark.skipif(not __import__("os").environ.get("PDF_TOOL_REAL_SAMPLE"), reason="echte Beispieldatei nur lokal (PDF_TOOL_REAL_SAMPLE)")
def test_real_sample_from_the_field(tmp_path: Path) -> None:
    """Echte, abgeschnittene Datei aus der Praxis – wegen personenbezogener Daten nicht im Repository.
    Lokal: PDF_TOOL_REAL_SAMPLE=/pfad/zur/datei.pdf pytest tests/test_pdf_recovery.py -k real_sample"""
    source = Path(__import__("os").environ["PDF_TOOL_REAL_SAMPLE"])
    damaged = tmp_path / "praxis.pdf"
    damaged.write_bytes(source.read_bytes())
    analysis = engine.analyze(damaged)
    assert analysis.condition is Condition.RAW_RECOVERABLE
    result, _stages = repair(damaged, tmp_path)
    assert result.usable and result.pages_after == analysis.pages_expected
    assert result.status in (RepairStatus.REPAIRED, RepairStatus.PARTIALLY_RECOVERED)
    assert all(len(text) > 100 for text in texts(result.output_path))


def test_tolerant_engine_wins_when_it_keeps_more_than_pdfium(tmp_path: Path, monkeypatch) -> None:
    """Scheitert qpdf, übernimmt pypdf das ganze Dokument – mit Lesezeichen, anders als PDFium."""
    for stage in ("_stage_rewrite", "_stage_pages"):
        monkeypatch.setattr(engine, stage, lambda *args: None)
    result, _stages = repair(samples.healthy(tmp_path / "gesund.pdf"), tmp_path)
    assert result.method is Method.LENIENT and result.status is RepairStatus.REPAIRED
    assert result.pages_after == 5 and not any("Lesezeichen" in w for w in result.warnings)
    with pikepdf.open(result.output_path) as pdf:
        assert "/Outlines" in pdf.Root
