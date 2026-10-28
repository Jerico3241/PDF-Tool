"""Texte, Beta 5: Verzeichnis, Fuß- und Endnoten, Querverweise, Formeln, Diagramme, Kommentare, nachverfolgte
Änderungen, Vergleichen, Serienbrief, Lesemodus und Augenschutz.

Die Tests mit dem Textkern brauchen LibreOffice (mit Math und Chart); im Setup prüft ``build.py probe_text`` die
Hilfsmakros im mitgelieferten LibreOffice."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent

from conftest import wait_until
from qtutil import pump


def _text_available() -> bool:
    from tools.text import engine

    return engine.available()


needs_text = pytest.mark.skipif(not _text_available(), reason="LibreOffice fehlt – Textkern nicht prüfbar")


def _new_text(h):
    reader = h.runtime.singletons["Reader"]
    reader.newText()
    assert wait_until(lambda: reader.current is not None and getattr(reader.current, "ready", False), 120)
    pump(1.0)
    return reader.current


def _write(doc, text: str) -> None:
    doc.type_text(text)
    pump(0.3)


def _enter(doc) -> None:
    doc.key(13, 1280)
    pump(0.2)


def _macro(doc, name: str, values: list | None = None) -> list:
    result: list = []
    errors: list = []
    doc.macro(name, values, lambda answer: result.append(answer), lambda exc: errors.append(exc))
    assert wait_until(lambda: result or errors, 60), name
    assert not errors, errors
    return result[0]


def _save_odt(doc, path: Path) -> str:
    assert doc.save(str(path)) is not False
    assert wait_until(lambda: not doc.saving and path.exists(), 60)
    pump(0.3)
    return zipfile.ZipFile(path).read("content.xml").decode("utf-8")


def _letter(doc) -> None:
    """Zwei Überschriften mit Text, eine Fußnote, eine Endnote."""
    doc.applyStyle("Überschrift 1")
    pump(0.2)
    _write(doc, "Angebot")
    _enter(doc)
    doc.applyStyle("Standard")
    pump(0.2)
    _write(doc, "Wartung der Heizung")
    doc.insertFootnote()
    pump(0.5)
    _write(doc, "Termine nach Absprache.")
    doc.uno(".uno:GoToEndOfDoc")
    pump(0.3)
    doc.uno(".uno:GoToEndOfDoc")
    pump(0.3)
    _enter(doc)
    doc.applyStyle("Überschrift 2")
    pump(0.2)
    _write(doc, "Preise")
    _enter(doc)
    doc.applyStyle("Standard")
    pump(0.2)
    _write(doc, "Die Wartung kostet 189 Euro.")
    doc.insertEndnote()
    pump(0.5)
    _write(doc, "Ohne Mehrwertsteuer.")
    doc.uno(".uno:GoToEndOfDoc")
    pump(0.3)
    doc.uno(".uno:GoToEndOfDoc")
    pump(0.3)
    _enter(doc)


@pytest.mark.parametrize("name", ["TextCommentsPanel", "TextChangesPanel", "TextMergePanel"])
def test_review_panels_load(ui_app, name: str) -> None:
    """Die neuen Seitenleisten laden ohne Meldungen, auch ohne Text."""
    from qtapp.application import QML_DIR

    component = QQmlComponent(ui_app.engine, QUrl.fromLocalFile(str(QML_DIR / "PdfTool" / "Reader" / f"{name}.qml")))
    assert component.isReady(), component.errorString()
    item = component.create()
    assert item is not None, component.errorString()
    item.deleteLater()
    pump(0.1)


@pytest.mark.parametrize("name", ["CrossReferenceContent", "FormulaContent", "ChartContent"])
def test_review_dialogs_load(ui_app, name: str) -> None:
    from qtapp.application import QML_DIR

    component = QQmlComponent(ui_app.engine, QUrl.fromLocalFile(str(QML_DIR / "PdfTool" / "Dialogs" / f"{name}.qml")))
    assert component.isReady(), component.errorString()
    item = component.create()
    assert item is not None, component.errorString()
    item.deleteLater()
    pump(0.1)


@needs_text
def test_toc_notes_cross_reference_formula_and_chart(ui_app, tmp_path: Path, monkeypatch) -> None:
    """Verzeichnis mit beiden Überschriften, Fuß- und Endnote, Querverweise auf Überschrift und Fußnote, eine Formel
    und ein Diagramm – alles echt in der gespeicherten Datei (OpenDocument)."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_text(h)
    _letter(doc)
    targets = [record.split("\x1f") for record in _macro(doc, "Ziele")]
    kinds = [target[0] for target in targets]
    assert kinds.count("heading") == 2 and kinds.count("footnote") == 1 and kinds.count("endnote") == 1, targets
    assert any(target[0] == "heading" and target[4] == "Preise" for target in targets)

    # Querverweise über den Dialog: Text der Überschrift »Preise«, Nummer der Fußnote
    answers = iter([
        ("primary", {"target": next(i for i, t in enumerate(targets) if t[4] == "Preise"), "part": "text"}),
        ("primary", {"target": kinds.index("footnote"), "part": "number"}),
    ])
    asked: list = []
    monkeypatch.setattr(h.app.dialogs, "ask", lambda kind, title, message="", **options: (asked.append((kind, options)), next(answers))[1])
    _write(doc, "Siehe ")
    doc.insertCrossReference()
    assert wait_until(lambda: len(asked) == 1, 30)
    pump(1.0)
    _write(doc, ", Fußnote ")
    doc.insertCrossReference()
    assert wait_until(lambda: len(asked) == 2, 30)
    pump(1.0)
    assert asked[0][0] == "text_crossref" and {kind["key"] for kind in asked[0][1]["data"]["kinds"]} == {"heading", "footnote", "endnote"}
    _enter(doc)

    # Formel und Diagramm (über die Dialoge)
    formulas = iter([("primary", {"formula": "a^2 + b^2 = c^2"})])
    monkeypatch.setattr(h.app.dialogs, "ask", lambda kind, title, message="", **options: (asked.append((kind, options)), next(formulas))[1])
    doc.insertFormula()
    assert wait_until(lambda: len(asked) == 3, 30)
    pump(1.5)
    assert asked[2][0] == "text_formula" and asked[2][1]["data"] == {"formula": ""}
    doc.uno(".uno:Escape")
    pump(0.3)
    doc.uno(".uno:GoToEndOfDoc")
    _enter(doc)
    charts = iter([("primary", {"kind": "bar", "title": "Umsatz", "series": ["2025", "2026"],
                                "rows": [{"label": "Januar", "values": ["4", "5,5"]}, {"label": "Februar", "values": ["6", "7"]}]})])
    monkeypatch.setattr(h.app.dialogs, "ask", lambda kind, title, message="", **options: (asked.append((kind, options)), next(charts))[1])
    doc.insertChart()
    assert wait_until(lambda: len(asked) == 4, 30)
    pump(1.5)
    assert asked[3][0] == "text_chart"
    # Diagramm anklicken (hier: zum nächsten Objekt springen): »Diagramm« liest seine Werte zum Ändern
    doc.uno(".uno:GoToStartOfDoc")
    pump(0.3)
    doc.uno(".uno:JumpToNextFrame")
    pump(0.5)
    assert _macro(doc, "FormelLesen") == ["a^2 + b^2 = c^2"]
    doc.uno(".uno:Escape")
    pump(0.3)
    doc.uno(".uno:JumpToNextFrame")
    pump(0.5)
    result = _macro(doc, "DiagrammLesen")
    assert result[:2] == ["bar", "Umsatz"] and result[2].split("\x1f")[1:] == ["2025", "2026"]
    assert [row.split("\x1f")[0] for row in result[3:]] == ["Januar", "Februar"]
    assert [float(value) for value in result[3].split("\x1f")[1:]] == [4.0, 5.5]
    # Ändern: dasselbe Diagramm bekommt Art, Titel und Werte aus dem Dialog
    changed = iter([("primary", {"kind": "line", "title": "Neu", "series": ["A"], "rows": [{"label": "X", "values": ["1"]}]})])
    monkeypatch.setattr(h.app.dialogs, "ask", lambda kind, title, message="", **options: (asked.append((kind, title, options)), next(changed))[1])
    doc.insertChart()
    assert wait_until(lambda: len(asked) == 5, 30)
    pump(1.5)
    assert asked[4][1] == "Diagramm ändern" and asked[4][2]["data"]["title"] == "Umsatz"
    result = _macro(doc, "DiagrammLesen")
    assert result[:2] == ["line", "Neu"] and len(result) == 4
    doc.uno(".uno:Escape")
    pump(0.3)

    # Verzeichnis an den Anfang
    doc.uno(".uno:GoToStartOfDoc")
    pump(0.3)
    doc.insertToc()
    pump(2.0)
    assert _macro(doc, "VerzeichnisseAktualisieren") == ["1"]

    target = tmp_path / "Angebot.odt"
    xml = _save_odt(doc, target)
    toc = re.search(r"<text:table-of-content\b.*?</text:table-of-content>", xml, re.S)
    assert toc, "Inhaltsverzeichnis fehlt"
    body = re.sub(r"<[^>]+>", "", toc.group(0))
    assert "Inhaltsverzeichnis" in body and "Angebot" in body and "Preise" in body
    assert len(re.findall(r'<text:note [^>]*text:note-class="footnote"', xml)) == 1
    assert len(re.findall(r'<text:note [^>]*text:note-class="endnote"', xml)) == 1
    assert re.search(r"<text:bookmark-ref [^>]*text:reference-format=\"text\"[^>]*>Preise</text:bookmark-ref>", xml), "Querverweis auf Überschrift"
    assert re.search(r"<text:note-ref [^>]*text:note-class=\"footnote\"[^>]*>1</text:note-ref>", xml), "Querverweis auf Fußnote"
    # Word: Verzeichnis als Feld (lässt sich dort aktualisieren), Formel als Word-Formel, Diagramm als Word-Diagramm
    word = tmp_path / "Angebot.docx"
    assert doc.save(str(word)) is not False
    assert wait_until(lambda: not doc.saving and word.exists(), 60)
    document = zipfile.ZipFile(word).read("word/document.xml").decode("utf-8")
    assert "TOC \\" in document and "<m:oMath" in document and "word/charts/chart1.xml" in zipfile.ZipFile(word).namelist()
    names = zipfile.ZipFile(target).namelist()
    objects = {name.split("/")[0] for name in names if name.startswith("Object ") and name.endswith("content.xml")}
    contents = [zipfile.ZipFile(target).read(f"{name}/content.xml").decode("utf-8") for name in sorted(objects)]
    assert any("a^2 + b^2 = c^2" in content for content in contents), "Formel fehlt"
    assert any("chart:chart" in content and "Neu" in content for content in contents), "Diagramm fehlt"
    assert len(contents) == 2


