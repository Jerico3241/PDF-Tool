"""Kundenakte 2.0: Datenmodell, E-Mail-Wiedererkennung, Speicher und Übernahme der alten Historie."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from richtext import FOOTER_STYLE, HEADER_STYLE, CharStyle, RichText
from tools.contract_overview.customers import migration
from tools.contract_overview.customers.matching import MatchKind, is_valid_email, match_emails, normalize_email, split_emails
from tools.contract_overview.customers.models import SCHEMA_VERSION, Customer, TextBlock
from tools.contract_overview.customers.repository import FILE_NAME, ORDER_COMPANY, ORDER_NUMBER, ORDER_RECENT, CustomerStore, EmailConflict


def store_with(tmp_path: Path) -> CustomerStore:
    return CustomerStore(tmp_path / FILE_NAME)


# --- Normalisierung ------------------------------------------------------------------------


def test_email_normalization_is_conservative() -> None:
    assert normalize_email("  RECHNUNG@KUNDE.DE \t") == "rechnung@kunde.de"
    assert normalize_email("Max.Mustermann+rechnung@Kunde.de") == "max.mustermann+rechnung@kunde.de"  # Punkte und +Tags bleiben
    assert normalize_email("rechnung@straße.de") == "rechnung@straße.de"  # Domain wird nicht umgeschrieben
    assert normalize_email(None) == ""
    assert is_valid_email("rechnung@mueller.de")
    for invalid in ("", "rechnung", "rechnung@", "@kunde.de", "a b@kunde.de", "rechnung@kunde", "a@@kunde.de"):
        assert not is_valid_email(invalid), invalid
    assert split_emails("Rechnung@A.de; buchhaltung@a.de, <invoice@a.de>  kein-mail") == ["rechnung@a.de", "buchhaltung@a.de", "invoice@a.de"]


# --- Wiedererkennung -----------------------------------------------------------------------


def test_first_use_has_no_match_and_invents_nothing(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    result = store.match(["rechnung@kunde.de"])
    assert result.kind is MatchKind.NONE and result.unknown == ("rechnung@kunde.de",)
    assert len(store) == 0  # aus der Adresse entsteht keine Kundenakte, kein Firmenname


def test_recognition_is_case_and_whitespace_insensitive(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    kunde = store.create("Beispiel GmbH", "123456", ["rechnung@kunde.de"])
    for variant in ("rechnung@kunde.de", "RECHNUNG@KUNDE.DE", "  rechnung@kunde.de  "):
        result = store.match([variant])
        assert result.kind is MatchKind.SINGLE and result.customer_id == kunde.id, variant
    assert store.match(["neu@anderekunde.de"]).kind is MatchKind.NONE


def test_several_emails_of_one_customer_are_a_single_match(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    kunde = store.create("Firma", "1", ["rechnung@firma.de", "buchhaltung@firma.de", "invoice@firma.de"])
    result = store.match(["buchhaltung@firma.de", "INVOICE@firma.de", "neu@firma.de"])
    assert result.kind is MatchKind.SINGLE and result.customer_id == kunde.id
    assert result.unknown == ("neu@firma.de",)
    assert set(result.emails_of(kunde.id)) == {"buchhaltung@firma.de", "invoice@firma.de"}


def test_emails_of_different_customers_conflict(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    a = store.create("Kunde A", "1", ["rechnung@kunde-a.de"])
    b = store.create("Kunde B", "2", ["buchhaltung@kunde-b.de"])
    result = store.match(["rechnung@kunde-a.de", "buchhaltung@kunde-b.de"])
    assert result.kind is MatchKind.CONFLICT and result.customer_ids == (a.id, b.id)
    assert result.customer_id is None


def test_ambiguous_legacy_email_requires_a_choice() -> None:
    result = match_emails(["x@firma.de"], {"x@firma.de": ["a", "b"]})
    assert result.kind is MatchKind.AMBIGUOUS and result.customer_ids == ("a", "b")


# --- Kundenakten -----------------------------------------------------------------------------


def test_stable_id_survives_edits_and_restart(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    kunde = store.create("Müller & Söhne GmbH", "K-0815", ["rechnung@mueller.de"])
    assert len(kunde.id) == 36 and kunde.created_at
    store.update(kunde.id, company="Müller & Söhne KG", number="K-0816")
    assert store.save()
    again = CustomerStore.load(tmp_path / FILE_NAME)
    loaded = again.get(kunde.id)
    assert loaded is not None and loaded.company == "Müller & Söhne KG" and loaded.number == "K-0816"
    assert loaded.emails == ["rechnung@mueller.de"]
    data = json.loads((tmp_path / FILE_NAME).read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION == 2


def test_email_conflicts_need_a_decision(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    a = store.create("Kunde A", "1", ["rechnung@kunde.de"])
    b = store.create("Kunde B", "2")
    with pytest.raises(EmailConflict) as info:
        store.add_email(b.id, "RECHNUNG@kunde.de")
    assert [owner.id for owner in info.value.owners] == [a.id]
    assert store.owner_ids("rechnung@kunde.de") == [a.id]  # keine stille Doppelzuordnung
    with pytest.raises(EmailConflict):
        store.create("Kunde C", "3", ["rechnung@kunde.de"])
    assert store.add_email(b.id, "rechnung@kunde.de", move=True)
    assert store.owner_ids("rechnung@kunde.de") == [b.id] and store.get(a.id).emails == []
    assert not store.add_email(b.id, "rechnung@kunde.de")  # schon zugeordnet
    with pytest.raises(ValueError):
        store.add_email(b.id, "keine-adresse")


def test_removing_the_last_email_keeps_the_customer(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    kunde = store.create("Firma", "1", ["a@firma.de"])
    assert store.remove_email(kunde.id, "A@firma.de")
    assert store.get(kunde.id) is not None and store.get(kunde.id).emails == []
    assert store.match(["a@firma.de"]).kind is MatchKind.NONE


def test_delete_removes_mapping_but_no_files(tmp_path: Path) -> None:
    pdf = tmp_path / "Vertragsuebersicht_Kd1.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    store = store_with(tmp_path)
    kunde = store.create("Firma", "1", ["a@firma.de"])
    store.touch(kunde.id, excel=str(tmp_path / "liste.xlsx"), pdf=str(pdf))
    store.delete(kunde.id)
    assert store.match(["a@firma.de"]).kind is MatchKind.NONE and len(store) == 0
    assert pdf.read_bytes() == b"%PDF-1.4 test"


def test_duplicates_are_only_hints(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    a = store.create("Beispiel GmbH", "123456", ["rechnung@kunde.de"])
    b = store.create("beispiel  gmbh", "999")  # gleiche Firma, andere Nummer – erlaubt
    hints = store.duplicates(company="Beispiel GmbH", number="123456", emails=["RECHNUNG@kunde.de"], exclude=None)
    reasons = {customer.id: reasons for customer, reasons in hints}
    assert reasons[a.id] == ["number", "company", "email"] and reasons[b.id] == ["company"]
    assert store.duplicates(number="123456", exclude=a.id) == []


def test_search_and_order(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    mueller = store.create("Müller & Söhne GmbH", "10", ["rechnung@mueller.de"])
    zeta = store.create("Zeta AG", "9", ["buchhaltung@zeta.de"])
    alpha = store.create("alpha GmbH", "100")
    assert [c.id for c in store.search("müller")] == [mueller.id]
    assert [c.id for c in store.search("ZETA.de")] == [zeta.id]
    assert [c.id for c in store.search("10")] == [mueller.id, alpha.id]
    assert [c.id for c in store.search("söhne 10")] == [mueller.id]
    assert store.search("") == store.all()
    assert [c.id for c in store.ordered(ORDER_COMPANY)] == [alpha.id, mueller.id, zeta.id]
    assert [c.id for c in store.ordered(ORDER_NUMBER)] == [zeta.id, mueller.id, alpha.id]
    store.touch(zeta.id)
    assert store.ordered(ORDER_RECENT)[0].id == zeta.id


def test_merge_combines_without_losing_data(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    a = store.create("Beispiel GmbH", "123456", ["rechnung@kunde.de"])
    b = store.create("Beispiel GmbH", "123456", ["buchhaltung@kunde.de"])
    footer = TextBlock("Eigene Fußzeile", {"x": 1})
    store.update(b.id, template="Standard", template_auto=True, footer=footer, note="Aus B")
    store.touch(b.id, excel="C:/listen/b.xlsx", pdf="C:/pdf/b.pdf")
    merged = store.merge(a.id, b.id)
    assert merged.id == a.id and store.get(b.id) is None and len(store) == 1
    assert merged.emails == ["rechnung@kunde.de", "buchhaltung@kunde.de"]
    assert merged.template == "Standard" and merged.template_auto and merged.footer == footer
    assert merged.last_pdf == "C:/pdf/b.pdf" and merged.note == "Aus B"
    assert store.match(["buchhaltung@kunde.de"]).customer_id == a.id
    with pytest.raises(ValueError):
        store.merge(a.id, a.id)


def test_empty_footer_never_replaces_the_valid_one(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    kunde = store.create("Firma", "1", footer=TextBlock("   "))
    assert kunde.footer is None


def test_atomic_save_keeps_backup_and_survives_corruption(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    kunde = store.create("Firma", "1", ["a@firma.de"])
    assert store.save()
    store.update(kunde.id, company="Firma Neu")
    assert store.save()
    main = tmp_path / FILE_NAME
    backup = tmp_path / (FILE_NAME + ".bak")
    assert backup.is_file() and not list(tmp_path.glob(".kundenakten-*.tmp"))
    main.write_text("{ halb geschrieben", encoding="utf-8")
    recovered = CustomerStore.load(main)
    assert recovered.get(kunde.id) is not None and "Sicherung" in recovered.load_error
    assert list(tmp_path.glob("kundenakten.defekt-*.json"))  # beschädigte Datei aufbewahrt


def test_unicode_customer_roundtrip(tmp_path: Path) -> None:
    store = store_with(tmp_path)
    rich = RichText.plain("Grüße an Müller & Söhne", CharStyle(**{**FOOTER_STYLE.to_dict(), "bold": True}), "center")
    kunde = store.create("Müller & Söhne GmbH", "Ä-12", ["rechnung@mueller.de"], footer=TextBlock(rich.text, rich.to_dict()))
    assert store.save()
    loaded = CustomerStore.load(tmp_path / FILE_NAME).get(kunde.id)
    assert loaded.company == "Müller & Söhne GmbH" and loaded.number == "Ä-12"
    assert RichText.from_storage(loaded.footer.text, loaded.footer.format, FOOTER_STYLE, "center") == rich


# --- Übernahme der Kundenhistorie (bis 2.3) -----------------------------------------------------


LEGACY = [
    {
        "firmenname": "Beispiel GmbH",
        "kundennummer": "123456",
        "rechnungsempfaenger": "Rechnung@Kunde.de",
        "excel": "C:/Listen/beispiel.xlsx",
        "logo": "C:/Logos/beispiel.png",
        "fusszeile": "",
        "kopfzeile": "",
        "pdf": "C:/PDF/Vertragsuebersicht_Kd123456.pdf",
    },
    {
        "firmenname": "Müller & Söhne GmbH",
        "kundennummer": "0815",
        "rechnungsempfaenger": "buchhaltung@mueller.de",
        "excel": "",
        "logo": "",
        "fusszeile": "Eigene Fußzeile\nZeile 2",
        "fusszeile_format": None,
        "kopfzeile": "Kopf Müller",
        "pdf": "",
    },
    {"firmenname": "Ohne Mail AG", "kundennummer": "7", "rechnungsempfaenger": "Frau Schmidt", "fusszeile": "", "kopfzeile": ""},
]


def legacy_config(tmp_path: Path) -> tuple[dict, Path]:
    rich = RichText.plain("Eigene Fußzeile\nZeile 2", CharStyle(**{**FOOTER_STYLE.to_dict(), "italic": True}), "center")
    kunden = json.loads(json.dumps(LEGACY))
    kunden[1]["fusszeile_format"] = rich.to_dict()
    config = {"gesehen": "2.3.0", "kunden": kunden, "firmenname": "Beispiel GmbH"}
    path = tmp_path / "gui-config.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config, path


def test_legacy_history_is_migrated_once_with_backup(tmp_path: Path) -> None:
    config, path = legacy_config(tmp_path)
    before = path.read_bytes()
    store, report = migration.open_store(tmp_path, config, path)
    assert report is not None and report.ok and report.migrated == 3 and report.skipped == 0
    assert report.backup is not None and hashlib.sha256(report.backup.read_bytes()).digest() == hashlib.sha256(before).digest()
    assert path.read_bytes() == before  # die Konfiguration selbst bleibt unangetastet
    kunden = store.all()
    assert [k.label for k in kunden] == ["Beispiel GmbH · 123456", "Müller & Söhne GmbH · 0815", "Ohne Mail AG · 7"]
    beispiel, mueller, ohne = kunden
    assert beispiel.emails == ["rechnung@kunde.de"] and beispiel.last_excel == "C:/Listen/beispiel.xlsx"
    assert beispiel.last_pdf.endswith("Kd123456.pdf") and beispiel.logo == "C:/Logos/beispiel.png"
    assert beispiel.footer is None and beispiel.header is None  # leere Altwerte löschen nichts
    assert mueller.footer is not None and mueller.footer.text == "Eigene Fußzeile\nZeile 2"
    assert RichText.from_storage(mueller.footer.text, mueller.footer.format, FOOTER_STYLE, "center").style_at(0).italic
    assert mueller.header is not None and mueller.header.text == "Kopf Müller"
    assert ohne.emails == [] and "Frau Schmidt" in ohne.note
    assert store.match(["RECHNUNG@kunde.de"]).customer_id == beispiel.id
    # Zweiter Start: keine erneute Übernahme, dieselben IDs
    again, report2 = migration.open_store(tmp_path, config, path)
    assert report2 is None and [k.id for k in again.all()] == [k.id for k in kunden]


def test_history_after_a_downgrade_only_adds_what_is_missing(tmp_path: Path) -> None:
    config, path = legacy_config(tmp_path)
    store, _report = migration.open_store(tmp_path, config, path)
    beispiel, _mueller, ohne = store.all()
    store.delete(ohne.id)  # bewusst gelöscht – darf nicht zurückkehren
    assert store.save()
    # Zurück auf 2.3 und wieder auf 2.4: dort entstand eine neue Historie
    later = {
        "kunden": [
            {"firmenname": "Neu GmbH", "kundennummer": "900", "rechnungsempfaenger": "neu@neu.de"},
            {"firmenname": "beispiel  gmbh", "kundennummer": "123456", "rechnungsempfaenger": "zweite@kunde.de; buchhaltung@mueller.de"},
        ]
    }
    path.write_text(json.dumps(later), encoding="utf-8")
    store, report = migration.open_store(tmp_path, later, path)
    assert report is not None and report.ok and report.migrated == 1 and report.backup is not None
    labels = sorted(k.label for k in store.all())
    assert labels == ["Beispiel GmbH · 123456", "Müller & Söhne GmbH · 0815", "Neu GmbH · 900"]
    beispiel = store.get(beispiel.id)
    # neue Adresse ergänzt, fremde Zuordnung (Müller) unverändert
    assert beispiel.emails == ["rechnung@kunde.de", "zweite@kunde.de"]
    assert [k.company for k in store.owners("buchhaltung@mueller.de")] == ["Müller & Söhne GmbH"]
    # Ein weiterer Start mit derselben Historie legt nichts doppelt an
    again, report2 = migration.open_store(tmp_path, later, path)
    assert report2 is None and len(again) == 3


def test_failed_migration_keeps_the_old_history(tmp_path: Path, monkeypatch) -> None:
    config, path = legacy_config(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(CustomerStore, "save", lambda self: False)
    store, report = migration.open_store(tmp_path, config, path)
    assert report is not None and not report.ok and "konnte nicht" in report.error
    assert store.path is None and len(store) == 0
    assert path.read_bytes() == before and config["kunden"]
    assert not (tmp_path / FILE_NAME).exists()
    monkeypatch.undo()
    store, report = migration.open_store(tmp_path, config, path)  # nächster Start: neuer Versuch
    assert report is not None and report.ok and len(store) == 3


def test_customer_model_tolerates_damaged_entries() -> None:
    assert Customer.from_dict({"company": "ohne id"}) is None
    kunde = Customer.from_dict({"id": "x", "company": 5, "emails": ["A@b.de", "a@B.de", 7], "header": "kaputt", "template_auto": "ja"})
    assert kunde is not None and kunde.company == "" and kunde.emails == ["a@b.de"]
    assert kunde.header is None and kunde.template_auto is False
    assert HEADER_STYLE  # Import-Kontrolle
