"""PDF-Formular mit KI ausfüllen (seit 5.0 Beta 8).

Der Benutzer gibt die Angaben als freien Text an (eingetippt, eingefügt oder aus einer Datei). Das Sprachmodell
bekommt die Felder des Formulars – Name, Beschriftung neben dem Feld, Art, erlaubte Werte – und ordnet die Angaben zu.
Die Antwort ist JSON (llama-server erzwingt das mit ``response_format``); ``parse_json`` liest sie trotzdem tolerant.
``normalize`` prüft jeden Wert gegen das Feld: Auswahlfelder nur mit erlaubten Werten, Kontrollkästchen nur ja/nein,
Höchstlängen werden eingehalten. Nichts wird ohne Vorschau eingetragen – der Benutzer sieht jeden Vorschlag und wählt.
"""

from __future__ import annotations

I18N_CALLS = ()  # Anweisungen an das Sprachmodell und Dokumentinhalt – keine Oberflächentexte (tools/i18n_extract.py)

import json
import re
from dataclasses import dataclass

MAX_FIELDS = 120
MAX_DATA_CHARS = 8000
FILL_TOKENS = 1600
TRUE_WORDS = {"ja", "yes", "true", "wahr", "x", "1", "an", "ein", "on", "angekreuzt", "zutreffend", "checked", "y", "j"}
FALSE_WORDS = {"nein", "no", "false", "falsch", "0", "aus", "off", "", "nicht zutreffend", "n"}

SYSTEM = (
    "Du füllst im Programm Novadesk ein PDF-Formular aus. Du bekommst die Felder des Formulars und die Angaben des "
    "Benutzers. Trage in jedes Feld nur ein, was eindeutig aus den Angaben hervorgeht – erfinde nichts. Felder, zu denen "
    "die Angaben nichts sagen, lässt du weg. Antworte nur mit einem JSON-Objekt: Schlüssel ist die Nummer des Feldes "
    "(als Text, etwa \"3\"), Wert ist der einzutragende Text; bei Kontrollkästchen true oder false; bei Feldern mit "
    "erlaubten Werten genau einer dieser Werte. Datumsangaben im Format TT.MM.JJJJ, sofern das Feld nichts anderes "
    "verlangt."
)


@dataclass(frozen=True)
class Field:
    key: str
    name: str
    kind: str  # text, checkbox, radio, combo, list
    label: str = ""  # Beschriftung (Tooltip oder Text neben dem Feld)
    options: tuple[tuple[str, str], ...] = ()  # (Wert, Anzeige)
    max_length: int = 0
    multiline: bool = False
    value: str | bool = ""

    @property
    def title(self) -> str:
        """Für die Anzeige: Beschriftung, sonst der lesbare Teil des Namens."""
        if self.label:
            return self.label
        name = self.name.rsplit(".", 1)[-1]
        name = re.sub(r"\[\d+\]$", "", name)
        return re.sub(r"[_]+", " ", name).strip() or self.name


@dataclass(frozen=True)
class Proposal:
    key: str
    title: str
    value: str | bool
    display: str  # wie in der Vorschau gezeigt (»Ja«, Anzeige einer Auswahl)
    current: str | bool = ""


def describe(fields: list[Field]) -> str:
    """Felder für das Modell: »3: Vorname (Textfeld, höchstens 30 Zeichen)« bzw. mit erlaubten Werten."""
    lines = []
    for number, item in enumerate(fields[:MAX_FIELDS], start=1):
        label = item.title
        if item.label and item.name and item.label != item.name:
            label = f"{item.label} [Feldname {item.name}]"
        if item.kind == "checkbox":
            kind = "Kontrollkästchen, true oder false"
        elif item.kind in ("radio", "combo", "list"):
            allowed = ", ".join(f"\"{display or value}\"" for value, display in item.options) or "–"
            kind = f"Auswahl, erlaubte Werte: {allowed}"
        else:
            kind = "Textfeld" + (", mehrzeilig" if item.multiline else "") + (f", höchstens {item.max_length} Zeichen" if item.max_length else "")
        lines.append(f"{number}: {label} ({kind})")
    return "\n".join(lines)


