"""Stapelverarbeitung (Version 2.5): Datenmodell, Voranalyse, Vorrang der Angaben und Verarbeitung.

Diese Tests brauchen keine Oberfläche. Sie prüfen die Schicht unter der Ansicht »Stapel«:
dieselbe Excel-Prüfung, Kundenerkennung und PDF-Engine wie im Einzelmodus, Fehler bleiben
beim Eintrag, nichts wird unbeabsichtigt überschrieben, ein Abbruch hinterlässt keine Reste.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

import appstate
from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText
from tools.contract_overview.batch import analyzer, processor, resolver
from tools.contract_overview.batch.models import BatchItem, BatchSettings, ConflictMode, CustomerMode, ItemStatus, Overrides, path_key
from tools.contract_overview.customers.models import TextBlock
from tools.contract_overview.customers.repository import FILE_NAME, CustomerStore
from tools.contract_overview.overview import ExcelAnalysis, contract_summary

pypdf = pytest.importorskip("pypdf")

SPALTEN = ["Vertrag-Nr.", "Beginnt am", "Abrechnungszyklus", "Netto [€]", "Zahlungsart", "Bemerkung", "Rechnungsempfänger Email", "Anwenderstatus"]


def liste(pfad: Path, mail: str = "rechnung@kunde-a.de", aktiv: int = 2, inaktiv: int = 0, fett: tuple[int, ...] = (), nummer: str | None = None, mails: tuple[str, ...] = ()) -> Path:
    """Excel wie die echten Listen: Verträge und Empfänger, auf Wunsch mit Kundennummer."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    spalten = SPALTEN + (["Kundennummer"] if nummer is not None else [])
    book = Workbook()
    sheet = book.active
    sheet.append(spalten)
    zeilen = []
    for index in range(aktiv + inaktiv):
        adresse = mails[index % len(mails)] if mails else mail
        zeile = [f"V-{index + 1:03d}", datetime(2020 + index % 5, 1, 1), "jährlich", 10.0 + index, "Sofort", f"Vertrag {index + 1}", adresse, "Aktiv" if index < aktiv else "Inaktiv"]
        if nummer is not None:
            zeile.append(nummer)
        zeilen.append(zeile)
        sheet.append(zeile)
    for index in fett:
        sheet[f"F{index + 2}"].font = Font(bold=True)
    book.save(pfad)
    return pfad


def defaults(**changes) -> resolver.Defaults:
    values = dict(
        dateiname=appstate.DEFAULT_DATEINAME,
        seitenformat="hoch",
        logo_breite=appstate.DEFAULT_LOGO_BREITE,
        titel=appstate.DEFAULT_TITEL,
        untertitel=appstate.DEFAULT_UNTERTITEL,
        header=RichText.plain("", HEADER_STYLE, HEADER_ALIGN),
        footer=appstate.default_footer_rich(),
        regeln=tuple(dict(r) for r in appstate.DEFAULT_REGELN),
        logo=str(appstate.DEFAULT_LOGO),
    )
    values.update(changes)
    return resolver.Defaults(**values)


def analysed(pfad: Path, **kwargs) -> BatchItem:
    item = BatchItem(str(pfad), **kwargs)
    item.analysis, item.stamp = analyzer.analyze_file(pfad)
    return item


class Templates:
    def __init__(self, *entries: dict) -> None:
        self.entries = {entry["name"]: entry for entry in entries}

    def __call__(self, name: str) -> dict | None:
        return self.entries.get(name)


def resolve(item: BatchItem, store: CustomerStore, settings: BatchSettings, templates: Templates | None = None, **default_changes) -> resolver.Resolution:
    return resolver.resolve(item, store, templates or Templates(), settings, defaults(**default_changes))


def job_for(item: BatchItem, res: resolver.Resolution, settings: BatchSettings, created: frozenset[str] = frozenset()) -> processor.Job:
    assert res.ready, res.issues
    return processor.Job(item.id, res.company or item.name, item.path, item.stamp, processor.identity_of(item.analysis), res.fields, res.folder, settings.conflict, created)


