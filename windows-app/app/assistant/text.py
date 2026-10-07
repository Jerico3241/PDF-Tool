"""Text eines PDFs für den KI-Assistenten: Abschnitte mit Seitenangabe, die Suche passender Stellen zu einer Frage und
die Seitenangaben in den Antworten.

Ein kleines Sprachmodell kann nicht ein ganzes langes Dokument auf einmal lesen. Für eine Frage sucht ``Index`` daher
zuerst die passenden Abschnitte (BM25 – dasselbe Verfahren wie viele Suchmaschinen, hier mit einfacher Behandlung
deutscher Wortformen und zusammengesetzter Wörter); nur diese gehen mit ihrer Seitenzahl an das Modell. Die Antwort
nennt die Seiten – ``rich`` macht daraus Verweise, die zur Seite springen.

Nichts hier protokolliert Text.
"""

from __future__ import annotations

import html
import math
import re
from collections import Counter
from dataclasses import dataclass

CHARS_PER_TOKEN = 3.2  # Schätzung für deutsche Texte (eher zu wenig Zeichen je Token – nie zu viel Text)
PASSAGE_CHARS = 1000
MIN_PREFIX_WORD = 7  # längere Wörter zählen zusätzlich mit ihrem Anfang (»Kündigungsfrist« trifft »Kündigung«)
PREFIX = 5

