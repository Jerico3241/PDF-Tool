"""Blitzvorschau (Strg+E, seit 5.0 Beta 5): Muster aus Beispielen – ohne LibreOffice prüfbar."""

from __future__ import annotations

import pytest

from qtapp.sheet.flashfill import NoPattern, flash_fill, learn


def test_first_name_with_header_row() -> None:
    rows = [["Name", "Vorname"], ["Max Müller", "Max"], ["Anna Maria Schmidt", ""], ["Jo Weber", ""], ["", ""]]
    assert flash_fill(rows, 1) == [None, None, "Anna", "Jo", None]


def test_initial_and_last_name_and_reordering() -> None:
    assert flash_fill([["Max Müller", "M. Müller"], ["Anna Maria Schmidt", ""]], 1) == [None, "A. Schmidt"]
    assert flash_fill([["Müller, Max", "Max Müller"], ["Schmidt, Anna", ""]], 1) == [None, "Anna Schmidt"]


def test_case_digits_and_email_domain() -> None:
    assert flash_fill([["köln", "KÖLN"], ["bonn", ""]], 1) == [None, "BONN"]
    assert flash_fill([["+49 (221) 123-45", "4922112345"], ["0228 / 99 88", ""]], 1) == [None, "02289988"]
    assert flash_fill([["max.mueller@firma.de", "firma"], ["jo@x.org", ""]], 1) == [None, "x"]


def test_two_source_columns() -> None:
    rows = [["Max", "Müller", "Max Müller"], ["Anna", "Schmidt", ""]]
    assert flash_fill(rows, 2) == [None, "Anna Schmidt"]


def test_no_pattern() -> None:
    with pytest.raises(NoPattern):
        flash_fill([["a", "xyz"], ["b", ""]], 1)
    with pytest.raises(NoPattern):
        flash_fill([["a", ""], ["b", ""]], 1)
    with pytest.raises(NoPattern):
        learn([(["x"], "y" * 300)], [0])
