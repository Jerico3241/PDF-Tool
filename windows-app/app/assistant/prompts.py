"""Anweisungen an das Sprachmodell: Antworten nur aus dem Dokument, auf Deutsch, mit Seitenangaben – und ehrlich, wenn
etwas nicht im Dokument steht.

Rechenzeit: Ein kleines Modell auf dem Prozessor liest nur einige Tausend Tokens in vertretbarer Zeit. Fragen bekommen
deshalb nur die passenden Abschnitte (``QUESTION_CHARS``); Zusammenfassungen lesen kurze Dokumente ganz und lange in
Teilen (``SUMMARY_PART_CHARS``), höchstens ``SUMMARY_MAX_PARTS`` Teile – darüber hinaus nennt die Antwort, bis zu
welcher Seite sie reicht.
"""

from __future__ import annotations

from dataclasses import dataclass

from .text import Passage, excerpt_block, library_block

QUESTION_CHARS = 9000  # Auszüge für eine Frage (rund 2800 Tokens)
SUMMARY_PART_CHARS = 12000  # ein Teil einer Zusammenfassung (rund 3800 Tokens)
SUMMARY_MAX_PARTS = 5
ANSWER_TOKENS = 700
PART_TOKENS = 320
TEMPERATURE = 0.2

SYSTEM = (
    "Du bist der Assistent im Programm Novadesk. Du hilfst beim Verstehen des PDF-Dokuments, das der Benutzer "
    "geöffnet hat. Du kennst vom Dokument nur die Auszüge in der Nachricht; jeder Auszug beginnt mit seiner Seite, "
    "etwa [Seite 3]. Antworte ausschließlich anhand dieser Auszüge – erfinde nichts und ergänze kein Wissen von "
    "außen. Steht die Antwort nicht in den Auszügen, sage das ausdrücklich. Nenne nach jeder Aussage die Seite in "
    "Klammern, etwa (S. 3). Antworte auf Deutsch, sachlich und knapp; Zahlen, Beträge, Daten und Fristen genau wie "
    "im Dokument."
)


LIBRARY_SYSTEM = (
    "Du bist der Assistent im Programm Novadesk. Du hilfst beim Durchsuchen mehrerer PDF-Dateien, die der Benutzer "
    "gewählt hat. Du kennst von den Dateien nur die Auszüge in der Nachricht; jeder Auszug beginnt mit Datei und "
    "Seite, etwa [Datei 2 »Vertrag.pdf«, Seite 3]. Antworte ausschließlich anhand dieser Auszüge – erfinde nichts und "
    "ergänze kein Wissen von außen. Steht die Antwort nicht in den Auszügen, sage das ausdrücklich. Nenne nach jeder "
    "Aussage die Quelle in Klammern, etwa (Datei 2, S. 3). Antworte auf Deutsch, sachlich und knapp; Zahlen, Beträge, "
    "Daten und Fristen genau wie in den Dateien."
)
@dataclass(frozen=True)
class Scope:
    """Welche Art Dokument der Assistent liest (seit 5.0 Beta 8): ``pdf``, ``text`` (Text-Dokument), ``praesentation``
    oder ``tabelle``. Texte und Präsentationen zählen wie PDFs Seiten bzw. Folien; Tabellen nennen je »Seite« ein Blatt
    (``labels``, etwa »Blatt »Umsatz««) und in den Auszügen die Zeilen."""

    kind: str = "pdf"
    labels: tuple[str, ...] = ()

    @property
    def unit(self) -> str:
        return {"praesentation": "Folie", "tabelle": "Blatt"}.get(self.kind, "Seite")

    def block(self, items: list[Passage]) -> str:
        return excerpt_block(items, list(self.labels) or None, self.unit)

    @property
    def cite(self) -> str:
        """Wie Antworten ihre Quelle nennen sollen."""
        if self.kind == "praesentation":
            return "die Folie"
        if self.kind == "tabelle":
            return "Blatt und Zeile"
        return "die Seite"


PDF = Scope()


