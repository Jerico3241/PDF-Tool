"""Oberflächentests für Version 2.2: Rich-Text-Editor, Persistenz der Formatierung und Workflow."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from conftest import COLUMNS, display_available, neustart, pump, schliessen, wait_until, write_excel

pytestmark = pytest.mark.skipif(not display_available(), reason="kein Display verfügbar")

ROT = "#B51F1F"


def markiere(editor, start: str, end: str) -> None:
    text = editor.text
    text.tag_remove("sel", "1.0", "end")
    text.tag_add("sel", start, end)
    text.mark_set("insert", end)


def cursor(editor, index: str) -> None:
    editor.text.tag_remove("sel", "1.0", "end")
    editor.text.mark_set("insert", index)
    editor.refresh_toolbar()


def tippe(app, editor, text: str) -> None:
    for zeichen in text:
        editor.text.insert("insert", zeichen)
    pump(app, 0.05)


def runs(rich) -> list[tuple[str, dict]]:
    return [(rich.text[s:e], {k: v for k, v in style.to_dict().items() if k in ("bold", "italic", "underline", "strike", "color", "size", "font")}) for s, e, style in rich.runs()]


# --- Editor ------------------------------------------------------------------------------------


def test_selection_gets_only_the_chosen_format(app) -> None:
    editor = app.ui.txt_kopf
    editor.set("Bitte beachten Sie die Hinweise")
    markiere(editor, "1.0", "1.18")  # »Bitte beachten Sie«
    editor.toggle("bold")
    pump(app, 0.1)
    rich = editor.get_rich()
    assert [(t, s["bold"]) for t, s in runs(rich)] == [("Bitte beachten Sie", True), (" die Hinweise", False)]
    # Leiste: Cursor im fetten Bereich → Fett aktiv; gemischte Markierung → neutral
    cursor(editor, "1.5")
    assert editor.btn_bold.checked is True
    cursor(editor, "1.25")
    assert editor.btn_bold.checked is False
    markiere(editor, "1.10", "1.25")
    editor.refresh_toolbar()
    assert editor.btn_bold.checked is None


def test_format_without_selection_applies_to_new_text(app) -> None:
    editor = app.ui.txt_kopf
    editor.set("Anfang ")
    cursor(editor, "end-1c")
    editor.text.focus_force()
    pump(app, 0.1)
    editor.text.event_generate("<Control-b>")
    pump(app, 0.05)
    assert editor.btn_bold.checked is True
    tippe(app, editor, "fett")
    rich = editor.get_rich()
    assert [(t, s["bold"]) for t, s in runs(rich)] == [("Anfang ", False), ("fett", True)]
    # Cursor bewegt: das zuvor gewählte Eingabeformat gilt nicht mehr
    cursor(editor, "1.2")
    tippe(app, editor, "x")
    assert not editor.get_rich().style_at(2).bold


def test_shortcuts_undo_and_redo(app) -> None:
    editor = app.ui.txt_kopf
    editor.set("Wort eins")
    editor.text.focus_force()
    pump(app, 0.1)
    markiere(editor, "1.0", "1.4")
    for key in ("<Control-b>", "<Control-i>", "<Control-u>"):
        editor.text.event_generate(key)
        pump(app, 0.02)
    style = editor.get_rich().style_at(0)
    assert style.bold and style.italic and style.underline
    editor.text.event_generate("<Control-z>")  # Unterstrichen zurück
    pump(app, 0.02)
    style = editor.get_rich().style_at(0)
    assert style.bold and style.italic and not style.underline
    editor.text.event_generate("<Control-y>")  # wieder da
    pump(app, 0.02)
    assert editor.get_rich().style_at(0).underline
    # Text-Rückgängig: Tippen wird zu einem Schritt zusammengefasst
    cursor(editor, "end-1c")
    tippe(app, editor, " zwei")
    assert editor.get().endswith(" zwei")
    editor.text.event_generate("<Control-z>")
    pump(app, 0.02)
    assert editor.get() == "Wort eins"


def test_toolbar_font_size_color_and_alignment(app) -> None:
    editor = app.ui.txt_fuss
    editor.set("Absatz eins\nAbsatz zwei")
    markiere(editor, "1.0", "1.6")
    editor.font_combo.select_index(editor.font_combo.values().index("Times"))
    markiere(editor, "1.0", "1.6")
    editor.size_combo.select_index(editor.size_combo.values().index("12"))
    markiere(editor, "1.0", "1.6")
    editor.set_color(ROT)
    cursor(editor, "2.3")
    editor.align_buttons["right"].invoke()
    pump(app, 0.1)
    rich = editor.get_rich()
    style = rich.style_at(0)
    assert (style.font, style.size, style.color) == ("Times", 12, ROT)
    assert rich.style_at(7) == editor.default
    assert rich.aligns == ["center", "right"]
    cursor(editor, "1.2")
    assert editor.font_combo.get() == "Times" and editor.size_combo.get() == "12"
    assert editor.align_buttons["center"].checked is True and editor.align_buttons["right"].checked is False


def test_toolbar_wraps_when_narrow(app) -> None:
    app.nav.navigate("layout")
    app.geometry("780x700")
    pump(app, 0.8)
    bar = app.ui.txt_fuss.toolbar
    breite = bar.winfo_width()
    for kind in bar.winfo_children():
        assert kind.winfo_x() + kind.winfo_width() <= breite + 1  # keine kaputte horizontale Anordnung
    assert app.ui.txt_fuss.area.winfo_width() <= bar.winfo_width() + 2


# --- Persistenz --------------------------------------------------------------------------------


def formatiere_fuss_und_kopf(app) -> tuple:
    fuss = app.ui.txt_fuss
    fuss.set("Kundennummer: {kd}\nZweiter Absatz")
    markiere(fuss, "1.14", "1.18")
    fuss.toggle("bold")
    fuss.set_color(ROT)
    cursor(fuss, "2.2")
    fuss.align("right")
    kopf = app.ui.txt_kopf
    kopf.set("Kopf kursiv")
    markiere(kopf, "1.5", "1.11")
    kopf.toggle("italic")
    pump(app, 0.1)
    return fuss.get_rich(), kopf.get_rich()


def test_rich_header_footer_survive_restart(app, config_file: Path) -> None:
    fuss, kopf = formatiere_fuss_und_kopf(app)
    pump(app, 1.2)  # verzögertes automatisches Speichern
    gespeichert = json.loads(config_file.read_text(encoding="utf-8"))
    assert gespeichert["fusszeile"] == fuss.text and gespeichert["kopfzeile"] == kopf.text  # reiner Text bleibt
    assert gespeichert["fusszeile_format"]["text"] == fuss.text and gespeichert["kopfzeile_format"]["text"] == kopf.text
    zweite = neustart(app)
    try:
        assert zweite.ui.txt_fuss.get_rich() == fuss
        assert zweite.ui.txt_kopf.get_rich() == kopf
    finally:
        schliessen(zweite)


def test_restore_default_resets_text_and_formatting(app) -> None:
    from appstate import default_footer_rich

    formatiere_fuss_und_kopf(app)
    app.restore_default_footer()
    assert app.footer_rich() == default_footer_rich()
    zweite = neustart(app)
    try:
        assert zweite.ui.txt_fuss.get_rich() == default_footer_rich()
    finally:
        schliessen(zweite)


def test_template_keeps_formatting_across_restart(app) -> None:
    fuss, kopf = formatiere_fuss_und_kopf(app)
    app.var_vorlage.set("Formatiert")
    app.save_vorlage()
    app.ui.txt_fuss.set("anders")
    app.ui.txt_kopf.set("")
    zweite = neustart(app)
    try:
        zweite.on_vorlage_pick("Formatiert")
        assert zweite.footer_rich() == fuss
        assert zweite.header_rich() == kopf
    finally:
        schliessen(zweite)


def test_text_block_keeps_formatting_across_restart(app) -> None:
    fuss, _kopf = formatiere_fuss_und_kopf(app)
    app.var_baustein.set("Gruß formatiert")
    app.save_footer()
    zweite = neustart(app)
    try:
        zweite.ui.txt_fuss.set("etwas anderes")
        zweite.on_baustein_pick("Gruß formatiert")
        assert zweite.footer_rich() == fuss
        # ältere Bausteine (nur Text) laden weiterhin – mit Standardformat
        zweite.state.bausteine.append({"name": "Alt", "text": "Nur Text"})
        zweite.on_baustein_pick("Alt")
        assert zweite.footer_text() == "Nur Text"
        assert zweite.footer_rich().styles == [zweite.ui.txt_fuss.default] * len("Nur Text")
    finally:
        schliessen(zweite)


def test_customer_history_keeps_formatting(app) -> None:
    fuss, kopf = formatiere_fuss_und_kopf(app)
    app.var_firma.set("Format AG")
    app.var_kd.set("777")
    app._remember_customer()
    zweite = neustart(app)
    try:
        zweite.ui.txt_fuss.set("x")
        zweite.ui.txt_kopf.set("y")
        label = next(label for label, eintrag in zweite._recent_by_label.items() if eintrag["kundennummer"] == "777")
        zweite.on_recent_pick(label)
        assert zweite.footer_rich() == fuss and zweite.header_rich() == kopf
    finally:
        schliessen(zweite)


def test_old_config_with_plain_header_and_footer(config_file: Path, monkeypatch) -> None:
    import vertragdesk
    from richtext import FOOTER_STYLE, HEADER_STYLE
    from ui import dialogs

    config_file.write_text(json.dumps({"gesehen": "2.2.0", "theme": "light", "kopfzeile": "Alte Kopfzeile", "fusszeile": "Alte Fußzeile"}), encoding="utf-8")
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "primary")
    app = vertragdesk.App()
    try:
        pump(app, 0.3)
        assert app.ui.txt_kopf.get() == "Alte Kopfzeile" and app.ui.txt_fuss.get() == "Alte Fußzeile"
        assert set(app.header_rich().styles) == {HEADER_STYLE} and app.header_rich().aligns == ["left"]
        assert set(app.footer_rich().styles) == {FOOTER_STYLE} and app.footer_rich().aligns == ["center"]
        app._on_close()
        gespeichert = json.loads(config_file.read_text(encoding="utf-8"))
        assert gespeichert["kopfzeile"] == "Alte Kopfzeile" and gespeichert["fusszeile"] == "Alte Fußzeile"
        assert gespeichert["kopfzeile_format"]["text"] == "Alte Kopfzeile"
    finally:
        schliessen(app)


def test_fresh_config_default_footer_in_pdf_and_after_restart(app, excel_file: Path, tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    from appstate import DEFAULT_FOOTER

    assert app.footer_text() == DEFAULT_FOOTER
    app.var_ziel.set(str(tmp_path))
    app.var_open.set(False)
    app.use_excel(str(excel_file))
    assert wait_until(app, lambda: app.ui.ready.kind == "success", 60), app.ui.ready.text
    app.start_pdf()
    assert wait_until(app, lambda: not app.busy, 90)
    seite = pypdf.PdfReader(str(tmp_path / "Vertragsuebersicht_Kd10042.pdf")).pages[0]
    text = " ".join(seite.extract_text().split())
    for absatz in DEFAULT_FOOTER.split("\n"):
        if absatz:
            assert absatz in text
    fonts = set()
    seite.extract_text(visitor_text=lambda t, _c, _m, f, s: fonts.add((str(f.get("/BaseFont", "")), round(s, 1))) if "Mehrwertsteuer" in t and f else None)
    assert fonts == {("/Helvetica", 8.0)}
    zweite = neustart(app)
    try:
        assert zweite.footer_text() == DEFAULT_FOOTER
    finally:
        schliessen(zweite)


# --- Workflow ------------------------------------------------------------------------------------


def excel_ohne_kunde(tmp_path: Path, zeilen: list[list], name: str = "liste.xlsx") -> Path:
    """Wie die echten Listen: Verträge und Empfänger-E-Mail, aber keine Kundennummer/Firma."""
    spalten = [c for c in COLUMNS if c not in ("Kundennummer", "Firmenname")]
    return write_excel(tmp_path / name, zeilen, spalten)


def test_excel_analysis_shows_only_real_values(app, tmp_path: Path) -> None:
    pfad = excel_ohne_kunde(
        tmp_path,
        [
            ["V-1", datetime(2023, 1, 1), "jährlich", 10.0, "Sofort", "Eins", "rechnung@firma-mueller.de", "Aktiv"],
            ["V-2", datetime(2022, 1, 1), "jährlich", 20.0, "Sofort", "Zwei", "rechnung@firma-mueller.de", "Inaktiv"],
        ],
    )
    app.use_excel(str(pfad))
    assert wait_until(app, lambda: app.ui.info_excel.severity == "success", 60)
    pump(app, 0.3)
    fakten = {label: wert for label, wert, _ton in app.ui.excel_facts.facts()}
    assert fakten["Aktive Verträge"] == "1" and fakten["Ausgeblendet (inaktiv)"] == "1"
    assert fakten["Rechnungsempfänger"] == "rechnung@firma-mueller.de"
    # nichts aus der E-Mail-Adresse erraten
    assert "Kundennummer" not in fakten and "Firmenname" not in fakten
    assert app.var_kd.get() == "" and app.var_firma.get() == ""
    assert app.ui.excel_details.expanded


def test_missing_columns_are_reported(app, tmp_path: Path) -> None:
    spalten = ["Vertrag-Nr.", "Beginnt am", "Abrechnungszyklus", "Netto [€]", "Bemerkung", "Anwenderstatus"]
    pfad = write_excel(tmp_path / "ohne.xlsx", [["V-1", datetime(2023, 1, 1), "jährlich", 10.0, "Eins", "Aktiv"]], spalten)
    app.var_kd.set("1")
    app.use_excel(str(pfad))
    assert wait_until(app, lambda: app.ui.info_excel.severity == "error", 60)
    assert "Zahlungsart" in app.ui.info_excel.message
    pump(app, 0.2)
    assert app.ui.ready.kind == "critical" and "Zahlungsart" in app.ui.ready.text


def test_readiness_states(app, excel_file: Path, tmp_path: Path) -> None:
    app.var_excel.set("")
    app.var_kd.set("")
    pump(app, 0.1)
    assert app.ui.ready.kind in ("caution", "critical")
    assert "Excel-Datei fehlt" in app.ui.ready.text and "Kundennummer fehlt" in app.ui.ready.text
    app.var_ziel.set(str(tmp_path))
    app.use_excel(str(excel_file))
    assert wait_until(app, lambda: app.ui.ready.kind == "success", 60), app.ui.ready.text
    assert app.ui.ready.text == "Bereit zum Erstellen"
    app.var_kd.set("")
    pump(app, 0.1)
    assert app.ui.ready.text == "Kundennummer fehlt"
    app.fix_readiness()  # Klick auf die Anzeige: zum Feld springen
    pump(app, 0.1)
    assert app.ui.field_kd._error
    app.var_kd.set("10042")
    app.var_breite.set("abc")
    pump(app, 0.1)
    assert app.ui.ready.text == "Logo-Breite ungültig"
    app.var_breite.set("62")
    app.var_logo.set(str(tmp_path / "fehlt.png"))
    pump(app, 0.1)
    assert app.ui.ready.text == "Logo-Datei nicht gefunden"
    app.use_default_logo()
    datei = tmp_path / "keinordner.txt"
    datei.write_text("x", encoding="utf-8")
    app.var_ziel.set(str(datei))
    pump(app, 0.1)
    assert app.ui.ready.text == "Zielordner nicht erreichbar"
    app.var_ziel.set(str(tmp_path / "neu" / "unterordner"))  # wird beim Erstellen angelegt
    pump(app, 0.1)
    assert app.ui.ready.kind == "success"


def test_multiple_recipients_readiness_and_choice(app, tmp_path: Path) -> None:
    pfad = excel_ohne_kunde(
        tmp_path,
        [
            ["V-1", datetime(2023, 1, 1), "jährlich", 10.0, "Sofort", "Eins", "a@x.de", "Aktiv"],
            ["V-2", datetime(2023, 2, 1), "jährlich", 20.0, "Sofort", "Zwei", "b@x.de", "Aktiv"],
        ],
    )
    app.var_kd.set("5")
    app.var_mail.set("")
    app.use_excel(str(pfad))
    assert wait_until(app, lambda: app.ui.info_excel.severity == "success", 60)
    pump(app, 0.3)
    assert app.ui.ready.text == "Bitte Rechnungsempfänger auswählen"
    fakten = {label: wert for label, wert, _ton in app.ui.excel_facts.facts()}
    assert "2 verschiedene" in fakten["Rechnungsempfänger"]
    app.ui.mail_combo.select_index(1)
    pump(app, 0.1)
    assert app.var_mail.get() == "b@x.de"
    assert app.ui.ready.kind == "success"


def test_pdf_completion_actions_copy_and_new_overview(app, excel_file: Path, tmp_path: Path) -> None:
    app.var_ziel.set(str(tmp_path))
    app.var_open.set(False)
    app.use_excel(str(excel_file))
    assert wait_until(app, lambda: app.ui.ready.kind == "success", 60)
    fuss_vorher = app.footer_rich()
    logo_vorher = app.var_logo.get()
    app.start_pdf()
    assert wait_until(app, lambda: not app.busy, 90)
    bar = app.ui.pdf_info
    assert bar.severity == "success"
    knoepfe = {button.text(): button for button in bar._actions.winfo_children()}
    assert list(knoepfe) == ["Öffnen", "Ordner öffnen", "Pfad kopieren", "Neue Übersicht"]
    assert bar._actions.winfo_manager() == "pack" and bar._actions.pack_info()["in"] == bar.box  # unter dem Text
    knoepfe["Pfad kopieren"].invoke()
    assert app.clipboard_get() == str(tmp_path / "Vertragsuebersicht_Kd10042.pdf")
    knoepfe["Neue Übersicht"].invoke()
    pump(app, 0.2)
    assert (app.var_firma.get(), app.var_kd.get(), app.var_mail.get(), app.var_excel.get()) == ("", "", "", "")
    assert app.var_logo.get() == logo_vorher and app.var_ziel.get() == str(tmp_path)
    assert app.footer_rich() == fuss_vorher
    assert "Excel-Datei fehlt" in app.ui.ready.text
    # Rückgängig stellt die Arbeitsdaten wieder her
    rueck = app.ui.kunde_info._actions.winfo_children()[0]
    rueck.invoke()
    pump(app, 0.2)
    assert app.var_kd.get() == "10042" and app.var_excel.get() == str(excel_file)


def test_autosave_of_all_fields_is_debounced(app, config_file: Path, tmp_path: Path) -> None:
    calls = []
    original = app.persist
    app.persist = lambda: (calls.append(1), original())[1]
    pump(app, 1.0)
    calls.clear()
    werte = {"var_firma": "Auto GmbH", "var_kd": "4711", "var_mail": "a@b.de", "var_ziel": str(tmp_path), "var_titel": "Übersicht", "var_breite": "70"}
    for name, wert in werte.items():
        getattr(app, name).set(wert)
        pump(app, 0.05)
    assert calls == []
    pump(app, 1.2)
    assert len(calls) == 1
    gespeichert = json.loads(config_file.read_text(encoding="utf-8"))
    assert gespeichert["firmenname"] == "Auto GmbH" and gespeichert["kundennummer"] == "4711"
    assert gespeichert["rechnungsempfaenger"] == "a@b.de" and gespeichert["zielordner"] == str(tmp_path)
    assert gespeichert["titel"] == "Übersicht" and gespeichert["logo_breite"] == "70"
    assert not [p for p in config_file.parent.iterdir() if p.name.endswith(".tmp")]  # atomar geschrieben


def test_drag_and_drop_highlight_and_drop(app, excel_file: Path) -> None:
    card = app.ui.dateien_card
    app._drag_enter(True)
    pump(app, 0.05)
    assert card._stroke_role == "accent"
    assert app.ui.info_excel.message.startswith("Loslassen")
    app._drag_leave()
    pump(app, 0.05)
    assert card._stroke_role == "card_stroke"
    assert not app.ui.info_excel.message.startswith("Loslassen")
    app._drag_enter(False)  # keine Excel-Datei: keine Hervorhebung
    assert card._stroke_role == "card_stroke"
    app.nav.navigate("layout")
    pump(app, 0.3)
    app._on_drop(["C:/nicht/excel.txt", str(excel_file)])
    assert app.nav.current == "create" and app.var_excel.get() == str(excel_file)
    assert wait_until(app, lambda: app.ui.info_excel.severity == "success", 60)
    app._on_drop(["C:/bild.png"])
    assert app.ui.info_excel.severity == "warning"


def test_file_dialogs_start_in_last_folder(app, excel_file: Path, monkeypatch) -> None:
    import vertragdesk

    gesehen = {}

    def ask(**kwargs):
        gesehen.update(kwargs)
        return str(excel_file)

    monkeypatch.setattr(vertragdesk.filedialog, "askopenfilename", ask)
    app.var_excel.set("")
    app.pick_excel()
    assert app.var_excel.get() == str(excel_file)
    app.var_excel.set("")
    app.pick_excel()
    assert gesehen["initialdir"] == str(excel_file.parent)
    zweite = neustart(app)
    try:
        assert zweite._dirs["excel"] == str(excel_file.parent)
    finally:
        schliessen(zweite)


def test_copy_path_from_file_rows(app, excel_file: Path) -> None:
    app.var_excel.set(str(excel_file))
    app.copy_path(app.var_excel.get())
    assert app.clipboard_get() == str(excel_file)
    assert app.nav.status.text.startswith("Pfad kopiert")
    app.copy_path("")
    assert app.nav.status.text == "Kein Pfad zum Kopieren vorhanden."
