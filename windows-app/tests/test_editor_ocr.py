"""PDF Editor – Texterkennung (OCR): Scanseiten erkennen, Seitenbild, Tesseract (Text-only-PDF, Abbruch,
Zeitlimit, fehlende Sprache), unsichtbare Textebene übernehmen – auch bei /Rotate und CropBox –, ersetzen,
entfernen, Rückgängig/Wiederholen, Speichern, Spracherkennung, Suche nach der Engine.

Die Scans sind künstlich (``editorsamples.scanned``: Text in Bitstream Vera als Bild, 300 dpi). Tests mit
Tesseract laufen nur, wenn ``ocr.find_engine()`` eine Engine mit Deutsch und Englisch findet. Die Textebene
selbst prüfen weitere Tests mit einer nachgebauten Text-only-PDF – sie laufen auch ohne Tesseract."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pikepdf
import pytest
from PIL import Image, ImageChops

import editorsamples as samples
from tools.pdf_editor import commands, ocr, pages, render, save, textlayer
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import ReadOnlyDocument

ENGINE = ocr.find_engine()
needs_engine = pytest.mark.skipif(ENGINE is None or not {"deu", "eng"} <= set(ENGINE.languages), reason="Tesseract mit Deutsch und Englisch nicht gefunden")
VARIANTS = {
    "aufrecht": {},
    "rotate-90": {"rotate": 90},
    "rotate-180": {"rotate": 180},
    "rotate-270": {"rotate": 270},
    "cropbox": {"crop": [40, 60, 555, 800]},
    "cropbox-rotate-90": {"rotate": 90, "crop": [50, 40, 800, 560]},
}


@pytest.fixture
def opened():
    """``opened(path)`` öffnet ein Dokument samt eigener Bearbeitungshistorie; geschlossen wird am Ende."""
    docs: list[EditorDocument] = []

    def open_(path: Path) -> tuple[EditorDocument, commands.History]:
        doc = EditorDocument.open(path)
        docs.append(doc)
        return doc, commands.History()

    yield open_
    for doc in docs:
        doc.close()


@pytest.fixture
def private_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Eigener Temp-Ordner – so ist sichtbar, ob die Texterkennung etwas liegen lässt."""
    folder = tmp_path / "temp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


# --- Hilfen ----------------------------------------------------------------------------------------------------
def picture(doc: EditorDocument, page: int):
    return render.to_pil(render.render_page(doc, page, 600)).convert("L")


def unchanged(before, after) -> bool:
    return before.size == after.size and ImageChops.difference(before, after).getbbox() is None


def view_rects(doc: EditorDocument, page: int, word: str = "Hottgenroth") -> list[tuple[float, ...]]:
    geo = doc.geometry(page)
    return [geo.rect_to_view(rect) for hit in textlayer.search(doc, page, word) for rect in hit.rects]


def near(rect, expected, tolerance: float = 4.0) -> bool:
    """Trefferrechteck (Anzeige) liegt auf dem Wort im Bild: Anfang, Ober- und Unterkante auf wenige Punkte
    genau; Tesseract streckt jedes Wort samt folgendem Leerzeichen, das Ende darf deshalb etwas früher liegen."""
    x0, y0, x1, y1 = rect
    e0, f0, e1, f1 = expected
    return abs(x0 - e0) <= tolerance and abs(y0 - f0) <= tolerance and abs(y1 - f1) <= tolerance and e0 + 0.75 * (e1 - e0) <= x1 <= e1 + tolerance


def recognized(doc: EditorDocument, page: int, languages=("deu", "eng")) -> ocr.RecognizedPage:
    png, dpi = ocr.render_page_image(doc, page)
    return ocr.recognize(ENGINE, page, png, list(languages), dpi)


WORD_AT = (samples.SCAN_LEFT, 100.0)  # Anzeige-Punkte: Anfang und Grundlinie des nachgebauten Worts


