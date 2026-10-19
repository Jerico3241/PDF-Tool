"""Vergleichen zweier Fassungen (4.0): Wörter mit Lage, Unterschiede, Zusammenfassung."""

from __future__ import annotations

from pathlib import Path

import editorsamples as samples
from qtapp.reader.session import Session
from tools.pdf_editor import compare
from tools.pdf_editor.compare import Word


def words(page: int, text: str, y: float = 100.0) -> list[Word]:
    result, x = [], 72.0
    for part in text.split():
        result.append(Word(page, part, (x, y, x + 6 * len(part), y + 12)))
        x += 6 * len(part) + 4
    return result


def test_words_split_at_spaces_and_line_breaks() -> None:
    chars = [(c, (10.0 + 6 * i, 100.0, 16.0 + 6 * i, 112.0)) for i, c in enumerate("Ab cd")]
    chars += [(c, (10.0 + 6 * i, 130.0, 16.0 + 6 * i, 142.0)) for i, c in enumerate("ef")]  # nächste Zeile ohne Leerzeichen
    found = compare.words_from_chars(3, chars)
    assert [word.text for word in found] == ["Ab", "cd", "ef"]
    assert all(word.page == 3 for word in found)
    assert found[0].rect == (10.0, 100.0, 22.0, 112.0)


def test_changed_added_and_removed_words_with_places_in_both_versions() -> None:
    old = words(0, "Die Miete beträgt 800 Euro im Monat.") + words(1, "Kündigung mit drei Monaten Frist.")
    new = words(0, "Die Miete beträgt 850 Euro im Monat zuzüglich Nebenkosten.") + words(1, "Kündigung mit Frist.")
    result = compare.compare(old, new)
    kinds = [(change.kind, change.before, change.after) for change in result.changes]
    assert kinds == [("changed", "800", "850"), ("changed", "Monat.", "Monat zuzüglich Nebenkosten."), ("removed", "drei Monaten", "")]
    first = result.changes[0]
    assert list(first.old) == [0] and list(first.new) == [0] and first.old_at[0] == 0 and first.new_at[0] == 0
    removed = result.changes[2]
    assert removed.new == {} and removed.new_at[0] == 1  # in der neuen Fassung: die Stelle, an der es fehlt
    assert len(removed.old[1]) == 1  # zwei Wörter derselben Zeile: ein Rechteck
    assert compare.summary(result) == "3 Unterschiede: 2 geändert, 1 entfernt."


def test_identical_text_and_scanned_pages_are_named() -> None:
    same = words(0, "Gleicher Text")
    result = compare.compare(same, list(same), old_empty=[2], new_empty=[])
    assert result.changes == []
    assert compare.summary(result).startswith("Keine Unterschiede im Text gefunden. 1 Seite ohne Text")


def test_session_reads_words_of_a_real_pdf(tmp_path: Path) -> None:
    old_path = samples.standard_text(tmp_path / "alt.pdf", pages=2)
    new_path = samples.standard_text(tmp_path / "neu.pdf", pages=2, lines=("Rechnung Nr. 4712 vom 01.10.2026", "Gesamtbetrag: 1.234,56 EUR", "Zahlbar innerhalb von 30 Tagen."))
    old, new = Session.open("a", str(old_path)), Session.open("b", str(new_path))
    try:
        old_words, old_empty = old.compare_words()
        new_words, _ = new.compare_words()
    finally:
        old.close()
        new.close()
    assert old_empty == [] and [word.text for word in old_words[:3]] == ["Rechnung", "Nr.", "4711"]
    result = compare.compare(old_words, new_words)
    assert [(change.before, change.after) for change in result.changes] == [("4711", "4712"), ("14", "30"), ("4711", "4712"), ("14", "30")]
    assert {change.new_at[0] for change in result.changes} == {0, 1}