def pdf_text(pfad: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(str(pfad)).pages)


def run_sync(item_ids, prepare, run=processor.run_job):
    """Stapel ohne Oberfläche ablaufen lassen: jede Arbeit sofort, Ergebnisse der Reihe nach."""
    events: list[tuple] = []
    finished: dict = {}

    def submit(func, on_done, on_error):
        try:
            on_done(func())
        except BaseException as exc:  # noqa: BLE001
            on_error(exc, "")

    runner = processor.BatchRunner(
        list(item_ids),
        prepare,
        submit,
        on_start=lambda item_id, job: events.append(("start", item_id)),
        on_result=lambda result: events.append(("done", result)),
        on_finish=lambda summary, remaining: finished.update(summary=summary, remaining=remaining),
        run=run,
    )
    runner.start()
    return runner, events, finished


# --- Datenmodell ------------------------------------------------------------------------------


def test_contract_summary_uses_singular_and_omits_zero_inactive() -> None:
    assert contract_summary(5, 3) == "5 aktive Verträge · 3 inaktiv ausgeblendet"
    assert contract_summary(5, 0) == "5 aktive Verträge"
    assert contract_summary(1, 0) == "1 aktiver Vertrag"
    assert contract_summary(5, 3, short=True) == "5 aktive · 3 inaktiv ausgeblendet"
    assert contract_summary(1, 0, short=True) == "1 aktiver"


def test_path_key_detects_the_same_file(tmp_path: Path) -> None:
    pfad = tmp_path / "Liste.xlsx"
    assert path_key(pfad) == path_key(str(tmp_path / "." / "Liste.xlsx"))
    assert path_key(pfad) == path_key(tmp_path / "sub" / ".." / "Liste.xlsx")
    if os.name == "nt":
        assert path_key(pfad) == path_key(str(pfad).upper())


def test_items_and_settings_round_trip_without_contents(tmp_path: Path) -> None:
    item = BatchItem(str(tmp_path / "a.xlsx"), customer_mode=CustomerMode.MANUAL, customer_id="k1", overrides=Overrides(number="42", template=""))
    item.status, item.output = ItemStatus.SUCCESS, str(tmp_path / "a.pdf")
    item.analysis = ExcelAnalysis(ok=True, active=3, emails=("x@y.de",))
    data = item.to_dict()
    assert "analysis" not in data and data["overrides"] == {"number": "42", "template": ""}
    back = BatchItem.from_dict(data)
    assert back.path == item.path and back.customer_mode is CustomerMode.MANUAL and back.customer_id == "k1"
    assert back.overrides.number == "42" and back.overrides.template == "" and back.overrides.company is None
    assert back.status is ItemStatus.SUCCESS and back.output == item.output
    assert BatchItem.from_dict({"path": ""}) is None and BatchItem.from_dict("kaputt") is None
    settings = BatchSettings(target_dir=str(tmp_path), subfolders=True, conflict=ConflictMode.SKIP)
    assert BatchSettings.from_config(settings.to_config()) == settings
    assert BatchSettings.from_config({}, default_target="D").target_dir == "D" and BatchSettings.from_config({}).conflict is ConflictMode.NUMBER


# --- Voranalyse ---------------------------------------------------------------------------------


