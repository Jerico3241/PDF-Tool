"""Anweisungen an das Sprachmodell: Antworten nur aus dem Dokument, auf Deutsch, mit Seitenangaben – und ehrlich, wenn
etwas nicht im Dokument steht.

Rechenzeit: Ein kleines Modell auf dem Prozessor liest nur einige Tausend Tokens in vertretbarer Zeit. Fragen bekommen
deshalb nur die passenden Abschnitte (``QUESTION_CHARS``); Zusammenfassungen lesen kurze Dokumente ganz und lange in
Teilen (``SUMMARY_PART_CHARS``), höchstens ``SUMMARY_MAX_PARTS`` Teile – darüber hinaus nennt die Antwort, bis zu
welcher Seite sie reicht.
"""

from __future__ import annotations

from dataclasses import dataclass

from .text import Passage, excerpt_block

QUESTION_CHARS = 9000  # Auszüge für eine Frage (rund 2800 Tokens)
SUMMARY_PART_CHARS = 12000  # ein Teil einer Zusammenfassung (rund 3800 Tokens)
SUMMARY_MAX_PARTS = 5
ANSWER_TOKENS = 700
PART_TOKENS = 320
TEMPERATURE = 0.2

SYSTEM = (
    "Du bist der Assistent im Programm PDF Tool. Du hilfst beim Verstehen des PDF-Dokuments, das der Benutzer "
    "geöffnet hat. Du kennst vom Dokument nur die Auszüge in der Nachricht; jeder Auszug beginnt mit seiner Seite, "
    "etwa [Seite 3]. Antworte ausschließlich anhand dieser Auszüge – erfinde nichts und ergänze kein Wissen von "
    "außen. Steht die Antwort nicht in den Auszügen, sage das ausdrücklich. Nenne nach jeder Aussage die Seite in "
    "Klammern, etwa (S. 3). Antworte auf Deutsch, sachlich und knapp; Zahlen, Beträge, Daten und Fristen genau wie "
    "im Dokument."
)


@dataclass(frozen=True)
class SummaryPlan:
    parts: list[list[Passage]]  # je Teil die Abschnitte
    last_page: int  # letzte gelesene Seite (1-basiert)
    complete: bool  # das ganze Dokument wird gelesen


def question_messages(question: str, excerpts: list[Passage]) -> list[dict]:
    text = excerpt_block(excerpts) if excerpts else "(Das Dokument enthält keinen lesbaren Text.)"
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Auszüge aus dem Dokument:\n<<<\n{text}\n>>>\n\nFrage: {question.strip()}"},
    ]


def plan_summary(items: list[Passage]) -> SummaryPlan:
    """Teile für die Zusammenfassung: Abschnitte der Reihe nach, je Teil höchstens ``SUMMARY_PART_CHARS`` Zeichen,
    höchstens ``SUMMARY_MAX_PARTS`` Teile."""
    parts: list[list[Passage]] = []
    current: list[Passage] = []
    used = 0
    for item in items:
        if current and used + len(item.text) > SUMMARY_PART_CHARS:
            parts.append(current)
            if len(parts) == SUMMARY_MAX_PARTS:
                current = []
                break
            current, used = [], 0
        current.append(item)
        used += len(item.text)
    if current:
        parts.append(current)
    read = [item for part in parts for item in part]
    last = (read[-1].page + 1) if read else 0
    return SummaryPlan(parts, last, len(read) == len(items))


def summary_messages(part: list[Passage]) -> list[dict]:
    """Ein Dokument (oder ein Teil davon) in einem Schritt zusammenfassen."""
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                f"Auszüge aus dem Dokument:\n<<<\n{excerpt_block(part)}\n>>>\n\n"
                "Fasse das Dokument in höchstens acht Stichpunkten zusammen: worum es geht, wer beteiligt ist, die "
                "wichtigsten Zahlen, Beträge, Daten und Fristen. Nenne bei jedem Stichpunkt die Seite."
            ),
        },
    ]


def part_messages(part: list[Passage], number: int, total: int) -> list[dict]:
    """Ein Teil eines langen Dokuments – Stichpunkte, die danach zusammengeführt werden."""
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                f"Teil {number} von {total} des Dokuments:\n<<<\n{excerpt_block(part)}\n>>>\n\n"
                "Notiere die wichtigsten Inhalte dieses Teils in höchstens fünf kurzen Stichpunkten, jeweils mit "
                "Seite. Zahlen, Beträge, Daten und Fristen genau übernehmen."
            ),
        },
    ]


def combine_messages(notes: list[str], last_page: int, complete: bool) -> list[dict]:
    """Stichpunkte der Teile zu einer Zusammenfassung zusammenführen."""
    joined = "\n\n".join(f"Teil {index}:\n{note.strip()}" for index, note in enumerate(notes, 1))
    scope = "" if complete else f" Die Stichpunkte reichen bis Seite {last_page}; das Dokument ist länger."
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                f"Stichpunkte aus den Teilen eines Dokuments (mit Seitenangaben):\n<<<\n{joined}\n>>>\n\n"
                "Fasse daraus das Dokument in höchstens acht Stichpunkten zusammen: worum es geht, wer beteiligt ist, "
                "die wichtigsten Zahlen, Beträge, Daten und Fristen. Behalte die Seitenangaben bei." + scope
            ),
        },
    ]
