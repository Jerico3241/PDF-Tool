"""Qt-Oberfläche (5.0 Beta 7): Werkzeug »Umwandeln« – Dateien jeder Art umwandeln, zusammenfügen, teilen, drucken und
umbenennen.

Die Abläufe laufen über den Controller (``Convert``) wie ein Klick in QML; geprüft wird, dass die Seite ohne
QML-Meldungen lädt, die Dateien wirklich entstehen, nie etwas überschrieben wird und »Rückgängig« die alten Namen
wiederherstellt. Office-Dateien brauchen LibreOffice – ohne (CI-Qt-Tests) werden diese Fälle übersprungen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pikepdf
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

import editorsamples as samples
from conftest import neustart, pump, wait_until

from tools.pdf_editor import fonts, office


@pytest.fixture(autouse=True)
def substitute_fonts(monkeypatch):
    monkeypatch.setenv("PDFTOOL_FONT_DIRS", str(samples.vera_path().parent))
    fonts.find_system_font.cache_clear()
    yield
    fonts.find_system_font.cache_clear()


def controller(h):
    return h.runtime.convert.controller


def open_page(h):
    h.app.openTool("convert")
    pump(0.4)
    assert h.app.currentPage == "convert" and h.item("convertPage") is not None


def run(h, timeout: float = 120.0):
    c = controller(h)
    c.start()
    assert wait_until(lambda: not c.running, timeout), "Umwandeln wurde nicht fertig"
    pump(0.1)
    return c


def test_page_lists_mixed_files_and_targets(ui_app, tmp_path: Path) -> None:
    h = ui_app
    open_page(h)
    assert h.item("convertDropZone").isVisible()
    pdf = samples.standard_text(tmp_path / "Brief.pdf")
    Image.new("RGB", (40, 30), (200, 0, 0)).save(tmp_path / "Foto.webp")
    (tmp_path / "notiz.xyz").write_text("x", encoding="utf-8")
    h.app.drop([str(pdf), str(tmp_path / "Foto.webp"), str(tmp_path / "notiz.xyz"), str(pdf)])
    pump(0.3)
    c = controller(h)
    assert [row["name"] for row in c.files] == ["Brief.pdf", "Foto.webp"]
    assert [row["kind"] for row in c.files] == ["PDF", "Bild"]
    keys = [target["key"] for target in c.targets]
    assert keys[:2] == ["pdf", "docx"] and "pptx" in keys and "html" in keys and "avif" in keys and "csv" not in keys
    counts = {target["key"]: target["count"] for target in c.targets}
    assert counts["pdf"] == 1 and counts["png"] == 2 and counts["docx"] == 1
    assert h.item("convertFiles").isVisible() and not h.item("convertDropZone").isVisible()
    for mode in ("merge", "split", "print", "rename", "convert"):
        c.setMode(mode)
        pump(0.1)
    assert not h.messages()


def test_convert_images_and_pdf_pages_without_overwriting(ui_app, tmp_path: Path) -> None:
    h = ui_app
    open_page(h)
    c = controller(h)
    pdf = samples.standard_text(tmp_path / "Brief.pdf")
    Image.new("RGBA", (40, 30), (0, 0, 255, 120)).save(tmp_path / "Logo.png")
    (tmp_path / "Logo.jpg").write_bytes(b"schon da")  # wird nicht überschrieben
    c.add([str(pdf), str(tmp_path / "Logo.png")])
    c.setTarget("jpg")
    assert c.canStart and c.startText == "Alle umwandeln"
    run(h)
    assert c.resultTone == "success", c.resultText
    assert (tmp_path / "Logo.jpg").read_bytes() == b"schon da"
    with Image.open(tmp_path / "Logo (2).jpg") as image:
        assert image.format == "JPEG" and image.mode == "RGB" and image.size == (40, 30)
    pages = sorted(tmp_path.glob("Brief*.jpg"))
    assert pages and all(Image.open(path).format == "JPEG" for path in pages)
    assert [row["state"] for row in c.files] == ["done", "done"]
    # Ziel, in das sich nicht alle umwandeln lassen: die anderen werden mit Grund ausgelassen
    c.setTarget("docx")
    run(h)
    states = {row["name"]: (row["state"], row["message"]) for row in c.files}
    assert states["Brief.pdf"][0] == "done" and (tmp_path / "Brief.docx").is_file()
    assert states["Logo.png"] == ("skipped", "Bild lässt sich nicht in Word (.docx) umwandeln.")
    assert c.resultTone == "warning" and "1 ausgelassen" in c.resultText
    assert not h.messages()


def test_heic_and_avif_photos(tmp_path: Path) -> None:
    """HEIC (iPhone) lesen über pi-heif, AVIF und WEBP über Pillow – und als PDF-Seite."""
    from tools.convert import jobs

    assert jobs.register_image_formats()
    Image.new("RGB", (64, 48), (10, 120, 30)).save(tmp_path / "foto.avif")
    result = jobs.convert_file(tmp_path / "foto.avif", "png", tmp_path)
    assert [path.name for path in result.outputs] == ["foto.png"]
    result = jobs.convert_file(tmp_path / "foto.avif", "pdf", tmp_path)
    with pikepdf.open(result.outputs[0]) as pdf:
        assert len(pdf.pages) == 1
    heic = Path(__file__).parent / "fixtures" / "foto.heic"  # 64 × 48, mit pillow-heif erzeugt
    result = jobs.convert_file(heic, "jpg", tmp_path)
    with Image.open(result.outputs[0]) as image:
        assert image.format == "JPEG" and image.size == (64, 48)
    result = jobs.convert_file(heic, "pdf", tmp_path)
    with pikepdf.open(result.outputs[0]) as pdf:
        assert len(pdf.pages) == 1


def test_pdf_to_html_and_powerpoint(tmp_path: Path) -> None:
    from tools.convert import jobs

    pdf = samples.standard_text(tmp_path / "Bericht.pdf")
    html = jobs.convert_file(pdf, "html", tmp_path).outputs[0]
    text = html.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>") and '<section class="page" id="seite-1">' in text and "<title>Bericht</title>" in text
    if office.libreoffice() is None:
        pytest.skip("LibreOffice fehlt")
    pptx = jobs.convert_file(pdf, "pptx", tmp_path).outputs[0]
    import zipfile

    with zipfile.ZipFile(pptx) as package:
        assert any(name.startswith("ppt/slides/slide") for name in package.namelist())


def test_merge_mixed_files_with_bookmarks(ui_app, tmp_path: Path) -> None:
    h = ui_app
    open_page(h)
    c = controller(h)
    a = samples.standard_text(tmp_path / "Anschreiben.pdf")
    Image.new("RGB", (50, 70), (255, 255, 255)).save(tmp_path / "Beleg.png")
    (tmp_path / "kaputt.pdf").write_bytes(b"%PDF-1.4 kaputt")
    c.add([str(a), str(tmp_path / "Beleg.png"), str(tmp_path / "kaputt.pdf")])
    c.setMode("merge")
    c.move(c.files[1]["key"], -1)  # Bild nach oben
    assert [row["name"] for row in c.files][:2] == ["Beleg.png", "Anschreiben.pdf"]
    c.setMergeName("Unterlagen")
    run(h)
    target = tmp_path / "Unterlagen.pdf"
    assert c.resultPath == str(target) and target.is_file()
    with pikepdf.open(target) as pdf:
        with pdf.open_outline() as outline:
            assert [item.title for item in outline.root] == ["Beleg", "Anschreiben"]
    states = {row["name"]: row["state"] for row in c.files}
    assert states == {"Beleg.png": "done", "Anschreiben.pdf": "done", "kaputt.pdf": "skipped"}
    assert "1 ausgelassen" in c.resultText
    assert not h.messages()


def test_split_every_page_and_ranges(ui_app, tmp_path: Path) -> None:
    h = ui_app
    open_page(h)
    c = controller(h)
    pdf = samples.multi_page(tmp_path / "Akte.pdf", 5) if hasattr(samples, "multi_page") else None
    if pdf is None:
        with pikepdf.new() as new:
            for _ in range(5):
                new.add_blank_page()
            new.save(tmp_path / "Akte.pdf")
        pdf = tmp_path / "Akte.pdf"
    c.add([str(pdf)])
    c.setMode("split")
    c.setSplitMode("ranges")
    c.setSplitValue("1-2, 3-")
    run(h)
    assert sorted(path.name for path in tmp_path.glob("Akte - Teil *.pdf")) == ["Akte - Teil 1.pdf", "Akte - Teil 2.pdf"]
    with pikepdf.open(tmp_path / "Akte - Teil 2.pdf") as part:
        assert len(part.pages) == 3
    c.setSplitValue("1-9")
    assert "außerhalb" not in c.problem  # erst beim Teilen bekannt: die Seitenzahl der Datei
    c.setSplitMode("pages")
    run(h)
    assert len(list(tmp_path.glob("Akte - Seite *.pdf"))) == 5
    c.setSplitMode("every")
    c.setSplitValue("0")
    assert c.problem == "Bitte eine Seitenzahl ab 1 angeben." and not c.canStart
    assert not h.messages()


def test_rename_with_pattern_preview_and_undo(ui_app, tmp_path: Path) -> None:
    tmp_path = tmp_path / "scans"
    tmp_path.mkdir()
    h = ui_app
    open_page(h)
    c = controller(h)
    for name in ("b.pdf", "a.png", "c.txt"):
        (tmp_path / name).write_bytes(b"x")
    c.add([str(tmp_path / "b.pdf"), str(tmp_path / "a.png"), str(tmp_path / "c.txt")])
    c.setMode("rename")
    c.setPattern("Rechnung_{nr}")
    c.setStartNumber(9)
    assert [row["message"] for row in c.files] == ["→ Rechnung_09.pdf", "→ Rechnung_10.png", "→ Rechnung_11.txt"]
    c.setPattern("fest")  # ohne Platzhalter: alle gleich
    assert "braucht {nr}" in c.problem and not c.canStart
    c.setPattern("x/{nr}")
    assert "Nicht erlaubt" in c.problem
    c.setPattern("Rechnung_{nr}")
    (tmp_path / "Rechnung_10.png").write_bytes(b"belegt")  # erst nach der Prüfung belegt: beim Start erkannt
    c.start()
    assert c.resultTone == "critical" and c.resultText == "Nichts umbenannt – a.png: »Rechnung_10.png« gibt es in diesem Ordner schon."
    assert (tmp_path / "b.pdf").is_file()  # alles oder nichts
    c.setStartNumber(9)
    assert c.problem.startswith("a.png:") and not c.canStart
    (tmp_path / "Rechnung_10.png").unlink()
    c.setStartNumber(9)
    c.start()
    pump(0.1)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["Rechnung_09.pdf", "Rechnung_10.png", "Rechnung_11.txt"]
    assert c.canUndo and c.resultText == "3 Dateien umbenannt."
    c.undoRename()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["a.png", "b.pdf", "c.txt"]
    assert not c.canUndo and [row["name"] for row in c.files] == ["b.pdf", "a.png", "c.txt"]
    # Tausch von Namen über vorläufige Namen
    c.setPattern("{name}")
    assert c.problem == "Mit diesem Muster bleiben alle Namen gleich."
    assert not h.messages()


def test_print_all_files_as_separate_jobs(ui_app, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtPrintSupport import QPrinter

    from qtapp import convertprint

    out = tmp_path / "druck"
    out.mkdir()
    printers = []

    def printer():
        target = QPrinter(QPrinter.PrinterMode.HighResolution)
        target.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        target.setResolution(72)
        target.setOutputFileName(str(out / f"auftrag{len(printers)}.pdf"))
        printers.append(target)
        return target

    monkeypatch.setattr(convertprint, "TEST_PRINTER", printer)
    h = ui_app
    open_page(h)
    c = controller(h)
    pdf = samples.standard_text(tmp_path / "Brief.pdf")
    Image.new("RGB", (60, 40), (0, 0, 0)).save(tmp_path / "Bild.png")
    c.add([str(pdf), str(tmp_path / "Bild.png")])
    c.setMode("print")
    assert c.startText == "Alle drucken"
    run(h)
    assert c.resultText == "2 Dateien an den Drucker gesendet.", c.resultText
    assert [row["state"] for row in c.files] == ["done", "done"]
    assert (out / "auftrag0.pdf").is_file() and (out / "auftrag0.pdf").stat().st_size > 0
    assert not h.messages()


def test_settings_survive_restart(ui_app, config_file: Path) -> None:
    h = ui_app
    open_page(h)
    c = controller(h)
    c.setMode("split")
    c.setSplitMode("every")
    c.setSplitValue("3")
    c.setPattern("Scan_{datum}_{nr}")
    c.setMode("convert")
    c.setTarget("webp")
    h2 = neustart(h)
    c2 = controller(h2)
    assert (c2.mode, c2.target, c2.splitMode, c2.splitValue, c2.pattern) == ("convert", "webp", "every", "3", "Scan_{datum}_{nr}")


def test_office_targets_need_libreoffice(ui_app, tmp_path: Path, monkeypatch) -> None:
    h = ui_app
    open_page(h)
    c = controller(h)
    from openpyxl import Workbook

    book = Workbook()
    book.active["A1"] = "Hallo"
    book.save(tmp_path / "Liste.xlsx")
    monkeypatch.setattr(office, "TEST_INSTALLED", set())
    c.add([str(tmp_path / "Liste.xlsx")])
    c.setTarget("pdf")
    assert c.problem == "Für Office-Dateien fehlt LibreOffice. Bitte Novadesk neu installieren." and not c.canStart
    monkeypatch.setattr(office, "TEST_INSTALLED", None)
    c.setTarget("csv")
    if office.libreoffice() is None:
        return
    run(h)
    assert (tmp_path / "Liste.csv").read_text(encoding="utf-8").strip() == '"Hallo"'
    assert "nur das erste Blatt" in c.files[0]["message"]
