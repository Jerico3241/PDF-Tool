"""Qt-Oberfläche: Werkzeug »PDF reparieren« (2.7.1: eine oder mehrere PDFs).

Teil 1 – eine PDF: alle Abläufe aus 2.7.0 (Reparatur, Teilrettung, unlesbare, verschlüsselte und
signierte PDFs, Rettungsmodus, Abbrechen, flüssige Oberfläche, Ausgabeordner, keine PDF,
erweiterte Wiederherstellung) – mit einer Datei bleibt das Werkzeug so einfach wie bisher.
Teil 2 – mehrere PDFs: Mehrfachauswahl, Ziehen und Ablegen, gemischte Zustände, »Alle
reparieren«, Abbrechen mitten im Durchlauf, Passwort und Signaturen je Datei, 100 PDFs.
Teil 3 – Ausgabenamen: Schalter »„repariert“ anhängen«, eigene Namen, Konflikte, Nummerierung.

Die App läuft mit QML im Fenster (offscreen); geprüft werden der ``RepairController`` (in QML:
``Repair``), seine Zeilen (``Repair.items``) und die QML-Elemente der Seite. Nach jedem Test
darf die QML-Engine keine Warnung gemeldet haben.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt

import pdfsamples as samples
from conftest import neustart, pump, wait_until
from qtutil import process_events

from tools.pdf_repair import presentation, process
from tools.pdf_repair.batch import ItemState
from tools.pdf_repair.models import RepairMode
from tools.pdf_repair.presentation import OUT_FOLDER, OUT_ORIGINAL

PASSWORT = "Geheim-123"


@pytest.fixture
def repair_app(ui_app, tmp_path: Path):
    """App mit Oberfläche, Ansicht »PDF reparieren«, Protokoll im Testordner."""
    ui_app.repair.log.path = tmp_path / "protokoll" / "pdf-repair.log"
    ui_app.navigate("repair", 0.3)
    assert ui_app.app.currentPage == "repair"
    return ui_app


# --- Hilfen ------------------------------------------------------------------------------------------


def wait_idle(h, timeout: float = 120.0) -> None:
    assert wait_until(lambda: not h.repair.busy and not h.repair.running, timeout), "Vorgang wurde nicht beendet"
    pump(0.1)


def eintrag(h, path: Path):
    """Die Datei in der Liste (``BatchItem``)."""
    item = next((item for item in h.repair.batch.items if item.path == Path(path)), None)
    assert item is not None, f"{Path(path).name} fehlt in der Liste"
    return item


def zeile(h, item) -> dict:
    """Was QML für die Datei anzeigt (Rollen der Zeile)."""
    row = h.repair.model.item(item.key)
    assert row is not None
    return row


def analyse(h, path: Path):
    h.repair.use(str(path))
    wait_idle(h)
    item = eintrag(h, path)
    assert item.analysis is not None
    return item.analysis


def hinzufuegen(h, paths: list[Path]) -> list:
    h.repair.add([str(path) for path in paths])
    wait_idle(h, 180)
    return [eintrag(h, path) for path in paths]


def repair(h, mode=None):
    h.repair.start_repair(mode)
    wait_idle(h, 180)
    return h.repair.result


def sichtbar(h, name: str, settle: float = 0.45) -> bool:
    """Ist das QML-Element nach dem Auf-/Zuklappen sichtbar?"""
    pump(settle)
    item = h.item(name)
    return item is not None and bool(item.property("visible"))


def bedienbar(h, name: str) -> bool:
    item = h.item(name)
    assert item is not None, f"QML-Element {name} fehlt"
    return bool(item.property("enabled"))


def druecken(element) -> None:
    """Schaltfläche in QML auslösen – ihr ``onClicked`` läuft wie bei einem Klick."""
    from PySide6.QtCore import QMetaObject

    assert element is not None and element.property("enabled") and element.property("visible")
    assert QMetaObject.invokeMethod(element, "clicked")
    pump(0.05)


def klicken(h, name: str) -> None:
    druecken(h.item(name))


def karte(h, item):
    """Karte der Datei in der (virtualisierten) Liste – vorher in den sichtbaren Bereich holen."""
    from PySide6.QtCore import Q_ARG, QMetaObject

    liste = h.item("repairList")
    row = h.repair.model.indexOf(item.key)
    assert row >= 0
    QMetaObject.invokeMethod(liste, "positionViewAtIndex", Q_ARG(int, row), Q_ARG(int, 4))  # ListView.Contain
    pump(0.3)
    found = h.item(f"repairItem_{item.key}")
    assert found is not None, f"Karte von {item.name} fehlt"
    return found


def in_karte(h, item, name: str):
    """QML-Element mit ``objectName`` in der Karte der Datei."""
    stack = [karte(h, item)]
    while stack:
        current = stack.pop()
        if current.objectName() == name:
            return current
        stack.extend(current.childItems())
    raise AssertionError(f"{name} fehlt in der Karte von {item.name}")


def taste(h, key) -> None:
    from PySide6.QtTest import QTest

    QTest.keyClick(h.window, key)
    pump(0.05)


def zwischenablage() -> str:
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.clipboard().text()


def qt_werte(obj) -> list[str]:
    """Alle Qt-Properties eines Controllers als Text (was QML sehen kann)."""
    meta = type(obj).staticMetaObject  # Metaobjekt der Python-Klasse (samt ihrer Properties)
    assert meta.className() == type(obj).__name__
    werte = []
    for index in range(meta.propertyCount()):
        try:
            werte.append(repr(meta.property(index).read(obj)))
        except RuntimeError:  # Werte ohne Python-Entsprechung (z. B. Aufzählungen)
            continue
    return werte


def texte_unter(root) -> list[str]:
    """Texte aller QML-Elemente unterhalb von ``root`` (Beschriftungen, Eingabefelder)."""
    found = []
    stack = [root]
    while stack:
        item = stack.pop()
        for name in ("text", "displayText", "message", "title"):
            value = item.property(name)
            if isinstance(value, str) and value:
                found.append(value)
        stack.extend(item.childItems())
    return found


def reparierte(folder: Path) -> list[str]:
    return [name for name in samples.files_in(folder) if "repariert" in name]


def beschaedigt(path: Path, pages: int = 3, image: bool = False) -> Path:
    """Reparierbare PDF (falscher startxref-Verweis) ohne Quelldatei daneben."""
    path.parent.mkdir(parents=True, exist_ok=True)
    source = samples.healthy(path.with_name("_tmp_" + path.name), pages=pages, image=image)
    data = re.sub(rb"startxref\s+(\d+)", lambda m: b"startxref\n" + str(int(m.group(1)) + 137).encode(), source.read_bytes())
    source.unlink()
    path.write_bytes(data)
    return path


def inhalte(paths: list[Path]) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


# --- Teil 1: eine PDF ------------------------------------------------------------------------------------


def test_repair_flow_saves_next_to_original(repair_app, tmp_path: Path) -> None:
    from qtapp import files

    h = repair_app
    folder = tmp_path / "Benutzer" / "Jérôme" / "Übersichten"
    pdf = samples.xref_offset(folder / "Rechnung März.pdf")
    before = pdf.read_bytes()
    # Leer: große Ablagefläche, noch keine Ausgabe und kein Ergebnis
    assert sichtbar(h, "repairDrop", 0) and sichtbar(h, "repairPick", 0)
    assert not sichtbar(h, "repairOutput", 0) and not sichtbar(h, "repairResult", 0)
    analysis = analyse(h, pdf)
    item = eintrag(h, pdf)
    assert analysis.condition.value == "repairable" and item.state is ItemState.READY
    # Einzelmodus: Diagnose mit Erklärung in der Karte, »PDF reparieren« bedienbar
    assert h.repair.single and h.repair.hasFile and h.repair.canStart
    row = zeile(h, item)
    assert row["diagTitle"] == "Reparierbare Probleme erkannt" and row["diagSeverity"] == "warning"
    diagnose = in_karte(h, item, "repairDiagnosis")
    pump(0.45)
    assert diagnose.property("visible") and diagnose.property("title") == "Reparierbare Probleme erkannt"
    assert not sichtbar(h, "repairDrop", 0) and not sichtbar(h, "repairOverview", 0)  # eine PDF: keine Übersicht
    assert sichtbar(h, "repairOutput") and bedienbar(h, "repairStart") and not bedienbar(h, "repairCancel")
    assert h.item("repairStart").property("text") == "PDF reparieren"
    assert row["name"] == "Rechnung März.pdf" and row["outputBase"] == "Rechnung März_repariert"
    assert in_karte(h, item, "repairOutputName").property("text") == "Rechnung März_repariert"
    assert h.repair.outName == "Ausgabe: Rechnung März_repariert.pdf"
    assert h.item("repairOutName").property("text") == h.repair.outName
    # »PDF reparieren« (Klick in QML)
    klicken(h, "repairStart")
    wait_idle(h)
    result = h.repair.result
    assert result is not None and result.status.value == "repaired"
    target = folder / "Rechnung März_repariert.pdf"
    assert h.repair.output == target and target.is_file()
    assert pdf.read_bytes() == before  # Original unverändert
    # Karte »Ergebnis« (wie bis 2.7.0) mit Öffnen, Ordner öffnen und Pfad kopieren
    assert h.repair.hasResult and sichtbar(h, "repairResult")
    notice = h.app.notices.get("repair_result")
    assert notice.shown and notice.severity == "success" and notice.title == "PDF wurde repariert."
    row = zeile(h, item)
    assert row["state"] == "repaired" and row["hasOutput"] and row["stateText"] == "Repariert"
    facts = {fact["label"]: fact["value"] for fact in row["resultFacts"]}
    assert facts["Ausgabedatei"] == "Rechnung März_repariert.pdf" and facts["Ordner"] == str(folder)
    assert row["resultActions"] and row["resultActions"][0]["value"] != "Keine Aktionen"
    klicken(h, "repairOpen")
    assert files.OPENED[-1] == str(target)
    h.repair.copyResultPath()  # »Pfad kopieren«
    assert zwischenablage() == str(target)
    assert not h.repair.canStart  # schon repariert
    # »Weitere PDFs reparieren« leert die Liste
    klicken(h, "repairAgain")
    assert h.repair.count == 0 and not h.repair.hasFile and not h.repair.hasResult
    assert h.repair.path is None and h.repair.analysis is None and h.repair.result is None
    assert sichtbar(h, "repairDrop") and not sichtbar(h, "repairResult", 0)
    # Dieselbe Datei noch einmal: neuer Name, nichts wird überschrieben
    analyse(h, pdf)
    assert h.repair.outName == "Ausgabe: Rechnung März_repariert (1).pdf"
    row = zeile(h, eintrag(h, pdf))
    assert row["numbered"] and row["outputName"] == "Rechnung März_repariert (1).pdf"
    note = in_karte(h, eintrag(h, pdf), "repairOutputNote")
    assert note.property("visible") and "Rechnung März_repariert (1).pdf" in note.property("text")
    repair(h)
    assert h.repair.output == folder / "Rechnung März_repariert (1).pdf"
    assert target.is_file() and pdf.read_bytes() == before
    log = h.repair.log.path.read_text(encoding="utf-8")
    assert "Rechnung März.pdf" in log and str(folder) not in log  # keine vollständigen Pfade


def test_partial_recovery_is_labelled(repair_app, tmp_path: Path) -> None:
    h = repair_app
    pdf = samples.truncated(tmp_path / "abgeschnitten.pdf")
    analysis = analyse(h, pdf)
    assert analysis.condition.value == "damaged"
    item = eintrag(h, pdf)
    assert zeile(h, item)["diagSeverity"] == "warning" and zeile(h, item)["diagTitle"] == "Schwer beschädigt"
    result = repair(h)
    assert result.status.value == "partially_recovered"
    notice = h.app.notices.get("repair_result")
    assert notice.shown and notice.severity == "warning" and "Seiten" in notice.message
    assert notice.title == "PDF teilweise wiederhergestellt"
    assert h.repair.output is not None and h.repair.output.name == "abgeschnitten_repariert.pdf"
    row = zeile(h, item)
    assert row["state"] == "partially_recovered" and row["stateText"].startswith("Teilweise wiederhergestellt")
    assert row["hasOutput"] and sichtbar(h, "repairResult")


def test_unreadable_file_cannot_be_repaired(repair_app, tmp_path: Path) -> None:
    h = repair_app
    analysis = analyse(h, samples.garbage(tmp_path / "zerstoert.pdf"))
    assert analysis.condition.value == "unreadable"
    item = eintrag(h, tmp_path / "zerstoert.pdf")
    assert item.state is ItemState.UNREADABLE and not h.repair.canStart and not bedienbar(h, "repairStart")
    row = zeile(h, item)
    assert row["diagSeverity"] == "error" and row["diagTitle"] == "Keine Reparatur möglich"
    assert row["stateText"].startswith("Nicht wiederherstellbar")
    h.repair.start_repair()  # auch Strg+Enter startet nichts
    h.app.primaryAction()
    pump(0.2)
    assert not h.repair.jobs and h.repair.result is None and not h.repair.busy
    assert not reparierte(tmp_path)


def test_encrypted_pdf_needs_the_right_password(repair_app, tmp_path: Path, config_file: Path) -> None:
    import pikepdf
    from PySide6.QtCore import QMetaObject

    h = repair_app
    geleert: list[str] = []
    h.repair.passwordCleared.connect(lambda key: geleert.append(key))
    pdf = samples.encrypted(tmp_path / "geschuetzt.pdf", password=PASSWORT)
    analysis = analyse(h, pdf)
    item = eintrag(h, pdf)
    assert analysis.condition.value == "encrypted" and item.state is ItemState.ENCRYPTED
    assert zeile(h, item)["needsPassword"] and not h.repair.canStart and not bedienbar(h, "repairStart")
    assert zeile(h, item)["stateText"] == "Passwort erforderlich"
    field = in_karte(h, item, "repairPassword")
    pump(0.45)
    assert field.property("visible")
    # Eingabe verdeckt (»•«)
    field.setProperty("text", "falsch")
    assert field.property("displayText") == "••••••"
    # Falsches Passwort (Eingabetaste im Feld)
    assert QMetaObject.invokeMethod(field, "accepted")
    wait_idle(h)
    assert item.analysis.condition.value == "encrypted" and item.analysis.password_rejected
    row = zeile(h, item)
    assert row["diagSeverity"] == "error" and row["diagText"] == "Das Passwort ist falsch. Bitte erneut eingeben."
    assert row["stateText"] == "Passwort falsch"
    assert item.key in geleert and field.property("text") == ""  # Eingabe wird nach dem Versuch geleert
    # Richtiges Passwort
    geleert.clear()
    field.setProperty("text", PASSWORT)
    assert QMetaObject.invokeMethod(field, "accepted")
    wait_idle(h)
    assert item.analysis.condition.value == "healthy"
    assert item.key in geleert and field.property("text") == ""
    assert not zeile(h, item)["needsPassword"] and h.repair.canStart and bedienbar(h, "repairStart")
    assert h.item("repairStart").property("text") == "Trotzdem neu aufbauen"
    result = repair(h)
    assert result.status.value == "repaired"
    with pikepdf.open(h.repair.output, password=PASSWORT) as out:
        assert out.is_encrypted  # die Kopie bleibt geschützt
    # Das Passwort steht nirgends: nicht in Einstellungen, Protokoll, Qt-Properties, Zeilen oder QML
    h.app.persist()
    assert PASSWORT not in config_file.read_text(encoding="utf-8")
    assert PASSWORT not in h.repair.log.path.read_text(encoding="utf-8")
    assert PASSWORT not in repr(item)
    assert not [value for value in qt_werte(h.repair) if PASSWORT in value]
    assert PASSWORT not in json.dumps(h.repair.model.items(), default=str)
    for notice in h.app.notices._areas.values():
        assert not [value for value in qt_werte(notice) if PASSWORT in value]
    assert PASSWORT not in h.app.statusText
    assert not [text for text in texte_unter(h.item("repairPage")) if PASSWORT in text]
    assert not [request for request in h.app.dialogs.history if PASSWORT in json.dumps(request, default=str)]


def test_empty_password_is_not_tried(repair_app, tmp_path: Path) -> None:
    """»Entsperren« ohne Eingabe: Hinweis an der Datei statt Analyse, das Feld bleibt leer."""
    h = repair_app
    pdf = samples.encrypted(tmp_path / "geschuetzt.pdf", password=PASSWORT)
    analyse(h, pdf)
    item = eintrag(h, pdf)
    starts = []
    h.repair._start_job = lambda *args, **kwargs: (starts.append(args), False)[1]
    h.repair.unlock(item.key, "")
    pump(0.1)
    assert starts == [] and not h.repair.busy
    assert zeile(h, item)["message"] == "Bitte das Passwort dieser PDF eingeben."
    assert in_karte(h, item, "repairItemMessage").property("text") == "Bitte das Passwort dieser PDF eingeben."
    # Strg+Enter vor dem Entsperren: Hinweis, keine Reparatur
    h.app.primaryAction()
    pump(0.1)
    assert starts == [] and h.repair.result is None
    notice = h.app.notices.get("repair_info")
    assert notice.shown and "Passwort" in notice.message


def test_signed_pdf_asks_before_repair(repair_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import dialogs

    h = repair_app
    pdf = samples.signed(tmp_path / "signiert.pdf")
    analysis = analyse(h, pdf)
    assert analysis.signatures == 1
    item = eintrag(h, pdf)
    # Die Analyse warnt vor den Signaturen
    facts = {fact["label"]: fact for fact in zeile(h, item)["facts"]}
    assert facts["Digitale Signaturen"]["tone"] == "caution" and "ungültig" in facts["Digitale Signaturen"]["value"]
    assert zeile(h, item)["signatures"] == 1
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")  # »Abbrechen«
    anfragen = len(h.app.dialogs.history)
    h.repair.start_repair()
    pump(0.2)
    assert len(h.app.dialogs.history) == anfragen + 1
    request = h.app.dialogs.history[-1]
    assert request["kind"] == "confirm" and request["title"] == presentation.SIGNATURE_TITLE
    assert request["primary"] == "Trotzdem reparieren" and request["danger"] is True
    assert "Signaturen" in request["message"]
    assert not h.repair.jobs and not h.repair.busy and h.repair.result is None
    assert not reparierte(tmp_path)
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")  # »Trotzdem reparieren«
    result = repair(h)
    assert result.status.value == "repaired"
    assert any("Signaturen" in warning for warning in result.warnings)
    # Die Warnung steht in der Karte der Datei
    assert any("Signaturen" in warning for warning in zeile(h, item)["warnings"]) and sichtbar(h, "repairResult")


def test_raster_rescue_asks_for_confirmation(repair_app, tmp_path: Path, monkeypatch) -> None:
    """Rettungsmodus (Seiten als Bilder) nur nach Bestätigung – Text- und Vektorinformationen gehen verloren."""
    from qtapp import dialogs

    h = repair_app
    pdf = samples.healthy(tmp_path / "Rettung.pdf", pages=2)
    analyse(h, pdf)
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")
    h.repair.rescue()
    pump(0.2)
    request = h.app.dialogs.history[-1]
    assert request["kind"] == "confirm" and request["title"] == presentation.RASTER_TITLE
    assert request["primary"] == presentation.RASTER_CONFIRM and request["danger"] is False
    assert "Text- und Vektorinformationen" in request["message"]
    assert not h.repair.jobs and not h.repair.busy and h.repair.result is None
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    h.repair.rescue()
    wait_idle(h)
    result = h.repair.result
    assert result is not None and result.method is not None and result.method.value == "raster"
    assert result.status.value in ("repaired", "partially_recovered")
    assert h.repair.output == tmp_path / "Rettung_repariert.pdf" and h.repair.output.is_file()
    assert sichtbar(h, "repairResult")


def test_cancel_stops_the_worker_and_leaves_no_file(repair_app, tmp_path: Path) -> None:
    h = repair_app
    pdf = samples.large(tmp_path / "gross.pdf", pages=300)
    analyse(h, pdf)
    item = eintrag(h, pdf)
    # Der Rettungsmodus rendert jede Seite einzeln – der Vorgang läuft sicher noch, wenn abgebrochen wird.
    h.repair.start_repair(RepairMode.RASTER)
    assert h.app.dialogs.history[-1]["title"] == presentation.RASTER_TITLE  # erst nach Bestätigung
    assert h.repair.busy and bedienbar(h, "repairCancel") and not bedienbar(h, "repairStart")
    job = h.repair.jobs[item.key]
    work = job.work_dir
    assert work is not None and work.is_dir()
    assert wait_until(lambda: item.stage == "raster", 60)
    klicken(h, "repairCancel")  # »Abbrechen«
    assert not h.repair.busy and not h.repair.jobs and not h.repair.running
    assert job.cancelled and not job._process.is_alive()  # Arbeitsprozess wirklich beendet
    assert not work.exists()  # Zwischendateien entfernt
    assert item.state is ItemState.CANCELLED and zeile(h, item)["stateText"] == "Abgebrochen"
    assert bedienbar(h, "repairStart") and not bedienbar(h, "repairCancel")
    notice = h.app.notices.get("repair_info")
    assert notice.shown and "abgebrochen" in notice.message
    assert h.repair.result is None and not h.repair.hasResult  # eine Datei: kein Ergebnis
    pump(0.3)
    assert not reparierte(tmp_path)


def test_ui_stays_responsive_during_repair(repair_app, tmp_path: Path) -> None:
    h = repair_app
    pdf = samples.large(tmp_path / "gross.pdf", pages=300)
    analyse(h, pdf)
    h.repair.start_repair()
    assert h.repair.busy
    longest = 0.0
    fortschritt = set()
    phasen = set()
    last = time.perf_counter()
    end = last + 120
    while h.repair.busy and time.perf_counter() < end:
        process_events()
        now = time.perf_counter()
        longest = max(longest, now - last)
        last = now
        if h.repair.busy:
            fortschritt.add(h.repair.progressText)
            phasen.add(zeile(h, eintrag(h, pdf))["phaseText"].split(" · ")[0])
        time.sleep(0.01)
    assert not h.repair.busy
    assert longest < 0.5, f"Oberfläche blockiert ({longest:.2f} s)"
    assert h.repair.result.status.value in ("healthy", "repaired")
    assert fortschritt and all(text for text in fortschritt)  # Fortschritt wurde angezeigt
    assert phasen & {"Reparatur", "Validierung"}  # Fortschritt je Datei in Schritten


def test_output_folder_is_used_and_remembered(repair_app, tmp_path: Path, config_file: Path) -> None:
    from qtapp import files

    h = repair_app
    out = tmp_path / "Ausgabe"
    out.mkdir()
    pdf = samples.xref_offset(tmp_path / "quelle" / "Vertrag.pdf")
    # »Durchsuchen« wählt den Ordner und schaltet auf »Gemeinsamer Ausgabeordner«
    files.RESPONSES.append(str(out))
    h.repair.pickOutDir()
    assert h.repair.outMode == OUT_FOLDER and h.repair.var_out_mode.get() == OUT_FOLDER
    assert h.repair.out_dir == str(out) and h.repair.outLabel == "Ausgabe" and h.repair.outPath == str(out)
    analyse(h, pdf)
    assert h.repair.outName == "Ausgabe: Vertrag_repariert.pdf"
    repair(h)
    assert h.repair.output == out / "Vertrag_repariert.pdf" and h.repair.output.is_file()
    assert not (pdf.parent / "Vertrag_repariert.pdf").exists()
    neu = neustart(h)
    assert neu.repair.var_out_mode.get() == OUT_FOLDER and neu.repair.outMode == OUT_FOLDER
    assert neu.repair.out_dir == str(out)
    assert neu.repair.source_dir == str(pdf.parent)
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["reparatur_ausgabe"] == OUT_FOLDER and data["reparatur_ordner"] == str(out)


def test_output_folder_mode_without_folder_asks_for_one(repair_app, tmp_path: Path) -> None:
    """»Gemeinsamer Ausgabeordner« ohne gewählten Ordner: deutlicher Hinweis statt eines leeren Pfads."""
    h = repair_app
    h.repair.out_dir = ""
    h.repair.setOutMode(OUT_FOLDER)
    assert h.repair.outMissing and h.repair.outLabel == "Bitte einen Ordner wählen"
    analyse(h, beschaedigt(tmp_path / "a.pdf"))
    h.repair.start_repair()
    pump(0.1)
    notice = h.app.notices.get("repair_info")
    assert notice.shown and "Ausgabeordner" in notice.message and not h.repair.jobs
    h.repair.setOutMode(OUT_ORIGINAL)
    assert not h.repair.outMissing and h.repair.outLabel == "Neben der Original-PDF"


def test_non_pdf_is_rejected(repair_app, tmp_path: Path) -> None:
    h = repair_app
    text = samples.not_pdf(tmp_path / "notiz.txt")
    assert h.app.dragEnter([text.as_uri()]) is False  # in »PDF reparieren« nur PDF-Dateien
    h.app.dragLeave()
    h.app.drop([text.as_uri()])
    notice = h.app.notices.get("repair_drop_info")
    assert h.repair.count == 0 and notice.shown and notice.severity == "warning"
    assert h.app.currentPage == "repair" and not h.repair.busy
    fake = tmp_path / "falsch.pdf"
    fake.write_bytes(text.read_bytes())
    analysis = analyse(h, fake)
    assert analysis.condition.value == "unreadable" and not analysis.looks_like_pdf
    assert not h.app.notices.get("repair_drop_info").shown  # eine PDF löst den Hinweis ab
    assert not h.repair.canStart and not bedienbar(h, "repairStart")


def test_raw_recoverable_file_offers_the_structure_rebuild(repair_app, tmp_path: Path) -> None:
    h = repair_app
    pdf = samples.real_case(tmp_path / "Vertrag März.pdf")
    before = pdf.read_bytes()
    analysis = analyse(h, pdf)
    assert analysis.condition.value == "raw_recoverable"
    item = eintrag(h, pdf)
    row = zeile(h, item)
    assert row["diagSeverity"] == "warning" and row["diagTitle"] == "Erweiterte Wiederherstellung möglich"
    assert "PDF Tool versucht, die noch vorhandenen Inhalte wiederherzustellen." in row["diagText"]
    assert "Datenströme" in row["diagText"]
    assert row["stateText"] == "Erweiterte Wiederherstellung möglich"
    assert h.repair.primaryText == "PDF-Struktur rekonstruieren" and h.repair.canStart
    assert h.item("repairStart").property("text") == "PDF-Struktur rekonstruieren" and bedienbar(h, "repairStart")
    facts = {fact["label"]: fact["value"] for fact in row["facts"]}
    assert facts["Seiten"] == "3 gefunden" and "Objektkandidaten" not in facts  # Technik nur in den Details
    details = {fact["label"]: fact["value"] for fact in row["details"]}
    assert details["Objektkandidaten"].startswith("9 gefunden") and details["Seitenobjekte (/Page)"] == "3"
    assert details["Trailer-Wörterbuch"] == "fehlt" and details["%%EOF"] == "fehlt"
    # »Technische Details anzeigen« klappt die Befunde auf (erst dann entstehen sie)
    druecken(in_karte(h, item, "repairItemDetails"))
    pump(0.45)
    assert in_karte(h, item, "repairDetails").property("visible")
    result = repair(h)
    assert result.status.value == "repaired" and result.method.value == "page_tree_rebuild"
    notice = h.app.notices.get("repair_result")
    assert notice.severity == "success" and notice.title == "PDF-Struktur wurde rekonstruiert."
    assert h.repair.output == tmp_path / "Vertrag März_repariert.pdf" and h.repair.output.is_file()
    assert pdf.read_bytes() == before
    assert zeile(h, item)["stateText"] == "Struktur rekonstruiert" and sichtbar(h, "repairResult")


# --- Teil 2: mehrere PDFs ------------------------------------------------------------------------------------


def test_pick_dialog_takes_several_files_and_more_can_be_added(repair_app, tmp_path: Path) -> None:
    from qtapp import files

    h = repair_app
    a, b, c = (beschaedigt(tmp_path / name) for name in ("A.pdf", "B.pdf", "C.pdf"))
    files.RESPONSES.append([str(a), str(b)])  # Mehrfachauswahl im Dialog
    klicken(h, "repairPick")
    wait_idle(h)
    assert h.repair.count == 2 and not h.repair.single
    assert sichtbar(h, "repairOverview") and sichtbar(h, "repairAdd") and sichtbar(h, "repairRemoveAll")
    assert h.repair.overview == "2 PDFs · 2 reparierbar" and h.repair.primaryText == "Alle reparieren (2)"
    # Später weitere hinzufügen (Schaltfläche und Ziehen und Ablegen)
    files.RESPONSES.append([str(c)])
    klicken(h, "repairAdd")
    wait_idle(h)
    assert [item.name for item in h.repair.batch.items] == ["A.pdf", "B.pdf", "C.pdf"]
    # Eintrag entfernen: die Datei bleibt unverändert
    before = c.read_bytes()
    druecken(in_karte(h, eintrag(h, c), "repairItemRemove"))
    pump(0.4)
    assert h.repair.count == 2 and c.read_bytes() == before
    klicken(h, "repairRemoveAll")
    pump(0.4)
    assert h.repair.count == 0 and sichtbar(h, "repairDrop") and a.is_file() and b.is_file()


def test_drop_several_files_once_each_and_reject_non_pdfs(repair_app, tmp_path: Path) -> None:
    h = repair_app
    a = beschaedigt(tmp_path / "A.pdf")
    b = samples.healthy(tmp_path / "B.pdf")
    note = samples.not_pdf(tmp_path / "Notiz.txt")
    uris = [a.as_uri(), b.as_uri(), a.as_uri(), note.as_uri()]
    assert h.app.dragEnter(uris) is True  # mindestens eine PDF
    assert h.repair.dropHighlight
    h.app.drop(uris)
    wait_idle(h)
    assert not h.repair.dropHighlight
    assert [item.name for item in h.repair.batch.items] == ["A.pdf", "B.pdf"]  # doppelte Datei nur einmal
    notice = h.app.notices.get("repair_drop_info")
    assert notice.shown and "Notiz.txt" in notice.message and "Bereits in der Liste: A.pdf" in notice.message
    # Dieselben Dateien noch einmal ablegen: nichts Neues, nur der Hinweis
    h.app.drop([a.as_uri(), b.as_uri()])
    pump(0.2)
    assert h.repair.count == 2 and "Bereits in der Liste" in h.app.notices.get("repair_drop_info").message


def test_mixed_batch_of_ten_pdfs_isolates_errors(repair_app, tmp_path: Path) -> None:
    """Gesunde, reparierbare, schwer beschädigte, verschlüsselte, unlesbare und rekonstruierbare
    PDFs in einer Liste: jede wird für sich analysiert, »Alle reparieren« nimmt nur die
    beschädigten, ein Fehler betrifft nur seine Datei. Originale bleiben unverändert, keine
    Arbeitsordner bleiben zurück."""
    h = repair_app
    folder = tmp_path / "Eingang"
    reparierbar = [beschaedigt(folder / f"Rechnung {n}.pdf") for n in range(1, 6)]
    gesund = samples.healthy(folder / "Gesund.pdf")
    schwer = samples.truncated(folder / "Abgeschnitten.pdf")
    verschluesselt = samples.encrypted(folder / "Geschützt.pdf", password=PASSWORT)
    unlesbar = samples.garbage(folder / "Zerstört.pdf")
    rekonstruierbar = samples.real_case(folder / "Struktur.pdf")
    paths = [*reparierbar, gesund, schwer, verschluesselt, unlesbar, rekonstruierbar]
    vorher = inhalte(paths)
    namen_vorher = set(samples.files_in(folder))
    gleichzeitig = []
    h.repair.add([str(path) for path in paths])
    while h.repair.busy:
        process_events()
        gleichzeitig.append(len(h.repair.jobs))
        time.sleep(0.01)
    wait_idle(h)
    assert max(gleichzeitig) <= 2  # nie mehr als zwei Arbeitsprozesse
    states = {item.name: item.state for item in h.repair.batch.items}
    assert states["Gesund.pdf"] is ItemState.READY and states["Zerstört.pdf"] is ItemState.UNREADABLE
    assert states["Geschützt.pdf"] is ItemState.ENCRYPTED and states["Struktur.pdf"] is ItemState.READY
    assert h.repair.overview == "10 PDFs · 7 reparierbar · 1 ohne Fehler · 1 verschlüsselt · 1 nicht wiederherstellbar"
    assert h.repair.primaryText == "Alle reparieren (7)" and h.repair.canStart
    # Kompakte Karten: Etikett und eine Zeile Erklärung
    assert zeile(h, eintrag(h, verschluesselt))["message"] == "Zum Öffnen wird ein Passwort benötigt."
    assert zeile(h, eintrag(h, unlesbar))["stateText"] == "Nicht wiederherstellbar"
    arbeitsordner = set()
    h.repair.startRepair()
    fortschritt = set()
    while h.repair.running or h.repair.busy:
        process_events()
        arbeitsordner |= {job.work_dir for job in h.repair.jobs.values() if job.work_dir is not None}
        if h.repair.running:
            fortschritt.add(h.repair.progressText)
        time.sleep(0.01)
    wait_idle(h)
    assert any(re.fullmatch(r"\d / 7 Dateien", text) for text in fortschritt)  # »3 / 7 Dateien«
    states = {item.name: item.state for item in h.repair.batch.items}
    for path in reparierbar:
        assert states[path.name] is ItemState.REPAIRED
        assert (folder / f"{path.stem}_repariert.pdf").is_file()
    assert states["Abgeschnitten.pdf"] is ItemState.PARTIALLY_RECOVERED
    assert states["Struktur.pdf"] is ItemState.REPAIRED
    assert states["Gesund.pdf"] is ItemState.READY  # keine Reparatur nötig → nicht angefasst
    assert states["Geschützt.pdf"] is ItemState.ENCRYPTED and states["Zerstört.pdf"] is ItemState.UNREADABLE
    assert not (folder / "Gesund_repariert.pdf").exists() and not (folder / "Zerstört_repariert.pdf").exists()
    # Zusammenfassung des Durchlaufs
    notice = h.app.notices.get("repair_result")
    assert notice.shown and notice.title == "Reparatur abgeschlossen" and notice.severity == "warning"
    assert h.repair.summary["lines"] == ["6 erfolgreich repariert", "1 teilweise wiederhergestellt"]
    assert sichtbar(h, "repairResult") and sichtbar(h, "repairOpenFolder") and not sichtbar(h, "repairOpen", 0)
    # Originale unverändert, keine fremden Dateien angefasst, keine Arbeitsordner übrig
    assert inhalte(paths) == vorher
    assert namen_vorher <= set(samples.files_in(folder))
    # Arbeitsordner: entfernt, sobald ihr Arbeitsprozess beendet ist (unter Windows bis zu einer Sekunde danach)
    assert arbeitsordner and wait_until(lambda: not [path for path in arbeitsordner if path.exists()], 15)


def test_cancel_at_file_four_of_ten_keeps_finished_files(repair_app, tmp_path: Path) -> None:
    h = repair_app
    folder = tmp_path / "Zehn"
    paths = [beschaedigt(folder / f"Datei {n:02}.pdf") for n in range(1, 11)]
    paths[3] = beschaedigt(folder / "Datei 04.pdf", pages=300, image=True)  # dauert lange genug für »Abbrechen«
    vorher = inhalte(paths)
    items = hinzufuegen(h, paths)
    assert h.repair.primaryText == "Alle reparieren (10)"
    h.repair.startRepair()
    vierte = items[3]
    assert wait_until(lambda: vierte.state is ItemState.REPAIRING and vierte.stage not in ("", "hash"), 120)
    job = h.repair.jobs[vierte.key]
    work = job.work_dir
    assert [item.state for item in items[:3]] == [ItemState.REPAIRED] * 3
    assert h.repair.progressText == "3 / 10 Dateien"
    klicken(h, "repairCancel")
    wait_idle(h)
    assert job.cancelled and not job._process.is_alive() and not work.exists()
    assert [item.state for item in items[:3]] == [ItemState.REPAIRED] * 3  # fertige Dateien bleiben
    assert all(item.output is not None and item.output.is_file() for item in items[:3])
    assert vierte.state is ItemState.CANCELLED and vierte.output is None
    assert "keine Datei gespeichert" in zeile(h, vierte)["message"]
    assert all(item.state is ItemState.CANCELLED and item.message == "Nicht gestartet (abgebrochen)." for item in items[4:])
    assert sorted(reparierte(folder)) == [f"Datei {n:02}_repariert.pdf" for n in (1, 2, 3)]
    notice = h.app.notices.get("repair_result")
    assert notice.title == "Reparatur abgebrochen" and notice.severity == "warning"
    assert h.repair.summary["lines"] == ["3 erfolgreich repariert", "1 abgebrochen", "6 nicht gestartet"]
    assert inhalte(paths) == vorher
    # Danach lassen sich die übrigen wieder reparieren
    assert h.repair.primaryText == "Alle reparieren (7)" and h.repair.canStart


def test_password_applies_only_to_its_own_file(repair_app, tmp_path: Path) -> None:
    h = repair_app
    erste = samples.encrypted(tmp_path / "Erste.pdf", password=PASSWORT)
    zweite = samples.encrypted(tmp_path / "Zweite.pdf", password=PASSWORT)
    eins, zwei = hinzufuegen(h, [erste, zweite])
    assert eins.state is ItemState.ENCRYPTED and zwei.state is ItemState.ENCRYPTED
    h.repair.unlock(eins.key, PASSWORT)
    wait_idle(h)
    assert eins.state is ItemState.READY and eins.analysis.condition.value == "healthy"
    assert zwei.state is ItemState.ENCRYPTED and zwei.password is None  # nicht übernommen
    assert not zwei.analysis.password_rejected  # nicht einmal versucht


def test_signed_files_can_be_skipped_in_a_batch(repair_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import dialogs

    h = repair_app
    signiert = samples.signed(tmp_path / "Signiert.pdf")
    data = re.sub(rb"startxref\s+(\d+)", lambda m: b"startxref\n" + str(int(m.group(1)) + 137).encode(), signiert.read_bytes())
    signiert.write_bytes(data)  # signiert und beschädigt
    normal = beschaedigt(tmp_path / "Normal.pdf")
    sig, nor = hinzufuegen(h, [signiert, normal])
    assert sig.signatures == 1 and sig.state is ItemState.READY and nor.state is ItemState.READY
    assert "digital signiert" in in_karte(h, sig, "repairItemCaption").property("text")
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "secondary")  # »Signierte überspringen«
    h.repair.startRepair()
    wait_idle(h)
    request = h.app.dialogs.history[-1]
    assert request["title"] == presentation.SIGNATURE_TITLE and request["primary"] == "Alle reparieren"
    assert request["secondary"] == "Signierte überspringen" and "Signiert.pdf" in request["message"]
    assert sig.state is ItemState.SKIPPED and sig.output is None and nor.state is ItemState.REPAIRED
    assert h.repair.summary["lines"] == ["1 erfolgreich repariert", "1 übersprungen"]
    assert not (tmp_path / "Signiert_repariert.pdf").exists()


def test_batch_never_rasterizes_silently(repair_app, tmp_path: Path, monkeypatch) -> None:
    """»Alle reparieren« nutzt nie den Rettungsmodus; er gilt nur für eine Datei nach Rückfrage."""
    from qtapp import dialogs

    h = repair_app
    items = hinzufuegen(h, [beschaedigt(tmp_path / "A.pdf"), samples.truncated(tmp_path / "B.pdf"), samples.garbage(tmp_path / "C.pdf")])
    modes = []
    original = process.Job

    def job(kind, request):
        if kind == "repair":
            modes.append(request["mode"])
        return original(kind, request)

    monkeypatch.setattr(process, "Job", job)
    anfragen = len(h.app.dialogs.history)
    h.repair.startRepair()
    wait_idle(h)
    assert modes and RepairMode.RASTER.value not in modes
    assert len(h.app.dialogs.history) == anfragen  # keine Rückfrage, kein Rettungsmodus
    assert items[2].state is ItemState.UNREADABLE and items[2].output is None
    # Rettungsmodus für eine Datei: nur nach Bestätigung, nur diese Datei
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")
    h.repair.rescueItem(items[1].key)
    pump(0.2)
    assert h.app.dialogs.history[-1]["title"] == presentation.RASTER_TITLE
    assert RepairMode.RASTER.value not in modes and not h.repair.running


def test_failed_file_can_be_retried_alone(repair_app, tmp_path: Path) -> None:
    h = repair_app
    a = beschaedigt(tmp_path / "A.pdf")
    b = beschaedigt(tmp_path / "B.pdf")
    eins, zwei = hinzufuegen(h, [a, b])
    gesichert = tmp_path / "gesichert.bin"
    shutil.move(b, gesichert)  # Datei verschwindet nach der Analyse: ihre Reparatur scheitert
    h.repair.startRepair()
    wait_idle(h)
    assert eins.state is ItemState.REPAIRED and zwei.state is ItemState.FAILED  # Fehler nur bei ihr
    assert h.repair.canRetry and sichtbar(h, "repairResultRetry")
    assert h.repair.summary["lines"] == ["1 erfolgreich repariert", "1 fehlgeschlagen"]
    assert zeile(h, zwei)["message"]  # verständliche Meldung an der Datei
    shutil.move(gesichert, b)
    klicken(h, "repairResultRetry")  # »Fehlgeschlagene erneut versuchen«
    wait_idle(h)
    assert zwei.state is ItemState.REPAIRED and (tmp_path / "B_repariert.pdf").is_file()
    assert eins.output == tmp_path / "A_repariert.pdf"  # die fertige wurde nicht noch einmal repariert
    assert not h.repair.canRetry
    # Nur eine Datei im Durchlauf: ihr Ergebnis mit Öffnen, Ordner öffnen und Pfad kopieren
    assert h.repair.summary["single"] and h.repair.summary["title"] == "PDF wurde repariert."
    assert sichtbar(h, "repairOpen") and not sichtbar(h, "repairOpenFolder", 0)


def test_unwritable_output_stops_the_whole_run(repair_app, tmp_path: Path, monkeypatch) -> None:
    """Kein Schreibzugriff (oder Datenträger voll): der Durchlauf hält an, statt jede Datei scheitern zu lassen."""
    h = repair_app
    items = hinzufuegen(h, [beschaedigt(tmp_path / f"{name}.pdf") for name in "ABC"])

    def deliver(*args, **kwargs):
        raise PermissionError(13, "Zugriff verweigert")

    monkeypatch.setattr(process, "deliver", deliver)
    h.repair.startRepair()
    wait_idle(h)
    assert items[0].state is ItemState.FAILED
    assert [item.state for item in items[1:]] == [ItemState.SKIPPED, ItemState.SKIPPED]
    notice = h.app.notices.get("repair_info")
    assert notice.shown and notice.title == "Reparatur angehalten"
    assert not reparierte(tmp_path)


def test_hundred_pdfs_keep_the_ui_fluid(repair_app, tmp_path: Path) -> None:
    """100 PDFs: Hinzufügen und Analyse blockieren die Oberfläche nicht; nur sichtbare Zeilen existieren."""
    h = repair_app
    vorlage = samples.healthy(tmp_path / "vorlage.pdf", pages=1)
    folder = tmp_path / "Hundert"
    folder.mkdir()
    paths = []
    for n in range(100):
        path = folder / f"Beleg {n:03}.pdf"
        shutil.copyfile(vorlage, path)
        paths.append(path)
    start = time.perf_counter()
    h.repair.add([str(path) for path in paths])
    dauer = time.perf_counter() - start
    assert dauer < 1.0, f"Hinzufügen dauerte {dauer:.2f} s"
    longest, last, gleichzeitig = 0.0, time.perf_counter(), 0
    end = last + 240
    while h.repair.busy and time.perf_counter() < end:
        process_events()
        now = time.perf_counter()
        longest = max(longest, now - last)
        last = now
        gleichzeitig = max(gleichzeitig, len(h.repair.jobs))
        time.sleep(0.005)
    wait_idle(h)
    assert longest < 0.5, f"Oberfläche blockiert ({longest:.2f} s)"
    assert gleichzeitig <= 2
    assert all(item.state is ItemState.READY for item in h.repair.batch.items)
    assert h.repair.overview == "100 PDFs · 100 ohne Fehler"
    karten = [item for item in h.item("repairList").property("contentItem").childItems() if item.objectName().startswith("repairItem_")]
    assert 0 < len(karten) < 40  # virtualisiert
    # Ende der Liste erreichbar
    letzte = karte(h, h.repair.batch.items[-1])
    assert letzte.property("visible") and zeile(h, h.repair.batch.items[-1])["name"] == "Beleg 099.pdf"


@pytest.mark.parametrize("profil", ["full", "reduced", "off"])
def test_list_animations_follow_the_motion_profile(repair_app, tmp_path: Path, profil: str) -> None:
    h = repair_app
    h.settings.setProfile(profil)
    pump(0.1)
    a, b, c = hinzufuegen(h, [beschaedigt(tmp_path / name) for name in ("A.pdf", "B.pdf", "C.pdf")])
    pump(0.6)
    for item in (a, b, c):
        card = karte(h, item)
        assert card.property("opacity") == pytest.approx(1.0) and card.property("scale") == pytest.approx(1.0)
    h.repair.remove(b.key)
    pump(0.6)
    assert h.repair.count == 2
    assert karte(h, c).property("opacity") == pytest.approx(1.0)
    # Neue Datei nach dem Entfernen: wiederverwendete Zeile ist voll sichtbar
    d = hinzufuegen(h, [beschaedigt(tmp_path / "D.pdf")])[0]
    pump(0.6)
    assert karte(h, d).property("opacity") == pytest.approx(1.0) and karte(h, d).property("scale") == pytest.approx(1.0)


def test_page_title_stays_visible_when_the_header_changes(repair_app, tmp_path: Path) -> None:
    """Wächst der Kopfbereich (erste Datei, Übersicht, Hinweise), bleibt die Seite oben; wer zu den
    Dateien gescrollt hat, behält sie im Blick."""
    h = repair_app
    liste = h.item("repairList")

    def oben() -> bool:
        return abs(liste.property("contentY") - liste.property("originY")) < 1

    hinzufuegen(h, [beschaedigt(tmp_path / "A.pdf")])
    pump(0.6)
    assert oben()
    hinzufuegen(h, [beschaedigt(tmp_path / f"{name}.pdf") for name in "BCDEFG"])  # Ausgabe wandert nach oben
    pump(0.6)
    assert oben() and sichtbar(h, "repairOverview", 0)
    h.app.notify("repair_info", "warning", "Ein Hinweis über der Liste.")
    pump(0.6)
    assert oben()
    # Zu den Dateien gescrollt: ein neuer Hinweis verschiebt die Zeilen nicht
    karte(h, h.repair.batch.items[-1])
    vorher = h.item(f"repairItem_{h.repair.batch.items[-1].key}").mapToScene(QPointF(0, 0)).y()
    h.app.hide_notice("repair_info")
    pump(0.6)
    assert not oben()
    assert h.item(f"repairItem_{h.repair.batch.items[-1].key}").mapToScene(QPointF(0, 0)).y() == pytest.approx(vorher, abs=1)


# --- Teil 3: Ausgabenamen ---------------------------------------------------------------------------------------


def test_switch_on_appends_repariert(repair_app, tmp_path: Path) -> None:
    h = repair_app
    pdf = beschaedigt(tmp_path / "Original.pdf")
    analyse(h, pdf)
    assert h.repair.appendSuffix and h.item("repairAppendSuffix").property("checked")
    assert h.repair.namingExample == "Original.pdf → Original_repariert.pdf"
    repair(h)
    assert h.repair.output == tmp_path / "Original_repariert.pdf"


def test_switch_off_same_folder_numbers_instead_of_overwriting(repair_app, tmp_path: Path) -> None:
    h = repair_app
    pdf = beschaedigt(tmp_path / "Original.pdf")
    before = pdf.read_bytes()
    analyse(h, pdf)
    item = eintrag(h, pdf)
    schalter = h.item("repairAppendSuffix")
    schalter.forceActiveFocus()
    taste(h, Qt.Key.Key_Space)  # Schalter aus (Tastatur wie ein Benutzer)
    pump(0.3)
    assert not h.repair.appendSuffix and not schalter.property("checked")
    assert h.repair.namingExample == "Original.pdf → Original.pdf"
    # Live-Vorschau: der Name wäre das Original → nummeriert
    row = zeile(h, item)
    assert row["outputBase"] == "Original" and row["outputName"] == "Original (1).pdf" and row["numbered"]
    assert h.repair.outName == "Ausgabe: Original (1).pdf"
    assert not sichtbar(h, "repairSuffix")  # Zusatz nur mit eingeschaltetem Schalter
    repair(h)
    assert h.repair.output == tmp_path / "Original (1).pdf"
    assert pdf.read_bytes() == before  # das Original wurde nicht überschrieben


def test_switch_off_other_folder_keeps_the_name(repair_app, tmp_path: Path) -> None:
    from qtapp import files

    h = repair_app
    out = tmp_path / "Leer"
    out.mkdir()
    pdf = beschaedigt(tmp_path / "Quelle" / "Original.pdf")
    files.RESPONSES.append(str(out))
    h.repair.pickOutDir()
    h.repair.setAppendSuffix(False)
    analyse(h, pdf)
    assert h.repair.outName == "Ausgabe: Original.pdf"
    repair(h)
    assert h.repair.output == out / "Original.pdf"


def test_custom_name_with_validation_and_reset(repair_app, tmp_path: Path) -> None:
    h = repair_app
    pdf = beschaedigt(tmp_path / "Scan_0042.pdf")
    analyse(h, pdf)
    item = eintrag(h, pdf)
    feld = in_karte(h, item, "repairOutputName")
    # Ungültige Namen: Hinweis direkt am Feld, Reparatur gesperrt
    for eingabe, teil in (("Kunden:vertrag", "Nicht erlaubt"), ("CON", "reservierter Name"), ("", "Bitte einen Dateinamen"), ("Vertrag.", "Punkt oder Leerzeichen")):
        h.repair.setOutputName(item.key, eingabe)
        pump(0.05)
        row = zeile(h, item)
        assert teil in row["nameError"], (eingabe, row["nameError"])
        assert feld.property("invalid") and in_karte(h, item, "repairOutputNote").property("text") == row["nameError"]
        h.repair.start_repair()
        pump(0.05)
        assert not h.repair.jobs and "Ausgabenamen" in h.app.notices.get("repair_info").message
    # Eigener Name (».pdf« wird ergänzt, auch wenn mit eingegeben)
    h.repair.setOutputName(item.key, "Kundenvertrag.pdf")
    row = zeile(h, item)
    assert row["nameError"] == "" and row["nameManual"] and row["outputName"] == "Kundenvertrag.pdf"
    assert in_karte(h, item, "repairOutputReset").property("visible")
    # Der Schalter überschreibt eigene Namen nicht
    h.repair.setAppendSuffix(False)
    h.repair.setAppendSuffix(True)
    assert zeile(h, item)["outputName"] == "Kundenvertrag.pdf"
    # »Automatischen Namen wiederherstellen«
    druecken(in_karte(h, item, "repairOutputReset"))
    assert zeile(h, item)["outputName"] == "Scan_0042_repariert.pdf" and not zeile(h, item)["nameManual"]
    h.repair.setOutputName(item.key, "Kundenvertrag")
    repair(h)
    assert h.repair.output == tmp_path / "Kundenvertrag.pdf"


def test_custom_suffix_applies_to_all_automatic_names(repair_app, tmp_path: Path) -> None:
    h = repair_app
    a, b = hinzufuegen(h, [beschaedigt(tmp_path / "A.pdf"), beschaedigt(tmp_path / "B.pdf")])
    h.repair.setOutputName(b.key, "Eigener Name")
    h.repair.setSuffix("_gefixt")
    assert zeile(h, a)["outputName"] == "A_gefixt.pdf" and zeile(h, b)["outputName"] == "Eigener Name.pdf"
    h.repair.setSuffix("_a/b")
    assert "Nicht erlaubt" in h.repair.suffixError and h.repair.suffix == "_gefixt"  # letzter gültiger bleibt
    h.repair.setSuffix("_gefixt")
    assert h.repair.suffixError == ""
    h.repair.startRepair()
    wait_idle(h)
    assert (tmp_path / "A_gefixt.pdf").is_file() and (tmp_path / "Eigener Name.pdf").is_file()


def test_same_names_from_different_folders_into_one_folder(repair_app, tmp_path: Path) -> None:
    """Gleich benannte PDFs aus zwei Ordnern in einen gemeinsamen Ordner, in dem es den Namen schon gibt
    (anders geschrieben): eindeutige Namen ohne Rücksicht auf Groß-/Kleinschreibung, nichts überschrieben."""
    from qtapp import files

    h = repair_app
    out = tmp_path / "Ausgabe"
    out.mkdir()
    vorhanden = out / "vertrag_REPARIERT.pdf"
    vorhanden.write_bytes(b"%PDF-1.4 vorhanden")
    erste = beschaedigt(tmp_path / "Kunde A" / "Vertrag.pdf")
    zweite = beschaedigt(tmp_path / "Kunde B" / "Vertrag.pdf")
    files.RESPONSES.append(str(out))
    h.repair.pickOutDir()
    eins, zwei = hinzufuegen(h, [erste, zweite])
    assert zeile(h, eins)["outputName"] == "Vertrag_repariert (1).pdf"
    assert zeile(h, zwei)["outputName"] == "Vertrag_repariert (2).pdf"
    h.repair.startRepair()
    wait_idle(h)
    assert eins.output == out / "Vertrag_repariert (1).pdf" and zwei.output == out / "Vertrag_repariert (2).pdf"
    assert vorhanden.read_bytes() == b"%PDF-1.4 vorhanden"


def test_names_are_reserved_when_the_run_starts(repair_app, tmp_path: Path) -> None:
    """Entsteht der geplante Name nach der Planung (z. B. durch ein anderes Programm), wird beim Start
    neu geplant; beim Speichern wird eine vorhandene Datei nie überschrieben."""
    h = repair_app
    a, b = hinzufuegen(h, [beschaedigt(tmp_path / "A.pdf"), beschaedigt(tmp_path / "B.pdf")])
    assert zeile(h, a)["outputName"] == "A_repariert.pdf"
    fremd = tmp_path / "A_repariert.pdf"
    fremd.write_bytes(b"fremd")
    h.repair.startRepair()
    wait_idle(h)
    assert a.output == tmp_path / "A_repariert (1).pdf" and fremd.read_bytes() == b"fremd"
    assert b.output == tmp_path / "B_repariert.pdf"


def test_switch_and_suffix_survive_restart(repair_app, config_file: Path) -> None:
    h = repair_app
    h.repair.setAppendSuffix(False)
    h.repair.setSuffix("_gefixt")
    neu = neustart(h)
    assert not neu.repair.appendSuffix and neu.repair.suffix == "_gefixt"
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["reparatur_anhaengen"] is False and data["reparatur_zusatz"] == "_gefixt"


def test_missing_switch_setting_defaults_to_on(repair_app, config_file: Path) -> None:
    """Update von 2.7.0: Die Einstellung fehlt – es gilt das bisherige Verhalten (»_repariert«)."""
    from qtutil import Harness

    h = repair_app
    h.holder["current"].close()  # speichert wie beim Beenden
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["reparatur_anhaengen"] is True
    data.pop("reparatur_anhaengen")
    data.pop("reparatur_zusatz")
    config_file.write_text(json.dumps(data), encoding="utf-8")
    neu = Harness(ui=False)
    h.holder["current"] = neu
    assert neu.repair.appendSuffix and neu.repair.suffix == "_repariert"
