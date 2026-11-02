"""KI-Werkzeuge von 5.0 Beta 8 ohne Oberfläche: Schreibhilfe (Ausgabe säubern, Sätze vergleichen), Gliederung einer
Präsentation lesen und als Datei schreiben, Übersetzung nebeneinander, Kennzahlen von Tabellen und Diagrammregel,
Formularfelder zuordnen und prüfen."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant import bilingual, formfill, prompts, slidegen, tables, writing  # noqa: E402
from assistant import text as doctext  # noqa: E402

DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
PRESENTATION = "{urn:oasis:names:tc:opendocument:xmlns:presentation:1.0}"


# --- Schreibhilfe -------------------------------------------------------------------------------------------------
def test_clean_output_removes_preambles_fences_and_quotes() -> None:
    assert writing.clean_output("Hier ist der überarbeitete Text:\n\nNeuer Satz.") == "Neuer Satz."
    assert writing.clean_output("```\nNeuer Satz.\n```") == "Neuer Satz."
    assert writing.clean_output("»Neuer Satz.«", "Alter Satz.") == "Neuer Satz."
    assert writing.clean_output("»Zitat« bleibt.", "»Zitat« bleibt fast.") == "»Zitat« bleibt."  # Anführungszeichen im Text bleiben
    assert writing.plain("## Titel\n**fett** und *kursiv*\n* Punkt") == "Titel\nfett und kursiv\n- Punkt"


def test_messages_carry_the_task_and_stay_within_limits() -> None:
    messages = writing.edit_messages("shorten", "Ein langer Text.")
    assert messages[0]["content"] == writing.EDIT_SYSTEM and "Kürze den Text" in messages[1]["content"] and "Ein langer Text." in messages[1]["content"]
    assert writing.edit_tokens("expand", "x" * 400) > writing.edit_tokens("shorten", "x" * 400)
    written = writing.write_messages("Einladung " * 400, "Vorher stand dies.")
    assert len(written[1]["content"]) < writing.MAX_INSTRUCTION + 200 and "Vorher stand dies." in written[1]["content"]
    assert set(writing.TONES) <= set(writing.MODES)


def test_sentences_respect_abbreviations() -> None:
    assert writing.sentences("Dr. Meier kommt um 9 Uhr. Er bringt z. B. Akten mit. Fertig!") == [
        "Dr. Meier kommt um 9 Uhr.", "Er bringt z. B. Akten mit.", "Fertig!"]


def test_changes_compare_sentence_by_sentence() -> None:
    original = "Das ist ein fehler. Dieser Satz stimmt. Er gehen heim."
    corrected = "Das ist ein Fehler. Dieser Satz stimmt. Er geht heim."
    found = writing.changes(original, corrected)
    assert [(c.before, c.after) for c in found] == [("Das ist ein fehler.", "Das ist ein Fehler."), ("Er gehen heim.", "Er geht heim.")]
    assert found[0].rich == "Das ist ein <s>fehler.</s> <b>Fehler.</b>"
    assert writing.changes("Ein Satz.", "Etwas völlig anderes, das nichts damit zu tun hat.") == []  # umgeschrieben statt korrigiert
    assert writing.changes(original, original) == []
    assert "&lt;b&gt;" in writing.diff_rich("<b>", "<i>")  # maskiert


def test_parts_split_long_texts() -> None:
    text = "\n\n".join(f"Absatz {n} " + "Wort " * 120 for n in range(10))
    pieces = writing.parts(text)
    assert len(pieces) > 1 and all(len(piece) <= 3200 for piece in pieces)


# --- Präsentation ----------------------------------------------------------------------------------------------------
ANSWER = """Gern, hier ist die Gliederung:
TITEL: Neue Urlaubsplanung
UNTERTITEL: Team Vertrieb
FOLIE: Warum neu?
- Bisher Excel-Listen
- **Doppelte** Buchungen
NOTIZ: Kurz die Probleme schildern.
## Ablauf
* Antrag im Portal
* Freigabe durch die Leitung
Folie 3: Nächste Schritte
1. Schulung im Mai
"""


def test_parse_reads_the_outline_tolerantly() -> None:
    outline = slidegen.parse(ANSWER, 3)
    assert outline.title == "Neue Urlaubsplanung" and outline.subtitle == "Team Vertrieb"
    assert [slide.title for slide in outline.slides] == ["Warum neu?", "Ablauf", "Nächste Schritte"]
    assert outline.slides[0].bullets == ["Bisher Excel-Listen", "Doppelte Buchungen"] and outline.slides[0].notes == "Kurz die Probleme schildern."
    assert outline.slides[2].bullets == ["Schulung im Mai"] and outline.usable
    assert len(slidegen.parse(ANSWER + "FOLIE: Vier\n- noch einer\n", 3).slides) == 3
    assert not slidegen.parse("Das kann ich leider nicht.").usable
    assert slidegen.clamp(1) == slidegen.MIN_SLIDES and slidegen.clamp(99) == slidegen.MAX_SLIDES and slidegen.clamp("x") == slidegen.DEFAULT_SLIDES


def test_write_fodp_makes_a_title_and_content_slides_with_notes(tmp_path: Path) -> None:
    outline = slidegen.parse(ANSWER.replace("Ablauf", "Ablauf & <Regeln>"), 3)
    target = slidegen.write_fodp(outline, tmp_path / "neu.fodp")
    tree = ET.parse(target)
    pages = tree.getroot().iter(f"{DRAW}page")
    pages = list(pages)
    assert len(pages) == 4
    texts = ["".join(page.itertext()) for page in pages]
    assert "Neue Urlaubsplanung" in texts[0] and "Ablauf & <Regeln>" in texts[2]
    notes = [page.find(f"{PRESENTATION}notes") for page in pages]
    assert notes[1] is not None and "Kurz die Probleme schildern." in "".join(notes[1].itertext())
    names = [page.get(f"{DRAW}name") for page in pages]
    assert len(set(names)) == len(names)


def test_topic_and_document_messages_name_the_count() -> None:
    assert "Genau 5 Inhaltsfolien" in slidegen.topic_messages("Thema", 5)[1]["content"]
    document = slidegen.document_messages("Text " * 5000, 4, "bericht.pdf")[1]["content"]
    assert "bericht.pdf" in document and len(document) < slidegen.SOURCE_CHARS + 3000


# --- Übersetzung nebeneinander -------------------------------------------------------------------------------------
def test_numbered_round_trip_and_missing_numbers() -> None:
    items = ["Erster Absatz.", "Zweiter Absatz.", "Dritter."]
    sent = bilingual.numbered(items, [0, 1, 2])
    assert sent == "[1] Erster Absatz.\n\n[2] Zweiter Absatz.\n\n[3] Dritter."
    assert bilingual.split_numbered("[1] First.\n\n[3] Third.", 3) == ["First.", None, "Third."]
    assert bilingual.split_numbered("Only one.", 1) == ["Only one."]
    assert bilingual.paragraphs("Zeile eins\nweiter\n\n\nNeuer Absatz") == ["Zeile eins weiter", "Neuer Absatz"]
    chunks = bilingual.chunks(["x" * 900] * 5, 2000)
    assert chunks == [[0, 1], [2, 3], [4]]
    assert "etwa [1]" in prompts.translate_numbered_messages(sent, "en")[0]["content"]


def test_write_fodt_puts_original_and_translation_side_by_side(tmp_path: Path) -> None:
    blocks = [bilingual.Block("Seite 1", ["Hallo & <Welt>", "Zwei"], ["Hello & <world>", ""])]
    target = bilingual.write_fodt(blocks, tmp_path / "x.fodt", title="Brief – Englisch", source="brief.pdf", language="Englisch")
    root = ET.parse(target).getroot()
    rows = list(root.iter("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row"))
    cells = [["".join(cell.itertext()) for cell in row] for row in rows]
    assert cells[0] == ["Original", "Übersetzung (Englisch)"] and cells[1][0] == "Seite 1"
    assert cells[2] == ["Hallo & <Welt>", "Hello & <world>"] and cells[3] == ["Zwei", "–"]


# --- Tabellen --------------------------------------------------------------------------------------------------------
def test_numbers_and_dates_in_german_formats() -> None:
    assert tables.number("1.234,50 €") == 1234.5 and tables.number("-12") == -12 and tables.number("−3,5 %") == -3.5
    assert tables.number("12.5") == 12.5 and tables.number("abc") is None and tables.number("2026-01-01") is None
    assert tables.day("3.5.2026").isoformat() == "2026-05-03" and tables.day("Mai") is None
    assert tables.fmt(5250) == "5.250" and tables.fmt(1234.5) == "1.234,50"


ROWS = [["Monat", "Umsatz", "Status"], ["Januar", "1.200", "offen"], ["Februar", "1.350", "offen"], ["März", "1.100", "bezahlt"], ["April", "1.600", "offen"]]


def test_profile_computes_the_key_figures_itself() -> None:
    prof = tables.profile(ROWS, first_row=4)
    assert prof.header and prof.rows == 4 and [c.kind for c in prof.columns] == ["text", "zahl", "text"]
    revenue = prof.columns[1].stats
    assert revenue["sum"] == 5250 and revenue["max"] == 1600 and revenue["max_row"] == 8 and revenue["min_row"] == 7
    summary = prof.summary()
    assert "»Umsatz« (Zahlen, 4 Werte): Summe 5.250" in summary and "offen (3×)" in summary
    assert tables.sheet_page("Umsatz", ROWS[:2]).startswith("Zeile 2: Monat: Januar; Umsatz: 1.200; Status: offen")
    messages = tables.analysis_messages(prof, ROWS, "Umsatz")
    assert "wertest Tabellen aus" in messages[0]["content"] and "Summe 5.250" in messages[1]["content"]


def test_chart_rule_picks_by_the_shape_of_the_table() -> None:
    assert tables.chart_rule(tables.profile(ROWS)).kind == "line"  # Monate: Verlauf
    shares = [["Region", "Anteil"], ["Nord", "30"], ["Süd", "50"], ["West", "20"]]
    assert tables.chart_rule(tables.profile(shares)).kind == "pie"
    many = [["Kunde", "Betrag", "Kosten"]] + [[f"Kunde {n}", str(n), str(n + 1)] for n in range(12)]
    assert tables.chart_rule(tables.profile(many)).kind == "bar"
    two = [["Team", "Plan", "Ist"], ["A", "1", "2"], ["B", "3", "4"]]
    assert tables.chart_rule(tables.profile(two)).kind == "column"
    assert tables.chart_rule(tables.profile([["Name"], ["Anna"], ["Ben"]])) is None
    assert tables.is_period("Q3") and tables.is_period("KW 12") and not tables.is_period("Müller")


# --- Formular -----------------------------------------------------------------------------------------------------
FIELDS = [
    formfill.Field("1", "person.vorname", "text", "Vorname", max_length=10),
    formfill.Field("2", "Text2", "text", ""),
    formfill.Field("3", "agb", "checkbox", "AGB akzeptiert"),
    formfill.Field("4", "anrede", "radio", "Anrede", options=(("/Herr", "Herr"), ("/Frau", "Frau"))),
    formfill.Field("5", "land", "combo", "Land", options=(("DE", "Deutschland"), ("AT", "Österreich")), value="DE"),
]


def test_describe_and_schema_list_every_field() -> None:
    text = formfill.describe(FIELDS)
    assert "1: Vorname [Feldname person.vorname] (Textfeld, höchstens 10 Zeichen)" in text
    assert "2: Text2 (Textfeld)" in text and "3: AGB akzeptiert [Feldname agb] (Kontrollkästchen, true oder false)" in text
    assert '"Herr", "Frau"' in text
    schema = formfill.schema(FIELDS)
    assert schema["properties"]["3"] == {"type": "boolean"} and schema["additionalProperties"] is False
    assert "Angaben des Benutzers" in formfill.messages(FIELDS, "x" * 20000)[1]["content"]
    assert len(formfill.messages(FIELDS, "x" * 20000)[1]["content"]) < formfill.MAX_DATA_CHARS + 2000


def test_proposals_check_every_value_against_its_field() -> None:
    answer = formfill.parse_json('Hier: ```json\n{"1": "Annabelle-Marie", "3": "ja", "4": "frau", "5": "Deutschland", "9": "x", "2": ["x"],}\n```')
    proposals = {p.key: p for p in formfill.proposals(FIELDS, answer)}
    assert proposals["1"].value == "Annabelle-" and proposals["3"].value is True and proposals["3"].display == "Ja"
    assert proposals["4"].value == "/Frau" and proposals["4"].display == "Frau"
    assert "5" not in proposals  # schon so ausgefüllt
    assert "2" not in proposals and "9" not in proposals
    assert formfill.parse_json("kein JSON") == {} and formfill.parse_json("[1, 2]") == {}
    assert formfill.normalize(FIELDS[3], "Herr Dr.") == ("/Herr", "Herr")
    assert formfill.normalize(FIELDS[2], "vielleicht") is None
    assert FIELDS[1].title == "Text2" and formfill.Field("x", "form1[0].seite1[0].Strasse_Nr[0]", "text").title == "Strasse Nr"


# --- Antworten zu Folien ----------------------------------------------------------------------------------------------
def test_citations_also_link_slides() -> None:
    assert doctext.cited_pages("Das steht auf Folie 2 und Folien 3.", 5) == [2, 3]
    scope = prompts.Scope("praesentation")
    assert scope.unit == "Folie" and "die Folie" in prompts.system(scope)
    sheet = prompts.Scope("tabelle", ("Blatt »A«",))
    assert sheet.unit == "Blatt"


def test_header_rows_with_years_or_a_date_are_recognized() -> None:
    assert tables.has_header([["Monat", "Umsatz", "Stand 01.01.2026", "01.01.2026"], ["Januar", "1200", "", ""]])
    years = tables.profile([["Region", "2024", "2025"], ["Nord", "10", "12"], ["Süd", "7", "9"]])
    assert years.header and [c.name for c in years.columns] == ["Region", "2024", "2025"] and years.columns[1].stats["sum"] == 17
    assert not tables.has_header([["1", "2"], ["3", "4"]])
