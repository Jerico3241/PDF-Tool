"""Qt-Oberfläche: Vorlagen 2.0 (Tests 95–97 der Vorgabe).

* Ansicht »Vorlagen«: Liste, Suche, Detail, Anwenden, Umbenennen, Duplizieren, Standard, Löschen.
* »Darstellung«: geladene Vorlage, »Vorlage geändert«, Aktualisieren, Verwerfen, Als neue Vorlage
  speichern – ohne sichtbaren Neuaufbau, mit Vorschau-Aktualisierung.
* Standardvorlage für jede neue Übersicht (rückgängig machbar).
* Verweise (Kundenakte, Stapel, Standard) werden beim Löschen kontrolliert gelöst, beim
  Umbenennen bleiben sie bestehen (Verweis per ID).
* Der Namensdialog (QML »text_input«) mit echter Eingabe.

Nach jedem Test darf die QML-Engine keine Warnung gemeldet haben.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest

from conftest import neustart, pump, wait_until
from test_qt_contracts import setze_kopf
from test_qt_customers import antworten, hinweis


def vorlage_speichern(h, name: str, titel: str = "", fmt: str = "") -> str:
    """Darstellung setzen und als neue Vorlage speichern – Rückgabe: ID."""
    o = h.overview
    if titel:
        o.titel = titel
    if fmt:
        o.setFormat(fmt)
    pump(0.05)
    assert o.saveAsTemplate(name) is True
    template = h.app.state.templates.by_name(name)
    assert template is not None and o.vorlageId == template.id
    return template.id


def sichtbar(h, name: str) -> bool:
    item = h.item(name)
    return item is not None and bool(item.isVisible()) and item.property("opacity") > 0.5


def test_95_template_list_detail_and_apply(ui_app) -> None:
    h = ui_app
    o, t = h.overview, h.templates
    h.navigate("templates", 0.3)
    assert t.total == 0 and sichtbar(h, "templatesPage")
    ident = vorlage_speichern(h, "Energie", titel="Energie-Übersicht", fmt="quer")
    vorlage_speichern(h, "Bank", titel="Bank-Übersicht")
    pump(0.2)
    assert t.total == 2 and t.countText == "2 Vorlagen"
    assert [t.listModel.get(i)["name"] for i in range(t.listModel.count)] == ["Bank", "Energie"]  # alphabetisch
    t.search = "ener"
    assert wait_until(lambda: t.listModel.count == 1, 3) and t.countText == "1 von 2 Vorlagen"
    t.search = ""
    assert wait_until(lambda: t.listModel.count == 2, 3)
    # Detail
    t.showDetail(ident)
    pump(0.3)
    assert t.detailName == "Energie"
    facts = {fact["label"]: fact["value"] for fact in t.detailFacts}
    assert facts["Seitenformat"] == "A4 Querformat" and facts["Titel"] == "Energie-Übersicht"
    assert facts["Regelwerk"] == "keines"
    # Anwenden: Darstellung folgt, Hinweis mit »Zur Darstellung«
    o.titel = "Etwas anderes"
    o.setFormat("hoch")
    pump(0.1)
    t.apply(ident)
    assert o.titel == "Energie-Übersicht" and o.format == "quer" and o.vorlageId == ident and not o.templateModified
    assert "Zur Darstellung" in list(hinweis(h, "vorlagen_verwaltung").actions)
    t.showList()
    pump(0.3)
    assert t.detailId == ""


def test_96_template_modified_update_discard_and_save_as_new(ui_app) -> None:
    h = ui_app
    o = h.overview
    h.navigate("layout", 0.3)
    ident = vorlage_speichern(h, "Standard Energie", titel="Titel A")
    pump(0.1)
    assert not o.templateModified and not sichtbar(h, "templateModifiedBadge")
    # Änderung der Darstellung → »Vorlage geändert« (gesammelt, ohne Neuaufbau der Seite)
    seite = h.item("page_layout").property("item")
    o.titel = "Titel B"
    assert wait_until(lambda: o.templateModified, 3)
    pump(0.4)
    assert h.item("page_layout").property("item") == seite
    assert h.item("templateModifiedBadge").property("text") == "Vorlage geändert"
    assert sichtbar(h, "updateTemplate")
    # Zurück auf den Stand der Vorlage: nicht mehr geändert
    o.titel = "Titel A"
    assert wait_until(lambda: not o.templateModified, 3)
    # Verwerfen
    o.titel = "Titel C"
    assert wait_until(lambda: o.templateModified, 3)
    o.discardTemplateChanges()
    assert o.titel == "Titel A" and wait_until(lambda: not o.templateModified, 3)
    # Aktualisieren: gleiche ID, neuer Inhalt
    o.titel = "Titel D"
    assert wait_until(lambda: o.templateModified, 3)
    o.updateTemplate()
    assert not o.templateModified
    template = h.app.state.templates.get(ident)
    assert template.layout.titel == "Titel D" and template.name == "Standard Energie"
    # Als neue Vorlage speichern: neue ID, die alte bleibt unverändert
    o.titel = "Titel E"
    assert o.templateNameProblem("Standard Energie") != ""
    assert o.saveAsTemplate("standard energie") is False  # Name schon vergeben (ohne Groß-/Kleinschreibung)
    assert o.saveAsTemplate("Energie 2") is True
    neu = h.app.state.templates.by_name("Energie 2")
    assert neu.id != ident and o.vorlageId == neu.id and h.app.state.templates.get(ident).layout.titel == "Titel D"
    # Kopf- und Fußzeile gehören zur Vorlage
    o.updateTemplate()
    setze_kopf(h, "Neue Kopfzeile")
    assert wait_until(lambda: o.templateModified, 3)


def test_96_template_state_survives_restart(ui_app, config_file: Path) -> None:
    h = ui_app
    ident = vorlage_speichern(h, "Bleibt", titel="Titel A")
    h.overview.titel = "Titel B"
    assert wait_until(lambda: h.overview.templateModified, 3)
    neu = neustart(h)
    pump(0.3)
    assert neu.overview.vorlageId == ident and neu.overview.templateLabel == "Bleibt"
    assert neu.overview.templateModified  # Abweichung bleibt nach dem Neustart sichtbar
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["vorlage_aktiv"] == ident and "vorlagen" not in data or isinstance(data.get("vorlagen"), list)
    assert (Path(config_file).parent / "vorlagen" / f"{ident}.json").is_file()


def test_97_rename_duplicate_default_and_delete_with_references(ui_app, monkeypatch, config_file: Path) -> None:
    h = ui_app
    o, t, b = h.overview, h.templates, h.batch
    ident = vorlage_speichern(h, "Alt", titel="Titel A")
    b.setDefaultTemplate("Alt")  # Vorlage des Stapels (Verweis per ID)
    assert b.settings.template == ident
    # Umbenennen über den Namensdialog
    gestellt = antworten(monkeypatch, "text_input", "primary", {"value": "Neu"})
    t.showDetail(ident)
    t.rename(ident)
    assert gestellt and gestellt[-1]["data"]["value"] == "Alt"
    assert h.app.state.templates.get(ident).name == "Neu" and o.templateLabel == "Neu" and b.settings.template == ident
    assert t.detailName == "Neu"
    # Duplizieren: neue ID, eindeutiger Name
    t.duplicate(ident)
    kopie = h.app.state.templates.by_name("Neu – Kopie")
    assert kopie is not None and kopie.id != ident and t.detailId == kopie.id
    # Standardvorlage
    t.setDefault(ident, True)
    assert o.defaultTemplate == ident and t.listModel.get(t.listModel.indexOf(ident))["standard"] is True
    h.app.persist()
    assert json.loads(config_file.read_text(encoding="utf-8"))["vorlage_standard"] == ident
    # Löschen (Rückfrage nennt die Verwendung): Verweise werden gelöst, die Darstellung bleibt
    titel = o.titel
    t.showDetail(ident)
    t.remove(ident)
    frage = h.app.dialogs.history[-1]
    assert frage["kind"] == "confirm" and "Standardvorlage" in frage["message"] and "Stapel" in frage["message"]
    assert h.app.state.templates.get(ident) is None and t.detailId == ""
    assert o.defaultTemplate == "" and o.vorlageId == "" and b.settings.template == "" and o.titel == titel
    assert h.app.state.templates.get(kopie.id) is not None  # die Kopie bleibt


def test_default_template_for_new_overview_is_undoable(ui_app) -> None:
    h = ui_app
    o = h.overview
    ident = vorlage_speichern(h, "Standard", titel="Standardtitel", fmt="quer")
    o.setDefaultTemplate(ident)
    o.detachTemplate()
    o.titel = "Eigener Titel"
    o.setFormat("hoch")
    o.firma = "Muster GmbH"
    pump(0.1)
    o.new_overview()
    assert o.titel == "Standardtitel" and o.format == "quer" and o.vorlageId == ident and o.firma == ""
    assert "Standardvorlage „Standard“ geladen" in hinweis(h, "kunde_info").message
    o._undo_new_overview()
    assert o.titel == "Eigener Titel" and o.format == "hoch" and o.vorlageId == "" and o.firma == "Muster GmbH"


def test_text_input_dialog_in_qml(ui_app, monkeypatch) -> None:
    """Ohne Autoantwort: Der Namensdialog erscheint in QML mit markiertem Namen; Tippen ersetzt ihn,
    ein leeres Feld lässt sich nicht bestätigen, Eingabe bestätigt."""
    from qtapp import dialogs

    h = ui_app
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    seen = {}

    def tippen() -> None:
        feld = h.item("dialogTextInput")
        seen["value"] = feld.property("text")
        seen["selected"] = feld.property("selectedText")
        seen["focus"] = feld.property("activeFocus")
        QTest.keyClick(h.window, Qt.Key.Key_Backspace)  # markierten Namen löschen
        pump(0.05)
        seen["empty_acceptable"] = feld.parentItem().property("acceptable")
        QTest.keyClick(h.window, Qt.Key.Key_Return)  # leer: bleibt offen
        pump(0.05)
        seen["still_open"] = h.app.dialogs.open
        for zeichen in "Neuer Name":
            QTest.keyClick(h.window, zeichen)
        pump(0.05)
        seen["acceptable"] = feld.parentItem().property("acceptable")
        QTest.keyClick(h.window, Qt.Key.Key_Return)

    def notausgang() -> None:  # nie endlos warten, falls die Eingabe nicht wirkt
        if h.app.dialogs.open:
            h.app.dialogs.answer(h.app.dialogs.request["id"], "close", {})

    QTimer.singleShot(400, tippen)
    QTimer.singleShot(6000, notausgang)
    answer, result = h.app.dialogs.ask("text_input", "Vorlage umbenennen", primary="Umbenennen", data={"label": "Neuer Name", "value": "Alter Name"})
    assert seen["value"] == "Alter Name" and seen["selected"] == "Alter Name" and seen["focus"] is True
    assert seen["empty_acceptable"] is False and seen["still_open"] is True and seen["acceptable"] is True
    assert answer == "primary" and result == {"value": "Neuer Name"}
    pump(0.3)
    assert not h.app.dialogs.open


def test_templates_page_handles_many_templates(ui_app) -> None:
    """100 Vorlagen: Liste flüssig (virtualisiert), Suche gezielt."""
    import time

    h = ui_app
    store = h.app.state.templates
    for index in range(100):
        assert store.create(f"Vorlage {index:03d}") is not None
    start = time.perf_counter()
    h.templates.refresh_list()
    dauer = time.perf_counter() - start
    h.navigate("templates", 0.3)
    assert h.templates.total == 100 and h.templates.listModel.count == 100
    assert dauer < 1.0, dauer
    h.templates.search = "Vorlage 05"
    assert wait_until(lambda: h.templates.listModel.count == 10, 3)


def test_corrupt_template_file_is_reported_not_fatal(qt_application, config_file: Path, monkeypatch) -> None:
    """Eine beschädigte Vorlagendatei bricht den Start nicht ab – sie wird übersprungen und gemeldet."""
    from conftest import _prepare
    from qtutil import Harness

    _prepare(config_file, monkeypatch, "off")
    folder = config_file.parent / "vorlagen"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "kaputt.json").write_text("{ nicht json", encoding="utf-8")
    h = Harness(ui=True)
    try:
        h.navigate("templates", 0.3)
        assert h.templates.total == 0 and "nicht gelesen" in h.templates.problemsText
        assert (folder / "kaputt.json").is_file()  # nie gelöscht
        assert not h.messages()
    finally:
        h.close()


def test_view_bar_scrolls_to_the_current_view_when_narrow(ui_app) -> None:
    """Acht Ansichten: Ist die Seite zu schmal, lässt sich die Leiste verschieben und die gewählte
    Ansicht steht immer ganz im Bild; breit genug, steht sie unverschoben."""
    h = ui_app

    def leiste(seite: str):
        page = h.item(f"page_{seite}").property("item")
        stack = [page]
        while stack:
            current = stack.pop()
            if current.objectName() == "contractViews":
                return current
            stack.extend(current.childItems())
        raise AssertionError("Ansichtsleiste fehlt")

    def flick(bar):
        return next(child for child in bar.childItems() if child.property("contentX") is not None)

    h.window.resize(760, 700)
    pump(0.4)
    h.navigate("customers", 0.8)
    bar = leiste("customers")
    assert bar.property("overflowing") is True
    f = flick(bar)
    x = f.property("contentX")
    assert x > 0 and x + f.property("width") >= f.property("contentWidth") - 30  # »Kunden« steht ganz rechts im Bild
    h.window.resize(1400, 860)
    pump(0.4)
    h.navigate("create", 0.8)
    bar = leiste("create")
    assert bar.property("overflowing") is False and flick(bar).property("contentX") == 0
