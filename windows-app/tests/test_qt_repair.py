"""Qt-Oberfläche: Werkzeug »PDF reparieren« (2.7.0).

Ersetzt die Tk-Tests des Werkzeugs aus test_app_v23 (Reparatur, Teilrettung, unlesbare,
verschlüsselte und signierte PDFs, Abbrechen, flüssige Oberfläche, Ausgabeordner, keine PDF)
und aus test_app_v26 (erweiterte Wiederherstellung). Die App läuft mit QML im Fenster
(offscreen); geprüft werden der ``RepairController`` (in QML: ``Repair``) und die Karten der
Seite (``repairAnalysis``, ``repairResult``). Nach jedem Test darf die QML-Engine keine Warnung
gemeldet haben.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import pdfsamples as samples
from conftest import neustart, pump, wait_until
from qtutil import process_events

from tools.pdf_repair import presentation
from tools.pdf_repair.models import RepairMode
from tools.pdf_repair.presentation import OUT_FOLDER

PASSWORT = "Geheim-123"


@pytest.fixture
def repair_app(ui_app, tmp_path: Path):
    """App mit Oberfläche, Ansicht »PDF reparieren«, Protokoll im Testordner."""
    ui_app.repair.log.path = tmp_path / "protokoll" / "pdf-repair.log"
    ui_app.navigate("repair", 0.3)
    assert ui_app.app.currentPage == "repair"
    return ui_app


def wait_idle(h, timeout: float = 90.0) -> None:
    assert wait_until(lambda: not h.repair.busy, timeout), "Vorgang wurde nicht beendet"
    pump(0.1)


def analyse(h, path: Path):
    h.repair.use(str(path))
    wait_idle(h)
    assert h.repair.analysis is not None
    return h.repair.analysis


def repair(h, mode=None):
    h.repair.start_repair(mode)
    wait_idle(h)
    return h.repair.result


def sichtbar(h, name: str, settle: float = 0.45) -> bool:
    """Ist das QML-Element (z. B. die Karte »Analyse«) nach dem Auf-/Zuklappen sichtbar?"""
    pump(settle)
    item = h.item(name)
    assert item is not None, f"QML-Element {name} fehlt"
    return bool(item.property("visible"))


def bedienbar(h, name: str) -> bool:
    item = h.item(name)
    assert item is not None, f"QML-Element {name} fehlt"
    return bool(item.property("enabled"))


def klicken(h, name: str) -> None:
    """Schaltfläche in QML auslösen – ihr ``onClicked`` läuft wie bei einem Klick."""
    from PySide6.QtCore import QMetaObject

    assert bedienbar(h, name), f"{name} ist nicht bedienbar"
    assert QMetaObject.invokeMethod(h.item(name), "clicked")
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


# --- Reparatur ----------------------------------------------------------------------------------------


def test_repair_flow_saves_next_to_original(repair_app, tmp_path: Path) -> None:
    from qtapp import files

    h = repair_app
    folder = tmp_path / "Benutzer" / "Jérôme" / "Übersichten"
    pdf = samples.xref_offset(folder / "Rechnung März.pdf")
    before = pdf.read_bytes()
    assert not sichtbar(h, "repairAnalysis", 0) and not sichtbar(h, "repairResult", 0)
    analysis = analyse(h, pdf)
    assert analysis.condition.value == "repairable" and h.repair.condition == "repairable"
    # Karte »Analyse« aufgeklappt, »PDF reparieren« bedienbar
    assert h.repair.hasFile and h.repair.analyzed and h.repair.canRepair
    assert sichtbar(h, "repairAnalysis") and bedienbar(h, "repairStart") and not bedienbar(h, "repairCancel")
    assert h.repair.fileName == "Rechnung März.pdf"
    assert "Rechnung März_repariert.pdf" in h.repair.outName
    assert h.item("repairOutName").property("text") == h.repair.outName
    # »PDF reparieren« (Klick in QML)
    klicken(h, "repairStart")
    wait_idle(h)
    result = h.repair.result
    assert result is not None and result.status.value == "repaired"
    target = folder / "Rechnung März_repariert.pdf"
    assert h.repair.output == target and target.is_file()
    assert pdf.read_bytes() == before  # Original unverändert
    assert "Rechnung März_repariert_2.pdf" in h.repair.outName  # Vorschau: nächster freier Name
    assert h.item("repairOutName").property("text") == h.repair.outName
    # Karte »Ergebnis« mit Öffnen, Ordner öffnen und Pfad kopieren
    assert h.repair.hasResult and h.repair.hasOutput and sichtbar(h, "repairResult")
    notice = h.app.notices.get("repair_result")
    assert notice.shown and notice.severity == "success" and notice.title == "PDF wurde repariert."
    facts = {fact["label"]: fact["value"] for fact in h.repair.resultFacts}
    assert facts["Ausgabedatei"] == "Rechnung März_repariert.pdf" and facts["Ordner"] == str(folder)
    klicken(h, "repairOpen")
    assert files.OPENED[-1] == str(target)
    h.repair.copyOutputPath()  # »Pfad kopieren«
    assert zwischenablage() == str(target)
    # zweiter Durchlauf: neuer Name, nichts wird überschrieben
    analyse(h, pdf)
    assert not h.repair.hasResult  # neue Datei: altes Ergebnis verschwindet
    repair(h)
    assert h.repair.output == folder / "Rechnung März_repariert_2.pdf"
    assert target.is_file() and pdf.read_bytes() == before
    # »Weitere PDF reparieren« leert den Zustand
    klicken(h, "repairAgain")
    assert h.repair.path is None and h.repair.analysis is None and h.repair.result is None
    assert not h.repair.hasResult and not h.repair.hasFile and not h.repair.analyzed
    assert not sichtbar(h, "repairResult") and not sichtbar(h, "repairAnalysis")
    assert h.repair.outName == presentation.OUT_NAME_EMPTY
    log = h.repair.log.path.read_text(encoding="utf-8")
    assert "Rechnung März.pdf" in log and str(folder) not in log  # keine vollständigen Pfade


def test_partial_recovery_is_labelled(repair_app, tmp_path: Path) -> None:
    h = repair_app
    analysis = analyse(h, samples.truncated(tmp_path / "abgeschnitten.pdf"))
    assert analysis.condition.value == "damaged"
    assert h.app.notices.get("repair_analysis").severity == "warning"
    result = repair(h)
    assert result.status.value == "partially_recovered"
    notice = h.app.notices.get("repair_result")
    assert notice.shown and notice.severity == "warning" and "Seiten" in notice.message
    assert notice.title == "PDF teilweise wiederhergestellt"
    assert h.repair.output is not None and h.repair.output.name == "abgeschnitten_repariert.pdf"
    assert h.repair.hasOutput and sichtbar(h, "repairResult")


def test_unreadable_file_cannot_be_repaired(repair_app, tmp_path: Path) -> None:
    h = repair_app
    analysis = analyse(h, samples.garbage(tmp_path / "zerstoert.pdf"))
    assert analysis.condition.value == "unreadable"
    assert not h.repair.canRepair and sichtbar(h, "repairAnalysis") and not bedienbar(h, "repairStart")
    notice = h.app.notices.get("repair_analysis")
    assert notice.shown and notice.severity == "error" and notice.title == "Keine Reparatur möglich"
    h.repair.start_repair()  # auch Strg+Enter startet nichts
    h.app.primaryAction()
    pump(0.2)
    assert h.repair.job is None and h.repair.result is None and not h.repair.busy
    assert not [name for name in samples.files_in(tmp_path) if "repariert" in name]


def test_encrypted_pdf_needs_the_right_password(repair_app, tmp_path: Path, config_file: Path) -> None:
    import pikepdf
    from PySide6.QtCore import QMetaObject

    h = repair_app
    geleert: list[bool] = []
    h.repair.passwordCleared.connect(lambda: geleert.append(True))
    pdf = samples.encrypted(tmp_path / "geschuetzt.pdf", password=PASSWORT)
    analysis = analyse(h, pdf)
    assert analysis.condition.value == "encrypted"
    assert h.repair.needsPassword and not h.repair.canRepair and not bedienbar(h, "repairStart")
    field = h.item("repairPassword")
    assert sichtbar(h, "repairPassword")
    # Eingabe verdeckt (»•«)
    field.setProperty("text", "falsch")
    assert field.property("displayText") == "••••••"
    # Falsches Passwort (Eingabetaste im Feld)
    vorher = len(geleert)
    assert QMetaObject.invokeMethod(field, "accepted")
    wait_idle(h)
    assert h.repair.analysis.condition.value == "encrypted" and h.repair.analysis.password_rejected
    notice = h.app.notices.get("repair_analysis")
    assert notice.severity == "error" and notice.message == "Das Passwort ist falsch. Bitte erneut eingeben."
    assert len(geleert) > vorher and field.property("text") == ""  # Eingabe wird nach dem Versuch geleert
    # Richtiges Passwort
    vorher = len(geleert)
    field.setProperty("text", PASSWORT)
    assert QMetaObject.invokeMethod(field, "accepted")
    wait_idle(h)
    assert h.repair.analysis.condition.value == "healthy"
    assert len(geleert) > vorher and field.property("text") == ""
    assert not h.repair.needsPassword and h.repair.canRepair and bedienbar(h, "repairStart")
    result = repair(h)
    assert result.status.value == "repaired"
    with pikepdf.open(h.repair.output, password=PASSWORT) as out:
        assert out.is_encrypted  # die Kopie bleibt geschützt
    # Das Passwort steht nirgends: nicht in Einstellungen, Protokoll, Qt-Properties oder QML
    h.app.persist()
    assert PASSWORT not in config_file.read_text(encoding="utf-8")
    assert PASSWORT not in h.repair.log.path.read_text(encoding="utf-8")
    assert not [value for value in qt_werte(h.repair) if PASSWORT in value]
    for notice in h.app.notices._areas.values():
        assert not [value for value in qt_werte(notice) if PASSWORT in value]
    assert PASSWORT not in h.app.statusText
    assert not [text for text in texte_unter(h.item("repairPage")) if PASSWORT in text]
    assert not [request for request in h.app.dialogs.history if PASSWORT in json.dumps(request, default=str)]


def test_empty_password_is_not_tried(repair_app, tmp_path: Path) -> None:
    """»Entsperren« ohne Eingabe: Hinweis statt Analyse, das Feld bleibt leer."""
    h = repair_app
    analyse(h, samples.encrypted(tmp_path / "geschuetzt.pdf", password=PASSWORT))
    runs = []
    original = h.repair.analyze
    h.repair.analyze = lambda: (runs.append(True), original())[1]
    h.repair.unlock("")
    pump(0.1)
    assert runs == [] and not h.repair.busy
    notice = h.app.notices.get("repair_info")
    assert notice.shown and notice.severity == "warning" and "Passwort" in notice.message
    # Strg+Enter vor dem Entsperren: Hinweis, keine Reparatur
    h.app.primaryAction()
    pump(0.1)
    assert h.repair.job is None and h.repair.result is None
    assert "Passwort" in h.app.notices.get("repair_info").message


def test_signed_pdf_asks_before_repair(repair_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import dialogs

    h = repair_app
    pdf = samples.signed(tmp_path / "signiert.pdf")
    analysis = analyse(h, pdf)
    assert analysis.signatures == 1
    # Die Analyse warnt vor den Signaturen
    facts = {fact["label"]: fact for fact in h.repair.facts}
    assert facts["Digitale Signaturen"]["tone"] == "caution" and "ungültig" in facts["Digitale Signaturen"]["value"]
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")  # »Abbrechen«
    anfragen = len(h.app.dialogs.history)
    h.repair.start_repair()
    pump(0.2)
    assert len(h.app.dialogs.history) == anfragen + 1
    request = h.app.dialogs.history[-1]
    assert request["kind"] == "confirm" and request["title"] == presentation.SIGNATURE_TITLE
    assert request["primary"] == "Trotzdem reparieren" and request["danger"] is True
    assert "Signaturen" in request["message"]
    assert h.repair.job is None and not h.repair.busy and h.repair.result is None
    assert not [name for name in samples.files_in(tmp_path) if "repariert" in name]
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")  # »Trotzdem reparieren«
    result = repair(h)
    assert result.status.value == "repaired"
    assert any("Signaturen" in warning for warning in result.warnings)
    # Die Warnung steht in der Karte »Ergebnis«
    assert any("Signaturen" in warning for warning in h.repair.resultWarnings) and sichtbar(h, "repairResult")


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
    assert h.repair.job is None and not h.repair.busy and h.repair.result is None
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
    # Der Rettungsmodus rendert jede Seite einzeln – der Vorgang läuft sicher noch, wenn abgebrochen wird.
    h.repair.start_repair(RepairMode.RASTER)
    assert h.app.dialogs.history[-1]["title"] == presentation.RASTER_TITLE  # erst nach Bestätigung
    assert h.repair.busy and bedienbar(h, "repairCancel") and not bedienbar(h, "repairStart")
    job = h.repair.job
    work = job.work_dir
    assert work is not None and work.is_dir()
    assert wait_until(lambda: h.repair.stage == "raster", 60)
    klicken(h, "repairCancel")  # »Abbrechen«
    assert not h.repair.busy and h.repair.job is None
    assert job.cancelled and not job._process.is_alive()  # Arbeitsprozess wirklich beendet
    assert not work.exists()  # Zwischendateien entfernt
    assert bedienbar(h, "repairStart") and not bedienbar(h, "repairCancel")
    notice = h.app.notices.get("repair_info")
    assert notice.shown and "abgebrochen" in notice.message
    assert h.repair.result is None and not h.repair.hasResult
    pump(0.3)
    assert not [name for name in samples.files_in(tmp_path) if "repariert" in name]


def test_ui_stays_responsive_during_repair(repair_app, tmp_path: Path) -> None:
    h = repair_app
    pdf = samples.large(tmp_path / "gross.pdf", pages=300)
    analyse(h, pdf)
    h.repair.start_repair()
    assert h.repair.busy
    longest = 0.0
    fortschritt = set()
    last = time.perf_counter()
    end = last + 120
    while h.repair.busy and time.perf_counter() < end:
        process_events()
        now = time.perf_counter()
        longest = max(longest, now - last)
        last = now
        if h.repair.busy:
            fortschritt.add(h.repair.progressText)
        time.sleep(0.01)
    assert not h.repair.busy
    assert longest < 0.5, f"Oberfläche blockiert ({longest:.2f} s)"
    assert h.repair.result.status.value in ("healthy", "repaired")
    assert fortschritt and all(text for text in fortschritt)  # Fortschritt wurde angezeigt


def test_output_folder_is_used_and_remembered(repair_app, tmp_path: Path, config_file: Path) -> None:
    from qtapp import files

    h = repair_app
    out = tmp_path / "Ausgabe"
    out.mkdir()
    pdf = samples.xref_offset(tmp_path / "quelle" / "Vertrag.pdf")
    # »Durchsuchen« wählt den Ordner und schaltet auf »Anderer Ordner«
    files.RESPONSES.append(str(out))
    h.repair.pickOutDir()
    assert h.repair.outMode == OUT_FOLDER and h.repair.var_out_mode.get() == OUT_FOLDER
    assert h.repair.out_dir == str(out) and h.repair.outLabel == "Ausgabe" and h.repair.outPath == str(out)
    analyse(h, pdf)
    assert "Vertrag_repariert.pdf" in h.repair.outName
    repair(h)
    assert h.repair.output == out / "Vertrag_repariert.pdf" and h.repair.output.is_file()
    assert not (pdf.parent / "Vertrag_repariert.pdf").exists()
    neu = neustart(h)
    assert neu.repair.var_out_mode.get() == OUT_FOLDER and neu.repair.outMode == OUT_FOLDER
    assert neu.repair.out_dir == str(out)
    assert neu.repair.source_dir == str(pdf.parent)
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["reparatur_ausgabe"] == OUT_FOLDER and data["reparatur_ordner"] == str(out)


def test_output_folder_mode_without_folder_asks_for_one(repair_app) -> None:
    """»Anderer Ordner« ohne gewählten Ordner: deutlicher Hinweis statt eines leeren Pfads."""
    from tools.pdf_repair.presentation import OUT_ORIGINAL

    h = repair_app
    h.repair.out_dir = ""
    h.repair.setOutMode(OUT_FOLDER)
    assert h.repair.outMissing and h.repair.outLabel == "Bitte einen Ordner wählen"
    h.repair.setOutMode(OUT_ORIGINAL)
    assert not h.repair.outMissing and h.repair.outLabel == "Neben der Original-PDF"


def test_non_pdf_is_rejected(repair_app, tmp_path: Path) -> None:
    h = repair_app
    text = samples.not_pdf(tmp_path / "notiz.txt")
    assert h.app.dragEnter([text.as_uri()]) is False  # in »PDF reparieren« nur PDF-Dateien
    h.app.dragLeave()
    h.app.drop([text.as_uri()])
    notice = h.app.notices.get("repair_drop_info")
    assert h.repair.path is None and notice.shown and notice.severity == "warning"
    assert h.app.currentPage == "repair" and not h.repair.busy
    fake = tmp_path / "falsch.pdf"
    fake.write_bytes(text.read_bytes())
    analysis = analyse(h, fake)
    assert analysis.condition.value == "unreadable" and not analysis.looks_like_pdf
    assert not h.app.notices.get("repair_drop_info").shown  # eine PDF löst den Hinweis ab
    assert not h.repair.canRepair and not bedienbar(h, "repairStart")


# --- Erweiterte Wiederherstellung (2.6) -----------------------------------------------------------------------


def test_raw_recoverable_file_offers_the_structure_rebuild(repair_app, tmp_path: Path) -> None:
    h = repair_app
    pdf = samples.real_case(tmp_path / "Vertrag März.pdf")
    before = pdf.read_bytes()
    h.repair.use(str(pdf))
    assert wait_until(lambda: not h.repair.busy and h.repair.analysis is not None, 90)
    pump(0.2)
    analysis = h.repair.analysis
    assert analysis.condition.value == "raw_recoverable"
    notice = h.app.notices.get("repair_analysis")
    assert notice.shown and notice.severity == "warning" and notice.title == "Erweiterte Wiederherstellung möglich"
    assert "PDF Tool versucht, die noch vorhandenen Inhalte wiederherzustellen." in notice.message
    assert "Datenströme" in notice.message
    assert h.repair.repairText == "PDF-Struktur rekonstruieren" and h.repair.canRepair
    assert h.item("repairStart").property("text") == "PDF-Struktur rekonstruieren" and bedienbar(h, "repairStart")
    facts = {fact["label"]: fact["value"] for fact in h.repair.facts}
    assert facts["Seiten"] == "3 gefunden" and "Objektkandidaten" not in facts  # Technik nur in den Details
    details = {fact["label"]: fact["value"] for fact in h.repair.details}
    assert details["Objektkandidaten"].startswith("9 gefunden") and details["Seitenobjekte (/Page)"] == "3"
    assert details["Trailer-Wörterbuch"] == "fehlt" and details["%%EOF"] == "fehlt"
    assert sichtbar(h, "repairAnalysis")
    h.repair.start_repair()
    assert wait_until(lambda: not h.repair.busy and h.repair.result is not None, 120)
    pump(0.2)
    result = h.repair.result
    assert result.status.value == "repaired" and result.method.value == "page_tree_rebuild"
    notice = h.app.notices.get("repair_result")
    assert notice.severity == "success" and notice.title == "PDF-Struktur wurde rekonstruiert."
    assert h.repair.output == tmp_path / "Vertrag März_repariert.pdf" and h.repair.output.is_file()
    assert pdf.read_bytes() == before
    assert sichtbar(h, "repairResult")