def system(scope: Scope = PDF) -> str:
    """Anweisung für Fragen und Zusammenfassungen – je Art des Dokuments."""
    if scope.kind == "text":
        return SYSTEM.replace("des PDF-Dokuments", "des Text-Dokuments")
    if scope.kind == "praesentation":
        return (
            "Du bist der Assistent im Programm Novadesk. Du hilfst beim Verstehen der Präsentation, die der Benutzer "
            "geöffnet hat. Du kennst von ihr nur die Auszüge in der Nachricht; jeder Auszug beginnt mit seiner Folie, "
            "etwa [Folie 3]. Antworte ausschließlich anhand dieser Auszüge – erfinde nichts und ergänze kein Wissen von "
            "außen. Steht die Antwort nicht in den Auszügen, sage das ausdrücklich. Nenne nach jeder Aussage die Folie in "
            "Klammern, etwa (Folie 3). Antworte auf Deutsch, sachlich und knapp; Zahlen, Beträge und Daten genau wie in "
            "der Präsentation."
        )
    if scope.kind == "tabelle":
        return (
            "Du bist der Assistent im Programm Novadesk. Du hilfst beim Verstehen der Tabelle, die der Benutzer geöffnet "
            "hat. Du kennst von ihr nur die Auszüge in der Nachricht; jeder Auszug beginnt mit seinem Blatt, etwa "
            "[Blatt »Umsatz«], jede Zeile mit ihrer Nummer und den Spalten als »Spalte: Wert«. Antworte ausschließlich "
            "anhand dieser Auszüge – erfinde nichts. Steht die Antwort nicht in den Auszügen, sage das ausdrücklich. "
            "Nenne Blatt und Zeile in Klammern, etwa (Blatt »Umsatz«, Zeile 12). Antworte auf Deutsch, sachlich und "
            "knapp; Zahlen, Beträge und Daten genau wie in der Tabelle. Rechne nur, wenn es nötig ist, und nenne dann den "
            "Rechenweg."
        )
    return SYSTEM


TRANSLATE_PART_CHARS = 2400  # ein Stück einer Übersetzung (rund 750 Tokens hin, etwas mehr zurück)
# Zielsprachen der Übersetzung: Schlüssel → (Anzeige, Sprache im Auftrag an das Modell)
LANGUAGES = {
    "en": ("Englisch", "Englische"), "de": ("Deutsch", "Deutsche"), "fr": ("Französisch", "Französische"),
    "es": ("Spanisch", "Spanische"), "it": ("Italienisch", "Italienische"), "nl": ("Niederländisch", "Niederländische"),
    "pl": ("Polnisch", "Polnische"), "pt": ("Portugiesisch", "Portugiesische"), "tr": ("Türkisch", "Türkische"),
}


@dataclass(frozen=True)
class SummaryPlan:
    parts: list[list[Passage]]  # je Teil die Abschnitte
    last_page: int  # letzte gelesene Seite (1-basiert)
    complete: bool  # das ganze Dokument wird gelesen


def question_messages(question: str, excerpts: list[Passage], scope: Scope = PDF) -> list[dict]:
    text = scope.block(excerpts) if excerpts else "(Das Dokument enthält keinen lesbaren Text.)"
    return [
        {"role": "system", "content": system(scope)},
        {"role": "user", "content": f"Auszüge aus dem Dokument:\n<<<\n{text}\n>>>\n\nFrage: {question.strip()}"},
    ]


def library_messages(question: str, excerpts: list[Passage], names: list[str]) -> list[dict]:
    text = library_block(excerpts, names) if excerpts else "(Die Dateien enthalten keinen lesbaren Text.)"
    return [
        {"role": "system", "content": LIBRARY_SYSTEM},
        {"role": "user", "content": f"Auszüge aus den Dateien:\n<<<\n{text}\n>>>\n\nFrage: {question.strip()}"},
    ]


def translate_messages(text: str, language: str) -> list[dict]:
    """Ein Stück Text übersetzen – nur die Übersetzung, Absätze wie im Original."""
    target = LANGUAGES[language][1]
    return [
        {"role": "system", "content": (
            f"Du bist ein Übersetzer. Übersetze den Text des Benutzers vollständig und genau ins {target}. Gib nur die "
            "Übersetzung aus – ohne Einleitung, Erklärung oder Anmerkungen. Behalte Absätze, Aufzählungen, Zahlen, "
            "Beträge, Daten, Namen und Abkürzungen bei. Ist der Text schon in der Zielsprache, gib ihn unverändert aus.")},
        {"role": "user", "content": text},
    ]


