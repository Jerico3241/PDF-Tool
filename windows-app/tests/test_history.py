"""Vertragsvergleich: Normalisierung, Vergleich, Vertragsstände und ihre Ablage.

Die Excel-Listen entstehen programmatisch; verglichen wird nie der Inhalt einer PDF.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import appstate
from engine import PdfAuftrag, Vertragsdaten, erstelle_pdf, pruefe_excel
from tools.contract_overview.history import compare as comparing
from tools.contract_overview.history import report
from tools.contract_overview.history.models import (
    SCHEMA_VERSION,
    ChangeKind,
    ContractRecord,
    Snapshot,
    SnapshotSource,
    amount,
    content_hash,
    record_from,
    records_from,
)
from tools.contract_overview.history.repository import FOLDER, HistoryStore, file_sha256

pypdf = pytest.importorskip("pypdf")

SPALTEN = ["Vertrag-Nr.", "Beginnt am", "Abrechnungszyklus", "Netto [€]", "Zahlungsart", "Bemerkung", "Rechnungsempfänger Email", "Anwenderstatus"]
KUNDE_A = "6f1c1d2e-0000-4000-8000-00000000000a"
KUNDE_B = "6f1c1d2e-0000-4000-8000-00000000000b"
T0 = datetime(2026, 8, 12, 14, 3, tzinfo=timezone(timedelta(hours=2)))


def vertrag(nummer: str, text: str = "GetSolar", netto=250.0, zyklus: str = "monatlich", beginn: str | None = "2026-01-01", zahlung: str = "Überweisung") -> ContractRecord:
    return record_from(Vertragsdaten(nummer=nummer, bemerkung=text, beginn=beginn, zyklus=zyklus, netto=netto, zahlungsart=zahlung))


def stand(*records: ContractRecord, customer: str = KUNDE_A, when: datetime = T0) -> Snapshot:
    return Snapshot("id-" + str(len(records)), customer, when.isoformat(), tuple(records), content_hash(records))


def excel(pfad: Path, zeilen: list[list]) -> Path:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(SPALTEN)
    for zeile in zeilen:
        sheet.append(zeile)
    book.save(pfad)
    return pfad


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(tmp_path / FOLDER)


# --- Beispiel aus der Vorgabe --------------------------------------------------------------------------------


def test_example_from_the_specification() -> None:
    vorher = stand(vertrag("10001", "GetSolar", 250), vertrag("10002", "ECO-CAD", 180), vertrag("10003", "Hotline Basic", 120, beginn="2026-03-01"))
    aktuell = [vertrag("10001", "GetSolar", 270), vertrag("10003", "Hotline Basic", 120, beginn="2026-03-01"), vertrag("10004", "Hott-KI", 299, beginn="2026-09-01")]
    result = comparing.compare(vorher, aktuell)
    assert [c.contract_number for c in result.added] == ["10004"]
    assert [c.contract_number for c in result.removed] == ["10002"]
    assert [c.contract_number for c in result.changed] == ["10001"]
    assert [c.contract_number for c in result.unchanged] == ["10003"]
    (feld,) = result.changed[0].fields
    assert (feld.field, feld.old_value, feld.new_value) == ("net_amount", "250.00", "270.00")
    assert report.change_text(feld) == "Netto: 250,00 € → 270,00 €"
    assert result.counts() == {ChangeKind.ADDED: 1, ChangeKind.REMOVED: 1, ChangeKind.CHANGED: 1, ChangeKind.UNCHANGED: 1}
    text = report.comparison_text(result, "Muster GmbH")
    assert "Neu (1)\n  10004 Hott-KI" in text and "Entfernt (1)\n  10002 ECO-CAD" in text
    assert "10001 GetSolar\n    Netto: 250,00 € → 270,00 €" in text and "Unverändert: 1 Vertrag" in text


# --- 45–49: Kategorien und Normalisierung -------------------------------------------------------------------


def test_added_contract() -> None:
    result = comparing.compare(stand(vertrag("A"), vertrag("B")), [vertrag("A"), vertrag("B"), vertrag("C")])
    assert [(c.kind, c.key) for c in result.added] == [(ChangeKind.ADDED, "C")]
    assert not result.removed and not result.changed and len(result.unchanged) == 2


def test_removed_contract() -> None:
    result = comparing.compare(stand(vertrag("A"), vertrag("B"), vertrag("C")), [vertrag("A"), vertrag("C")])
    assert [(c.kind, c.key) for c in result.removed] == [(ChangeKind.REMOVED, "B")]
    assert result.removed[0].old is not None and result.removed[0].new is None


def test_changed_contract_names_the_exact_field() -> None:
    result = comparing.compare(stand(vertrag("A", netto=250)), [vertrag("A", netto=270)])
    (change,) = result.changed
    assert change.kind is ChangeKind.CHANGED and [(f.field, f.old_value, f.new_value) for f in change.fields] == [("net_amount", "250.00", "270.00")]


def test_several_changed_fields_are_all_listed() -> None:
    result = comparing.compare(stand(vertrag("A", netto=250, zyklus="monatlich", zahlung="Überweisung")), [vertrag("A", netto=270, zyklus="jährlich", zahlung="Lastschr")])
    fields = {f.field: (f.old_value, f.new_value) for f in result.changed[0].fields}
    assert fields == {"net_amount": ("250.00", "270.00"), "billing_cycle": ("monatlich", "jährlich"), "payment_method": ("Überweisung", "Lastschrift")}
    texts = [report.change_text(f) for f in result.changed[0].fields]
    assert texts == ["Abrechnungszyklus: monatlich → jährlich", "Netto: 250,00 € → 270,00 €", "Zahlungsart: Überweisung → Lastschrift"]


def test_normalization_differences_are_no_change() -> None:
    import pandas as pd

    old = record_from(Vertragsdaten("10001", " GetSolar\r\n", "2026-01-01", "", " monatlich ", 250, "Überweisung"))
    new = [
        record_from(Vertragsdaten("10001", "GetSolar", "2026-01-01", "01.01.2026", "monatlich", "250,00 €", "Überweisung ")),
        record_from(Vertragsdaten("10001", "GetSolar", pd.Timestamp("2026-01-01 00:00").strftime("%Y-%m-%d"), "", "monatlich", 250.0, "Überweisung")),
        record_from(Vertragsdaten("10001", "GetSolar", "2026-01-01", "", "monatlich", "250.00", "Überweisung")),
    ]
    for record in new:
        result = comparing.compare(stand(old), [record])
        assert not result.has_changes and len(result.unchanged) == 1, record
    assert amount(0.1 + 0.2) == Decimal("0.30") and amount("1.234,50 €") == Decimal("1234.50") and amount("kein Betrag") is None


def test_contract_numbers_stay_text() -> None:
    record = vertrag("001234")
    assert record.contract_number == "001234"
    result = comparing.compare(stand(vertrag("1234")), [record])
    assert [c.key for c in result.added] == ["001234"] and [c.key for c in result.removed] == ["1234"]


def test_renumbered_contract_is_removed_and_added_never_merged() -> None:
    result = comparing.compare(stand(vertrag("10001", "GetSolar")), [vertrag("10009", "GetSolar")])
    assert [c.key for c in result.removed] == ["10001"] and [c.key for c in result.added] == ["10009"] and not result.changed


def test_duplicate_numbers_are_compared_per_occurrence() -> None:
    result = comparing.compare(stand(vertrag("7", netto=10), vertrag("7", netto=20)), [vertrag("7", netto=10), vertrag("7", netto=25), vertrag("7", netto=30)])
    assert [c.key for c in result.unchanged] == ["7"] and [c.key for c in result.changed] == ["7#2"] and [c.key for c in result.added] == ["7#3"]


def test_formatting_is_not_compared_but_pdf_values_are() -> None:
    # Regeln wirken wie in der PDF: »Hott-KI« wird jährlich abgerechnet
    raw = Vertragsdaten("5", "x SW-Pflege Hott-KI Modul", "2026-09-01", "", "monatlich", 299, "Lastschr")
    record = record_from(raw, [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}])
    assert (record.description, record.billing_cycle, record.payment_method, record.contract_type) == ("Hott-KI Modul", "jährlich", "Lastschrift", "Softwarepflegevertrag")
    assert record.raw["zyklus"] == "monatlich" and record.raw["bemerkung"] == "x SW-Pflege Hott-KI Modul"
    hotline = record_from(Vertragsdaten("6", "Hotline Basic"))
    assert hotline.contract_type == "Supportvertrag" and hotline.billing_cycle == "–" and hotline.net_amount is None


def test_comparison_of_large_lists_is_instant() -> None:
    old = [vertrag(str(100000 + i), f"Modul {i}", netto=i) for i in range(5000)]
    new = [vertrag(str(100000 + i), f"Modul {i}", netto=i + (1 if i % 10 == 0 else 0)) for i in range(250, 5250)]
    snapshot = stand(*old)
    start = time.perf_counter()
    result = comparing.compare(snapshot, new)
    assert time.perf_counter() - start < 0.5
    assert (len(result.added), len(result.removed), len(result.changed)) == (250, 250, 475)


# --- Hash ---------------------------------------------------------------------------------------------------------


def test_hash_depends_only_on_contract_data() -> None:
    a = [vertrag("1", netto=10), vertrag("2", netto=20)]
    same = [vertrag("2", netto=20.0), vertrag("1", netto="10,00")]
    assert content_hash(a) == content_hash(same)  # Reihenfolge und Darstellung egal
    other_row = [record_from(Vertragsdaten("1", "GetSolar", "2026-01-01", "", "monatlich", 10, "Überweisung", zeile=99)), vertrag("2", netto=20)]
    assert content_hash(other_row) == content_hash(a)  # Excel-Zeile ist keine Vertragsangabe
    assert content_hash([vertrag("1", netto=11), vertrag("2", netto=20)]) != content_hash(a)


# --- Ablage ----------------------------------------------------------------------------------------------------------


def test_snapshot_round_trip_with_schema_version(store: HistoryStore, tmp_path: Path) -> None:
    source = SnapshotSource(str(tmp_path / "liste.xlsx"), "abc", str(tmp_path / "Vertragsuebersicht.pdf"))
    snapshot, created = store.record(KUNDE_A, [vertrag("001"), vertrag("002", netto=19.99)], source, "Muster GmbH · 10042", now=T0)
    assert created
    (datei,) = list((tmp_path / FOLDER / KUNDE_A).glob("*.json"))
    data = json.loads(datei.read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION == 1 and data["customer_id"] == KUNDE_A
    assert data["created_at"] == "2026-08-12T14:03:00+02:00"
    assert data["contracts"][1]["effective"]["net_amount"] == "19.99" and data["contracts"][0]["contract_number"] == "001"
    assert data["source"] == {"excel_path": source.excel_path, "excel_sha256": "abc", "pdf_path": source.pdf_path}
    loaded = store.latest(KUNDE_A)
    assert loaded == snapshot and loaded.contracts[1].net_amount == "19.99"


def test_identical_export_creates_no_second_snapshot(store: HistoryStore, tmp_path: Path) -> None:
    contracts = [vertrag("1"), vertrag("2")]
    first, created = store.record(KUNDE_A, contracts, SnapshotSource(pdf_path="a.pdf"), now=T0)
    again, created_again = store.record(KUNDE_A, [vertrag("2"), vertrag("1")], SnapshotSource(pdf_path="b.pdf"), now=T0 + timedelta(hours=1))
    assert created and not created_again and again.id == first.id
    assert store.count(KUNDE_A) == 1 and again.export_count == 2 and again.source.pdf_path == "b.pdf"
    assert again.created_at == first.created_at and again.exported > first.exported
    changed, created_changed = store.record(KUNDE_A, [vertrag("1"), vertrag("2", netto=1)], SnapshotSource(), now=T0 + timedelta(days=1))
    assert created_changed and store.count(KUNDE_A) == 2 and store.latest(KUNDE_A).id == changed.id
    # Rückkehr zu einem älteren Stand ist ein neuer Stand (nur der unmittelbar letzte zählt)
    assert store.record(KUNDE_A, contracts, SnapshotSource(), now=T0 + timedelta(days=2))[1]
    assert [s.created for s in store.snapshots(KUNDE_A)] == sorted((s.created for s in store.snapshots(KUNDE_A)), reverse=True)


def test_customers_are_never_mixed(store: HistoryStore, tmp_path: Path) -> None:
    store.record(KUNDE_A, [vertrag("10001", netto=250)], SnapshotSource(), now=T0)
    store.record(KUNDE_B, [vertrag("10001", netto=999)], SnapshotSource(), now=T0 + timedelta(minutes=5))
    assert [s.customer_id for s in store.snapshots(KUNDE_A)] == [KUNDE_A]
    assert store.latest(KUNDE_A).contracts[0].net_amount == "250.00"
    result = comparing.compare(store.latest(KUNDE_A), [vertrag("10001", netto=250)])
    assert not result.has_changes  # nie mit dem Stand von Kunde B verglichen
    # Eine fremde Datei im Ordner eines Kunden wird ignoriert
    fremd = store.latest(KUNDE_B).to_dict()
    (tmp_path / FOLDER / KUNDE_A / "20990101T000000000000-fremd.json").write_text(json.dumps(fremd), encoding="utf-8")
    assert [s.customer_id for s in store.snapshots(KUNDE_A)] == [KUNDE_A]
    # Ohne Kundenakte (oder mit ungültiger ID) wird nichts gespeichert
    for invalid in ("", None, "../x", "a/b"):
        with pytest.raises(ValueError):
            store.record(invalid, [vertrag("1")], SnapshotSource())


def test_comparison_works_after_old_files_were_deleted(store: HistoryStore, tmp_path: Path) -> None:
    liste = tmp_path / "alt.xlsx"
    pdf = tmp_path / "alt.pdf"
    liste.write_bytes(b"x")
    pdf.write_bytes(b"%PDF")
    store.record(KUNDE_A, [vertrag("1", netto=10), vertrag("2")], SnapshotSource(str(liste), file_sha256(liste), str(pdf)), now=T0)
    liste.unlink()
    pdf.unlink()
    result = comparing.compare(store.latest(KUNDE_A), [vertrag("1", netto=12)])
    assert [c.key for c in result.changed] == ["1"] and [c.key for c in result.removed] == ["2"]
    assert len(store.latest(KUNDE_A).source.excel_sha256) == 64  # Prüfsumme der Excel von damals bleibt gespeichert


def test_broken_and_newer_files_are_skipped_not_deleted(store: HistoryStore, tmp_path: Path) -> None:
    store.record(KUNDE_A, [vertrag("1")], SnapshotSource(), now=T0)
    folder = tmp_path / FOLDER / KUNDE_A
    kaputt = folder / "20260901T000000000000-kaputt.json"
    kaputt.write_text('{"schema_version": 1, "contracts": [', encoding="utf-8")
    neuer = folder / "20260902T000000000000-neuer.json"
    neuer.write_text(json.dumps({**store.latest(KUNDE_A).to_dict(), "schema_version": 99}), encoding="utf-8")
    assert store.count(KUNDE_A) == 1 and kaputt.exists() and neuer.exists()
    assert set(store.skipped) == {kaputt.name, neuer.name}


def test_writing_is_atomic(store: HistoryStore, tmp_path: Path, monkeypatch) -> None:
    store.record(KUNDE_A, [vertrag("1")], SnapshotSource(pdf_path="a.pdf"), now=T0)
    (datei,) = list((tmp_path / FOLDER / KUNDE_A).glob("*.json"))
    before = datei.read_bytes()

    def crash(*_args, **_kwargs):
        raise OSError("Datenträger voll")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError):
        store.record(KUNDE_A, [vertrag("1")], SnapshotSource(pdf_path="b.pdf"), now=T0 + timedelta(hours=1))
    assert datei.read_bytes() == before  # der gespeicherte Stand bleibt vollständig
    assert [p.name for p in (tmp_path / FOLDER / KUNDE_A).iterdir()] == [datei.name]  # keine Reste


def test_only_the_newest_snapshots_are_kept(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / FOLDER, limit=3)
    for index in range(5):
        store.record(KUNDE_A, [vertrag("1", netto=index)], SnapshotSource(), now=T0 + timedelta(days=index))
    assert [s.contracts[0].net_amount for s in store.snapshots(KUNDE_A)] == ["4.00", "3.00", "2.00"]


def test_merged_customers_keep_both_histories(store: HistoryStore, tmp_path: Path) -> None:
    store.record(KUNDE_A, [vertrag("1")], SnapshotSource(), now=T0)
    store.record(KUNDE_B, [vertrag("2")], SnapshotSource(), now=T0 + timedelta(days=1))
    assert store.merge(KUNDE_A, KUNDE_B) == 1
    assert [s.customer_id for s in store.snapshots(KUNDE_A)] == [KUNDE_A, KUNDE_A]
    assert store.latest(KUNDE_A).contracts[0].contract_number == "2" and store.count(KUNDE_B) == 0
    assert not (tmp_path / FOLDER / KUNDE_B).exists()


def test_reading_never_creates_history(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / FOLDER)
    assert store.snapshots(KUNDE_A) == [] and store.latest(KUNDE_A) is None
    assert not (tmp_path / FOLDER).exists()  # Migration: keine künstlichen Stände
    assert comparing.compare(None, [vertrag("1")]).has_baseline is False
    assert report.comparison_text(comparing.compare(None, [vertrag("1")])) == "Vertragsänderungen\nNoch kein früherer Vertragsstand vorhanden.\n"


# --- Engine: dieselben Werte wie in der PDF --------------------------------------------------------------------------


def test_snapshot_values_are_those_of_the_pdf(tmp_path: Path) -> None:
    liste = excel(
        tmp_path / "liste.xlsx",
        [
            ["001234", datetime(2026, 1, 1), "monatlich", 250, "Überweisung", "x SW-Pflege GetSolar", "a@b.de", "Aktiv"],
            [10003, datetime(2026, 3, 1), "jährlich", "120,00 €", "Lastschr", "Hotline Basic", "a@b.de", "Aktiv"],
            [10004, datetime(2026, 9, 1), "monatlich", 299.0, "Sofort", "Hott-KI", "a@b.de", "Aktiv"],
            [10005, datetime(2026, 9, 1), "monatlich", 1, "Sofort", "alt", "a@b.de", "Inaktiv"],
        ],
    )
    regeln = [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}]
    auftrag = PdfAuftrag(excel=liste, logo=appstate.DEFAULT_LOGO, kundennummer="42", zielordner=tmp_path, regeln=regeln)
    pdf = erstelle_pdf(auftrag)
    records = records_from(auftrag.vertraege, regeln)
    assert [r.contract_number for r in records] == ["001234", "10003", "10004"]  # nur aktive, nach Beginn sortiert
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in pypdf.PdfReader(str(pdf)).pages)
    for record in records:
        for value in (record.contract_number, record.description, record.billing_cycle, record.net_text, record.payment_method):
            assert value in text, value
    assert [r.net_amount for r in records] == ["250.00", "120.00", "299.00"]
    assert records[2].billing_cycle == "jährlich" and records[1].contract_type == "Supportvertrag"
    # Die Excel-Prüfung liefert dieselben Rohwerte (Grundlage des Vergleichs vor dem Export)
    geprueft = pruefe_excel(liste, regeln)
    assert records_from(geprueft["vertraege"], regeln) == records
    assert content_hash(records_from(geprueft["vertraege"], regeln)) == content_hash(records)


def test_failed_or_cancelled_export_yields_no_contracts(tmp_path: Path) -> None:
    liste = excel(tmp_path / "liste.xlsx", [[1, datetime(2026, 1, 1), "monatlich", 1, "Sofort", "A", "a@b.de", "Aktiv"]])
    from engine import Abgebrochen

    auftrag = PdfAuftrag(excel=liste, logo=appstate.DEFAULT_LOGO, kundennummer="42", zielordner=tmp_path, abbrechen=lambda: True)
    with pytest.raises(Abgebrochen):
        erstelle_pdf(auftrag)
    assert auftrag.vertraege == ()
    kaputt = PdfAuftrag(excel=liste, logo=tmp_path / "fehlt.png", kundennummer="42", zielordner=tmp_path)
    with pytest.raises(FileNotFoundError):
        erstelle_pdf(kaputt)
    assert kaputt.vertraege == ()
