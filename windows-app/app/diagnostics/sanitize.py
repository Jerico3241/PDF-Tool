"""Texte für das Support-Paket entschärfen.

* ``anonymize``: Benutzerordner → ``%USERPROFILE%``, Benutzer- und Computername → Platzhalter,
  E-Mail-Adressen → ``<E-Mail>``. Für Angaben wie den Datenordner.
* ``redact``: zusätzlich jeder Pfad außerhalb von Programm- und Datenordner → ``<Pfad>`` (nur die
  Dateiendung bleibt, z. B. ``<Pfad>.xlsx``). Pfade zu Dokumenten enthalten oft Kunden- oder
  Firmennamen – sie gehören nie in ein Support-Paket. Für Protokolle.

Im Zweifel wird mehr entfernt als nötig.
"""

from __future__ import annotations

import getpass
import os
import platform
import re
from pathlib import Path

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PART = r"[^\\/\n\r\t\"'<>|*?„“”:]"
# Laufwerk (C:\…) oder Netzwerkpfad (\\server\…), danach beliebig viele Teile – auch mit Leerzeichen
_WINDOWS_PATH = re.compile(rf"(?:\b[A-Za-z]:|\\\\{_PART}+)(?:[\\/]{_PART}*)+")
_PROFILE_PATH = re.compile(rf"%USERPROFILE%(?:[\\/]{_PART}*)+", re.IGNORECASE)
_POSIX_PATH = re.compile(rf"(?<![\w<>%])/(?:home|Users|tmp|mnt|media|var|private|root|srv|opt)(?:/{_PART}*)+")
# Gekürzte Pfade der Protokolle (»…\\Liste Muster GmbH.xlsx«)
_SHORT_PATH = re.compile(rf"…[\\/]{_PART}*")
# Dateinamen von Dokumenten – auch mit Leerzeichen (»Muster GmbH 2026.xlsx«)
_DOCUMENT = re.compile(r"(?:[^\s\\/\"'<>|*?:„“”]+ ){0,6}[^\s\\/\"'<>|*?:„“”]+\.(?:pdf|xlsx|xlsm|xls|csv|png|jpe?g|gif|bmp|tiff?|docx?)\b", re.IGNORECASE)
_EXTENSION = re.compile(r"\.(pdf|xlsx|xlsm|xls|csv|json|log|png|jpe?g|gif|bmp|svg|pdtbackup|zip|exe|msi|py|qml|txt|tmp|ico|bak)\b", re.IGNORECASE)
_WORD = re.compile(r"\w+")


class _Terms:
    """Viele bekannte Begriffe (z. B. Firmennamen) in einem Durchgang ersetzen – ohne Rücksicht auf
    Groß-/Kleinschreibung, nur als ganze Wörter. Auch bei tausenden Begriffen und großen
    Protokollen schnell (Index über das erste Wort statt eines riesigen regulären Ausdrucks)."""

    def __init__(self, terms) -> None:
        self.index: dict[str, list[tuple[str, int]]] = {}
        for term in {str(t).strip() for t in terms if t and len(str(t).strip()) >= 3}:
            first = _WORD.search(term)
            if first is None:
                continue
            self.index.setdefault(first.group(0).lower(), []).append((term.lower(), first.start()))
        for entries in self.index.values():
            entries.sort(key=lambda entry: len(entry[0]), reverse=True)

    def sub(self, text: str, placeholder: str) -> str:
        if not self.index:
            return text
        lower = text.lower()
        if len(lower) != len(text):  # sehr seltene Sonderzeichen: Vergleich ohne Positionsfehler unmöglich
            lower = "".join(ch.lower() if len(ch.lower()) == 1 else ch for ch in text)
        out: list[str] = []
        pos = 0
        for match in _WORD.finditer(lower):
            entries = self.index.get(match.group(0))
            if not entries or match.start() < pos:
                continue
            for term, offset in entries:
                begin = match.start() - offset
                end = begin + len(term)
                if begin < pos or lower[begin:end] != term:
                    continue
                if (begin > 0 and term[0].isalnum() and lower[begin - 1].isalnum()) or (end < len(lower) and term[-1].isalnum() and lower[end].isalnum()):
                    continue
                out.append(text[pos:begin])
                out.append(placeholder)
                pos = end
                break
        out.append(text[pos:])
        return "".join(out)


def _variants(path: str) -> list[str]:
    text = str(path).rstrip("\\/")
    if not text:
        return []
    return sorted({text, text.replace("\\", "/"), text.replace("/", "\\")}, key=len, reverse=True)


