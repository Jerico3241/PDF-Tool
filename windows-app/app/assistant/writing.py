"""KI-Schreibhilfen (seit 5.0 Beta 8): Text schreiben lassen, umschreiben, kürzen, ausführlicher, Ton ändern, in einfache
Sprache bringen, Grammatik prüfen und markierten Text übersetzen.

Alles läuft wie der übrige Assistent mit dem lokalen Sprachmodell. Lange Texte gehen in Stücken an das Modell
(``parts``, an Absätzen); das Ergebnis eines Stücks ist nur der neue Text – ``clean_output`` entfernt, was kleine Modelle
gern davor oder dahinter schreiben (»Hier ist der Text:«, Anführungszeichen, Markdown-Zäune).

Grammatik: Das Modell gibt den korrigierten Text zurück; ``changes`` vergleicht Satz für Satz und liefert nur die Sätze,
die sich geändert haben – jeder lässt sich einzeln übernehmen (im Text gesucht und ersetzt).
"""

from __future__ import annotations

I18N_CALLS = ()  # Anweisungen an das Sprachmodell und Dokumentinhalt – keine Oberflächentexte (tools/i18n_extract.py)

import difflib
import html
import re
from dataclasses import dataclass

from .prompts import translation_parts
from .text import estimate_tokens

MAX_EDIT_CHARS = 24000  # markierter Text: mehr wird nicht bearbeitet (sonst dauert es sehr lange)
MAX_GRAMMAR_CHARS = 30000  # ganzes Dokument prüfen: so viel Text höchstens
MAX_INSTRUCTION = 1500
WRITE_TOKENS = 900
TEMPERATURE_WRITE = 0.6  # freies Schreiben darf etwas abwechslungsreicher sein
TEMPERATURE_EDIT = 0.3

# Art → (Bezeichnung in der Oberfläche, Auftrag an das Modell)
MODES: dict[str, tuple[str, str]] = {
    "rewrite": ("Umschreiben", "Formuliere den Text neu: klarer und flüssiger, mit derselben Bedeutung und ungefähr derselben Länge."),
    "shorten": ("Kürzen", "Kürze den Text auf etwa die Hälfte. Behalte alle wichtigen Aussagen, Zahlen, Beträge, Namen und Daten."),
    "expand": ("Ausführlicher", "Formuliere den Text ausführlicher und anschaulicher, etwa doppelt so lang. Erfinde keine neuen Fakten, Zahlen oder Namen."),
    "simple": ("Einfache Sprache", "Schreibe den Text in einfacher Sprache: kurze Sätze, bekannte Wörter, keine Fachbegriffe ohne Erklärung. Die Aussagen bleiben gleich."),
    "formal": ("Förmlich", "Schreibe den Text in einem förmlichen, höflichen Ton (Sie-Form), wie in einem Geschäftsbrief."),
    "friendly": ("Freundlich", "Schreibe den Text in einem freundlichen, warmen und zugewandten Ton."),
    "factual": ("Sachlich", "Schreibe den Text sachlich und neutral, ohne Wertungen und Ausschmückungen."),
    "casual": ("Locker", "Schreibe den Text in einem lockeren, persönlichen Ton (Du-Form)."),
    "confident": ("Überzeugend", "Schreibe den Text überzeugend und selbstbewusst, mit klaren Aussagen."),
}
TONES = ("formal", "friendly", "factual", "casual", "confident")