def test_analysis_matches_single_mode_and_caches_unchanged_files(tmp_path: Path) -> None:
    import engine

    pfad = liste(tmp_path / "a.xlsx", aktiv=5, inaktiv=3, fett=(1,))
    analysis, stamp = analyzer.analyze_file(pfad)
    assert analysis == ExcelAnalysis.from_result(engine.pruefe_excel(pfad))  # dieselbe Prüfung wie einzeln
    assert (analysis.active, analysis.inactive, analysis.emails, analysis.bold) == (5, 3, ("rechnung@kunde-a.de",), 1)
    cache = analyzer.AnalysisCache()
    calls = []
    original = analyzer.analyze_file

    def counting(path):
        calls.append(path)
        return original(path)

    analyzer.analyze_file, saved = counting, analyzer.analyze_file
    try:
        analyzer.analyze_cached(pfad, cache)
        analyzer.analyze_cached(pfad, cache)
        assert len(calls) == 1  # unverändert: aus dem Cache
        time.sleep(0.02)
        liste(pfad, aktiv=1)  # geändert: neu prüfen, nie die alte Analyse
        os.utime(pfad, ns=(stamp.mtime_ns + 5_000_000_000, stamp.mtime_ns + 5_000_000_000))
        neu, _stamp = analyzer.analyze_cached(pfad, cache)
        assert len(calls) == 2 and neu.active == 1
    finally:
        analyzer.analyze_file = saved


def test_missing_and_broken_files_are_reported_per_file(tmp_path: Path) -> None:
    fehlt, stamp = analyzer.analyze_file(tmp_path / "gibt-es-nicht.xlsx")
    assert not fehlt.ok and fehlt.error == analyzer.NOT_FOUND and stamp is None
    kaputt = tmp_path / "kaputt.xlsx"
    kaputt.write_bytes(b"PK\x03\x04 das ist keine Excel-Datei")
    broken, _ = analyzer.analyze_file(kaputt)
    assert not broken.ok and broken.error


def test_analyzer_checks_one_file_after_another_and_delivers_in_batches(tmp_path: Path) -> None:
    pfade = [liste(tmp_path / f"liste_{i:02d}.xlsx", mail=f"kunde{i}@beispiel.de") for i in range(20)]
    delivered: list[list] = []
    threads: list[threading.Thread] = []
    active = {"now": 0, "max": 0}
    original = analyzer.analyze_cached

    def watched(path, cache):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        try:
            return original(path, cache)
        finally:
            active["now"] -= 1

    def start(func):
        thread = threading.Thread(target=func)
        threads.append(thread)
        thread.start()

    queue = analyzer.Analyzer(analyzer.AnalysisCache(), start, lambda func, *args: func(*args), delivered.append, analyze=watched)
    queue.submit([(f"id{i}", str(p)) for i, p in enumerate(pfade[:10])])
    queue.submit([(f"id{i}", str(p)) for i, p in enumerate(pfade[10:], start=10)])  # während der Prüfung
    for thread in threads:
        thread.join(60)
    results = [entry for chunk in delivered for entry in chunk]
    assert [item_id for item_id, _a, _s in results] == [f"id{i}" for i in range(20)]
    assert all(analysis.ok and analysis.active == 2 for _i, analysis, _s in results)
    assert active["max"] == 1 and len(threads) == 1  # nie zwei Prüfungen gleichzeitig
    assert len(delivered) < 20  # gebündelt, nicht Zeile für Zeile
    assert not queue.busy()


# --- Kundenerkennung und Vorrang ----------------------------------------------------------------------


def test_known_unknown_and_conflicting_customers(tmp_path: Path) -> None:
    store = CustomerStore(tmp_path / FILE_NAME)
    a = store.create("Beispiel GmbH", "123456", ["rechnung@kunde-a.de"])
    store.create("Muster AG", "654321", ["buchhaltung@kunde-b.de"])
    settings = BatchSettings(target_dir=str(tmp_path / "out"))
    bekannt = resolve(analysed(liste(tmp_path / "a.xlsx")), store, settings)
    assert bekannt.ready and bekannt.customer.id == a.id and bekannt.customer_source == "erkannt"
    assert (bekannt.company, bekannt.number) == ("Beispiel GmbH", "123456") and bekannt.customer_line == "Kunde erkannt: Beispiel GmbH · 123456"
    unbekannt_item = analysed(liste(tmp_path / "c.xlsx", mail="info@unbekannt.de"))
    unbekannt = resolve(unbekannt_item, store, settings)
    assert resolver.status_for(unbekannt.issues) is ItemStatus.NEEDS_INPUT
    assert {i.code for i in unbekannt.issues} == {"company_missing", "number_missing"}
    assert unbekannt.company == "" and unbekannt.customer is None  # nichts aus der Adresse erraten
    unbekannt_item.overrides = Overrides(company="Neu GmbH", number="777")
    assert resolve(unbekannt_item, store, settings).ready
    konflikt = resolve(analysed(liste(tmp_path / "d.xlsx", mails=("rechnung@kunde-a.de", "buchhaltung@kunde-b.de"))), store, settings)
    assert konflikt.customer is None and "customer_conflict" in {i.code for i in konflikt.issues}
    assert resolver.status_for(konflikt.issues) is ItemStatus.NEEDS_INPUT  # nie automatisch entscheiden


