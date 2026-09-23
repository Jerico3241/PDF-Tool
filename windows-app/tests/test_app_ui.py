"""Oberflächentests: Die App wird gestartet und wie von einem Anwender bedient."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import display_available, pump, wait_until

pytestmark = pytest.mark.skipif(not display_available(), reason="kein Display verfügbar")


@pytest.fixture(params=[True, False], ids=["animationen", "ohne-animationen"])
def app(request, config_file: Path, monkeypatch):
    config_file.write_text(json.dumps({"gesehen": "2.1.0", "theme": "light", "accent": "#005FB8"}), encoding="utf-8")
    if request.param:
        monkeypatch.delenv("UE_NO_ANIMATIONS", raising=False)
    else:
        monkeypatch.setenv("UE_NO_ANIMATIONS", "1")
    from ui import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    import vertragdesk

    instance = vertragdesk.App()
    instance.ctx.anim.enabled = request.param
    pump(instance, 0.5)
    yield instance
    try:
        instance._on_close()
    except Exception:
        pass
    # Tk-Objekte im Hauptthread freigeben, nicht später in einem Worker-Thread.
    import gc

    gc.collect()


def test_start_and_version(app) -> None:
    assert app.title() == "Übersichten-Ersteller"
    assert app.version == "2.1.0"
    assert app.nav.current == "create"
    assert app.ui.btn_pdf.text() == "PDF erstellen"


def test_navigation_all_pages_and_rapid_switching(app) -> None:
    for key in ("layout", "settings", "create"):
        app.nav.navigate(key)
        pump(app, 0.4)
        assert app.nav.current == key
    for _ in range(4):
        for key in ("layout", "settings", "create", "settings", "layout"):
            app.nav.navigate(key)
            app.update()
    pump(app, 0.8)
    page = app.nav.pages[app.nav.current]
    for widget, _options in page._sections:
        assert widget.winfo_manager() == "pack"
    assert page.scroll.offset_x == 0


def test_theme_accent_switching(app) -> None:
    app.nav.navigate("settings")
    pump(app, 0.3)
    app.set_theme("dark")
    pump(app, 0.2)
    assert app.theme.palette.dark is True
    assert app.nav.pane.cget("bg").upper() == app.theme.palette.mica.upper()
    app.set_accent("#C42B1E")
    pump(app, 0.2)
    assert app.theme.accent_choice == "#C42B1E"
    app.set_theme("system")
    app.set_accent("system")
    pump(app, 0.2)
    cfg = json.loads(Path(app.cfg and __import__("appstate").CONFIG_FILE).read_text(encoding="utf-8"))
    assert cfg["theme"] == "system" and cfg["accent"] == "system"


def test_excel_check_and_pdf_creation(app, excel_file: Path, tmp_path: Path) -> None:
    app.var_ziel.set(str(tmp_path))
    app.var_open.set(False)
    app.var_excel.set(str(excel_file))
    app.inspect_excel(str(excel_file))
    assert wait_until(app, lambda: app.ui.info_excel.severity == "success", 60)
    assert "3 aktive Verträge" in app.ui.info_excel.message
    assert app.var_kd.get() == "10042"
    assert app.var_firma.get() == "Muster GmbH"
    app.start_pdf()
    assert app.busy and app.ui.btn_pdf.busy()
    assert wait_until(app, lambda: not app.busy, 90)
    assert app.ui.pdf_info.severity == "success", app.ui.pdf_info.message
    pdf = tmp_path / "Vertragsuebersicht_Kd10042.pdf"
    assert pdf.is_file()
    assert app.state.pdfs[0] == str(pdf)
    assert app.ui.pdf_combo.get() == pdf.name
    assert app.state.kunden[0]["kundennummer"] == "10042"
    assert app.ui.recent_combo.values()


def test_pdf_validation_messages(app, tmp_path: Path) -> None:
    app.var_excel.set("")
    app.start_pdf()
    pump(app, 0.3)
    assert app.ui.pdf_info.severity == "error"
    assert "Excel" in app.ui.pdf_info.message
    assert not app.busy


def test_multiple_recipients_need_choice(app, tmp_path: Path) -> None:
    from datetime import datetime

    from conftest import write_excel

    path = write_excel(
        tmp_path / "zwei.xlsx",
        [
            ["A-1", datetime(2023, 1, 1), "jährlich", 10.0, "Sofort", "Eins", "a@x.de", 1, "F", "Aktiv"],
            ["A-2", datetime(2023, 2, 1), "jährlich", 20.0, "Sofort", "Zwei", "b@x.de", 1, "F", "Aktiv"],
        ],
    )
    app.var_ziel.set(str(tmp_path))
    app.var_excel.set(str(path))
    app.inspect_excel(str(path))
    assert wait_until(app, lambda: app.ui.info_excel.severity == "success", 60)
    pump(app, 0.4)
    assert app.ui.mail_area.expanded
    assert app.ui.mail_combo.values() == ["a@x.de", "b@x.de"]
    app.var_mail.set("")
    app.start_pdf()
    pump(app, 0.2)
    assert app.ui.pdf_info.severity == "warning"
    app.ui.mail_combo.select_index(1)
    app.var_open.set(False)
    app.start_pdf()
    assert wait_until(app, lambda: not app.busy, 90)
    assert app.ui.pdf_info.severity == "success"


def test_templates_blocks_rules_history(app, tmp_path: Path) -> None:
    app.nav.navigate("layout")
    pump(app, 0.5)
    # Vorlage speichern, ändern, laden, löschen
    app.var_vorlage.set("Standard")
    app.var_titel.set("Titel A")
    app.ui.txt_kopf.set("Kopf A")
    app.save_vorlage()
    assert app.state.find_vorlage("Standard")["kopfzeile"] == "Kopf A"
    assert "Standard" in app.ui.vorlage_combo.values()
    app.var_titel.set("Anders")
    app.ui.txt_kopf.set("")
    app.on_vorlage_pick("Standard")
    assert app.var_titel.get() == "Titel A"
    assert app.header_text() == "Kopf A"
    app.delete_vorlage()
    assert app.state.find_vorlage("Standard") is None
    # Textbaustein
    app.var_baustein.set("Bank")
    app.ui.txt_fuss.set("IBAN DE00")
    app.save_footer()
    assert app.state.find_baustein("Bank")["text"] == "IBAN DE00"
    app.ui.txt_fuss.set("")
    app.on_baustein_pick("Bank")
    assert app.footer_text() == "IBAN DE00"
    app.delete_baustein()
    assert app.state.find_baustein("Bank") is None
    # Regeln
    count = len(app.state.regeln)
    app.var_regel_such.set("Wartung")
    app.var_regel_zyk.set("vierteljährlich")
    app.add_regel()
    assert len(app.state.regeln) == count + 1
    app.delete_regel(len(app.state.regeln) - 1)
    assert len(app.state.regeln) == count
    app.var_regel_such.set("")
    app.add_regel()
    assert app.ui.regeln_info.severity == "warning"
    # Kopfzeile speichern
    app.ui.txt_kopf.set("Kopfzeile X")
    app.save_header()
    assert app.ui.kopf_info.severity == "success"
    # Kundenhistorie
    app.var_firma.set("Beispiel AG")
    app.var_kd.set("777")
    app._remember_customer()
    label = next(iter(app._recent_by_label))
    app.clear_customer()
    assert app.var_kd.get() == ""
    app._undo_clear()
    assert app.var_kd.get() == "777"
    app.clear_customer()
    app.on_recent_pick(label)
    assert app.var_firma.get() == "Beispiel AG"
    app.nav.navigate("settings")
    pump(app, 0.3)
    app.clear_history()
    assert app.state.kunden == [] and app.state.pdfs == []


def test_persist_keeps_205_keys(app, config_file: Path) -> None:
    app.var_firma.set("Persist GmbH")
    app.persist()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    for key in ("firmenname", "kundennummer", "rechnungsempfaenger", "excel", "logo", "zielordner", "dateiname", "format", "logo_breite", "titel", "untertitel", "fusszeile", "kopfzeile", "baustein_name", "bausteine", "kunden", "pdfs", "regeln", "vorlagen", "staende", "gesehen", "pdf_oeffnen", "theme", "accent"):
        assert key in data, key
    assert data["firmenname"] == "Persist GmbH"


def test_dialogs_and_keyboard(app) -> None:
    from ui import dialogs

    for method in (app.show_help, app.show_about, app.show_changelog):
        method()
        pump(app, 0.1)
    dialogs.AUTO_ANSWER = None
    result = {}

    def open_dialog() -> None:
        result["value"] = dialogs.ContentDialog(app, "Test", "Text", primary="Ja", close="Nein").show()

    def press_escape() -> None:
        for child in app.winfo_children():
            if child.winfo_class() == "Toplevel":
                child.event_generate("<Escape>")

    app.after(300, press_escape)
    app.after(10, open_dialog)
    pump(app, 1.2)
    assert result.get("value") == "close"


def test_toggle_switch_and_combobox_keyboard(app) -> None:
    before = app.var_open.get()
    app.nav.navigate("settings")
    pump(app, 0.3)
    toggles = [w for w in _descendants(app.nav.pages["settings"]) if w.__class__.__name__ == "ToggleSwitch"]
    target = next(t for t in toggles if t.var is app.var_open)
    target.toggle()
    pump(app, 0.3)
    assert app.var_open.get() is (not before)
    combo = app.ui.theme_combo
    combo.focus_set()
    combo._step(1)
    pump(app, 0.2)
    assert app.theme.mode in ("light", "dark", "system")
    combo.open_popup()
    pump(app, 0.3)
    assert combo._popup is not None
    combo._escape()
    assert combo._popup is None


def test_scaling_does_not_break(app) -> None:
    for size in ("760x540", "1280x720", "1920x1080"):
        app.geometry(size)
        pump(app, 0.4)
        assert app.nav.pane.winfo_width() > 0
    app.geometry("760x540")
    pump(app, 0.6)
    assert app.nav.is_compact()


def test_long_status_is_elided_and_keeps_hints(app) -> None:
    app.geometry("720x560")
    message = "Excel erfolgreich geprüft: " + "sehr langer Hinweistext · " * 12
    app.set_status(message, "success")
    pump(app, 0.4)
    status = app.nav.status
    shown = status.label.cget("text")
    assert shown.endswith("…") and len(shown) < len(message)
    assert status._tooltip.text == message
    # Die Tastenhinweise bleiben vollständig sichtbar und überlappen die Meldung nicht.
    assert status.hint.winfo_width() >= status.hint.winfo_reqwidth()
    assert status.label.winfo_x() + status.label.winfo_width() <= status.hint.winfo_x()
    app.set_status("Bereit")
    pump(app, 0.1)
    assert status.label.cget("text") == "Bereit" and status._tooltip.text == ""


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)
