"""Scannen (seit 4.0 Beta 5): Seiten vom Scanner über die Scanner-Schnittstelle von Windows (WIA) holen.

Jeder Scanner mit Windows-Treiber (WIA) erscheint in der Liste – dieselben, die »Windows-Fax und -Scan« kennt.
Gescannt wird ohne Fenster des Treibers mit den Angaben aus PDF Tool:

* **Quelle:** Vorlagenglas (eine Seite je Durchgang) oder Einzug (alle eingelegten Blätter auf einmal; endet,
  sobald der Einzug leer ist).
* **Farbe:** Farbe, Graustufen oder Schwarzweiß.
* **Auflösung:** 150, 200, 300 oder 600 dpi (der Scanner nimmt die nächste, die er kann).

Die Seiten landen als Bilder in einem temporären Ordner; daraus entsteht die PDF (``imagepdf.create``). Unter
Linux und in Tests ersetzt eine Attrappe die Schnittstelle (``Backend``). Fehler des Scanners werden zu
verständlichen Meldungen (``ScanError``) – nie zu einem Absturz.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol

from .errors import EditorError

SOURCES = ("flatbed", "feeder")
COLORS = ("color", "gray", "bw")
RESOLUTIONS = (150, 200, 300, 600)
DEFAULT = {"source": "flatbed", "color": "color", "dpi": 300}
MAX_PAGES = 500  # Einzug: Schutz vor einem Treiber, der nie »leer« meldet

# WIA (wiadef.h): Gerätetyp, Eigenschaften, Bildformat, Fehlercodes
SCANNER_TYPE = 1
PROP_NAME = 7  # WIA_DIP_DEV_NAME
PROP_HANDLING_SELECT = 3088  # WIA_DPS_DOCUMENT_HANDLING_SELECT
PROP_PAGES = 3096  # WIA_DPS_PAGES
PROP_INTENT = 6146  # WIA_IPS_CUR_INTENT
PROP_XRES = 6147
PROP_YRES = 6148
FEEDER, FLATBED = 0x001, 0x002
INTENT = {"color": 0x001, "gray": 0x002, "bw": 0x004}
FORMAT_PNG = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"
PAPER_EMPTY = -2145320957  # 0x80210003 WIA_ERROR_PAPER_EMPTY
ERRORS = {
    -2145320959: "Der Scanner meldet einen Fehler. Bitte das Gerät prüfen und erneut versuchen.",  # 0x80210001 GENERAL
    -2145320958: "Papierstau im Scanner. Bitte das Papier entfernen und erneut scannen.",  # 0x80210002
    PAPER_EMPTY: "Im Einzug liegt kein Papier.",
    -2145320956: "Beim Einzug ist ein Problem aufgetreten (Papier prüfen).",  # 0x80210004 PAPER_PROBLEM
    -2145320955: "Der Scanner ist nicht erreichbar (ausgeschaltet oder nicht verbunden).",  # 0x80210005 OFFLINE
    -2145320954: "Der Scanner ist gerade beschäftigt. Bitte kurz warten und erneut versuchen.",  # 0x80210006 BUSY
    -2145320953: "Der Scanner wärmt sich auf. Bitte kurz warten und erneut versuchen.",  # 0x80210007
    -2145320952: "Der Scanner braucht eine Eingabe am Gerät.",  # 0x80210008 USER_INTERVENTION
    -2145320951: "Der Scanner wurde getrennt.",  # 0x80210009 ITEM_DELETED
    -2145320950: "Der Scanner antwortet nicht.",  # 0x8021000A DEVICE_COMMUNICATION
    -2145320945: "Die Abdeckung des Scanners ist offen.",  # 0x8021000F COVER_OPEN
    -2145320944: "Die Lampe des Scanners ist aus.",  # 0x80210010 LAMP_OFF
}


class ScanError(EditorError):
    """Scannen nicht möglich – ``str()`` ist die Meldung für die Anwendenden."""


class ScanCancelled(Exception):
    pass


@dataclass(frozen=True)
class Scanner:
    ident: str
    name: str


@dataclass(frozen=True)
class Settings:
    source: str = DEFAULT["source"]
    color: str = DEFAULT["color"]
    dpi: int = DEFAULT["dpi"]

    @staticmethod
    def of(data: dict | None) -> "Settings":
        data = data or {}
        source = data.get("source") if data.get("source") in SOURCES else DEFAULT["source"]
        color = data.get("color") if data.get("color") in COLORS else DEFAULT["color"]
        try:
            dpi = int(data.get("dpi") or DEFAULT["dpi"])
        except (TypeError, ValueError):
            dpi = DEFAULT["dpi"]
        return Settings(source, color, dpi if dpi in RESOLUTIONS else DEFAULT["dpi"])


class Backend(Protocol):
    def scanners(self) -> list[Scanner]: ...

    def pages(self, ident: str, settings: Settings, target: Path, start: int) -> Iterator[Path]:
        """Seiten scannen und je als Bild unter ``target`` ablegen (Vorlagenglas: eine, Einzug: bis er leer ist –
        dann ``PAPER_EMPTY``)."""
        ...


def scanners(backend: Backend | None = None) -> list[Scanner]:
    backend = backend or default_backend()
    if backend is None:
        return []
    try:
        return backend.scanners()
    except ScanError:
        raise
    except Exception as exc:  # noqa: BLE001 - Treiberfehler
        raise ScanError(_message(exc, "Die Scanner ließen sich nicht abfragen.")) from exc


def scan(ident: str, settings: Settings, folder: Path, *, start: int = 0, backend: Backend | None = None, cancel: threading.Event | None = None, progress: Callable[[int], None] | None = None, into: list | None = None) -> list[Path]:
    """Seiten scannen: am Vorlagenglas genau eine, am Einzug alle eingelegten. Rückgabe: die Bilder in Reihenfolge.
    ``into``: jede fertige Seite kommt sofort dazu – bricht der Scanner mitten im Einzug ab, bleiben sie erhalten."""
    backend = backend or default_backend()
    if backend is None:
        raise ScanError("Scannen ist nur unter Windows möglich.")
    folder.mkdir(parents=True, exist_ok=True)
    pages: list[Path] = []
    limit = MAX_PAGES if settings.source == "feeder" else 1
    try:
        for image in backend.pages(ident, settings, folder, start):
            _ensure_dpi(image, settings.dpi)
            pages.append(image)
            if into is not None:
                into.append(image)
            if progress is not None:
                progress(len(pages))
            if len(pages) >= limit:
                break
            if cancel is not None and cancel.is_set():
                raise ScanCancelled()
    except (ScanError, ScanCancelled):
        raise
    except Exception as exc:  # noqa: BLE001 - Treiberfehler
        if _code(exc) != PAPER_EMPTY or not (pages or settings.source == "feeder"):
            raise ScanError(_message(exc, "Der Scan ist fehlgeschlagen.")) from exc
    if not pages:
        raise ScanError(ERRORS[PAPER_EMPTY] if settings.source == "feeder" else "Der Scanner hat keine Seite geliefert.")
    return pages


def _ensure_dpi(path: Path, dpi: int) -> None:
    """Auflösung im Bild vermerken, falls der Treiber sie weglässt – sonst geriete die Seite in der PDF zu groß."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            if image.info.get("dpi"):
                return
            image.load()
            copy = image.copy()
        copy.save(path, format="PNG", dpi=(dpi, dpi))
    except Exception:  # noqa: BLE001 - dann mit der Standardauflösung von »PDF aus Bildern«
        pass


