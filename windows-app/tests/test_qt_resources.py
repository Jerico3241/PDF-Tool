"""QML als Qt-Ressource, Laufzeit ohne tkinter und das Verschlanken von PySide6 (2.7.0)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(ROOT))

import qmlres  # noqa: E402
import qtruntime  # noqa: E402


def test_qrc_lists_every_qml_file_qmldir_and_icon() -> None:
    text = qmlres.qrc_text()
    files = qmlres.resource_files()
    qml_dir = APP / "qml"
    expected = {p for p in qml_dir.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert set(files) == expected
    assert 'alias="qml/Main.qml"' in text and 'alias="qml/PdfTool/Pages/qmldir"' in text and 'alias="qml/icons/wrench.svg"' in text
    for folder in ("Style", "Controls", "Shell", "Pages", "Dialogs"):
        assert (qml_dir / "PdfTool" / folder / "qmldir").is_file()


def test_every_qml_component_is_registered_in_its_qmldir() -> None:
    """Eine QML-Datei, die in keinem qmldir steht, fehlte im Setup nicht – aber jede Seite würde
    beim Laden aus der Ressource scheitern. Deshalb: jede Komponente steht in ihrem qmldir."""
    for folder in (APP / "qml" / "PdfTool").iterdir():
        qmldir = (folder / "qmldir").read_text(encoding="utf-8")
        for qml in folder.glob("*.qml"):
            assert re.search(rf"\b{qml.stem}\b.*\b{qml.name}\b", qmldir), f"{qml.name} fehlt in {folder.name}/qmldir"


def test_ui_loads_from_the_compiled_resource(tmp_path: Path) -> None:
    """Wie im Setup: QML nur aus qml_rc.py, ohne den Ordner qml – alle Seiten ohne Meldung."""
    qmlres.compile_resources(tmp_path / "qml_rc.py")
    script = r"""
import json, os, sys, time
sys.path.insert(0, sys.argv[1]); sys.path.insert(1, sys.argv[2])
import appstate
from qtapp import application as appmod, images
from PySide6.QtCore import QEventLoop, qInstallMessageHandler
qInstallMessageHandler(appmod._message_handler)
source, _ = appmod.qml_source()
assert source.toString() == "qrc:/qml/Main.qml", source.toString()
images.ICON_DIR = images.ICON_DIR.parent / "gibt-es-nicht"  # Symbole nur aus der Ressource
assert images.read_icon("wrench", images.ICON_DIR).startswith(b"<svg")
qt = appmod.create_application([])
rt = appmod.Runtime(appmod.load_config())
engine = appmod.create_engine(rt)
window = appmod.show_window(rt, engine)
def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qt.processEvents(QEventLoop.AllEvents, 20); time.sleep(0.005)
pump(1.5)
rt.settings.setCustomerRecords(True)
for page in ("create", "layout", "preview", "batch", "comparison", "customers", "repair", "settings", "home"):
    rt.app.navigate(page); pump(0.3)
    assert rt.app.currentPage == page, (page, rt.app.currentPage)
print(json.dumps({"messages": appmod.MESSAGES}))
rt.app.shutdown()
"""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", UE_DATA_DIR=str(tmp_path / "daten"), UE_CONFIG_FILE=str(tmp_path / "daten" / "gui-config.json"))
    (tmp_path / "daten").mkdir()
    (tmp_path / "daten" / "gui-config.json").write_text('{"gesehen": "%s"}' % __import__("appstate").VERSION, encoding="utf-8")
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(APP)], env=env, capture_output=True, text=True, timeout=240, cwd=str(tmp_path))
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-4000:]
    import json

    messages = json.loads(result.stdout.strip().splitlines()[-1])["messages"]
    assert messages == []


def test_productive_app_contains_no_tkinter() -> None:
    offenders = []
    for path in APP.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(import tkinter|from tkinter|import _tkinter)", text, re.M):
            offenders.append(str(path.relative_to(APP)))
    assert offenders == []
    assert not (APP / "vertragdesk.py").exists() and not (APP / "ui").exists()


def test_start_script_needs_no_working_directory() -> None:
    text = (APP / "start.py").read_text(encoding="utf-8")
    assert "tkinter" not in text and "os.chdir" not in text
    assert "qtapp.application" in text


def test_pyside6_is_pinned_exactly_with_hashes() -> None:
    pins = (ROOT / "runtime-requirements.txt").read_text(encoding="utf-8")
    import PySide6

    for name in ("PySide6-Essentials", "shiboken6"):
        match = re.search(rf"^{name}==(\S+) --hash=sha256:[0-9a-f]{{64}}$", pins, re.M)
        assert match, name
        assert match.group(1) == PySide6.__version__  # Tests laufen mit derselben Version wie das Setup
    assert "tkinter" not in pins.lower()


def test_pe_imports_of_a_minimal_dll(tmp_path: Path) -> None:
    """Die Importtabelle (normal und verzögert) einer kleinen, selbst gebauten PE-Datei lesen."""
    import struct

    # Aufbau: DOS-Kopf, PE-Kopf (PE32+), ein Abschnitt .idata mit Import- und Delay-Import-Tabelle
    section_rva, section_raw = 0x1000, 0x400
    data = bytearray(0x800)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664, 1)  # Maschine, Abschnitte
    struct.pack_into("<H", data, 0x84 + 16, 240)  # Größe des optionalen Kopfs
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20B)
    directories = optional + 112
    struct.pack_into("<II", data, directories + 8, section_rva, 40)  # Importe
    struct.pack_into("<II", data, directories + 13 * 8, section_rva + 0x100, 64)  # verzögert
    header = optional + 240
    data[header : header + 8] = b".idata\0\0"
    struct.pack_into("<IIII", data, header + 8, 0x400, section_rva, 0x400, section_raw)
    base = section_raw
    struct.pack_into("<IIIII", data, base, 0, 0, 0, section_rva + 0x80, 0)  # Name bei +0x80
    data[base + 0x80 : base + 0x80 + 11] = b"Qt6Core.dll"
    struct.pack_into("<II", data, base + 0x100, 1, section_rva + 0xC0)  # verzögert, RVA-basiert
    data[base + 0xC0 : base + 0xC0 + 12] = b"Qt6Quick.dll"
    dll = tmp_path / "probe.dll"
    dll.write_bytes(bytes(data))
    assert qtruntime.pe_imports(dll) == ["Qt6Core.dll", "Qt6Quick.dll"]
    (tmp_path / "Qt6Core.dll").write_bytes(b"MZ")
    (tmp_path / "Qt6Quick.dll").write_bytes(b"MZ")
    (tmp_path / "Qt6Unused.dll").write_bytes(b"MZ")
    needed = qtruntime.dependency_closure([dll], [tmp_path])
    assert {path.name for path in needed} == {"Qt6Core.dll", "Qt6Quick.dll"}


@pytest.mark.skipif(sys.platform != "win32", reason="nur mit dem PySide6-Wheel für Windows")
def test_trim_plan_keeps_what_the_app_loads() -> None:
    import PySide6

    site = Path(PySide6.__file__).resolve().parents[1]
    keep, drop = qtruntime.plan(site)
    names = {path.name for path in keep}
    assert {"QtQuick.pyd", "Qt6Quick.dll", "qwindows.dll", "qtquickcontrols2basicstyleplugin.dll"} <= names
    assert "opengl32sw.dll" not in names and "designer.exe" not in names