def test_number_in_excel_that_contradicts_the_recognized_customer_blocks(tmp_path: Path) -> None:
    store = CustomerStore(tmp_path / FILE_NAME)
    store.create("Beispiel GmbH", "123456", ["rechnung@kunde-a.de"])
    item = analysed(liste(tmp_path / "a.xlsx", nummer="999"))
    res = resolve(item, store, BatchSettings(target_dir=str(tmp_path)))
    assert res.customer is None and "number_mismatch" in {i.code for i in res.issues}
    item.customer_mode = CustomerMode.NONE  # bewusst ohne Kundenakte: Nummer aus der Datei
    item.overrides.company = "Andere GmbH"
    res = resolve(item, store, BatchSettings(target_dir=str(tmp_path)))
    assert res.ready and res.number == "999"


def test_file_problems_fail_and_missing_values_need_input(tmp_path: Path) -> None:
    store = CustomerStore(tmp_path / FILE_NAME)
    settings = BatchSettings(target_dir=str(tmp_path))
    leer = analysed(liste(tmp_path / "leer.xlsx", aktiv=0, inaktiv=2))
    res = resolve(leer, store, settings)
    assert resolver.status_for(res.issues) is ItemStatus.FAILED and res.issues[0].code == "no_active"
    fehlt = BatchItem(str(tmp_path / "weg.xlsx"))
    assert resolve(fehlt, store, settings).issues[0].code == "file_missing"
    offen = BatchItem(str(liste(tmp_path / "offen.xlsx")))
    assert resolver.status_for(resolve(offen, store, settings).issues) is ItemStatus.PENDING
    mehrere = analysed(liste(tmp_path / "m.xlsx", mails=("a@x.de", "b@x.de")), overrides=Overrides(company="F", number="1"))
    res = resolve(mehrere, store, settings)
    assert [i.code for i in res.issues] == ["mail_choice"]
    mehrere.overrides.email = "b@x.de"
    assert resolve(mehrere, store, settings).ready


def test_template_priority_is_item_then_customer_then_batch(tmp_path: Path) -> None:
    store = CustomerStore(tmp_path / FILE_NAME)
    kunde = store.create("Beispiel GmbH", "123456", ["rechnung@kunde-a.de"], template="Kunde quer")
    templates = Templates(
        {"name": "Kunde quer", "format": "quer", "titel": "Titel Kunde"},
        {"name": "Stapel", "format": "hoch", "titel": "Titel Stapel", "dateiname": "Stapel_{kd}.pdf"},
        {"name": "Eintrag", "format": "hoch", "titel": "Titel Eintrag"},
    )
    settings = BatchSettings(target_dir=str(tmp_path), template="Stapel")
    item = analysed(liste(tmp_path / "a.xlsx"))
    res = resolve(item, store, settings, templates)
    assert (res.template, res.template_source, res.fields["seitenformat"], res.fields["titel"]) == ("Kunde quer", "Kundenakte", "quer", "Titel Kunde")
    item.overrides.template = "Eintrag"  # bewusst im Eintrag gesetzt: gewinnt
    res = resolve(item, store, settings, templates)
    assert (res.template_source, res.fields["titel"]) == ("Eintrag", "Titel Eintrag")
    item.overrides.template = None
    store.update(kunde.id, template="")
    res = resolve(item, store, settings, templates)
    assert (res.template, res.template_source, res.fields["dateiname"]) == ("Stapel", "Stapel", "Stapel_{kd}.pdf")
    item.overrides.template = ""  # bewusst keine Vorlage: globale Darstellung
    res = resolve(item, store, settings, templates)
    assert res.template == "" and res.fields["titel"] == appstate.DEFAULT_TITEL
    item.overrides.template = "Gelöscht"
    assert "template_missing" in {i.code for i in resolve(item, store, settings, templates).issues}


