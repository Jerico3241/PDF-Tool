"""Präsentation Profi (seit 5.0 Beta 6): Designs, Hintergrund, Folienmaster, Übergänge, Video und Ton, Vorführen mit
Übergängen, Export als Bilder und als Video – dazu die Vorlagen für Texte, Tabellen und Präsentationen.

Die Tests mit dem Textkern brauchen LibreOffice (``soffice`` im PATH oder ``NOVADESK_LIBREOFFICE``); die mit Video
zusätzlich Qt Multimedia (PySide6-Addons)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from conftest import wait_until
from qtutil import pump


def _office_available() -> bool:
    from tools.text import engine

    return engine.available()


def _multimedia() -> bool:
    try:
        from qtapp.text import video

        return video.available()
    except ImportError:
        return False


needs_text = pytest.mark.skipif(not _office_available(), reason="LibreOffice fehlt – Präsentationen nicht prüfbar")
needs_video = pytest.mark.skipif(not _multimedia(), reason="Qt Multimedia fehlt")


def _new_slides(h):
    reader = h.runtime.singletons["Reader"]
    reader.newSlides()
    assert wait_until(lambda: reader.current is not None and getattr(reader.current, "ready", False), 120)
    pump(1.0)
    return reader.current


def _settle(doc, seconds: float = 0.6) -> None:
    """Bis der Textkern alles erledigt hat (Makros laufen nacheinander)."""
    pump(seconds)


def _clip(path: Path, seconds: float = 1.0) -> Path:
    """Kurzes Video (zwei Farben) wie »Als Video speichern« – auch für »Video einfügen«."""
    from qtapp.text import video

    frames = []
    for color in ("#c50f1f", "#0f6cbd"):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        frames.append(video.Slide(image, seconds / 2, "keiner"))
    writer = video.VideoWriter(str(path), frames, QSize(320, 180))
    done: list = []
    writer.finished.connect(done.append)
    writer.failed.connect(lambda message: done.append("!" + message))
    writer.start()
    assert wait_until(lambda: bool(done), 60)
    assert not str(done[0]).startswith("!"), done
    return path


@needs_text
def test_design_background_and_transitions_are_saved(ui_app, tmp_path: Path) -> None:
    """Ein Design gilt für alle Folien (Hintergrund im Master), ein Übergang mit Dauer und »weiter nach« für die gezeigte
    bzw. alle Folien – PowerPoint liest beides aus der .pptx."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_slides(h)
    doc.newSlide()
    assert wait_until(lambda: doc.slideCount == 2, 20)
    assert [entry["key"] for entry in doc.designList()][:2] == ["weiss", "blau"]
    doc.applyDesign("blau")
    _settle(doc)
    doc.setTransition("blenden")
    _settle(doc)
    doc.setAdvance(5)
    _settle(doc)
    assert wait_until(lambda: len(doc.transitions) == 2 and doc.transitions[doc.slideIndex]["kind"] == "blenden", 20), doc.transitions
    assert doc.transitions[doc.slideIndex]["advance"] == 5
    doc.transitionToAll()
    _settle(doc)
    assert wait_until(lambda: all(entry["kind"] == "blenden" for entry in doc.transitions), 20), doc.transitions
    target = tmp_path / "Design.pptx"
    doc.save(str(target))
    assert wait_until(lambda: not doc.saving and target.exists(), 60)
    with zipfile.ZipFile(target) as archive:
        masters = "".join(archive.read(name).decode("utf-8") for name in archive.namelist() if name.startswith("ppt/slideMasters/slideMaster"))
        slides = [archive.read(f"ppt/slides/slide{n}.xml").decode("utf-8") for n in (1, 2)]
    assert "1F4E79" in masters.upper(), "Verlauf des Designs im Master"
    assert all("<p:transition" in slide and "fade" in slide for slide in slides)
    assert 'advTm="5000"' in slides[0]


