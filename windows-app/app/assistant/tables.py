"""Tabellen für den KI-Assistenten (seit 5.0 Beta 8): Text der Blätter für Fragen, Auswertung einer Tabelle und ein
passendes Diagramm vorschlagen.

Kleine Sprachmodelle rechnen unzuverlässig. Deshalb rechnet Novadesk selbst (``profile``: Anzahl, Summe, Mittelwert,
kleinster und größter Wert je Zahlenspalte, häufigste Werte je Textspalte, Zeitraum bei Datumsspalten) und gibt dem
Modell diese Zahlen zusammen mit den ersten Zeilen; das Modell beschreibt nur, was auffällt. Auch das Diagramm wählt
zuerst eine feste Regel (``chart_rule``); das Modell begründet die Wahl nur noch in einem Satz.
"""

from __future__ import annotations

I18N_CALLS = ()  # Anweisungen an das Sprachmodell und Dokumentinhalt – keine Oberflächentexte (tools/i18n_extract.py)

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

ROW_LIMIT = 3000  # Zeilen je Blatt für Fragen
COL_LIMIT = 30
SAMPLE_ROWS = 25  # so viele Zeilen sieht das Modell bei der Auswertung
ANALYSIS_TOKENS = 700
CHART_TYPES = {"column": "Säulendiagramm", "bar": "Balkendiagramm", "line": "Liniendiagramm", "pie": "Kreisdiagramm", "area": "Flächendiagramm"}

_NUMBER = re.compile(r"^\s*([-+−]?)\s*(?:€|EUR|\$|CHF)?\s*([0-9][0-9.\s ']*(?:,[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\s*(%|€|EUR|\$|CHF|Stk\.?)?\s*$")
_DATE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*$")
_ISO = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")


_MONTHS = ("januar", "jänner", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember",
           "january", "february", "march", "may", "june", "july", "october", "december",
           "jan", "feb", "mär", "mrz", "apr", "jun", "jul", "aug", "sep", "sept", "okt", "nov", "dez", "mar", "oct", "dec")
_PERIOD = re.compile(r"^(?:(?:%s)\.?(?:\s+\d{2,4})?|q[1-4](?:\s*/?\s*\d{2,4})?|[1-4]\.\s*quartal(?:\s+\d{2,4})?|kw\s*\d{1,2}(?:\s*/?\s*\d{2,4})?)$"
                     % "|".join(_MONTHS), re.IGNORECASE)


def is_period(text: str) -> bool:
    """Monat, Quartal oder Kalenderwoche (»März«, »Mär 2026«, »Q3«, »2. Quartal«, »KW 12«) – Zeitpunkte als Text."""
    return bool(_PERIOD.match(" ".join(str(text or "").split())))


def number(text: str) -> float | None:
    """Zahl aus angezeigtem Text: »1.234,50 €«, »12,5 %«, »-3«, »1234.5«. Datumsangaben sind keine Zahlen."""
    text = str(text or "").strip()
    if not text or _DATE.match(text) or _ISO.match(text):
        return None
    match = _NUMBER.match(text)
    if not match:
        return None
    sign, digits = match.group(1), match.group(2).replace(" ", "").replace(" ", "").replace("'", "")
    if "," in digits:
        digits = digits.replace(".", "").replace(",", ".")
    elif digits.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", digits):
        digits = digits.replace(".", "")  # 1.234.567 bzw. 1.234 (Tausender)
    try:
        value = float(digits)
    except ValueError:
        return None
    return -value if sign in ("-", "−") else value


def day(text: str) -> date | None:
    text = str(text or "").strip()
    match = _DATE.match(text)
    try:
        if match:
            d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
            if y < 100:
                y += 2000 if y < 70 else 1900
            return date(y, m, d)
        match = _ISO.match(text)
        if match:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return None


def fmt(value: float) -> str:
    """Zahl in deutscher Schreibweise (höchstens zwei Nachkommastellen)."""
    if math.isfinite(value) and abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}".replace(",", ".")
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass
class Column:
    name: str
    kind: str  # zahl, datum, text, leer
    filled: int = 0
    stats: dict = field(default_factory=dict)

    def describe(self) -> str:
        if self.kind == "zahl":
            s = self.stats
            return (f"»{self.name}« (Zahlen, {self.filled} Werte): Summe {fmt(s['sum'])}, Mittelwert {fmt(s['mean'])}, "
                    f"kleinster {fmt(s['min'])} (Zeile {s['min_row']}), größter {fmt(s['max'])} (Zeile {s['max_row']})")
        if self.kind == "datum":
            return f"»{self.name}« (Datum, {self.filled} Werte): vom {self.stats['first']} bis {self.stats['last']}"
        if self.kind == "text":
            top = ", ".join(f"{value} ({count}×)" for value, count in self.stats.get("top", []))
            return f"»{self.name}« (Text, {self.filled} Werte, {self.stats.get('distinct', 0)} verschiedene): häufigste {top}"
        return f"»{self.name}« (leer)"