def synthetic(doc: EditorDocument, page: int, *, mode: int = 3) -> ocr.RecognizedPage:
    """Ergebnis wie von Tesseract, ohne Tesseract: »Hottgenroth« unsichtbar bei ``WORD_AT`` der Anzeige."""
    geo = doc.geometry(page)
    data = samples.text_only_pdf(geo.width, geo.height, [("Hottgenroth", WORD_AT[0], geo.height - WORD_AT[1], 12.0)], mode=mode)
    return ocr.RecognizedPage(page, data, 1, 90.0, "deu", 300)


def layer_calls(doc: EditorDocument, page: int) -> int:
    return sum(1 for ins in pikepdf.parse_content_stream(doc.pdf.pages[page].obj) if not isinstance(ins, pikepdf.ContentStreamInlineImage) and str(ins.operator) == "Do" and str(ins.operands[0]).startswith(ocr.LAYER_PREFIX))


def fake_pe(path: Path, imports: list[str]) -> Path:
    """Kleinste Windows-Programmdatei (PE32+, 64 Bit) mit einer Importtabelle – Aufbau wie in test_qt_resources."""
    import struct

    section_rva, section_raw = 0x1000, 0x400
    data = bytearray(0x800)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664, 1)  # Maschine, Abschnitte
    struct.pack_into("<H", data, 0x84 + 16, 240)  # Größe des optionalen Kopfs
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<II", data, optional + 112 + 8, section_rva, 20 * (len(imports) + 1))  # Importe
    header = optional + 240
    data[header : header + 8] = b".idata\0\0"
    struct.pack_into("<IIII", data, header + 8, 0x400, section_rva, 0x400, section_raw)
    names = 0x200  # Namen der DLLs ab +0x200 im Abschnitt
    for number, name in enumerate(imports):
        struct.pack_into("<IIIII", data, section_raw + 20 * number, 0, 0, 0, section_rva + names, 0)
        data[section_raw + names : section_raw + names + len(name)] = name.encode("ascii")
        names += len(name) + 1
    path.write_bytes(bytes(data))
    return path


# --- Ohne Tesseract ------------------------------------------------------------------------------------------
def test_detect_language_uses_frequent_words() -> None:
    assert ocr.detect_language("Vielen Dank für die gute Zusammenarbeit und den Auftrag.") == "deu"
    assert ocr.detect_language("Thank you for the order and for your trust in our team.") == "eng"
    assert ocr.detect_language("Merci pour votre commande, nous sommes à votre disposition avec plaisir.") == "fra"
    assert ocr.detect_language("Grazie per l'ordine: questo documento è stato preparato anche per gli uffici della sede.") == "ita"
    assert ocr.detect_language("Gracias por el pedido, los documentos están en la oficina y pero también muy pronto.") == "spa"
    assert ocr.detect_language("Bedankt voor de bestelling, het pakket wordt morgen door de koerier naar u gebracht.") == "nld"
    assert ocr.detect_language("") == "" and ocr.detect_language("Rechnung Nr. 4711") == ""  # zu wenig Anhaltspunkte
    assert ocr.detect_language("the and der und") == ""  # zwei Sprachen gleichauf


def test_language_labels() -> None:
    assert ocr.language_label("deu") == "Deutsch" and ocr.language_label("eng") == "Englisch"
    assert ocr.language_label("xyz") == "xyz"


def test_bundled_engine_lives_in_the_install_folder() -> None:
    import appstate

    assert ocr.BUNDLED_DIR == appstate.INSTALL_DIR / "ocr"


def test_without_engine_find_engine_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "leer"
    empty.mkdir()
    monkeypatch.setattr(ocr, "BUNDLED_DIR", tmp_path / "nicht-installiert")
    monkeypatch.delenv(ocr.ENGINE_VARIABLE, raising=False)
    monkeypatch.setenv("PATH", str(empty))
    assert ocr.find_engine() is None
    monkeypatch.setenv(ocr.ENGINE_VARIABLE, str(tmp_path / "gibt-es-nicht.exe"))
    assert ocr.find_engine() is None