@needs_text
def test_comments_and_tracked_changes(ui_app, tmp_path: Path, monkeypatch) -> None:
    """Kommentar mit Antwort, erledigt, ändern, löschen; Änderungen nachverfolgen: Liste, eine annehmen, eine
    ablehnen; Vergleichen mit einer älteren Fassung markiert die Unterschiede."""
    h = ui_app
    h.app.dialogs.shutdown()
    monkeypatch.setattr(h.app.dialogs, "confirm", lambda *args, **kwargs: True)
    doc = _new_text(h)
    _write(doc, "Die Wartung kostet 189 Euro im Jahr.")
    old = tmp_path / "Alt.odt"
    _save_odt(doc, old)

    doc.find("189 Euro", False)
    pump(0.8)
    doc.addComment("Preis abstimmen.")
    assert wait_until(lambda: len(doc.comments) == 1, 20)
    first = doc.comments[0]
    assert first["text"] == "Preis abstimmen." and first["ranges"] and not first["resolved"]
    doc.replyComment(first["id"], "Ist abgestimmt.")
    assert wait_until(lambda: len(doc.comments) == 2 and doc.comments[1]["reply"], 20)
    doc.resolveComment(first["id"])
    assert wait_until(lambda: doc.comments[0]["resolved"], 20)
    doc.editComment(first["id"], "Preis mit Herrn Weber abstimmen.")
    assert wait_until(lambda: doc.comments[0]["text"] == "Preis mit Herrn Weber abstimmen.", 20)
    doc.deleteComment(doc.comments[1]["id"])
    assert wait_until(lambda: len(doc.comments) == 1, 20)

    doc.toggle("trackChanges")
    pump(0.4)
    doc.find("189", False)
    pump(0.6)
    _write(doc, "199")
    doc.uno(".uno:GoToEndOfDoc")
    pump(0.3)
    _write(doc, " Neu.")
    assert wait_until(lambda: len(doc.changes) == 3, 20), doc.changes
    assert [change["kind"] for change in doc.changes][:2] in (["Gelöscht", "Eingefügt"], ["Eingefügt", "Gelöscht"])
    assert doc.changes[-1]["kind"] == "Eingefügt" and doc.changes[-1]["author"]
    last = doc.changes[-1]["index"]
    doc.rejectChange(last)
    assert wait_until(lambda: len(doc.changes) == 2, 20)
    doc.acceptAllChanges()
    assert wait_until(lambda: not doc.changes, 20)
    doc.toggle("trackChanges")
    pump(0.4)

    xml = _save_odt(doc, tmp_path / "Neu.odt")
    text = re.sub(r"<[^>]+>", "", xml)
    assert "199 Euro im Jahr." in text and "Neu." not in text and "189" not in text
    assert "Preis mit Herrn Weber abstimmen." in text

    monkeypatch.setattr("qtapp.files.open_file", lambda *args, **kwargs: str(old))
    doc.compareWith()
    assert wait_until(lambda: doc.panel == "changes" and doc.sidebar and len(doc.changes) >= 1, 60), doc.changes


