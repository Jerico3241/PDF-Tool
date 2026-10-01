"""Dateien: native Datei- und Ordnerauswahl (Qt), Öffnen mit dem Standardprogramm, Zwischenablage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Sequence

from appstate import desktop_dir

import winsys

EXCEL_FILTER = "Excel (*.xlsx *.xlsm *.xls);;Alle Dateien (*.*)"
IMAGE_FILTER = "Bilder (*.png *.jpg *.jpeg *.webp);;Alle Dateien (*.*)"
PDF_FILTER = "PDF (*.pdf);;Alle Dateien (*.*)"

# Tests: Antworten der Dateiauswahl vorgeben (Liste wird von vorn abgearbeitet); ``None`` = echter Dialog.
RESPONSES: list | None = None


def _answer(default):
    if RESPONSES is not None:
        return RESPONSES.pop(0) if RESPONSES else default
    return None


def start_dir(*candidates: str) -> str:
    """Startordner: der erste vorhandene Ordner (bzw. Ordner der Datei), sonst der Desktop."""
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        folder = path if path.is_dir() else path.parent
        if folder.is_dir():
            return str(folder)
    return str(desktop_dir())


def open_file(title: str, directory: str, filters: str) -> str:
    answer = _answer("")
    if answer is not None:
        return str(answer)
    from PySide6.QtWidgets import QFileDialog

    path, _filter = QFileDialog.getOpenFileName(None, title, directory, filters)
    return path or ""


def open_files(title: str, directory: str, filters: str) -> list[str]:
    answer = _answer([])
    if answer is not None:
        return [str(p) for p in (answer if isinstance(answer, (list, tuple)) else [answer])]
    from PySide6.QtWidgets import QFileDialog

    paths, _filter = QFileDialog.getOpenFileNames(None, title, directory, filters)
    return list(paths or [])


def pick_folder(title: str, directory: str) -> str:
    answer = _answer("")
    if answer is not None:
        return str(answer)
    from PySide6.QtWidgets import QFileDialog

    return QFileDialog.getExistingDirectory(None, title, directory) or ""


def open_path(path: str | Path) -> None:
    """Datei oder Ordner mit der Standardanwendung öffnen. Löst OSError aus."""
    winsys.open_path(path)


def open_url(url: str) -> bool:
    """Adresse im Standardbrowser öffnen (nur nach einem Klick; geprüft wird vorher beim Aufrufer)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    return bool(QDesktopServices.openUrl(QUrl(url)))


def copy_text(text: str) -> None:
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().setText(text)


def local_paths(urls: Sequence) -> list[str]:
    """Aus QML (Drag & Drop): URLs bzw. Pfade als lokale Pfade – in der Schreibweise des Systems
    (unter Windows ``C:\\Ordner\\Datei.xlsx`` statt ``C:/Ordner/Datei.xlsx`` aus der URL)."""
    from PySide6.QtCore import QUrl

    paths: list[str] = []
    for url in urls or ():
        if isinstance(url, QUrl):
            local = url.toLocalFile()
        else:
            text = str(url)
            local = QUrl(text).toLocalFile() if text.startswith("file:") else text
        if local:
            paths.append(os.path.normpath(local))
    return paths


Opener = Callable[[str | Path], None]
