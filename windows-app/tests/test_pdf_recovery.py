"""Erweiterte PDF-Wiederherstellung: pypdf als dritte Engine, Rohanalyse, Neuaufbau von
Querverweisen, Trailer, startxref, %%EOF und Seitenbaum; fremde Daten vor bzw. nach der PDF
und die Rettung beschädigter Datenströme.

Alle Test-PDFs entstehen programmatisch (``pdfsamples.py``). Geprüft wird nie nur das
Öffnen: Seitenzahl, Text, Seitengröße und Darstellbarkeit der Ausgabe.
"""

from __future__ import annotations

import base64
import hashlib
import time
import zlib
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
import pytest

import pdfsamples as samples
from tools.pdf_repair import engine
from tools.pdf_repair.models import STAGES, Condition, Method, RepairMode, RepairStatus
from tools.pdf_repair.recovery import lenient, rebuild, scanner, streams

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


# --- Fremde Daten vor bzw. nach der PDF -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prefix",
    [samples.MAIL_HEADER, samples.HTTP_HEADER, samples.HTML_PAGE, samples.BOM_AND_GARBAGE],
    ids=["E-Mail-Kopf", "HTTP-Kopf", "HTML", "BOM-und-Muell"],
)
def test_data_before_the_pdf_header_is_removed(tmp_path: Path, prefix: bytes) -> None:
    """»%PDF-« erst hinter Byte 1024: Die PDF-Daten allein durchlaufen die Stufen; Analyse,
    Bericht und Ergebnis nennen die entfernten Daten."""
    assert len(prefix) > engine.HEAD_BYTES
    damaged = samples.with_prefix(tmp_path / "Anhang.pdf", prefix, samples.healthy(tmp_path / "quelle.pdf", pages=3))
    analysis = engine.analyze(damaged)
    assert analysis.condition is Condition.REPAIRABLE and analysis.repairable and analysis.looks_like_pdf
    assert analysis.data_before == len(prefix) and analysis.data_after == 0
    assert analysis.structural_errors == [engine.FINDINGS["header"]]  # die PDF selbst ist heil – kein Folgebefund
    checks = {check.key: check for check in analysis.checks}
    assert checks["header"].ok is False and checks["header"].detail.startswith("PDF 1.3 – erst nach")
    assert checks["xref"].ok and checks["trailer"].ok and checks["eof"].ok
    assert analysis.pdfium_pages == 3 and analysis.rasterizable_pages == 3  # auch PDFium liest die PDF-Daten
    result, stages = repair(damaged, tmp_path)
    assert "trim" in stages
    assert result.status is RepairStatus.REPAIRED and result.method is Method.REWRITE
    assert result.data_removed == len(prefix) and result.pages_before == result.pages_after == 3
    assert any(action.startswith("Daten vor dem PDF-Anfang entfernt") for action in result.repair_actions)
    assert len(result.warnings) == 1 and result.warnings[0].startswith("Vor dem PDF-Anfang standen")
    assert Path(result.output_path).read_bytes().startswith(b"%PDF-")
    assert_usable(result.output_path, 3, ["Seite 1", "Seite 2", "Seite 3"])


def test_data_before_a_damaged_pdf_no_longer_hides_it(tmp_path: Path) -> None:
    """Vorspann und zerstörte Struktur zugleich: bisher »keine lesbare PDF«, jetzt erweiterte Wiederherstellung."""
    damaged = samples.with_prefix(tmp_path / "Download.pdf", samples.HTTP_HEADER, samples.real_case(tmp_path / "_struktur.pdf"))
    analysis = engine.analyze(damaged)
    assert analysis.condition is Condition.RAW_RECOVERABLE and analysis.error is None and analysis.pages_expected == 3
    assert analysis.structural_errors[0] == engine.FINDINGS["header"]
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.method is Method.PAGE_TREE_REBUILD
    assert result.data_removed == len(samples.HTTP_HEADER)
    assert result.repair_actions[1].startswith("Daten vor dem PDF-Anfang entfernt")
    assert_usable(result.output_path, 3, ["Seite 1 von 3", "Seite 2 von 3", "Seite 3 von 3"])
    # Die Kopie der Eingabe ist wieder entfernt, nur die Ausgabe bleibt
    assert samples.files_in(tmp_path / "arbeit") == [engine.CLEAN_DIR]
    assert samples.files_in(tmp_path / "arbeit" / engine.CLEAN_DIR) == [Path(result.output_path).name]