def test_logo_and_target_priority(tmp_path: Path) -> None:
    from PIL import Image

    logos = {}
    for name in ("eintrag", "kunde", "stapel"):
        logos[name] = tmp_path / f"{name}.png"
        Image.new("RGB", (40, 20), "red").save(logos[name])
    store = CustomerStore(tmp_path / FILE_NAME)
    kunde = store.create("Beispiel GmbH", "123456", ["rechnung@kunde-a.de"], logo=str(logos["kunde"]), target_dir=str(tmp_path / "kundenordner"))
    (tmp_path / "kundenordner").mkdir()
    settings = BatchSettings(target_dir=str(tmp_path / "ausgabe"), logo=str(logos["stapel"]))
    item = analysed(liste(tmp_path / "a.xlsx"))
    res = resolve(item, store, settings)
    assert (res.logo, res.logo_source) == (str(logos["kunde"]), "Kundenakte")
    assert (res.folder, res.folder_source) == (str(tmp_path / "kundenordner"), "Kundenakte")
    item.overrides.logo, item.overrides.target_dir = str(logos["eintrag"]), str(tmp_path / "eigen")
    res = resolve(item, store, settings)
    assert (res.logo_source, res.folder_source, res.folder) == ("Eintrag", "Eintrag", str(tmp_path / "eigen"))
    item.overrides = Overrides()
    store.update(kunde.id, logo=str(tmp_path / "weg.png"), target_dir="")
    res = resolve(item, store, settings)
    assert (res.logo, res.logo_source) == (str(logos["stapel"]), "Stapel") and "Gespeichertes Logo wurde nicht gefunden." in res.notes
    assert res.folder == str(tmp_path / "ausgabe")
    settings.logo = ""
    assert resolve(item, store, settings).logo == str(appstate.DEFAULT_LOGO)  # globales Standardlogo
    settings.subfolders = True
    assert resolve(item, store, settings).folder == str(tmp_path / "ausgabe" / "123456 Beispiel GmbH")
    settings.customer_target = False
    store.update(kunde.id, target_dir=str(tmp_path / "kundenordner"))
    assert resolve(item, store, settings).folder_source == "Stapel"
    assert resolver.subfolder_name("12/34", 'Müller: "Söhne"') == "12_34 Müller_ _Söhne_"


def test_texts_come_from_the_customer_and_never_lose_the_standard_footer(tmp_path: Path) -> None:
    store = CustomerStore(tmp_path / FILE_NAME)
    text = "Sonderkonditionen für {firma}"
    fett = FOOTER_STYLE.with_(bold=True, color="#B51F1F")
    eigene = RichText(text, [fett] * 17 + [FOOTER_STYLE] * (len(text) - 17), None, FOOTER_STYLE, FOOTER_ALIGN)
    a = store.create("Beispiel GmbH", "1", ["rechnung@kunde-a.de"], footer=TextBlock(eigene.text, eigene.to_dict()), header=TextBlock("Kopf A", None))
    store.create("Leer GmbH", "2", ["rechnung@kunde-b.de"], footer=TextBlock("", None))  # alter leerer Wert
    settings = BatchSettings(target_dir=str(tmp_path))
    res_a = resolve(analysed(liste(tmp_path / "a.xlsx")), store, settings)
    assert res_a.fields["fusszeile"] == eigene.text and res_a.fields["fusszeile_format"] == eigene.to_dict() and res_a.fields["kopfzeile"] == "Kopf A"
    res_b = resolve(analysed(liste(tmp_path / "b.xlsx", mail="rechnung@kunde-b.de")), store, settings)
    assert res_b.fields["fusszeile"] == appstate.DEFAULT_FOOTER  # nie eine leere Fußzeile
    assert a.id != res_b.customer.id


