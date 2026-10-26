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

    workspace = h.item("readerWorkspace")
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
        monkeypatch.setattr(files, "RESPONSES", [str(target.with_suffix(""))])  # Endung ergänzt Novadesk
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
    # Gezogene Office-Dateien öffnen sich seit Novadesk 5.0 als Ansicht im eigenen Tab: ohne Dateiauswahl, ohne PDF
    # neben der Datei; der Tab zeigt den Originalnamen
    monkeypatch.setattr(files, "RESPONSES", [])
    hooks.drop([str(slides)], "reader")
    assert wait_until(lambda: reader(h).current is not None and reader(h).current.sourcePath == str(slides), 30)
    settle(h)
    assert reader(h).current.path == "" and reader(h).current.pageCount == 2 and not (tmp_path / "Folien.pdf").exists()
    assert calls[-1] == ("powerpoint", "Folien.pptx")
    # Ohne Excel: klare Meldung, keine Dateiauswahl
    sheet = tmp_path / "Liste.xlsx"
    sheet.write_bytes(b"PK")
    monkeypatch.setattr(files, "RESPONSES", [])
    reader(h).office_to_pdf(str(sheet))
    notice = h.app.notices.get("reader")
    assert notice.title == "Office in PDF" and "Microsoft Excel" in notice.message and not (tmp_path / "Liste.pdf").exists()


def test_office_view_tab_restore_and_failures(ui_app, tmp_path: Path, monkeypatch) -> None:
    """Ansicht einer Office-Datei (seit 5.0): eigener Tab mit Originalname und Dateiart, umgewandelt außerhalb der
    PDF-Engine; ein Fehler meldet sich als Office-Fehler (kein »PDF reparieren«); »Im Standardprogramm öffnen« zeigt
    »Öffnen mit«, wenn Novadesk selbst das Standardprogramm ist."""
    import winsys
    from tools.pdf_editor import office

    h = ui_app
    h.app.dialogs.shutdown()
    threads = []

    def fake(kind, source, target):
        import threading

        threads.append(threading.current_thread().name)
        if source.name.startswith("Kaputt"):
            raise office.OfficeError("LibreOffice konnte die Datei nicht umwandeln (Code 1). Ist sie beschädigt oder mit einem Kennwort geschützt?")
        samples.standard_text(target, pages=1)

    monkeypatch.setattr(office, "TEST_BACKEND", fake)
    monkeypatch.setattr(office, "TEST_INSTALLED", {"libreoffice"})
    # Tabellen öffnen sich seit 5.0 Beta 2 zum Bearbeiten (test_qt_sheet.py) – angesehen werden Texte und Präsentationen
    letter, sheet = tmp_path / "Brief.docx", tmp_path / "Folien.odp"
    for path in (letter, sheet):
        path.write_bytes(b"PK")
    controller = reader(h)
    # Texte (seit 5.0 Beta 3, test_qt_text.py) und Präsentationen (seit Beta 4, test_qt_slides.py) öffnen sich zum
    # Bearbeiten, solange LibreOffice da ist; ohne bleibt die Ansicht
    monkeypatch.setattr(type(controller), "edits_text", lambda self, path: False)
    monkeypatch.setattr(type(controller), "edits_slides", lambda self, path: False)
    controller.open_paths([str(letter), str(sheet)])
    assert wait_until(lambda: len(controller.tabs.items()) == 2, 30)
    settle(h)
    assert [(t["name"], t["kind"], t["path"]) for t in controller.tabs.items()] == [("Brief.docx", "text", ""), ("Folien.odp", "praesentation", "")]
    assert threads and all(name == "pdftool-arbeit" for name in threads)  # nicht im Thread der PDF-Engine
    assert controller.current.sourcePath == str(sheet)

    # Zuletzt verwendet und Sitzung merken den Originalpfad; der aktive Tab ist die Präsentation
    assert [item["path"] for item in controller.recent[:2]] == [str(sheet), str(letter)]
    snapshot = controller._session_snapshot()
    assert snapshot["aktiv"] == str(sheet) and [d["pfad"] for d in snapshot["dokumente"]] == [str(letter), str(sheet)]

    # Novadesk ist Standardprogramm für .odp: »Öffnen mit« statt wieder dieser Tab
    geoeffnet = []
    monkeypatch.setattr(winsys, "default_program", lambda path: r"C:\Users\x\AppData\Local\PDF-Tool\PDF-Tool.exe")
    monkeypatch.setattr(winsys, "open_with", lambda path: geoeffnet.append(("mit", str(path))))
    monkeypatch.setattr(controller, "openExternal", lambda path: geoeffnet.append(("standard", str(path))))
    controller.officeAction("external")
    monkeypatch.setattr(winsys, "default_program", lambda path: r"C:\Program Files\LibreOffice\program\simpress.exe")
    controller.officeAction("external")
    assert geoeffnet == [("mit", str(sheet)), ("standard", str(sheet))]

    # Umwandeln scheitert: klare Meldung, kein Tab, keine Frage nach »PDF reparieren«
    broken = tmp_path / "Kaputt.docx"
    broken.write_bytes(b"PK")
    asked = []
    monkeypatch.setattr(controller, "_offer_repair", lambda path: asked.append(path))
    controller.open_paths([str(broken)])
    assert wait_until(lambda: controller.opening == 0 and h.app.notices.get("reader") is not None, 30)
    notice = h.app.notices.get("reader")
    assert notice.title == "Office-Datei ansehen" and "beschädigt" in notice.message
    assert len(controller.tabs.items()) == 2 and asked == []