def _code(exc: BaseException) -> int | None:
    for value in (getattr(exc, "hresult", None), *(getattr(exc, "args", ()) or ())[:1]):
        if isinstance(value, int):
            return value if value < 0x80000000 else value - 0x100000000
    return None


def _message(exc: BaseException, fallback: str) -> str:
    code = _code(exc)
    return ERRORS.get(code, fallback) if code is not None else fallback


# Windows: WIA über COM (comtypes) ----------------------------------------------------------------------------------

class WiaBackend:
    """WIA-Automatisierung (``wiaaut.dll``, seit Windows XP Teil von Windows). Jeder Aufruf im eigenen Thread:
    COM wird dort eingerichtet und wieder abgebaut."""

    def __init__(self) -> None:
        import comtypes.client  # noqa: F401 - nur prüfen, ob vorhanden

    def _manager(self):
        import comtypes.client

        return comtypes.client.CreateObject("WIA.DeviceManager", dynamic=True)

    def scanners(self) -> list[Scanner]:
        with _Com():
            found = []
            infos = self._manager().DeviceInfos
            for index in range(1, int(infos.Count) + 1):
                info = infos.Item(index)
                if int(info.Type) != SCANNER_TYPE:
                    continue
                found.append(Scanner(str(info.DeviceID), _property(info.Properties, PROP_NAME) or "Scanner"))
            return found

    def pages(self, ident: str, settings: Settings, target: Path, start: int) -> Iterator[Path]:
        with _Com():
            device = self._connect(ident)
            _set(device.Properties, PROP_HANDLING_SELECT, FEEDER if settings.source == "feeder" else FLATBED)
            _set(device.Properties, PROP_PAGES, 1)
            item = device.Items.Item(1)
            _set(item.Properties, PROP_INTENT, INTENT[settings.color])
            _set(item.Properties, PROP_XRES, settings.dpi)
            _set(item.Properties, PROP_YRES, settings.dpi)
            index = start
            while True:
                image = item.Transfer(FORMAT_PNG)  # Einzug leer: COMError PAPER_EMPTY
                path = target / f"Seite-{index + 1:04d}.png"
                if path.exists():
                    path.unlink()
                image.SaveFile(str(path))
                index += 1
                yield path

    def _connect(self, ident: str):
        infos = self._manager().DeviceInfos
        for index in range(1, int(infos.Count) + 1):
            info = infos.Item(index)
            if str(info.DeviceID) == ident:
                return info.Connect()
        raise ScanError("Der gewählte Scanner ist nicht mehr verbunden.")