@dataclass
class Profile:
    columns: list[Column]
    rows: int  # Datenzeilen (ohne Kopfzeile)
    first_row: int  # Zeilennummer (1-basiert) der ersten Datenzeile
    header: bool

    @property
    def numeric(self) -> list[int]:
        return [index for index, column in enumerate(self.columns) if column.kind == "zahl"]

    def summary(self) -> str:
        lines = [f"{self.rows} Datenzeilen, {len(self.columns)} Spalten."]
        lines += [f"- {column.describe()}" for column in self.columns if column.kind != "leer"]
        return "\n".join(lines)


def _year(text: str) -> bool:
    value = number(text)
    return value is not None and float(value).is_integer() and 1900 <= value <= 2100 and "," not in text and "." not in text.strip()


def has_header(rows: list[list[str]]) -> bool:
    """Erste Zeile ist eine Kopfzeile: überwiegend Text (Jahreszahlen wie »2025« zählen als Überschrift), und darunter
    steht in einer ihrer Text-Spalten eine Zahl oder ein Datum – oder alle Einträge sind kurz und verschieden."""
    if len(rows) < 2:
        return False
    first = rows[0]
    filled = [index for index, cell in enumerate(first) if cell.strip()]
    if not filled:
        return False
    typed_head = [index for index in filled if (number(first[index]) is not None or day(first[index]) is not None) and not _year(first[index])]
    if len(typed_head) * 2 > len(filled):
        return False  # überwiegend Zahlen oder Daten: schon Daten
    below = rows[1:6]

    def typed(index: int) -> bool:
        return any(index < len(line) and (number(line[index]) is not None or day(line[index]) is not None) for line in below)

    if any(typed(index) for index in filled if index not in typed_head):
        return True
    values = [first[index].strip() for index in filled]
    return not typed_head and len(set(values)) == len(values) and all(len(value) <= 40 for value in values)


def profile(rows: list[list[str]], first_row: int = 1, header: bool | None = None) -> Profile:
    """Kennzahlen der Tabelle ``rows`` (angezeigte Texte; ``first_row`` ist die Zeilennummer der ersten Zeile)."""
    rows = [list(line[:COL_LIMIT]) for line in rows[:ROW_LIMIT + 1]]
    width = max((len(line) for line in rows), default=0)
    rows = [line + [""] * (width - len(line)) for line in rows]
    header = has_header(rows) if header is None else header
    names = [cell.strip() or f"Spalte {index + 1}" for index, cell in enumerate(rows[0])] if header and rows else [f"Spalte {index + 1}" for index in range(width)]
    data = rows[1:] if header else rows
    start = first_row + (1 if header else 0)
    columns = []
    for index in range(width):
        values = [(start + offset, line[index].strip()) for offset, line in enumerate(data) if line[index].strip()]
        if not values:
            columns.append(Column(names[index], "leer"))
            continue
        numbers = [(row, number(text)) for row, text in values]
        numbers = [(row, value) for row, value in numbers if value is not None]
        days = [d for d in (day(text) for _row, text in values) if d is not None]
        if len(numbers) >= max(1, 0.8 * len(values)):
            total = sum(value for _row, value in numbers)
            low = min(numbers, key=lambda item: item[1])
            high = max(numbers, key=lambda item: item[1])
            columns.append(Column(names[index], "zahl", len(numbers), {
                "sum": total, "mean": total / len(numbers), "min": low[1], "min_row": low[0], "max": high[1], "max_row": high[0]}))
        elif len(days) >= max(1, 0.8 * len(values)):
            columns.append(Column(names[index], "datum", len(days), {"first": min(days).strftime("%d.%m.%Y"), "last": max(days).strftime("%d.%m.%Y")}))
        else:
            counts = Counter(text for _row, text in values)
            columns.append(Column(names[index], "text", len(values), {"distinct": len(counts), "top": counts.most_common(4),
                                                                       "period": all(is_period(text) for _row, text in values)}))
    return Profile(columns, len(data), first_row, bool(header))


def sample(rows: list[list[str]], prof: Profile, limit: int = SAMPLE_ROWS) -> str:
    """Die ersten Zeilen als »Zeile N: Spalte: Wert; …« (so liest ein kleines Modell Tabellen am sichersten)."""
    data = rows[1:] if prof.header else rows
    start = prof.first_row + (1 if prof.header else 0)
    lines = []
    for offset, line in enumerate(data[:limit]):
        cells = [f"{prof.columns[i].name}: {value.strip()}" for i, value in enumerate(line[:len(prof.columns)]) if value.strip()]
        if cells:
            lines.append(f"Zeile {start + offset}: " + "; ".join(cells))
    return "\n".join(lines)


