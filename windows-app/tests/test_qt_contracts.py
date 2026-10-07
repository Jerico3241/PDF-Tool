"""Vertragsübersichten in der Qt-Oberfläche (2.7.0): Excel-Prüfung und PDF, Hinweise, mehrere
Rechnungsempfänger, Vorlagen, Textbausteine, Zyklus-Regeln und Verlauf, gespeicherte Werte (Schlüssel
wie 2.0.5), Dialoge und Tastatur, Standard-Fußzeile, formatierte Kopf- und Fußzeile (Rich Text),
Excel-Analyse, Bereitschaft, Abschlussaktionen, verzögertes Speichern, Drag & Drop und Dateiauswahl.

Portiert aus den Tk-Tests ``test_app_ui.py`` und ``test_app_v22.py`` (bis 2.6.1): dieselben Abläufe und
Erwartungen – bedient über die Controller (``Contracts``, ``Customers``, ``App``) und die QML-Elemente
statt über Tk-Widgets. Kopf- und Fußzeile werden im echten QML-Textfeld bearbeitet (Markierung,
Tastatur, Formatleiste, Rückgängig/Wiederholen des Dokuments). Nach jedem Test mit Oberfläche darf die
QML-Engine keine Warnung gemeldet haben (Fixture).

Bewusst nicht portiert (Tk-Interna ohne sichtbares Gegenstück bzw. schon in ``test_qt_shell.py``):

* ``test_navigation_all_pages_and_rapid_switching`` – gleichnamig in test_qt_shell.py; die übrigen
  Prüfungen (pack-Manager der Abschnitte, horizontaler Scrollversatz) sind Tk-Interna.
* ``test_breakpoint_hysteresis`` – die Hysterese der Breakpoints (8 px wie 2.6.1) und das Umschalten
  der Navigation prüft ``test_qt_shell.py::test_breakpoint_hysteresis_and_toggle``.
* ``test_moves_do_not_redraw_canvas_controls`` – Neuzeichnen von Tk-Canvas-Steuerelementen beim
  Verschieben; in Qt zeichnet der Szenengraph.
* ``test_width_change_renders_no_new_images`` – Bildzwischenspeicher der Tk-3-Slice-Grafiken.
* ``test_scrollregion_only_set_when_changed`` – ``scrollregion`` des Tk-Canvas (Qt: Flickable).
* ``test_theme_changes_are_coalesced`` – Abonnenten des Tk-Designs; Qt fasst Änderungen über
  Bindungen und Szenengraph ohnehin je Bild zusammen.

Innerhalb portierter Tests entfällt nur die Tk-Geometrie »Aktionen per pack unter dem Text«
(``test_pdf_completion_actions_copy_and_new_overview``; die QML-InfoBar ordnet Text und Aktionen in
einem Flow an – geprüft wird, dass alle Aktionen sichtbar sind).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Q_ARG, QMetaObject, QObject, QPointF, Qt, QTimer
from PySide6.QtTest import QTest

from conftest import COLUMNS, neustart, pump, wait_until, write_excel
from qtutil import qml_type

import appstate
from appstate import DEFAULT_FOOTER, default_footer_rich
from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText

KOPF = "headerEditor"
FUSS = "footerEditor"
ROT = "#B51F1F"
FUSS_EIGEN = "Eigener kundenspezifischer Text\nZeile 2\n\nZeile 4"
# Die Standard-Fußzeile der App – wörtlich, einschließlich aller Zeilenumbrüche.
STANDARD_FUSSZEILE = (
    "Die oben aufgeführte Auflistung gibt den aktuellen Stand Ihrer Verträge sowie die derzeit geltenden Vertragspreise wieder.\n"
    "Alle genannten Preise verstehen sich zuzüglich der jeweils geltenden gesetzlichen Mehrwertsteuer.\n"
    "\n"
    "Die Angaben erfolgen gemäß Ihren abgeschlossenen Verträgen sowie den jeweils geltenden Vertragsbedingungen "
    "und berücksichtigen gegebenenfalls bereits erfolgte Preisanpassungen."
)
PDF_NAME = "Vertragsuebersicht_Kd10042.pdf"


# --- Hilfen: QML-Elemente ------------------------------------------------------------------------


def elemente(wurzel):
    """Alle QML-Elemente unterhalb von ``wurzel`` (einschließlich)."""
    stapel = [wurzel]
    while stapel:
        element = stapel.pop()
        yield element
        stapel.extend(reversed(element.childItems()))


def finde(wurzel, bedingung) -> list:
    return [element for element in elemente(wurzel) if bedingung(element)]


def element(wurzel, **werte):
    """Erstes Element unterhalb von ``wurzel`` mit diesen Eigenschaftswerten (z. B. ``label=…``)."""
    treffer = finde(wurzel, lambda e: all(e.property(name) == wert for name, wert in werte.items()))
    assert treffer, f"Kein QML-Element mit {werte}"
    return treffer[0]


def qml_typ(element) -> str:
    return qml_type(element)


def gleich(a, b) -> bool:
    """Dasselbe C++-Objekt (Python-Hüllen können wechseln)."""
    import shiboken6

    return a is not None and b is not None and shiboken6.getCppPointer(a)[0] == shiboken6.getCppPointer(b)[0]


def liegt_in(element, vorfahr) -> bool:
    while element is not None:
        if gleich(element, vorfahr):
            return True
        element = element.parentItem()
    return False


def klicke(knopf) -> None:
    """Klick auf eine Schaltfläche (wie ``invoke()`` in Tk): löst ihr ``clicked`` aus."""
    assert QMetaObject.invokeMethod(knopf, "clicked")
    pump(0.05)


def waehle(auswahl, index: int) -> None:
    """Eintrag einer Auswahlliste wählen (wie ``select_index()`` in Tk): löst ``activated`` aus."""
    assert QMetaObject.invokeMethod(auswahl, "activated", Q_ARG(int, index))
    pump(0.05)


def vorlagen_namen(o) -> list[str]:
    """Namen der Vorlagen in der Auswahlliste (das Modell ist ab 2.8 nach der ID geordnet)."""
    return [o.templates.item(key)["name"] for key in o.templates.keys()]


def waehle_vorlage(h, name: str) -> None:
    """Gespeicherte Vorlage in der Auswahlliste der Ansicht »Darstellung« wählen."""
    namen = vorlagen_namen(h.overview)
    assert name in namen, name
    waehle(element(h.item("page_layout"), label="Geladene Vorlage"), namen.index(name))


def waehle_baustein(h, name: str) -> None:
    """Textbaustein in der Auswahlliste der Fußzeile wählen."""
    index = h.overview.textBlocks.indexOf(name)
    assert index >= 0, name
    waehle(element(h.item("page_layout"), label="Textbaustein"), index)


def taste(h, key, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    QTest.keyClick(h.window, key, modifiers)
    pump(0.02)


def strg(h, key) -> None:
    taste(h, key, Qt.KeyboardModifier.ControlModifier)


def tippe(h, text: str) -> None:
    """Tastatureingabe Zeichen für Zeichen in das Element mit dem Fokus."""
    for zeichen in text:
        QTest.keyClick(h.window, zeichen)
    pump(0.05)


def zwischenablage() -> str:
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.clipboard().text()


def statusleiste(h):
    return finde(h.window.contentItem(), lambda e: qml_typ(e).startswith("StatusBar"))[0]


# --- Hilfen: Hinweise ----------------------------------------------------------------------------


def hinweis(h, bereich: str):
    return h.app.notices.get(bereich)


def hinweisleiste(h, bereich: str):
    """Die QML-InfoBar des Hinweisbereichs ``bereich``."""
    notice = hinweis(h, bereich)
    leisten = finde(h.window.contentItem(), lambda e: e.property("notice") is notice)
    assert leisten, f"Keine InfoBar für {bereich}"
    return leisten[0]


def aktionsknoepfe(h, bereich: str) -> dict:
    """Aktionen der InfoBar (Beschriftung → Schaltfläche) in der angezeigten Reihenfolge."""
    leiste = hinweisleiste(h, bereich)
    knoepfe = finde(leiste, lambda e: qml_typ(e) == "PButton")
    return {knopf.property("text"): knopf for knopf in knoepfe}


def aktionsknopf(h, bereich: str, text: str):
    knoepfe = aktionsknoepfe(h, bereich)
    assert text in knoepfe, f"{bereich}: {list(knoepfe)}"
    return knoepfe[text]


# --- Hilfen: Kopf- und Fußzeile ---------------------------------------------------------------


def textfeld(h, editor: str):
    """Das QML-Textfeld (TextArea) im Editor »headerEditor« bzw. »footerEditor«."""
    return next(e for e in elemente(h.item(editor)) if e.inherits("QQuickTextEdit"))


def angezeigter_text(h, editor: str) -> str:
    """Text, den das QML-Textfeld zeigt (Absätze mit ``\\n``)."""
    return textfeld(h, editor).property("textDocument").textDocument().toPlainText()


def leistenknopf(h, editor: str, tip: str):
    """Schaltfläche der Formatleiste, z. B. »Fett (Strg+B)«."""
    return element(h.item(editor), tip=tip)


def markiere(h, editor: str, start: int, ende: int) -> None:
    QMetaObject.invokeMethod(textfeld(h, editor), "select", Q_ARG(int, start), Q_ARG(int, ende))
    pump(0.02)


def setze_cursor(h, editor: str, position: int) -> None:
    feld = textfeld(h, editor)
    QMetaObject.invokeMethod(feld, "deselect")
    feld.setProperty("cursorPosition", position)
    pump(0.02)


def fokus(h, editor: str) -> None:
    feld = textfeld(h, editor)
    feld.forceActiveFocus()
    pump(0.05)
    assert feld.hasActiveFocus()


def setze_kopf(h, text: str) -> None:
    """Kopfzeile laden – wie ``txt_kopf.set()`` bis 2.6.1 (neuer Inhalt, Rückgängig beginnt neu)."""
    h.overview.set_header(RichText.plain(text, HEADER_STYLE, HEADER_ALIGN))
    pump(0.02)


def setze_fuss(h, text: str) -> None:
    h.overview.set_footer(RichText.plain(text, FOOTER_STYLE, FOOTER_ALIGN))
    pump(0.02)


def runs(rich) -> list[tuple[str, dict]]:
    return [(rich.text[s:e], {k: v for k, v in style.to_dict().items() if k in ("bold", "italic", "underline", "strike", "color", "size", "font")}) for s, e, style in rich.runs()]


def lies(config_file: Path) -> dict:
    return json.loads(config_file.read_text(encoding="utf-8"))


@pytest.fixture
def alte_konfig(request, config_file: Path) -> dict:
    """Konfiguration einer älteren Version – geschrieben, bevor die App startet."""
    daten = {"gesehen": "2.2.0", "theme": "light", **request.param}
    config_file.write_text(json.dumps(daten), encoding="utf-8")
    return daten


# --- Start, Design, Excel-Prüfung und PDF ---------------------------------------------------------


def test_start_and_version(ui_app) -> None:
    from qtapp.app import window_title

    h = ui_app
    assert appstate.APP_NAME == "PDF Tool" and h.window.title() == window_title(appstate.VERSION)  # Beta: »PDF Tool X.Y.Z Beta«
    assert h.app.version == appstate.VERSION  # die Versionsnummer selbst prüft test_core
    assert h.app.currentPage == "home"  # nach dem Start: Startseite mit allen Werkzeugen
    assert h.item("createPdf").property("text") == "PDF erstellen"


def test_theme_accent_switching(ui_app, config_file: Path) -> None:
    h = ui_app
    h.navigate("settings", 0.3)
    h.settings.setTheme("dark")
    pump(0.2)
    assert h.theme.dark is True
    # Navigation und Fensterhintergrund in der Mica-Farbe des dunklen Designs
    assert h.window.color().name().lower() == h.theme.colors["mica"].lower()
    h.settings.setAccent("#C42B1E")
    pump(0.2)
    assert h.theme.accentChoice == "#C42B1E"
    h.settings.setTheme("system")
    h.settings.setAccent("system")
    pump(0.2)
    daten = lies(config_file)
    assert daten["theme"] == "system" and daten["accent"] == "system"


def test_excel_check_and_pdf_creation(ui_app, excel_file: Path, tmp_path: Path) -> None:
    h = ui_app
    o = h.overview
    o.ziel = str(tmp_path)
    o.pdfOeffnen = False
    o.excel = str(excel_file)
    o.inspect_excel(str(excel_file))
    info = hinweis(h, "info_excel")
    assert wait_until(lambda: info.severity == "success", 60)
    assert "3 aktive Verträge" in info.message
    assert o.kd == "10042"
    assert o.firma == "Muster GmbH"
    o.start_pdf()
    assert o.busy and h.item("createPdf").property("busy") is True
    assert wait_until(lambda: not o.busy, 90)
    assert hinweis(h, "pdf_info").severity == "success", hinweis(h, "pdf_info").message
    pdf = tmp_path / PDF_NAME
    assert pdf.is_file()
    assert h.app.state.pdfs[0] == str(pdf)
    pump(0.1)
    assert element(h.item("page_create"), label="Zuletzt erstellt").property("displayText") == pdf.name
    # Kundenakten entstehen nie automatisch – nach der PDF wird das Speichern nur angeboten.
    assert len(h.customers.customers) == 0
    assert hinweis(h, "kunde_info").title == "Als Kundenakte speichern?"


def test_status_bar_names_only_the_result_of_the_excel_check(ui_app, excel_file: Path, tmp_path: Path) -> None:
    """Einzelmodus: Die Vertragszahlen nennt nur die Hinweisleiste der Excel-Karte – die
    Statusleiste unten nur das Ergebnis, ohne Zahlen (und ohne Angaben aus der Datei)."""
    import re

    h = ui_app
    o = h.overview
    h.navigate("create", 0.3)

    def pruefe(pfad: Path, schwere: str) -> str:
        h.app.set_status("Bereit")
        o.use_excel(str(pfad))
        assert wait_until(lambda: hinweis(h, "info_excel").severity == schwere and h.app.statusText != "Bereit" and "wird geprüft" not in h.app.statusText, 60)
        pump(0.4)
        text = h.app.statusText
        assert not re.search(r"\d", text) and "Muster" not in text and "@" not in text, text
        sichtbar = [t for t in finde(statusleiste(h), lambda e: e.inherits("QQuickText")) if t.property("text") == text and t.property("opacity") > 0.99]
        assert sichtbar, f"»{text}« nicht in der Statusleiste"
        return text

    assert pruefe(excel_file, "success") == "Excel geprüft." and h.app.statusKind == "success"
    assert hinweis(h, "info_excel").message == "3 aktive Verträge · 1 inaktiv ausgeblendet"  # nur hier die Zahlen
    inaktiv = write_excel(tmp_path / "inaktiv.xlsx", [["V-1", datetime(2023, 1, 1), "jährlich", 10.0, "Sofort", "Eins", "a@x.de", 1, "F", "Inaktiv"]])
    assert pruefe(inaktiv, "warning") == "Excel geprüft – keine aktiven Verträge." and h.app.statusKind == "warning"
    spalten = ["Vertrag-Nr.", "Beginnt am", "Abrechnungszyklus", "Netto [€]", "Bemerkung", "Anwenderstatus"]
    ohne = write_excel(tmp_path / "ohne.xlsx", [["V-1", datetime(2023, 1, 1), "jährlich", 10.0, "Eins", "Aktiv"]], spalten)
    assert pruefe(ohne, "error") == "Excel geprüft – es fehlen Spalten." and h.app.statusKind == "warning"


def test_pdf_validation_messages(ui_app) -> None:
    h = ui_app
    h.overview.excel = ""
    h.overview.start_pdf()
    pump(0.3)
    info = hinweis(h, "pdf_info")
    assert info.severity == "error"
    assert "Excel" in info.message
    assert not h.overview.busy
    assert hinweisleiste(h, "pdf_info").property("shown") is True


def test_multiple_recipients_need_choice(ui_app, tmp_path: Path) -> None:
    h = ui_app
    o = h.overview
    pfad = write_excel(
        tmp_path / "zwei.xlsx",
        [
            ["A-1", datetime(2023, 1, 1), "jährlich", 10.0, "Sofort", "Eins", "a@x.de", 1, "F", "Aktiv"],
            ["A-2", datetime(2023, 2, 1), "jährlich", 20.0, "Sofort", "Zwei", "b@x.de", 1, "F", "Aktiv"],
        ],
    )
    h.navigate("create", 0.3)
    o.ziel = str(tmp_path)
    o.excel = str(pfad)
    o.inspect_excel(str(pfad))
    assert wait_until(lambda: hinweis(h, "info_excel").severity == "success", 60)
    pump(0.4)
    # Mehrere Empfänger: »2 erkannt« mit Auswahl direkt daneben (Excel-Karte)
    seite = h.item("page_create")
    auswahl = element(seite, label="Rechnungsempfänger wählen")
    assert o.mailValue == "2 erkannt" and auswahl.isVisible()
    assert any(e.isVisible() for e in finde(seite, lambda e: e.inherits("QQuickText") and e.property("text") == "2 erkannt"))
    assert o.mailChoices == ["a@x.de", "b@x.de"]
    o.mail = ""
    o.start_pdf()
    pump(0.2)
    assert hinweis(h, "pdf_info").severity == "warning"
    waehle(auswahl, 1)
    assert o.mail == "b@x.de"
    o.pdfOeffnen = False
    strg(h, Qt.Key.Key_Return)  # Strg+Enter: PDF erstellen
    assert o.busy or o.pdf_runs == 1
    assert wait_until(lambda: not o.busy, 90)
    assert o.pdf_runs == 1
    assert hinweis(h, "pdf_info").severity == "success"


def test_templates_blocks_rules_history(ui_app) -> None:
    h = ui_app
    o = h.overview
    state = h.app.state
    h.navigate("layout", 0.5)
    # Vorlage speichern, ändern, laden, löschen
    o.vorlage = "Standard"
    o.titel = "Titel A"
    setze_kopf(h, "Kopf A")
    o.saveVorlage()
    assert state.find_vorlage("Standard")["kopfzeile"] == "Kopf A"
    assert "Standard" in vorlagen_namen(o)
    o.titel = "Anders"
    setze_kopf(h, "")
    waehle_vorlage(h, "Standard")
    assert o.titel == "Titel A"
    assert o.header_text() == "Kopf A"
    o.deleteVorlage()
    assert state.find_vorlage("Standard") is None
    assert "Standard" not in vorlagen_namen(o)
    # Textbaustein
    o.baustein = "Bank"
    setze_fuss(h, "IBAN DE00")
    o.saveFooter()
    assert state.find_baustein("Bank")["text"] == "IBAN DE00"
    setze_fuss(h, "")
    waehle_baustein(h, "Bank")
    assert o.footer_text() == "IBAN DE00"
    o.deleteBaustein()
    assert state.find_baustein("Bank") is None
    # Regeln
    anzahl = len(state.regeln)
    o.regelSuch = "Wartung"
    o.regelZyk = "vierteljährlich"
    o.addRegel()
    assert len(state.regeln) == anzahl + 1
    o.deleteRegel(len(state.regeln) - 1)
    assert len(state.regeln) == anzahl
    o.regelSuch = ""
    o.addRegel()
    assert hinweis(h, "regeln_info").severity == "warning"
    # Kopfzeile speichern
    setze_kopf(h, "Kopfzeile X")
    o.saveHeader()
    assert hinweis(h, "kopf_info").severity == "success"
    # Kundenakte: bewusst speichern, leeren (rückgängig), wieder auswählen
    h.navigate("create", 0.3)
    o.firma = "Beispiel AG"
    o.kd = "777"
    pump(0.05)
    speichern = h.item("saveCustomer")
    assert speichern.property("enabled") is True and speichern.property("text") == "Als Kundenakte speichern"
    klicke(speichern)
    kunde = h.customers.active_customer()
    assert kunde is not None and kunde.label == "Beispiel AG · 777"
    o.clearCustomer()
    assert o.kd == "" and h.customers.active_customer() is None
    klicke(aktionsknopf(h, "kunde_info", "Rückgängig"))
    assert o.kd == "777" and h.customers.active_customer() is not None and h.customers.active_customer().id == kunde.id
    o.clearCustomer()
    klicke(h.item("customerPicker"))  # Dialog »Bekannten Kunden auswählen« (Tests: erster Treffer)
    assert o.firma == "Beispiel AG" and h.customers.active_customer().id == kunde.id
    o.clearHistory()
    assert state.pdfs == [] and len(h.customers.customers) == 1  # Kundenakten bleiben


def test_persist_keeps_205_keys(backend, config_file: Path) -> None:
    h = backend
    h.overview.firma = "Persist GmbH"
    h.app.persist()
    daten = lies(config_file)
    # Vorlagen liegen ab 2.8 in eigenen Dateien (test_templates.py); eine vorhandene Liste
    # »vorlagen« bleibt unverändert stehen (test_config_migration.py).
    for key in ("firmenname", "kundennummer", "rechnungsempfaenger", "excel", "logo", "zielordner", "dateiname", "format", "logo_breite", "titel", "untertitel", "fusszeile", "kopfzeile", "baustein_name", "bausteine", "pdfs", "regeln", "staende", "gesehen", "pdf_oeffnen", "theme", "accent"):
        assert key in daten, key
    assert daten["firmenname"] == "Persist GmbH"
    # Die Kundenhistorie bis 2.3 lebt als Kundenakte weiter (kundenakten.json), nicht in gui-config.json.
    assert "kunden" not in daten and daten["kunden_auto_uebernehmen"] is False


# --- Dialoge und Tastatur ------------------------------------------------------------------------------


def test_dialogs_and_keyboard(ui_app, monkeypatch) -> None:
    from qtapp import dialogs

    h = ui_app
    for methode in (h.app.showHelp, h.app.showAbout, h.app.showChangelog):
        methode()
        pump(0.1)
    assert [anfrage["kind"] for anfrage in h.app.dialogs.history[-3:]] == ["steps", "about", "changelog"]
    # Ein echter Dialog in QML: Esc schließt ihn mit »Abbrechen«
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    gesehen = {}

    def escape() -> None:
        gesehen["offen"] = h.app.dialogs.open
        gesehen["titel"] = h.app.dialogs.request.get("title")
        QTest.keyClick(h.window, Qt.Key.Key_Escape)

    def notausgang() -> None:  # nie endlos warten, falls Esc nicht wirkt
        if h.app.dialogs.open:
            h.app.dialogs.answer(h.app.dialogs.request["id"], "primary", {})

    QTimer.singleShot(300, escape)
    QTimer.singleShot(5000, notausgang)
    antwort, _daten = h.app.dialogs.ask("confirm", "Test", "Text", primary="Ja", close="Nein")
    assert gesehen == {"offen": True, "titel": "Test"}
    assert antwort == "close"
    pump(0.4)
    assert not h.app.dialogs.open


def test_toggle_switch_and_combobox_keyboard(ui_app) -> None:
    h = ui_app
    vorher = h.overview.pdfOeffnen
    h.navigate("create", 0.3)  # werkzeugbezogene Einstellung: im Werkzeug, nicht unter »Einstellungen«
    schalter = finde(h.item("page_create"), lambda e: e.property("label") == "PDF nach dem Erstellen öffnen" and e.inherits("QQuickAbstractButton"))[0]
    schalter.forceActiveFocus()
    taste(h, Qt.Key.Key_Space)
    pump(0.3)
    assert h.overview.pdfOeffnen is (not vorher)
    assert schalter.property("checked") is (not vorher)
    h.navigate("settings", 0.3)
    auswahl = h.item("themeCombo")
    auswahl.forceActiveFocus()
    modus = h.theme.mode
    taste(h, Qt.Key.Key_Down)
    pump(0.4)
    assert h.theme.mode in ("light", "dark", "system") and h.theme.mode != modus
    taste(h, Qt.Key.Key_Space)
    pump(0.3)
    assert auswahl.property("down") is True  # Liste offen
    taste(h, Qt.Key.Key_Escape)
    pump(0.3)
    assert auswahl.property("down") is False


def test_scaling_does_not_break(ui_app) -> None:
    h = ui_app
    leiste = h.item("appTabs")
    for breite, hoehe in ((760, 540), (1280, 720), (1920, 1080), (760, 540)):
        h.window.resize(breite, hoehe)
        pump(0.4)
        assert leiste.width() == breite and leiste.height() == 40  # Tab-Leiste über die ganze Breite


def test_long_status_is_elided_and_keeps_hints(ui_app) -> None:
    h = ui_app
    h.window.resize(720, 560)
    pump(0.4)
    meldung = "Excel erfolgreich geprüft: " + "sehr langer Hinweistext · " * 12
    h.app.set_status(meldung, "success")
    pump(0.4)
    leiste = statusleiste(h)
    texte = finde(leiste, lambda e: e.inherits("QQuickText"))
    sichtbar = [t for t in texte if t.property("text") == meldung and t.property("opacity") > 0.99]
    assert sichtbar, "Meldung nicht sichtbar"
    status = sichtbar[0]
    assert status.property("truncated") is True  # gekürzt mit »…«
    # Die Tastenhinweise bleiben vollständig sichtbar und überlappen die Meldung nicht.
    tasten = [t for t in texte if t.property("text") == h.app.hint]
    assert tasten and tasten[0].isVisible() and tasten[0].property("truncated") is False
    rechts = status.mapToScene(QPointF(status.width(), 0)).x()
    assert rechts <= tasten[0].mapToScene(QPointF(0, 0)).x()
    h.app.set_status("Bereit")
    pump(0.4)
    bereit = [t for t in texte if t.property("text") == "Bereit" and t.property("opacity") > 0.99]
    assert bereit and bereit[0].property("truncated") is False
    # Wie bis 2.6.1: Die vollständige Meldung steht als Tooltip der Statuszeile bereit.
    h.app.set_status(meldung, "success")
    pump(0.4)
    tooltips = [o for o in leiste.findChildren(QObject) if o.inherits("QQuickToolTip")]
    assert any(t.property("text") == meldung for t in tooltips), "Kein Tooltip mit der vollständigen Statusmeldung"


# --- Standard-Fußzeile und Speicherung ------------------------------------------------------------


def test_footer_default_on_first_start(ui_app) -> None:
    h = ui_app
    # Der Text der Standard-Fußzeile bleibt wörtlich erhalten (einzige Quelle: appstate.DEFAULT_FOOTER).
    assert DEFAULT_FOOTER == STANDARD_FUSSZEILE
    # Test 1: frische Konfiguration – die Standard-Fußzeile steht vollständig im Feld
    assert angezeigter_text(h, FUSS) == DEFAULT_FOOTER
    assert h.overview.footer_text() == DEFAULT_FOOTER
    assert h.overview.footer_rich() == default_footer_rich()


def test_footer_survives_restart_and_default_can_be_restored(ui_app, config_file: Path) -> None:
    h = ui_app
    # Test 2: eigene Fußzeile speichern, schließen, neu starten
    setze_fuss(h, FUSS_EIGEN)
    h.overview.saveFooter()
    assert hinweis(h, "fuss_info").severity == "success"
    gespeichert = lies(config_file)
    assert gespeichert["fusszeile"] == FUSS_EIGEN and gespeichert["fusszeile_explizit"] is True
    zweite = neustart(h)
    assert angezeigter_text(zweite, FUSS) == FUSS_EIGEN
    assert zweite.overview.footer_text() == FUSS_EIGEN
    # Test 3: Standard wiederherstellen, schließen, neu starten
    zweite.overview.restoreDefaultFooter()
    assert zweite.overview.footer_text() == DEFAULT_FOOTER
    assert hinweis(zweite, "fuss_info").message == "Standard-Fußzeile wiederhergestellt."
    dritte = neustart(zweite)
    assert angezeigter_text(dritte, FUSS) == DEFAULT_FOOTER
    assert dritte.overview.footer_text() == DEFAULT_FOOTER


def test_footer_restore_is_undoable(ui_app) -> None:
    h = ui_app
    h.navigate("layout", 0.4)
    setze_fuss(h, FUSS_EIGEN)
    h.overview.restoreDefaultFooter()
    assert h.overview.footer_text() == DEFAULT_FOOTER
    # »Rückgängig« in der Hinweisleiste
    assert hinweis(h, "fuss_info").actions == ["Rückgängig"]
    klicke(aktionsknopf(h, "fuss_info", "Rückgängig"))
    assert h.overview.footer_text() == FUSS_EIGEN
    # und Strg+Z im Textfeld (Rückgängig-Verlauf des Dokuments für Text und Formatierung)
    h.overview.restoreDefaultFooter()
    assert h.overview.footer_text() == DEFAULT_FOOTER
    fokus(h, FUSS)
    strg(h, Qt.Key.Key_Z)
    assert h.overview.footer_text() == FUSS_EIGEN
    assert angezeigter_text(h, FUSS) == FUSS_EIGEN


def test_footer_with_templates(ui_app) -> None:
    h = ui_app
    o = h.overview
    # Test 4: Vorlage mit eigener Fußzeile
    o.vorlage = "Mit Fußzeile"
    setze_fuss(h, FUSS_EIGEN)
    o.saveVorlage()
    assert h.app.state.find_vorlage("Mit Fußzeile")["fusszeile"] == FUSS_EIGEN
    setze_fuss(h, "Etwas anderes")
    waehle_vorlage(h, "Mit Fußzeile")
    assert o.footer_text() == FUSS_EIGEN
    # Vorlagen älterer Versionen ohne Wert, mit leerem Wert oder null: Standard
    h.app.state.vorlagen += [{"name": "Alt ohne"}, {"name": "Alt leer", "fusszeile": ""}, {"name": "Alt null", "fusszeile": None}]
    for name in ("Alt ohne", "Alt leer", "Alt null"):
        setze_fuss(h, "x")
        o.pickVorlage(name)
        assert o.footer_text() == DEFAULT_FOOTER, name
        assert angezeigter_text(h, FUSS) == DEFAULT_FOOTER, name


@pytest.mark.parametrize(
    "alte_konfig,erwartet",
    [
        ({"fusszeile": ""}, "STANDARD"),  # Test 5: alter Bug-Zustand
        ({"fusszeile": None}, "STANDARD"),
        ({}, "STANDARD"),
        ({"fusszeile": "Individuell\n\nAlt"}, "Individuell\n\nAlt"),  # keine Datenverluste
    ],
    indirect=["alte_konfig"],
    ids=["leer", "null", "fehlt", "individuell"],
)
def test_footer_migration_of_old_config(alte_konfig, erwartet: str, config_file: Path, ui_app) -> None:
    h = ui_app
    erwartet = DEFAULT_FOOTER if erwartet == "STANDARD" else erwartet
    pump(0.3)
    assert angezeigter_text(h, FUSS) == erwartet
    assert h.overview.footer_text() == erwartet
    assert h.app.requestClose() is True  # wie beim Schließen des Fensters
    gespeichert = lies(config_file)
    assert gespeichert["fusszeile"] == erwartet and gespeichert["fusszeile_explizit"] is True


def test_customer_record_keeps_footer_unless_it_has_its_own(ui_app) -> None:
    from tools.contract_overview.customers.models import TextBlock

    h = ui_app
    setze_fuss(h, FUSS_EIGEN)
    h.customers._mark_text_baseline()  # gültiger Stand, noch nicht vom Benutzer verändert
    akten = h.customers.customers
    alt = akten.create("Alt AG", "1")  # ohne eigene Fußzeile
    neu = akten.create("Neu AG", "2", footer=TextBlock("Kunde B\n\nGruß"))
    h.customers.apply_customer(alt.id)
    assert h.overview.footer_text() == FUSS_EIGEN
    h.customers.apply_customer(neu.id)
    assert h.overview.footer_text() == "Kunde B\n\nGruß"
    assert angezeigter_text(h, FUSS) == "Kunde B\n\nGruß"
    # Zurück zu einem Kunden ohne eigene Fußzeile: wieder die vorher gültige
    h.customers.apply_customer(alt.id)
    assert h.overview.footer_text() == FUSS_EIGEN


def test_footer_autosave_is_debounced(ui_app, config_file: Path) -> None:
    h = ui_app
    h.navigate("layout", 0.4)
    aufrufe = []
    original = h.app.persist
    h.app.persist = lambda: (aufrufe.append(1), original())[1]
    pump(1.0)  # Start abgeschlossen, ausstehende Speicherungen erledigt
    aufrufe.clear()
    fokus(h, FUSS)
    setze_cursor(h, FUSS, len(h.overview.footer_text()))
    for zeichen in "Nachtrag":
        QTest.keyClick(h.window, zeichen)
        pump(0.05)
    assert aufrufe == []  # nicht bei jedem Tastendruck
    pump(1.2)
    assert len(aufrufe) == 1
    assert lies(config_file)["fusszeile"].endswith("Nachtrag")


def test_pdf_uses_visible_footer(ui_app, excel_file: Path, tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    h = ui_app
    o = h.overview
    o.ziel = str(tmp_path)
    o.pdfOeffnen = False
    o.excel = str(excel_file)
    o.kd = "10042"
    setze_fuss(h, FUSS_EIGEN)
    assert angezeigter_text(h, FUSS) == FUSS_EIGEN
    o.start_pdf()
    assert wait_until(lambda: not o.busy, 90)
    assert hinweis(h, "pdf_info").severity == "success", hinweis(h, "pdf_info").message
    text = pypdf.PdfReader(str(tmp_path / PDF_NAME)).pages[0].extract_text()
    for zeile in ("Eigener kundenspezifischer Text", "Zeile 2", "Zeile 4"):
        assert zeile in text


# --- Aufbau, Seitenwechsel und Resize ohne sichtbare Zwischenzustände ---------------------------


def test_all_pages_prepared_at_startup(ui_app) -> None:
    h = ui_app
    assert h.app.ready
    assert h.app.navigations == 1  # nur die Startseite wurde angezeigt …
    for key in h.PAGES:  # … und doch sind alle Seiten fertig aufgebaut und angeordnet
        platz = h.item(f"page_{key}")
        assert platz is not None and platz.property("item") is not None, key
        assert platz.property("progress") == 1.0, key
        assert platz.width() == platz.parentItem().width() and platz.property("item").width() == platz.width(), key
        if key != h.app.currentPage:
            # verborgen: wird nicht gezeichnet und nimmt keinen Tastaturfokus
            assert not platz.isVisible(), key
            assert not platz.property("item").hasActiveFocus(), key


def test_navigation_shows_finished_page_without_rebuild(ui_app) -> None:
    """Seitenwechsel zeigen die fertige Seite – keine Seite erzeugt ein Element neu. Nur die Tab-Leiste erhält
    beim ersten Öffnen eines Werkzeugs dessen Tab und behält ihn bei jedem weiteren Wechsel."""
    h = ui_app
    seiten = {key: h.item(f"page_{key}").property("item") for key in h.PAGES}
    leiste = h.item("appTabs")

    def ohne_leiste() -> int:
        anzahl, stapel = 0, [h.window.contentItem()]
        while stapel:
            element = stapel.pop()
            if not gleich(element, leiste):
                anzahl += 1
                stapel.extend(element.childItems())
        return anzahl

    anzahl = ohne_leiste()
    gesamt = None
    for runde in range(2):
        for key in ("layout", "settings", "create", "repair", "home", "settings"):
            h.app.navigate(key)
            platz = h.item(f"page_{key}")
            # direkt nach dem Wechsel: dieselbe, fertig angeordnete Seite (kein Laden, kein Neuaufbau)
            assert gleich(platz.property("item"), seiten[key]), key
            assert platz.property("item").width() == platz.parentItem().width(), key
            pump(0.3)
            assert platz.isVisible() and platz.property("opacity") > 0.99, key
        assert ohne_leiste() == anzahl, runde  # kein Element neu erzeugt
        if gesamt is not None:
            assert len(list(elemente(h.window.contentItem()))) == gesamt  # jeder Tab entsteht nur einmal
        gesamt = len(list(elemente(h.window.contentItem())))


def test_resize_applies_breakpoints_immediately_without_animation(app) -> None:
    """Während die Fenstergröße geändert wird, gelten die Spalten sofort – ohne Zwischenzustand (wie in 2.6.1,
    auch mit Animationen). Die Seite hat die ganze Fensterbreite (keine Seitenleiste): zwei Spalten ab 804 px."""
    h = app
    h.navigate("create", 0.4)
    seite = h.item("createPage")
    for breite, spalten in ((1100, 2), (810, 2), (790, 1), (1100, 2)):
        h.window.resize(breite, 700)
        pump(0.03)  # mitten im Ziehen: kürzer als jede Animation
        assert seite.width() == breite, (breite, seite.width())
        assert seite.property("columns") == spalten, (breite, seite.property("contentWidth"))
    pump(0.5)


def test_tab_skips_parked_pages_and_collapsed_areas(ui_app) -> None:
    h = ui_app
    h.navigate("create", 0.4)
    h.item("fieldFirma").forceActiveFocus()
    pump(0.05)
    besucht = []
    for _ in range(40):
        QTest.keyClick(h.window, Qt.Key.Key_Tab)
        besucht.append(h.window.activeFocusItem())
    assert any(gleich(e, h.item("fieldKd")) for e in besucht)  # Tab wandert durch das Formular
    for key in h.PAGES:
        if key == "create":
            continue
        verborgen = h.item(f"page_{key}")
        assert not any(liegt_in(e, verborgen) for e in besucht), key
    # Die Empfänger-Auswahl erscheint erst bei mehreren Empfängern – vorher kein Tab-Ziel
    auswahl = element(h.item("page_create"), label="Rechnungsempfänger wählen")
    assert not auswahl.isVisible()
    assert not any(gleich(e, auswahl) for e in besucht)


# --- Rich-Text-Editor -------------------------------------------------------------------------------


def test_selection_gets_only_the_chosen_format(ui_app) -> None:
    h = ui_app
    h.navigate("layout", 0.4)
    kopf = h.overview.header
    fett = leistenknopf(h, KOPF, "Fett (Strg+B)")
    setze_kopf(h, "Bitte beachten Sie die Hinweise")
    markiere(h, KOPF, 0, 18)  # »Bitte beachten Sie«
    klicke(fett)
    assert [(t, s["bold"]) for t, s in runs(kopf.rich())] == [("Bitte beachten Sie", True), (" die Hinweise", False)]
    # Leiste: Cursor im fetten Bereich → Fett aktiv; daneben → aus; gemischte Markierung → »gemischt«
    setze_cursor(h, KOPF, 5)
    assert kopf.bold is True and fett.property("active") is True and fett.property("mixed") is False
    setze_cursor(h, KOPF, 25)
    assert kopf.bold is False and fett.property("active") is False and fett.property("mixed") is False
    markiere(h, KOPF, 10, 25)
    assert kopf.bold is False and fett.property("active") is False
    assert kopf.mixed == ["bold"] and fett.property("mixed") is True  # weder an noch aus (wie 2.6.1)
    assert leistenknopf(h, KOPF, "Kursiv (Strg+I)").property("mixed") is False


def test_format_without_selection_applies_to_new_text(ui_app) -> None:
    h = ui_app
    h.navigate("layout", 0.4)
    kopf = h.overview.header
    setze_kopf(h, "Anfang ")
    fokus(h, KOPF)
    setze_cursor(h, KOPF, len("Anfang "))
    strg(h, Qt.Key.Key_B)
    assert kopf.bold is True and leistenknopf(h, KOPF, "Fett (Strg+B)").property("active") is True
    tippe(h, "fett")
    assert [(t, s["bold"]) for t, s in runs(kopf.rich())] == [("Anfang ", False), ("fett", True)]
    # Cursor bewegt: das zuvor gewählte Eingabeformat gilt nicht mehr
    setze_cursor(h, KOPF, 2)
    tippe(h, "x")
    assert kopf.text() == "Anxfang fett"
    assert not kopf.rich().style_at(2).bold


def test_shortcuts_undo_and_redo(ui_app) -> None:
    h = ui_app
    h.navigate("layout", 0.4)
    kopf = h.overview.header
    setze_kopf(h, "Wort eins")
    fokus(h, KOPF)
    markiere(h, KOPF, 0, 4)
    for key in (Qt.Key.Key_B, Qt.Key.Key_I, Qt.Key.Key_U):
        strg(h, key)
    stil = kopf.rich().style_at(0)
    assert stil.bold and stil.italic and stil.underline
    strg(h, Qt.Key.Key_Z)  # Unterstrichen zurück
    stil = kopf.rich().style_at(0)
    assert stil.bold and stil.italic and not stil.underline
    strg(h, Qt.Key.Key_Y)  # wieder da
    assert kopf.rich().style_at(0).underline
    # Text-Rückgängig: Tippen wird zu einem Schritt zusammengefasst
    setze_cursor(h, KOPF, len("Wort eins"))
    tippe(h, " zwei")
    assert kopf.text().endswith(" zwei")
    strg(h, Qt.Key.Key_Z)
    assert kopf.text() == "Wort eins"


def test_toolbar_font_size_color_and_alignment(ui_app) -> None:
    h = ui_app
    h.navigate("layout", 0.4)
    fuss = h.overview.footer
    editor = h.item(FUSS)
    schrift = element(editor, label="Schriftart")
    groesse = element(editor, label="Schriftgröße")
    farben = [o for o in editor.findChildren(QObject) if qml_typ(o).startswith("PColorFlyout")][0]
    setze_fuss(h, "Absatz eins\nAbsatz zwei")
    markiere(h, FUSS, 0, 6)
    waehle(schrift, fuss.families.index("Times"))
    markiere(h, FUSS, 0, 6)
    waehle(groesse, fuss.sizes.index("12"))
    markiere(h, FUSS, 0, 6)
    assert QMetaObject.invokeMethod(farben, "picked", Q_ARG(str, ROT))  # Farbe in der Farbauswahl gewählt
    pump(0.05)
    setze_cursor(h, FUSS, len("Absatz eins\n") + 3)
    klicke(leistenknopf(h, FUSS, "Rechtsbündig (Strg+R)"))
    rich = fuss.rich()
    stil = rich.style_at(0)
    assert (stil.font, stil.size, stil.color) == ("Times", 12, ROT)
    assert rich.style_at(7) == fuss.default
    assert rich.aligns == ["center", "right"]
    setze_cursor(h, FUSS, 2)
    assert schrift.property("displayText") == "Times" and groesse.property("displayText") == "12"
    assert leistenknopf(h, FUSS, "Zentriert (Strg+E)").property("active") is True
    assert leistenknopf(h, FUSS, "Rechtsbündig (Strg+R)").property("active") is False


def test_toolbar_wraps_when_narrow(ui_app) -> None:
    h = ui_app
    h.navigate("layout")
    h.window.resize(780, 700)
    pump(0.8)
    editor = h.item(FUSS)
    leiste = finde(editor, lambda e: e.inherits("QQuickFlow"))[0]
    breite = leiste.width()
    for kind in leiste.childItems():
        if kind.isVisible():
            assert kind.x() + kind.width() <= breite + 1, qml_typ(kind)  # keine kaputte horizontale Anordnung
    assert textfeld(h, FUSS).width() <= leiste.width() + 2


# --- Persistenz der Formatierung ---------------------------------------------------------------------


def formatiere_fuss_und_kopf(h) -> tuple[RichText, RichText]:
    h.navigate("layout", 0.4)
    fuss = h.overview.footer
    setze_fuss(h, "Kundennummer: {kd}\nZweiter Absatz")
    markiere(h, FUSS, 14, 18)  # »{kd}«
    fuss.toggle("bold")
    fuss.setColor(ROT)
    setze_cursor(h, FUSS, len("Kundennummer: {kd}\n") + 2)
    fuss.setAlignment("right")
    kopf = h.overview.header
    setze_kopf(h, "Kopf kursiv")
    markiere(h, KOPF, 5, 11)
    kopf.toggle("italic")
    pump(0.1)
    fuss_rich, kopf_rich = fuss.rich(), kopf.rich()
    assert fuss_rich.style_at(14).bold and fuss_rich.style_at(14).color == ROT and not fuss_rich.style_at(0).bold
    assert fuss_rich.aligns == ["center", "right"]
    assert kopf_rich.style_at(5).italic and not kopf_rich.style_at(0).italic
    return fuss_rich, kopf_rich


def test_rich_header_footer_survive_restart(ui_app, config_file: Path) -> None:
    fuss, kopf = formatiere_fuss_und_kopf(ui_app)
    pump(1.2)  # verzögertes automatisches Speichern
    gespeichert = lies(config_file)
    assert gespeichert["fusszeile"] == fuss.text and gespeichert["kopfzeile"] == kopf.text  # reiner Text bleibt
    assert gespeichert["fusszeile_format"]["text"] == fuss.text and gespeichert["kopfzeile_format"]["text"] == kopf.text
    zweite = neustart(ui_app)
    assert zweite.overview.footer.attached and zweite.overview.header.attached
    assert zweite.overview.footer_rich() == fuss
    assert zweite.overview.header_rich() == kopf


def test_restore_default_resets_text_and_formatting(ui_app) -> None:
    formatiere_fuss_und_kopf(ui_app)
    ui_app.overview.restoreDefaultFooter()
    assert ui_app.overview.footer_rich() == default_footer_rich()
    zweite = neustart(ui_app)
    assert zweite.overview.footer_rich() == default_footer_rich()


def test_template_keeps_formatting_across_restart(ui_app) -> None:
    h = ui_app
    fuss, kopf = formatiere_fuss_und_kopf(h)
    h.overview.vorlage = "Formatiert"
    h.overview.saveVorlage()
    setze_fuss(h, "anders")
    setze_kopf(h, "")
    zweite = neustart(h)
    waehle_vorlage(zweite, "Formatiert")
    assert zweite.overview.footer_rich() == fuss
    assert zweite.overview.header_rich() == kopf


def test_text_block_keeps_formatting_across_restart(ui_app) -> None:
    h = ui_app
    fuss, _kopf = formatiere_fuss_und_kopf(h)
    h.overview.baustein = "Gruß formatiert"
    h.overview.saveFooter()
    zweite = neustart(h)
    setze_fuss(zweite, "etwas anderes")
    waehle_baustein(zweite, "Gruß formatiert")
    assert zweite.overview.footer_rich() == fuss
    # ältere Bausteine (nur Text) laden weiterhin – mit Standardformat
    zweite.app.state.bausteine.append({"name": "Alt", "text": "Nur Text"})
    zweite.overview.pickBaustein("Alt")
    assert zweite.overview.footer_text() == "Nur Text"
    assert zweite.overview.footer_rich().styles == [zweite.overview.footer.default] * len("Nur Text")


def test_customer_record_keeps_formatting(ui_app) -> None:
    h = ui_app
    fuss, kopf = formatiere_fuss_und_kopf(h)
    h.overview.firma = "Format AG"
    h.overview.kd = "777"
    h.customers.save_as_customer()  # bewusst als Kundenakte speichern (samt Formatierung)
    ident = h.customers.active_customer().id
    zweite = neustart(h)
    assert zweite.customers.active_customer() is not None and zweite.customers.active_customer().id == ident
    setze_fuss(zweite, "x")
    setze_kopf(zweite, "y")
    zweite.customers.apply_customer(ident)
    # vom Benutzer geänderte Texte werden nicht still überschrieben …
    assert zweite.overview.footer_text() == "x" and zweite.overview.header_text() == "y"
    assert "Texte der Kundenakte verwenden" in hinweis(zweite, "kunde_info").actions
    # … sondern auf Wunsch übernommen – mit Formatierung
    klicke(aktionsknopf(zweite, "kunde_info", "Texte der Kundenakte verwenden"))
    assert zweite.overview.footer_rich() == fuss and zweite.overview.header_rich() == kopf


@pytest.mark.parametrize("alte_konfig", [{"kopfzeile": "Alte Kopfzeile", "fusszeile": "Alte Fußzeile"}], indirect=True, ids=["2.2.0"])
def test_old_config_with_plain_header_and_footer(alte_konfig, config_file: Path, ui_app) -> None:
    h = ui_app
    pump(0.3)
    assert angezeigter_text(h, KOPF) == "Alte Kopfzeile" and angezeigter_text(h, FUSS) == "Alte Fußzeile"
    assert h.overview.header_text() == "Alte Kopfzeile" and h.overview.footer_text() == "Alte Fußzeile"
    kopf, fuss = h.overview.header_rich(), h.overview.footer_rich()
    assert set(kopf.styles) == {HEADER_STYLE} and kopf.aligns == ["left"]
    assert set(fuss.styles) == {FOOTER_STYLE} and fuss.aligns == ["center"]
    assert h.app.requestClose() is True
    gespeichert = lies(config_file)
    assert gespeichert["kopfzeile"] == "Alte Kopfzeile" and gespeichert["fusszeile"] == "Alte Fußzeile"
    assert gespeichert["kopfzeile_format"]["text"] == "Alte Kopfzeile"


def test_fresh_config_default_footer_in_pdf_and_after_restart(ui_app, excel_file: Path, tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    h = ui_app
    o = h.overview
    assert o.footer_text() == DEFAULT_FOOTER
    o.ziel = str(tmp_path)
    o.pdfOeffnen = False
    o.use_excel(str(excel_file))
    assert wait_until(lambda: o.readyKind == "success", 60), o.readyText
    o.start_pdf()
    assert wait_until(lambda: not o.busy, 90)
    seite = pypdf.PdfReader(str(tmp_path / PDF_NAME)).pages[0]
    text = " ".join(seite.extract_text().split())
    for absatz in DEFAULT_FOOTER.split("\n"):
        if absatz:
            assert absatz in text
    schriften = set()
    seite.extract_text(visitor_text=lambda t, _c, _m, f, s: schriften.add((str(f.get("/BaseFont", "")), round(s, 1))) if "Mehrwertsteuer" in t and f else None)
    assert schriften == {("/Helvetica", 8.0)}
    zweite = neustart(h)
    assert zweite.overview.footer_text() == DEFAULT_FOOTER


# --- Excel-Analyse, Bereitschaft und Abläufe ------------------------------------------------------------


def excel_ohne_kunde(tmp_path: Path, zeilen: list[list], name: str = "liste.xlsx") -> Path:
    """Wie die echten Listen: Verträge und Empfänger-E-Mail, aber keine Kundennummer/Firma."""
    spalten = [c for c in COLUMNS if c not in ("Kundennummer", "Firmenname")]
    return write_excel(tmp_path / name, zeilen, spalten)


def test_excel_analysis_shows_only_real_values(ui_app, tmp_path: Path) -> None:
    h = ui_app
    o = h.overview
    pfad = excel_ohne_kunde(
        tmp_path,
        [
            ["V-1", datetime(2023, 1, 1), "jährlich", 10.0, "Sofort", "Eins", "rechnung@firma-mueller.de", "Aktiv"],
            ["V-2", datetime(2022, 1, 1), "jährlich", 20.0, "Sofort", "Zwei", "rechnung@firma-mueller.de", "Inaktiv"],
        ],
    )
    h.navigate("create", 0.3)
    o.use_excel(str(pfad))
    info = hinweis(h, "info_excel")
    assert wait_until(lambda: info.severity == "success", 60)
    pump(0.3)
    fakten = {fakt["label"]: fakt["value"] for fakt in o.facts}
    # Vertragszahlen nur in der Statuszeile (2.5), darunter nur zusätzliche Angaben
    assert info.message == "1 aktiver Vertrag · 1 inaktiv ausgeblendet"
    assert "Aktive Verträge" not in fakten and "Ausgeblendet (inaktiv)" not in fakten
    assert o.mailValue == "rechnung@firma-mueller.de"
    # nichts aus der E-Mail-Adresse erraten
    assert "Kundennummer" not in fakten and "Firmenname" not in fakten
    assert o.kd == "" and o.firma == ""
    # Details unter der Prüfung sind aufgeklappt und zeigen den Empfänger
    assert o.detailsVisible
    empfaenger = finde(h.item("page_create"), lambda e: e.inherits("QQuickText") and e.property("text") == "rechnung@firma-mueller.de")
    assert empfaenger and empfaenger[0].isVisible()


def test_missing_columns_are_reported(ui_app, tmp_path: Path) -> None:
    h = ui_app
    o = h.overview
    spalten = ["Vertrag-Nr.", "Beginnt am", "Abrechnungszyklus", "Netto [€]", "Bemerkung", "Anwenderstatus"]
    pfad = write_excel(tmp_path / "ohne.xlsx", [["V-1", datetime(2023, 1, 1), "jährlich", 10.0, "Eins", "Aktiv"]], spalten)
    o.kd = "1"
    o.use_excel(str(pfad))
    info = hinweis(h, "info_excel")
    assert wait_until(lambda: info.severity == "error", 60)
    assert "Zahlungsart" in info.message
    pump(0.2)
    assert o.readyKind == "critical" and "Zahlungsart" in o.readyText
    zeile = h.item("readiness")
    assert zeile.property("kind") == "critical" and zeile.property("text") == o.readyText


def test_readiness_states(ui_app, excel_file: Path, tmp_path: Path) -> None:
    h = ui_app
    o = h.overview
    zeile = h.item("readiness")
    o.excel = ""
    o.kd = ""
    pump(0.1)
    assert o.readyKind in ("caution", "critical")
    assert "Excel-Datei fehlt" in o.readyText and "Kundennummer fehlt" in o.readyText
    assert zeile.property("text") == o.readyText
    o.ziel = str(tmp_path)
    o.use_excel(str(excel_file))
    assert wait_until(lambda: o.readyKind == "success", 60), o.readyText
    assert o.readyText == "Bereit zum Erstellen"
    o.kd = ""
    pump(0.1)
    assert o.readyText == "Kundennummer fehlt"
    h.navigate("create", 0.3)
    assert zeile.property("clickable") is True
    assert QMetaObject.invokeMethod(zeile, "activated")  # Klick auf die Anzeige: zum Feld springen
    pump(0.1)
    feld = h.item("fieldKd")
    assert o.errors.get("kd") is True and feld.property("invalid") is True
    assert feld.hasActiveFocus()
    o.kd = "10042"
    o.breite = "abc"
    pump(0.1)
    assert o.readyText == "Logo-Breite ungültig"
    o.breite = "62"
    o.logo = str(tmp_path / "fehlt.png")
    pump(0.1)
    assert o.readyText == "Logo-Datei nicht gefunden"
    o.useDefaultLogo()
    datei = tmp_path / "keinordner.txt"
    datei.write_text("x", encoding="utf-8")
    o.ziel = str(datei)
    pump(0.1)
    assert o.readyText == "Zielordner nicht erreichbar"
    o.ziel = str(tmp_path / "neu" / "unterordner")  # wird beim Erstellen angelegt
    pump(0.1)
    assert o.readyKind == "success"


def test_multiple_recipients_readiness_and_choice(ui_app, tmp_path: Path) -> None:
    h = ui_app
    o = h.overview
    pfad = excel_ohne_kunde(
        tmp_path,
        [
            ["V-1", datetime(2023, 1, 1), "jährlich", 10.0, "Sofort", "Eins", "a@x.de", "Aktiv"],
            ["V-2", datetime(2023, 2, 1), "jährlich", 20.0, "Sofort", "Zwei", "b@x.de", "Aktiv"],
        ],
    )
    h.navigate("create", 0.3)
    o.kd = "5"
    o.mail = ""
    o.use_excel(str(pfad))
    assert wait_until(lambda: hinweis(h, "info_excel").severity == "success", 60)
    pump(0.3)
    assert o.readyText == "Bitte Rechnungsempfänger auswählen"
    auswahl = element(h.item("page_create"), label="Rechnungsempfänger wählen")
    assert o.mailValue == "2 erkannt" and auswahl.isVisible()
    waehle(auswahl, 1)
    pump(0.1)
    assert o.mail == "b@x.de"
    assert o.readyKind == "success"
    assert auswahl.property("displayText") == "b@x.de"


def test_pdf_completion_actions_copy_and_new_overview(ui_app, excel_file: Path, tmp_path: Path) -> None:
    h = ui_app
    o = h.overview
    h.navigate("create", 0.3)
    o.ziel = str(tmp_path)
    o.pdfOeffnen = False
    o.use_excel(str(excel_file))
    assert wait_until(lambda: o.readyKind == "success", 60)
    fuss_vorher = o.footer_rich()
    logo_vorher = o.logo
    o.start_pdf()
    assert wait_until(lambda: not o.busy, 90)
    info = hinweis(h, "pdf_info")
    assert info.severity == "success"
    pump(0.3)
    knoepfe = aktionsknoepfe(h, "pdf_info")
    assert list(knoepfe) == ["Öffnen", "Ordner öffnen", "Pfad kopieren", "Neue Übersicht"]
    assert all(knopf.isVisible() for knopf in knoepfe.values())
    klicke(knoepfe["Pfad kopieren"])
    assert zwischenablage() == str(tmp_path / PDF_NAME)
    klicke(knoepfe["Neue Übersicht"])
    pump(0.2)
    assert (o.firma, o.kd, o.mail, o.excel) == ("", "", "", "")
    assert o.logo == logo_vorher and o.ziel == str(tmp_path)
    assert o.footer_rich() == fuss_vorher
    assert "Excel-Datei fehlt" in o.readyText
    # Rückgängig stellt die Arbeitsdaten wieder her
    klicke(aktionsknopf(h, "kunde_info", "Rückgängig"))
    pump(0.2)
    assert o.kd == "10042" and o.excel == str(excel_file)


def test_autosave_of_all_fields_is_debounced(ui_app, config_file: Path, tmp_path: Path) -> None:
    h = ui_app
    o = h.overview
    aufrufe = []
    original = h.app.persist
    h.app.persist = lambda: (aufrufe.append(1), original())[1]
    pump(1.0)
    aufrufe.clear()
    werte = {"firma": "Auto GmbH", "kd": "4711", "mail": "a@b.de", "ziel": str(tmp_path), "titel": "Übersicht", "breite": "70"}
    for name, wert in werte.items():
        setattr(o, name, wert)
        pump(0.05)
    assert aufrufe == []
    pump(1.2)
    assert len(aufrufe) == 1
    gespeichert = lies(config_file)
    assert gespeichert["firmenname"] == "Auto GmbH" and gespeichert["kundennummer"] == "4711"
    assert gespeichert["rechnungsempfaenger"] == "a@b.de" and gespeichert["zielordner"] == str(tmp_path)
    assert gespeichert["titel"] == "Übersicht" and gespeichert["logo_breite"] == "70"
    assert not [p for p in config_file.parent.iterdir() if p.name.endswith(".tmp")]  # atomar geschrieben


def test_drag_and_drop_highlight_and_drop(ui_app, excel_file: Path, tmp_path: Path) -> None:
    from PySide6.QtQml import QQmlProperty

    h = ui_app
    o = h.overview
    info = hinweis(h, "info_excel")
    h.navigate("create", 0.3)
    karte = element(h.item("page_create"), title="Dateien")
    assert h.app.dragEnter([excel_file.as_uri()]) is True
    pump(0.3)
    # Die Karte »Dateien« erhält den Akzentrahmen
    assert o.dropHighlight is True and QQmlProperty.read(karte, "border.width") == 2
    assert QQmlProperty.read(karte, "border.color").name().lower() == h.theme.colors["accent"].lower()
    assert info.message.startswith("Loslassen")
    h.app.dragLeave()
    pump(0.05)
    assert o.dropHighlight is False and QQmlProperty.read(karte, "border.width") == 1
    assert not info.message.startswith("Loslassen")
    assert h.app.dragEnter([str(tmp_path / "notiz.txt")]) is False  # keine Excel-Datei: keine Hervorhebung
    assert o.dropHighlight is False
    h.app.dragLeave()
    h.navigate("layout", 0.3)
    h.app.drop(["C:/nicht/excel.txt", str(excel_file)])
    assert h.app.currentPage == "create" and o.excel == str(excel_file)
    assert wait_until(lambda: info.severity == "success", 60)
    h.app.drop(["C:/bild.png"])
    assert info.severity == "warning"


def test_file_dialogs_start_in_last_folder(ui_app, excel_file: Path, monkeypatch) -> None:
    from qtapp import files

    h = ui_app
    gesehen = {}
    original = files.open_file

    def auswahl(title: str, directory: str, filters: str) -> str:
        gesehen["ordner"] = directory
        return original(title, directory, filters)

    monkeypatch.setattr(files, "open_file", auswahl)
    h.navigate("create", 0.3)
    h.overview.excel = ""
    files.RESPONSES.append(str(excel_file))
    strg(h, Qt.Key.Key_O)  # Strg+O: Excel öffnen
    assert h.overview.excel == str(excel_file)
    h.overview.excel = ""
    files.RESPONSES.append(str(excel_file))
    h.overview.pickExcel()
    assert gesehen["ordner"] == str(excel_file.parent)
    zweite = neustart(h)
    assert zweite.app.initial_dir("excel", "") == str(excel_file.parent)
    zweite.overview.excel = ""
    gesehen.clear()
    files.RESPONSES.append(str(excel_file))
    zweite.overview.pickExcel()
    assert gesehen["ordner"] == str(excel_file.parent)


def test_copy_path_from_file_rows(ui_app, excel_file: Path) -> None:
    h = ui_app
    h.navigate("create", 0.3)
    h.overview.excel = str(excel_file)
    kopieren = element(h.item("page_create"), tip="Pfad der Excel-Datei kopieren")
    klicke(kopieren)
    assert zwischenablage() == str(excel_file)
    assert h.app.statusText.startswith("Pfad kopiert")
    h.overview.excel = ""
    klicke(kopieren)
    assert h.app.statusText == "Kein Pfad zum Kopieren vorhanden."


# --- Ansichten und Karten (3.1.0-beta.3) ---------------------------------------------------------
def _labels(bar) -> tuple[dict[str, float], object]:
    """Beschriftungen der Ansichtswahl → waagerechte Mitte (Szene); dazu ihre Markierung."""
    found, marker, stack = {}, None, [bar]
    while stack:
        item = stack.pop()
        text = item.property("text") if item.metaObject().className().startswith("QQuickText") else None
        if text and item.isVisible():
            found[text] = item.mapToScene(QPointF(item.width() / 2, 0)).x()
        if item.objectName() == "selectorIndicator":
            marker = item
        stack.extend(item.childItems())
    return found, marker


def test_view_bar_marks_the_current_view_and_keeps_its_place(ui_app) -> None:
    """Ansichten von »Vertragsübersichten«: Die Markierung steht unter der gewählten Ansicht (bis 3.1.0-beta.2
    fehlte sie), und kein Eintrag springt beim Wechsel – die fette Schrift der gewählten Ansicht ist eingerechnet."""
    h = ui_app
    h.app.dialogs.shutdown()
    seen = []
    for key, label in (("create", "Übersicht erstellen"), ("layout", "Darstellung"), ("batch", "Stapel")):
        h.navigate(key, 0.6)
        bar = next(item for item in h.items("contractViews") if item.isVisible())
        labels, marker = _labels(bar)
        assert marker is not None and marker.isVisible() and marker.width() >= 16
        assert abs(marker.mapToScene(QPointF(marker.width() / 2, 0)).x() - labels[label]) < 1.5
        seen.append(labels)
    for labels in seen[1:]:  # gleiche Lage – höchstens Rundung der zentrierten Beschriftung
        assert labels.keys() == seen[0].keys()
        assert all(abs(labels[name] - seen[0][name]) < 1 for name in labels)


def test_card_header_button_sits_on_the_title_line(ui_app) -> None:
    """Kartenkopf ohne Untertitel: Schaltflächen rechts stehen mittig zur Titelzeile (»Kundendaten leeren«
    lag 6 px tiefer als der Titel)."""
    h = ui_app
    h.app.dialogs.shutdown()
    h.navigate("create", 0.6)
    page = h.item("page_create")
    button = title = None
    stack = [page]
    while stack:
        item = stack.pop()
        if item.isVisible() and item.property("tip") == "Kundendaten leeren":
            button = item
        if item.isVisible() and item.metaObject().className().startswith(("QQuickText", "PText")) and item.property("text") == "Kundendaten":
            title = item
        stack.extend(item.childItems())
    assert button is not None and title is not None
    middle = lambda item: item.mapToScene(QPointF(0, item.height() / 2)).y()  # noqa: E731
    assert abs(middle(button) - middle(title)) <= 2