EDIT_SYSTEM = (
    "Du bist die Schreibhilfe im Programm Novadesk. Du bearbeitest den Text des Benutzers genau nach dem Auftrag. "
    "Antworte in der Sprache des Textes. Gib nur den fertigen Text aus – ohne Einleitung, Erklärung, Anmerkungen, "
    "Anführungszeichen oder Markdown. Behalte Absätze und Aufzählungen bei."
)
WRITE_SYSTEM = (
    "Du bist die Schreibhilfe im Programm Novadesk. Du schreibst Texte nach dem Auftrag des Benutzers, auf Deutsch, "
    "sofern der Auftrag keine andere Sprache nennt. Gib nur den fertigen Text aus – ohne Einleitung, Erklärung oder "
    "Markdown-Zeichen wie # oder **. Absätze trennst du mit einer Leerzeile, Aufzählungen beginnen mit »- «. Erfinde "
    "keine konkreten Namen, Zahlen oder Daten, die nicht im Auftrag stehen – setze stattdessen Platzhalter in eckigen "
    "Klammern, etwa [Name] oder [Datum]."
)
GRAMMAR_SYSTEM = (
    "Du bist ein Korrektor. Korrigiere im Text des Benutzers nur Rechtschreibung, Grammatik und Zeichensetzung. Ändere "
    "sonst nichts: keine anderen Wörter, keinen anderen Stil, keine andere Reihenfolge, keine Umformulierungen. Ist "
    "der Text schon richtig, gib ihn unverändert aus. Gib nur den Text aus – ohne Erklärung, Einleitung oder "
    "Anführungszeichen. Absätze bleiben wie im Original."
)

_PREAMBLE = re.compile(
    r"^\s*(?:hier\s+(?:ist|sind|kommt|folgt)\b[^\n:]{0,80}:|(?:der|die|das)\s+(?:überarbeitete|gekürzte|korrigierte|neue|"
    r"umgeschriebene|übersetzte)\b[^\n:]{0,60}:|(?:überarbeiteter|gekürzter|korrigierter|neuer|umgeschriebener)\s+text\s*:|"
    r"(?:here\s+is|here's)\b[^\n:]{0,80}:|(?:übersetzung|translation|text|ergebnis)\s*:)\s*",
    re.IGNORECASE,
)
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$", re.DOTALL)
_QUOTES = (("»", "«"), ("„", "“"), ('"', '"'), ("“", "”"), ("«", "»"), ("'", "'"))
_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"“”»«')\]]*\s+(?=\S)")
_ABBREVIATION = re.compile(
    r"^(?:[A-Za-zÄÖÜäöü]\.|(?:[A-Za-zÄÖÜäöü]\.){2,}|\d{1,3}\.|(?:Dr|Nr|Hr|Fr|St|ca|bzw|ggf|inkl|evtl|vgl|Abs|Art|Tel|Str|Mio|Mrd|"
    r"Prof|gem|lt|zzgl|Jh|Mr|Mrs|etc|vs|No)\.)$")


