"""Dritte, tolerante Engine: pypdf (BSD-3-Clause) mit ``strict=False``.

pypdf hat eigene Wiederherstellungsregeln – andere als qpdf und PDFium. Lesbare Seiten
werden in eine neue PDF übertragen; wenn möglich mit dem ganzen Dokument (Formulare,
Lesezeichen, Links, Metadaten), sonst Seite für Seite. Dem Ergebnis wird nicht
vertraut: Es wird danach mit qpdf normalisiert und hart geprüft.

Meldungen von pypdf landen im technischen Protokoll (ohne Inhalte der PDF).
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path

MAX_MESSAGES = 40


@dataclass
class LenientResult:
    pages: int
    total: int
    whole_document: bool  # Dokument vollständig geklont (Formulare, Lesezeichen, Metadaten)
    lost: list[str] = field(default_factory=list)


class _Collect(logging.Handler):
    def __init__(self, into: list[str]) -> None:
        super().__init__(logging.WARNING)
        self.into = into

    def emit(self, record: logging.LogRecord) -> None:
        if len(self.into) < MAX_MESSAGES:
            self.into.append(f"pypdf: {record.getMessage()[:200]}")


def available() -> bool:
    import importlib.util

    return importlib.util.find_spec("pypdf") is not None


def recover(path: str | Path, target: str | Path, password: str | None, technical: list[str]) -> LenientResult | None:
    """Lesbare Seiten mit pypdf in ``target`` schreiben. ``None``: pypdf kann die Datei nicht lesen."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        technical.append("pypdf ist nicht verfügbar")
        return None
    logger = logging.getLogger("pypdf")
    handler = _Collect(technical)
    logger.addHandler(handler)
    propagate, logger.propagate = logger.propagate, False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reader = PdfReader(str(path), strict=False)
            if reader.is_encrypted and (not password or not reader.decrypt(password)):
                technical.append("pypdf: verschlüsselt, Passwort fehlt oder wird nicht unterstützt")
                return None
            total = len(reader.pages)
            if total <= 0:
                technical.append("pypdf: keine Seiten gefunden")
                return None
            whole = True
            try:
                writer = PdfWriter(clone_from=reader)
                kept = len(writer.pages)
            except Exception as exc:  # noqa: BLE001 - Dokument lässt sich nicht als Ganzes übernehmen
                technical.append(f"pypdf: Dokument nicht vollständig übertragbar ({type(exc).__name__}) – Seite für Seite")
                whole = False
                writer = PdfWriter()
                kept = 0
                for index in range(total):
                    try:
                        writer.add_page(reader.pages[index])
                        kept += 1
                    except Exception as page_exc:  # noqa: BLE001
                        technical.append(f"pypdf: Seite {index + 1} nicht übertragbar ({type(page_exc).__name__})")
            if kept <= 0:
                return None
            with open(target, "wb") as handle:
                writer.write(handle)
    except Exception as exc:  # noqa: BLE001 - jede Störung: diese Stufe liefert nichts
        technical.append(f"pypdf: Datei nicht lesbar ({type(exc).__name__}: {str(exc)[:160]})")
        return None
    finally:
        logger.removeHandler(handler)
        logger.propagate = propagate
    lost = [] if whole else ["Lesezeichen und Formularfelder wurden möglicherweise nicht vollständig übernommen."]
    return LenientResult(kept, total, whole, lost)
