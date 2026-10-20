"""Umwandeln im Reader (seit 4.0 Beta 6): »Alle Werkzeuge« › In Word/Excel/Text umwandeln; Office-Dateien (Attrappe
statt Office) über die Startseite, per Ziehen und ohne installiertes Office."""

from __future__ import annotations

import zipfile
from pathlib import Path

from PySide6.QtCore import QMetaObject

import editorsamples as samples
from conftest import wait_until
from test_convert import report_pdf
from test_qt_reader import open_pdf, reader, settle


def perform(h, command: str) -> None:
    from test_qt_protect import center, child
    from test_qt_reader import click

    workspace = h.item("readerQuickToolsArea").parentItem()
    panel = child(workspace, "readerAllToolsPanel")
    click(h, center(h.item("readerAllTools")))
    assert wait_until(lambda: panel.property("opened"), 3)
    # wie ein gewählter Eintrag: Befehl vormerken, Liste schließen – ausgeführt wird nach »closed«
    panel.setProperty("pending", command)
    panel.setProperty("quietClose", True)
    QMetaObject.invokeMethod(panel, "close")


def test_convert_to_word_excel_and_text(ui_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import files

    h = ui_app
    h.app.dialogs.shutdown()
    h.navigate("reader", 0.3)
    open_pdf(h, report_pdf(tmp_path / "bericht.pdf"))
    for command, suffix, title in (("toWord", ".docx", "In Word umgewandelt"), ("toExcel", ".xlsx", "In Excel umgewandelt"), ("toText", ".txt", "In Text umgewandelt")):
        target = tmp_path / f"ausgabe{suffix}"
        monkeypatch.setattr(files, "RESPONSES", [str(target.with_suffix(""))])  # Endung ergänzt PDF Tool
        perform(h, command)
        assert wait_until(lambda: target.is_file(), 20), command
        settle(h)
        notice = h.app.notices.get("reader")
        assert notice.title == title and "1 Seite gespeichert als" in notice.message
    assert "Jahresbericht 2026" in (tmp_path / "ausgabe.txt").read_text(encoding="utf-8-sig")
    with zipfile.ZipFile(tmp_path / "ausgabe.docx") as package:
        assert "Jahresbericht 2026" in package.read("word/document.xml").decode("utf-8")
    assert Path(reader(h).current.path).name == "bericht.pdf"  # das PDF bleibt offen und unverändert


def test_office_file_becomes_pdf(ui_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import files
    from tools.pdf_editor import office

    h = ui_app
    h.app.dialogs.shutdown()
    calls = []

    def fake(kind, source, target):
        calls.append((kind, source.name))
        samples.standard_text(target, pages=2)

    monkeypatch.setattr(office, "TEST_BACKEND", fake)
    monkeypatch.setattr(office, "TEST_INSTALLED", {"word", "powerpoint"})
    letter = tmp_path / "Brief.docx"
    letter.write_bytes(b"PK")
    # Startseite › »Office in PDF«: Datei wählen, Ziel bestätigen, PDF öffnet sich im Reader
    monkeypatch.setattr(files, "RESPONSES", [str(letter), str(tmp_path / "Brief.pdf")])
    reader(h).quickTool("office")
    assert wait_until(lambda: reader(h).current is not None and Path(reader(h).current.path or "").name == "Brief.pdf", 30)
    settle(h)
    assert calls == [("word", "Brief.docx")] and reader(h).current.pageCount == 2
    # Ziehen: Word und PowerPoint überall, Excel-Listen nur im Reader (Startseite: »Vertragsübersichten«)
    hooks = h.runtime.reader
    slides = tmp_path / "Folien.pptx"
    slides.write_bytes(b"PK")
    assert hooks.accepts([str(slides)], "") and not hooks.accepts([str(tmp_path / "Liste.xlsx")], "")
    assert hooks.accepts([str(tmp_path / "Liste.xlsx")], "reader")
    monkeypatch.setattr(files, "RESPONSES", [str(tmp_path / "Folien.pdf")])
    hooks.drop([str(slides)], "reader")
    assert wait_until(lambda: (tmp_path / "Folien.pdf").is_file() and Path(reader(h).current.path or "").name == "Folien.pdf", 30)
    # Ohne Excel: klare Meldung, keine Dateiauswahl
    sheet = tmp_path / "Liste.xlsx"
    sheet.write_bytes(b"PK")
    monkeypatch.setattr(files, "RESPONSES", [])
    reader(h).office_to_pdf(str(sheet))
    notice = h.app.notices.get("reader")
    assert notice.title == "Office in PDF" and "Microsoft Excel" in notice.message and not (tmp_path / "Liste.pdf").exists()
