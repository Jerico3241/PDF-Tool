"""Seiten als Bild exportieren (PNG oder JPEG) – in neue Dateien, nie über bestehende.

Gerendert wird wie in der Anzeige (PDFium, mit Anmerkungen und Formularwerten). Die Auflösung ist
frei wählbar (72–600 dpi); sehr große Seiten werden auf ``render.MAX_PIXELS`` begrenzt. Die
Berechtigung »Kopieren« der Datei gilt auch hier.
"""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from . import render
from .document import EditorDocument
from .errors import ReadOnlyDocument, SaveFailed, UnsupportedEdit
from .pages import unique_path

FORMATS = {"png": ("PNG", ".png"), "jpeg": ("JPEG", ".jpg")}
MIN_DPI, MAX_DPI = 72, 600


def export_pages(document: EditorDocument, pages, folder: str | os.PathLike, stem: str, *, fmt: str = "png", dpi: int = 150, quality: int = 90, progress=None, cancelled=None) -> list[Path]:
    """Seiten ``pages`` als Bilder in ``folder`` speichern: »Name_Seite3.png« … Liefert die Pfade.
    ``progress(fertig, gesamt)`` meldet den Fortschritt, ``cancelled()`` bricht ab (bereits
    geschriebene Bilder bleiben)."""
    if not document.permissions.copy:
        raise ReadOnlyDocument("Die Berechtigungen dieses PDFs erlauben keinen Export von Inhalten.")
    if fmt not in FORMATS:
        raise UnsupportedEdit("Unbekanntes Bildformat.")
    chosen = [int(i) for i in pages]
    if not chosen or min(chosen) < 0 or max(chosen) >= document.page_count:
        raise UnsupportedEdit("Die Auswahl enthält eine Seite, die es nicht gibt.")
    folder = Path(folder)
    if not folder.is_dir():
        raise SaveFailed("Der Zielordner existiert nicht.")
    dpi = max(MIN_DPI, min(MAX_DPI, int(dpi)))
    kind, suffix = FORMATS[fmt]
    safe = re.sub(r'[\\/:*?"<>|]+', "_", stem).strip(" .") or "Seite"
    written: list[Path] = []
    for done, index in enumerate(chosen):
        if cancelled is not None and cancelled():
            break
        geo = document.geometry(index)
        raster = render.render_page(document, index, max(8, int(round(geo.width * dpi / 72))))
        image = render.to_pil(raster)
        target = unique_path(folder, f"{safe}_Seite{index + 1}{suffix}")
        temp = folder / f".{target.stem[:40]}.pdftool-{secrets.token_hex(4)}.tmp"
        try:
            if kind == "JPEG":
                image.save(temp, "JPEG", quality=max(50, min(100, int(quality))), dpi=(dpi, dpi), optimize=True)
            else:
                image.save(temp, "PNG", dpi=(dpi, dpi))
            if target.exists():  # zwischenzeitlich von einem anderen Programm angelegt
                raise SaveFailed("Es gibt bereits eine Datei mit diesem Namen.")
            os.replace(temp, target)
        except OSError as exc:
            raise SaveFailed(f"Das Bild konnte nicht gespeichert werden ({exc.strerror or 'Ein-/Ausgabefehler'}).") from exc
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass
        written.append(target)
        if progress is not None:
            progress(done + 1, len(chosen))
    return written