def test_header_search_has_limits(tmp_path: Path, monkeypatch) -> None:
    """Kein Vorspann: eine kleine Markierung (bis 1 KB – das lesen alle Engines) und eine Kennung, vor der
    schon PDF-Objekte stehen (zerstörte Kennung, eingebettete PDF). Gesucht wird nur bis HEADER_LIMIT."""
    source = samples.healthy(tmp_path / "quelle.pdf", pages=1)
    bom = samples.with_prefix(tmp_path / "bom.pdf", b"\xef\xbb\xbf", source)
    analysis = engine.analyze(bom)
    assert analysis.condition is Condition.HEALTHY and analysis.data_before == 0
    data = source.read_bytes()
    embedded = tmp_path / "eingebettet.pdf"
    embedded.write_bytes(b"%XXX-1.3" + data[8:] + b"y" * 2000 + b"%PDF-1.7\n")
    assert engine._scan(embedded, embedded.stat().st_size).before == 0
    monkeypatch.setattr(engine, "HEADER_LIMIT", 4096)
    near = samples.with_prefix(tmp_path / "nah.pdf", b"x" * 2000, source)
    assert engine._scan(near, near.stat().st_size).before == 2000
    far = samples.with_prefix(tmp_path / "weit.pdf", b"x" * 5000, source)
    assert engine._scan(far, far.stat().st_size).before == 0


def test_data_after_the_last_eof_is_removed(tmp_path: Path) -> None:
    """Mehr als 1 KB nach dem letzten %%EOF (z. B. ein angehängtes Download-Fenster): kein »abgeschnitten«,
    sondern fremde Daten – sie werden entfernt und genannt."""
    suffix = b"\r\n" + samples.HTML_PAGE * 4
    damaged = samples.with_suffix(tmp_path / "Download.pdf", suffix, samples.healthy(tmp_path / "quelle.pdf", pages=3))
    analysis = engine.analyze(damaged)
    assert analysis.condition is Condition.REPAIRABLE and analysis.data_after == len(suffix) and analysis.data_before == 0
    assert analysis.structural_errors == [engine.FINDINGS["tail"]]
    checks = {check.key: check for check in analysis.checks}
    assert checks["eof"].ok is False and checks["eof"].detail.startswith("%%EOF vorhanden, danach")
    result, stages = repair(damaged, tmp_path)
    assert "trim" in stages and result.status is RepairStatus.REPAIRED and result.data_removed == len(suffix)
    assert any(action.startswith("Daten nach dem Dateiende (%%EOF) entfernt") for action in result.repair_actions)
    assert result.warnings[0].startswith("Nach dem Dateiende (%%EOF) standen")
    output = Path(result.output_path).read_bytes()
    assert output.rstrip().endswith(b"%%EOF") and b"<html>" not in output
    assert_usable(result.output_path, 3, ["Seite 1", "Seite 2", "Seite 3"])


def test_trailing_pdf_data_is_never_cut(tmp_path: Path) -> None:
    """Folgt auf %%EOF noch PDF-Struktur (ein abgeschnittenes inkrementelles Update), ist das kein Nachspann:
    nichts wird abgeschnitten, das fehlende Dateiende bleibt ein Befund. Bis 1 KB nach %%EOF stören nicht."""
    data = samples.classic_bytes(samples.classic_objects(2))
    damaged = tmp_path / "update.pdf"
    damaged.write_bytes(data + b"5 0 obj\n<< /Length 9000 >>\nstream\n" + b"0 0 m 10 10 l S\n" * 300)
    analysis = engine.analyze(damaged)
    assert analysis.data_after == 0 and engine.FINDINGS["tail"] not in analysis.structural_errors
    assert engine.FINDINGS["eof"] in analysis.structural_errors
    small = samples.with_suffix(tmp_path / "klein.pdf", b"\n" + b"x" * 500, samples.healthy(tmp_path / "quelle.pdf", pages=1))
    analysis = engine.analyze(small)
    assert analysis.condition is Condition.HEALTHY and analysis.data_after == 0


def test_foreign_data_around_an_unreadable_file_leaves_nothing(tmp_path: Path) -> None:
    damaged = samples.with_prefix(tmp_path / "kaputt.pdf", samples.MAIL_HEADER, samples.garbage(tmp_path / "_zufall.pdf"))
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.FAILED and result.output_path is None and result.data_removed == 0
    assert samples.files_in(tmp_path / "arbeit") == []


# --- Beschädigte Datenströme ------------------------------------------------------------------------------------------


