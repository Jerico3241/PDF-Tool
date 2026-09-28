"""Schriften für formatierte Kopf- und Fußzeilen in der PDF.

* Standard-PDF-Schriften, immer verfügbar: Helvetica, Times, Courier
* Windows-Schriften, falls installiert: Arial, Calibri, Segoe UI, Times New Roman

Windows-Schriften werden zur Laufzeit aus dem Schriftenordner geladen und als
Teilmenge in die PDF eingebettet – weder das Repository noch das Setup enthält
Schriftdateien. Eine Familie wird nur verwendet, wenn alle vier Schnitte
(normal, fett, kursiv, fett kursiv) vorhanden sind; sonst greift die passende
Standard-PDF-Schrift. Fettschrift ist damit immer ein echter Schnitt, nie eine
künstlich verstärkte Darstellung.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

BASE_FONTS: dict[str, tuple[str, str, str, str]] = {
    # normal, fett, kursiv, fett kursiv
    "Helvetica": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "Times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "Courier": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}
SYSTEM_FONTS: dict[str, tuple[str, tuple[str, str, str, str]]] = {
    # Familie: (Ersatz, Dateien normal/fett/kursiv/fett kursiv)
    "Arial": ("Helvetica", ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")),
    "Calibri": ("Helvetica", ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf")),
    "Segoe UI": ("Helvetica", ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf")),
    "Times New Roman": ("Times", ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf")),
}
FAMILY_ORDER = ("Helvetica", "Arial", "Calibri", "Segoe UI", "Times", "Times New Roman", "Courier")
DEFAULT_FAMILY = "Helvetica"

_lock = threading.Lock()
_registered: dict[str, tuple[str, str, str, str]] = {}
_available: list[str] | None = None


def font_dirs() -> list[Path]:
    """Schriftenordner von Windows (System und Benutzer). ``UE_FONT_DIR`` ergänzt einen Ordner (Tests)."""
    dirs: list[Path] = []
    override = os.environ.get("UE_FONT_DIR")
    if override:
        dirs.append(Path(override))
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windir:
        dirs.append(Path(windir) / "Fonts")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    return dirs


def _find(filename: str) -> Path | None:
    for folder in font_dirs():
        for name in (filename, filename.upper()):
            candidate = folder / name
            if candidate.is_file():
                return candidate
    return None


def system_font_files(family: str) -> tuple[Path, Path, Path, Path] | None:
    entry = SYSTEM_FONTS.get(family)
    if entry is None:
        return None
    found = [_find(name) for name in entry[1]]
    if any(path is None for path in found):
        return None
    return tuple(found)  # type: ignore[return-value]


def available_families() -> list[str]:
    """Auswählbare Schriften: Standard-PDF-Schriften und installierte Windows-Schriften."""
    global _available
    if _available is None:
        _available = [name for name in FAMILY_ORDER if name in BASE_FONTS or system_font_files(name) is not None]
    return list(_available)


def reset_cache() -> None:
    """Nur für Tests: Schriftsuche neu ausführen."""
    global _available
    with _lock:
        _available = None
        _registered.clear()


def fallback_family(family: str) -> str:
    if family in BASE_FONTS:
        return family
    if family in SYSTEM_FONTS:
        return SYSTEM_FONTS[family][0]
    lowered = str(family).casefold()
    if "times" in lowered or "serif" in lowered and "sans" not in lowered:
        return "Times"
    if "courier" in lowered or "mono" in lowered:
        return "Courier"
    return DEFAULT_FAMILY


def pdf_variants(family: str) -> tuple[str, str, str, str]:
    """Registrierte PDF-Schriftnamen (normal, fett, kursiv, fett kursiv) einer Familie."""
    if family in BASE_FONTS:
        return BASE_FONTS[family]
    with _lock:
        cached = _registered.get(family)
        if cached is not None:
            return cached
        names = BASE_FONTS[fallback_family(family)]
        files = system_font_files(family)
        if files is not None:
            try:
                names = _register(family, files)
            except Exception:  # noqa: BLE001 - defekte Schriftdatei: Standardschrift verwenden
                names = BASE_FONTS[fallback_family(family)]
        _registered[family] = names
        return names


def _register(family: str, files: tuple[Path, Path, Path, Path]) -> tuple[str, str, str, str]:
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    stem = "UE-" + "".join(ch for ch in family if ch.isalnum())
    names = (stem, f"{stem}-Bold", f"{stem}-Italic", f"{stem}-BoldItalic")
    fonts = [TTFont(name, str(path)) for name, path in zip(names, files)]
    for font in fonts:
        pdfmetrics.registerFont(font)
    # Familie bekannt machen, damit ReportLab die Schnitte einander zuordnen kann.
    for bold, italic, name in ((0, 0, names[0]), (1, 0, names[1]), (0, 1, names[2]), (1, 1, names[3])):
        addMapping(stem, bold, italic, name)
    return names


def pdf_font(family: str, bold: bool = False, italic: bool = False) -> str:
    variants = pdf_variants(family)
    return variants[(1 if bold else 0) + (2 if italic else 0)]