class _Com:
    def __enter__(self):
        import comtypes

        comtypes.CoInitialize()
        return self

    def __exit__(self, *_exc) -> None:
        import comtypes

        comtypes.CoUninitialize()


def _property(properties, ident: int):
    for index in range(1, int(properties.Count) + 1):
        prop = properties.Item(index)
        if int(prop.PropertyID) == ident:
            return prop.Value
    return None


def _set(properties, ident: int, value) -> bool:
    """Eigenschaft setzen, wenn der Treiber sie kennt; Werte außerhalb seines Bereichs ignoriert er bzw. rundet."""
    for index in range(1, int(properties.Count) + 1):
        prop = properties.Item(index)
        if int(prop.PropertyID) == ident:
            try:
                prop.Value = value
                return True
            except Exception:  # noqa: BLE001 - nicht unterstützt (z. B. Einzug ohne Einzug)
                if ident == PROP_HANDLING_SELECT and value == FEEDER:
                    raise ScanError("Dieser Scanner hat keinen Einzug. Bitte »Vorlagenglas« wählen.") from None
                return False
    if ident == PROP_HANDLING_SELECT and value == FEEDER:
        raise ScanError("Dieser Scanner hat keinen Einzug. Bitte »Vorlagenglas« wählen.")
    return False


_TEST_BACKEND: Backend | None = None


def default_backend() -> Backend | None:
    if _TEST_BACKEND is not None:
        return _TEST_BACKEND
    import sys

    if sys.platform != "win32":
        return None
    try:
        return WiaBackend()
    except ImportError:
        return None