class Sanitizer:
    def __init__(
        self,
        install_dir: str | os.PathLike | None = None,
        data_dir: str | os.PathLike | None = None,
        profile: str | None = None,
        user: str | None = None,
        computer: str | None = None,
    ) -> None:
        self.install = _variants(str(install_dir)) if install_dir else []
        self.data = _variants(str(data_dir)) if data_dir else []
        profile = profile if profile is not None else os.environ.get("USERPROFILE") or str(Path.home())
        self.profile = _variants(profile) if profile and len(profile.strip("\\/")) > 3 else []
        try:
            user = user if user is not None else getpass.getuser()
        except Exception:  # noqa: BLE001
            user = ""
        computer = computer if computer is not None else platform.node()
        self.names = [(name, placeholder) for name, placeholder in ((user, "<Benutzer>"), (computer, "<Computer>")) if name and len(name) >= 3]
        self.terms = _Terms(())

    def add_terms(self, terms) -> None:
        """Bekannte Angaben aus den eigenen Daten (Firmen, Kundennummern …) – werden zu »<Kunde>«."""
        self.terms = _Terms([*(t for entries in self.terms.index.values() for t, _o in entries), *terms])

    @staticmethod
    def _replace(text: str, values: list[str], placeholder: str) -> str:
        for value in values:
            text = re.sub(re.escape(value), lambda _m: placeholder, text, flags=re.IGNORECASE)
        return text

    def _names(self, text: str) -> str:
        for name, placeholder in self.names:
            text = re.sub(rf"(?<![\w]){re.escape(name)}(?![\w])", lambda _m: placeholder, text, flags=re.IGNORECASE)
        return text

    def anonymize(self, text: str) -> str:
        text = str(text)
        text = self._replace(text, self.profile, "%USERPROFILE%")
        text = _EMAIL.sub("<E-Mail>", text)
        return self._names(text)

    @staticmethod
    def _path(match: re.Match) -> str:
        found = list(_EXTENSION.finditer(match.group(0)))
        return "<Pfad>" + (found[-1].group(0).lower() if found else "")

    @staticmethod
    def _document(match: re.Match) -> str:
        found = list(_EXTENSION.finditer(match.group(0)))
        return "<Datei>" + (found[-1].group(0).lower() if found else "")

    def redact(self, text: str) -> str:
        text = str(text)
        text = self._replace(text, self.install, "<Programmordner>")
        text = self._replace(text, self.data, "<Datenordner>")
        text = self._replace(text, self.profile, "%USERPROFILE%")
        text = _EMAIL.sub("<E-Mail>", text)  # vor den Begriffen: Adressen bleiben als solche erkennbar
        text = _PROFILE_PATH.sub(self._path, text)
        text = _WINDOWS_PATH.sub(self._path, text)
        text = _POSIX_PATH.sub(self._path, text)
        text = _SHORT_PATH.sub(self._path, text)
        text = _DOCUMENT.sub(self._document, text)
        text = self.terms.sub(text, "<Kunde>")  # was als freier Text bleibt (Firmen, Kundennummern)
        return self._names(text)


# Werte der Einstellungen, die nie persönlich sind (Auswahl aus festen Werten, Versionen)
SAFE_TEXT_KEYS = frozenset({"theme", "accent", "animationsprofil", "format", "gesehen", "update_kanal", "kanal", "kundenakte_modus", "stapel_konflikt", "stapel_kunden", "sortierung",
                            "reader_zoom_beim_oeffnen", "reader_leiste_beim_oeffnen"})


def anonymize_config(cfg: dict) -> dict:
    """Einstellungen ohne persönliche Inhalte: Schalter und Zahlen bleiben, Texte und Pfade werden
    zu »<Text>«, Listen zu ihrer Anzahl (keine Namen, Firmen, E-Mail-Adressen, Kopf- oder Fußzeilen)."""
    result: dict = {}
    for key in sorted(cfg, key=str):
        value = cfg[key]
        if value is None or isinstance(value, (bool, int, float)):
            result[key] = value
        elif isinstance(value, str):
            if key in SAFE_TEXT_KEYS and len(value) <= 40 and not _EMAIL.search(value):
                result[key] = value
            else:
                result[key] = "<Text>" if value.strip() else ""
        elif isinstance(value, list):
            result[key] = f"<Liste mit {len(value)} {'Eintrag' if len(value) == 1 else 'Einträgen'}>"
        elif isinstance(value, dict):
            result[key] = f"<{len(value)} {'Angabe' if len(value) == 1 else 'Angaben'}>"
        else:
            result[key] = f"<{type(value).__name__}>"
    return result


def sensitive_terms(data_dir: str | os.PathLike) -> list[str]:
    """Angaben aus den eigenen Daten, die nie in ein Support-Paket gehören: Firmen, Kundennummern,
    E-Mail-Adressen der Kundenakten, Dateinamen und Angaben des Stapels, zuletzt verwendete Angaben."""
    from storage import read_json

    root = Path(data_dir)
    terms: set[str] = set()

    def add(value, minimum: int = 3) -> None:
        if isinstance(value, str) and len(value.strip()) >= minimum:
            terms.add(value.strip())

    def add_path(value) -> None:
        if isinstance(value, str) and value.strip():
            name = Path(value.replace("\\", "/")).name
            add(name)
            add(Path(name).stem)

    data, _reason = read_json(root / "kundenakten.json")
    for customer in (data or {}).get("customers") or [] if isinstance(data, dict) else []:
        if isinstance(customer, dict):
            add(customer.get("company"))
            add(customer.get("number"), 4)
            for email in customer.get("emails") or []:
                add(email)
            for key in ("last_excel", "last_pdf", "logo"):
                add_path(customer.get(key))
    data, _reason = read_json(root / "stapel.json")
    for item in (data or {}).get("eintraege") or [] if isinstance(data, dict) else []:
        if isinstance(item, dict):
            add_path(item.get("path"))
            overrides = item.get("overrides") if isinstance(item.get("overrides"), dict) else {}
            add(overrides.get("company"))
            add(overrides.get("number"), 4)
            add(overrides.get("email"))
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            add_path(result.get("output"))
    data, _reason = read_json(root / "gui-config.json")
    if isinstance(data, dict):
        add(data.get("firma"))
        add(data.get("kd"), 4)
        add(data.get("mail"))
        add_path(data.get("excel"))
        for entry in data.get("pdfs") or []:
            add_path(entry if isinstance(entry, str) else (entry or {}).get("pfad") if isinstance(entry, dict) else None)
    return sorted(terms, key=len, reverse=True)