def operators(pdf_path: str, index: int) -> list[str]:
    with pikepdf.open(pdf_path, attempt_recovery=False) as pdf:
        assert pdf.get_warnings() == []
        found = [str(operator) for _operands, operator in pikepdf.parse_content_stream(pdf.pages[index])]
        assert pdf.get_warnings() == []  # vollständig lesbar
        return found


def test_truncated_flate_content_is_partially_rescued(tmp_path: Path) -> None:
    """Abgeschnittener Inhaltsstrom: Der lesbare Teil bis zum letzten vollständigen Befehl wird übernommen,
    die Seite ist teilweise darstellbar – das Ergebnis heißt ehrlich »teilweise wiederhergestellt«."""
    damaged = samples.flate_truncated(tmp_path / "strom.pdf")
    analysis = engine.analyze(damaged)
    assert analysis.condition is Condition.DAMAGED and analysis.incomplete_pages == [2]
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.PARTIALLY_RECOVERED  # nie »repariert«
    assert result.streams_rescued == 1 and result.incomplete_pages == [2] and result.pages_after == 3
    assert result.warnings[0] == "2 von 3 Seiten konnten vollständig rekonstruiert werden."
    assert "1 Datenstrom teilweise gerettet: Übernommen wurde nur der lesbare Teil, der beschädigte Rest fehlt." in result.warnings
    assert any(action.startswith("1 Inhaltsstrom teilweise gerettet") for action in result.repair_actions)
    found = operators(result.output_path, 1)
    assert found[-1] == "ET" and 0 < found.count("Tj") < 50  # offener Textblock geschlossen
    content = texts(result.output_path)
    assert "Zeile 1 von Seite 2" in content[1] and "Zeile 50 von Seite 2" not in content[1]
    assert "Seite 1 von 3" in content[0] and "Seite 3 von 3" in content[2]
    doc = pdfium.PdfDocument(result.output_path)
    try:
        assert doc[1].render(scale=0.3).to_pil().getextrema() != ((255, 255), (255, 255), (255, 255))
    finally:
        doc.close()


def test_rescued_stream_ends_at_the_last_complete_operator(tmp_path: Path) -> None:
    """ASCII85 + Flate (wie bei reportlab), abgeschnitten: qpdf übernähme den Strom stillschweigend gekürzt,
    mitten in einem Befehl. Gerettet wird bis zum letzten vollständigen Befehl, die Seite zählt als unvollständig."""
    damaged = samples.a85_truncated(tmp_path / "a85.pdf")
    with pikepdf.open(samples.healthy(tmp_path / "vorlage.pdf")) as pdf:
        original = [str(operator) for _operands, operator in pikepdf.parse_content_stream(pdf.pages[0])]
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.incomplete_pages == [1] and result.streams_rescued == 1
    found = operators(result.output_path, 0)
    assert 0 < len(found) < len(original) and found[:-1] == original[: len(found) - 1] and found[-1] == "ET"


def test_truncated_form_xobject_is_rescued(tmp_path: Path) -> None:
    result, _stages = repair(samples.form_truncated(tmp_path / "formular.pdf"), tmp_path)
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.incomplete_pages == [1] and result.streams_rescued == 1
    with pikepdf.open(result.output_path, attempt_recovery=False) as pdf:
        form = pdf.pages[0].obj.Resources.XObject.Fm1
        assert form.read_bytes().rstrip().endswith(b"Q") and pdf.get_warnings() == []  # Grafikzustand geschlossen
    content = texts(result.output_path)
    assert "Zeile 1 von Seite 1" in content[0] and "Zeile 50 von Seite 1" not in content[0]
    assert "Seite 2 von 2" in content[1]


@pytest.mark.parametrize("kind", ["rgb", "png"], ids=["ohne-Praediktor", "PNG-Praediktor"])
def test_truncated_image_keeps_readable_rows(tmp_path: Path, kind: str) -> None:
    """Bild sicher rettbar (Flate, RGB): lesbare Zeilen bleiben, fehlende werden weiß – nichts wird erfunden."""
    result, _stages = repair(samples.image_truncated(tmp_path / f"bild-{kind}.pdf", kind), tmp_path)
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.incomplete_pages == [1] and result.streams_rescued == 1
    assert any(action.startswith("1 Bild teilweise gerettet") for action in result.repair_actions)
    width, height = samples.IMAGE_SIZE
    row = width * 3
    pixels = samples.image_pixels()
    with pikepdf.open(result.output_path, attempt_recovery=False) as pdf:
        image = pikepdf.PdfImage(pdf.pages[0].obj.Resources.XObject.Im1).as_pil_image().convert("RGB")
        assert pdf.get_warnings() == []
    assert image.size == (width, height)
    data = image.tobytes()
    kept = next(index for index in range(height) if data[index * row : (index + 1) * row] != pixels[index * row : (index + 1) * row])
    assert 0 < kept < height
    assert data[kept * row :] == b"\xff" * ((height - kept) * row)


