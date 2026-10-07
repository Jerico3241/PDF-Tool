"""Werkzeug »PDF reparieren«: Analyse, Reparaturstufen, Ausgabeprüfung und Prozess.

Alle Test-PDFs entstehen programmatisch (siehe ``pdfsamples.py``).
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pikepdf
import pytest

import pdfsamples as samples
from tools.pdf_repair import engine, process
from tools.pdf_repair.models import Condition, Method, RepairMode, RepairStatus

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_repair(path: Path, tmp_path: Path, password: str | None = None, mode: RepairMode = RepairMode.AUTO, sha: str | None = None):
    work = tmp_path / "arbeit"
    work.mkdir(exist_ok=True)
    before = digest(path)
    result = engine.repair(path, work, password, mode, sha)
    assert digest(path) == before, "Original wurde verändert"
    return result


def open_output(result, password: str | None = None) -> pikepdf.Pdf:
    assert result.output_path
    return pikepdf.open(result.output_path, password=password or "", attempt_recovery=False)


# --- Analyse -------------------------------------------------------------------------------


def test_healthy_pdf_has_no_findings(tmp_path: Path) -> None:
    pdf = samples.healthy(tmp_path / "Rechnung.pdf")
    analysis = engine.analyze(pdf)
    assert analysis.condition is Condition.HEALTHY
    assert analysis.structural_errors == [] and analysis.warnings == []
    assert analysis.page_count == 5 and analysis.pdfium_pages == 5 and analysis.readable_pages == 5
    assert analysis.pdf_version and analysis.looks_like_pdf and not analysis.encrypted
    assert analysis.outlines and analysis.metadata_ok
    assert all(check.ok is not False for check in analysis.checks)
    assert analysis.size == pdf.stat().st_size and analysis.sha256 == digest(pdf)
    assert "qpdf" in analysis.engine and "PDFium" in analysis.engine


@pytest.mark.parametrize("make", [samples.xref_offset, samples.xref_garbage], ids=["startxref-falsch", "xref-zerstoert"])
def test_damaged_xref_is_detected(tmp_path: Path, make) -> None:
    analysis = engine.analyze(make(tmp_path / "kaputt.pdf"))
    assert analysis.condition is Condition.REPAIRABLE and analysis.repairable
    assert engine.FINDINGS["xref"] in analysis.structural_errors
    assert {c.key: c.ok for c in analysis.checks}["xref"] is False
    assert analysis.page_count == 5


def test_missing_trailer_is_detected(tmp_path: Path) -> None:
    analysis = engine.analyze(samples.trailer_removed(tmp_path / "ohne-trailer.pdf"))
    assert analysis.condition is Condition.REPAIRABLE
    assert engine.FINDINGS["trailer"] in analysis.structural_errors


def test_truncated_file_names_pages_without_content(tmp_path: Path) -> None:
    analysis = engine.analyze(samples.truncated(tmp_path / "abgeschnitten.pdf"))
    assert analysis.condition is Condition.DAMAGED
    assert analysis.incomplete_pages == [2, 3, 4, 5] and analysis.readable_pages == 1
    assert {c.key: c.ok for c in analysis.checks}["eof"] is False


def test_corrupt_stream_marks_affected_page(tmp_path: Path) -> None:
    analysis = engine.analyze(samples.corrupt_stream(tmp_path / "strom.pdf"))
    assert analysis.condition is Condition.DAMAGED
    assert analysis.incomplete_pages == [1]


def test_garbage_is_unreadable(tmp_path: Path) -> None:
    analysis = engine.analyze(samples.garbage(tmp_path / "muell.pdf"))
    assert analysis.condition is Condition.UNREADABLE and not analysis.repairable
    assert analysis.error


def test_non_pdf_and_empty_file(tmp_path: Path) -> None:
    analysis = engine.analyze(samples.not_pdf(tmp_path / "text.pdf"))
    assert analysis.condition is Condition.UNREADABLE and not analysis.looks_like_pdf
    assert "keine lesbare PDF" in analysis.error
    empty = tmp_path / "leer.pdf"
    empty.write_bytes(b"")
    assert engine.analyze(empty).error == "Die Datei ist leer."
    assert "nicht gelesen" in engine.analyze(tmp_path / "fehlt.pdf").error


def test_encrypted_pdf_requires_password(tmp_path: Path) -> None:
    pdf = samples.encrypted(tmp_path / "geheim.pdf")
    locked = engine.analyze(pdf)
    assert locked.condition is Condition.ENCRYPTED and locked.password_required and not locked.password_rejected
    wrong = engine.analyze(pdf, "falsch")
    assert wrong.condition is Condition.ENCRYPTED and wrong.password_rejected
    opened = engine.analyze(pdf, "geheim")
    assert opened.condition is Condition.HEALTHY and opened.encrypted
    assert any("verschlüsselt" in w for w in opened.warnings)


def test_signatures_forms_and_attachments_are_reported(tmp_path: Path) -> None:
    signed = engine.analyze(samples.signed(tmp_path / "signiert.pdf"))
    assert signed.signatures == 1 and signed.forms
    assert "digitale Signaturen" in signed.warnings[0]
    form = engine.analyze(samples.with_form(tmp_path / "formular.pdf"))
    assert form.forms and form.form_fields == 2 and form.signatures == 0
    attached = engine.analyze(samples.with_attachment(tmp_path / "anhang.pdf"))
    assert attached.attachments == 1


# --- Reparatur ------------------------------------------------------------------------------


@pytest.mark.parametrize("make", [samples.xref_offset, samples.xref_garbage, samples.trailer_removed], ids=["startxref", "xref", "trailer"])
def test_structural_damage_is_repaired_completely(tmp_path: Path, make) -> None:
    damaged = make(tmp_path / "kaputt.pdf")
    result = run_repair(damaged, tmp_path)
    assert result.status is RepairStatus.REPAIRED and result.method is Method.REWRITE
    assert result.pages_before == result.pages_after == 5
    assert result.warnings == [] and result.error is None
    with open_output(result) as out:
        assert out.get_warnings() == []
        assert len(out.pages) == 5
        # Links und Lesezeichen bleiben erhalten, Seiten unverändert groß
        assert "/Outlines" in out.Root
        assert all(len(page.obj.get("/Annots", [])) == 1 for page in out.pages)
        assert [[round(float(v), 2) for v in page.mediabox] for page in out.pages] == [[0, 0, 595.28, 841.89]] * 5
    assert any("Querverweistabelle" in action for action in result.repair_actions)


def test_truncated_file_is_partially_recovered(tmp_path: Path) -> None:
    result = run_repair(samples.truncated(tmp_path / "abgeschnitten.pdf"), tmp_path)
    assert result.status is RepairStatus.PARTIALLY_RECOVERED
    assert result.pages_after == 5 and result.incomplete_pages == [3, 4, 5]
    assert result.warnings[0] == "2 von 5 Seiten konnten vollständig rekonstruiert werden."
    # qpdf verwirft den Inhalt von Seite 2 (»EOF after endobj«), die Rohrekonstruktion übernimmt ihn
    assert result.method is Method.RAW_REBUILD
    with open_output(result) as out:
        assert len(out.pages) == 5
        assert b"Seite 2" in out.pages[1].Contents.read_bytes()


def test_corrupt_stream_is_reported_as_partial(tmp_path: Path) -> None:
    result = run_repair(samples.corrupt_stream(tmp_path / "strom.pdf"), tmp_path)
    assert result.status is RepairStatus.PARTIALLY_RECOVERED
    assert result.incomplete_pages == [1]
    assert "4 von 5 Seiten" in result.warnings[0]


def test_unrepairable_file_fails_without_output(tmp_path: Path) -> None:
    result = run_repair(samples.garbage(tmp_path / "muell.pdf"), tmp_path)
    assert result.status is RepairStatus.FAILED and result.output_path is None and result.error
    assert samples.files_in(tmp_path / "arbeit") == []


def test_healthy_pdf_rebuild_keeps_content(tmp_path: Path) -> None:
    pdf = samples.healthy(tmp_path / "gesund.pdf", pages=3, image=True)
    result = run_repair(pdf, tmp_path, mode=RepairMode.REBUILD)
    assert result.status is RepairStatus.REPAIRED and result.pages_after == 3
    with open_output(result) as out, pikepdf.open(pdf) as original:
        assert out.docinfo.get("/Title") == original.docinfo.get("/Title")
        assert len(out.pages[0].get_images()) == len(original.pages[0].get_images()) == 1


def test_encrypted_repair_needs_password_and_stays_protected(tmp_path: Path) -> None:
    pdf = samples.encrypted(tmp_path / "geheim.pdf")
    assert run_repair(pdf, tmp_path).status is RepairStatus.ENCRYPTED
    assert run_repair(pdf, tmp_path, password="falsch").status is RepairStatus.ENCRYPTED
    result = run_repair(pdf, tmp_path, password="geheim", mode=RepairMode.REBUILD)
    assert result.status is RepairStatus.REPAIRED
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(result.output_path)
    with open_output(result, "geheim") as out:
        assert out.is_encrypted and len(out.pages) == 5


def test_forms_attachments_and_signature_warning_survive_rewrite(tmp_path: Path) -> None:
    form = run_repair(samples.with_form(tmp_path / "formular.pdf"), tmp_path, mode=RepairMode.REBUILD)
    with open_output(form) as out:
        assert len(out.Root.AcroForm.Fields) == 2
    attached = run_repair(samples.with_attachment(tmp_path / "anhang.pdf"), tmp_path, mode=RepairMode.REBUILD)
    with open_output(attached) as out:
        assert out.attachments["notiz.txt"].get_file().read_bytes() == b"Anhang-Inhalt"
    signed = run_repair(samples.signed(tmp_path / "signiert.pdf"), tmp_path, mode=RepairMode.REBUILD)
    assert any("Signaturen" in warning for warning in signed.warnings)


def test_page_salvage_keeps_forms_and_attachments(tmp_path: Path, monkeypatch) -> None:
    """Stufe 3: Scheitert das Neu-Schreiben, werden lesbare Seiten einzeln übertragen."""
    monkeypatch.setattr(engine, "_stage_rewrite", lambda *args: None)
    form = run_repair(samples.with_form(tmp_path / "formular.pdf"), tmp_path)
    assert form.method is Method.PAGES and form.status is RepairStatus.REPAIRED
    with open_output(form) as out:
        assert len(out.pages) == 2 and len(out.Root.AcroForm.Fields) == 2
    attached = run_repair(samples.with_attachment(tmp_path / "anhang.pdf"), tmp_path)
    with open_output(attached) as out:
        assert "notiz.txt" in out.attachments


def test_second_engine_transfers_pages(tmp_path: Path, monkeypatch) -> None:
    for stage in ("_stage_rewrite", "_stage_pages", "_stage_lenient", "_stage_raw"):
        monkeypatch.setattr(engine, stage, lambda *args: None)
    result = run_repair(samples.healthy(tmp_path / "gesund.pdf"), tmp_path)
    assert result.method is Method.PDFIUM and result.pages_after == 5
    # Lesezeichen gehen dabei verloren – das wird ehrlich gemeldet
    assert result.status is RepairStatus.REPAIRED and any("Lesezeichen" in w for w in result.warnings)


def test_unknown_page_count_in_source(tmp_path: Path, monkeypatch) -> None:
    """Liefert keine Engine eine Seitenzahl der Quelle, zählt die geprüfte Ausgabe."""
    original = engine._source_info

    def without_pages(*args):
        info = original(*args)
        info.pages = info.pdfium_pages = None
        return info

    monkeypatch.setattr(engine, "_source_info", without_pages)
    result = run_repair(samples.xref_offset(tmp_path / "kaputt.pdf"), tmp_path)
    assert result.method is Method.REWRITE and result.pages_after == 5
    assert result.status is RepairStatus.REPAIRED


def test_rescue_mode_rasterizes_only_on_request(tmp_path: Path) -> None:
    result = run_repair(samples.healthy(tmp_path / "gesund.pdf", pages=2), tmp_path, mode=RepairMode.RASTER)
    assert result.method is Method.RASTER and result.status is RepairStatus.PARTIALLY_RECOVERED
    assert any("Text- und Vektorinformationen" in w for w in result.warnings)
    with open_output(result) as out:
        assert len(out.pages) == 2 and len(out.pages[0].get_images()) == 1
        assert [round(float(v)) for v in out.pages[0].mediabox] == [0, 0, 595, 842]


def test_changed_input_is_rejected(tmp_path: Path) -> None:
    pdf = samples.healthy(tmp_path / "gesund.pdf")
    result = run_repair(pdf, tmp_path, sha="0" * 64)
    assert result.status is RepairStatus.FAILED and "verändert" in result.error


def test_input_changed_during_repair_leaves_no_output(tmp_path: Path, monkeypatch) -> None:
    pdf = samples.xref_offset(tmp_path / "kaputt.pdf")
    original = engine._stage_rewrite

    def rewrite_then_modify(*args):
        candidate = original(*args)
        with open(pdf, "ab") as handle:
            handle.write(b"% geaendert\n")
        return candidate

    monkeypatch.setattr(engine, "_stage_rewrite", rewrite_then_modify)
    work = tmp_path / "arbeit"
    work.mkdir()
    result = engine.repair(pdf, work)
    assert result.status is RepairStatus.FAILED and "während der Verarbeitung" in result.error
    assert samples.files_in(work) == []


def test_umlaut_paths(tmp_path: Path) -> None:
    folder = tmp_path / "Benutzer" / "Jérôme" / "Übersichten"
    pdf = samples.xref_offset(folder / "Rechnung März.pdf")
    analysis = engine.analyze(pdf)
    assert analysis.condition is Condition.REPAIRABLE
    result = run_repair(pdf, tmp_path)
    target = process.deliver(Path(result.output_path), pdf)
    assert target == folder / "Rechnung März_repariert.pdf" and target.is_file()


def test_technical_messages_contain_no_full_path(tmp_path: Path) -> None:
    folder = tmp_path / "vertraulich"
    analysis = engine.analyze(samples.truncated(folder / "abgeschnitten.pdf"))
    assert analysis.technical and not any(str(folder) in line for line in analysis.technical)


DAMAGE = [
    # (Schaden, Erzeuger, ehrliches Ergebnis, Seiten der Ausgabe)
    ("eof-fehlt", samples.only_eof_missing, RepairStatus.REPAIRED, 2),
    ("eof-beschaedigt", samples.eof_damaged, RepairStatus.REPAIRED, 2),
    ("startxref-falsch", samples.xref_offset, RepairStatus.REPAIRED, 5),
    ("xref-zerstoert", samples.xref_garbage, RepairStatus.REPAIRED, 5),
    ("xref-fehlt", samples.xref_missing, RepairStatus.REPAIRED, 2),
    ("trailer-fehlt", samples.trailer_removed, RepairStatus.REPAIRED, 5),
    ("seitenbaum-ins-leere", samples.real_case, RepairStatus.REPAIRED, 3),
    ("seitenbaum-eltern", samples.broken_parents, RepairStatus.REPAIRED, 3),
    ("datenstrom-abgeschnitten", samples.flate_truncated, RepairStatus.PARTIALLY_RECOVERED, 3),
    ("datei-abgeschnitten", samples.truncated, RepairStatus.PARTIALLY_RECOVERED, 5),
    ("muell-vor-header", lambda path: samples.with_prefix(path, samples.MAIL_HEADER), RepairStatus.REPAIRED, 3),
    ("muell-nach-eof", lambda path: samples.with_suffix(path, b"\n" + samples.HTML_PAGE * 3), RepairStatus.REPAIRED, 3),
]


@pytest.mark.parametrize("make,status,pages", [case[1:] for case in DAMAGE], ids=[case[0] for case in DAMAGE])
def test_every_damage_case_gets_an_honest_result(tmp_path: Path, make, status, pages) -> None:
    """Jeder Schadensfall: analysiert, repariert, geprüft – Original bitgleich, Ergebnis ehrlich gekennzeichnet."""
    damaged = make(tmp_path / "Beschädigt.pdf")
    before = digest(damaged)
    analysis = engine.analyze(damaged)
    assert digest(damaged) == before
    assert analysis.repairable and analysis.condition is not Condition.HEALTHY and analysis.structural_errors
    result = run_repair(damaged, tmp_path)  # prüft auch: Original unverändert
    assert result.status is status and result.pages_after == pages and result.error is None
    with open_output(result) as out:
        assert out.get_warnings() == [] and len(out.pages) == pages
    if status is RepairStatus.PARTIALLY_RECOVERED:
        assert result.incomplete_pages and result.warnings[0].endswith("Seiten konnten vollständig rekonstruiert werden.")
    else:
        assert result.incomplete_pages == [] and result.streams_rescued == 0
    target = process.deliver(Path(result.output_path), damaged)
    assert target.name == "Beschädigt_repariert.pdf" and digest(damaged) == before


def test_repaired_output_never_replaces_an_existing_file(tmp_path: Path) -> None:
    damaged = samples.flate_truncated(tmp_path / "Vertrag.pdf")
    existing = [tmp_path / "Vertrag_repariert.pdf", tmp_path / "vertrag_repariert (1).pdf"]
    for path in existing:
        path.write_bytes(b"%PDF-1.4 fremde Datei")
    hashes = {path: digest(path) for path in [damaged, *existing]}
    result = run_repair(damaged, tmp_path)
    assert result.status is RepairStatus.PARTIALLY_RECOVERED
    target = process.deliver(Path(result.output_path), damaged)
    assert target.name == "Vertrag_repariert (2).pdf" and digest(target) == digest(Path(result.output_path))
    assert {path: digest(path) for path in hashes} == hashes  # Original und vorhandene Dateien unverändert
    folder = tmp_path / "Ausgabe"
    folder.mkdir()
    (folder / "Vertrag_repariert.pdf").write_bytes(b"alt")
    assert process.deliver(Path(result.output_path), damaged, folder).name == "Vertrag_repariert (1).pdf"
    assert (folder / "Vertrag_repariert.pdf").read_bytes() == b"alt"


def test_engine_works_without_lxml(tmp_path: Path) -> None:
    """Die Laufzeit liefert lxml nicht mit – Analyse und Reparatur dürfen es nicht brauchen."""
    pdf = samples.xref_offset(tmp_path / "kaputt.pdf")
    work = tmp_path / "arbeit"
    work.mkdir()
    code = (
        "import sys; sys.modules['lxml'] = None; sys.path.insert(0, sys.argv[1]);"
        "from tools.pdf_repair import engine;"
        "a = engine.analyze(sys.argv[2]); r = engine.repair(sys.argv[2], sys.argv[3]);"
        "print(a.condition.value, r.status.value)"
    )
    out = subprocess.run([sys.executable, "-c", code, str(APP_DIR), str(pdf), str(work)], capture_output=True, text=True, timeout=120)
    assert out.stdout.split() == ["repairable", "repaired"], out.stderr


# --- Ausgabe und Prozess --------------------------------------------------------------------


def test_output_names_never_overwrite(tmp_path: Path) -> None:
    pdf = samples.healthy(tmp_path / "Vertrag.pdf")
    original = pdf.read_bytes()
    temp = tmp_path / "temp.pdf"
    temp.write_bytes(original)
    assert process.next_output(pdf).name == "Vertrag_repariert.pdf"
    first = process.deliver(temp, pdf)
    second = process.deliver(temp, pdf)
    assert (first.name, second.name) == ("Vertrag_repariert.pdf", "Vertrag_repariert (1).pdf")
    assert process.next_output(pdf).name == "Vertrag_repariert (2).pdf"
    other = process.deliver(temp, pdf, tmp_path / "Ausgabe")
    assert other == tmp_path / "Ausgabe" / "Vertrag_repariert.pdf"
    # Das Original heißt nie wie eine Ausgabe
    trap = tmp_path / "Falle_repariert.pdf"
    trap.write_bytes(b"original")
    assert process.deliver(temp, trap).name == "Falle_repariert_repariert.pdf" and trap.read_bytes() == b"original"
    # Ohne »_repariert« neben dem Original: nummeriert, das Original bleibt unverändert
    assert process.deliver(temp, pdf, base="Vertrag").name == "Vertrag (1).pdf" and pdf.read_bytes() == original
    # Groß-/Kleinschreibung zählt nicht (wie unter Windows); reservierte Namen anderer Dateien auch nicht
    (tmp_path / "vertrag_repariert (2).pdf").write_bytes(b"fremd")
    assert process.next_output(pdf).name == "Vertrag_repariert (3).pdf"
    reserviert = process.deliver(temp, pdf, base="Vertrag_repariert", start=3, avoid=["VERTRAG_REPARIERT (3).PDF"])
    assert reserviert.name == "Vertrag_repariert (4).pdf"
    assert (tmp_path / "vertrag_repariert (2).pdf").read_bytes() == b"fremd"


@pytest.fixture(autouse=True)
def fresh_workers():
    """Jeder Test beginnt ohne wartende Arbeitsprozesse (sie werden sonst über Tests hinweg wiederverwendet)."""
    process.stop_workers()
    yield
    process.stop_workers()


def test_job_runs_in_separate_process(tmp_path: Path) -> None:
    pdf = samples.xref_garbage(tmp_path / "kaputt.pdf")
    job = process.Job("analyze", {"path": str(pdf)})
    events = job.wait(120)
    stages = [event[1] for event in events if event[0] == "progress"]
    assert stages[0] == "hash" and "open" in stages and events[-1][0] == "result"
    analysis = events[-1][1]
    assert analysis.condition is Condition.REPAIRABLE
    job = process.Job("repair", {"path": str(pdf), "sha256": analysis.sha256})
    result = job.wait(120)[-1][1]
    assert result.status is RepairStatus.REPAIRED and Path(result.output_path).parent == job.work_dir
    job.cleanup()
    assert not Path(result.output_path).exists()


def test_job_cancel_removes_work_dir(tmp_path: Path) -> None:
    pdf = samples.large(tmp_path / "gross.pdf", pages=150)
    job = process.Job("repair", {"path": str(pdf), "mode": RepairMode.RASTER.value})
    time.sleep(0.5)
    work = job.work_dir
    assert work.is_dir()
    job.cancel()
    assert job.done and job.cancelled and not work.exists()
    assert job.events() == []


def test_result_does_not_wait_for_the_worker_to_exit(tmp_path: Path) -> None:
    import threading

    exited = threading.Event()

    class SlowExit:
        """Arbeitsprozess, der nach dem Ergebnis noch lange zum Beenden braucht (Windows, PDF-Bibliotheken)."""

        exitcode = 0

        def is_alive(self) -> bool:
            return not exited.is_set()

        def join(self, timeout: float | None = None) -> None:
            exited.wait(timeout)

    class Receiver:
        def __init__(self) -> None:
            self.items = [("progress", "write", None), ("result", "fertig")]

        def poll(self) -> bool:
            return bool(self.items)

        def recv(self):
            return self.items.pop(0)

        def close(self) -> None:
            pass

    job = process.Job.__new__(process.Job)
    job.kind, job.done, job.cancelled = "repair", False, False
    job._receiver, job._process, job._reaper = Receiver(), SlowExit(), None
    work = tmp_path / "arbeit"
    work.mkdir()
    (work / "ausgabe.pdf").write_bytes(b"%PDF-1.7\n")
    job.work_dir = work
    start = time.perf_counter()
    assert job.events()[-1] == ("result", "fertig") and job.done
    job.cleanup()
    assert time.perf_counter() - start < 0.2  # die Oberfläche wartet nicht auf das Prozessende
    assert work.exists()  # gelöscht wird erst, wenn der Prozess keine Dateien mehr offen haben kann
    exited.set()
    deadline = time.time() + 5
    while work.exists() and time.time() < deadline:
        time.sleep(0.02)
    assert not work.exists() and job.work_dir is None


def test_job_reports_crash(tmp_path: Path) -> None:
    job = process.Job("analyze", {"path": str(samples.healthy(tmp_path / "a.pdf"))})
    job._starter.join(30)  # der Prozess startet im Hilfsthread
    job._process.kill()
    events = job.wait(30)
    assert events[-1][0] == "crash"


@pytest.fixture
def slow_spawn(monkeypatch):
    """Prozessstart wie unter Windows auf einem ausgelasteten Rechner: eine halbe Sekunde."""
    import multiprocessing.context

    original = multiprocessing.context.SpawnProcess.start

    def start(self) -> None:
        time.sleep(0.5)
        original(self)

    monkeypatch.setattr(multiprocessing.context.SpawnProcess, "start", start)


def test_job_start_does_not_block_the_caller(tmp_path: Path, slow_spawn) -> None:
    pdf = samples.healthy(tmp_path / "a.pdf")
    start = time.perf_counter()
    job = process.Job("analyze", {"path": str(pdf)})
    assert time.perf_counter() - start < 0.3  # die Oberfläche wartet nicht auf den Prozessstart
    assert job.starting() and job.events() == [] and not job.done  # kein Absturz, solange er startet
    events = job.wait(120)
    assert events[-1][0] == "result" and events[-1][1].condition is Condition.HEALTHY


def test_job_cancel_while_starting(tmp_path: Path, slow_spawn) -> None:
    job = process.Job("repair", {"path": str(samples.large(tmp_path / "gross.pdf", pages=50)), "mode": RepairMode.RASTER.value})
    work = job.work_dir
    start = time.perf_counter()
    job.cancel()
    assert time.perf_counter() - start < 0.3 and job.done and job.cancelled and job.events() == []
    job._starter.join(30)
    deadline = time.time() + 10
    while (work.exists() or job._process.is_alive()) and time.time() < deadline:
        time.sleep(0.02)
    assert not job._process.is_alive() and not work.exists()  # gleich nach dem Start beendet, Arbeitsordner weg


def test_worker_is_reused_for_the_next_job(tmp_path: Path) -> None:
    """Ein Arbeitsprozess erledigt mehrere Aufträge – der Prozessstart mit den PDF-Bibliotheken fällt nur einmal an."""
    first = process.Job("analyze", {"path": str(samples.healthy(tmp_path / "a.pdf"))})
    assert first.wait(120)[-1][0] == "result"
    pid = first._process.pid
    second = process.Job("repair", {"path": str(samples.xref_garbage(samples.healthy(tmp_path / "b.pdf")))})
    events = second.wait(120)
    assert events[-1][0] == "result" and second._process.pid == pid
    assert Path(events[-1][1].output_path).is_file()
    second.cleanup()  # die Ausgabe hält der Prozess nicht mehr offen
    assert not Path(events[-1][1].output_path).exists()


def test_worker_is_not_reused_after_an_error_or_cancel(tmp_path: Path) -> None:
    failed = process.Job("unbekannt", {"path": str(tmp_path / "a.pdf")})  # Fehler im Arbeitsprozess
    assert failed.wait(120)[-1] == ("error", "Die Datei konnte nicht verarbeitet werden (ValueError: Unbekannte Aufgabe: unbekannt).")
    after_error = process.Job("analyze", {"path": str(samples.healthy(tmp_path / "a.pdf"))})
    assert after_error.wait(120)[-1][0] == "result" and after_error._process.pid != failed._process.pid
    cancelled = process.Job("repair", {"path": str(samples.large(tmp_path / "gross.pdf", pages=50)), "mode": RepairMode.RASTER.value})
    cancelled._starter.join(30)
    assert cancelled._process.pid == after_error._process.pid  # der wartende Prozess übernimmt
    cancelled.cancel()
    assert not cancelled._process.is_alive()
    after_cancel = process.Job("analyze", {"path": str(samples.healthy(tmp_path / "c.pdf"))})
    assert after_cancel.wait(120)[-1][0] == "result" and after_cancel._process.pid != cancelled._process.pid


def test_worker_is_replaced_after_many_jobs_or_when_it_ended(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(process, "WORKER_JOBS", 2)
    pdf = str(samples.healthy(tmp_path / "a.pdf"))
    pids = []
    for _ in range(3):
        job = process.Job("analyze", {"path": pdf})
        assert job.wait(120)[-1][0] == "result"
        pids.append(job._process.pid)
    assert pids[0] == pids[1] != pids[2]  # nach zwei Aufträgen ein frischer Prozess
    # Ein wartender Prozess, der inzwischen beendet ist, wird nicht vergeben – kein »Absturz« für die nächste Datei
    job._process.kill()
    job._process.join(10)
    job = process.Job("analyze", {"path": pdf})
    events = job.wait(120)
    assert events[-1][0] == "result" and job._process.pid != pids[2]


def test_prepare_worker_starts_one_in_the_background(tmp_path: Path) -> None:
    process.prepare_worker()
    deadline = time.time() + 60
    while not process._POOL._idle and time.time() < deadline:
        time.sleep(0.05)
    assert len(process._POOL._idle) == 1
    pid = process._POOL._idle[0].process.pid
    job = process.Job("analyze", {"path": str(samples.healthy(tmp_path / "a.pdf"))})
    assert job.wait(120)[-1][0] == "result" and job._process.pid == pid


def test_job_reports_a_failed_start(tmp_path: Path, monkeypatch) -> None:
    import multiprocessing.context

    def start(self) -> None:
        raise OSError("keine Ressourcen")

    monkeypatch.setattr(multiprocessing.context.SpawnProcess, "start", start)
    job = process.Job("repair", {"path": str(samples.healthy(tmp_path / "a.pdf"))})
    events = job.wait(30)
    assert events == [("error", "Der Vorgang konnte nicht gestartet werden (OSError).")] and job.done
    work = job.work_dir
    job.cleanup()
    assert work is not None and not work.exists()


class _Keep(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def repair_log():
    """Protokoll des Bereichs »repair« (``diagnostics.applog``) mitlesen."""
    logger = logging.getLogger("pdftool.repair")
    keep, level = _Keep(), logger.level
    logger.addHandler(keep)
    logger.setLevel(logging.DEBUG)
    yield keep.messages
    logger.removeHandler(keep)
    logger.setLevel(level)


def test_worker_log_lines_go_to_the_app_log_not_into_events(repair_log) -> None:
    class Exited:
        exitcode = 0

        def is_alive(self) -> bool:
            return False

        def join(self, timeout: float | None = None) -> None:
            pass

    class Receiver:
        def __init__(self) -> None:
            self.items = [("log", logging.INFO, "Priorität nicht gesenkt (PermissionError)"), ("progress", "open", None), ("result", "fertig")]

        def poll(self) -> bool:
            return bool(self.items)

        def recv(self):
            return self.items.pop(0)

        def close(self) -> None:
            pass

    job = process.Job.__new__(process.Job)
    job.kind, job.done, job.cancelled, job.work_dir = "analyze", False, False, None
    job._receiver, job._process, job._reaper = Receiver(), Exited(), None
    assert job.events() == [("progress", "open", None), ("result", "fertig")]
    assert repair_log == ["Arbeitsprozess (analyze): Priorität nicht gesenkt (PermissionError)"]


def test_worker_forwards_its_log_through_the_pipe(monkeypatch) -> None:
    class Pipe:
        def __init__(self) -> None:
            self.sent: list[tuple] = []

        def send(self, item) -> None:
            self.sent.append(item)

    class Broken:
        def send(self, item) -> None:
            raise BrokenPipeError(32, "Broken pipe")

    record = logging.LogRecord("pdftool.repair", logging.WARNING, __file__, 1, "Engine %s nicht verfügbar (%s)", ("qpdf", "ImportError"), None)
    pipe = Pipe()
    process._ToApp(pipe).handle(record)
    assert pipe.sent == [("log", logging.WARNING, "Engine qpdf nicht verfügbar (ImportError)")]
    monkeypatch.setattr(logging, "raiseExceptions", False)
    process._ToApp(Broken()).handle(record)  # App nicht mehr erreichbar: kein Absturz des Arbeitsprozesses


@pytest.mark.skipif(sys.platform == "win32", reason="unter Windows über die Prozess-Priorität (ctypes)")
def test_lower_priority_failure_is_logged(monkeypatch, repair_log) -> None:
    def refuse(_increment: int) -> int:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(process.os, "nice", refuse)
    process._lower_priority()  # kein Fehler nach außen
    assert repair_log == ["Arbeitsprozess: Priorität nicht gesenkt (PermissionError)"]


def test_worker_errors_are_readable_and_without_paths() -> None:
    source = "/home/nutzer/Jérôme/Übersichten/Rechnung März.pdf"
    text = process._error_text(FileNotFoundError(2, "Datei fehlt", source), {"path": source})
    assert "Rechnung März.pdf" in text and "/home/nutzer" not in text
    assert process._error_text(MemoryError(), {"path": source}) == process.MEMORY_TEXT


def test_worker_memory_limit_is_bounded() -> None:
    gb = 1024**3
    assert process.memory_limit(0) == process.MEMORY_MIN
    assert process.memory_limit(2 * gb) == process.MEMORY_MIN  # halber Speicher, mindestens 1,5 GB
    assert process.memory_limit(4 * gb) == 2 * gb
    assert process.memory_limit(12 * gb) == 6 * gb
    assert process.memory_limit(64 * gb) == process.MEMORY_MAX


def test_stale_work_dirs_are_removed() -> None:
    import os

    old = Path(tempfile.mkdtemp(prefix=process.TEMP_PREFIX))
    fresh = Path(tempfile.mkdtemp(prefix=process.TEMP_PREFIX))
    past = time.time() - process.STALE_SECONDS - 60
    os.utime(old, (past, past))
    try:
        assert process.cleanup_stale() >= 1
        assert not old.exists() and fresh.exists()
    finally:
        import shutil

        shutil.rmtree(fresh, ignore_errors=True)


def test_large_pdf(tmp_path: Path) -> None:
    pdf = samples.large(tmp_path / "gross.pdf", pages=300)
    started = time.monotonic()
    analysis = engine.analyze(pdf)
    assert analysis.condition is Condition.HEALTHY and analysis.page_count == 300
    result = run_repair(pdf, tmp_path, mode=RepairMode.REBUILD)
    assert result.status is RepairStatus.REPAIRED and result.pages_after == 300
    assert time.monotonic() - started < 120
