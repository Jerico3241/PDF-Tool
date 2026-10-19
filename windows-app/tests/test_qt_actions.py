"""Qt-Oberfläche (4.0): Werkzeug »Stapel-Aktionen«, »PDF aus Bildern« und »Als PDF/A speichern« im Reader.

Die Abläufe laufen über die Controller (``Actions``, ``Reader``); Dateiauswahl und Dialoge sind vorgegeben
(``files.RESPONSES``, ``dialogs.ask``). Geprüft wird, dass die Seite ohne QML-Meldungen lädt, Schritte und
Einstellungen nach einem Neustart bleiben, das Kennwort nie gespeichert wird und die Dateien wirklich
entstehen – ohne die Originale zu ändern.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pikepdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import editorsamples as samples
from conftest import neustart, pump, wait_until

from tools.pdf_editor import fonts, pdfa


@pytest.fixture(autouse=True)
def substitute_fonts(monkeypatch):
    monkeypatch.setenv("PDFTOOL_FONT_DIRS", str(samples.vera_path().parent))
    fonts.find_system_font.cache_clear()
    yield
    fonts.find_system_font.cache_clear()


def controller(h):
    return h.runtime.actions.controller


def test_page_loads_and_lists_dropped_pdfs(ui_app, tmp_path: Path) -> None:
    h = ui_app
    h.app.openShortcut(6)
    pump(0.4)
    assert h.app.currentPage == "actions" and h.item("actionsPage") is not None
    assert h.item("actionsDropZone").isVisible()
    a = samples.standard_text(tmp_path / "a.pdf")
    b = samples.standard_text(tmp_path / "b.pdf")
    (tmp_path / "notiz.txt").write_text("x", encoding="utf-8")
    h.app.drop([str(a), str(b), str(tmp_path / "notiz.txt"), str(a)])  # doppelt und keine PDF: nur einmal a, b
    pump(0.3)
    c = controller(h)
    assert c.count == 2 and [row["name"] for row in c.files] == ["a.pdf", "b.pdf"]
    assert h.item("actionsFiles").isVisible() and not h.item("actionsDropZone").isVisible()
    assert not c.canStart and c.problem == "Bitte mindestens eine Aktion wählen."
    assert not h.messages()


def test_steps_settings_survive_restart_without_password(ui_app, config_file: Path) -> None:
    h = ui_app
    c = controller(h)
    c.setStep("numbers", True)
    c.setStep("protect", True)
    c.setPassword("geheim123")
    c.setNumberFormat("zahl_von")
    c.setSuffix("_fertig")
    assert c.summary == "Seitenzahlen → Kennwortschutz"
    c.setStep("pdfa", True)  # schließt den Kennwortschutz aus
    assert [s["key"] for s in c.steps if s["checked"]] == ["numbers", "pdfa"]
    h.app.persist()
    assert "geheim123" not in config_file.read_text(encoding="utf-8")
    h = neustart(h)
    c = controller(h)
    assert [s["key"] for s in c.steps if s["checked"]] == ["numbers", "pdfa"]
    assert c.numberFormat == "zahl_von" and c.suffix == "_fertig" and not c.hasPassword
    stored = json.loads(config_file.read_text(encoding="utf-8"))["stapel_aktionen"]
    assert stored["schritte"] == ["numbers", "pdfa"]


def test_run_creates_new_files_and_keeps_originals(ui_app, tmp_path: Path) -> None:
    h = ui_app
    c = controller(h)
    sources = [samples.standard_text(tmp_path / f"brief{n}.pdf", pages=2) for n in (1, 2)]
    (tmp_path / "brief1_bearbeitet.pdf").write_bytes(b"vorhanden")  # wird nie überschrieben
    originals = [p.read_bytes() for p in sources]
    c.add([str(p) for p in sources])
    c.setStep("numbers", True)
    c.setStep("pdfa", True)
    c.setSuffix("_bearbeitet")
    assert c.canStart
    c.start()
    assert wait_until(lambda: not c.running, 60)
    assert c.resultTone == "success" and c.resultText.startswith("2 von 2 PDFs bearbeitet")
    assert [p.read_bytes() for p in sources] == originals
    assert (tmp_path / "brief1_bearbeitet.pdf").read_bytes() == b"vorhanden"
    first, second = tmp_path / "brief1_bearbeitet (2).pdf", tmp_path / "brief2_bearbeitet.pdf"
    for result in (first, second):
        assert pdfa.check(result.read_bytes()) == []
    assert [row["state"] for row in c.files] == ["done", "done"]
    assert c.files[0]["outputName"] == first.name


def test_protected_and_broken_files_do_not_stop_the_run(ui_app, tmp_path: Path) -> None:
    h = ui_app
    c = controller(h)
    locked = samples.encrypted(tmp_path / "geheim.pdf")
    broken = tmp_path / "kaputt.pdf"
    broken.write_bytes(b"%PDF-1.7\nkaputt")
    good = samples.standard_text(tmp_path / "gut.pdf")
    c.add([str(locked), str(broken), str(good)])
    c.setStep("watermark", True)
    c.start()
    assert wait_until(lambda: not c.running, 60)
    assert [row["state"] for row in c.files] == ["skipped", "error", "done"]
    assert c.resultTone == "warning" and "1 mit Fehler" in c.resultText and "1 ausgelassen" in c.resultText
    with pikepdf.open(tmp_path / "gut_bearbeitet.pdf") as pdf:
        assert len(pdf.pages) == 1


def test_output_folder_needs_an_existing_folder(ui_app, tmp_path: Path) -> None:
    from qtapp import files

    h = ui_app
    c = controller(h)
    c.add([str(samples.standard_text(tmp_path / "a.pdf"))])
    c.setStep("optimize", True)
    files.RESPONSES.append("")  # Ordnerauswahl abgebrochen
    c.setOutMode("folder")
    assert not c.canStart and "Ausgabeordner" in c.problem
    target = tmp_path / "ziel"
    target.mkdir()
    files.RESPONSES.append(str(target))
    c.pickOutDir()
    assert c.canStart
    c.start()
    assert wait_until(lambda: not c.running, 60)
    assert (target / "a_bearbeitet.pdf").is_file()


def test_images_to_pdf_from_the_home_quick_tool(ui_app, tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    from qtapp import files

    h = ui_app
    r = h.runtime.reader.controller
    for name, size in (("eins.jpg", (400, 300)), ("zwei.png", (200, 300))):
        Image.new("RGB", size, (10, 120, 200)).save(tmp_path / name)
    asked: list = []

    def ask(kind, title, message="", **options):
        asked.append((kind, options.get("data")))
        data = options.get("data") or {}
        return "primary", {"order": [f["path"] for f in reversed(data["files"])], "pageSize": "a4", "margin": "small"}

    monkeypatch.setattr(h.app.dialogs, "ask", ask)
    files.RESPONSES.extend([[str(tmp_path / "eins.jpg"), str(tmp_path / "zwei.png")], str(tmp_path / "bilder")])
    r.quickTool("images")
    assert wait_until(lambda: r.tabs.count == 1, 30)
    assert asked[0][0] == "images" and [f["name"] for f in asked[0][1]["files"]] == ["eins.jpg", "zwei.png"]
    with pikepdf.open(tmp_path / "bilder.pdf") as pdf:
        sizes = [tuple(round(float(v)) for v in page.mediabox[2:]) for page in pdf.pages]
    assert sizes == [(595, 842), (842, 595)]  # umgekehrte Reihenfolge, A4 hoch bzw. quer
    h.app.persist()
    assert h.runtime.reader.controller.config()["reader_bilder"]["seite"] == "a4"


def test_dropped_images_start_images_to_pdf(ui_app, tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    h = ui_app
    Image.new("RGB", (100, 100)).save(tmp_path / "scan.png")
    asked: list = []
    monkeypatch.setattr(h.app.dialogs, "ask", lambda kind, title, message="", **options: (asked.append(kind), ("close", None))[1])
    h.app.drop([str(tmp_path / "scan.png")])
    pump(0.3)
    assert asked == ["images"]


def test_reader_saves_a_pdfa_copy(ui_app, tmp_path: Path) -> None:
    from qtapp import files

    h = ui_app
    r = h.runtime.reader.controller
    source = samples.standard_text(tmp_path / "vertrag.pdf")
    r.open_paths([str(source)])
    assert wait_until(lambda: r.current is not None and r.current.pageCount == 1, 30)
    files.RESPONSES.append(str(tmp_path / "vertrag_PDFA.pdf"))
    r.current.pdfaDocument()
    assert wait_until(lambda: (tmp_path / "vertrag_PDFA.pdf").is_file(), 30)
    assert pdfa.check((tmp_path / "vertrag_PDFA.pdf").read_bytes()) == []
    assert wait_until(lambda: h.app.notices.get("reader").shown, 10)
    assert h.app.notices.get("reader").title == "PDF/A-Kopie gespeichert"
