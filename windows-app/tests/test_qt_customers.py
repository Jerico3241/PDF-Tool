"""Qt-Oberfläche: Kundenakte 2.0, Wiedererkennung per E-Mail, Ansicht »Kunden« und Live-Vorschau –
samt Übernahme der Kundenhistorie aus 2.3 (ersetzt die Tk-Tests aus test_app_v24.py).

Die App läuft mit QML im Fenster (offscreen, Profil »Vollständig«), die Kundenakte ist
eingeschaltet. Rückfragen beantwortet ``dialogs.AUTO_ANSWER`` (»primary«) – wo ein Test eine
bestimmte Eingabe im Dialog braucht, antwortet ``antworten()`` wie ein Benutzer. Nach jedem Test
darf die QML-Engine keine Warnung gemeldet haben.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from conftest import neustart, pump, wait_until, write_excel
from qtutil import qml_type

KUNDEN_23 = [
    {"firmenname": "Muster GmbH", "kundennummer": "10042", "rechnungsempfaenger": "rechnung@muster.de", "fusszeile": "Eigene\nFußzeile", "kopfzeile": "", "excel": "C:/x.xlsx", "pdf": ""},
    {"firmenname": "Alt AG", "kundennummer": "1", "rechnungsempfaenger": "", "fusszeile": "", "kopfzeile": ""},
]


# --- Hilfen ------------------------------------------------------------------------------------------


def liste(tmp_path: Path, name: str, mails, kd="10042", firma="Muster GmbH", rows: int = 3) -> Path:
    """Excel-Liste mit den angegebenen Rechnungsempfängern (reihum auf die Zeilen verteilt)."""
    mails = list(mails) or [""]
    daten = []
    for index in range(max(rows, len(mails))):
        daten.append([f"V-{index + 1}", datetime(2023, 1, 1 + index % 28), "monatlich", 10.0 + index, "Lastschr", f"Modul {index + 1}", mails[index % len(mails)], kd, firma, "Aktiv"])
    return write_excel(tmp_path / name, daten)


def akten(h):
    """Die Kundenakten der laufenden App (``CustomerStore``)."""
    return h.customers.customers


def pruefen(h, path: Path) -> None:
    """Excel wählen und die Prüfung abwarten."""
    h.navigate("create", 0.05)
    h.overview.use_excel(str(path))
    assert wait_until(lambda: h.overview.excel == str(path) and h.overview.analysis_for_current() is not None, 60)
    pump(0.1)


def hinweis(h, area: str):
    return h.app.notices.get(area)


def aktionen(h, area: str) -> list[str]:
    return list(hinweis(h, area).actions)


def klicken(h, area: str, text: str) -> None:
    """Aktion eines Hinweises auslösen (wie ein Klick auf die Schaltfläche in der InfoBar)."""
    labels = aktionen(h, area)
    assert text in labels, f"»{text}« fehlt in {area}: {labels}"
    hinweis(h, area).trigger(labels.index(text))


def antworten(monkeypatch, kind: str, button: str, data=None) -> list[dict]:
    """Rückfragen der Art ``kind`` wie ein Benutzer beantworten: Schaltfläche und Eingaben im Dialog.

    ``data`` ist das Ergebnis des Dialogs (``collect()`` in QML) oder eine Funktion der Anfrage.
    Rückgabe: die gestellten Anfragen dieser Art.
    """
    from qtapp.dialogs import DialogService

    original = DialogService.ask
    gestellt: list[dict] = []

    def ask(self, ask_kind, title, message="", *args, **kwargs):
        answer = original(self, ask_kind, title, message, *args, **kwargs)  # protokolliert die Anfrage
        if ask_kind != kind:
            return answer
        request = self.history[-1]
        gestellt.append(request)
        return button, (data(request) if callable(data) else dict(data or {}))

    monkeypatch.setattr(DialogService, "ask", ask)
    return gestellt


def erste_zeile(h):
    """Im Auswahldialog die erste Zeile der Liste wählen (Liste ``Customers.pickerModel``)."""
    return lambda _request: {"id": h.customers.picker.get(0).get("id", "")}


def elemente(root):
    """Alle QML-Elemente unterhalb von ``root`` (auch in Loadern und Listen)."""
    stack = [root]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.childItems()))


def merkmal(item, name: str):
    try:
        return item.property(name)
    except RuntimeError:  # Property ohne Python-Entsprechung
        return None


def texte(root, nur_sichtbare: bool = True) -> list[str]:
    """Texte aller (sichtbaren) Elemente – Beschriftungen, Schaltflächen, Felder."""
    found = []
    for item in elemente(root):
        value = merkmal(item, "text")
        if isinstance(value, str) and value and (item.isVisible() or not nur_sichtbare):
            found.append(value)
    return found


def zeigt(h, key: str, fragment: str) -> bool:
    """Zeigt die Seite ``key`` sichtbar einen Text mit ``fragment`` (Hinweis, Schaltfläche, Beschriftung)?"""
    return any(fragment in text for text in texte(seite(h, key)))


def element(root, **merkmale):
    """Erstes QML-Element mit den angegebenen Property-Werten (oder ``None``)."""
    for item in elemente(root):
        if all(merkmal(item, name) == wert for name, wert in merkmale.items()):
            return item
    return None


def typ(root, name: str):
    """Erstes QML-Element eines QML-Typs (z. B. »PListPage«)."""
    for item in elemente(root):
        if qml_type(item) == name:
            return item
    return None


def seite(h, key: str):
    """Die geladene Seite (Inhalt des Loaders ``page_<key>``)."""
    slot = h.item(f"page_{key}")
    assert slot is not None, key
    return slot.property("item")


def klick(button) -> None:
    from PySide6.QtCore import QMetaObject

    assert QMetaObject.invokeMethod(button, "click")
    pump(0.3)


def taste(h, key, modifiers=None) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(h.window, key, modifiers if modifiers is not None else Qt.KeyboardModifier.NoModifier)
    pump(0.1)


def tippen(h, editor: str, text: str) -> None:
    """Inhalt eines Kopf-/Fußzeilen-Editors ersetzen – wie eine Eingabe des Benutzers im QML-Textfeld."""
    from PySide6.QtGui import QTextCursor

    for item in elemente(h.item(editor)):
        document = merkmal(item, "textDocument")
        if document is not None:
            cursor = QTextCursor(document.textDocument())
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(text)
            pump(0.05)
            return
    raise AssertionError(f"Kein Textfeld in {editor}")


def vorschau_bild(h):
    """Das Seitenbild der Vorschau in QML (``Image`` mit der Quelle ``Preview.imageSource``)."""
    source = h.preview.imageSource
    for item in elemente(seite(h, "preview")):
        if qml_type(item) == "QQuickImage" and merkmal(item, "source") is not None and item.property("source").toString() == source:
            return item
    return None


def vorschau_fertig(h) -> bool:
    """Aktuelle Vorschau erzeugt und die gewünschte Seite in QML angezeigt."""
    p = h.preview
    doc = p._doc
    if p._building is not None or doc is None or p.state != "current":
        return False
    if not p.imageSource.startswith(f"image://preview/{doc.token}/{p.page}/"):
        return False
    bild = vorschau_bild(h)
    return bild is not None and bild.property("sourceSize").width() > 0


def vorschau_text(h) -> str:
    pypdf = pytest.importorskip("pypdf")
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(str(h.preview._doc.path)).pages)


# --- Wiedererkennung ------------------------------------------------------------------------------


def test_unknown_customer_is_normal_and_never_blocks(ui_app, tmp_path: Path) -> None:
    h = ui_app
    h.overview.ziel = str(tmp_path)
    h.overview.pdfOeffnen = False
    pruefen(h, liste(tmp_path, "neu.xlsx", ["rechnung@unbekannt.de"]))
    assert h.customers._match.kind.value == "no_match"
    assert not hinweis(h, "kunde_match").shown and hinweis(h, "info_excel").severity == "success"
    # Nichts erfunden: Firma und Kundennummer nur aus den Spalten der Datei, nie aus der Domain
    assert h.overview.firma == "Muster GmbH" and h.overview.kd == "10042"
    h.overview.start_pdf()
    assert wait_until(lambda: not h.overview.busy, 90)
    assert hinweis(h, "pdf_info").severity == "success"
    assert len(akten(h)) == 0  # keine Kundenakte ohne bewusste Entscheidung


def test_domain_is_never_turned_into_a_company(ui_app, tmp_path: Path) -> None:
    h = ui_app
    pruefen(h, liste(tmp_path, "ohne.xlsx", ["rechnung@mueller-gmbh.de"], kd="", firma=""))
    assert h.overview.firma == "" and h.overview.kd == ""
    assert "Müller" not in hinweis(h, "kunde_match").message


def test_single_match_offers_the_customer_without_applying(ui_app, tmp_path: Path) -> None:
    h = ui_app
    kunde = akten(h).create("Beispiel GmbH", "123456", ["Rechnung@Kunde.de"])
    assert h.customers.autoApply is False  # Standard: aus
    pruefen(h, liste(tmp_path, "a.xlsx", ["  rechnung@KUNDE.de "], kd="", firma=""))
    bar = hinweis(h, "kunde_match")
    assert h.customers._match.kind.value == "single_match" and h.customers._match.customer_id == kunde.id
    assert bar.shown and bar.title == "Bekannter Kunde gefunden" and "Beispiel GmbH · 123456" in bar.message
    assert aktionen(h, "kunde_match") == ["Übernehmen", "Kundenakte", "Ignorieren"]
    pump(0.3)
    assert zeigt(h, "create", "Bekannter Kunde gefunden") and zeigt(h, "create", "Ignorieren")  # Hinweis samt Aktionen in QML
    assert h.customers.active_customer() is None and h.overview.firma == ""
    klicken(h, "kunde_match", "Übernehmen")
    assert h.customers.active_customer() is kunde
    assert h.overview.firma == "Beispiel GmbH" and h.overview.kd == "123456"
    assert h.customers.activeTitle == "Kunde: Beispiel GmbH · 123456"
    pump(0.5)
    assert "Kunde: Beispiel GmbH · 123456" in texte(seite(h, "create"))  # Bereich »aktive Kundenakte« aufgeklappt
    assert not zeigt(h, "create", "Bekannter Kunde gefunden")
    assert kunde.last_excel.endswith("a.xlsx") and kunde.last_used_at  # automatische Metadaten


def test_ignore_hides_the_offer_for_this_excel(ui_app, tmp_path: Path) -> None:
    h = ui_app
    akten(h).create("Beispiel GmbH", "1", ["r@kunde.de"])
    datei = liste(tmp_path, "a.xlsx", ["r@kunde.de"])
    pruefen(h, datei)
    klicken(h, "kunde_match", "Ignorieren")
    assert not hinweis(h, "kunde_match").shown
    pruefen(h, datei)  # erneute Prüfung derselben Datei (z. B. neue Regel)
    assert not hinweis(h, "kunde_match").shown and h.customers.active_customer() is None
    pump(0.5)
    assert not zeigt(h, "create", "Bekannter Kunde gefunden")


def test_open_record_from_the_offer(ui_app, tmp_path: Path) -> None:
    h = ui_app
    kunde = akten(h).create("Beispiel GmbH", "1", ["r@kunde.de"])
    pruefen(h, liste(tmp_path, "a.xlsx", ["r@kunde.de"]))
    klicken(h, "kunde_match", "Kundenakte")
    pump(0.4)
    assert h.app.currentPage == "customers" and h.customers.detailId == kunde.id
    page = seite(h, "customers")
    # Detailansicht statt Liste (Überblendung abwarten – auf langsamen Rechnern dauert sie länger)
    assert wait_until(lambda: typ(page, "PPage").isVisible() and not typ(page, "PListPage").isVisible(), 10)
    assert h.customers.detailTitle == "Beispiel GmbH" and "Beispiel GmbH" in texte(page)


def test_auto_apply_only_when_enabled_and_undoable(ui_app, tmp_path: Path) -> None:
    h = ui_app
    kunde = akten(h).create("Beispiel GmbH", "123456", ["r@kunde.de"])
    h.customers.autoApply = True  # Schalter »Bekannte Kunden automatisch übernehmen«
    pruefen(h, liste(tmp_path, "a.xlsx", ["r@kunde.de"], kd="", firma=""))
    assert h.customers.active_customer() is kunde and h.overview.kd == "123456"
    info = hinweis(h, "kunde_info")
    assert info.title == "Bekannter Kunde übernommen" and "Rückgängig" in aktionen(h, "kunde_info")
    pump(0.3)
    assert zeigt(h, "create", "Bekannter Kunde übernommen") and zeigt(h, "create", "Rückgängig")
    klicken(h, "kunde_info", "Rückgängig")
    assert h.customers.active_customer() is None and h.overview.kd == "" and h.overview.firma == ""
    assert hinweis(h, "kunde_match").shown  # wieder als Angebot
    pump(0.3)
    assert zeigt(h, "create", "Bekannter Kunde gefunden")


def test_auto_apply_never_replaces_other_entered_data(ui_app, tmp_path: Path) -> None:
    h = ui_app
    akten(h).create("Beispiel GmbH", "123456", ["r@kunde.de"])
    h.customers.autoApply = True
    h.overview.kd = "999"  # bereits eingetragen – ein anderer Kunde?
    pruefen(h, liste(tmp_path, "a.xlsx", ["r@kunde.de"], kd="", firma=""))
    assert h.customers.active_customer() is None and h.overview.kd == "999"
    assert hinweis(h, "kunde_match").title == "Bekannter Kunde gefunden"


def test_conflicting_customers_need_a_decision(ui_app, tmp_path: Path, monkeypatch) -> None:
    h = ui_app
    a = akten(h).create("A GmbH", "1", ["a@a.de"])
    b = akten(h).create("B GmbH", "2", ["b@b.de"])
    h.customers.autoApply = True
    pruefen(h, liste(tmp_path, "ab.xlsx", ["a@a.de", "b@b.de"], kd="", firma=""))
    bar = hinweis(h, "kunde_match")
    assert h.customers._match.kind.value == "conflicting_matches"
    assert bar.severity == "warning"
    assert "Die Excel enthält Rechnungsempfänger, die verschiedenen bekannten Kunden zugeordnet sind." in bar.message
    assert h.customers.active_customer() is None  # keine automatische Entscheidung
    gestellt = antworten(monkeypatch, "choose_customer", "primary", erste_zeile(h))
    klicken(h, "kunde_match", "Kunden auswählen …")  # Auswahl: erster Kandidat
    assert len(gestellt) == 1 and gestellt[0]["data"] == {"search": False}  # nur die Kandidaten, ohne Suche
    assert h.customers.picker.keys() == [a.id, b.id]
    assert h.customers.active_customer() is a


def test_several_emails_of_one_customer_are_one_match(ui_app, tmp_path: Path) -> None:
    h = ui_app
    kunde = akten(h).create("A GmbH", "1", ["rechnung@a.de", "buchhaltung@a.de"])
    pruefen(h, liste(tmp_path, "a.xlsx", ["rechnung@a.de", "Buchhaltung@a.de"]))
    assert h.customers._match.kind.value == "single_match" and h.customers._match.customer_id == kunde.id


@pytest.fixture
def mehrdeutige_akten(config_file: Path):
    """Kundenakten aus Altdaten, in denen eine E-Mail zwei Akten zugeordnet ist (vor dem Start gespeichert)."""
    from tools.contract_overview.customers.models import Customer
    from tools.contract_overview.customers.repository import FILE_NAME, CustomerStore

    store = CustomerStore(config_file.parent / FILE_NAME, [Customer("x", "X AG", "1", ["r@x.de"]), Customer("y", "X AG Filiale", "2", ["r@x.de"])])
    assert store.save()
    return store


def test_ambiguous_legacy_mapping_asks(mehrdeutige_akten, ui_app, tmp_path: Path) -> None:
    h = ui_app
    assert sorted(akten(h).owner_ids("r@x.de")) == ["x", "y"]
    pruefen(h, liste(tmp_path, "x.xlsx", ["r@x.de"]))
    assert h.customers._match.kind.value == "ambiguous_match"
    assert hinweis(h, "kunde_match").title == "Zuordnung nicht eindeutig" and h.customers.active_customer() is None


# --- Übernehmen und Arbeitskopie ------------------------------------------------------------------


def test_working_copy_never_changes_the_record_silently(ui_app, tmp_path: Path, monkeypatch) -> None:
    h = ui_app
    logo = tmp_path / "logo.png"
    from PIL import Image

    Image.new("RGB", (40, 20), "red").save(logo)
    ziel = tmp_path / "ausgabe"
    ziel.mkdir()
    kunde = akten(h).create("Beispiel GmbH", "123456", ["r@kunde.de"], logo=str(logo), target_dir=str(ziel))
    antworten(monkeypatch, "choose_customer", "primary", erste_zeile(h))
    h.customers.pick_customer()  # »Bekannten Kunden auswählen« – erster Treffer
    assert h.customers.active_customer() is kunde
    assert h.overview.logo == str(logo) and h.overview.ziel == str(ziel)
    h.overview.firma = "Beispiel GmbH & Co. KG"
    pump(0.2)
    assert akten(h).get(kunde.id).company == "Beispiel GmbH"  # Kundenakte unverändert
    assert "Firmenname" in h.customers.activeCaption
    assert h.customers.saveText == "Kundenakte aktualisieren"
    h.navigate("create")
    assert zeigt(h, "create", "Geändert gegenüber der Kundenakte: Firmenname")
    assert h.item("saveCustomer").property("text") == "Kundenakte aktualisieren" and h.item("saveCustomer").property("enabled") is True
    h.customers.update_active_customer()  # Dialog: alle gezeigten Änderungen übernehmen
    anfrage = h.app.dialogs.history[-1]
    assert anfrage["kind"] == "customer_update" and [change["key"] for change in anfrage["data"]["changes"]] == ["company"]
    assert akten(h).get(kunde.id).company == "Beispiel GmbH & Co. KG"
    ident = kunde.id
    zweite = neustart(h)
    assert akten(zweite).get(ident).company == "Beispiel GmbH & Co. KG"
    assert zweite.customers.active_customer().id == ident  # aktive Kundenakte bleibt nach dem Neustart


def test_missing_logo_and_folder_fall_back_with_hint(ui_app, tmp_path: Path) -> None:
    h = ui_app
    logo_vorher, ziel_vorher = h.overview.logo, h.overview.ziel
    kunde = akten(h).create("A GmbH", "1", logo=str(tmp_path / "fehlt.png"), target_dir=str(tmp_path / "fehlt"))
    h.customers.apply_customer(kunde.id)
    assert h.overview.logo == logo_vorher and h.overview.ziel == ziel_vorher
    assert "Gespeichertes Logo wurde nicht gefunden" in hinweis(h, "kunde_info").message
    assert "Zielordner" in hinweis(h, "kunde_info").message


def test_template_follows_the_rule(ui_app) -> None:
    h = ui_app
    h.app.state.save_vorlage({"name": "Vorlage X", "titel": "Titel X", "format": "quer"})
    kunde = akten(h).create("A GmbH", "1", template="Vorlage X")
    h.customers.apply_customer(kunde.id)
    assert h.overview.titel != "Titel X"  # ohne »automatisch verwenden« nur angeboten
    assert "Vorlage „Vorlage X“ anwenden" in aktionen(h, "kunde_info")
    akten(h).update(kunde.id, template_auto=True)
    h.customers.apply_customer(kunde.id)
    assert h.overview.titel == "Titel X" and h.overview.format == "quer"


def test_user_edited_texts_are_not_overwritten(ui_app) -> None:
    from tools.contract_overview.customers.models import TextBlock

    h = ui_app
    kunde = akten(h).create("A GmbH", "1", footer=TextBlock("Fußzeile A"), header=TextBlock("Kopf A"))
    tippen(h, "footerEditor", "Eigene Fußzeile")  # Benutzer hat die Fußzeile geändert
    pump(0.1)
    h.customers.apply_customer(kunde.id)
    assert h.overview.footer_text() == "Eigene Fußzeile" and h.overview.header_text() != "Kopf A"
    klicken(h, "kunde_info", "Texte der Kundenakte verwenden")
    assert h.overview.footer_text() == "Fußzeile A" and h.overview.header_text() == "Kopf A"


def test_standard_footer_never_vanishes(ui_app) -> None:
    from appstate import DEFAULT_FOOTER
    from tools.contract_overview.customers.migration import customer_from_legacy

    h = ui_app
    assert h.overview.footer_text() == DEFAULT_FOOTER
    alt = customer_from_legacy({"firmenname": "Alt AG", "kundennummer": "1", "fusszeile": "", "kopfzeile": ""}, "")
    akten(h).restore(alt)
    h.customers.apply_customer(alt.id)
    assert h.overview.footer_text() == DEFAULT_FOOTER
    # auch ein bewusst leerer Fußzeilenwert in der Akte ersetzt die gültige nie
    from tools.contract_overview.customers.models import TextBlock

    alt.footer = TextBlock("   ")
    h.customers.apply_customer(alt.id)
    assert h.overview.footer_text() == DEFAULT_FOOTER


def test_new_overview_leaves_the_customer(ui_app) -> None:
    from tools.contract_overview.customers.models import TextBlock

    h = ui_app
    vorher = h.overview.footer_text()
    kunde = akten(h).create("A GmbH", "1", footer=TextBlock("Fußzeile A"))
    h.customers.apply_customer(kunde.id)
    assert h.overview.footer_text() == "Fußzeile A"
    h.overview.new_overview()
    assert h.customers.active_customer() is None and h.overview.kd == ""
    assert h.overview.footer_text() == vorher  # Text eines Kunden nie in der Übersicht des nächsten
    klicken(h, "kunde_info", "Rückgängig")
    assert h.customers.active_customer() is kunde and h.overview.footer_text() == "Fußzeile A"


def test_detach_keeps_the_entered_data(ui_app) -> None:
    h = ui_app
    kunde = akten(h).create("A GmbH", "1")
    h.navigate("create")
    h.customers.apply_customer(kunde.id)
    pump(0.5)
    assert "Kunde: A GmbH · 1" in texte(seite(h, "create"))
    h.customers.detach_customer()
    assert h.customers.active_customer() is None and h.overview.firma == "A GmbH"
    assert h.customers.activeId == ""
    pump(0.5)
    assert "Kunde: A GmbH · 1" not in texte(seite(h, "create"))  # Bereich »aktive Kundenakte« zugeklappt
    klicken(h, "kunde_info", "Rückgängig")
    assert h.customers.active_customer() is kunde


# --- Lernen nur nach bewusster Zuordnung ------------------------------------------------------------


def test_save_as_customer_learns_the_email_on_request(ui_app, tmp_path: Path) -> None:
    h = ui_app
    h.overview.ziel = str(tmp_path)
    h.overview.pdfOeffnen = False
    datei = liste(tmp_path, "neu.xlsx", ["neu@kunde.de"])
    pruefen(h, datei)
    h.overview.start_pdf()
    assert wait_until(lambda: not h.overview.busy, 90)
    assert hinweis(h, "kunde_info").title == "Als Kundenakte speichern?" and len(akten(h)) == 0
    klicken(h, "kunde_info", "Als Kundenakte speichern")  # Dialog: »Zuordnung merken« ist vorbelegt
    anfrage = h.app.dialogs.history[-1]
    assert anfrage["kind"] == "new_customer" and anfrage["data"]["email"] == "neu@kunde.de" and anfrage["data"]["remember"] is True
    kunde = h.customers.active_customer()
    assert kunde is not None and kunde.emails == ["neu@kunde.de"] and kunde.label == "Muster GmbH · 10042"
    h.overview.new_overview()
    pruefen(h, datei)
    assert h.customers._match.kind.value == "single_match" and h.customers._match.customer_id == kunde.id


def test_save_without_remembering_the_email(ui_app, tmp_path: Path, monkeypatch) -> None:
    h = ui_app
    antworten(monkeypatch, "new_customer", "primary", {"remember": False})  # »Zuordnung merken« ausgeschaltet
    pruefen(h, liste(tmp_path, "neu.xlsx", ["neu@kunde.de"]))
    h.customers.save_as_customer()
    assert h.customers.active_customer().emails == []


def test_new_email_of_a_known_customer_is_offered(ui_app, tmp_path: Path) -> None:
    h = ui_app
    kunde = akten(h).create("K GmbH", "5", ["alt@k.de"])
    datei = liste(tmp_path, "k.xlsx", ["neu@k.de"], kd="5", firma="K GmbH")
    pruefen(h, datei)
    assert h.customers._match.kind.value == "no_match"
    h.customers.apply_customer(kunde.id)  # bewusst gewählt
    bar = hinweis(h, "kunde_match")
    assert bar.title == "Diese E-Mail künftig diesem Kunden zuordnen?" and "neu@k.de" in bar.message
    assert aktionen(h, "kunde_match") == ["Zuordnung merken", "Nicht zuordnen"]
    klicken(h, "kunde_match", "Zuordnung merken")
    assert akten(h).get(kunde.id).emails == ["alt@k.de", "neu@k.de"]
    pruefen(h, datei)
    assert h.customers._match.kind.value == "single_match"


def test_excel_of_another_customer_is_flagged(ui_app, tmp_path: Path) -> None:
    h = ui_app
    kunde = akten(h).create("K GmbH", "5", ["k@k.de"])
    h.customers.apply_customer(kunde.id)
    pruefen(h, liste(tmp_path, "fremd.xlsx", ["andere@firma.de"], kd="999", firma="Andere GmbH"))
    bar = hinweis(h, "kunde_match")
    assert bar.severity == "warning" and bar.title == "Excel passt nicht zur aktiven Kundenakte" and "999" in bar.message
    klicken(h, "kunde_match", "Kundenakte lösen")
    assert h.customers.active_customer() is None


def test_declined_email_is_not_offered_again(ui_app, tmp_path: Path) -> None:
    h = ui_app
    kunde = akten(h).create("K GmbH", "5")
    pruefen(h, liste(tmp_path, "k.xlsx", ["neu@k.de"], kd="5", firma="K GmbH"))
    h.customers.apply_customer(kunde.id)
    klicken(h, "kunde_match", "Nicht zuordnen")
    h.customers.apply_customer(kunde.id)
    assert not hinweis(h, "kunde_match").shown and akten(h).get(kunde.id).emails == []


@pytest.mark.parametrize(("antwort", "besitzer"), [("primary", "B"), ("secondary", "A"), ("close", "A")])
def test_email_conflict_is_decided_by_the_user(backend, monkeypatch, antwort: str, besitzer: str) -> None:
    from qtapp import dialogs

    h = backend
    a = akten(h).create("A", "1", ["x@x.de"])
    b = akten(h).create("B", "2")
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", antwort)
    h.customers.assign_emails(b.id, ["X@x.de"])
    anfrage = h.app.dialogs.history[-1]
    assert anfrage["title"] == "E-Mail bereits zugeordnet" and "x@x.de" in anfrage["message"]
    assert (anfrage["primary"], anfrage["secondary"], anfrage["default"]) == ("Zuordnung verschieben", "Bestehende Zuordnung verwenden", "close")
    owners = [c.company for c in akten(h).owners("x@x.de")]
    assert owners == [besitzer]  # nie still doppelt zugeordnet
    assert (a.emails == ["x@x.de"]) == (besitzer == "A")


def test_info_bar_width_does_not_follow_its_message(ui_app) -> None:
    """Die Meldung einer Hinweisleiste fordert keine textabhängige Breite an.

    Sonst schaukeln sich Umbruch und Breite gegenseitig auf (unter Tk entstand mit bestimmten
    Texten eine endlose Folge von Configure-Ereignissen). In QML: feste ``implicitWidth``, die
    Breite gibt das Layout vor, der Text bricht innerhalb der Leiste um – ohne Bindungsschleife.
    """
    h = ui_app
    h.navigate("create")
    notice = hinweis(h, "kunde_info")
    bars = [item for item in elemente(seite(h, "create")) if merkmal(item, "notice") is notice]
    assert len(bars) == 1
    bar = bars[0]
    breiten = set()
    for title in ("", "Zuordnung gemerkt"):
        for text in ("kurz", "neu@k.de wird künftig als Rechnungsempfänger von „K GmbH · 5“ erkannt. " * 4):
            h.app.notify("kunde_info", "success", text, title=title, animate=False)
            pump(0.3)
            assert bar.isVisible() and bar.implicitWidth() == 300  # unabhängig von der Textlänge
            breiten.add(bar.width())
            meldung, zeile = typ(bar, "QQuickText"), typ(bar, "QQuickFlow")
            assert meldung is not None and zeile is not None
            assert meldung.width() <= zeile.width() <= bar.width()  # bricht innerhalb der Leiste um
            if len(text) > 100:
                assert meldung.width() == pytest.approx(zeile.width(), abs=1)  # volle Breite
                assert meldung.height() > 2 * 18  # mehrzeilig statt breiter
    assert len(breiten) == 1  # volle Breite des Layouts, gleich für jeden Text


# --- Ansicht »Kunden« ----------------------------------------------------------------------------------


def test_empty_state(ui_app) -> None:
    h = ui_app
    h.navigate("customers")
    page = seite(h, "customers")
    assert h.customers.total == 0 and not h.customers.listShown
    assert typ(page, "PListPage").property("count") == 0  # keine Karte mit Zeilen
    sichtbar = texte(page)
    assert "Noch keine Kunden gespeichert." in sichtbar
    assert any(t.startswith("PDF Tool kann bekannte Rechnungsempfänger später automatisch wiedererkennen.") for t in sichtbar)
    bereich = element(page, text="Noch keine Kunden gespeichert.").parentItem()
    buttons = [item for item in elemente(bereich) if qml_type(item) == "PButton"]
    assert [b.property("text") for b in buttons] == ["Zur Vertragsübersicht"]
    klick(buttons[0])
    assert h.app.currentPage == "create"


def test_list_search_sort_with_hundreds_of_customers(ui_app) -> None:
    h = ui_app
    for number in range(400):
        akten(h).create(f"Firma {number:03d}", str(1000 + number), [f"r{number}@firma{number}.de"])
    akten(h).create("Müller & Söhne GmbH", "77", ["buchhaltung@mueller.de"])
    start = time.perf_counter()
    h.customers.customers_changed()
    assert time.perf_counter() - start < 2.0
    h.navigate("customers")
    model = h.customers.model
    start = time.perf_counter()
    h.customers.refresh_list()
    pump(0.05)
    assert time.perf_counter() - start < 2.0
    assert "401 Kundenakten" in h.customers.countText and "Suche verfeinern" in h.customers.countText
    assert h.customers.countText in texte(seite(h, "customers"))
    listing = typ(seite(h, "customers"), "PListPage")
    assert model.rowCount() == 200 and listing.property("count") == 200
    # Die Liste ist virtualisiert: nur sichtbare Zeilen (samt Puffer) existieren als Elemente.
    zeilen = [item for item in listing.property("contentItem").childItems() if merkmal(item, "subtitle") is not None]
    assert 0 < len(zeilen) < 60
    resets = model.resets

    def suchen(text: str) -> None:
        start = time.perf_counter()
        h.customers.search = text  # wie eine Eingabe im Suchfeld (entprellt)
        assert wait_until(lambda: not h.app.timers.pending("customers:search"), 5)
        assert time.perf_counter() - start < 2.0

    def sortieren(label: str) -> None:
        start = time.perf_counter()
        h.customers.setOrder(next(entry["value"] for entry in h.customers.orders if entry["label"] == label))
        pump(0.3)
        assert time.perf_counter() - start < 2.0

    suchen("müller")
    assert model.rowCount() == 1 and model.get(0)["company"] == "Müller & Söhne GmbH"
    suchen("MUELLER.de")  # E-Mail, Groß-/Kleinschreibung egal
    assert model.rowCount() == 1 and model.get(0)["company"] == "Müller & Söhne GmbH"
    suchen("1007")  # Kundennummer
    assert [akten(h).get(key).number for key in model.keys()] == ["1007"]
    suchen("")
    sortieren("Kundennummer")
    assert akten(h).get(model.keys()[0]).number == "77" and h.customers.order == "number"
    sortieren("Firma A–Z")
    assert model.get(0)["company"] == "Firma 000"
    assert model.resets == resets  # Suchen und Sortieren ändern die Liste gezielt – kein Neuaufbau
    assert listing.property("count") == model.rowCount()


def test_keyboard_opens_and_leaves_the_detail(ui_app, monkeypatch) -> None:
    from PySide6.QtCore import Qt

    h = ui_app
    kunde = akten(h).create("A GmbH", "1")
    h.customers.customers_changed()
    h.navigate("customers")
    page = seite(h, "customers")
    listing, detail = typ(page, "PListPage"), typ(page, "PPage")
    listing.forceActiveFocus()
    pump(0.1)
    taste(h, Qt.Key.Key_Down)
    taste(h, Qt.Key.Key_Return)
    pump(0.3)
    assert h.customers.detailId == kunde.id and detail.isVisible() and not listing.isVisible()
    h.customers.show_list()
    pump(0.4)
    assert h.customers.detailId == "" and listing.isVisible() and not detail.isVisible()
    # Strg+F: in »Kunden« die Suche, sonst »Bekannten Kunden auswählen«
    taste(h, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    pump(0.2)
    assert h.item("customerSearch").property("activeFocus") is True
    h.navigate("create")
    antworten(monkeypatch, "choose_customer", "primary", erste_zeile(h))
    taste(h, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert h.customers.active_customer() is kunde


def test_detail_edit_emails_and_persistence(ui_app, config_file: Path) -> None:
    h = ui_app
    kunde = akten(h).create("A GmbH", "1", ["a@a.de"])
    h.customers.customers_changed()
    h.navigate("customers")
    h.customers.show_detail(kunde.id)
    h.customers.company = "A GmbH & Co."  # Eingabe im Feld »Firmenname«
    h.customers.flush()
    assert kunde.company == "A GmbH & Co."
    h.customers.newEmail = "kein-at-zeichen"
    h.customers.addEmail()
    assert hinweis(h, "kunde_mail_info").severity == "warning" and kunde.emails == ["a@a.de"]
    h.customers.newEmail = " Zweite@A.de "
    h.customers.addEmail()
    assert kunde.emails == ["a@a.de", "zweite@a.de"] and h.customers.emails.keys() == ["a@a.de", "zweite@a.de"]
    h.customers.newEmail = "zweite@a.de"
    h.customers.addEmail()
    assert hinweis(h, "kunde_mail_info").severity == "info" and kunde.emails == ["a@a.de", "zweite@a.de"]
    h.customers.makePrimary("zweite@a.de")
    assert kunde.primary_email == "zweite@a.de" and h.customers.emails.get(0)["email"] == "zweite@a.de" and h.customers.emails.get(0)["primary"]
    h.customers.removeEmail("zweite@a.de")
    h.customers.removeEmail("a@a.de")
    assert kunde.emails == [] and akten(h).get(kunde.id) is kunde  # Akte bleibt
    klicken(h, "kunde_mail_info", "Rückgängig")
    assert kunde.emails == ["a@a.de"]
    data = json.loads((config_file.parent / "kundenakten.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 2 and data["customers"][0]["company"] == "A GmbH & Co."


def test_delete_removes_record_but_never_files(ui_app, tmp_path: Path) -> None:
    h = ui_app
    pdf = tmp_path / "alt.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    excel = liste(tmp_path, "alt.xlsx", ["d@d.de"])
    kunde = akten(h).create("D GmbH", "4", ["d@d.de"])
    akten(h).touch(kunde.id, excel=str(excel), pdf=str(pdf))
    h.customers.apply_customer(kunde.id)
    h.navigate("customers")
    h.customers.show_detail(kunde.id)
    h.customers.deleteRecord()  # Bestätigung: Hauptschaltfläche
    anfrage = h.app.dialogs.history[-1]
    assert anfrage["kind"] == "confirm" and anfrage["title"] == "Kundenakte löschen?" and anfrage["primary"] == "Löschen"
    assert akten(h).get(kunde.id) is None and akten(h).owner_ids("d@d.de") == []
    assert pdf.is_file() and excel.is_file()
    assert h.customers.active_customer() is None and h.overview.firma == "D GmbH"
    klicken(h, "kunden_info", "Rückgängig")
    assert akten(h).get(kunde.id) is not None


def test_merge_only_on_request(ui_app, monkeypatch) -> None:
    h = ui_app
    a = akten(h).create("Beispiel GmbH", "123", ["a@b.de"])
    b = akten(h).create("Beispiel", "123", ["c@b.de"])
    h.customers.customers_changed()
    h.navigate("customers")
    h.customers.show_detail(a.id)
    assert hinweis(h, "kunde_detail_info").shown and "Mögliche Doppelung" in hinweis(h, "kunde_detail_info").message
    assert len(akten(h)) == 2  # Hinweis, keine automatische Zusammenführung
    antworten(monkeypatch, "choose_customer", "primary", erste_zeile(h))
    h.customers.merge()  # Auswahl: erster Kandidat (die Doppelung), dann bestätigen
    assert h.app.dialogs.history[-1]["title"] == "Kundenakten zusammenführen?"
    assert len(akten(h)) == 1 and akten(h).get(b.id) is None
    assert akten(h).get(a.id).emails == ["a@b.de", "c@b.de"]


def test_create_customer_manually(ui_app, monkeypatch) -> None:
    h = ui_app
    antworten(monkeypatch, "customer_fields", "primary", {"company": "Neu GmbH", "number": "55", "email": "Info@Neu.de"})
    h.navigate("customers")
    h.customers.newCustomer()
    kunde = akten(h).all()[0]
    assert kunde.label == "Neu GmbH · 55" and kunde.emails == ["info@neu.de"]
    assert h.customers.detailId == kunde.id
    antworten(monkeypatch, "customer_fields", "primary", {"company": "", "number": "", "email": ""})
    h.customers.newCustomer()
    assert len(akten(h)) == 1 and hinweis(h, "kunden_info").severity == "warning"


def test_use_last_excel_checks_it_again(ui_app, tmp_path: Path) -> None:
    h = ui_app
    excel = liste(tmp_path, "letzte.xlsx", ["l@l.de"])
    kunde = akten(h).create("L GmbH", "8", ["l@l.de"])
    akten(h).touch(kunde.id, excel=str(excel))
    h.navigate("customers")
    h.customers.show_detail(kunde.id)
    assert h.customers.excelAvailable  # »Als Quelle verwenden« nur mit vorhandener Datei
    h.customers.useLastExcel()
    assert h.app.currentPage == "create" and h.customers.active_customer() is kunde
    assert h.overview.analysis() is None  # nie eine alte Analyse – die Datei wird neu geprüft
    assert wait_until(lambda: h.overview.analysis() is not None, 60)


# --- Live-Vorschau --------------------------------------------------------------------------------------


def test_preview_follows_customer_changes_without_stale_results(ui_app, tmp_path: Path) -> None:
    h = ui_app
    a = akten(h).create("Alpha GmbH", "111")
    b = akten(h).create("Beta GmbH", "222")
    pruefen(h, liste(tmp_path, "v.xlsx", ["v@v.de"], kd="", firma=""))
    h.navigate("preview")
    assert wait_until(lambda: vorschau_fertig(h), 60)
    assert "Kundennummer: –" in vorschau_text(h)  # Platzhalter ohne Kundennummer
    laeufe = h.preview.runs
    h.customers.apply_customer(a.id)
    h.preview.refresh()  # Erzeugung für A läuft …
    assert h.preview._building is not None
    h.customers.apply_customer(b.id)  # … und der Kunde wechselt sofort zu B
    assert wait_until(lambda: vorschau_fertig(h) and "Beta GmbH" in json.dumps(h.preview._signature), 90)
    text = vorschau_text(h)
    assert "Beta GmbH" in text and "222" in text and "Alpha GmbH" not in text
    assert h.preview.runs >= laeufe + 1


def test_preview_pages_and_zoom(ui_app, tmp_path: Path) -> None:
    h = ui_app
    h.overview.kd = "1"
    pruefen(h, liste(tmp_path, "lang.xlsx", ["v@v.de"], rows=90))
    h.navigate("preview")
    assert wait_until(lambda: vorschau_fertig(h), 60)
    p = h.preview
    page = seite(h, "preview")
    zurueck, weiter = element(page, tip="Vorherige Seite (Bild ↑)"), element(page, tip="Nächste Seite (Bild ↓)")
    breite_anpassen = element(page, text="An Breite anpassen")
    assert p._doc.pages >= 2 and p.pages == p._doc.pages
    assert f"Seite 1 von {p._doc.pages}" in texte(page)
    assert not p.canPrev and p.canNext
    assert zurueck.property("enabled") is False and weiter.property("enabled") is True
    p.step(1)
    assert wait_until(lambda: vorschau_fertig(h) and p.page == 1, 30)
    assert p.canPrev and zurueck.property("enabled") is True
    breite = p.pageWidth
    p.zoomIn()
    assert wait_until(lambda: vorschau_fertig(h) and p.pageWidth > breite, 30)
    assert p.zoomText.endswith("%") and breite_anpassen.property("enabled") is True
    p.fitWidth()
    pump(0.1)
    assert p.zoomText == "An Breite" and breite_anpassen.property("enabled") is False
    assert "An Breite" in texte(page)
    # Keine Vorschau-Dateien im Zielordner, temporäre Dateien werden beim Beenden gelöscht
    ordner = p._doc.folder
    assert ordner.is_dir() and not list(Path(h.overview.target_folder()).glob("vorschau*.pdf"))
    neustart(h)
    assert not ordner.exists()


def test_stale_preview_folders_are_removed(tmp_path: Path, monkeypatch, qt_application) -> None:
    import os
    import tempfile

    from tools.contract_overview import preview

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    alt = tmp_path / (preview.FOLDER_PREFIX + "alt")
    neu = tmp_path / (preview.FOLDER_PREFIX + "neu")
    fremd = tmp_path / "anderer-ordner"
    for folder in (alt, neu, fremd):
        folder.mkdir()
        (folder / "vorschau.pdf").write_bytes(b"%PDF")
    vor_zwei_tagen = time.time() - 2 * 86400
    os.utime(alt, (vor_zwei_tagen, vor_zwei_tagen))
    os.utime(fremd, (vor_zwei_tagen, vor_zwei_tagen))
    assert preview.sweep_stale_folders() == 1
    assert not alt.exists() and neu.exists() and fremd.exists()
    # Die Vorschau der Qt-App räumt beim Start ebenso auf (im Hintergrund).
    import shiboken6

    from qtapp.contracts.preview import PreviewController

    alt.mkdir()
    os.utime(alt, (vor_zwei_tagen, vor_zwei_tagen))
    controller = PreviewController(None, None)
    try:
        assert wait_until(lambda: not alt.exists(), 10)
        assert neu.exists() and fremd.exists()
    finally:
        shiboken6.delete(controller)


def test_preview_explains_what_is_missing(ui_app) -> None:
    h = ui_app
    h.overview.excel = ""
    h.navigate("preview")
    pump(0.2)
    assert h.preview.state == "empty"
    assert h.preview.problem == "Excel-Datei fehlt"
    sichtbar = texte(seite(h, "preview"))
    assert "Noch keine Vorschau" in sichtbar and "Excel-Datei fehlt" in sichtbar


# --- Übernahme aus 2.3 und Unabhängigkeit von »PDF reparieren« -------------------------------------------


@pytest.fixture
def kundenhistorie_23(config_file: Path) -> list[dict]:
    """Einstellungen von Version 2.3 mit Kundenhistorie (vor dem Start geschrieben)."""
    config_file.write_text(json.dumps({"gesehen": "2.3.0", "theme": "light", "kunden": KUNDEN_23, "firmenname": "Muster GmbH", "kundenakte_verwenden": True}), encoding="utf-8")
    return KUNDEN_23


def test_history_of_23_becomes_customer_records(kundenhistorie_23, ui_app, config_file: Path) -> None:
    h = ui_app
    pump(0.8)  # »Neu in Version« erscheint nach 0,5 s (im Test ohne Warten beantwortet)
    assert sorted(k.label for k in akten(h).all()) == ["Alt AG · 1", "Muster GmbH · 10042"]
    assert hinweis(h, "kunden_info").severity == "success" and "2 Kunden" in hinweis(h, "kunden_info").message
    h.navigate("customers")
    assert zeigt(h, "customers", "2 Kunden wurden aus der bisherigen Kundenhistorie als Kundenakte übernommen.")
    assert list((config_file.parent / "sicherungen").glob("gui-config-vor-kundenakte-*.json"))
    assert "kunden" not in json.loads(config_file.read_text(encoding="utf-8"))
    ids = sorted(k.id for k in akten(h).all())
    zweite = neustart(h)
    assert sorted(k.id for k in akten(zweite).all()) == ids  # keine zweite Übernahme, stabile IDs


@pytest.fixture
def uebernahme_scheitert(config_file: Path, monkeypatch) -> list[dict]:
    """Kundenhistorie aus 2.3, deren Übernahme scheitert (Kundenakten lassen sich nicht speichern)."""
    from tools.contract_overview.customers.repository import CustomerStore

    kunden = [{"firmenname": "Muster GmbH", "kundennummer": "10042", "rechnungsempfaenger": "r@m.de"}]
    monkeypatch.setattr(CustomerStore, "save", lambda self: False)
    config_file.write_text(json.dumps({"gesehen": "2.3.0", "theme": "light", "kunden": kunden, "kundenakte_verwenden": True}), encoding="utf-8")
    return kunden


def test_failed_migration_keeps_the_history(uebernahme_scheitert, ui_app, config_file: Path) -> None:
    h = ui_app
    pump(0.8)
    assert hinweis(h, "kunden_info").severity == "error"
    h.navigate("customers")
    assert zeigt(h, "customers", "Die bisherige Kundenhistorie konnte nicht übernommen werden")
    h.app.persist()
    assert json.loads(config_file.read_text(encoding="utf-8"))["kunden"] == uebernahme_scheitert  # nichts verloren


def test_repair_tool_stays_independent(ui_app) -> None:
    from PySide6.QtCore import Qt

    from tools.registry import CONTRACTS, REPAIR

    h = ui_app
    assert REPAIR.pages == ("repair",) and "customers" in CONTRACTS.pages and "preview" in CONTRACTS.pages
    h.app.openTool(REPAIR.key)
    pump(0.3)
    vorher = list(h.app.dialogs.history)
    taste(h, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)  # Strg+F hat in »PDF reparieren« keine Wirkung
    assert h.app.currentPage == "repair" and h.app.dialogs.history == vorher
    alle = " ".join(texte(seite(h, "repair"), nur_sichtbare=False))
    assert "Kunde" not in alle and "Kunde" not in h.app.hint