def test_installed_languages_come_from_the_tessdata_folder(tmp_path: Path) -> None:
    for name in ("deu.traineddata", "eng.traineddata", "osd.traineddata", "pdf.ttf", "x y.traineddata"):
        (tmp_path / name).write_bytes(b"-")
    (tmp_path / "configs").mkdir()
    assert ocr.installed_languages(tmp_path) == ("deu", "eng")
    assert ocr.installed_languages(tmp_path / "fehlt") == ()


def test_scan_pages_tells_scans_from_text_pages(tmp_path: Path, opened) -> None:
    doc, _history = opened(samples.scanned(tmp_path / "gemischt.pdf", text_page=True))
    text, scan = ocr.scan_pages(doc)
    assert (text.page, scan.page) == (0, 1)
    assert text.chars >= ocr.TEXT_LIMIT and text.image_cover == 0 and not text.needs_ocr
    assert scan.chars == 0 and scan.image_cover >= 0.99 and scan.needs_ocr and not scan.ocr_layer
    assert ocr.scan_pages(doc, [1]) == [scan]


def test_scan_pages_counts_images_in_forms_and_ignores_small_logos(tmp_path: Path, opened) -> None:
    doc, _history = opened(samples.image_in_form(tmp_path / "form.pdf"))  # Bild in einem Formular, 180 × 120 pt
    (found,) = ocr.scan_pages(doc)
    assert 0 < found.image_cover < 0.1 and not found.needs_ocr


def test_render_page_image_is_the_visible_rotated_page(tmp_path: Path, opened) -> None:
    doc, _history = opened(samples.scanned(tmp_path / "quer.pdf", rotate=90))
    data, dpi = ocr.render_page_image(doc, 0)
    image = Image.open(io.BytesIO(data))
    assert dpi == 300 and image.mode == "L" and image.format == "PNG"
    assert abs(image.width - 595 * 300 / 72) <= 1 and abs(image.height - 842 * 300 / 72) <= 1  # aufrecht wie in der Anzeige
    x0, y0, x1, y1 = (round(value * 300 / 72) for value in samples.scan_word_box("Hottgenroth"))
    assert image.crop((x0, y0, x1, y1)).getextrema()[0] < 100  # das Wort steht dort, wo es die Anzeige zeigt


def test_huge_pages_are_rendered_with_fewer_dpi(tmp_path: Path, opened) -> None:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(3000, 3000))
    pdf.save(tmp_path / "plakat.pdf")
    doc, _history = opened(tmp_path / "plakat.pdf")
    data, dpi = ocr.render_page_image(doc, 0)
    width, height = Image.open(io.BytesIO(data)).size
    assert dpi < 100 and width * height <= ocr.MAX_PIXELS


@pytest.mark.parametrize("variant", list(VARIANTS), ids=list(VARIANTS))
def test_text_layer_lands_on_the_word_with_rotation_and_cropbox(tmp_path: Path, opened, variant: str) -> None:
    doc, history = opened(samples.scanned(tmp_path / f"{variant}.pdf", **VARIANTS[variant]))
    before = picture(doc, 0)
    assert ocr.apply_text_layers(doc, history, [synthetic(doc, 0)]) == 1
    (rect,) = view_rects(doc, 0)
    assert abs(rect[0] - WORD_AT[0]) <= 1.5 and rect[1] < WORD_AT[1] < rect[3] and 55 < rect[2] - rect[0] < 85, rect
    assert unchanged(before, picture(doc, 0))
    assert ocr.scan_pages(doc)[0].ocr_layer and not ocr.scan_pages(doc)[0].needs_ocr


def test_apply_is_one_undo_step_and_redo_restores(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.scanned(tmp_path / "zwei.pdf", text_page=True))
    page = doc.pdf.pages[1].obj
    contents, resources = page.Contents, page.Resources
    assert ocr.apply_text_layers(doc, history, [synthetic(doc, 1)]) == 1
    assert history.undo_title == "Text erkennen (OCR)" and len(view_rects(doc, 1)) == 1
    assert view_rects(doc, 0) == []  # nur die Scanseite
    history.undo(doc)
    assert view_rects(doc, 1) == [] and not ocr.has_text_layer(doc, 1) and not history.can_undo
    assert page.Contents.objgen == contents.objgen and list(page.Resources.XObject.keys()) == list(resources.XObject.keys()) == ["/Im1"]
    history.redo(doc)
    assert len(view_rects(doc, 1)) == 1 and ocr.has_text_layer(doc, 1)


