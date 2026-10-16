"""Gekündigte und abgelaufene Verträge (Anwenderstatus) wahlweise mit in der Vertragsübersicht."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import appstate
import engine
from conftest import write_excel


@pytest.fixture
def status_excel(tmp_path: Path) -> Path:
    rows = [
        ["V-1001", datetime(2023, 1, 15), "monatlich", 49.9, "Lastschr", "SW-Pflege", "rechnung@muster.de", 10042, "Muster GmbH", "Aktiv"],
        ["V-1002", datetime(2022, 6, 1), "monatlich", 120.0, "Überweisung", "Hotline", "rechnung@muster.de", 10042, "Muster GmbH", "Gekündigt"],
        ["V-1003", datetime(2021, 3, 1), "jährlich", 300.0, "Sofort", "Altes Modul", "rechnung@muster.de", 10042, "Muster GmbH", " abgelaufen "],
        ["V-0999", datetime(2020, 1, 1), "jährlich", 10.0, "Sofort", "Entwurf", "rechnung@muster.de", 10042, "Muster GmbH", "Inaktiv"],
    ]
    return write_excel(tmp_path / "status.xlsx", rows)


def _pdf_text(path: Path) -> str:
    import pypdf

    return "\n".join(page.extract_text() for page in pypdf.PdfReader(str(path)).pages)


def test_without_the_option_only_active_contracts_appear(status_excel: Path, tmp_path: Path) -> None:
    result = engine.pruefe_excel(status_excel)
    assert (result["aktiv"], result["beendet"], result["inaktiv"]) == (1, 0, 3)
    assert [v.nummer for v in result["vertraege"]] == ["V-1001"]
    assert result["text"].startswith("1 aktiver Vertrag · 3 inaktiv ausgeblendet")
    text = _pdf_text(engine.erstelle_pdf(engine.PdfAuftrag(excel=status_excel, logo=appstate.DEFAULT_LOGO, kundennummer="10042", zielordner=tmp_path)))
    assert "V-1001" in text and "V-1002" not in text and "V-1003" not in text
    assert "Gekündigt" not in text and "Abgelaufen" not in text


def test_with_the_option_cancelled_and_expired_contracts_appear_with_their_status(status_excel: Path, tmp_path: Path) -> None:
    result = engine.pruefe_excel(status_excel, beendete=True)
    assert (result["aktiv"], result["beendet"], result["inaktiv"]) == (1, 2, 1)  # »Inaktiv« bleibt ausgeblendet
    assert {v.nummer: v.status for v in result["vertraege"]} == {"V-1001": "", "V-1002": "Gekündigt", "V-1003": "Abgelaufen"}
    assert result["text"].startswith("1 aktiver Vertrag · 2 gekündigt/abgelaufen · 1 inaktiv ausgeblendet")
    auftrag = engine.PdfAuftrag(excel=status_excel, logo=appstate.DEFAULT_LOGO, kundennummer="10042", zielordner=tmp_path, beendete=True)
    text = _pdf_text(engine.erstelle_pdf(auftrag))
    assert all(nummer in text for nummer in ("V-1001", "V-1002", "V-1003")) and "V-0999" not in text
    assert text.count("Gekündigt") == 1 and text.count("Abgelaufen") == 1  # Status-Hinweis nur bei den beendeten
    assert [v.status for v in auftrag.vertraege] == ["Abgelaufen", "Gekündigt", ""]  # nach Beginn sortiert wie bisher


def test_a_list_with_only_ended_contracts_needs_the_option(tmp_path: Path) -> None:
    rows = [["V-2001", datetime(2022, 1, 1), "monatlich", 20.0, "Sofort", "Hotline", "a@b.de", 1, "Firma", "Gekündigt"]]
    path = write_excel(tmp_path / "nur-gekuendigt.xlsx", rows)
    with pytest.raises(ValueError, match="keine aktiven Verträge"):
        engine.erstelle_pdf(engine.PdfAuftrag(excel=path, logo=appstate.DEFAULT_LOGO, kundennummer="1", zielordner=tmp_path))
    assert engine.erstelle_pdf(engine.PdfAuftrag(excel=path, logo=appstate.DEFAULT_LOGO, kundennummer="1", zielordner=tmp_path, beendete=True)).is_file()
    from tools.contract_overview.overview import ExcelAnalysis, excel_issues

    assert [issue.code for issue in excel_issues(str(path), ExcelAnalysis.from_result(engine.pruefe_excel(path)))] == ["no_active"]
    assert excel_issues(str(path), ExcelAnalysis.from_result(engine.pruefe_excel(path, beendete=True))) == []


def test_without_a_status_column_nothing_changes(tmp_path: Path) -> None:
    from conftest import COLUMNS

    columns = [c for c in COLUMNS if c != "Anwenderstatus"]
    rows = [["V-3001", datetime(2022, 1, 1), "monatlich", 20.0, "Sofort", "Hotline", "a@b.de", 1, "Firma"]]
    path = write_excel(tmp_path / "ohne-status.xlsx", rows, columns)
    for beendete in (False, True):
        result = engine.pruefe_excel(path, beendete=beendete)
        assert (result["aktiv"], result["beendet"], result["inaktiv"]) == (1, 0, 0)
        assert result["vertraege"][0].status == ""


def test_the_batch_follows_the_same_switch(status_excel: Path) -> None:
    from tools.contract_overview.batch.analyzer import AnalysisCache, analyze_cached

    cache = AnalysisCache()
    analysis, _stamp = analyze_cached(str(status_excel), cache)
    assert (analysis.active, analysis.ended) == (1, 0)
    cache.beendete = True
    cache.clear()
    analysis, _stamp = analyze_cached(str(status_excel), cache)
    assert (analysis.active, analysis.ended) == (1, 2)