@needs_text
def test_master_view_and_slide_pictures(ui_app) -> None:
    """Der Folienmaster zeigt die Master statt der Folien (Präsentieren ist dort gesperrt), zurück stehen wieder die
    Folien da. Bilder anderer Folien zeigen die Folie – früher mitunter die Notizenseite (weiß mit Notizenrahmen)."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_slides(h)
    doc.newSlide()
    assert wait_until(lambda: doc.slideCount == 2, 20)
    doc.applyDesign("nacht")
    _settle(doc)
    view = h.item("slidesView")
    doc.toggleMaster()
    assert wait_until(lambda: doc.masterMode and doc.slideCount >= 1 and doc.slideNames and doc.slideNames[0] != "Folie 1", 20), doc.slideNames
    assert view.findChild(QObject, "slidesMasterBar").property("visible")
    doc.present()
    pump(0.3)
    assert not doc.presenting
    doc.toggleMaster()
    assert wait_until(lambda: not doc.masterMode and doc.slideCount == 2 and doc.slideNames[:1] == ["Folie 1"], 20), doc.slideNames
    # Folie 1 ist nicht die gezeigte: ihr Bild muss den dunklen Hintergrund des Designs zeigen
    doc.goSlide(1)
    assert wait_until(lambda: doc.slideIndex == 1, 20)
    pictures: list = []
    doc.request_thumb(0, 160, 90, pictures.append, lambda exc: pictures.append(exc))
    assert wait_until(lambda: bool(pictures), 20)
    data = pictures[0]
    assert isinstance(data, bytes) and len(data) == 160 * 90 * 4
    image = QImage(data, 160, 90, 160 * 4, QImage.Format.Format_ARGB32_Premultiplied)
    middle = image.pixelColor(80, 60)
    assert middle.lightness() < 120, f"Folie 1 ist hell ({middle.name()}) – Notizenseite statt Folie?"


@needs_text
@needs_video
def test_video_on_slide_is_embedded_and_plays_in_show(ui_app, tmp_path: Path) -> None:
    """Ein Video kommt mit Vorschaubild auf die Folie und in die Datei (.pptx); beim Vorführen spielt es an seiner
    Stelle, die Folie selbst steht ohne leere Platzhalter da."""
    from qtapp import files

    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_slides(h)
    clip = _clip(tmp_path / "Clip.mp4")
    files.RESPONSES = [str(clip)]
    try:
        doc.insertMedia("video")
        _settle(doc, 1.0)
    finally:
        files.RESPONSES = None
    doc.refresh_media()
    assert wait_until(lambda: len(doc.media) == 1, 20), doc.media
    entry = doc.media[0]
    assert entry["part"] == 0 and not entry["audio"] and Path(entry["path"]).is_file()
    assert 0.1 < entry["x"] < 0.5 and 0.4 < entry["w"] < 0.8
    target = tmp_path / "Video.pptx"
    doc.save(str(target))
    assert wait_until(lambda: not doc.saving and target.exists(), 60)
    with zipfile.ZipFile(target) as archive:
        assert any(name.startswith("ppt/media/") and name.endswith(".mp4") for name in archive.namelist())
    doc.presentFromStart()
    assert wait_until(lambda: doc.presenting and len(doc.showFrames) == 1 and doc.showFrames[0], 30)
    view = h.item("slidesView")
    loader = view.findChild(QObject, "slidesShowMedia")
    assert wait_until(lambda: loader.property("item") is not None, 20)
    clips = [child for child in loader.property("item").childItems() if child.objectName() == "slideShowMedia_0"]
    assert clips, "Video beim Vorführen"
    doc.endPresent()
    assert wait_until(lambda: not doc.presenting and doc.showFrames == [], 10)


@needs_text
def test_show_runs_transition_and_advances_by_time(ui_app) -> None:
    """Beim Vorführen läuft der Übergang der neuen Folie; mit »weiter nach« blättert die Präsentation selbst."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_slides(h)
    doc.newSlide()
    assert wait_until(lambda: doc.slideCount == 2, 20)
    doc.goSlide(0)
    assert wait_until(lambda: doc.slideIndex == 0, 20)
    doc.setTransition("schieben")
    _settle(doc)
    doc.setAdvance(2)
    _settle(doc)
    doc.transitionToAll()
    _settle(doc)
    view = h.item("slidesView")
    stage = view.findChild(QObject, "slidesShowStage")
    doc.presentFromStart()
    assert wait_until(lambda: doc.presenting and stage.property("backPart") == 0, 30)
    # Nach zwei Sekunden die zweite Folie, mit Schieben
    assert wait_until(lambda: doc.presentIndex == 1, 10)
    assert wait_until(lambda: stage.property("running"), 5) or stage.property("backPart") == 1
    assert wait_until(lambda: stage.property("backPart") == 1 and not stage.property("running"), 10)
    doc.endPresent()
    assert wait_until(lambda: not doc.presenting, 10)


@needs_text
def test_export_slides_as_pictures(ui_app, tmp_path: Path) -> None:
    """»Exportieren → Folien als Bilder«: je Folie ein Bild in der gewählten Größe, ohne leere Platzhalter."""
    from qtapp import dialogs, files

    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_slides(h)
    doc.newSlide()
    assert wait_until(lambda: doc.slideCount == 2, 20)
    folder = tmp_path / "Bilder"
    folder.mkdir()
    dialogs.AUTO_ANSWER = "primary"
    files.RESPONSES = [str(folder)]
    try:
        doc.exportImages()
        assert wait_until(lambda: not doc.exporting and len(list(folder.iterdir())) == 2, 60)
    finally:
        dialogs.AUTO_ANSWER = None
        files.RESPONSES = None
    pictures = sorted(folder.iterdir())
    assert [path.name[-12:] for path in pictures] == ["Folie 01.png", "Folie 02.png"]
    image = QImage(str(pictures[0]))
    assert image.width() == 1920 and image.height() in (1080, 1079, 1081)
    # Leere Platzhalter (»Titel durch Klicken hinzufügen«) erscheinen nicht: die Folie ist eine Fläche
    colors = {image.pixelColor(x, y).name() for x in range(0, 1920, 64) for y in range(0, 1080, 64)}
    assert len(colors) <= 2, colors


