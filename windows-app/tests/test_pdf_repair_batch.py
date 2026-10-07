"""Mehrere PDFs reparieren – Dateiliste, Status, Ausgabenamen, Zusammenfassung (ohne Qt).

Geprüft wird ``tools.pdf_repair.batch``: Hinzufügen ohne Doppelte, Windows-Dateinamen,
Namensregel (Schalter »„repariert“ anhängen«, Zusatz), eigene Namen, eindeutige Namen bei
Konflikten (auch ohne Rücksicht auf Groß-/Kleinschreibung), Reservierung beim Start.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.pdf_repair import batch
from tools.pdf_repair.batch import BatchItem, ItemState, NameMode, Phase, RepairBatch
from tools.pdf_repair.models import Condition, PdfAnalysis, PdfRepairResult, RepairMode, RepairStatus


def pdf(path: Path, data: bytes = b"%PDF-1.4\n%%EOF\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def analysiert(item: BatchItem, condition: Condition, signatures: int = 0) -> BatchItem:
    item.analysis = PdfAnalysis(path=str(item.path), condition=condition, signatures=signatures)
    item.state = batch.analysis_state(item.analysis)
    return item


def namen(liste: RepairBatch) -> list[str]:
    return [item.planned.name for item in liste.items]


# --- Dateinamen ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "eingabe,erwartet",
    [("ETU_Pflegevertrag", "ETU_Pflegevertrag"), ("Kundenvertrag.pdf", "Kundenvertrag"), ("  Name.PDF  ", "Name"), ("a.pdf.pdf", "a"), ("Bericht 2026 – März", "Bericht 2026 – März")],
)
def test_pdf_extension_is_added_automatically(eingabe: str, erwartet: str) -> None:
    assert batch.strip_pdf(eingabe) == erwartet
    assert batch.name_error(erwartet) == ""
    assert batch.numbered(erwartet, 0) == f"{erwartet}.pdf"


@pytest.mark.parametrize("zeichen", list('<>:"/\\|?*') + ["\x01"])
def test_forbidden_characters_are_rejected(zeichen: str) -> None:
    fehler = batch.name_error(f"Rechnung{zeichen}2026")
    assert fehler.startswith("Nicht erlaubt in Dateinamen")


@pytest.mark.parametrize("name", ["CON", "con", "PRN", "AUX", "NUL", "COM1", "lpt9", "NUL.backup"])
def test_reserved_windows_names_are_rejected(name: str) -> None:
    assert "reservierter Name" in batch.name_error(name)


def test_empty_and_problematic_names_are_rejected() -> None:
    assert batch.name_error("") == "Bitte einen Dateinamen eingeben."
    assert batch.name_error(batch.strip_pdf(" .pdf ")) == "Bitte einen Dateinamen eingeben."
    assert "Punkt oder Leerzeichen" in batch.name_error("Bericht.")
    assert "zu lang" in batch.name_error("x" * (batch.MAX_BASE + 1))
    assert batch.name_error("CONSOLE") == ""  # nur der exakte Gerätename ist reserviert
    assert batch.suffix_error("") and batch.suffix_error("_gefixt") == "" and "Nicht erlaubt" in batch.suffix_error("_a/b")


def test_name_rule_with_and_without_switch() -> None:
    quelle = Path("C:/Daten/Rechnung.pdf")
    assert batch.auto_base(quelle, True) == "Rechnung_repariert"
    assert batch.auto_base(quelle, False) == "Rechnung"
    assert batch.auto_base(quelle, True, "_gefixt") == "Rechnung_gefixt"
    assert [batch.numbered("Dokument_repariert", n) for n in range(3)] == ["Dokument_repariert.pdf", "Dokument_repariert (1).pdf", "Dokument_repariert (2).pdf"]


# --- Liste --------------------------------------------------------------------------------------


def test_add_skips_duplicates_non_pdfs_and_missing_files(tmp_path: Path) -> None:
    a = pdf(tmp_path / "a.pdf")
    b = pdf(tmp_path / "Unterordner" / "b.pdf")
    (tmp_path / "notiz.txt").write_text("x")
    liste = RepairBatch()
    erstes = liste.add([a, b, tmp_path / "notiz.txt", tmp_path / "fehlt.pdf"])
    assert [item.name for item in erstes.added] == ["a.pdf", "b.pdf"]
    assert erstes.rejected == ["notiz.txt"] and erstes.missing == ["fehlt.pdf"]
    assert erstes.added[0].size == a.stat().st_size and erstes.added[0].state is ItemState.PENDING
    # Dieselbe Datei noch einmal – auch über einen anderen Pfad-Weg – wird nicht doppelt aufgenommen
    zweites = liste.add([a, tmp_path / "Unterordner" / ".." / "a.pdf", str(b)])
    assert zweites.added == [] and zweites.duplicates == ["a.pdf", "a.pdf", "b.pdf"]
    assert len(liste) == 2
    # Nach dem Entfernen darf sie wieder hinzu
    liste.remove(erstes.added[0].key)
    assert [item.name for item in liste.add([a]).added] == ["a.pdf"]


def test_analysis_queue_and_states(tmp_path: Path) -> None:
    liste = RepairBatch()
    items = liste.add([pdf(tmp_path / f"{n}.pdf") for n in "abcdef"]).added
    assert liste.next_to_analyze() is items[0]
    zustand = {
        Condition.HEALTHY: ItemState.READY,
        Condition.REPAIRABLE: ItemState.READY,
        Condition.DAMAGED: ItemState.READY,
        Condition.RAW_RECOVERABLE: ItemState.READY,
        Condition.ENCRYPTED: ItemState.ENCRYPTED,
        Condition.UNREADABLE: ItemState.UNREADABLE,
    }
    for item, (condition, state) in zip(items, zustand.items()):
        analysiert(item, condition)
        assert item.state is state
    assert liste.next_to_analyze() is None
    # »Alle reparieren«: nur beschädigte; gesunde nur einzeln (»Trotzdem neu aufbauen«)
    assert [item.name for item in liste.to_repair()] == ["b.pdf", "c.pdf", "d.pdf"]
    assert items[0].can_repair() and items[0].repair_mode() is RepairMode.REBUILD
    assert not items[4].can_repair() and not items[5].can_repair()  # verschlüsselt, unlesbar
    assert items[1].repair_mode() is RepairMode.AUTO
    # Ergebnis: gespeichert → repariert / teilweise; sonst fehlgeschlagen
    assert batch.result_state(PdfRepairResult(RepairStatus.REPAIRED, "x", "y"), True) is ItemState.REPAIRED
    assert batch.result_state(PdfRepairResult(RepairStatus.PARTIALLY_RECOVERED, "x", "y"), True) is ItemState.PARTIALLY_RECOVERED
    assert batch.result_state(PdfRepairResult(RepairStatus.REPAIRED, "x", "y"), False) is ItemState.FAILED
    assert batch.result_state(PdfRepairResult(RepairStatus.ENCRYPTED, "x"), False) is ItemState.ENCRYPTED
    items[1].state = ItemState.REPAIRED
    items[2].state = ItemState.FAILED
    assert [item.name for item in liste.to_repair()] == ["d.pdf"]
    assert [item.name for item in liste.failed()] == ["c.pdf"]
    assert liste.counts()[ItemState.READY] == 2


def test_progress_phases_follow_the_engine_stages() -> None:
    assert batch.phase_of("analyze", "streams") is Phase.ANALYSIS
    assert batch.phase_of("repair", "hash") is Phase.ANALYSIS
    assert batch.phase_of("repair", "rewrite") is Phase.REPAIR and batch.phase_of("repair", "raster") is Phase.REPAIR
    assert batch.phase_of("repair", "trim") is Phase.REPAIR and batch.phase_of("repair", "streams_rescue") is Phase.REPAIR
    assert batch.phase_of("repair", "validate") is Phase.VALIDATION
    assert batch.phase_of("repair", "finish") is Phase.DONE


def test_password_is_not_part_of_the_text_representation(tmp_path: Path) -> None:
    item = BatchItem(path=tmp_path / "geheim.pdf", password="Geheim-123")
    assert "Geheim-123" not in repr(item)


# --- Namensplanung ------------------------------------------------------------------------------


def planen(liste: RepairBatch, ordner: Path | None = None, anhaengen: bool = True, zusatz: str = "_repariert") -> list[str]:
    liste.plan(lambda item: ordner or item.path.parent, anhaengen, zusatz)
    return namen(liste)


def test_switch_on_keeps_the_existing_naming(tmp_path: Path) -> None:
    liste = RepairBatch()
    liste.add([pdf(tmp_path / "Rechnung.pdf")])
    assert planen(liste) == ["Rechnung_repariert.pdf"]
    pdf(tmp_path / "rechnung_REPARIERT.pdf")  # anders geschrieben, unter Windows derselbe Name
    assert planen(liste) == ["Rechnung_repariert (1).pdf"]
    pdf(tmp_path / "Rechnung_repariert (1).pdf")
    assert planen(liste) == ["Rechnung_repariert (2).pdf"]


def test_switch_off_never_hits_the_original(tmp_path: Path) -> None:
    liste = RepairBatch()
    liste.add([pdf(tmp_path / "Original.pdf")])
    assert planen(liste, anhaengen=False) == ["Original (1).pdf"]  # gleicher Ordner: nummeriert
    leer = tmp_path / "Ausgabe"
    leer.mkdir()
    assert planen(liste, ordner=leer, anhaengen=False) == ["Original.pdf"]  # anderer, leerer Ordner
    assert planen(liste, ordner=leer, anhaengen=True, zusatz="_gefixt") == ["Original_gefixt.pdf"]


def test_same_names_from_different_folders_get_unique_outputs(tmp_path: Path) -> None:
    liste = RepairBatch()
    liste.add([pdf(tmp_path / "A" / "Rechnung.pdf"), pdf(tmp_path / "B" / "Rechnung.pdf"), pdf(tmp_path / "C" / "rechnung.pdf")])
    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    assert planen(liste, ordner=ziel) == ["Rechnung_repariert.pdf", "Rechnung_repariert (1).pdf", "rechnung_repariert (2).pdf"]
    # Neben den Originalen: kein Konflikt
    assert planen(liste) == ["Rechnung_repariert.pdf", "Rechnung_repariert.pdf", "rechnung_repariert.pdf"]


def test_manual_names_stay_until_reset(tmp_path: Path) -> None:
    liste = RepairBatch()
    kaputt, zweite = liste.add([pdf(tmp_path / "kaputt.pdf"), pdf(tmp_path / "SWP_ETU_PL_B1_M.pdf")]).added
    kaputt.name_mode, kaputt.manual_base = NameMode.MANUAL, "Kundenvertrag"
    zweite.name_mode, zweite.manual_base = NameMode.MANUAL, "ETU_Pflegevertrag_repariert"
    assert planen(liste) == ["Kundenvertrag.pdf", "ETU_Pflegevertrag_repariert.pdf"]
    assert planen(liste, anhaengen=False) == ["Kundenvertrag.pdf", "ETU_Pflegevertrag_repariert.pdf"]  # Schalter ändert sie nicht
    kaputt.name_mode = NameMode.AUTO  # »Automatischen Namen wiederherstellen«
    assert planen(liste, anhaengen=False) == ["kaputt (1).pdf", "ETU_Pflegevertrag_repariert.pdf"]


def test_manual_name_colliding_with_another_file_is_numbered(tmp_path: Path) -> None:
    liste = RepairBatch()
    a, b = liste.add([pdf(tmp_path / "a.pdf"), pdf(tmp_path / "b.pdf")]).added
    b.name_mode, b.manual_base = NameMode.MANUAL, "a_repariert"
    assert planen(liste) == ["a_repariert.pdf", "a_repariert (1).pdf"]
    b.manual_base = "A"  # entspricht dem Original »a.pdf« (Groß-/Kleinschreibung egal)
    assert planen(liste) == ["a_repariert.pdf", "A (1).pdf"]


def test_saved_and_reserved_names_are_kept(tmp_path: Path) -> None:
    liste = RepairBatch()
    erste, zweite = liste.add([pdf(tmp_path / "X" / "Bericht.pdf"), pdf(tmp_path / "Y" / "Bericht.pdf")]).added
    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    liste.reserve([erste, zweite], lambda item: ziel, True, "_repariert")
    assert namen(liste) == ["Bericht_repariert.pdf", "Bericht_repariert (1).pdf"] and erste.reserved
    # Während des Durchlaufs ändert sich nichts an reservierten Namen, auch wenn die Regel wechselt
    liste.plan(lambda item: ziel, False, "_repariert")
    assert namen(liste) == ["Bericht_repariert.pdf", "Bericht_repariert (1).pdf"]
    assert liste.reserved_names(ziel, except_item=erste) == {"bericht_repariert (1).pdf"}
    # Eine dritte Datei plant um die reservierten Namen herum
    dritte = liste.add([pdf(tmp_path / "Z" / "Bericht.pdf")]).added[0]
    liste.plan(lambda item: ziel, True, "_repariert")
    assert dritte.planned.name == "Bericht_repariert (2).pdf"
    # Gespeichert: der Name gehört der Ausgabe
    erste.output = pdf(ziel / "Bericht_repariert.pdf")
    liste.release()
    liste.plan(lambda item: ziel, True, "_repariert")
    assert (zweite.planned.name, dritte.planned.name) == ("Bericht_repariert (1).pdf", "Bericht_repariert (2).pdf")


def test_ten_files_get_ten_distinct_names(tmp_path: Path) -> None:
    liste = RepairBatch()
    liste.add([pdf(tmp_path / f"Ordner{n}" / "Scan.pdf") for n in range(10)])
    ziel = tmp_path / "Ziel"
    ziel.mkdir()
    geplant = planen(liste, ordner=ziel)
    assert len({name.casefold() for name in geplant}) == 10
    assert geplant[0] == "Scan_repariert.pdf" and geplant[9] == "Scan_repariert (9).pdf"


# --- Gesamtstand und Zusammenfassung (Texte aus den Zuständen) ---------------------------------------


def test_overview_counts_states_not_texts(tmp_path: Path) -> None:
    from tools.pdf_repair import presentation

    liste = RepairBatch()
    items = liste.add([pdf(tmp_path / f"{n}.pdf") for n in range(8)]).added
    for item, condition in zip(items, [Condition.REPAIRABLE] * 4 + [Condition.DAMAGED, Condition.RAW_RECOVERABLE, Condition.ENCRYPTED, Condition.UNREADABLE]):
        analysiert(item, condition)
    assert presentation.batch_overview(liste) == ("8 PDFs · 6 reparierbar · 1 verschlüsselt · 1 nicht wiederherstellbar", "info")
    items[0].state = ItemState.ANALYZING
    text, art = presentation.batch_overview(liste)
    assert text.startswith("8 PDFs · 1 wird geprüft · 5 reparierbar") and art == "busy"
    # Zustandstext einer Datei: aus Zustand und Analyse, nie aus Texten
    assert presentation.item_state_text(items[1]) == ("Beschädigt · Reparatur möglich", "caution")
    items[7].rescue = True
    assert presentation.item_state_text(items[7]) == ("Nicht wiederherstellbar · Weitere Rettungsoption verfügbar", "critical")
    assert presentation.batch_overview(RepairBatch()) == ("", "neutral")


@pytest.mark.parametrize(
    "zustaende,nicht_gestartet,erwartet",
    [
        ([ItemState.REPAIRED] * 5, 0, ("success", "Reparatur abgeschlossen", ["5 erfolgreich repariert"])),
        (
            [ItemState.REPAIRED] * 5 + [ItemState.PARTIALLY_RECOVERED, ItemState.FAILED, ItemState.SKIPPED],
            0,
            ("warning", "Reparatur abgeschlossen", ["5 erfolgreich repariert", "1 teilweise wiederhergestellt", "1 fehlgeschlagen", "1 übersprungen"]),
        ),
        ([ItemState.FAILED, ItemState.FAILED], 0, ("error", "Reparatur abgeschlossen", ["2 fehlgeschlagen"])),
        ([ItemState.REPAIRED] * 3 + [ItemState.CANCELLED], 6, ("warning", "Reparatur abgebrochen", ["3 erfolgreich repariert", "1 abgebrochen", "6 nicht gestartet"])),
        ([ItemState.SKIPPED], 0, ("info", "Keine PDF repariert", ["1 übersprungen"])),
    ],
)
def test_run_summary(zustaende, nicht_gestartet, erwartet) -> None:
    from tools.pdf_repair import presentation

    assert presentation.run_summary(zustaende, nicht_gestartet) == erwartet


# --- Stapel mit echten Dateien ------------------------------------------------------------------------------------


def test_batch_with_mixed_results(tmp_path: Path) -> None:
    """Echte, unterschiedlich beschädigte PDFs wie bei »Alle reparieren«: jede Datei für sich (Analyse,
    Reparatur, Übernahme), gemischte Ergebnisse – repariert, teilweise wiederhergestellt, nicht
    reparierbar, fehlgeschlagen. Originale bleiben bitgleich, keine Ausgabe ersetzt eine vorhandene Datei."""
    import hashlib

    import pdfsamples as samples
    from tools.pdf_repair import engine, presentation, process

    folder = tmp_path / "Eingang"
    dateien = {
        "xref": samples.xref_offset(folder / "Rechnung.pdf"),
        "vorspann": samples.with_prefix(folder / "Anhang.pdf", samples.MAIL_HEADER),
        "strom": samples.flate_truncated(folder / "Strom.pdf"),
        "zufall": samples.garbage(folder / "Zufall.pdf"),
        "verschwindet": samples.trailer_removed(folder / "Weg.pdf"),
    }
    (folder / "Rechnung_repariert.pdf").write_bytes(b"vorhanden")

    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    vorher = {path: sha(path) for path in folder.iterdir()}
    liste = RepairBatch()
    items = dict(zip(dateien, liste.add(dateien.values()).added))
    for item in liste.items:
        item.analysis = engine.analyze(item.path)
        item.state = batch.analysis_state(item.analysis)
    assert items["zufall"].state is ItemState.UNREADABLE and not items["zufall"].can_repair()
    durchlauf = liste.to_repair()
    assert items["zufall"] not in durchlauf and len(durchlauf) == 4
    liste.reserve(durchlauf, lambda item: item.path.parent, True, batch.DEFAULT_SUFFIX)
    weg = items["verschwindet"].path
    weg.unlink()  # nach der Analyse verschwunden: nur ihre Reparatur scheitert
    for nummer, item in enumerate(durchlauf):
        arbeit = tmp_path / f"arbeit{nummer}"
        arbeit.mkdir()
        result = engine.repair(item.path, arbeit, None, item.repair_mode(), item.analysis.sha256)
        gespeichert = False
        if result.usable:
            ziel = item.planned.parent
            item.output = process.deliver(Path(result.output_path), item.path, ziel, item.planned_base, item.planned_number, liste.reserved_names(ziel, except_item=item))
            gespeichert = True
        item.result, item.state = result, batch.result_state(result, gespeichert)
        item.reserved = False
    zustaende = {key: item.state for key, item in items.items()}
    assert zustaende == {
        "xref": ItemState.REPAIRED,
        "vorspann": ItemState.REPAIRED,
        "strom": ItemState.PARTIALLY_RECOVERED,
        "zufall": ItemState.UNREADABLE,
        "verschwindet": ItemState.FAILED,
    }
    assert items["verschwindet"].output is None and "nicht mehr lesbar" in items["verschwindet"].result.error
    assert items["xref"].output.name == "Rechnung_repariert (1).pdf"  # die vorhandene Datei bleibt
    assert items["vorspann"].result.data_removed == len(samples.MAIL_HEADER)
    assert items["strom"].result.streams_rescued == 1 and items["strom"].result.incomplete_pages == [2]
    assert presentation.item_state_text(items["strom"]) == ("Teilweise wiederhergestellt", "caution")
    assert presentation.run_summary([item.state for item in durchlauf]) == (
        "warning",
        "Reparatur abgeschlossen",
        ["2 erfolgreich repariert", "1 teilweise wiederhergestellt", "1 fehlgeschlagen"],
    )
    # Originale und vorhandene Dateien unverändert (die verschwundene ausgenommen)
    assert {path: sha(path) for path in vorher if path != weg} == {path: wert for path, wert in vorher.items() if path != weg}
    assert (folder / "Rechnung_repariert.pdf").read_bytes() == b"vorhanden"
    neu = sorted(path.name for path in folder.iterdir() if path not in vorher)
    assert neu == ["Anhang_repariert.pdf", "Rechnung_repariert (1).pdf", "Strom_repariert.pdf"]
