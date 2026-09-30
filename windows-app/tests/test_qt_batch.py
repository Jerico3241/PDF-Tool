"""Qt-Oberfläche (2.7.0): kompakte Excel-Karte und Stapelverarbeitung in »Vertragsübersichten«.

Portiert aus test_app_v25.py (Tk). Die Abläufe laufen über die Controller (``Contracts``,
``Customers``, ``Batch``, ``Preview``) und – wo es um die Oberfläche geht – über die QML-Elemente
der Seiten: Schaltflächen werden wie mit der Maus ausgelöst (``click``), Auswahllisten und die
Filterleiste über ihre Signale, Hinweise über ihre Aktionen. Nach jedem Test mit Oberfläche
(``ui_app``) darf die QML-Engine keine Warnung gemeldet haben. Reine Abläufe ohne QML laufen mit
``backend``.

Statt »nur die geänderte Zeile wird neu gezeichnet« (Tk-Canvas) prüft
``test_status_changes_update_single_rows_without_reset``, dass das Listenmodell bei
Statusänderungen nur einzelne Zeilen meldet und nie neu aufgebaut wird.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QCoreApplication, QEvent, QMetaObject, QObject, Qt
from PySide6.QtGui import QKeyEvent

from conftest import neustart, pump, wait_until, write_excel
from qtutil import process_events

from tools.contract_overview.batch import processor
from tools.contract_overview.batch.models import WAITING

pypdf = pytest.importorskip("pypdf")

SPALTEN = ["Vertrag-Nr.", "Beginnt am", "Abrechnungszyklus", "Netto [€]", "Zahlungsart", "Bemerkung", "Rechnungsempfänger Email", "Anwenderstatus"]


# --- Testdaten -------------------------------------------------------------------------------------------


def excel(pfad: Path, aktiv: int = 5, inaktiv: int = 0, mails=("rechnung@kunde-a.de",), spalten=None) -> Path:
    """Excel wie die echten Listen (ohne Kundennummer und Firma) – Empfänger reihum."""
    zeilen = []
    for index in range(aktiv + inaktiv):
        mail = mails[index % len(mails)] if mails else ""
        zeilen.append([f"V-{index + 1}", datetime(2022, 1, 1 + index % 28), "jährlich", 10.0 + index, "Sofort", f"Modul {index + 1}", mail, "Aktiv" if index < aktiv else "Inaktiv"])
    spalten = spalten or list(SPALTEN)
    if "Rechnungsempfänger Email" not in spalten:
        zeilen = [zeile[:6] + zeile[7:] for zeile in zeilen]
    return write_excel(pfad, zeilen, spalten)


def stapel_liste(pfad: Path, mail: str = "rechnung@kunde-a.de", aktiv: int = 2) -> Path:
    """Wie ``test_batch.liste``: Verträge über mehrere Jahre, ein Rechnungsempfänger."""
    zeilen = [[f"V-{index + 1:03d}", datetime(2020 + index % 5, 1, 1), "jährlich", 10.0 + index, "Sofort", f"Vertrag {index + 1}", mail, "Aktiv"] for index in range(aktiv)]
    return write_excel(pfad, zeilen, SPALTEN)


def pdf_text(pfad) -> str:
    return " ".join(" ".join(page.extract_text() or "" for page in pypdf.PdfReader(str(pfad)).pages).split())


# --- Abläufe ---------------------------------------------------------------------------------------------


def einzeln_pruefen(h, path: Path) -> None:
    """Excel im Einzelmodus übernehmen und warten, bis ihre Prüfung angezeigt wird."""
    h.navigate("create", 0.2)
    h.overview.use_excel(str(path))
    assert wait_until(lambda: h.overview.excel == str(path) and h.overview.analysis_for_current() is not None, 60)
    pump(0.2)


def fakten(h) -> dict[str, str]:
    """Zeilen unter der Excel-Prüfung (Beschriftung → Wert)."""
    return {fact["label"]: fact["value"] for fact in h.overview.facts}


def stapel(h, target: Path | None = None):
    h.navigate("batch", 0.3)
    if target is not None:
        h.batch.update_settings(target_dir=str(target))
    return h.batch


def geprueft(h, timeout: float = 90) -> None:
    batch = h.batch
    assert wait_until(lambda: batch.items and all(item.status not in WAITING for item in batch.items), timeout), [(i.name, i.status) for i in batch.items]
    pump(0.2)


def erstellen(h, timeout: float = 180) -> None:
    h.batch.start_run()
    assert wait_until(lambda: not h.batch.running_now, timeout)
    pump(0.2)


def eintrag(h, name: str):
    return next(item for item in h.batch.items if item.name == name)


def status(h) -> dict[str, str]:
    return {item.name: item.status.value for item in h.batch.items}


def zeilen(h) -> dict[str, dict]:
    """Zeilen der Stapel-Liste (Listenmodell, wie QML sie zeigt) nach Dateiname."""
    return {row["name"]: row for row in h.batch.model.items()}


def aktualisiert(h, timeout: float = 5.0) -> None:
    """Warten, bis die gesammelte Aktualisierung der Stapel-Ansicht gelaufen ist."""
    assert wait_until(lambda: not h.app.timers.pending("batch:refresh"), timeout)
    process_events()


def pumpen_bis(bedingung, timeout: float, beobachten=None) -> tuple[bool, float, int]:
    """Ereignisschleife laufen lassen, bis ``bedingung`` gilt: (erfüllt, längster Schritt in s, Schritte)."""
    longest, steps = 0.0, 0
    last = time.perf_counter()
    end = last + timeout
    while not bedingung() and time.perf_counter() < end:
        process_events()
        if beobachten is not None:
            beobachten()
        now = time.perf_counter()
        longest = max(longest, now - last)
        last = now
        steps += 1
        time.sleep(0.01)
    return bool(bedingung()), longest, steps


# --- QML --------------------------------------------------------------------------------------------------


def elemente(wurzel):
    """Alle QML-Elemente unterhalb von ``wurzel`` (auch Kopfbereich und Zeilen der Liste)."""
    stack = [wurzel]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.childItems()))


def qml_typ(item) -> str:
    return item.metaObject().className().split("_QML")[0]


def sichtbar(item) -> bool:
    """Wirklich zu sehen: sichtbar, nicht ausgeblendet (auch keine ausgeblendete Überblendung) und
    keine zur Wiederverwendung zurückgelegte Zeile der Liste (``index`` −1)."""
    if not item.isVisible():
        return False
    current = item
    while current is not None:
        if current.opacity() < 0.01:
            return False
        if current.property("statusKey") is not None and current.property("index") == -1:
            return False
        current = current.parentItem()
    return True


def seite(h, name: str = "batchPage"):
    root = h.item(name)
    assert root is not None, name
    return root


def sichtbare_texte(h, name: str = "batchPage") -> set[str]:
    return {item.property("text") for item in elemente(seite(h, name)) if isinstance(item.property("text"), str) and item.property("text") and sichtbar(item)}


def element(h, text: str, typ: str = "PButton", name: str = "batchPage"):
    treffer = [item for item in elemente(seite(h, name)) if qml_typ(item) == typ and item.property("text") == text and sichtbar(item)]
    assert len(treffer) == 1, f"{typ} »{text}«: {len(treffer)} sichtbare Treffer"
    return treffer[0]


def ist_sichtbar(h, text: str, typ: str = "PButton", name: str = "batchPage") -> bool:
    return any(qml_typ(item) == typ and item.property("text") == text and sichtbar(item) for item in elemente(seite(h, name)))


def klicken(h, text: str, typ: str = "PButton", name: str = "batchPage") -> None:
    """Schaltfläche (bzw. Kontrollkästchen) der Oberfläche auslösen – wie ein Mausklick."""
    item = element(h, text, typ, name)
    assert item.isEnabled(), f"»{text}« ist nicht aktiv"
    assert QMetaObject.invokeMethod(item, "click")
    pump(0.1)


def waehlen(h, label: str, index: int, name: str = "batchPage") -> None:
    """Eintrag einer Auswahlliste wählen (Signal ``activated`` wie bei der Auswahl mit der Maus)."""
    combos = [item for item in elemente(seite(h, name)) if qml_typ(item) == "PComboBox" and item.property("label") == label and sichtbar(item)]
    assert len(combos) == 1, f"Auswahlliste »{label}«: {len(combos)} sichtbare Treffer"
    assert QMetaObject.invokeMethod(combos[0], "activated", Q_ARG(int, index))
    pump(0.1)


def filter_waehlen(h, key: str) -> None:
    """Filter der Stapel-Liste wählen (Filterleiste über der Liste)."""
    bars = [item for item in elemente(seite(h)) if qml_typ(item) == "PSelectorBar" and sichtbar(item) and any(entry.get("key") == "needs_input" for entry in item.property("items") or [])]
    assert len(bars) == 1
    assert QMetaObject.invokeMethod(bars[0], "selected", Q_ARG(str, key))


def infobar(h, bereich: str, name: str):
    """Die InfoBar einer Seite, die den Hinweisbereich ``bereich`` zeigt."""
    bars = [item for item in elemente(seite(h, name)) if qml_typ(item) == "PInfoBar" and item.property("notice") is not None and item.property("notice").name == bereich]
    assert len(bars) == 1, bereich
    return bars[0]


def karte(item) -> str | None:
    """Titel der Karte, in der ``item`` steht."""
    current = item.parentItem()
    while current is not None:
        if qml_typ(current) == "PCard":
            return current.property("title")
        current = current.parentItem()
    return None


def aktion(h, bereich: str, label: str) -> None:
    """Aktion eines Hinweises auslösen (wie die Schaltfläche in der InfoBar)."""
    notice = h.app.notices.get(bereich)
    assert notice.shown and label in notice.actions, (bereich, notice.actions)
    notice.trigger(notice.actions.index(label))
    pump(0.2)


def listenansicht(h):
    """Die Liste der Stapel-Einträge (``ListView`` der Seite »Stapel«)."""
    views = [item for item in elemente(seite(h)) if qml_typ(item) == "PListPage"]
    assert len(views) == 1
    return views[0]


def taste(h, key) -> None:
    """Taste drücken und loslassen (geht an das Element mit Tastaturfokus)."""
    for art in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QCoreApplication.sendEvent(h.window, QKeyEvent(art, key, Qt.KeyboardModifier.NoModifier))
    pump(0.05)


def tippen(h, text: str) -> None:
    """Text über die Tastatur eingeben (Buchstaben und Leerzeichen)."""
    for zeichen in text:
        key = Qt.Key.Key_Space if zeichen == " " else getattr(Qt.Key, f"Key_{zeichen.upper()}")
        for art in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QCoreApplication.sendEvent(h.window, QKeyEvent(art, key, Qt.KeyboardModifier.NoModifier, zeichen))
        process_events()


def zeilen_elemente(h) -> dict[str, object]:
    """Angezeigte Zeilen (Delegates) der Stapel-Liste nach Dateiname – je Zeile des Modells über
    ``ListView.itemAtIndex`` (zur Wiederverwendung zurückgelegte Zeilen zählen nicht)."""
    view = listenansicht(h)
    result = {}
    for row in range(h.batch.model.rowCount()):
        item = QMetaObject.invokeMethod(view, "itemAtIndex", Q_RETURN_ARG("QQuickItem*"), Q_ARG(int, row))
        if item is not None and sichtbar(item):
            result[item.property("name")] = item
    return result


# --- Teil A: kompakte Excel-Karte ------------------------------------------------------------------------


def test_excel_card_shows_contract_counts_only_once(ui_app, tmp_path: Path) -> None:
    h = ui_app
    einzeln_pruefen(h, excel(tmp_path / "liste.xlsx", aktiv=5, inaktiv=3, mails=("p.zimmermann@ipb-zimmermann.de",)))
    bar = h.app.notices.get("info_excel")
    assert (bar.severity, bar.title, bar.message) == ("success", "Excel geprüft", "5 aktive Verträge · 3 inaktiv ausgeblendet")
    assert sichtbar(infobar(h, "info_excel", "createPage"))
    labels = fakten(h)
    assert "Aktive Verträge" not in labels and "Ausgeblendet (inaktiv)" not in labels  # keine Doppelung
    assert not any("aktiv" in wert for wert in labels.values())
    # Rechnungsempfänger als eigene Zeile – ohne Auswahlliste
    assert h.overview.mailValue == "p.zimmermann@ipb-zimmermann.de" and ist_sichtbar(h, "p.zimmermann@ipb-zimmermann.de", "PText", "createPage")
    assert h.overview.mailChoices == []
    assert not any(qml_typ(item) == "PComboBox" and item.property("label") == "Rechnungsempfänger wählen" and sichtbar(item) for item in elemente(seite(h, "createPage")))
    assert h.overview.detailsVisible


def test_status_line_without_inactive_and_in_singular(ui_app, tmp_path: Path) -> None:
    h = ui_app
    einzeln_pruefen(h, excel(tmp_path / "fuenf.xlsx", aktiv=5))
    assert h.app.notices.get("info_excel").message == "5 aktive Verträge"  # kein »0 inaktiv ausgeblendet«
    einzeln_pruefen(h, excel(tmp_path / "eins.xlsx", aktiv=1))
    assert h.app.notices.get("info_excel").message == "1 aktiver Vertrag"
    einzeln_pruefen(h, excel(tmp_path / "eins_inaktiv.xlsx", aktiv=1, inaktiv=1))
    assert h.app.notices.get("info_excel").message == "1 aktiver Vertrag · 1 inaktiv ausgeblendet"


def test_several_recipients_show_a_count_and_the_choice(ui_app, tmp_path: Path) -> None:
    h = ui_app
    h.overview.mail = ""
    einzeln_pruefen(h, excel(tmp_path / "drei.xlsx", aktiv=6, mails=("a@x.de", "b@x.de", "c@x.de")))
    assert h.overview.mailValue == "3 erkannt" and ist_sichtbar(h, "3 erkannt", "PText", "createPage")
    assert h.overview.mailChoices == ["a@x.de", "b@x.de", "c@x.de"]
    combo = [item for item in elemente(seite(h, "createPage")) if qml_typ(item) == "PComboBox" and item.property("label") == "Rechnungsempfänger wählen"]
    assert len(combo) == 1 and sichtbar(combo[0])
    assert "a@x.de" not in json.dumps(fakten(h))  # keine lange Liste in der Karte
    assert h.overview.readyText.endswith("Bitte Rechnungsempfänger auswählen")
    assert h.item("readiness").property("text") == h.overview.readyText
    waehlen(h, "Rechnungsempfänger wählen", 1, "createPage")
    assert h.overview.mail == "b@x.de"


def test_no_recipient_means_no_empty_row(ui_app, tmp_path: Path) -> None:
    h = ui_app
    spalten = ["Vertrag-Nr.", "Beginnt am", "Abrechnungszyklus", "Netto [€]", "Zahlungsart", "Bemerkung", "Anwenderstatus"]
    einzeln_pruefen(h, excel(tmp_path / "ohne.xlsx", aktiv=2, spalten=spalten))
    assert h.app.notices.get("info_excel").severity == "success"
    assert h.overview.mailValue == "" and not ist_sichtbar(h, "Rechnungsempfänger", "PText", "createPage")
    assert not any("Rechnungsempfänger" in wert for wert in fakten(h).values())


def test_known_customer_appears_once(ui_app, tmp_path: Path) -> None:
    h = ui_app
    kunde = h.customers.customers.create("IPB Zimmermann", "123456", ["p.zimmermann@ipb-zimmermann.de"])
    h.customers.customers_changed()
    einzeln_pruefen(h, excel(tmp_path / "ipb.xlsx", mails=("p.zimmermann@ipb-zimmermann.de",)))
    bar = h.app.notices.get("kunde_match")
    assert bar.shown and bar.title == "Bekannter Kunde gefunden" and "IPB Zimmermann · 123456" in bar.message
    assert "p.zimmermann@" not in bar.message  # steht schon als Rechnungsempfänger darüber
    assert "Kunde" not in fakten(h)
    element_bar = infobar(h, "kunde_match", "createPage")
    assert sichtbar(element_bar) and karte(element_bar) == "Dateien"  # in der Dateikarte
    aktion(h, "kunde_match", "Übernehmen")
    assert kunde.id == h.customers.active_id
    assert not bar.shown and "Kunde" not in fakten(h)
    assert h.customers.activeTitle == "Kunde: IPB Zimmermann · 123456" and ist_sichtbar(h, "Kunde: IPB Zimmermann · 123456", "PText", "createPage")
    picker = h.item("customerPicker")
    assert picker.property("text") == "" and "IPB Zimmermann" not in h.customers.pickerPlaceholder  # das Auswahlfeld wiederholt die aktive Kundenakte nicht
    h.customers.detach_customer()
    einzeln_pruefen(h, excel(tmp_path / "neu.xlsx", mails=("info@unbekannt.de",)))
    assert fakten(h).get("Kunde") == "Nicht zugeordnet"


# --- Teil B: Stapel anlegen ----------------------------------------------------------------------------------


def test_empty_batch_offers_files_and_folder(ui_app, tmp_path: Path) -> None:
    from qtapp import files

    h = ui_app
    batch = stapel(h)
    assert not batch.hasItems and batch.model.rowCount() == 0
    texte = sichtbare_texte(h)
    assert "Noch keine Excel-Dateien hinzugefügt." in texte
    assert "Füge mehrere Excel-Dateien hinzu, um Vertragsübersichten gesammelt zu erstellen." in texte
    assert ist_sichtbar(h, "Dateien hinzufügen") and ist_sichtbar(h, "Ordner hinzufügen")
    # Die leere Karte bietet die Aktionen – oben keine Doppelung, noch kein Stapel und keine Liste
    assert not ist_sichtbar(h, "Excel-Dateien hinzufügen")
    assert not ist_sichtbar(h, "Bereite Übersichten erstellen") and not ist_sichtbar(h, "Alle auswählen", "PCheckBox")
    # »Dateien hinzufügen« aus der leeren Karte: danach Stapel und Liste statt der leeren Karte
    files.RESPONSES.append([str(excel(tmp_path / "a.xlsx")), str(excel(tmp_path / "b.xlsx"))])
    klicken(h, "Dateien hinzufügen")
    geprueft(h)
    pump(0.4)
    texte = sichtbare_texte(h)
    assert batch.hasItems and "Noch keine Excel-Dateien hinzugefügt." not in texte
    assert ist_sichtbar(h, "Excel-Dateien hinzufügen") and ist_sichtbar(h, "Bereite Übersichten erstellen") and ist_sichtbar(h, "Alle auswählen", "PCheckBox")
    assert set(zeilen_elemente(h)) == {"a.xlsx", "b.xlsx"}


def test_help_follows_the_open_view(ui_app) -> None:
    h = ui_app
    stapel(h)
    h.app.showHelp()
    batch_help = h.app.dialogs.history[-1]
    h.navigate("create", 0.2)
    h.app.showHelp()
    single_help = h.app.dialogs.history[-1]
    assert batch_help["kind"] == "steps" and batch_help["title"] == "Kurzanleitung – Stapel"
    assert any("Bereite Übersichten erstellen" in step for step in batch_help["data"]["steps"])
    assert single_help["title"] == "Kurzanleitung – Vertragsübersichten" and any("»Stapel«" in note for note in single_help["data"]["notes"])


def test_files_folders_and_duplicates(ui_app, tmp_path: Path) -> None:
    h = ui_app
    stapel(h, tmp_path / "out")
    ordner = tmp_path / "ordner"
    ordner.mkdir()
    a = excel(ordner / "a.xlsx")
    excel(ordner / "b.xlsx", mails=("x@y.de",))
    (ordner / "notiz.txt").write_text("keine Excel", encoding="utf-8")
    (ordner / "~$a.xlsx").write_bytes(b"Sperrdatei von Excel")
    unter = ordner / "unter"
    unter.mkdir()
    excel(unter / "tief.xlsx")  # nicht rekursiv
    assert h.batch.add([str(a)]) == (1, 0, 0)
    # a.xlsx kommt zweimal (über den Ordner und direkt) und steht schon im Stapel: 2 Doppelte, 1 neu (b.xlsx)
    assert h.batch.add([str(ordner), str(a).upper() if os.name == "nt" else str(a), str(tmp_path / "bild.png")]) == (1, 2, 1)
    assert sorted(item.name for item in h.batch.items) == ["a.xlsx", "b.xlsx"]
    info = h.app.notices.get("batch_info")
    assert info.severity == "warning" and "keine Excel" in info.message
    pump(0.4)
    assert sichtbar(infobar(h, "batch_info", "batchPage"))
    geprueft(h)
    assert set(status(h).values()) <= {"ready", "needs_input"}


def test_drop_adds_several_files_only_on_the_batch_page(ui_app, tmp_path: Path) -> None:
    h = ui_app
    a, b = excel(tmp_path / "a.xlsx"), excel(tmp_path / "b.xlsx")
    stapel(h)
    urls = [a.as_uri(), b.as_uri(), (tmp_path / "bild.png").as_uri()]
    assert h.app.dragEnter(urls) is True
    assert h.app.notices.get("batch_info").message.startswith("Loslassen")
    h.app.drop(urls)
    pump(0.2)
    assert [item.name for item in h.batch.items] == ["a.xlsx", "b.xlsx"]
    assert h.overview.excel != str(a)  # der Einzelmodus bleibt unberührt
    assert h.app.currentPage == "batch"
    # Im Einzelmodus: weiterhin genau eine Excel in den aktuellen Arbeitsablauf
    h.navigate("create", 0.2)
    h.app.drop([b.as_uri()])
    assert wait_until(lambda: h.overview.excel == str(b) and h.overview.analysis_for_current() is not None, 60)
    assert len(h.batch.items) == 2


# --- Teil B: Status, Kunden, Verarbeitung --------------------------------------------------------------------------


def test_single_file_batch(ui_app, tmp_path: Path) -> None:
    h = ui_app
    h.customers.customers.create("Beispiel GmbH", "123456", ["rechnung@kunde-a.de"])
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "vertrag_a.xlsx"))])
    geprueft(h)
    item = h.batch.items[0]
    assert item.status.value == "ready"
    row = h.batch.model.get(0)
    expected = ("vertrag_a.xlsx", "5 aktive · rechnung@kunde-a.de", "Kunde erkannt: Beispiel GmbH · 123456", "Bereit")
    assert (row["name"], row["facts"], row["detail"], row["status"]) == expected
    assert set(expected) <= sichtbare_texte(h)  # dieselben Texte in der Zeile der Liste
    klicken(h, "Bereite Übersichten erstellen")
    assert wait_until(lambda: not h.batch.running_now, 180)
    pump(0.3)
    assert item.status.value == "success" and Path(item.output) == tmp_path / "out" / "Vertragsuebersicht_Kd123456.pdf"
    result = h.batch.result
    assert result["shown"] and result["title"] == "Stapel abgeschlossen" and result["message"] == "1 Übersicht erstellt"
    assert {"Stapel abgeschlossen", "1 Übersicht erstellt"} <= sichtbare_texte(h)
    assert "Beispiel GmbH" in pdf_text(item.output)


def test_twenty_files_are_analysed_while_the_ui_stays_responsive(ui_app, tmp_path: Path) -> None:
    h = ui_app
    stapel(h, tmp_path / "out")
    files = [str(stapel_liste(tmp_path / f"liste_{i:02d}.xlsx", mail=f"kunde{i}@beispiel.de", aktiv=40)) for i in range(20)]
    h.batch.add(files)
    ok, longest, _steps = pumpen_bis(lambda: not any(item.status in WAITING for item in h.batch.items), 120)
    assert ok
    assert all(item.analysis is not None and item.analysis.active == 40 for item in h.batch.items)
    assert longest < 0.75, f"Oberfläche blockiert ({longest:.2f} s)"
    aktualisiert(h)
    assert h.batch.model.rowCount() == 20


def test_fifty_files_stay_fluid(ui_app, tmp_path: Path) -> None:
    h = ui_app
    stapel(h, tmp_path / "out")
    files = [str(stapel_liste(tmp_path / f"liste_{i:02d}.xlsx", mail=f"kunde{i}@beispiel.de", aktiv=10)) for i in range(50)]
    start = time.perf_counter()
    assert h.batch.add(files) == (50, 0, 0)
    # aufgenommen, ohne auf die Prüfung zu warten: Ergebnisse kommen erst über die Ereignisschleife
    assert all(item.status in WAITING for item in h.batch.items)
    assert wait_until(lambda: h.batch.model.rowCount() == 50, 3.0)
    added = time.perf_counter() - start
    assert added < 3.0, f"Hinzufügen dauerte {added:.2f} s"
    ok, longest, _steps = pumpen_bis(lambda: not any(item.status in WAITING for item in h.batch.items), 180)
    assert ok
    assert h.batch.count_items()["needs_input"] == 50
    assert longest < 0.75, f"Oberfläche blockiert ({longest:.2f} s)"
    aktualisiert(h)
    for key in ("needs_input", "all"):
        start = time.perf_counter()
        filter_waehlen(h, key)
        aktualisiert(h)
        assert h.batch.filter == key and h.batch.visibleCount == 50
        assert time.perf_counter() - start < 1.0, key
    start = time.perf_counter()
    h.batch.refresh_all()  # z. B. nach einer Änderung an Kundenakten
    aktualisiert(h)
    assert time.perf_counter() - start < 1.5
    for item in h.batch.items:
        h.batch.edit(item.id, company="Firma", number=item.name[6:8])
    pump(0.3)
    assert h.batch.count_items()["ready"] == 50


def test_mixed_customers_get_the_right_status(ui_app, tmp_path: Path) -> None:
    h = ui_app
    h.customers.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    h.customers.customers.create("Muster AG", "200", ["buchhaltung@kunde-b.de"])
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "bekannt.xlsx")), str(excel(tmp_path / "unbekannt.xlsx", mails=("info@neu.de",))), str(excel(tmp_path / "konflikt.xlsx", mails=("rechnung@kunde-a.de", "buchhaltung@kunde-b.de")))])
    geprueft(h)
    assert status(h) == {"bekannt.xlsx": "ready", "unbekannt.xlsx": "needs_input", "konflikt.xlsx": "needs_input"}
    konflikt = h.batch.resolution(eintrag(h, "konflikt.xlsx").id)
    assert konflikt.customer is None and konflikt.company == "" and konflikt.number == ""  # nie automatisch entscheiden
    assert h.batch.count_items() == {"all": 3, "ready": 1, "needs_input": 2, "failed": 0, "done": 0}
    assert h.batch.summaryText == "3 Dateien · 1 bereit · 2 Angaben erforderlich"
    assert h.item("batchSummary").property("text") == h.batch.summaryText
    # Konflikt bewusst lösen: Eintrag öffnen, »Kunden auswählen …« (Dialog wählt im Test den ersten Kandidaten)
    item = eintrag(h, "konflikt.xlsx")
    h.batch.showDetail(item.id)
    pump(0.4)
    assert h.batch.customerTitle == "Mehrere bekannte Kunden"
    klicken(h, "Kunden auswählen …")
    pump(0.2)
    assert h.app.dialogs.history[-1]["kind"] == "choose_customer"
    res = h.batch.resolution(item.id)
    assert res.customer is not None and res.customer_source == "gewählt" and res.customer.company == "Beispiel GmbH"
    # Von den beiden Empfängern gehört genau einer zur gewählten Kundenakte – wie im Einzelmodus
    assert item.status.value == "ready" and res.email == "rechnung@kunde-a.de" and res.email_source == "Kundenakte"
    waehlen(h, "Rechnungsempfänger", h.batch.mailChoices.index("buchhaltung@kunde-b.de"))  # bewusst anders gewählt
    pump(0.2)
    assert h.batch.resolution(item.id).email == "buchhaltung@kunde-b.de" and item.status.value == "ready"


def test_missing_number_does_not_hold_back_the_others(backend, tmp_path: Path) -> None:
    h = backend
    h.customers.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "bekannt.xlsx")), str(excel(tmp_path / "ohne_nummer.xlsx", mails=("info@neu.de",)))])
    geprueft(h)
    offen = eintrag(h, "ohne_nummer.xlsx")
    h.batch.edit(offen.id, company="Neu GmbH")  # nur die Firma – Kundennummer fehlt weiterhin
    pump(0.2)
    assert offen.status.value == "needs_input" and [i.code for i in offen.issues] == ["number_missing"]
    erstellen(h)
    assert eintrag(h, "bekannt.xlsx").status.value == "success"
    assert offen.status.value == "needs_input"  # bleibt »Angaben erforderlich«, schlägt nicht fehl
    summary = h.batch.summary
    assert summary.created == 1 and summary.skipped == 1 and summary.failed == 0
    # nachträglich im Eintrag ergänzen (Feld »Kundennummer« der Detailansicht) und separat verarbeiten
    h.batch.show_detail(offen.id)
    assert h.batch.company == "Neu GmbH" and h.batch.numberError
    h.batch.number = "777"
    assert wait_until(lambda: offen.overrides.number == "777", 5)
    pump(0.2)
    assert offen.status.value == "ready" and offen.overrides.company == "Neu GmbH"
    erstellen(h)
    assert offen.status.value == "success" and (tmp_path / "out" / "Vertragsuebersicht_Kd777.pdf").is_file()


def test_broken_or_empty_files_fail_alone(ui_app, tmp_path: Path) -> None:
    h = ui_app
    stapel(h, tmp_path / "out")
    kaputt = tmp_path / "kaputt.xlsx"
    kaputt.write_bytes(b"keine Excel-Datei")
    gut = excel(tmp_path / "gut.xlsx")
    leer = excel(tmp_path / "leer.xlsx", aktiv=0, inaktiv=2)
    h.batch.add([str(kaputt), str(gut), str(leer)])
    geprueft(h)
    h.batch.edit(eintrag(h, "gut.xlsx").id, company="Gut GmbH", number="1")
    pump(0.2)
    assert status(h) == {"kaputt.xlsx": "failed", "gut.xlsx": "ready", "leer.xlsx": "failed"}
    rows = zeilen(h)
    assert rows["leer.xlsx"]["status"] == "Keine aktiven Verträge" and "0 aktive" not in rows["leer.xlsx"]["facts"]
    assert rows["kaputt.xlsx"]["status"] == "Excel nicht lesbar" and "(" not in rows["kaputt.xlsx"]["detail"]
    assert {"Keine aktiven Verträge", "Excel nicht lesbar"} <= sichtbare_texte(h)
    erstellen(h)
    assert status(h) == {"kaputt.xlsx": "failed", "gut.xlsx": "success", "leer.xlsx": "failed"}
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["Vertragsuebersicht_Kd1.pdf"]
    assert h.batch.summary.failed == 2 and h.batch.summary.created == 1


def test_file_deleted_before_processing_fails_only_this_entry(ui_app, tmp_path: Path, monkeypatch) -> None:
    h = ui_app
    stapel(h, tmp_path / "out")
    files = [excel(tmp_path / f"liste_{i}.xlsx") for i in range(3)]
    h.batch.add([str(f) for f in files])
    geprueft(h)
    for index, item in enumerate(h.batch.items):
        h.batch.edit(item.id, company=f"Firma {index}", number=str(index + 10))
    pump(0.2)
    original = processor.run_job

    def run(job, cancelled):
        if job.excel == str(files[0]):
            files[1].unlink()  # während der Verarbeitung von Datei 1 wird Datei 2 gelöscht
        return original(job, cancelled)

    monkeypatch.setattr(processor, "run_job", run)
    erstellen(h)
    assert status(h) == {"liste_0.xlsx": "success", "liste_1.xlsx": "failed", "liste_2.xlsx": "success"}
    geloescht = eintrag(h, "liste_1.xlsx")
    assert geloescht.issues[0].code == "file_missing"
    assert zeilen(h)["liste_1.xlsx"]["status"] == "Datei nicht gefunden"
    summary = h.batch.summary
    assert (summary.created, summary.failed, summary.skipped) == (2, 1, 0)
    assert h.batch.result["message"] == "2 Übersichten erstellt · 1 fehlgeschlagen"
    assert "2 Übersichten erstellt · 1 fehlgeschlagen" in sichtbare_texte(h)


def test_existing_pdf_is_never_overwritten_by_default(backend, tmp_path: Path) -> None:
    h = backend
    out = tmp_path / "out"
    out.mkdir()
    vorhanden = out / "Vertragsuebersicht_Kd42.pdf"
    vorhanden.write_bytes(b"%PDF-1.4 alte Datei")
    stapel(h, out)
    h.batch.add([str(excel(tmp_path / "a.xlsx"))])
    geprueft(h)
    item = h.batch.items[0]
    h.batch.edit(item.id, company="A", number="42")
    pump(0.2)
    erstellen(h)
    assert vorhanden.read_bytes() == b"%PDF-1.4 alte Datei"
    assert item.status.value == "warning" and Path(item.output).name == "Vertragsuebersicht_Kd42_2.pdf"
    assert "gespeichert als »Vertragsuebersicht_Kd42_2.pdf«" in item.notes[0]
    assert not any(p.name.endswith(".tmp") for p in out.iterdir())


def test_customer_template_and_item_override(backend, tmp_path: Path) -> None:
    h = backend
    h.app.state.save_vorlage({"name": "Quer", "format": "quer"})
    h.app.state.save_vorlage({"name": "Hoch", "format": "hoch", "titel": "Hochformat"})
    h.customers.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"], template="Quer")
    h.customers.customers.create("Muster AG", "200", ["buchhaltung@kunde-b.de"], template="Quer")
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "a.xlsx")), str(excel(tmp_path / "b.xlsx", mails=("buchhaltung@kunde-b.de",)))])
    geprueft(h)
    b = eintrag(h, "b.xlsx")
    h.batch.apply_template("Hoch", [b.id])  # im Eintrag gesetzt: hat Vorrang vor der Kundenvorlage
    pump(0.2)
    assert h.batch.resolution(b.id).template_source == "Eintrag"
    erstellen(h)
    breite, hoehe = pypdf.PdfReader(str(tmp_path / "out" / "Vertragsuebersicht_Kd100.pdf")).pages[0].mediabox.upper_right
    assert breite > hoehe  # Kundenvorlage »Quer«
    breite, hoehe = pypdf.PdfReader(str(tmp_path / "out" / "Vertragsuebersicht_Kd200.pdf")).pages[0].mediabox.upper_right
    assert breite < hoehe and "Hochformat" in pdf_text(tmp_path / "out" / "Vertragsuebersicht_Kd200.pdf")


def test_rich_text_and_standard_footer_per_customer(ui_app, tmp_path: Path) -> None:
    import appstate
    from tools.contract_overview.customers.models import TextBlock

    h = ui_app
    assert h.overview.footer.attached  # Standard-Fußzeile aus dem Editor der »Darstellung«
    customers = h.customers.customers
    customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"], footer=TextBlock("Fußzeile für {firma}", None), header=TextBlock("Kopf Beispiel", None))
    customers.create("Muster AG", "200", ["buchhaltung@kunde-b.de"], footer=TextBlock("Sonderpreise Muster", None))
    customers.create("Leer GmbH", "300", ["info@leer.de"], footer=TextBlock("", None))  # alter leerer Wert
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "a.xlsx")), str(excel(tmp_path / "b.xlsx", mails=("buchhaltung@kunde-b.de",))), str(excel(tmp_path / "c.xlsx", mails=("info@leer.de",)))])
    geprueft(h)
    erstellen(h)
    a = pdf_text(tmp_path / "out" / "Vertragsuebersicht_Kd100.pdf")
    b = pdf_text(tmp_path / "out" / "Vertragsuebersicht_Kd200.pdf")
    c = pdf_text(tmp_path / "out" / "Vertragsuebersicht_Kd300.pdf")
    assert "Fußzeile für Beispiel GmbH" in a and "Kopf Beispiel" in a and "Sonderpreise Muster" not in a
    assert "Sonderpreise Muster" in b and "Kopf Beispiel" not in b
    standard = " ".join(appstate.DEFAULT_FOOTER.split())
    assert standard[:60] in c  # die Standard-Fußzeile verschwindet nie


def test_preview_of_a_batch_entry_uses_the_same_pipeline(ui_app, tmp_path: Path) -> None:
    h = ui_app
    h.customers.customers.create("Beispiel GmbH", "123456", ["rechnung@kunde-a.de"])
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "a.xlsx"))])
    geprueft(h)
    item = h.batch.items[0]
    runs = h.preview.runs
    h.batch.showDetail(item.id)
    pump(0.4)
    assert h.batch.canPreview
    klicken(h, "Vorschau")  # Schaltfläche im Eintrag
    assert wait_until(lambda: h.preview.runs > runs and h.preview.state == "current", 60)
    source = h.app.notices.get("preview_source")
    assert h.app.currentPage == "preview" and source.shown and "a.xlsx" in source.message
    text = pdf_text(h.preview._doc.path)
    assert "Beispiel GmbH" in text and "123456" in text
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())  # nichts im Zielordner
    h.navigate("create", 0.2)
    assert h.preview._item is None  # beim nächsten Öffnen wieder die Einzelübersicht


def test_failed_job_does_not_stop_the_batch(ui_app, tmp_path: Path) -> None:
    h = ui_app
    stapel(h, tmp_path / "out")
    files = [str(excel(tmp_path / f"liste_{i:02d}.xlsx")) for i in range(10)]
    h.batch.add(files)
    geprueft(h)
    kaputt = tmp_path / "kaputt.png"
    kaputt.write_bytes(b"kein Bild")
    for index, item in enumerate(h.batch.items):
        h.batch.edit(item.id, company=f"Firma {index}", number=str(1000 + index), logo=str(kaputt) if index == 3 else None)
    pump(0.2)
    erstellen(h)
    stati = [item.status.value for item in h.batch.items]
    assert stati[3] == "failed" and stati.count("success") == 9
    assert h.batch.items[3].error == "Das Logo ist keine lesbare Bilddatei."
    assert zeilen(h)["liste_03.xlsx"]["detail"] == "Das Logo ist keine lesbare Bilddatei."
    assert len(list((tmp_path / "out").iterdir())) == 9
    log = h.batch.log.path.read_text(encoding="utf-8")
    assert "liste_03.xlsx" in log and str(tmp_path) not in log  # keine vollständigen Pfade


def test_cancel_keeps_finished_pdfs_and_leaves_no_partial_files(ui_app, tmp_path: Path, monkeypatch) -> None:
    h = ui_app
    stapel(h, tmp_path / "out")
    h.batch.add([str(stapel_liste(tmp_path / f"liste_{i}.xlsx", aktiv=20)) for i in range(5)])
    geprueft(h)
    for index, item in enumerate(h.batch.items):
        h.batch.edit(item.id, company=f"Firma {index}", number=str(index + 1))
    pump(0.2)
    original = processor.run_job

    def slow(job, cancelled):
        result = original(job, cancelled)
        time.sleep(0.3)
        return result

    monkeypatch.setattr(processor, "run_job", slow)
    h.batch.start_run()
    assert wait_until(lambda: sum(item.status.value == "success" for item in h.batch.items) >= 2, 60)
    klicken(h, "Stapel abbrechen")
    assert wait_until(lambda: not h.batch.running_now, 60)
    pump(0.3)
    created = [item for item in h.batch.items if item.status.value == "success"]
    assert 2 <= len(created) < 5 and h.batch.summary.aborted
    assert [item.status.value for item in h.batch.items if item.status.value != "success"] == ["ready"] * (5 - len(created))
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert len(names) == len(created) and not any(name.endswith(".tmp") for name in names)
    for name in names:
        assert pypdf.PdfReader(str(tmp_path / "out" / name)).pages
    assert h.batch.result["title"] == "Stapel abgebrochen" and "Stapel abgebrochen" in sichtbare_texte(h)


def test_cancel_during_a_running_pdf_counts_it_as_not_processed(ui_app, tmp_path: Path, monkeypatch) -> None:
    h = ui_app
    stapel(h, tmp_path / "out")
    h.batch.add([str(stapel_liste(tmp_path / f"liste_{i}.xlsx", aktiv=5)) for i in range(5)])
    geprueft(h)
    for index, item in enumerate(h.batch.items):
        h.batch.edit(item.id, company=f"Firma {index}", number=str(index + 1))
    pump(0.2)
    original = processor.run_job

    def run(job, cancelled):
        if job.label == "Firma 2":  # die dritte PDF läuft, als abgebrochen wird
            deadline = time.monotonic() + 30
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.02)
        return original(job, cancelled)

    monkeypatch.setattr(processor, "run_job", run)
    h.batch.start_run()
    assert wait_until(lambda: h.batch.items[2].status.value == "processing", 60)
    pump(0.1)
    assert h.batch.currentText == "Firma 2 wird verarbeitet …"
    klicken(h, "Stapel abbrechen")
    assert wait_until(lambda: not h.batch.running_now, 60)
    pump(0.3)
    assert [item.status.value for item in h.batch.items] == ["success", "success", "ready", "ready", "ready"]
    summary = h.batch.summary
    assert (summary.created, summary.skipped, summary.failed, summary.cancelled, summary.aborted) == (2, 0, 0, 3, True)
    assert h.batch.result["message"] == "2 Übersichten erstellt · 3 nicht verarbeitet"
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert names == ["Vertragsuebersicht_Kd1.pdf", "Vertragsuebersicht_Kd2.pdf"]  # keine halbe dritte PDF


def test_retry_processes_only_failed_entries(ui_app, tmp_path: Path) -> None:
    from PIL import Image

    h = ui_app
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "ok.xlsx")), str(excel(tmp_path / "logo.xlsx"))])
    geprueft(h)
    ok, logo_item = eintrag(h, "ok.xlsx"), eintrag(h, "logo.xlsx")
    kaputt = tmp_path / "logo.png"
    kaputt.write_bytes(b"kein Bild")
    h.batch.edit(ok.id, company="A", number="1")
    h.batch.edit(logo_item.id, company="B", number="2", logo=str(kaputt))
    pump(0.2)
    erstellen(h)
    assert (ok.status.value, logo_item.status.value) == ("success", "failed")
    first = Path(ok.output).stat().st_mtime_ns
    Image.new("RGB", (40, 20), "blue").save(kaputt)  # Fehler behoben
    klicken(h, "Fehlgeschlagene erneut versuchen")
    assert wait_until(lambda: not h.batch.running_now and logo_item.status.value == "success", 60)
    assert Path(ok.output).stat().st_mtime_ns == first  # der erfolgreiche Eintrag wurde nicht erneut erstellt
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["Vertragsuebersicht_Kd1.pdf", "Vertragsuebersicht_Kd2.pdf"]


def test_customer_record_gets_only_activity_metadata(backend, tmp_path: Path) -> None:
    h = backend
    kunde = h.customers.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"], template="", logo="", target_dir="")
    before = kunde.to_dict()
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "a.xlsx"))])
    geprueft(h)
    item = h.batch.items[0]
    h.batch.apply_template("", [item.id])  # nur für den Eintrag
    h.batch.edit(item.id, target_dir=str(tmp_path / "eigen"))
    pump(0.2)
    erstellen(h)
    after = h.customers.customers.get(kunde.id).to_dict()
    assert after["last_excel"] == item.path and after["last_pdf"] == item.output and after["last_used_at"] > (before["last_used_at"] or "")
    for key in ("company", "number", "emails", "logo", "target_dir", "template", "header", "footer"):
        assert after[key] == before[key], key  # keine Darstellungswerte ungefragt gespeichert
    saved = json.loads(Path(h.customers.customers.path).read_text(encoding="utf-8"))
    assert any(entry.get("last_pdf") == item.output for entry in saved["customers"])


def test_new_email_is_only_learned_after_remember(ui_app, tmp_path: Path) -> None:
    h = ui_app
    kunde = h.customers.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "neu.xlsx", mails=("neu@kunde-a.de",))), str(excel(tmp_path / "noch.xlsx", mails=("neu@kunde-a.de",)))])
    geprueft(h)
    neu, noch = eintrag(h, "neu.xlsx"), eintrag(h, "noch.xlsx")
    h.batch.showDetail(neu.id)
    pump(0.4)
    klicken(h, "Kunden auswählen …")  # manuell gewählt (Dialog: erster Kunde)
    pump(0.2)
    assert h.customers.customers.get(kunde.id).emails == ["rechnung@kunde-a.de"]  # nicht automatisch gelernt
    bar = h.app.notices.get("batch_mail_info")
    assert bar.shown and bar.title == "Diese E-Mail künftig diesem Kunden zuordnen?"
    assert sichtbar(infobar(h, "batch_mail_info", "batchPage"))
    assert noch.status.value == "needs_input"
    aktion(h, "batch_mail_info", "Zuordnung merken")
    assert "neu@kunde-a.de" in h.customers.customers.get(kunde.id).emails
    assert h.batch.resolution(noch.id).customer_source == "erkannt" and noch.status.value == "ready"  # jetzt wiedererkannt


def test_customer_changes_apply_but_item_values_stay(backend, tmp_path: Path) -> None:
    h = backend
    customers = h.customers.customers
    kunde = customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "a.xlsx"))])
    geprueft(h)
    item = h.batch.items[0]
    h.batch.edit(item.id, number="555")  # bewusst im Eintrag
    customers.update(kunde.id, company="Beispiel GmbH & Co. KG", number="101")
    h.customers.customers_changed()
    pump(0.2)
    res = h.batch.resolution(item.id)
    assert res.company == "Beispiel GmbH & Co. KG" and res.number == "555"
    customers.delete(kunde.id)
    h.customers.customers_changed()
    pump(0.2)
    assert h.batch.resolution(item.id).customer is None and item.status.value == "needs_input"


def test_changed_excel_is_checked_again_before_processing(backend, tmp_path: Path) -> None:
    h = backend
    h.customers.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    h.customers.customers.create("Muster AG", "200", ["buchhaltung@kunde-b.de"])
    stapel(h, tmp_path / "out")
    pfad = excel(tmp_path / "a.xlsx")
    h.batch.add([str(pfad)])
    geprueft(h)
    item = h.batch.items[0]
    assert h.batch.resolution(item.id).customer.company == "Beispiel GmbH"
    excel(pfad, mails=("buchhaltung@kunde-b.de",))  # jetzt die Liste eines anderen Kunden
    os.utime(pfad, ns=(item.stamp.mtime_ns + 5_000_000_000,) * 2)
    erstellen(h)
    assert not (tmp_path / "out" / "Vertragsuebersicht_Kd100.pdf").exists()  # nie mit der alten Zuordnung
    assert item.status.value == "ready" and h.batch.resolution(item.id).customer.company == "Muster AG"
    assert any("geändert" in note for note in item.notes)
    erstellen(h)
    assert (tmp_path / "out" / "Vertragsuebersicht_Kd200.pdf").is_file()


def test_filters_and_bulk_actions(ui_app, tmp_path: Path) -> None:
    h = ui_app
    h.app.state.save_vorlage({"name": "Quer", "format": "quer"})
    h.customers.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "a.xlsx")), str(excel(tmp_path / "b.xlsx", mails=("x@y.de",))), str(excel(tmp_path / "c.xlsx", mails=("z@y.de",)))])
    geprueft(h)
    filter_waehlen(h, "needs_input")
    pump(0.3)
    assert [row["name"] for row in h.batch.model.items()] == ["b.xlsx", "c.xlsx"]
    assert set(zeilen_elemente(h)) == {"b.xlsx", "c.xlsx"}
    klicken(h, "Alle auswählen", "PCheckBox")
    pump(0.2)
    assert [item.name for item in h.batch.selected_items()] == ["b.xlsx", "c.xlsx"]  # nur die sichtbaren
    assert h.batch.selectedText == "2 ausgewählt"
    klicken(h, "Vorlage anwenden …")  # Auswahl im Dialog: erste Vorlage
    pump(0.2)
    assert h.app.dialogs.history[-1]["kind"] == "choose_template"
    assert [item.overrides.template for item in h.batch.items] == [None, "Quer", "Quer"]
    klicken(h, "Auswahl entfernen")
    pump(0.2)
    assert [item.name for item in h.batch.items] == ["a.xlsx"]
    aktion(h, "batch_info", "Rückgängig")
    assert [item.name for item in h.batch.items] == ["a.xlsx", "b.xlsx", "c.xlsx"]
    filter_waehlen(h, "all")
    pump(0.3)
    assert h.batch.model.rowCount() == 3 and set(zeilen_elemente(h)) == {"a.xlsx", "b.xlsx", "c.xlsx"}


def test_queue_is_restored_after_a_restart(ui_app, tmp_path: Path, config_file: Path) -> None:
    h = ui_app
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "a.xlsx")), str(excel(tmp_path / "b.xlsx", mails=("x@y.de",)))])
    geprueft(h)
    a, b = h.batch.items
    h.batch.edit(a.id, company="A", number="1")
    h.batch.edit(b.id, company="B GmbH")
    pump(0.2)
    erstellen(h)
    assert a.status.value == "success"
    neu = neustart(h)
    assert [item.name for item in neu.batch.items] == ["a.xlsx", "b.xlsx"]
    assert neu.batch.items[0].status.value == "success" and neu.batch.items[0].output == a.output
    geprueft(neu)
    assert neu.batch.items[1].overrides.company == "B GmbH" and neu.batch.items[1].status.value == "needs_input"
    assert neu.batch.settings.target_dir == str(tmp_path / "out")
    stapel(neu)
    assert set(zeilen_elemente(neu)) == {"a.xlsx", "b.xlsx"}
    saved = json.loads((config_file.parent / "stapel.json").read_text(encoding="utf-8"))
    assert "analysis" not in json.dumps(saved) and "Modul" not in json.dumps(saved)  # nur Pfade und Angaben


def test_new_batch_keeps_customers_templates_and_settings(ui_app, tmp_path: Path) -> None:
    h = ui_app
    h.app.state.save_vorlage({"name": "Quer", "format": "quer"})
    kunde = h.customers.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(h, tmp_path / "out")
    h.batch.update_settings(template="Quer", subfolders=True)
    pfad = excel(tmp_path / "a.xlsx")
    h.batch.add([str(pfad)])
    geprueft(h)
    klicken(h, "Neuer Stapel")  # Rückfrage bestätigt der Test
    pump(0.3)
    assert h.app.dialogs.history[-1]["title"] == "Neuen Stapel beginnen?"
    assert h.batch.items == [] and not h.batch.hasItems and "Noch keine Excel-Dateien hinzugefügt." in sichtbare_texte(h)
    assert h.customers.customers.get(kunde.id) is not None and h.app.state.find_vorlage("Quer") is not None
    assert h.batch.settings.template == "Quer" and h.batch.settings.subfolders
    assert pfad.is_file()


def test_edit_single_takes_the_entry_into_the_single_workflow(ui_app, tmp_path: Path) -> None:
    h = ui_app
    kunde = h.customers.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(h, tmp_path / "out")
    pfad = excel(tmp_path / "a.xlsx")
    h.batch.add([str(pfad)])
    geprueft(h)
    h.overview.firma = "Vorher AG"
    h.batch.showDetail(h.batch.items[0].id)
    pump(0.4)
    klicken(h, "Einzeln bearbeiten")
    assert wait_until(lambda: h.overview.excel == str(pfad) and h.overview.analysis_for_current() is not None, 60)
    pump(0.3)
    assert h.app.currentPage == "create" and h.overview.excel == str(pfad)
    active = h.customers.active_customer()
    assert active is not None and active.id == kunde.id
    assert (h.overview.firma, h.overview.kd) == ("Beispiel GmbH", "100")
    assert len(h.batch.items) == 1  # der Stapel-Eintrag bleibt
    aktion(h, "kunde_info", "Rückgängig")
    assert h.overview.firma == "Vorher AG"


def test_single_mode_and_repair_still_work_after_a_batch(ui_app, tmp_path: Path, excel_file: Path) -> None:
    import pdfsamples as samples

    h = ui_app
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "a.xlsx"))])
    geprueft(h)
    h.batch.edit(h.batch.items[0].id, company="A", number="1")
    pump(0.2)
    erstellen(h)
    # Einzelmodus unverändert
    h.navigate("create", 0.2)
    c = h.overview
    c.ziel = str(tmp_path / "einzel")
    c.pdfOeffnen = False
    c.use_excel(str(excel_file))
    assert wait_until(lambda: c.readyKind == "success", 60)
    c.start_pdf()
    assert wait_until(lambda: not c.busy, 90)
    assert h.app.notices.get("pdf_info").severity == "success" and (tmp_path / "einzel" / "Vertragsuebersicht_Kd10042.pdf").is_file()
    # PDF reparieren: unabhängig vom Stapel
    h.app.openTool("repair")
    pump(0.2)
    pdf = samples.xref_offset(tmp_path / "defekt.pdf")
    h.repair.use(str(pdf))
    assert wait_until(lambda: not h.repair.busy and h.repair.analysis is not None, 90)
    assert h.repair.analysis.condition.value == "repairable"
    assert len(h.batch.items) == 1 and h.batch.items[0].status.value == "success"


def test_close_during_a_batch_cancels_cleanly(ui_app, tmp_path: Path, monkeypatch) -> None:
    h = ui_app
    stapel(h, tmp_path / "out")
    h.batch.add([str(stapel_liste(tmp_path / f"liste_{i}.xlsx", aktiv=20)) for i in range(4)])
    geprueft(h)
    for index, item in enumerate(h.batch.items):
        h.batch.edit(item.id, company=f"F{index}", number=str(index + 1))
    pump(0.2)
    original = processor.run_job
    monkeypatch.setattr(processor, "run_job", lambda job, cancelled: (time.sleep(0.4), original(job, cancelled))[1])
    h.batch.start_run()
    assert wait_until(lambda: h.batch.runner is not None and h.batch.runner.current is not None, 30)
    assert h.app.requestClose() is True  # Rückfrage bestätigt der Test
    assert h.app.dialogs.history[-1]["title"] == "Stapel wird gerade erstellt"
    assert h.batch.runner.finished  # die laufende PDF wurde sauber beendet
    out = tmp_path / "out"
    names = [p.name for p in out.iterdir()] if out.exists() else []
    assert not any(name.endswith(".tmp") for name in names)
    for name in names:
        assert pypdf.PdfReader(str(out / name)).pages


# --- Qt: Liste und viele Dateien ----------------------------------------------------------------------------------


def test_status_changes_update_single_rows_without_reset(ui_app, tmp_path: Path, monkeypatch) -> None:
    """Statt »nur die geänderte Zeile neu zeichnen« (Tk): Während eines Laufs meldet das
    Listenmodell nur einzelne geänderte Zeilen – kein Neuaufbau, keine eingefügten oder
    entfernten Zeilen, und die angezeigten Zeilen (Delegates) bleiben dieselben Objekte."""
    import shiboken6

    h = ui_app
    stapel(h, tmp_path / "out")
    h.batch.add([str(stapel_liste(tmp_path / f"liste_{i}.xlsx", aktiv=3)) for i in range(5)])
    geprueft(h)
    for index, item in enumerate(h.batch.items):
        h.batch.edit(item.id, company=f"Firma {index}", number=str(index + 1))
    aktualisiert(h)
    pump(0.2)
    model = h.batch.model
    assert [row["statusKey"] for row in model.items()] == ["ready"] * 5
    rows_before = {name: shiboken6.getCppPointer(item)[0] for name, item in zeilen_elemente(h).items()}
    assert set(rows_before) == {f"liste_{i}.xlsx" for i in range(5)}
    status_role = next(role for role, name in model.roleNames().items() if bytes(name) == b"status")
    resets = model.resets
    structure: list[str] = []
    changes: list[tuple[int, int, tuple, str]] = []
    model.modelReset.connect(lambda: structure.append("reset"))
    model.rowsInserted.connect(lambda *_args: structure.append("inserted"))
    model.rowsRemoved.connect(lambda *_args: structure.append("removed"))
    model.rowsMoved.connect(lambda *_args: structure.append("moved"))
    model.layoutChanged.connect(lambda *_args: structure.append("layout"))
    model.dataChanged.connect(lambda top, bottom, roles=(): changes.append((top.row(), bottom.row(), tuple(roles), model.get(top.row())["statusKey"])))
    original = processor.run_job

    def run(job, cancelled):
        time.sleep(0.15)  # »Wird erstellt …« bleibt kurz sichtbar
        return original(job, cancelled)

    monkeypatch.setattr(processor, "run_job", run)
    erstellen(h)
    aktualisiert(h)
    assert [item.status.value for item in h.batch.items] == ["success"] * 5
    assert model.resets == resets and structure == []  # kein Neuaufbau, keine Zeile neu angelegt
    assert changes and all(top == bottom for top, bottom, _roles, _key in changes)  # immer genau eine Zeile
    assert {top for top, _bottom, _roles, _key in changes} == set(range(5))
    for row in range(5):
        seen = [key for top, _bottom, roles, key in changes if top == row and status_role in roles]
        assert "processing" in seen and seen[-1] == "success" and seen.index("processing") < len(seen) - 1, (row, seen)
    rows_after = {name: shiboken6.getCppPointer(item)[0] for name, item in zeilen_elemente(h).items()}
    assert rows_after == rows_before  # dieselben Zeilen-Objekte, nur neu beschriftet
    assert {row["status"] for row in model.items()} == {"Erstellt"}
    assert all(item.property("status") == "Erstellt" for item in zeilen_elemente(h).values())


def test_hundred_excel_files_are_analysed_and_created_while_the_ui_stays_responsive(ui_app, tmp_path: Path) -> None:
    """QA-Plan 2.7.0: Stapel mit 100 Excel-Dateien (ganzer Ordner). Alle werden geprüft und als PDF
    erstellt; die Oberfläche verarbeitet währenddessen laufend Ereignisse (kein Schritt blockiert
    ~1 s), der Fortschritt wird fortlaufend angezeigt und QML zeichnet weiter."""
    h = ui_app
    out = tmp_path / "out"
    stapel(h, out)
    quellen = tmp_path / "listen"
    quellen.mkdir()
    for index in range(100):
        mail = f"kunde{index}@beispiel.de"
        rows = [
            [f"V-{index}-1", datetime(2023, 1, 15), "jährlich", 10.0 + index, "Sofort", "Hotline Premium", mail, 50000 + index, f"Firma {index:03d} GmbH", "Aktiv"],
            [f"V-{index}-2", datetime(2022, 6, 1), "monatlich", 20.0 + index, "Lastschrift", "Pflege Warenwirtschaft", mail, 50000 + index, f"Firma {index:03d} GmbH", "Aktiv"],
        ]
        write_excel(quellen / f"kunde_{index:03d}.xlsx", rows)
    frames = [0]
    h.window.frameSwapped.connect(lambda: frames.__setitem__(0, frames[0] + 1))

    # Hinzufügen und Prüfen
    start = time.perf_counter()
    assert h.batch.add([str(quellen)]) == (100, 0, 0)
    ok, longest, steps = pumpen_bis(lambda: not any(item.status in WAITING for item in h.batch.items), 120)
    checked = time.perf_counter() - start
    assert ok, status(h)
    assert longest < 1.0, f"Oberfläche blockiert beim Prüfen ({longest:.2f} s)"
    assert steps >= checked / 0.25, f"zu wenige Durchläufe der Ereignisschleife ({steps} in {checked:.1f} s)"
    aktualisiert(h)
    assert h.batch.count_items()["ready"] == 100 and h.batch.model.rowCount() == 100

    # Erstellen
    progress: set[float] = set()
    frames_before = frames[0]
    start = time.perf_counter()
    klicken(h, "Bereite Übersichten erstellen")
    ok, longest, steps = pumpen_bis(lambda: not h.batch.running_now, 170, beobachten=lambda: progress.add(round(h.batch.progress, 3)))
    duration = time.perf_counter() - start
    assert ok, "Stapel nicht rechtzeitig fertig"
    aktualisiert(h)
    assert longest < 1.0, f"Oberfläche blockiert beim Erstellen ({longest:.2f} s)"
    assert steps >= duration / 0.25, f"zu wenige Durchläufe der Ereignisschleife ({steps} in {duration:.1f} s)"
    assert len(progress) >= 20, f"Fortschritt nur {len(progress)}-mal aktualisiert"
    assert frames[0] - frames_before >= 20, "QML hat während des Laufs nicht weitergezeichnet"
    summary = h.batch.summary
    assert (summary.created, summary.failed, summary.skipped, summary.aborted) == (100, 0, 0, False)
    assert all(item.status.value == "success" for item in h.batch.items)
    pdfs = sorted(p.name for p in out.iterdir())
    assert len(pdfs) == 100 and all(name.endswith(".pdf") for name in pdfs)
    assert pdfs[0] == "Vertragsuebersicht_Kd50000.pdf" and pdfs[-1] == "Vertragsuebersicht_Kd50099.pdf"
    assert h.batch.result["message"] == "100 Übersichten erstellt"


def test_typing_in_an_entry_is_not_rewritten_while_editing(ui_app, tmp_path: Path) -> None:
    """Eingaben im Eintrag werden während des Tippens nicht umgeschrieben – wie in 2.6.1, wo ein Feld
    mit Tastaturfokus nie neu geladen wurde. Eine kurze Pause nach einem Leerzeichen darf das
    Leerzeichen nicht entfernen: »Neu GmbH«, nicht »NeuGmbH« (in Kundenakte, Liste und PDF)."""
    h = ui_app
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "a.xlsx", mails=("info@neu.de",)))])
    geprueft(h)
    item = h.batch.items[0]
    h.batch.showDetail(item.id)
    pump(0.4)
    felder = [feld for feld in elemente(seite(h)) if qml_typ(feld) == "PTextField" and feld.property("label") == "Firmenname" and sichtbar(feld)]
    assert len(felder) == 1
    feld = felder[0]
    feld.forceActiveFocus()
    pump(0.1)
    assert feld.hasActiveFocus()
    tippen(h, "Neu ")
    pump(0.8)  # Pause – länger als die Verzögerung, mit der Eingaben in den Eintrag übernommen werden
    assert feld.property("text") == "Neu ", "Das Feld wurde während der Eingabe umgeschrieben"
    tippen(h, "GmbH")
    pump(0.8)
    assert feld.property("text") == "Neu GmbH"
    assert item.overrides.company == "Neu GmbH"


def test_list_keyboard_navigation_like_before(ui_app, tmp_path: Path) -> None:
    """Tastatur in der Stapel-Liste wie in 2.6.1 (``BatchList``): ↑ ↓, Bild ↑/↓ (fünf Zeilen), Pos1,
    Ende, Leertaste wählt aus, Eingabe öffnet den Eintrag."""
    h = ui_app
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / f"liste_{i}.xlsx", aktiv=1)) for i in range(8)])
    geprueft(h)
    liste = listenansicht(h)
    liste.forceActiveFocus()
    pump(0.1)
    assert liste.hasActiveFocus() and liste.property("currentIndex") == 0  # erster Fokus: erste Zeile
    taste(h, Qt.Key.Key_Down)
    assert liste.property("currentIndex") == 1
    taste(h, Qt.Key.Key_Up)
    assert liste.property("currentIndex") == 0
    taste(h, Qt.Key.Key_Space)
    assert [item.selected for item in h.batch.items] == [True] + [False] * 7
    for key, expected in ((Qt.Key.Key_PageDown, 5), (Qt.Key.Key_End, 7), (Qt.Key.Key_PageUp, 2), (Qt.Key.Key_Home, 0)):
        taste(h, key)
        assert liste.property("currentIndex") == expected, (key, liste.property("currentIndex"))
    taste(h, Qt.Key.Key_Return)
    assert h.batch.detailId == h.batch.items[0].id


def test_row_menu_opens_the_pdf_only_for_created_entries(ui_app, tmp_path: Path) -> None:
    """Kontextmenü einer Zeile: »PDF öffnen« erst, wenn die PDF erstellt ist – bei »Bereit« gibt es
    noch keine PDF (der Eintrag wäre aktiv, täte aber nichts)."""
    h = ui_app
    h.customers.customers.create("Beispiel GmbH", "100", ["rechnung@kunde-a.de"])
    stapel(h, tmp_path / "out")
    h.batch.add([str(excel(tmp_path / "bekannt.xlsx"))])
    geprueft(h)
    aktualisiert(h)

    def pdf_oeffnen():
        """Zeile, Menü und Menüeintrag – alle drei festhalten: PySide verwirft die Python-Objekte der
        Kinder, sobald das des Elternobjekts freigegeben ist."""
        zeile = zeilen_elemente(h)["bekannt.xlsx"]
        menus = [obj for obj in zeile.findChildren(QObject) if qml_typ(obj) == "PMenu"]
        assert len(menus) == 1
        treffer = [obj for obj in menus[0].findChildren(QObject) if qml_typ(obj) == "PMenuItem" and obj.property("text") == "PDF öffnen"]
        assert len(treffer) == 1
        return zeile, menus[0], treffer[0]

    assert eintrag(h, "bekannt.xlsx").status.value == "ready"
    _zeile, _menu, menue = pdf_oeffnen()
    assert not menue.property("enabled")
    erstellen(h)
    aktualisiert(h)
    item = eintrag(h, "bekannt.xlsx")
    assert item.status.value == "success" and Path(item.output).is_file()
    _zeile, _menu, menue = pdf_oeffnen()
    assert menue.property("enabled")
    QMetaObject.invokeMethod(menue, "triggered")
    pump(0.1)
    from qtapp import files

    assert files.OPENED == [item.output]
