"""Präsentation mit KI erstellen (seit 5.0 Beta 8): aus einem Thema oder aus dem Text eines Dokuments.

Das Sprachmodell schreibt nur die Gliederung in einem einfachen Zeilenformat (``OUTLINE_FORMAT``) – das gelingt auch
kleinen Modellen zuverlässig, anders als JSON. ``parse`` liest sie tolerant (auch Markdown-Überschriften und
nummerierte Folien) und ``write_fodp`` baut daraus eine Präsentation im Design der Vorlage »Projektvorstellung«
(Titelfolie mit Verlauf, Inhaltsfolien mit Stichpunkten, Notizen für den Vortrag). Novadesk öffnet sie als neues,
noch nicht gespeichertes Dokument.
"""

from __future__ import annotations

I18N_CALLS = ()  # Anweisungen an das Sprachmodell und Dokumentinhalt – keine Oberflächentexte (tools/i18n_extract.py)

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

MIN_SLIDES, MAX_SLIDES, DEFAULT_SLIDES = 3, 15, 7
MAX_BULLETS = 6
MAX_TOPIC = 1500
SOURCE_CHARS = 12000  # so viel Dokumenttext liest das Modell für die Gliederung (längere: erst Stichpunkte je Teil)
OUTLINE_TOKENS = 1400
TEMPERATURE = 0.5
TEMPLATE = Path(__file__).resolve().parents[1] / "vorlagen" / "projektvorstellung.fodp"

SYSTEM = (
    "Du bist die Präsentationshilfe im Programm Novadesk. Du schreibst die Gliederung einer Präsentation genau im "
    "verlangten Format und sonst nichts – keine Einleitung, keine Erklärung, kein Markdown."
)
OUTLINE_FORMAT = (
    "Format (jede Angabe in einer eigenen Zeile):\n"
    "TITEL: Titel der Präsentation\n"
    "UNTERTITEL: ein kurzer Satz, worum es geht\n"
    "FOLIE: Überschrift der Folie\n"
    "- Stichpunkt\n"
    "- Stichpunkt\n"
    "NOTIZ: ein bis zwei Sätze, was der Vortragende dazu sagt\n"
    "(dann die nächste FOLIE …)"
)


@dataclass
class Slide:
    title: str
    bullets: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Outline:
    title: str = ""
    subtitle: str = ""
    slides: list[Slide] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return bool(self.title or self.slides) and any(slide.bullets for slide in self.slides)


def clamp(count: int) -> int:
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = DEFAULT_SLIDES
    return max(MIN_SLIDES, min(MAX_SLIDES, count))


def topic_messages(topic: str, count: int, audience: str = "") -> list[dict]:
    topic = " ".join(str(topic or "").split())[:MAX_TOPIC]
    count = clamp(count)
    who = f" Zielgruppe: {audience.strip()}." if audience.strip() else ""
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": (
            f"Erstelle die Gliederung einer Präsentation zum Thema: {topic}.{who}\n"
            f"Genau {count} Inhaltsfolien (ohne Titelfolie), je Folie drei bis fünf kurze Stichpunkte mit höchstens "
            "zwölf Wörtern. Sprache: wie das Thema (sonst Deutsch). Erfinde keine konkreten Zahlen, Namen oder Daten.\n\n"
            + OUTLINE_FORMAT
        )},
    ]


def document_messages(text: str, count: int, name: str = "") -> list[dict]:
    """Gliederung aus dem Text eines Dokuments (oder aus Stichpunkten seiner Teile)."""
    count = clamp(count)
    source = f" »{name}«" if name else ""
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": (
            f"Inhalt des Dokuments{source}:\n<<<\n{text.strip()[:SOURCE_CHARS + 2000]}\n>>>\n\n"
            f"Erstelle daraus die Gliederung einer Präsentation mit genau {count} Inhaltsfolien (ohne Titelfolie), je "
            "Folie drei bis fünf kurze Stichpunkte mit höchstens zwölf Wörtern. Nimm nur Inhalte aus dem Dokument; "
            "Zahlen, Beträge und Daten genau wie dort. Sprache: wie das Dokument.\n\n" + OUTLINE_FORMAT
        )},
    ]