def sheet_page(name: str, rows: list[list[str]], first_row: int = 1) -> str:
    """Ein Blatt als Text für Fragen: je Zeile ein Absatz »Zeile N: Spalte: Wert; …« (mit Kopfzeile als Spaltennamen)."""
    rows = [list(line[:COL_LIMIT]) for line in rows[:ROW_LIMIT + 1]]
    if not rows:
        return ""
    prof = profile(rows, first_row)
    data = rows[1:] if prof.header else rows
    start = first_row + (1 if prof.header else 0)
    paragraphs = []
    for offset, line in enumerate(data):
        cells = [f"{prof.columns[i].name}: {value.strip()}" for i, value in enumerate(line) if i < len(prof.columns) and value.strip()]
        if cells:
            paragraphs.append(f"Zeile {start + offset}: " + "; ".join(cells))
    del name
    return "\n\n".join(paragraphs)


ANALYSIS_SYSTEM = (
    "Du bist der Assistent im Programm Novadesk und wertest Tabellen aus. Du bekommst Kennzahlen, die Novadesk genau "
    "berechnet hat, und die ersten Zeilen der Tabelle. Verwende nur diese Angaben und rechne nicht selbst nach – die "
    "Kennzahlen stimmen. Antworte auf Deutsch, sachlich und knapp."
)


def analysis_messages(prof: Profile, rows: list[list[str]], sheet: str = "", question: str = "") -> list[dict]:
    where = f" (Blatt »{sheet}«)" if sheet else ""
    task = question.strip() or (
        "Beschreibe in höchstens sechs Stichpunkten, was an dieser Tabelle auffällt: worum es geht, Größenordnungen, "
        "größte und kleinste Werte, häufige Einträge, Zeitraum. Schlage zum Schluss in einem Satz eine sinnvolle "
        "nächste Auswertung vor (etwa eine Pivot-Tabelle oder einen Filter)."
    )
    return [
        {"role": "system", "content": ANALYSIS_SYSTEM},
        {"role": "user", "content": (
            f"Kennzahlen der Tabelle{where}:\n<<<\n{prof.summary()}\n>>>\n\n"
            f"Erste Zeilen:\n<<<\n{sample(rows, prof)}\n>>>\n\nAuftrag: {task}"
        )},
    ]


@dataclass(frozen=True)
class ChartChoice:
    kind: str
    reason: str


def chart_rule(prof: Profile) -> ChartChoice | None:
    """Feste Regel für ein passendes Diagramm – ``None``, wenn die Tabelle keine Zahlen hat."""
    numeric = prof.numeric
    if not numeric:
        return None
    first = prof.columns[0] if prof.columns else None
    if first is not None and first.kind == "datum":
        return ChartChoice("line", "Die erste Spalte enthält Daten – ein Liniendiagramm zeigt den Verlauf über die Zeit.")
    if first is not None and first.kind == "text" and first.stats.get("period"):
        return ChartChoice("line", "Die erste Spalte nennt Monate oder Quartale – ein Liniendiagramm zeigt den Verlauf über die Zeit.")
    labels = first.stats.get("distinct", 0) if first is not None and first.kind == "text" else 0
    if first is not None and first.kind == "text" and len(numeric) == 1 and 2 <= labels <= 6 and prof.columns[numeric[0]].stats.get("min", 0) >= 0:
        return ChartChoice("pie", "Wenige Kategorien mit einer Zahlenspalte – ein Kreisdiagramm zeigt die Anteile am Ganzen.")
    if labels > 8 or (first is not None and first.kind == "text" and max((len(str(v)) for v, _c in first.stats.get("top", [])), default=0) > 18):
        return ChartChoice("bar", "Viele oder lange Bezeichnungen – waagerechte Balken bleiben gut lesbar.")
    if len(numeric) > 1:
        return ChartChoice("column", "Mehrere Zahlenspalten – ein Säulendiagramm vergleicht sie je Zeile nebeneinander.")
    return ChartChoice("column", "Ein Säulendiagramm vergleicht die Werte der Zeilen übersichtlich.")


def chart_messages(prof: Profile, choice: ChartChoice, sheet: str = "") -> list[dict]:
    where = f" auf dem Blatt »{sheet}«" if sheet else ""
    return [
        {"role": "system", "content": ANALYSIS_SYSTEM},
        {"role": "user", "content": (
            f"Kennzahlen der Tabelle{where}:\n<<<\n{prof.summary()}\n>>>\n\n"
            f"Novadesk schlägt dafür ein {CHART_TYPES[choice.kind]} vor. Erkläre in höchstens zwei Sätzen, was dieses "
            "Diagramm an genau diesen Daten zeigt (nenne die Spalten). Keine Einleitung."
        )},
    ]