def messages(fields: list[Field], data: str) -> list[dict]:
    data = str(data or "").strip()[:MAX_DATA_CHARS]
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Felder des Formulars:\n<<<\n{describe(fields)}\n>>>\n\nAngaben des Benutzers:\n<<<\n{data}\n>>>"},
    ]


def parse_json(answer: str) -> dict:
    """JSON-Objekt aus der Antwort – auch mit Text oder Markdown-Zaun drumherum. Kein Objekt: leeres ``dict``."""
    text = str(answer or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        # häufige Fehler kleiner Modelle: Komma vor »}«, einfache Anführungszeichen
        repaired = re.sub(r",\s*}", "}", text[start:end + 1])
        try:
            data = json.loads(repaired)
        except ValueError:
            return {}
    return data if isinstance(data, dict) else {}


def _match_option(field: Field, value: str) -> str | None:
    wanted = " ".join(str(value).split()).casefold()
    if not wanted:
        return None
    for export, display in field.options:
        if wanted in (export.casefold(), (display or "").casefold(), export.lstrip("/").casefold()):
            return export
    for export, display in field.options:  # »Herr« passt zu »Herr Dr.«? nur eindeutig
        label = (display or export).lstrip("/").casefold()
        if label.startswith(wanted) or wanted.startswith(label):
            return export
    return None


def normalize(field: Field, value) -> tuple[str | bool, str] | None:
    """Wert für ``field`` prüfen und umwandeln: (Wert, Anzeige) oder ``None`` (passt nicht oder leer)."""
    if value is None:
        return None
    if field.kind == "checkbox":
        if isinstance(value, bool):
            flag = value
        else:
            word = " ".join(str(value).split()).casefold()
            if word in TRUE_WORDS:
                flag = True
            elif word in FALSE_WORDS:
                flag = False
            else:
                return None
        return flag, "Ja" if flag else "Nein"
    if isinstance(value, (list, dict)):
        return None
    if isinstance(value, bool):
        value = "Ja" if value else "Nein"
    text = " ".join(str(value).split()) if not field.multiline else str(value).strip()
    if not text:
        return None
    if field.kind in ("radio", "combo", "list") and field.options:
        export = _match_option(field, text)
        if export is None:
            return None
        display = dict(field.options).get(export) or export.lstrip("/")
        return export, display
    if field.max_length and len(text) > field.max_length:
        text = text[: field.max_length]
    return text, text


def proposals(fields: list[Field], answer: dict) -> list[Proposal]:
    """Vorschläge aus der Antwort des Modells (Schlüssel: Nummer des Feldes oder sein Name)."""
    by_number = {str(number): item for number, item in enumerate(fields[:MAX_FIELDS], start=1)}
    by_name = {item.name: item for item in fields}
    result: dict[str, Proposal] = {}
    for key, value in answer.items():
        item = by_number.get(str(key).strip()) or by_name.get(str(key))
        if item is None or item.key in result:
            continue
        checked = normalize(item, value)
        if checked is None:
            continue
        new, display = checked
        if new == item.value or (isinstance(new, str) and not new.strip()):
            continue
        result[item.key] = Proposal(item.key, item.title, new, display, item.value)
    order = {item.key: index for index, item in enumerate(fields)}
    return sorted(result.values(), key=lambda proposal: order.get(proposal.key, 0))


def schema(fields: list[Field]) -> dict:
    """JSON-Schema für ``response_format``: nur bekannte Feldnummern, alle optional."""
    properties = {}
    for number, item in enumerate(fields[:MAX_FIELDS], start=1):
        if item.kind == "checkbox":
            properties[str(number)] = {"type": "boolean"}
        else:
            properties[str(number)] = {"type": "string"}
    return {"type": "object", "properties": properties, "additionalProperties": False}