_KEY = re.compile(r"^\s*(?:[#*>\s]*)(TITEL|TITLE|UNTERTITEL|SUBTITLE|FOLIE|SLIDE|NOTIZ|NOTIZEN|NOTE|NOTES)\s*(?:\d+\s*)?[:：.\-–]\s*(.*)$", re.IGNORECASE)
_HEADING = re.compile(r"^\s*(#{1,3})\s+(.*)$")
_NUMBERED = re.compile(r"^\s*(?:Folie|Slide)\s+\d+\s*[:.\-–]?\s*(.*)$", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•–·]|\d+[.)])\s+(.*)$")


def _tidy(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), str(text or ""))
    text = text.strip().strip("*_ ").strip()
    if len(text) >= 2 and text[0] in "\"»„“" and text[-1] in "\"«“”":
        text = text[1:-1].strip()
    return re.sub(r"\s+", " ", text)


def parse(answer: str, count: int | None = None) -> Outline:
    """Gliederung aus der Antwort des Modells. Mehr als ``count`` (bzw. ``MAX_SLIDES``) Folien werden abgeschnitten,
    Stichpunkte je Folie auf ``MAX_BULLETS`` begrenzt; leere Folien fallen weg."""
    outline = Outline()
    current: Slide | None = None
    explicit = False  # Titel aus »TITEL:« (eine Zeile davor war nur ein Ersatz)
    for raw in str(answer or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        key = _KEY.match(line)
        if key:
            name, value = key.group(1).upper(), _tidy(key.group(2))
            if name in ("TITEL", "TITLE"):
                if not explicit and current is None:
                    outline.title, explicit = value, True
                elif value:  # zweiter Titel: eine Folie
                    current = Slide(value)
                    outline.slides.append(current)
            elif name in ("UNTERTITEL", "SUBTITLE"):
                outline.subtitle = outline.subtitle or value
            elif name in ("FOLIE", "SLIDE"):
                current = Slide(value or f"Folie {len(outline.slides) + 1}")
                outline.slides.append(current)
            elif current is not None and value:
                current.notes = f"{current.notes} {value}".strip()
            continue
        heading = _HEADING.match(line) or _NUMBERED.match(line)
        if heading:
            text = _tidy(heading.group(heading.lastindex))
            level = len(heading.group(1)) if heading.re is _HEADING else 2
            if level == 1 and not outline.title and not outline.slides:
                outline.title = text
            elif text:
                current = Slide(text)
                outline.slides.append(current)
            continue
        bullet = _BULLET.match(line)
        if bullet and current is not None:
            text = _tidy(bullet.group(1))
            if text and len(current.bullets) < MAX_BULLETS:
                current.bullets.append(text)
            continue
        if current is not None and current.bullets and not current.notes and len(line) > 30 and not line.endswith(":"):
            continue  # Fließtext zwischen den Folien (Erklärungen des Modells) bleibt weg
        if line.endswith(":"):
            continue  # »Hier ist die Gliederung:«
        if not outline.title and not outline.slides:
            outline.title = _tidy(line)
        elif not outline.subtitle and not outline.slides:
            outline.subtitle = _tidy(line)
    outline.slides = [slide for slide in outline.slides if slide.title or slide.bullets]
    limit = clamp(count) if count else MAX_SLIDES
    outline.slides = outline.slides[:limit]
    if not outline.title and outline.slides:
        outline.title = outline.slides[0].title
    outline.title = outline.title[:120]
    outline.subtitle = outline.subtitle[:200]
    return outline


# Präsentation schreiben ------------------------------------------------------------------------------------------
def _frame(style: str, x: float, y: float, w: float, h: float, paragraphs: str, *, presentation: str = "") -> str:
    cls = f' presentation:class="{presentation}"' if presentation else ""
    return (f'<draw:frame draw:style-name="{style}"{cls} svg:x="{x}cm" svg:y="{y}cm" svg:width="{w}cm" svg:height="{h}cm">'
            f"<draw:text-box>{paragraphs}</draw:text-box></draw:frame>")


def _p(text: str, style: str) -> str:
    return f'<text:p text:style-name="{style}">{escape(text)}</text:p>'


def _notes(text: str) -> str:
    if not text.strip():
        return ""
    # eigene Vorlage »notiz« ohne Füllung und Rahmen – ohne sie zeichnet LibreOffice das Notizfeld blau gefüllt
    return ('<presentation:notes><draw:frame draw:style-name="notiz" presentation:class="notes" svg:x="2cm" svg:y="14cm" '
            f'svg:width="17cm" svg:height="10cm"><draw:text-box><text:p text:style-name="notiztext">{escape(text.strip())}</text:p>'
            "</draw:text-box></draw:frame>"
            "</presentation:notes>")


def _bullet_size(slide: Slide) -> str:
    """Viele oder lange Stichpunkte: kleinere Schrift, damit alles auf die Folie passt."""
    chars = sum(len(item) for item in slide.bullets)
    if len(slide.bullets) >= 6 or chars > 420:
        return "text-klein"
    return "text"


def write_fodp(outline: Outline, target: str | Path, *, template: Path = TEMPLATE) -> Path:
    """Gliederung als OpenDocument-Präsentation in einer Datei (.fodp) im Design der Vorlage »Projektvorstellung«."""
    source = template.read_text(encoding="utf-8")
    head = source[: source.index("<office:body>")]
    # zusätzliche Absatzvorlage für volle Folien (kleinere Schrift)
    extra = ('<style:style style:name="text-klein" style:family="paragraph"><style:paragraph-properties fo:text-align="start" '
             'fo:margin-bottom="0.18cm"/><style:text-properties style:font-name="Calibri" fo:font-size="15pt" fo:color="#242424"/>'
             "</style:style>"
             '<style:style style:name="notiz" style:family="graphic"><style:graphic-properties draw:fill="none" draw:stroke="none"/>'
             "</style:style>"
             '<style:style style:name="notiztext" style:family="paragraph"><style:text-properties style:font-name="Calibri" '
             'fo:font-size="12pt" fo:color="#242424"/></style:style>')
    head = head.replace("</office:automatic-styles>", extra + "</office:automatic-styles>", 1)
    title = outline.title or "Präsentation"
    head = re.sub(r"<dc:title>.*?</dc:title>", f"<dc:title>{escape(title)}</dc:title>", head, count=1)
    pages = []
    subtitle = _p(outline.subtitle, "unter") if outline.subtitle else ""
    pages.append(
        '<draw:page draw:name="Titel" draw:style-name="dunkel" draw:master-page-name="Novadesk">'
        + _frame("mitte", 1.6, 4.0, 24.4, 3.6, _p(title, "gross"))
        + '<draw:rect draw:style-name="leiste" svg:x="1.8cm" svg:y="7.6cm" svg:width="4cm" svg:height="0.15cm"/>'
        + (_frame("rahmen", 1.6, 7.9, 24.4, 2.6, subtitle) if subtitle else "")
        + "</draw:page>"
    )
    used: set[str] = {"Titel"}
    for number, slide in enumerate(outline.slides, start=1):
        name = _unique((slide.title or f"Folie {number + 1}")[:60], used)
        style = _bullet_size(slide)
        items = "".join(f"<text:list-item>{_p(item, style)}</text:list-item>" for item in slide.bullets)
        body = f'<text:list text:style-name="punkte">{items}</text:list>' if items else ""
        pages.append(
            f'<draw:page draw:name="{escape(name, {chr(34): "&quot;"})}" draw:style-name="hell" draw:master-page-name="Novadesk">'
            + _frame("rahmen", 1.6, 0.9, 24.8, 1.8, _p(slide.title, "titel"))
            + (_frame("rahmen", 1.6, 3.0, 24.8, 11.4, body) if body else "")
            + _notes(slide.notes)
            + "</draw:page>"
        )
    document = head + "<office:body><office:presentation>" + "".join(pages) + "</office:presentation></office:body></office:document>\n"
    target = Path(target)
    target.write_text(document, encoding="utf-8")
    return target


def _unique(name: str, used: set[str]) -> str:
    """Folien brauchen eindeutige Namen (sonst benennt LibreOffice sie um)."""
    base = name.strip() or "Folie"
    candidate, number = base, 2
    while candidate in used:
        candidate = f"{base} ({number})"
        number += 1
    used.add(candidate)
    return candidate