def clean_output(text: str, original: str = "") -> str:
    """Antwort des Modells auf den reinen Text bringen: Einleitung, Markdown-Zaun und umschließende Anführungszeichen
    weg (nicht, wenn schon das Original so begann), Leerraum am Rand weg."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    fence = _FENCE.match(text)
    if fence:
        text = fence.group(1).strip()
    match = _PREAMBLE.match(text)
    if match and not _PREAMBLE.match(original or ""):
        text = text[match.end():].lstrip()
    for left, right in _QUOTES:
        if len(text) > 2 and text.startswith(left) and text.endswith(right) and text.count(left) == 1 and text.count(right) == 1:
            if not (original.strip().startswith(left) and original.strip().endswith(right)):
                text = text[len(left):-len(right)].strip()
            break
    return text


def plain(text: str) -> str:
    """Markdown, das kleine Modelle trotz Auftrag schreiben, in reinen Text: **fett** → fett, »# Titel« → »Titel«."""
    lines = []
    for line in str(text or "").split("\n"):
        line = re.sub(r"^\s*#{1,6}\s+", "", line)
        line = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), line)
        line = re.sub(r"(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])", r"\1", line)  # *kursiv*
        line = re.sub(r"^(\s*)[*•]\s+", r"\1- ", line)
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def parts(text: str) -> list[str]:
    """Text in Stücke für das Modell (an Absätzen, rund 2400 Zeichen) – ein Stück, wenn er kurz ist."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    return translation_parts(text) or [text]


def edit_messages(mode: str, text: str) -> list[dict]:
    label, task = MODES[mode]
    return [
        {"role": "system", "content": EDIT_SYSTEM},
        {"role": "user", "content": f"Auftrag: {task}\n\nText:\n<<<\n{text}\n>>>"},
    ]


def edit_tokens(mode: str, text: str) -> int:
    """Antwortlänge für ein Stück: »Ausführlicher« darf doppelt so lang werden, Kürzen braucht weniger."""
    tokens = estimate_tokens(text)
    factor = {"expand": 2.4, "shorten": 0.9}.get(mode, 1.5)
    return max(160, int(tokens * factor) + 64)


def write_messages(instruction: str, context: str = "") -> list[dict]:
    """»Text schreiben lassen«: ``instruction`` vom Benutzer, ``context`` der Text vor der Schreibmarke (Anschluss)."""
    instruction = " ".join(str(instruction or "").split())[:MAX_INSTRUCTION]
    content = f"Auftrag: {instruction}"
    if context.strip():
        content += f"\n\nDer Text soll an diese Stelle des Dokuments passen (davor steht):\n<<<\n{context.strip()[-1500:]}\n>>>"
    return [{"role": "system", "content": WRITE_SYSTEM}, {"role": "user", "content": content}]


def grammar_messages(text: str) -> list[dict]:
    return [{"role": "system", "content": GRAMMAR_SYSTEM}, {"role": "user", "content": text}]


def grammar_tokens(text: str) -> int:
    return max(160, int(estimate_tokens(text) * 1.25) + 64)


# Grammatik: Änderungen Satz für Satz --------------------------------------------------------------------------------
@dataclass(frozen=True)
class Change:
    before: str
    after: str

    @property
    def rich(self) -> str:
        return diff_rich(self.before, self.after)


def sentences(text: str) -> list[str]:
    """Sätze eines Absatzes (an ».«, »!«, »?« mit folgendem Leerraum)."""
    result = []
    for paragraph in re.split(r"\n+", str(text or "")):
        paragraph = paragraph.strip()
        start = 0
        for match in _SENTENCE_END.finditer(paragraph):
            word = paragraph[:match.start()].rsplit(None, 1)[-1] if paragraph[:match.start()].strip() else ""
            if _ABBREVIATION.match(word):  # »Dr.«, »z.B.«, »3.« beenden keinen Satz
                continue
            piece = paragraph[start:match.start()].strip()
            if piece:
                result.append(piece)
            start = match.end()
        if paragraph[start:].strip():
            result.append(paragraph[start:].strip())
    return result


def changes(original: str, corrected: str, limit: int = 200) -> list[Change]:
    """Geänderte Sätze (vorher, nachher). Sätze, die das Modell weggelassen, hinzugefügt oder stark umgeschrieben hat,
    gelten nicht als Korrektur – nur ähnliche Sätze (mindestens 60 % gleich) werden vorgeschlagen."""
    before, after = sentences(original), sentences(corrected)
    result: list[Change] = []
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        old, new = before[i1:i2], after[j1:j2]
        if len(old) == len(new):
            pairs = list(zip(old, new))
        else:  # anders geteilt: als ein Stück vergleichen
            pairs = [(" ".join(old), " ".join(new))]
        for a, b in pairs:
            if a == b or _normalized(a) == _normalized(b):
                continue
            if difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() < 0.6:
                continue
            result.append(Change(a, b))
            if len(result) >= limit:
                return result
    return result


def _normalized(text: str) -> str:
    return " ".join(text.split())


def diff_rich(before: str, after: str) -> str:
    """Unterschied Wort für Wort für die Anzeige (Qt »StyledText«): entfernt durchgestrichen, neu fett. Alles maskiert."""
    a, b = re.findall(r"\S+|\s+", before), re.findall(r"\S+|\s+", after)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append(html.escape("".join(a[i1:i2]), quote=False))
            continue
        old, new = "".join(a[i1:i2]), "".join(b[j1:j2])
        lead = old[: len(old) - len(old.lstrip())] or new[: len(new) - len(new.lstrip())]
        trail = old[len(old.rstrip()):] or new[len(new.rstrip()):]
        pieces = []
        if old.strip():
            pieces.append(f"<s>{html.escape(old.strip(), quote=False)}</s>")
        if new.strip():
            pieces.append(f"<b>{html.escape(new.strip(), quote=False)}</b>")
        out.append(lead + " ".join(pieces) + trail)
    return "".join(out)


def short(text: str, length: int = 70) -> str:
    """Kurzfassung für die Anzeige (»Umschreiben: »Sehr geehrte …««)."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"