def translate_numbered_messages(text: str, language: str) -> list[dict]:
    """Übersetzung nebeneinander (seit 5.0 Beta 8): Absätze mit Nummern »[1] …« – die Nummern bleiben, damit jede
    Übersetzung neben ihrem Absatz steht."""
    target = LANGUAGES[language][1]
    return [
        {"role": "system", "content": (
            f"Du bist ein Übersetzer. Übersetze den Text des Benutzers vollständig und genau ins {target}. Jeder Absatz "
            "beginnt mit einer Nummer in eckigen Klammern, etwa [1]. Gib jeden Absatz übersetzt mit derselben Nummer am "
            "Anfang aus, in derselben Reihenfolge, getrennt durch eine Leerzeile – ohne Einleitung, Erklärung oder "
            "Anmerkungen. Behalte Zahlen, Beträge, Daten, Namen und Abkürzungen bei.")},
        {"role": "user", "content": text},
    ]


def translation_parts(text: str, size: int = TRANSLATE_PART_CHARS) -> list[str]:
    """Seitentext in Stücke für die Übersetzung: an Absätzen, zu lange Absätze an Satzgrenzen."""
    from .text import _split_long

    parts: list[str] = []
    current = ""
    for paragraph in [p.strip() for p in text.split("\n\n") if p.strip()]:
        pieces = [paragraph] if len(paragraph) <= size else _split_long(paragraph, size)
        for piece in pieces:
            if current and len(current) + 2 + len(piece) > size:
                parts.append(current)
                current = ""
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        parts.append(current)
    return parts


def translation_tokens(text: str) -> int:
    """Antwortlänge für ein Stück: großzügig, Übersetzungen werden oft länger als das Original."""
    from .text import estimate_tokens

    return max(200, int(estimate_tokens(text) * 1.6) + 64)


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


def summary_messages(part: list[Passage], scope: Scope = PDF) -> list[dict]:
    """Ein Dokument (oder ein Teil davon) in einem Schritt zusammenfassen."""
    return [
        {"role": "system", "content": system(scope)},
        {
            "role": "user",
            "content": (
                f"Auszüge aus dem Dokument:\n<<<\n{scope.block(part)}\n>>>\n\n"
                "Fasse das Dokument in höchstens acht Stichpunkten zusammen: worum es geht, wer beteiligt ist, die "
                f"wichtigsten Zahlen, Beträge, Daten und Fristen. Nenne bei jedem Stichpunkt {scope.cite}."
            ),
        },
    ]


def part_messages(part: list[Passage], number: int, total: int, scope: Scope = PDF) -> list[dict]:
    """Ein Teil eines langen Dokuments – Stichpunkte, die danach zusammengeführt werden."""
    where = {"praesentation": "Folie", "tabelle": "Blatt und Zeile"}.get(scope.kind, "Seite")
    return [
        {"role": "system", "content": system(scope)},
        {
            "role": "user",
            "content": (
                f"Teil {number} von {total} des Dokuments:\n<<<\n{scope.block(part)}\n>>>\n\n"
                "Notiere die wichtigsten Inhalte dieses Teils in höchstens fünf kurzen Stichpunkten, jeweils mit "
                f"{where}. Zahlen, Beträge, Daten und Fristen genau übernehmen."
            ),
        },
    ]


def combine_messages(notes: list[str], last_page: int, complete: bool, scope: Scope = PDF) -> list[dict]:
    """Stichpunkte der Teile zu einer Zusammenfassung zusammenführen."""
    joined = "\n\n".join(f"Teil {index}:\n{note.strip()}" for index, note in enumerate(notes, 1))
    rest = "" if complete else f" Die Stichpunkte reichen bis {scope.unit} {last_page}; das Dokument ist länger."
    return [
        {"role": "system", "content": system(scope)},
        {
            "role": "user",
            "content": (
                f"Stichpunkte aus den Teilen eines Dokuments (mit Seitenangaben):\n<<<\n{joined}\n>>>\n\n"
                "Fasse daraus das Dokument in höchstens acht Stichpunkten zusammen: worum es geht, wer beteiligt ist, "
                "die wichtigsten Zahlen, Beträge, Daten und Fristen. Behalte die Quellenangaben bei." + rest
            ),
        },
    ]
