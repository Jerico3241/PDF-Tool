"""Systeminformationen für Diagnose und Support-Paket."""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

# Bibliotheken, deren Version für eine Fehlersuche zählt: (Distributionen, Anzeige, Modul)
MODULES = (
    (("PySide6", "PySide6_Essentials", "PySide6-Essentials"), "PySide6", "PySide6"),
    (("reportlab",), "ReportLab", "reportlab"),
    (("openpyxl",), "openpyxl", "openpyxl"),
    (("pandas",), "pandas", "pandas"),
    (("numpy",), "NumPy", "numpy"),
    (("Pillow",), "Pillow", "PIL"),
    (("xlrd",), "xlrd", "xlrd"),
    (("pypdf",), "pypdf", "pypdf"),
    (("pikepdf",), "pikepdf", "pikepdf"),
    (("pypdfium2",), "pypdfium2", "pypdfium2"),
    (("lxml",), "lxml", "lxml"),
)


@dataclass(frozen=True)
class Fact:
    key: str
    label: str
    value: str


def module_version(distribution: str) -> str:
    from importlib import metadata

    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return ""
    except Exception:  # noqa: BLE001 - beschädigte Metadaten
        return ""


def _imported_version(module: str) -> str:
    """Rückgriff ohne Metadaten (z. B. eingebettete Laufzeit): ``__version__`` des Moduls."""
    import importlib

    try:
        value = getattr(importlib.import_module(module), "__version__", "")
    except Exception:  # noqa: BLE001
        return ""
    return str(value) if value else ""


def module_versions() -> dict[str, str]:
    result = {}
    for distributions, label, module in MODULES:
        version = next((found for name in distributions if (found := module_version(name))), "") or _imported_version(module)
        result[label] = version or "nicht installiert"
    return result


def os_brief() -> str:
    """Kurzform des Betriebssystems für das Protokoll beim Start – ohne WMI-Abfrage.

    ``platform.platform()`` und ``platform.uname()`` fragen unter Windows (ab Python 3.12) WMI ab;
    das kann den Start spürbar verzögern. Die ausführliche Angabe ermittelt die Diagnose im
    Hintergrund (``windows_version``)."""
    if sys.platform == "win32":
        try:
            version = sys.getwindowsversion()
            return f"Windows {version.major}.{version.minor} Build {version.build}"
        except Exception:  # noqa: BLE001
            return "Windows"
    try:
        uname = os.uname()
        return f"{uname.sysname} {uname.release}"
    except (AttributeError, OSError):
        return sys.platform


def windows_version() -> str:
    """»Windows 11 Pro 23H2 (Build 22631)« – sonst die Plattform (Tests unter Linux)."""
    if sys.platform != "win32":
        return platform.platform(terse=True)
    try:
        build = sys.getwindowsversion().build
        name = "Windows 11" if build >= 22000 else "Windows 10" if build >= 10240 else f"Windows {platform.release()}"
        edition = platform.win32_edition() or ""
        display = ""
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
                display = str(winreg.QueryValueEx(key, "DisplayVersion")[0])
        except OSError:
            display = ""
        parts = [name, edition.replace("Professional", "Pro") if edition else "", display]
        return " ".join(part for part in parts if part) + f" (Build {build})"
    except Exception:  # noqa: BLE001
        return platform.platform(terse=True)


def repair_engines() -> str:
    try:
        from tools.pdf_repair.engine import engine_name

        return engine_name() or "nicht verfügbar"
    except Exception:  # noqa: BLE001
        return "nicht verfügbar"


def qt_versions() -> str:
    try:
        import PySide6
        from PySide6.QtCore import qVersion

        return f"PySide6 {PySide6.__version__} · Qt {qVersion()}"
    except Exception:  # noqa: BLE001
        return "nicht verfügbar"


# Angaben der Systeminformationen in ihrer Reihenfolge: (Schlüssel, Beschriftung)
FACTS = (
    ("version", "PDF Tool"),
    ("channel", "Update-Kanal"),
    ("python", "Python"),
    ("qt", "Oberfläche"),
    ("os", "Betriebssystem"),
    ("arch", "Architektur"),
    ("data", "Datenordner"),
    ("install", "Programmordner"),
    ("engines", "Reparatur-Engines"),
    ("modules", "Module"),
)


def system_facts(app_version: str, channel: str, data_dir: Path, install_dir: Path) -> list[Fact]:
    bits = "64 Bit" if sys.maxsize > 2**32 else "32 Bit"
    values = {
        "version": app_version or "unbekannt",
        "channel": "Beta" if channel == "beta" else "Stable",
        "python": f"{platform.python_version()} ({bits})",
        "qt": qt_versions(),
        "os": windows_version(),
        "arch": platform.machine() or "unbekannt",
        "data": str(data_dir),
        "install": str(install_dir),
        "engines": repair_engines(),
        "modules": ", ".join(f"{label} {version}" for label, version in module_versions().items()),
    }
    return [Fact(key, label, values[key]) for key, label in FACTS]