def test_unsafe_image_stays_unchanged_and_is_reported(tmp_path: Path) -> None:
    """Bild mit Farbpalette: fehlende Zeilen ließen sich nicht sicher »weiß« füllen – unverändert, gemeldet."""
    damaged = samples.image_truncated(tmp_path / "palette.pdf", "indexed")
    with pikepdf.open(damaged) as pdf:
        before = pdf.pages[0].obj.Resources.XObject.Im1.read_raw_bytes()
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.incomplete_pages == [1] and result.streams_rescued == 0
    assert "Ein beschädigtes Bild ließ sich nicht sicher retten und wurde unverändert übernommen." in result.warnings
    with pikepdf.open(result.output_path) as pdf:
        assert pdf.pages[0].obj.Resources.XObject.Im1.read_raw_bytes() == before


def test_stream_without_checksum_is_rewritten_completely(tmp_path: Path) -> None:
    """Fehlt einem Flate-Strom nur die Prüfsumme am Ende, ist nichts verloren: neu geschrieben, »repariert«.
    Ein leerer Datenstrom (leere Seite) gilt nie als beschädigt."""
    objs = samples.classic_objects(2)
    packed = zlib.compress(samples.content_lines(1))[:-4]
    objs[5] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(packed) + packed + b"\nendstream"
    objs[7] = b"<< /Length 0 /Filter /FlateDecode >>\nstream\n\nendstream"
    damaged = tmp_path / "pruefsumme.pdf"
    damaged.write_bytes(samples._cut_structure(samples.classic_bytes(objs)))  # dazu: xref, Trailer und %%EOF fehlen
    result, _stages = repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.incomplete_pages == [] and result.streams_rescued == 0
    assert any(action == "1 Datenstrom ohne gültiges Ende vollständig gelesen und neu geschrieben" for action in result.repair_actions)
    assert operators(result.output_path, 0).count("Tj") == 50
    assert "Zeile 50 von Seite 1" in texts(result.output_path)[0]


def test_corrupt_stream_without_readable_operator_stays_unchanged(tmp_path: Path) -> None:
    result, _stages = repair(samples.corrupt_stream(tmp_path / "strom.pdf"), tmp_path)
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.streams_rescued == 0
    assert "Einzelne Datenströme waren schon im Original nicht lesbar und wurden unverändert übernommen." in result.warnings


def test_rescue_after_selection_when_only_pdfium_succeeds(tmp_path: Path, monkeypatch) -> None:
    """PDFium übernimmt beschädigte Ströme unverändert – gerettet wird nach der Auswahl, dann erneut geprüft."""
    for stage in ("_stage_rewrite", "_stage_pages", "_stage_lenient", "_stage_raw"):
        monkeypatch.setattr(engine, stage, lambda *args: None)
    result, stages = repair(samples.flate_truncated(tmp_path / "strom.pdf"), tmp_path)
    assert result.method is Method.PDFIUM and "streams_rescue" in stages
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.streams_rescued == 1 and result.incomplete_pages == [2]
    assert operators(result.output_path, 1)[-1] == "ET"
    assert samples.files_in(tmp_path / "arbeit") == [Path(result.output_path).name]


def test_rescue_is_dropped_without_improvement(tmp_path: Path, monkeypatch) -> None:
    """Nichts verschlechtern: Prüft die gerettete Fassung nicht besser, bleibt die bisherige Ausgabe."""
    for stage in ("_stage_rewrite", "_stage_pages", "_stage_lenient", "_stage_raw"):
        monkeypatch.setattr(engine, stage, lambda *args: None)
    original = engine.validate

    def stricter(path: Path, password: str | None = None) -> engine.Validation:
        check = original(path, password)
        if path.name.endswith("-datenstroeme.pdf"):
            check.problems = check.problems + ["absichtlich schlechter"] * 10
        return check

    monkeypatch.setattr(engine, "validate", stricter)
    result, _stages = repair(samples.flate_truncated(tmp_path / "strom.pdf"), tmp_path)
    assert result.method is Method.PDFIUM and result.streams_rescued == 0
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.incomplete_pages == [2]
    assert any("Gerettete Datenströme verworfen" in line for line in result.technical)
    assert samples.files_in(tmp_path / "arbeit") == ["stufe3-pdfium.pdf"]