# --- Ausgabe und Verarbeitung ------------------------------------------------------------------------------------


def test_output_names_never_overwrite_unintentionally(tmp_path: Path) -> None:
    geplant = tmp_path / "Vertragsuebersicht_Kd1.pdf"
    assert processor.plan_output(geplant, ConflictMode.NUMBER) == (geplant, [], False)
    geplant.write_bytes(b"alt")
    ziel, hinweise, ersetzen = processor.plan_output(geplant, ConflictMode.NUMBER)
    assert ziel.name == "Vertragsuebersicht_Kd1_2.pdf" and hinweise and not ersetzen
    assert processor.plan_output(geplant, ConflictMode.SKIP)[0] is None
    assert processor.plan_output(geplant, ConflictMode.OVERWRITE)[0:3:2] == (geplant, True)
    # im selben Lauf erstellt: nie ersetzen, auch nicht mit »Überschreiben«
    ziel, _h, ersetzen = processor.plan_output(geplant, ConflictMode.OVERWRITE, frozenset({path_key(geplant)}))
    assert ziel.name == "Vertragsuebersicht_Kd1_2.pdf" and not ersetzen


def test_batch_creates_pdfs_with_the_single_mode_engine(tmp_path: Path) -> None:
    import engine

    store = CustomerStore(tmp_path / FILE_NAME)
    store.create("Beispiel GmbH", "123456", ["rechnung@kunde-a.de"], template="Quer")
    store.create("Muster AG", "654321", ["buchhaltung@kunde-b.de"])
    templates = Templates({"name": "Quer", "format": "quer"})
    settings = BatchSettings(target_dir=str(tmp_path / "out"))
    a = analysed(liste(tmp_path / "a.xlsx", fett=(0,)))
    b = analysed(liste(tmp_path / "b.xlsx", mail="buchhaltung@kunde-b.de", aktiv=3, fett=(2,)))
    items = {item.id: item for item in (a, b)}
    runner, _events, finished = run_sync(items, lambda item_id, created: job_for(items[item_id], resolve(items[item_id], store, settings, templates), settings, created))
    summary = finished["summary"]
    assert (summary.created, summary.failed, summary.skipped) == (2, 0, 0)
    pfad_a = tmp_path / "out" / "Vertragsuebersicht_Kd123456.pdf"
    pfad_b = tmp_path / "out" / "Vertragsuebersicht_Kd654321.pdf"
    assert pfad_a.is_file() and pfad_b.is_file()
    breite_a, hoehe_a = pypdf.PdfReader(str(pfad_a)).pages[0].mediabox.upper_right
    breite_b, hoehe_b = pypdf.PdfReader(str(pfad_b)).pages[0].mediabox.upper_right
    assert breite_a > hoehe_a and breite_b < hoehe_b  # gemischt: Kunde A quer, Kunde B hoch
    assert "Beispiel GmbH" in pdf_text(pfad_a) and "Muster AG" in pdf_text(pfad_b)
    assert appstate.DEFAULT_FOOTER.split("\n")[0][:40] in " ".join(pdf_text(pfad_b).split())
    # Dieselbe Engine: Einzel-PDF mit denselben Angaben ist inhaltlich gleich
    einzel = engine.erstelle_pdf(engine.PdfAuftrag(**resolve(b, store, settings, templates).fields, zielordner=tmp_path / "einzel"))
    assert pdf_text(einzel).replace(einzel.name, "") == pdf_text(pfad_b).replace(pfad_b.name, "")