def test_second_ocr_replaces_the_layer(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.scanned(tmp_path / "zweimal.pdf"))
    ocr.apply_text_layers(doc, history, [synthetic(doc, 0)])
    ocr.apply_text_layers(doc, history, [synthetic(doc, 0)])
    assert len(view_rects(doc, 0)) == 1 and layer_calls(doc, 0) == 1
    assert [name for name in doc.pdf.pages[0].Resources.XObject.keys() if name.startswith(ocr.LAYER_PREFIX)] == ["/PTOCR1"]
    history.undo(doc)  # zurück zur ersten Ebene, nicht zu keiner
    assert len(view_rects(doc, 0)) == 1


def test_layer_is_replaced_also_after_another_edit_merged_the_content(tmp_path: Path, opened) -> None:
    """Nach einer Bearbeitung kann der Aufruf der Ebene im selben Inhaltsstrom wie der Scan stehen."""
    doc, history = opened(samples.scanned(tmp_path / "zusammen.pdf"))
    ocr.apply_text_layers(doc, history, [synthetic(doc, 0)])
    page = doc.pdf.pages[0].obj
    with commands.record(doc, history, "Zusammenführen", pages=(0,)) as rec:
        rec.page(0)
        page.Contents = doc.pdf.make_stream(pikepdf.unparse_content_stream(list(pikepdf.parse_content_stream(page))))
    ocr.apply_text_layers(doc, history, [synthetic(doc, 0)])
    assert len(view_rects(doc, 0)) == 1 and layer_calls(doc, 0) == 1


def test_remove_text_layers_is_one_undo_step(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.scanned(tmp_path / "entfernen.pdf", rotate=90))
    before = picture(doc, 0)
    ocr.apply_text_layers(doc, history, [synthetic(doc, 0)])
    assert ocr.remove_text_layers(doc, history, [0]) == 1 and history.undo_title == "Erkannten Text entfernen"
    assert view_rects(doc, 0) == [] and layer_calls(doc, 0) == 0 and not ocr.has_text_layer(doc, 0)
    assert unchanged(before, picture(doc, 0))
    assert ocr.remove_text_layers(doc, history, [0]) == 0  # nichts mehr zu entfernen
    history.undo(doc)
    assert len(view_rects(doc, 0)) == 1


def test_layer_is_no_object_and_no_image_but_searchable(tmp_path: Path, opened) -> None:
    """Objekt bearbeiten blendet den unsichtbaren Text aus, das Bildwerkzeug sieht nur den Scan – die Suche
    findet den Text (gewollt)."""
    from tools.pdf_editor import images, objects

    doc, history = opened(samples.scanned(tmp_path / "objekte.pdf"))
    ocr.apply_text_layers(doc, history, [synthetic(doc, 0)])
    assert objects.analyze(doc, 0).segments == []
    (scan,) = images.list_images(doc, 0)
    assert scan.kind == "image" and scan.editable
    assert len(view_rects(doc, 0)) == 1


