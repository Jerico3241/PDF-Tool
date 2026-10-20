"""Sprache der Oberfläche (seit 4.0 Beta 6): Deutsch oder Englisch – wählbar in den Einstellungen, Standard wie Windows.

Die Texte der App sind deutsch geschrieben. ``tr`` übersetzt einen fertigen Text zur Laufzeit ins Englische – über den
Katalog ``en.json``:

* ``exact``: ganze Texte (»Speichern« → »Save«)
* ``patterns``: Texte mit Platzhaltern ``{0}``, ``{1}`` … (»Seite {0} von {1}« → »Page {0} of {1}«). Was an der Stelle
  eines Platzhalters steht, wird seinerseits übersetzt (»{0} gespeichert« mit »2 Bilder« → »2 images saved«).
* Ohne Treffer: Text aus mehreren Sätzen oder Zeilen wird Satz für Satz übersetzt; sonst bleibt er, wie er ist –
  Dateinamen, Kundennamen und Inhalte der PDFs kommen nie im Katalog vor und bleiben deshalb unverändert.

In QML läuft jede Textbindung über ``I18n.tr(…, I18n.revision)`` (``revision`` ändert sich beim Umschalten: die Oberfläche
wechselt die Sprache sofort). Ergebnisse werden zwischengespeichert. Deutsch ist der Text selbst – ohne Aufwand.
"""

from __future__ import annotations

import json
import locale
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

LANGUAGES = ("de", "en")
CHOICES = ("system", "de", "en")  # Einstellung: wie Windows, Deutsch, Englisch
CATALOG = Path(__file__).resolve().parent / "en.json"
FORCE_VARIABLE = "PDFTOOL_SPRACHE"  # Tests und Diagnose: Sprache fest vorgeben (de, en)
MAX_DEPTH = 3
MAX_CHARS = 3000
_SENTENCES = re.compile(r"(?<=[.!?…:])\s+(?=[A-ZÄÖÜ»„(0-9])")
_PLACEHOLDER = re.compile(r"\{(\d+)\}")
# Ein Dateiname für sich (Tab, Liste): nie über Muster übersetzen (»Vertrag Müller.pdf« bleibt)
_FILE_NAME = re.compile(r"^[^\n:»«„“]{1,240}\.(?:pdf|xlsx|xlsm|xls|csv|docx?|pptx?|txt|png|jpe?g|webp|tiff?|bmp|gif|json|log|pfx|p12|pdtbackup)$", re.I)

_language = "de"


def system_language() -> str:
    """Sprache von Windows: Deutsch, wenn die Anzeigesprache Deutsch ist – sonst Englisch."""
    code = ""
    if sys.platform == "win32":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):  # type: ignore[attr-defined]
                code = buffer.value
            languages = ctypes.c_ulong(0)
            size = ctypes.c_ulong(0)
            # Anzeigesprache der Oberfläche (kann vom Gebietsschema abweichen)
            if ctypes.windll.kernel32.GetUserPreferredUILanguages(8, ctypes.byref(languages), None, ctypes.byref(size)) and size.value:  # type: ignore[attr-defined]
                names = ctypes.create_unicode_buffer(size.value)
                if ctypes.windll.kernel32.GetUserPreferredUILanguages(8, ctypes.byref(languages), names, ctypes.byref(size)):  # type: ignore[attr-defined]
                    code = names.value or code
        except (AttributeError, OSError):
            code = ""
    if not code:
        code = (locale.getlocale()[0] or os.environ.get("LANG") or "").replace("_", "-")
    return "de" if code.lower().startswith("de") else "en"


def resolve(choice: str | None) -> str:
    """Einstellung (system, de, en) → Sprache. ``PDFTOOL_SPRACHE`` hat Vorrang."""
    forced = os.environ.get(FORCE_VARIABLE, "").strip().lower()
    if forced in LANGUAGES:
        return forced
    if choice in LANGUAGES:
        return str(choice)
    return system_language()


def language() -> str:
    return _language


def set_language(code: str) -> None:
    global _language
    _language = code if code in LANGUAGES else "de"
    _translate.cache_clear()


@lru_cache(maxsize=1)
def catalog() -> tuple[dict[str, str], dict[str, list[tuple[re.Pattern, str, str]]]]:
    """Katalog laden: ganze Texte und Muster (Regulärer Ausdruck, Vorlage, Übersetzung), nach dem ersten Zeichen der
    Vorlage gruppiert (``""``: beginnt mit einem Platzhalter) – innerhalb einer Gruppe die genauesten zuerst."""
    try:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    exact = {str(k): str(v) for k, v in (data.get("exact") or {}).items() if v}
    patterns: dict[str, list[tuple[re.Pattern, str, str]]] = {}
    for source, target in sorted((data.get("patterns") or {}).items(), key=lambda item: -len(_PLACEHOLDER.sub("", item[0]))):
        if not target or len(re.findall(r"[A-Za-zÄÖÜäöüß]", _PLACEHOLDER.sub("", source))) < 2:
            continue  # nur Platzhalter: passte auf jeden Text
        parts = _PLACEHOLDER.split(source)
        regex = ""
        for index, part in enumerate(parts):
            regex += re.escape(part) if index % 2 == 0 else f"(?P<p{part}>.+?)"
        try:
            compiled = re.compile(f"^{regex}$", re.DOTALL)
        except re.error:
            continue
        key = "" if source.startswith("{") else source[0]
        patterns.setdefault(key, []).append((compiled, source, str(target)))
    return exact, patterns


def tr(text):
    """Text in der gewählten Sprache. Alles, was kein Text ist (Zahlen, ``None``), bleibt unverändert."""
    if _language == "de" or not isinstance(text, str) or not text.strip() or len(text) > MAX_CHARS:
        return text  # sehr lange Texte sind Inhalte (Antworten, Dokumenttext), keine Beschriftungen
    return _translate(text)


@lru_cache(maxsize=8000)
def _translate(text: str) -> str:
    return _lookup(text, 0)


def _lookup(text: str, depth: int) -> str:
    exact, patterns = catalog()
    found = exact.get(text)
    if found is not None:
        return found
    stripped = text.strip()
    if stripped != text and stripped:
        inner = _lookup(stripped, depth)
        if inner != stripped:
            start = text[: len(text) - len(text.lstrip())]
            end = text[len(text.rstrip()):]
            return start + inner + end
    if stripped and stripped[-1] in ".:!?" and stripped[:-1] in exact:  # Satzzeichen am Ende
        return text.replace(stripped, exact[stripped[:-1]] + stripped[-1], 1)
    if depth >= MAX_DEPTH or _FILE_NAME.match(stripped):
        return text
    for regex, _source, target in (*patterns.get(text[0], ()), *patterns.get("", ())):
        match = regex.match(text)
        if match is None:
            continue
        values = {name[1:]: _lookup(value, depth + 1) for name, value in match.groupdict().items()}
        return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), target)
    # Mehrere Zeilen oder Sätze: einzeln übersetzen
    for splitter in ("\n", None):
        pieces = text.split("\n") if splitter else _SENTENCES.split(text)
        if len(pieces) > 1:
            translated = [_lookup(piece, depth + 1) if piece.strip() else piece for piece in pieces]
            if translated != pieces:
                return ("\n" if splitter else " ").join(translated)
    return text