def test_excel_bold_is_kept_per_file(tmp_path: Path) -> None:
    from test_excel_bold import pdf_zellen

    store = CustomerStore(tmp_path / FILE_NAME)
    settings = BatchSettings(target_dir=str(tmp_path / "out"))
    a = analysed(liste(tmp_path / "a.xlsx", fett=(0,)), overrides=Overrides(company="A", number="1"))
    b = analysed(liste(tmp_path / "b.xlsx", fett=(1,)), overrides=Overrides(company="B", number="2"))
    items = {item.id: item for item in (a, b)}
    run_sync(items, lambda item_id, created: job_for(items[item_id], resolve(items[item_id], store, settings), settings, created))
    zellen_a = pdf_zellen(tmp_path / "out" / "Vertragsuebersicht_Kd1.pdf")
    zellen_b = pdf_zellen(tmp_path / "out" / "Vertragsuebersicht_Kd2.pdf")
    assert zellen_a["Vertrag 1"] == {"Helvetica-Bold"} and zellen_a["Vertrag 2"] == {"Helvetica"}
    assert zellen_b["Vertrag 1"] == {"Helvetica"} and zellen_b["Vertrag 2"] == {"Helvetica-Bold"}


def test_one_failure_does_not_stop_the_batch(tmp_path: Path) -> None:
    store = CustomerStore(tmp_path / FILE_NAME)
    settings = BatchSettings(target_dir=str(tmp_path / "out"))
    items = {}
    for index in range(10):
        item = analysed(liste(tmp_path / f"liste_{index}.xlsx"), overrides=Overrides(company=f"Firma {index}", number=str(1000 + index)))
        items[item.id] = item
    order = list(items)
    kaputt = items[order[3]]
    logo = tmp_path / "kaputt.png"
    logo.write_bytes(b"kein Bild")  # Datei 4: Die Erstellung selbst schlägt fehl (Logo nicht lesbar)
    kaputt.overrides.logo = str(logo)
    runner, events, finished = run_sync(order, lambda item_id, created: job_for(items[item_id], resolve(items[item_id], store, settings), settings, created))
    results = {result.item_id: result for kind, result in events if kind == "done"}
    assert results[kaputt.id].status is ItemStatus.FAILED and results[kaputt.id].error
    assert all(results[item_id].status is ItemStatus.SUCCESS for item_id in order if item_id != kaputt.id)
    summary = finished["summary"]
    assert (summary.created, summary.failed) == (9, 1)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(f"Vertragsuebersicht_Kd{1000 + i}.pdf" for i in range(10) if i != 3)


