"""Formatierter Text für Kopf- und Fußzeile – unabhängig von Tk und ReportLab.

Datenmodell
-----------
Ein ``RichText`` besteht aus dem reinen Text, einer Formatierung je Zeichen
(``CharStyle``) und einer Ausrichtung je Absatz. Absätze trennt ``\\n``.

Gespeichert wird er als JSON-kompatibles Wörterbuch::

    {
      "version": 1,
      "text": "Kundennummer: {kd}",
      "spans": [
        {"start": 0, "end": 14, "font": "Helvetica", "size": 8, "color": "#333333",
         "bold": false, "italic": false, "underline": false, "strike": false},
        {"start": 14, "end": 18, "font": "Helvetica", "size": 8, "color": "#B51F1F",
         "bold": true, "italic": false, "underline": false, "strike": false}
      ],
      "paragraphs": [{"start": 0, "end": 18, "alignment": "left"}]
    }

``spans`` decken den Text lückenlos ab (gleiche Nachbarn zusammengefasst),
``paragraphs`` enthalten jeden Absatz ohne das trennende ``\\n``. Der reine Text
steht zusätzlich wie bisher unter ``kopfzeile`` bzw. ``fusszeile``. Passen beide
nicht zusammen (z. B. nach einer Bearbeitung mit einer älteren Version), gilt der
reine Text mit Standardformatierung – es geht nie Text verloren.

Für die PDF entsteht ReportLab-Absatz-Markup: Der Text wird zuerst maskiert,
danach setzt ausschließlich dieses Modul eigene Tags (``<font>``, ``<u>``,
``<strike>``). Eingaben werden nie als Markup interpretiert.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Mapping

FORMAT_VERSION = 1
ALIGNMENTS = ("left", "center", "right")
FONT_SIZES = (6, 7, 8, 9, 10, 11, 12, 14, 16, 18)
MIN_SIZE = 4.0
MAX_SIZE = 72.0
LINE_FACTOR = 1.25  # Zeilenabstand je Schriftgröße: 8 pt → 10 pt wie in den bisherigen PDFs
TEXT_COLOR = "#333333"  # Textfarbe von Kopf- und Fußzeile in der PDF
PLACEHOLDER_NAMES = ("kd", "kundennummer", "kunde", "firma", "datum", "datumkurz")

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PLACEHOLDER = re.compile(r"\{([A-Za-z]+)\}")


def normalize_newlines(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def valid_color(value, default: str = TEXT_COLOR) -> str:
    if isinstance(value, str) and _HEX.match(value.strip()):
        return value.strip().upper()
    return default


def valid_size(value, default: float = 8) -> float:
    if isinstance(value, bool):
        return default
    try:
        size = float(value)
    except (TypeError, ValueError):
        return default
    if size != size or not (MIN_SIZE <= size <= MAX_SIZE):
        return default
    return int(size) if size.is_integer() else round(size, 1)


def size_text(size: float) -> str:
    return str(int(size)) if float(size).is_integer() else f"{size:g}"


@dataclass(frozen=True)
class CharStyle:
    """Formatierung eines Zeichens."""

    font: str = "Helvetica"
    size: float = 8
    color: str = TEXT_COLOR
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False

    def with_(self, **changes) -> "CharStyle":
        return replace(self, **changes)

    def to_dict(self) -> dict:
        return {
            "font": self.font,
            "size": valid_size(self.size),
            "color": self.color,
            "bold": self.bold,
            "italic": self.italic,
            "underline": self.underline,
            "strike": self.strike,
        }

    @classmethod
    def from_dict(cls, data: Mapping, default: "CharStyle") -> "CharStyle":
        font = data.get("font")
        return cls(
            font=font.strip() if isinstance(font, str) and font.strip() else default.font,
            size=valid_size(data.get("size"), default.size),
            color=valid_color(data.get("color"), default.color),
            bold=data.get("bold") is True if "bold" in data else default.bold,
            italic=data.get("italic") is True if "italic" in data else default.italic,
            underline=data.get("underline") is True if "underline" in data else default.underline,
            strike=data.get("strike") is True if "strike" in data else default.strike,
        )


# Etablierte Optik der PDF: Helvetica 8 pt, dunkles Grau; Kopfzeile links, Fußzeile zentriert.
HEADER_STYLE = CharStyle()
FOOTER_STYLE = CharStyle()
HEADER_ALIGN = "left"
FOOTER_ALIGN = "center"


class RichText:
    """Text mit Formatierung je Zeichen und Ausrichtung je Absatz (unveränderlich verwendet)."""

    __slots__ = ("text", "styles", "aligns", "default", "align")

    def __init__(self, text: str = "", styles: Iterable[CharStyle] | None = None, aligns: Iterable[str] | None = None, default: CharStyle = FOOTER_STYLE, align: str = "left") -> None:
        text = normalize_newlines(text)
        self.text = text
        self.default = default
        self.align = align if align in ALIGNMENTS else "left"
        char_styles = list(styles or [])
        if len(char_styles) < len(text):
            char_styles += [default] * (len(text) - len(char_styles))
        self.styles: list[CharStyle] = char_styles[: len(text)]
        count = text.count("\n") + 1
        paragraph_aligns = [a if a in ALIGNMENTS else self.align for a in (aligns or [])]
        if len(paragraph_aligns) < count:
            paragraph_aligns += [self.align] * (count - len(paragraph_aligns))
        self.aligns: list[str] = paragraph_aligns[:count]

    # Erzeugen ------------------------------------------------------------------
    @classmethod
    def plain(cls, text: str, default: CharStyle = FOOTER_STYLE, align: str = "left") -> "RichText":
        return cls(text, None, None, default, align)

    @classmethod
    def from_dict(cls, data, default: CharStyle = FOOTER_STYLE, align: str = "left", text: str | None = None) -> "RichText | None":
        """Gespeicherte Formatierung laden. ``None``, wenn sie ungültig ist oder nicht zu ``text`` passt."""
        if not isinstance(data, Mapping):
            return None
        stored = data.get("text")
        if not isinstance(stored, str):
            return None
        stored = normalize_newlines(stored)
        if text is not None and normalize_newlines(text) != stored:
            return None
        styles = [default] * len(stored)
        for span in data.get("spans") or []:
            if not isinstance(span, Mapping):
                continue
            start, end = span.get("start"), span.get("end")
            if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
                continue
            start, end = max(0, start), min(len(stored), end)
            if end <= start:
                continue
            style = CharStyle.from_dict(span, default)
            styles[start:end] = [style] * (end - start)
        by_start: dict[int, str] = {}
        for paragraph in data.get("paragraphs") or []:
            if isinstance(paragraph, Mapping) and isinstance(paragraph.get("start"), int) and paragraph.get("alignment") in ALIGNMENTS:
                by_start[int(paragraph["start"])] = str(paragraph["alignment"])
        rich = cls(stored, styles, None, default, align)
        rich.aligns = [by_start.get(start, rich.align) for start, _end, _a in rich.paragraphs()]
        return rich

    @classmethod
    def from_storage(cls, text: str, data, default: CharStyle = FOOTER_STYLE, align: str = "left") -> "RichText":
        """Reiner Text plus gespeicherte Formatierung; ohne passende Formatierung: Standardformat."""
        return cls.from_dict(data, default, align, text=text) or cls.plain(text, default, align)

    # Abfragen -----------------------------------------------------------------------
    def __eq__(self, other) -> bool:
        if not isinstance(other, RichText):
            return NotImplemented
        return self.text == other.text and self.styles == other.styles and self.aligns == other.aligns

    def __repr__(self) -> str:
        return f"RichText({self.text!r}, runs={len(self.runs())}, aligns={self.aligns!r})"

    def is_blank(self) -> bool:
        return not self.text.strip()

    def paragraphs(self) -> list[tuple[int, int, str]]:
        """Absätze als (Anfang, Ende ohne ``\\n``, Ausrichtung)."""
        result = []
        start = 0
        for index, line in enumerate(self.text.split("\n")):
            end = start + len(line)
            result.append((start, end, self.aligns[index]))
            start = end + 1
        return result

    def runs(self, start: int = 0, end: int | None = None) -> list[tuple[int, int, CharStyle]]:
        """Abschnitte gleicher Formatierung im Bereich [start, end)."""
        end = len(self.text) if end is None else min(end, len(self.text))
        result: list[tuple[int, int, CharStyle]] = []
        index = max(0, start)
        while index < end:
            style = self.styles[index]
            stop = index + 1
            while stop < end and self.styles[stop] == style:
                stop += 1
            result.append((index, stop, style))
            index = stop
        return result

    def style_at(self, index: int) -> CharStyle:
        """Format am Zeichen ``index`` (bzw. des letzten Zeichens, sonst das Standardformat)."""
        if 0 <= index < len(self.styles):
            return self.styles[index]
        if self.styles:
            return self.styles[-1]
        return self.default

    def paragraph_style(self, start: int, end: int) -> CharStyle:
        """Format eines Absatzes für Leerzeilen: das Format seines Absatzzeichens."""
        if end < len(self.text):
            return self.styles[end]
        if start > 0:
            return self.styles[start - 1]
        return self.default

    # Speichern --------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "version": FORMAT_VERSION,
            "text": self.text,
            "spans": [{"start": s, "end": e, **style.to_dict()} for s, e, style in self.runs()],
            "paragraphs": [{"start": s, "end": e, "alignment": a} for s, e, a in self.paragraphs()],
        }

    # Umformen -------------------------------------------------------------------------------
    def stripped(self) -> "RichText":
        """Wie beim reinen Text: Leerraum am Ende entfernen; nur Leerraum gilt als leer."""
        keep = len(self.text.rstrip()) if self.text.strip() else 0
        text = self.text[:keep]
        return RichText(text, self.styles[:keep], self.aligns[: text.count("\n") + 1], self.default, self.align)

    def with_placeholders(self, values: Mapping[str, str]) -> "RichText":
        """Bekannte Platzhalter ersetzen; der eingesetzte Wert behält die Formatierung des Platzhalters."""
        text: list[str] = []
        styles: list[CharStyle] = []
        position = 0
        for match in _PLACEHOLDER.finditer(self.text):
            name = match.group(1)
            if name not in values:
                continue
            text.append(self.text[position : match.start()])
            styles.extend(self.styles[position : match.start()])
            value = normalize_newlines(str(values[name])).replace("\n", " ")
            text.append(value)
            styles.extend([self.styles[match.start()]] * len(value))
            position = match.end()
        if position == 0 and not text:
            return self
        text.append(self.text[position:])
        styles.extend(self.styles[position:])
        return RichText("".join(text), styles, self.aligns, self.default, self.align)


# ---------------------------------------------------------------------------
# ReportLab-Markup (nur Zeichenketten – ReportLab selbst wird hier nicht geladen)
# ---------------------------------------------------------------------------


def escape_markup(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def paragraph_markup(rich: RichText, start: int, end: int, font_name: Callable[[str, bool, bool], str]) -> str:
    """Markup eines Absatzes. ``font_name(schrift, fett, kursiv)`` liefert den PDF-Schriftnamen."""
    parts = []
    for s, e, style in rich.runs(start, end):
        inner = escape_markup(rich.text[s:e])
        if style.strike:
            inner = f"<strike>{inner}</strike>"
        if style.underline:
            inner = f"<u>{inner}</u>"
        name = font_name(style.font, style.bold, style.italic)
        parts.append(f'<font name="{name}" size="{size_text(style.size)}" color="{valid_color(style.color)}">{inner}</font>')
    return "".join(parts)


def paragraph_size(rich: RichText, start: int, end: int) -> float:
    """Größte Schrift eines Absatzes (bestimmt den Zeilenabstand); Leerzeilen: Format des Absatzzeichens."""
    sizes = [style.size for _s, _e, style in rich.runs(start, end)]
    if sizes:
        return max(sizes)
    return rich.paragraph_style(start, end).size
