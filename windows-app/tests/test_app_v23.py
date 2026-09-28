"""Oberflächentests für Version 2.3: Startseite, Werkzeug-Navigation und »PDF reparieren«."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import pdfsamples as samples
from tools.pdf_repair.models import RepairMode
from conftest import display_available, neustart, pump, schliessen, wait_until

pytestmark = pytest.mark.skipif(not display_available(), reason="kein Display verfügbar")


@pytest.fixture
def repair_app(config_file: Path, tmp_path: Path, monkeypatch):
    """App ohne Animationen, Protokoll im Testordner."""
    import appstate

    config_file.write_text(json.dumps({"gesehen": appstate.VERSION, "theme": "light"}), encoding="utf-8")
    monkeypatch.setenv("UE_NO_ANIMATIONS", "1")
    from ui import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    import vertragdesk

    instance = vertragdesk.App()
    instance.ctx.anim.enabled = False
    instance.repair.log.path = tmp_path / "protokoll" / "pdf-repair.log"
    pump(instance, 0.3)
    yield instance
    schliessen(instance)


def wait_idle(app, timeout: float = 90.0) -> None:
    assert wait_until(app, lambda: not app.repair.busy, timeout), "Vorgang wurde nicht beendet"
    pump(app, 0.1)


def analyse(app, path: Path):
    app.repair.use(str(path))
    wait_idle(app)
    assert app.repair.analysis is not None
    return app.repair.analysis


def repair(app, mode=None):
    app.repair.start_repair(mode)
    wait_idle(app)
    return app.repair.result


# --- Startseite und Navigation ----------------------------------------------------------------


def test_start_page_shows_tool_cards(app) -> None:
    assert app.nav.current == "home"
    assert app.title() == "PDF Tool"
    assert set(app.ui.tool_cards) == {"contracts", "repair"}
    app.ui.tool_cards["repair"].button.invoke()
    pump(app, 0.4)
    assert app.nav.current == "repair" and app.nav.pane.selected == "repair"
    app.open_tool("home")
    pump(app, 0.4)
    app.ui.tool_cards["contracts"].button.invoke()
    pump(app, 0.4)
    assert app.nav.current == "create" and app.nav.pane.selected == "contracts"


def test_shortcuts_open_tools(app) -> None:
    app.focus_force()
    pump(app, 0.2)
    for number, page in ((2, "create"), (3, "repair"), (4, "settings"), (1, "home")):
        app.event_generate(f"<Control-Key-{number}>")
        pump(app, 0.4)
        assert app.nav.current == page


def test_tool_remembers_its_last_view(app) -> None:
    app.open_tool("contracts")
    pump(app, 0.3)
    app.ui.selector_create._activate("layout")  # SelectorBar »Darstellung«
    pump(app, 0.4)
    assert app.nav.current == "layout"
    assert app.nav.pane.selected == "contracts"  # Navigationseintrag bleibt das Werkzeug
    assert app.ui.selector_layout.selected == "layout"
    app.open_tool("repair")
    pump(app, 0.3)
    app.open_tool("contracts")
    pump(app, 0.3)
    assert app.nav.current == "layout"
    app.ui.selector_layout._activate("create")
    pump(app, 0.3)
    assert app.nav.current == "create" and app.ui.selector_create.selected == "create"


def test_settings_contain_only_global_options(app) -> None:
    from ui.pages import settings

    source = Path(settings.__file__).read_text(encoding="utf-8")
    for tool_setting in ("Verlauf löschen", "Excel", "Kundennummer", "clear_history", "var_excel", "var_out_mode", "app.repair"):
        assert tool_setting not in source
    # Tool-Einstellungen liegen im Werkzeug
    assert app.ui.daten_info.winfo_toplevel() is app


def test_status_hint_follows_the_tool(app) -> None:
    from tools.pdf_repair import page as repair_page

    app.open_tool("repair")
    pump(app, 0.3)
    assert app.nav.status.hint_text == repair_page.HINT
    app.open_tool("home")
    pump(app, 0.3)
    assert "Strg+3" in app.nav.status.hint_text


def test_drop_on_start_page_routes_by_file_type(repair_app, excel_file: Path, tmp_path: Path) -> None:
    app = repair_app
    pdf = samples.healthy(tmp_path / "eingang" / "Rechnung.pdf", pages=2)
    assert app._accepts_drop([str(pdf)]) and app._accepts_drop([str(excel_file)])
    assert not app._accepts_drop([str(tmp_path / "bild.png")])
    app._on_drop([str(pdf)])
    pump(app, 0.3)
    assert app.nav.current == "repair"
    wait_idle(app)
    assert app.repair.analysis is not None and app.repair.analysis.page_count == 2
    # Im Werkzeug »PDF reparieren« wird keine Excel-Liste angenommen …
    assert not app._accepts_drop([str(excel_file)])
    # … und in »Vertragsübersichten« keine PDF.
    app.open_tool("contracts")
    pump(app, 0.3)
    assert not app._accepts_drop([str(pdf)])
    app.open_tool("home")
    pump(app, 0.3)
    app._on_drop([str(excel_file)])
    pump(app, 0.3)
    assert app.nav.current == "create"
    assert app.var_excel.get() == str(excel_file)


# --- PDF reparieren ---------------------------------------------------------------------------


def test_repair_flow_saves_next_to_original(repair_app, tmp_path: Path) -> None:
    app = repair_app
    folder = tmp_path / "Benutzer" / "Jérôme" / "Übersichten"
    pdf = samples.xref_offset(folder / "Rechnung März.pdf")
    before = pdf.read_bytes()
    app.open_tool("repair")
    analysis = analyse(app, pdf)
    ui = app.repair.ui
    assert analysis.condition.value == "repairable"
    assert ui.analysis_area.expanded and ui.btn_repair.enabled()
    assert "Rechnung März_repariert.pdf" in ui.out_name.cget("text")
    result = repair(app)
    assert result.status.value == "repaired"
    target = folder / "Rechnung März_repariert.pdf"
    assert app.repair.output == target and target.is_file()
    assert pdf.read_bytes() == before  # Original unverändert
    assert "Rechnung März_repariert_2.pdf" in ui.out_name.cget("text")  # Vorschau: nächster freier Name
    assert ui.result_area.expanded and ui.btn_open.enabled() and ui.btn_copy.enabled()
    ui.btn_copy.invoke()
    assert app.clipboard_get() == str(target)
    # zweiter Durchlauf: neuer Name, nichts wird überschrieben
    analyse(app, pdf)
    repair(app)
    assert app.repair.output == folder / "Rechnung März_repariert_2.pdf"
    # »Weitere PDF reparieren« leert den Zustand
    app.repair.reset()
    pump(app, 0.2)
    assert app.repair.path is None and not ui.result_area.expanded and not ui.analysis_area.expanded
    log = app.repair.log.path.read_text(encoding="utf-8")
    assert "Rechnung März.pdf" in log and str(folder) not in log  # keine vollständigen Pfade


def test_partial_recovery_is_labelled(repair_app, tmp_path: Path) -> None:
    app = repair_app
    analysis = analyse(app, samples.truncated(tmp_path / "abgeschnitten.pdf"))
    assert analysis.condition.value == "damaged"
    result = repair(app)
    assert result.status.value == "partially_recovered"
    ui = app.repair.ui
    assert ui.result_info.severity == "warning" and "Seiten" in ui.result_info.message
    assert app.repair.output is not None and app.repair.output.name == "abgeschnitten_repariert.pdf"


def test_unreadable_file_cannot_be_repaired(repair_app, tmp_path: Path) -> None:
    app = repair_app
    analysis = analyse(app, samples.garbage(tmp_path / "zerstoert.pdf"))
    assert analysis.condition.value == "unreadable"
    assert not app.repair.ui.btn_repair.enabled()
    assert app.repair.ui.analysis_info.severity == "error"
    app.repair.start_repair()
    assert app.repair.job is None and app.repair.result is None
    assert not [name for name in samples.files_in(tmp_path) if "repariert" in name]


def test_encrypted_pdf_needs_the_right_password(repair_app, tmp_path: Path, config_file: Path) -> None:
    app = repair_app
    pdf = samples.encrypted(tmp_path / "geschuetzt.pdf", password="Geheim-123")
    analysis = analyse(app, pdf)
    ui = app.repair.ui
    assert analysis.condition.value == "encrypted"
    assert ui.password_area.expanded and not ui.btn_repair.enabled()
    assert ui.field_password.entry.cget("show") == "•"
    app.repair.var_password.set("falsch")
    app.repair.unlock()
    wait_idle(app)
    assert app.repair.analysis.condition.value == "encrypted" and app.repair.analysis.password_rejected
    assert app.repair.var_password.get() == ""  # Eingabe wird nach dem Versuch geleert
    app.repair.var_password.set("Geheim-123")
    app.repair.unlock()
    wait_idle(app)
    assert app.repair.analysis.condition.value == "healthy"
    assert ui.btn_repair.enabled()
    result = repair(app)
    assert result.status.value == "repaired"
    import pikepdf

    with pikepdf.open(app.repair.output, password="Geheim-123") as out:
        assert out.is_encrypted  # die Kopie bleibt geschützt
    # Das Passwort steht nirgends
    app.persist()
    assert "Geheim-123" not in config_file.read_text(encoding="utf-8")
    assert "Geheim-123" not in app.repair.log.path.read_text(encoding="utf-8")


def test_signed_pdf_asks_before_repair(repair_app, tmp_path: Path, monkeypatch) -> None:
    from ui import dialogs

    app = repair_app
    pdf = samples.signed(tmp_path / "signiert.pdf")
    analysis = analyse(app, pdf)
    assert analysis.signatures == 1
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "close")  # »Abbrechen«
    app.repair.start_repair()
    pump(app, 0.2)
    assert app.repair.job is None and not app.repair.busy and app.repair.result is None
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")  # »Trotzdem reparieren«
    result = repair(app)
    assert result.status.value == "repaired"
    assert any("Signaturen" in warning for warning in result.warnings)


def test_cancel_stops_the_worker_and_leaves_no_file(repair_app, tmp_path: Path) -> None:
    app = repair_app
    pdf = samples.large(tmp_path / "gross.pdf", pages=300)
    analyse(app, pdf)
    # Der Rettungsmodus rendert jede Seite einzeln – der Vorgang läuft sicher noch, wenn abgebrochen wird.
    app.repair.start_repair(RepairMode.RASTER)
    assert app.repair.busy and app.repair.ui.btn_cancel.enabled()
    job = app.repair.job
    work = job.work_dir
    assert work is not None and work.is_dir()
    assert wait_until(app, lambda: app.repair.stage == "raster", 60)
    app.repair.ui.btn_cancel.invoke()
    assert not app.repair.busy and app.repair.job is None
    assert job.cancelled and not job._process.is_alive()  # Arbeitsprozess wirklich beendet
    assert not work.exists()  # Zwischendateien entfernt
    assert app.repair.ui.btn_repair.enabled() and not app.repair.ui.btn_cancel.enabled()
    assert "abgebrochen" in app.ui.repair_info.message
    assert not [name for name in samples.files_in(tmp_path) if "repariert" in name]


def test_ui_stays_responsive_during_repair(repair_app, tmp_path: Path) -> None:
    app = repair_app
    pdf = samples.large(tmp_path / "gross.pdf", pages=300)
    analyse(app, pdf)
    app.repair.start_repair()
    longest = 0.0
    last = time.perf_counter()
    end = last + 120
    while app.repair.busy and time.perf_counter() < end:
        app.update()
        now = time.perf_counter()
        longest = max(longest, now - last)
        last = now
        time.sleep(0.01)
    assert not app.repair.busy
    assert longest < 0.5, f"Oberfläche blockiert ({longest:.2f} s)"
    assert app.repair.result.status.value in ("healthy", "repaired")


def test_output_folder_is_used_and_remembered(repair_app, tmp_path: Path) -> None:
    from tools.pdf_repair.page import OUT_FOLDER

    app = repair_app
    out = tmp_path / "Ausgabe"
    out.mkdir()
    pdf = samples.xref_offset(tmp_path / "quelle" / "Vertrag.pdf")
    app.repair.out_dir = str(out)
    app.repair.var_out_mode.set(OUT_FOLDER)
    analyse(app, pdf)
    assert "Vertrag_repariert.pdf" in app.repair.ui.out_name.cget("text")
    repair(app)
    assert app.repair.output == out / "Vertrag_repariert.pdf"
    assert not (pdf.parent / "Vertrag_repariert.pdf").exists()
    neu = neustart(app)
    try:
        assert neu.repair.var_out_mode.get() == OUT_FOLDER
        assert neu.repair.out_dir == str(out)
        assert neu.repair.source_dir == str(pdf.parent)
    finally:
        schliessen(neu)


def test_non_pdf_is_rejected(repair_app, tmp_path: Path) -> None:
    app = repair_app
    app.open_tool("repair")
    pump(app, 0.2)
    text = samples.not_pdf(tmp_path / "notiz.txt")
    app.repair.drop([str(text)])
    assert app.repair.path is None and app.ui.repair_drop_info.severity == "warning"
    fake = tmp_path / "falsch.pdf"
    fake.write_bytes(text.read_bytes())
    analysis = analyse(app, fake)
    assert analysis.condition.value == "unreadable" and not analysis.looks_like_pdf