def test_encrypted_file_with_truncated_stream_stays_protected(tmp_path: Path) -> None:
    plain = samples.flate_truncated(tmp_path / "_offen.pdf")
    damaged = tmp_path / "geschuetzt.pdf"
    with pikepdf.open(plain) as pdf:
        pdf.save(damaged, encryption=pikepdf.Encryption(user="geheim", owner="geheim", R=6))
    result, _stages = repair(damaged, tmp_path, password="geheim")
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.streams_rescued == 1 and result.incomplete_pages == [2]
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(result.output_path)
    with pikepdf.open(result.output_path, password="geheim", attempt_recovery=False) as pdf:
        assert pdf.is_encrypted and pdf.get_warnings() == []
        assert str(pikepdf.parse_content_stream(pdf.pages[1])[-1].operator) == "ET"


# --- Bausteine der Rettung ----------------------------------------------------------------------------------------


def test_content_is_cut_at_the_last_complete_operator() -> None:
    cut = streams.cut_content(b"q 1 0 0 1 0 0 cm BT /F1 12 Tf (Hal(l)o \\) Welt) Tj ET BT /F1 9 Tf [(Ab) -20 (c")
    assert cut.data == b"q 1 0 0 1 0 0 cm BT /F1 12 Tf (Hal(l)o \\) Welt) Tj ET BT /F1 9 Tf\nET Q\n"
    assert cut.operators == 8 and cut.closed == ["ET", "Q"]
    complete = b"/P <</MCID 0>> BDC BT <48656C6C6F> Tj ET EMC BX /X 1 Vendor EX 0 g"
    assert streams.cut_content(complete).data == complete + b"\n"  # Wörterbücher, Hex-Text, BX … EX
    image = b"q BI /W 2 /H 1 /BPC 8 /CS /G ID \x00\xff EI Q"
    assert streams.cut_content(image).data == image + b"\n"
    assert streams.cut_content(b"q BI /W 2 /H 1 /BPC 8 /CS /G ID \x00").data == b"q\nQ\n"  # Inline-Bild abgeschnitten
    assert streams.cut_content(b"0 0 m 10 10 l S \x93\x01Zufall 1 2 Tx").data == b"0 0 m 10 10 l S\n"  # unbekannt: Schluss
    assert streams.cut_content(b"BT /F1 12 Tf 16.").data == b"BT /F1 12 Tf\nET\n"  # Operanden ohne Befehl fallen weg
    assert streams.cut_content(b"(nur Text ohne Ende") is None and streams.cut_content(b"") is None


def test_flate_is_read_as_far_as_possible() -> None:
    data = bytes(range(256)) * 64
    packed = zlib.compress(data)
    assert streams.inflate(packed, 1 << 20) == streams.Decoded(data, True)
    part = streams.inflate(packed[: len(packed) // 2], 1 << 20)
    assert not part.complete and 0 < len(part.data) < len(data) and data.startswith(part.data)
    assert streams.inflate(packed[:-4], 1 << 20) == streams.Decoded(data, True)  # nur die Prüfsumme fehlt
    assert not streams.inflate(packed[:-4] + bytes(4), 1 << 20).complete  # falsche Prüfsumme: beschädigt
    bomb = streams.inflate(zlib.compress(bytes(10 << 20)), 1 << 20)  # Schutz vor »Zip-Bomben«
    assert not bomb.complete and len(bomb.data) == 1 << 20
    assert streams.flate_ok(packed) and not streams.flate_ok(packed[:-4]) and not streams.flate_ok(packed[:100])
    assert streams.flate_complete(packed) and streams.flate_complete(packed[:-4])  # nur die Prüfsumme fehlt
    assert not streams.flate_complete(packed[:-4] + bytes(4)) and not streams.flate_complete(packed[:100])


def test_ascii_filters_are_read_tolerantly() -> None:
    assert streams.ascii_hex(b"48 65 6C 6c 6F>") == streams.Decoded(b"Hello", True)
    assert streams.ascii_hex(b"48656C6") == streams.Decoded(b"Hel", False)  # abgeschnitten: halbe Ziffer fällt weg
    text = b"Hallo Welt, 1234"
    encoded = base64.a85encode(text) + b"~>"
    assert streams.ascii85(encoded) == streams.Decoded(text, True)
    assert streams.ascii85(b"z!!!!!~>") == streams.Decoded(bytes(8), True)
    cut = streams.ascii85(encoded[:12])
    assert not cut.complete and cut.data == text[:8]
    assert STAGES["trim"] and STAGES["streams_rescue"]