def test_scan_with_a_small_printed_header_gets_its_layer_too(tmp_path: Path, opened) -> None:
    """Scan mit wenig echtem Text (z. B. eine Seitenzahl des Scanprogramms): wird vorgeschlagen, die
    Textebene steht hinter dem vorhandenen Text, beides bleibt lesbar."""
    path = samples.scanned(tmp_path / "kopf.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        page = pdf.pages[0]
        page.Resources.Font = pikepdf.Dictionary(F1=samples._helvetica(pdf))
        page.Contents = pikepdf.Array([page.Contents, pdf.make_stream(b"BT /F1 9 Tf 500 20 Td (Seite 1) Tj ET\n")])
        pdf.save(path)
    doc, history = opened(path)
    (scan,) = ocr.scan_pages(doc)
    assert 0 < scan.chars < ocr.TEXT_LIMIT and scan.needs_ocr
    ocr.apply_text_layers(doc, history, [synthetic(doc, 0)])
    assert len(view_rects(doc, 0)) == 1 and textlayer.search(doc, 0, "Seite 1")


def test_release_check_finds_an_incomplete_ocr_bundle(tmp_path: Path) -> None:
    """``release_check.check_ocr``: tesseract.exe (64 Bit), jede geladene DLL vorhanden, keine überzählige,
    Sprachdaten, pdf.ttf und Lizenz – mit kleinen, selbst gebauten PE-Dateien."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("release_check_ocr", Path(__file__).resolve().parents[1] / "release_check.py")
    release_check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release_check)
    folder = tmp_path / "payload" / "ocr"
    (folder / "tessdata").mkdir(parents=True)
    fake_pe(folder / "tesseract.exe", ["libtesseract-5.dll", "KERNEL32.dll"])
    fake_pe(folder / "libtesseract-5.dll", ["zlib1.dll", "msvcrt.dll"])
    fake_pe(folder / "zlib1.dll", ["KERNEL32.dll"])
    for language in ("deu", "eng", "osd"):
        (folder / "tessdata" / f"{language}.traineddata").write_bytes(b"\0" * 600_000)
    (folder / "tessdata" / "pdf.ttf").write_bytes(b"\0" * 572)
    (folder / "LICENSE.txt").write_text("Apache License 2.0", encoding="utf-8")
    assert release_check.check_ocr(tmp_path / "payload") == []
    fake_pe(folder / "libunbenutzt.dll", [])
    (folder / "zlib1.dll").unlink()
    (folder / "tessdata" / "osd.traineddata").unlink()
    assert release_check.check_ocr(tmp_path / "payload") == [
        "Für die Texterkennung fehlen DLLs in ocr/: zlib1.dll",
        "Nicht benötigte DLLs in ocr/: libunbenutzt.dll",
        "Sprachdaten fehlen: ocr/tessdata/osd.traineddata",
    ]
    assert release_check.check_ocr(tmp_path / "leer") == ["Texterkennung fehlt im Paket: ocr/tesseract.exe"]


def test_layer_survives_save_and_reopen(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.scanned(tmp_path / "speichern.pdf", crop=[40, 60, 555, 800]))
    ocr.apply_text_layers(doc, history, [synthetic(doc, 0)])
    rects = view_rects(doc, 0)
    save.save(doc, tmp_path / "gespeichert.pdf")
    again, _history = opened(tmp_path / "gespeichert.pdf")
    reopened = view_rects(again, 0)
    assert len(reopened) == len(rects) == 1 and reopened[0] == pytest.approx(rects[0], abs=0.01) and ocr.has_text_layer(again, 0)


def test_visible_result_is_rolled_back(tmp_path: Path, opened) -> None:
    """Prüfung: Ein Ergebnis, das die Darstellung ändern würde (sichtbarer Text), wird nicht übernommen."""
    doc, history = opened(samples.scanned(tmp_path / "sichtbar.pdf"))
    page = doc.pdf.pages[0].obj
    contents = page.Contents.objgen
    with pytest.raises(ocr.OcrError, match="Darstellung"):
        ocr.apply_text_layers(doc, history, [synthetic(doc, 0, mode=0)])
    assert page.Contents.objgen == contents and not ocr.has_text_layer(doc, 0) and not history.can_undo
    assert view_rects(doc, 0) == []


def test_stale_result_and_empty_pages_are_not_applied(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.scanned(tmp_path / "veraltet.pdf"))
    old = synthetic(doc, 0)
    pages.rotate(doc, history, [0], 90)  # die Seite wurde inzwischen gedreht
    with pytest.raises(ocr.OcrError, match="verändert"):
        ocr.apply_text_layers(doc, history, [old])
    assert history.undo_title != "Text erkennen (OCR)"
    empty = ocr.RecognizedPage(0, b"", 0, 0.0, "", 300)
    assert ocr.apply_text_layers(doc, history, [empty]) == 0
    with pytest.raises(ocr.OcrError):
        ocr.apply_text_layers(doc, history, [ocr.RecognizedPage(5, b"", 1, 0.0, "", 300)])


def test_read_only_documents_are_not_changed(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.encrypted(tmp_path / "gesperrt.pdf", allow_edit=False), password="geheim")
    try:
        with pytest.raises(ReadOnlyDocument):
            ocr.apply_text_layers(doc, commands.History(), [synthetic(doc, 0)])
        with pytest.raises(ReadOnlyDocument):
            ocr.remove_text_layers(doc, commands.History(), [0])
    finally:
        doc.close()


# --- Mit Tesseract ---------------------------------------------------------------------------------------------
@needs_engine
def test_ocr_makes_the_scan_searchable_on_the_right_page(tmp_path: Path, opened, private_temp: Path) -> None:
    doc, history = opened(samples.scanned(tmp_path / "gemischt.pdf", text_page=True))
    scans = ocr.scan_pages(doc)
    targets = [scan.page for scan in scans if scan.needs_ocr]
    assert targets == [1]
    before = picture(doc, 1)
    result = recognized(doc, 1)
    assert result.page == 1 and result.dpi == 300 and result.words >= 15 and result.confidence > 70 and result.language == "deu"
    assert result.pdf.startswith(b"%PDF-") and list(private_temp.iterdir()) == []  # nichts liegen geblieben
    assert ocr.apply_text_layers(doc, history, [result]) == 1
    assert view_rects(doc, 0) == []
    (rect,) = view_rects(doc, 1)
    assert near(rect, samples.scan_word_box("Hottgenroth")), rect
    assert textlayer.search(doc, 1, "4711") and textlayer.search(doc, 1, "Straße") and textlayer.search(doc, 1, "Zusammenarbeit")
    assert unchanged(before, picture(doc, 1))
    assert ocr.scan_pages(doc, [1])[0].ocr_layer


@needs_engine
@pytest.mark.parametrize("variant", ["rotate-90", "cropbox", "cropbox-rotate-90"])
def test_ocr_on_rotated_and_cropped_pages_finds_the_word_where_it_is(tmp_path: Path, opened, variant: str) -> None:
    doc, history = opened(samples.scanned(tmp_path / f"{variant}.pdf", **VARIANTS[variant]))
    ocr.apply_text_layers(doc, history, [recognized(doc, 0)])
    (rect,) = view_rects(doc, 0)
    assert near(rect, samples.scan_word_box("Hottgenroth")), rect
    (straße,) = view_rects(doc, 0, "Straße")
    assert near(straße, samples.scan_word_box("Straße", 2)), straße
    assert view_rects(doc, 0, samples.SCAN_MARGIN_WORD) == []  # außerhalb der CropBox wird nichts erkannt


@needs_engine
def test_ocr_undo_redo_save_reopen_and_repeat(tmp_path: Path, opened) -> None:
    doc, history = opened(samples.scanned(tmp_path / "ablauf.pdf", rotate=90))
    first = recognized(doc, 0)
    ocr.apply_text_layers(doc, history, [first])
    assert len(view_rects(doc, 0)) == 1
    history.undo(doc)
    assert view_rects(doc, 0) == [] and not ocr.has_text_layer(doc, 0)
    history.redo(doc)
    assert len(view_rects(doc, 0)) == 1
    ocr.apply_text_layers(doc, history, [recognized(doc, 0)])  # zweite Erkennung ersetzt die Ebene
    assert len(view_rects(doc, 0)) == 1 and layer_calls(doc, 0) == 1
    save.save(doc, tmp_path / "erkannt.pdf")
    again, _history = opened(tmp_path / "erkannt.pdf")
    (rect,) = view_rects(again, 0)
    assert near(rect, samples.scan_word_box("Hottgenroth"))


@needs_engine
def test_cancel_stops_tesseract_and_leaves_no_temp_files(tmp_path: Path, opened, private_temp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc, _history = opened(samples.scanned(tmp_path / "abbruch.pdf"))
    png, dpi = ocr.render_page_image(doc, 0)
    cancel = threading.Event()
    processes: list[subprocess.Popen] = []
    start = subprocess.Popen

    def popen(*args, **kwargs):
        process = start(*args, **kwargs)
        processes.append(process)
        cancel.set()  # abbrechen, während Tesseract läuft
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    started = time.monotonic()
    with pytest.raises(ocr.OcrCancelled):
        ocr.recognize(ENGINE, 0, png, ["deu", "eng"], dpi, cancel=cancel, timeout=60)
    (process,) = processes
    assert process.returncode not in (None, 0)  # beendet, nicht zu Ende gelaufen
    assert time.monotonic() - started < 5 and list(private_temp.iterdir()) == []
    with pytest.raises(ocr.OcrCancelled):  # schon vor dem Start abgebrochen: Tesseract startet gar nicht
        ocr.recognize(ENGINE, 0, png, ["deu"], dpi, cancel=cancel)
    assert len(processes) == 1 and list(private_temp.iterdir()) == []


@needs_engine
def test_timeout_is_an_error_and_cleans_up(tmp_path: Path, opened, private_temp: Path) -> None:
    doc, _history = opened(samples.scanned(tmp_path / "zeit.pdf"))
    png, dpi = ocr.render_page_image(doc, 0)
    with pytest.raises(ocr.OcrError, match="zu lange"):
        ocr.recognize(ENGINE, 0, png, ["deu"], dpi, timeout=0.05)
    assert list(private_temp.iterdir()) == []


@needs_engine
def test_missing_or_broken_language_data_is_reported(tmp_path: Path, private_temp: Path) -> None:
    png = b"\x89PNG"  # wird nie gelesen: die Sprache fehlt vorher
    with pytest.raises(ocr.OcrError, match="fehlt die Sprache »xyz«"):
        ocr.recognize(ENGINE, 0, png, ["deu", "xyz"], 300)
    with pytest.raises(ocr.OcrError, match="mindestens eine Sprache"):
        ocr.recognize(ENGINE, 0, png, [], 300)
    broken = tmp_path / "tessdata"
    broken.mkdir()
    (broken / "abc.traineddata").write_bytes(b"keine Sprachdaten")
    if (ENGINE.tessdata / "pdf.ttf").is_file():
        shutil.copy2(ENGINE.tessdata / "pdf.ttf", broken / "pdf.ttf")
    engine = ocr.OcrEngine(ENGINE.executable, broken, ENGINE.version, ("abc",))
    image = Image.new("L", (200, 100), 255)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    with pytest.raises(ocr.OcrError, match="»abc« sind nicht lesbar"):
        ocr.recognize(engine, 0, buffer.getvalue(), ["abc"], 300)
    assert list(private_temp.iterdir()) == []


@needs_engine
def test_find_engine_uses_the_configured_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "leer"
    empty.mkdir()
    monkeypatch.setattr(ocr, "BUNDLED_DIR", tmp_path / "nicht-installiert")
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv(ocr.ENGINE_VARIABLE, str(ENGINE.executable))
    found = ocr.find_engine()
    assert found is not None and found.executable == ENGINE.executable and found.tessdata == ENGINE.tessdata
    assert found.version.split(".")[0].isdigit() and int(found.version.split(".")[0]) >= ocr.MIN_VERSION
    assert "osd" not in found.languages and found.orientation == (ENGINE.tessdata / "osd.traineddata").is_file()


@needs_engine
def test_bundled_layout_is_preferred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gebündelt (``<Installationsordner>\\ocr``) geht vor PATH – hier mit einem Verweis auf die lokale Engine."""
    if os.name == "nt":
        pytest.skip("Verknüpfungen auf ausführbare Dateien sind unter Windows nicht ohne Weiteres möglich")
    bundled = tmp_path / "ocr"
    (bundled / "tessdata").mkdir(parents=True)
    (bundled / "tesseract").symlink_to(ENGINE.executable)
    shutil.copy2(ENGINE.tessdata / "deu.traineddata", bundled / "tessdata" / "deu.traineddata")
    monkeypatch.setattr(ocr, "BUNDLED_DIR", bundled)
    found = ocr.find_engine()
    assert found is not None and found.executable == bundled / "tesseract" and found.tessdata == bundled / "tessdata" and found.languages == ("deu",)