@needs_text
@needs_video
def test_export_presentation_as_video(ui_app, tmp_path: Path) -> None:
    """»Exportieren → Als Video«: jede Folie so lange wie eingestellt, als MP4."""
    from qtapp import dialogs, files

    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_slides(h)
    doc.newSlide()
    assert wait_until(lambda: doc.slideCount == 2, 20)
    target = tmp_path / "Film.mp4"
    dialogs.AUTO_ANSWER = "primary"
    files.RESPONSES = [str(target)]
    try:
        doc.exportVideo()
        assert wait_until(lambda: not doc.exporting and target.exists(), 120)
    finally:
        dialogs.AUTO_ANSWER = None
        files.RESPONSES = None
    assert target.stat().st_size > 10_000
    assert target.read_bytes()[4:8] == b"ftyp"


def test_frame_plan_and_poster() -> None:
    """Ablauf des Videos (Überblenden, durch Schwarz) und das Vorschaubild eines Videos bzw. Tons."""
    from qtapp.text import video

    image = QImage(16, 9, QImage.Format.Format_RGB32)
    slides = [video.Slide(image, 1.0, "keiner"), video.Slide(image, 1.0, "blenden"), video.Slide(image, 1.0, "schwarz")]
    plan = video.frame_plan(slides, fps=10)
    fade = round(video.FADE_SECONDS * 10)
    assert len(plan) == 30 + fade + 2 * (fade // 2)
    assert plan[10] == (1, 0, pytest.approx(1 / (fade + 1)))
    assert any(share < 0 for _index, _previous, share in plan), "durch Schwarz"
    poster = video.poster(None, 1920, 1080, False)
    assert poster.width() == video.POSTER_WIDTH and abs(poster.height() - 540) <= 1
    assert video.poster(None, 0, 0, True).width() == video.poster(None, 0, 0, True).height()


def test_templates_page_lists_every_template(ui_app) -> None:
    """»Vorlagen« in der Navigation (und »Neu → Aus Vorlage«) zeigt die Vorlagen mit Vorschau; der Filter grenzt nach
    Dateiart ein. Die Vorlagen für Vertragsübersichten bleiben erreichbar."""
    from qtapp.reader import controller

    h = ui_app
    h.app.dialogs.shutdown()
    for entry in controller.OFFICE_TEMPLATES:
        assert (controller.TEMPLATE_DIR / entry["file"]).is_file(), entry["file"]
        assert (Path(controller.__file__).resolve().parents[2] / "qml" / "images" / "vorlagen" / f"{entry['key']}.png").is_file()
    QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     h.item("navTemplates").mapToScene(QPointF(20, 10)).toPoint())
    pump(0.5)
    assert h.app.homeSection == "templates" and h.item("homeTemplates").isVisible()
    for entry in controller.OFFICE_TEMPLATES:
        assert h.item("homeTemplate_" + entry["key"]) is not None, entry["key"]
    QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     h.item("homeTemplatesKind_tabelle").mapToScene(QPointF(10, 10)).toPoint())
    pump(0.4)
    assert h.item("homeTemplate_rechnung") is not None and h.item("homeTemplate_lebenslauf") is None
    QTest.mouseClick(h.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     h.item("homeTemplatesContractsOpen").mapToScene(QPointF(10, 10)).toPoint())
    pump(0.5)
    assert h.app.currentPage == "templates"


@needs_text
def test_new_documents_from_templates(ui_app, tmp_path: Path) -> None:
    """Aus einer Vorlage entsteht ein neues, unverändertes Dokument (»Rechnung1.xlsx«, ohne Pfad); die Rechnung rechnet
    ihre Summen selbst, der Lebenslauf speichert als .docx, die Präsentation hat fünf Folien."""
    h = ui_app
    h.app.dialogs.shutdown()
    reader = h.runtime.singletons["Reader"]

    def make(key: str):
        before = reader.current
        reader.newFromTemplate(key)
        assert wait_until(lambda: reader.current is not None and reader.current is not before and getattr(reader.current, "ready", False), 120)
        pump(1.0)
        return reader.current

    sheet = make("rechnung")
    assert sheet.name == "Rechnung1.xlsx" and sheet.path == "" and not sheet.dirty
    target = tmp_path / "Rechnung.xlsx"
    sheet.save(str(target))
    assert wait_until(lambda: not sheet.saving and target.exists(), 60)
    import openpyxl

    values = openpyxl.load_workbook(target, data_only=True).active
    cells = {str(row[4].value): row[5].value for row in values.iter_rows() if row[4].value in ("Netto", "Gesamt")}
    assert cells.get("Netto") == pytest.approx(279.9) and cells.get("Gesamt") == pytest.approx(333.08), cells
    text = make("lebenslauf")
    assert text.name == "Lebenslauf1.docx" and text.path == "" and not text.dirty
    target = tmp_path / "Lebenslauf.docx"
    text.save(str(target))
    assert wait_until(lambda: not text.saving and target.exists(), 60)
    assert "Berufserfahrung" in zipfile.ZipFile(target).read("word/document.xml").decode("utf-8")
    deck = make("projektvorstellung")
    assert deck.kind == "praesentation" and deck.name == "Projekt1.pptx" and deck.slideCount == 5
    assert make("rechnung").name == "Rechnung2.xlsx"