@needs_text
def test_mail_merge_letters(ui_app, tmp_path: Path, monkeypatch) -> None:
    """Empfänger aus CSV, Felder an der Schreibmarke, Briefe in einem neuen ungespeicherten Text."""
    h = ui_app
    h.app.dialogs.shutdown()
    reader = h.runtime.singletons["Reader"]
    doc = _new_text(h)
    source = tmp_path / "Empfänger.csv"
    source.write_text("Anrede;Name\nFrau;Müller\nHerr;Schmidt\nFrau;Weber\n", encoding="utf-8")
    monkeypatch.setattr("qtapp.files.open_file", lambda *args, **kwargs: str(source))
    doc.chooseMergeSource()
    assert doc.mergeFields == ["Anrede", "Name"] and doc.mergeCount == 3 and doc.panel == "merge"
    assert doc.mergeRecord(1) == {"Anrede": "Herr", "Name": "Schmidt"} and doc.mergeRecord(9) == {}
    _write(doc, "Hallo ")
    doc.insertMergeField("Anrede")
    _write(doc, " ")
    doc.insertMergeField("Name")
    doc.insertMergeField("Fehlt")
    _write(doc, ",")
    pump(0.5)
    doc.createLetters()
    assert wait_until(lambda: reader.current is not doc and getattr(reader.current, "ready", False), 120)
    assert wait_until(lambda: not doc.mergeBusy and reader.current.dirty, 30)
    letters = reader.current
    assert letters.name.endswith("– Serienbrief.docx") and not letters.path
    xml = _save_odt(letters, tmp_path / "Briefe.odt")
    text = re.sub(r"<[^>]+>", "\n", xml)
    for name in ("Hallo Frau Müller,", "Hallo Herr Schmidt,", "Hallo Frau Weber,"):
        assert name in text


@needs_text
def test_reading_mode_and_eye_care(ui_app) -> None:
    """Lesemodus: ohne Menüband, Text schreibgeschützt, Esc beendet ihn; Augenschutz färbt die Seiten."""
    h = ui_app
    h.app.dialogs.shutdown()
    doc = _new_text(h)
    _write(doc, "Lesen")
    view = h.item("textView")
    canvas = h.item("textCanvas")
    view.startReading()
    pump(0.3)
    assert view.property("reading") and canvas.property("readOnly")
    assert not h.item("textRibbonTabs").isVisible()
    view.stopReading()
    pump(0.3)
    assert not view.property("reading") and not canvas.property("readOnly") and h.item("textRibbonTabs").isVisible()
    view.setProperty("eyeCare", True)
    pump(0.2)
    assert canvas.property("tintColor").alpha() > 0
    view.setProperty("eyeCare", False)
    pump(0.2)
    assert canvas.property("tintColor").alpha() == 0
    assert view.findChild(QObject, "textCanvas") is not None