def test_deleted_or_changed_files_are_handled_per_item(tmp_path: Path) -> None:
    store = CustomerStore(tmp_path / FILE_NAME)
    settings = BatchSettings(target_dir=str(tmp_path / "out"))
    weg = analysed(liste(tmp_path / "weg.xlsx"), overrides=Overrides(company="A", number="1"))
    geaendert = analysed(liste(tmp_path / "geaendert.xlsx"), overrides=Overrides(company="B", number="2"))
    items = {weg.id: weg, geaendert.id: geaendert}
    jobs = {item_id: job_for(item, resolve(item, store, settings), settings) for item_id, item in items.items()}
    Path(weg.path).unlink()
    liste(Path(geaendert.path), mail="anderer@kunde.de")  # anderer Empfänger: Zuordnung könnte sich ändern
    os.utime(geaendert.path, ns=(geaendert.stamp.mtime_ns + 7_000_000_000,) * 2)
    _r, events, finished = run_sync(list(items), lambda item_id, created: jobs[item_id])
    results = {result.item_id: result for kind, result in events if kind == "done"}
    assert results[weg.id].status is ItemStatus.FAILED and results[weg.id].error == "Datei nicht gefunden."
    assert results[geaendert.id].changed and results[geaendert.id].status is ItemStatus.NEEDS_INPUT
    assert results[geaendert.id].analysis.emails == ("anderer@kunde.de",)
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_cancel_keeps_finished_pdfs_and_leaves_no_partial_files(tmp_path: Path) -> None:
    store = CustomerStore(tmp_path / FILE_NAME)
    settings = BatchSettings(target_dir=str(tmp_path / "out"))
    items = {}
    for index in range(5):
        item = analysed(liste(tmp_path / f"l{index}.xlsx", aktiv=30), overrides=Overrides(company=f"F{index}", number=str(index + 1)))
        items[item.id] = item
    order = list(items)
    state = {"runner": None}

    def run(job, cancelled):
        result = processor.run_job(job, cancelled)
        if job.item_id == order[1]:
            state["runner"].cancel()  # nach der zweiten PDF abbrechen
        return result

    def submit(func, on_done, on_error):
        on_done(func())

    finished: dict = {}
    runner = processor.BatchRunner(order, lambda item_id, created: job_for(items[item_id], resolve(items[item_id], store, settings), settings, created), submit, lambda *_a: None, lambda _r: None, lambda summary, remaining: finished.update(summary=summary, remaining=remaining), run=run)
    state["runner"] = runner
    runner.start()
    summary = finished["summary"]
    assert summary.aborted and summary.created == 2 and summary.cancelled == 3 and finished["remaining"] == order[2:]
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert names == ["Vertragsuebersicht_Kd1.pdf", "Vertragsuebersicht_Kd2.pdf"]
    for name in names:
        assert len(pypdf.PdfReader(str(tmp_path / "out" / name)).pages) >= 1  # vollständig lesbar
    # Abbruch mitten in einer PDF: keine temporäre oder halbe Datei
    item = items[order[4]]
    calls = {"n": 0}

    def cancel_later() -> bool:
        calls["n"] += 1
        return calls["n"] > 3

    result = processor.run_job(job_for(item, resolve(item, store, settings), settings), cancel_later)
    assert result.cancelled and result.status is ItemStatus.READY
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == names


def test_retry_only_processes_failed_items(tmp_path: Path) -> None:
    store = CustomerStore(tmp_path / FILE_NAME)
    settings = BatchSettings(target_dir=str(tmp_path / "out"))
    ok = analysed(liste(tmp_path / "ok.xlsx"), overrides=Overrides(company="A", number="1"))
    bad = analysed(liste(tmp_path / "bad.xlsx"), overrides=Overrides(company="B", number="2"))
    logo = tmp_path / "logo.png"
    bad.overrides.logo = str(logo)  # Logo fehlt noch
    items = {ok.id: ok, bad.id: bad}
    prepare = lambda item_id, created: job_for(items[item_id], resolve(items[item_id], store, settings), settings, created) if resolve(items[item_id], store, settings).ready else None  # noqa: E731
    _r, events, finished = run_sync(list(items), prepare)
    assert finished["summary"].created == 1 and finished["summary"].skipped == 1
    from PIL import Image

    Image.new("RGB", (40, 20), "blue").save(logo)  # Fehler behoben
    _r, events, finished = run_sync([bad.id], prepare)
    assert finished["summary"].created == 1 and [r.item_id for k, r in events if k == "done"] == [bad.id]
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["Vertragsuebersicht_Kd1.pdf", "Vertragsuebersicht_Kd2.pdf"]


def test_log_contains_no_full_paths(tmp_path: Path) -> None:
    log = processor.BatchLog(tmp_path)
    geheim = str(tmp_path / "Kunden" / "Geheim GmbH" / "liste.xlsx")
    log.write([processor.redact(f"Fehler: Excel-Datei nicht gefunden: {geheim}", [geheim])])
    text = (tmp_path / processor.LOG_FILE).read_text(encoding="utf-8")
    assert "liste.xlsx" in text and "Geheim GmbH" not in text
