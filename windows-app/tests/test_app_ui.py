"""Oberflächentests: Die App wird gestartet und wie von einem Anwender bedient."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import display_available, pump, wait_until
from conftest import neustart as _neustart
from conftest import schliessen as _schliessen

pytestmark = pytest.mark.skipif(not display_available(), reason="kein Display verfügbar")


def test_start_and_version(app) -> None:
    import appstate

    assert app.title() == appstate.APP_NAME == "PDF Tool"
    assert app.version == appstate.VERSION == "2.6.0"
    assert app.nav.current == "home"  # nach dem Start: Startseite mit allen Werkzeugen
    assert app.ui.btn_pdf.text() == "PDF erstellen"


def test_navigation_all_pages_and_rapid_switching(app) -> None:
    for key in ("layout", "settings", "create", "repair", "home"):
        app.nav.navigate(key)
        pump(app, 0.4)
        assert app.nav.current == key
    for _ in range(4):
        for key in ("layout", "settings", "create", "repair", "home", "settings", "layout"):
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
    # Kundenakten entstehen nie automatisch – nach der PDF wird das Speichern nur angeboten.
    assert len(app.customers) == 0
    assert app.ui.kunde_info.title == "Als Kundenakte speichern?"


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
    # Mehrere Empfänger: »2 erkannt« mit Auswahl direkt daneben (Excel-Karte)
    assert app.ui.mail_value.cget("text") == "2 erkannt" and app.ui.mail_combo.winfo_ismapped()
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
    # Kundenakte: bewusst speichern, leeren (rückgängig), wieder auswählen
    app.var_firma.set("Beispiel AG")
    app.var_kd.set("777")
    app.save_as_customer()
    kunde = app.active_customer()
    assert kunde is not None and kunde.label == "Beispiel AG · 777"
    app.clear_customer()
    assert app.var_kd.get() == "" and app.active_customer() is None
    app._undo_clear()
    assert app.var_kd.get() == "777" and app.active_customer() is kunde
    app.clear_customer()
    app.pick_customer()  # Dialog (Tests: erster Treffer)
    assert app.var_firma.get() == "Beispiel AG" and app.active_customer() is kunde
    app.nav.navigate("settings")
    pump(app, 0.3)
    app.clear_history()
    assert app.state.pdfs == [] and len(app.customers) == 1  # Kundenakten bleiben


def test_persist_keeps_205_keys(app, config_file: Path) -> None:
    app.var_firma.set("Persist GmbH")
    app.persist()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    for key in ("firmenname", "kundennummer", "rechnungsempfaenger", "excel", "logo", "zielordner", "dateiname", "format", "logo_breite", "titel", "untertitel", "fusszeile", "kopfzeile", "baustein_name", "bausteine", "pdfs", "regeln", "vorlagen", "staende", "gesehen", "pdf_oeffnen", "theme", "accent"):
        assert key in data, key
    assert data["firmenname"] == "Persist GmbH"
    # Die Kundenhistorie bis 2.3 lebt als Kundenakte weiter (kundenakten.json), nicht in gui-config.json.
    assert "kunden" not in data and data["kunden_auto_uebernehmen"] is False


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
    app.nav.navigate("create")  # werkzeugbezogene Einstellung: im Werkzeug, nicht unter »Einstellungen«
    pump(app, 0.3)
    toggles = [w for w in _descendants(app.nav.pages["create"]) if w.__class__.__name__ == "ToggleSwitch"]
    target = next(t for t in toggles if t.var is app.var_open)
    target.toggle()
    pump(app, 0.3)
    assert app.var_open.get() is (not before)
    app.nav.navigate("settings")
    pump(app, 0.3)
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


# --- Standard-Fußzeile und Speicherung ------------------------------------------------------

FUSS_EIGEN = "Eigener kundenspezifischer Text\nZeile 2\n\nZeile 4"


def test_footer_default_on_first_start(app) -> None:
    from appstate import DEFAULT_FOOTER

    # Test 1: frische Konfiguration – die Standard-Fußzeile steht vollständig im Feld
    assert app.ui.txt_fuss.get() == DEFAULT_FOOTER
    assert app.footer_text() == DEFAULT_FOOTER


def test_footer_survives_restart_and_default_can_be_restored(app, config_file: Path) -> None:
    from appstate import DEFAULT_FOOTER

    # Test 2: eigene Fußzeile speichern, schließen, neu starten
    app.ui.txt_fuss.set(FUSS_EIGEN)
    app.save_footer()
    assert app.ui.fuss_info.severity == "success"
    gespeichert = json.loads(config_file.read_text(encoding="utf-8"))
    assert gespeichert["fusszeile"] == FUSS_EIGEN and gespeichert["fusszeile_explizit"] is True
    zweite = _neustart(app)
    try:
        assert zweite.ui.txt_fuss.get() == FUSS_EIGEN
        # Test 3: Standard wiederherstellen, schließen, neu starten
        zweite.restore_default_footer()
        assert zweite.ui.txt_fuss.get() == DEFAULT_FOOTER
        assert zweite.ui.fuss_info.message == "Standard-Fußzeile wiederhergestellt."
        dritte = _neustart(zweite)
        try:
            assert dritte.ui.txt_fuss.get() == DEFAULT_FOOTER
        finally:
            _schliessen(dritte)
    finally:
        _schliessen(zweite)


def test_footer_restore_is_undoable(app) -> None:
    from appstate import DEFAULT_FOOTER

    app.ui.txt_fuss.set(FUSS_EIGEN)
    app.restore_default_footer()
    assert app.footer_text() == DEFAULT_FOOTER
    # »Rückgängig« in der Hinweisleiste
    aktion = app.ui.fuss_info._actions.winfo_children()[0]
    aktion.invoke()
    assert app.footer_text() == FUSS_EIGEN
    # und Strg+Z im Textfeld (eigener Rückgängig-Verlauf für Text und Formatierung)
    app.restore_default_footer()
    app.ui.txt_fuss.text.focus_force()
    pump(app, 0.1)
    app.ui.txt_fuss.text.event_generate("<Control-z>")
    pump(app, 0.1)
    assert app.footer_text() == FUSS_EIGEN


def test_footer_with_templates(app) -> None:
    from appstate import DEFAULT_FOOTER

    # Test 4: Vorlage mit eigener Fußzeile
    app.var_vorlage.set("Mit Fußzeile")
    app.ui.txt_fuss.set(FUSS_EIGEN)
    app.save_vorlage()
    assert app.state.find_vorlage("Mit Fußzeile")["fusszeile"] == FUSS_EIGEN
    app.ui.txt_fuss.set("Etwas anderes")
    app.on_vorlage_pick("Mit Fußzeile")
    assert app.footer_text() == FUSS_EIGEN
    # Vorlagen älterer Versionen ohne Wert, mit leerem Wert oder null: Standard
    app.state.vorlagen += [{"name": "Alt ohne"}, {"name": "Alt leer", "fusszeile": ""}, {"name": "Alt null", "fusszeile": None}]
    for name in ("Alt ohne", "Alt leer", "Alt null"):
        app.ui.txt_fuss.set("x")
        app.on_vorlage_pick(name)
        assert app.footer_text() == DEFAULT_FOOTER, name


@pytest.mark.parametrize(
    "alt,erwartet",
    [
        ({"fusszeile": ""}, "STANDARD"),  # Test 5: alter Bug-Zustand
        ({"fusszeile": None}, "STANDARD"),
        ({}, "STANDARD"),
        ({"fusszeile": "Individuell\n\nAlt"}, "Individuell\n\nAlt"),  # keine Datenverluste
    ],
)
def test_footer_migration_of_old_config(config_file: Path, monkeypatch, alt: dict, erwartet: str) -> None:
    from appstate import DEFAULT_FOOTER
    from ui import dialogs

    import vertragdesk

    erwartet = DEFAULT_FOOTER if erwartet == "STANDARD" else erwartet
    config_file.write_text(json.dumps({"gesehen": "2.2.0", "theme": "light", **alt}), encoding="utf-8")
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    app = vertragdesk.App()
    try:
        pump(app, 0.3)
        assert app.ui.txt_fuss.get() == erwartet
        app._on_close()
        gespeichert = json.loads(config_file.read_text(encoding="utf-8"))
        assert gespeichert["fusszeile"] == erwartet and gespeichert["fusszeile_explizit"] is True
    finally:
        _schliessen(app)


def test_customer_record_keeps_footer_unless_it_has_its_own(app) -> None:
    from tools.contract_overview.customers.models import TextBlock

    app.ui.txt_fuss.set(FUSS_EIGEN)
    app._mark_text_baseline()  # gültiger Stand, noch nicht vom Benutzer verändert
    alt = app.customers.create("Alt AG", "1")  # ohne eigene Fußzeile
    neu = app.customers.create("Neu AG", "2", footer=TextBlock("Kunde B\n\nGruß"))
    app.apply_customer(alt.id)
    assert app.footer_text() == FUSS_EIGEN
    app.apply_customer(neu.id)
    assert app.footer_text() == "Kunde B\n\nGruß"
    # Zurück zu einem Kunden ohne eigene Fußzeile: wieder die vorher gültige
    app.apply_customer(alt.id)
    assert app.footer_text() == FUSS_EIGEN


def test_footer_autosave_is_debounced(app, config_file: Path) -> None:
    calls = []
    original = app.persist
    app.persist = lambda: (calls.append(1), original())[1]
    pump(app, 1.0)  # Start abgeschlossen, ausstehende Speicherungen erledigt
    calls.clear()
    for zeichen in "Nachtrag":
        app.ui.txt_fuss.text.insert("end", zeichen)
        pump(app, 0.05)
    assert calls == []  # nicht bei jedem Tastendruck
    pump(app, 1.2)
    assert len(calls) == 1
    gespeichert = json.loads(config_file.read_text(encoding="utf-8"))
    assert gespeichert["fusszeile"].endswith("Nachtrag")


def test_pdf_uses_visible_footer(app, excel_file: Path, tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    app.var_ziel.set(str(tmp_path))
    app.var_open.set(False)
    app.var_excel.set(str(excel_file))
    app.var_kd.set("10042")
    app.ui.txt_fuss.set(FUSS_EIGEN)
    app.start_pdf()
    assert wait_until(app, lambda: not app.busy, 90)
    assert app.ui.pdf_info.severity == "success", app.ui.pdf_info.message
    text = pypdf.PdfReader(str(tmp_path / "Vertragsuebersicht_Kd10042.pdf")).pages[0].extract_text()
    for zeile in ("Eigener kundenspezifischer Text", "Zeile 2", "Zeile 4"):
        assert zeile in text


# --- Aufbau, Seitenwechsel und Resize ohne sichtbare Zwischenzustände ---------------------------


def test_all_pages_prepared_at_startup(app) -> None:
    from ui.navigation import PARK_X

    assert set(app.nav.pages) == {"home", "create", "batch", "layout", "preview", "customers", "repair", "settings"}
    assert app.ctx.ready and not app.ctx.anim.is_resizing
    host_w = app.nav.host.winfo_width()
    for key, page in app.nav.pages.items():
        # jede Seite ist vollständig angeordnet – auch die nicht sichtbaren
        assert page.winfo_width() == host_w and page.winfo_ismapped(), key
        if key != app.nav.current:
            assert int(page.place_info()["x"]) == PARK_X, key
            assert app.ctx.focus_blocked(str(page))


def test_navigation_shows_finished_page_without_rebuild(app) -> None:
    created = {}
    import tkinter as tk

    original = tk.Widget.__init__

    def counting(self, *args, **kwargs):
        created["n"] = created.get("n", 0) + 1
        return original(self, *args, **kwargs)

    tk.Widget.__init__ = counting
    try:
        for key in ("layout", "settings", "create", "repair", "home", "settings"):
            app.nav.navigate(key)
            page = app.nav.pages[key]
            # direkt nach dem Wechsel: Seite liegt vorn und ist fertig angeordnet
            assert int(page.place_info()["x"]) == 0
            assert page.winfo_width() == app.nav.host.winfo_width()
            pump(app, 0.3)
    finally:
        tk.Widget.__init__ = original
    assert created.get("n", 0) == 0  # kein Widget neu erzeugt


def test_resize_applies_breakpoints_immediately_without_animation(app, monkeypatch) -> None:
    from ui import context
    from ui.context import MODE_COMPACT, MODE_MEDIUM, MODE_WIDE
    from ui.theme import px

    # Geprüft wird der Zustand während des Resize. Dessen Ende erkennt die App nach
    # RESIZE_SETTLE_MS Ruhe; ein langsamer Rechner braucht für update() nach einer
    # Größenänderung aber länger und würde das Ende schon darin auslösen.
    monkeypatch.setattr(context, "RESIZE_SETTLE_MS", 1500)
    app.ctx.anim.enabled = True
    for width, mode, columns in ((px(1100), MODE_WIDE, 2), (px(900), MODE_MEDIUM, 2), (px(780), MODE_COMPACT, 1), (px(1100), MODE_WIDE, 2)):
        app.geometry(f"{width}x{px(700)}")
        app.update()
        assert app.ctx.anim.is_resizing
        assert app.nav.mode == mode
        assert app.ctx.layout.columns == columns
        assert not app.ctx.anim.running(f"pane:{app.nav}")  # keine Animation während des Resize
        assert app.nav.pane.expanded_amount in (0.0, 1.0)
    assert wait_until(app, lambda: not app.ctx.anim.is_resizing, 5)


def test_breakpoint_hysteresis(app) -> None:
    from ui.navigation import BREAKPOINT_HYSTERESIS, WIDE_FROM
    from ui.theme import px

    nav = app.nav
    nav.apply_layout(px(WIDE_FROM) + 2)
    assert nav.mode == "wide"
    nav.apply_layout(px(WIDE_FROM) - 2)  # knapp darunter: bleibt breit (Hysterese)
    assert nav.mode == "wide"
    nav.apply_layout(px(WIDE_FROM) - px(BREAKPOINT_HYSTERESIS) - 2)
    assert nav.mode == "medium"
    nav.apply_layout(px(WIDE_FROM) - 2)  # zurück: erst ab dem Breakpoint wieder breit
    assert nav.mode == "medium"


def test_moves_do_not_redraw_canvas_controls(app) -> None:
    button = app.ui.btn_pdf
    calls = []
    original = button.redraw
    button.redraw = lambda animate=True: (calls.append(animate), original(animate))[1]
    width, height = button.winfo_width(), button.winfo_height()
    button.event_generate("<Configure>", x=5, y=5, width=width, height=height)
    assert calls == []  # nur verschoben: nichts neu zu zeichnen
    button.event_generate("<Configure>", x=5, y=5, width=width + 30, height=height)
    assert calls == [False]


def test_width_change_renders_no_new_images(app) -> None:
    field = app.ui.field_firma
    images = app.ctx.images
    before = len(images._items)
    for width in range(300, 420, 7):
        field.event_generate("<Configure>", width=width, height=field.winfo_height())
    assert len(images._items) == before  # 3-Slice: nur Elemente verschoben


def test_scrollregion_only_set_when_changed(app) -> None:
    area = app.nav.pages["create"].scroll
    calls = []
    original = area.canvas.configure

    def counting(*args, **kwargs):
        if "scrollregion" in kwargs:
            calls.append(kwargs["scrollregion"])
        return original(*args, **kwargs)

    area.canvas.configure = counting
    for _ in range(5):
        area._sync()
    assert calls == []


def test_theme_changes_are_coalesced(app) -> None:
    calls = []
    app.theme.subscribe(lambda: calls.append(1))
    app.theme.set(mode="dark")
    app.theme.set(accent="#C42B1E")
    app.theme.set(mode="light")
    assert calls == []  # noch nichts gezeichnet
    app.update()
    assert calls == [1]  # genau ein Neuzeichnen


def test_tab_skips_parked_pages_and_collapsed_areas(app) -> None:
    app.nav.navigate("create", animate=False)
    pump(app, 0.2)
    widget = app.ui.field_firma.entry
    visited = []
    for _ in range(40):
        widget = app.nametowidget(app.tk.call("tk_focusNext", str(widget)))
        visited.append(str(widget))
    for key in ("layout", "settings"):
        assert not any(path.startswith(str(app.nav.pages[key])) for path in visited), key
    # Die Empfänger-Auswahl erscheint erst bei mehreren Empfängern – vorher kein Tab-Ziel
    assert not app.ui.mail_combo.winfo_ismapped()
    assert str(app.ui.mail_combo) not in visited


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)