_STOPWORDS = (
    """
    aber alle allem allen aller alles als also am an ander andere anderem anderen anderer anderes auch auf aus bei bin
    bis bist da damit dann das dass dein deine dem den der des dessen deshalb die dies diese diesem diesen dieser dieses
    doch dort du durch ein eine einem einen einer eines er es etwas euch euer eure für gegen gewesen hab habe haben hat
    hatte hätte hier hin hinter ich ihm ihn ihnen ihr ihre ihrem ihren ihrer im in ins ist ja jede jedem jeden jeder
    jedes jetzt kann kein keine keinem keinen keiner können könnte machen man manche mein meine mich mir mit muss musste
    nach nicht nichts noch nun nur ob oder ohne sehr sein seine seinem seinen seiner sich sie sind so solche soll sollte
    sondern sonst über um und uns unser unsere unter viel vom von vor war waren warum was weg weil weiter welche welchem
    welchen welcher welches wenn wer werde werden wie wieder will wir wird wirst wo wollen wollte würde würden zu zum
    zur zwar zwischen
    a an and are as at be by for from has have in is it its of on or that the this to was were will with
    bitte gibt gilt steht stehen dokument pdf seite seiten
    """
)
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
STOPWORDS = frozenset(word.translate(_UMLAUTS) for word in _STOPWORDS.split())  # wie die Suchbegriffe geschrieben
_WORD = re.compile(r"[0-9a-z]+")
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(?=[a-zäöüß])")
_SPACES = re.compile(r"[ \t ]+")
_SENTENCE = re.compile(r"(?<=[.!?:;])\s+")
# Seitenangaben in Antworten: »S. 3«, »S. 3–4«, »S. 3, 5 und 7«, »Seite 3«, »Seiten 3 bis 5«
_CITATION = re.compile(r"\b(S\.|Seiten?)\s?(\d{1,5})((?:\s?(?:[,–\-]|und|bis)\s?\d{1,5})*)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_BULLET = re.compile(r"[-*•·]\s+")  # nummerierte Zeilen bleiben Text: ihre Zahlen bleiben genau so stehen
_HEADING = re.compile(r"#{1,6}\s+")


@dataclass(frozen=True)
class Passage:
    page: int  # 0-basiert
    text: str


def clean(text: str) -> str:
    """Seitentext aufbereiten: Silbentrennung am Zeilenende zusammenführen, Leerraum vereinheitlichen."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    text = _HYPHEN_BREAK.sub(r"\1", text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def passages(pages: list[str], size: int = PASSAGE_CHARS) -> list[Passage]:
    """Seitentexte in Abschnitte von höchstens etwa ``size`` Zeichen – nie über eine Seitengrenze hinweg. Absätze
    bleiben zusammen, solange sie passen; zu lange Absätze werden an Satzgrenzen geteilt."""
    result: list[Passage] = []
    for page, raw in enumerate(pages):
        text = clean(raw)
        if not text:
            continue
        pieces: list[str] = []
        for paragraph in re.split(r"\n\s*\n", text):
            paragraph = " ".join(line.strip() for line in paragraph.split("\n") if line.strip())
            if len(paragraph) <= size:
                pieces.append(paragraph)
                continue
            pieces.extend(_split_long(paragraph, size))
        current = ""
        for piece in pieces:
            if current and len(current) + 1 + len(piece) > size:
                result.append(Passage(page, current))
                current = piece
            else:
                current = f"{current}\n{piece}" if current else piece
        if current:
            result.append(Passage(page, current))
    return result


def _split_long(paragraph: str, size: int) -> list[str]:
    out: list[str] = []
    current = ""
    for sentence in _SENTENCE.split(paragraph):
        while len(sentence) > size:  # ein Satz ohne Satzzeichen: an einer Wortgrenze teilen
            cut = sentence.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            if current:
                out.append(current)
                current = ""
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > size:
            out.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        out.append(current)
    return out


def tokens(text: str) -> list[str]:
    """Suchbegriffe: klein, Umlaute ausgeschrieben, ohne Füllwörter; lange Wörter zusätzlich mit ihrem Anfang."""
    words = _WORD.findall(str(text or "").lower().translate(_UMLAUTS))
    result: list[str] = []
    for word in words:
        if word in STOPWORDS or (len(word) < 2 and not word.isdigit()):
            continue
        result.append(word)
        if len(word) >= MIN_PREFIX_WORD and not word.isdigit():
            result.append("~" + word[:PREFIX])
    return result


def estimate_tokens(text: str) -> int:
    return int(math.ceil(len(text) / CHARS_PER_TOKEN))


class Index:
    """BM25 über die Abschnitte eines Dokuments."""

    K1 = 1.4
    B = 0.75

    def __init__(self, items: list[Passage]) -> None:
        self.items = items
        self._terms = [Counter(tokens(item.text)) for item in items]
        self._lengths = [sum(terms.values()) for terms in self._terms]
        self._average = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        frequency: Counter = Counter()
        for terms in self._terms:
            frequency.update(terms.keys())
        count = len(items)
        self._idf = {term: math.log(1 + (count - df + 0.5) / (df + 0.5)) for term, df in frequency.items()}

    def scores(self, query: str) -> list[float]:
        wanted = Counter(tokens(query))
        result = []
        for terms, length in zip(self._terms, self._lengths):
            score = 0.0
            for term, weight in wanted.items():
                tf = terms.get(term)
                if not tf:
                    continue
                norm = tf * (self.K1 + 1) / (tf + self.K1 * (1 - self.B + self.B * length / (self._average or 1)))
                # Wortanfänge zählen halb – sie sind unschärfer als das ganze Wort
                score += self._idf.get(term, 0.0) * norm * (0.5 if term.startswith("~") else 1.0) * min(weight, 2)
            result.append(score)
        return result

    def search(self, query: str, budget_chars: int) -> list[Passage]:
        """Die passendsten Abschnitte, zusammen höchstens ``budget_chars`` Zeichen, in der Reihenfolge des Dokuments.
        Trifft nichts, kommen die ersten Abschnitte (der Anfang eines Dokuments enthält oft das Wichtigste)."""
        scores = self.scores(query)
        order = sorted((i for i in range(len(self.items)) if scores[i] > 0), key=lambda i: (-scores[i], i))
        beginning = not order  # nichts passt: der Anfang des Dokuments, ohne Lücken
        if beginning:
            order = list(range(len(self.items)))
        chosen: list[int] = []
        used = 0
        for index in order:
            size = len(self.items[index].text)
            if used + size > budget_chars:
                if not chosen and size > budget_chars:  # schon der erste Abschnitt ist zu lang: gekürzt
                    return [Passage(self.items[index].page, self.items[index].text[:budget_chars])]
                if beginning:
                    break
                continue
            chosen.append(index)
            used += size
        return [self.items[index] for index in sorted(chosen)]


def excerpt_block(items: list[Passage]) -> str:
    """Abschnitte für das Modell: je Abschnitt »[Seite N]« und der Text."""
    return "\n\n".join(f"[Seite {item.page + 1}]\n{item.text}" for item in items)


def cited_pages(answer: str, page_count: int) -> list[int]:
    """Seitenzahlen (1-basiert), die eine Antwort nennt – nur Seiten, die es im Dokument gibt."""
    pages: list[int] = []
    for match in _CITATION.finditer(answer or ""):
        for number in _numbers(match):
            if 1 <= number <= page_count and number not in pages:
                pages.append(number)
    return pages


def _numbers(match: re.Match) -> list[int]:
    first = int(match.group(2))
    numbers = [first]
    rest = match.group(3) or ""
    previous = first
    for separator, value in re.findall(r"\s?([,–\-]|und|bis)\s?(\d{1,5})", rest):
        number = int(value)
        if separator in ("–", "-", "bis") and previous < number <= previous + 50:
            numbers.extend(range(previous + 1, number + 1))
        else:
            numbers.append(number)
        previous = number
    return numbers


def rich(answer: str, page_count: int) -> str:
    """Antwort für die Anzeige (Qt »StyledText«). Zuerst wird alles maskiert – so kann eine Antwort weder Bilder noch
    Verweise oder andere Auszeichnungen einschleusen (ihr Inhalt stammt zum Teil aus dem PDF). Danach nur: **fett**,
    Überschriften (fett), Stichpunkte und Seitenverweise: »S. 3–5« verweist auf die Seiten 3 und 5, ein Klick springt
    dorthin. Zahlen, die keine Seite des Dokuments sind, bleiben Text."""

    def page_link(number: re.Match) -> str:
        value = int(number.group(0))
        return f'<a href="page:{value}">{value}</a>' if 1 <= value <= page_count else number.group(0)

    def citation(match: re.Match) -> str:
        label, rest = match.group(1), match.group(0)[len(match.group(1)):]
        return label + re.sub(r"\d{1,5}", page_link, rest)

    def inline(line: str) -> str:
        line = _BOLD.sub(lambda match: f"<b>{match.group(1) or match.group(2)}</b>", html.escape(line, quote=False))
        return _CITATION.sub(citation, line)

    out: list[str] = []
    in_list = False
    gap = False  # Leerzeile davor: neuer Absatz
    for raw in str(answer or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            gap = bool(out)
            continue
        bullet = _BULLET.match(line)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[bullet.end():])}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            heading = _HEADING.match(line)
            text = f"<b>{inline(line[heading.end():])}</b>" if heading else inline(line)
            if out and out[-1] != "</ul>":
                out.append("<br><br>" if gap else "<br>")
            elif out and gap:
                out.append("<br>")
            out.append(text)
        gap = False
    if in_list:
        out.append("</ul>")
    return "".join(out)
