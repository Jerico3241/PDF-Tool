"""Qt-Oberfläche: Start, Navigation, Tastenkürzel, Hilfe, Design und Fenster (2.7.0).

Ersetzt die Tk-Tests der Oberfläche (test_app_ui/test_app_v23). Die App läuft mit QML im
Fenster (offscreen); nach jedem Test darf die QML-Engine keine Warnung gemeldet haben.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from conftest import neustart, pump, wait_until

import appstate
from tools.registry import CONTRACTS, REPAIR


def test_start_and_version(app) -> None:
    assert app.app.version == appstate.VERSION
    assert app.window.title() == "PDF Tool"
    assert app.app.currentPage == "home"
    assert app.item("homePage") is not None
    assert app.item("toolCard_contracts") is not None and app.item("toolCard_repair") is not None
    assert app.window.isVisible()


def test_qml_runtime_avoids_the_qt_611_crash_when_loading_pages(ui_app) -> None:
    """Qt 6.11: Mit der schrittweisen Speicherbereinigung der QML-Engine können Objekte, die beim
    Laden der Seiten im Hintergrund entstehen, ihre QML-Funktionen verlieren – ein »Connections«
    mit Funktionen stürzt dann beim Fertigstellen ab (unter Windows und Linux beobachtet).

    Deshalb bereinigt die Engine in einem Zug (``QV4_GC_TIMELIMIT=0``, gesetzt vor dem Anlegen der
    Engine), und Steuerelemente, die in vielen Schaltflächen und Seiten stecken, kommen ohne
    »Connections« aus."""
    import os
    import sys

    from qtapp import application as appmod

    assert os.environ.get(appmod.GC_TIME_LIMIT) == "0"
    if sys.platform == "win32":
        import ctypes

        crt = ctypes.CDLL("ucrtbase")  # Qt liest die Variable über die C-Laufzeit
        crt.getenv.restype = ctypes.c_char_p
        assert crt.getenv(appmod.GC_TIME_LIMIT.encode()) == b"0"
    controls = Path(appmod.QML_DIR) / "PdfTool" / "Controls"
    for name in ("PButton", "PIconButton", "PIcon", "PProgressRing", "PInfoBar"):
        assert not re.search(r"\bConnections\s*\{", (controls / f"{name}.qml").read_text(encoding="utf-8")), name


def test_navigation_all_pages_and_rapid_switching(app) -> None:
    pages = ["create", "batch", "layout", "preview", "templates", "rules", "comparison", "customers", "repair", "settings", "home"]
    for page in pages:
        app.navigate(page, 0.3)
        assert app.app.currentPage == page
        assert app.item(f"page_{page}") is not None
    # Schnelles Umschalten: am Ende gilt der letzte Wunsch, nichts bleibt halb sichtbar
    for _ in range(3):
        for page in pages:
            app.app.navigate(page)
    pump(0.6)
    assert app.app.currentPage == "home"
    visible = [page for page in pages if app.item(f"page_{page}") is not None and app.item(f"page_{page}").property("opacity") > 0.99 and app.item(f"page_{page}").property("visible")]
    assert visible == ["home"]


def test_start_page_shows_tool_cards(app) -> None:
    tools = app.app.tools
    assert [tool["key"] for tool in tools] == [CONTRACTS.key, REPAIR.key]
    assert tools[0]["title"] == "Vertragsübersichten" and tools[1]["title"] == "PDF reparieren"
    assert tools[0]["shortcut"] == "Strg+2" and tools[1]["shortcut"] == "Strg+3"


def _szene(item) -> tuple[float, float, float, float]:
    from PySide6.QtCore import QPointF

    p = item.mapToScene(QPointF(0, 0))
    return (p.x(), p.y(), item.width(), item.height())


def _teil(karte, name: str) -> tuple[float, float, float, float]:
    """Lage eines Kartenteils relativ zur Karte (Symbol, Titel, Fußzeile, Tastenkürzel …)."""
    stapel = [karte]
    while stapel:
        aktuell = stapel.pop()
        if aktuell.objectName() == name:
            x, y, w, h = _szene(aktuell)
            kx, ky, _kw, _kh = _szene(karte)
            return (x - kx, y - ky, w, h)
        stapel.extend(aktuell.childItems())
    raise AssertionError(name)


def _pruefe_startseite(h) -> int:
    """Symmetrie der Startseite; liefert die Zahl der Spalten."""
    karten = [h.item("toolCard_contracts"), h.item("toolCard_repair")]
    raster, hinweis = h.item("homeGrid"), h.item("homePrivacy")
    a, b = (_szene(k) for k in karten)
    # exakt gleich groß (ganzzahlig), gleicher Innenaufbau
    assert (a[2], a[3]) == (b[2], b[3]) and float(a[2]).is_integer() and float(a[3]).is_integer()
    for teil in ("toolIcon", "toolTitle", "toolFooter", "toolOpen", "toolShortcut"):
        assert _teil(karten[0], teil) == _teil(karten[1], teil), teil
    assert _teil(karten[0], "toolIcon")[2:] == (48, 48)
    # Fußzeile unten in der Karte, Tastenkürzel am rechten Rand
    fx, fy, fw, fh = _teil(karten[0], "toolFooter")
    assert fy + fh == pytest.approx(a[3] - 20, abs=0.5)
    sx, _sy, sw, _sh = _teil(karten[0], "toolShortcut")
    assert sx + sw == pytest.approx(a[2] - 20, abs=0.5)
    # Gruppe mittig im Inhaltsbereich: gleicher Abstand links und rechts (± 1 px Rundung)
    flaeche = raster.parentItem()
    while flaeche is not None and not flaeche.inherits("QQuickFlickable"):
        flaeche = flaeche.parentItem()
    fx0, _fy0, fbreite, _fh0 = _szene(flaeche)
    gx, gy, gbreite, _gh = _szene(raster)
    links, rechts = gx - fx0, fx0 + fbreite - (gx + gbreite)
    assert abs(links - rechts) <= 1, (links, rechts)
    # Titel und Datenschutzhinweis an der linken Kante der Karten
    assert _szene(hinweis)[0] == gx and min(a[0], b[0]) == gx
    titel = next(k for k in _alle(h.item("homePage")) if k.objectName() == "pageHeader")
    assert _szene(titel)[0] == gx
    if a[1] == b[1]:  # zwei Spalten: gleiche Oberkante, Abstand = Token, Gruppe voll genutzt
        assert b[0] - (a[0] + a[2]) == 16
        assert b[0] + b[2] == pytest.approx(gx + gbreite, abs=0.5)
        return 2
    assert a[0] == b[0] and b[1] - (a[1] + a[3]) == 16  # eine Spalte: untereinander, gleich breit
    return 1


def _alle(wurzel) -> list:
    alle, stapel = [], [wurzel]
    while stapel:
        aktuell = stapel.pop()
        alle.append(aktuell)
        stapel.extend(aktuell.childItems())
    return alle


@pytest.mark.parametrize("groesse,spalten", [((1366, 768), 2), ((1920, 1080), 2), ((2560, 1440), 2), ((1093, 614), 2), ((760, 700), 1)])
def test_start_page_is_symmetric(ui_app, groesse, spalten) -> None:
    h = ui_app
    h.window.resize(*groesse)
    pump(0.6)
    assert _pruefe_startseite(h) == spalten
    breite = _szene(h.item("toolCard_contracts"))[2]
    assert breite <= 512 or spalten == 1  # Gruppe höchstens 1040 px: nebeneinander nie übermäßig breit
    assert breite >= 360 or spalten == 1  # nie schmaler als die Mindestbreite nebeneinander


def test_start_page_footer_stays_aligned_with_longer_text(ui_app) -> None:
    h = ui_app
    h.window.resize(1366, 768)
    pump(0.4)
    karten = [h.item("toolCard_contracts"), h.item("toolCard_repair")]
    vorher = _szene(karten[0])[3]
    karten[1].setProperty("description", "Eine deutlich längere Beschreibung, die in dieser Breite über mehrere Zeilen läuft und die Karte höher macht, als sie es sonst wäre.")
    pump(0.3)
    assert _szene(karten[0])[3] > vorher  # beide Karten wachsen gemeinsam …
    assert _pruefe_startseite(h) == 2  # … Fußzeile und Tastenkürzel bleiben auf einer Linie


def test_shortcuts_open_tools(app) -> None:
    app.app.openShortcut(2)
    pump(0.2)
    assert app.app.currentTool == CONTRACTS.key and app.app.currentPage == "create"
    app.app.openShortcut(3)
    pump(0.2)
    assert app.app.currentPage == "repair"
    app.app.openShortcut(4)
    pump(0.2)
    assert app.app.currentPage == "settings"
    app.app.openShortcut(1)
    pump(0.2)
    assert app.app.currentPage == "home"


def test_tool_remembers_its_last_view(app) -> None:
    app.navigate("layout")
    app.navigate("repair")
    app.app.openTool(CONTRACTS.key)
    pump(0.2)
    assert app.app.currentPage == "layout"


def test_status_hint_follows_the_tool(app) -> None:
    assert "Vertragsübersichten" in app.app.hint
    app.navigate("create")
    assert "PDF erstellen" in app.app.hint and "Kunde suchen" in app.app.hint
    app.navigate("batch")
    assert "Stapel" in app.app.hint or "Excel-Dateien" in app.app.hint
    app.navigate("repair")
    assert app.app.hint.startswith("Strg+O  PDFs auswählen")  # eine oder mehrere PDFs


def test_help_follows_the_open_view(app) -> None:
    from qtapp import dialogs

    for page, title in (("home", "Kurzanleitung – PDF Tool"), ("create", "Kurzanleitung – Vertragsübersichten"), ("repair", "Kurzanleitung – PDF reparieren")):
        app.navigate(page, 0.15)
        app.app.showHelp()
        assert app.app.dialogs.history[-1]["title"] == title
        assert app.app.dialogs.history[-1]["kind"] == "steps"
    assert dialogs.AUTO_ANSWER == "primary"


def test_about_and_changelog(app) -> None:
    app.app.showAbout()
    about = app.app.dialogs.history[-1]
    assert about["kind"] == "about" and about["data"]["version"] == appstate.VERSION
    assert "Manuelsen" in about["data"]["author"]
    app.app.showChangelog()
    news = app.app.dialogs.history[-1]
    assert news["kind"] == "changelog" and news["data"]["items"] == list(appstate.NEUERUNGEN)


def test_dialog_host_shows_and_closes_a_real_dialog(app, monkeypatch) -> None:
    """Ohne Autoantwort: der Dialog erscheint in QML und schließt über »Abbrechen«."""
    from PySide6.QtCore import QTimer

    from qtapp import dialogs

    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    seen = {}

    def answer() -> None:
        seen["open"] = app.app.dialogs.open
        seen["kind"] = app.app.dialogs.request.get("kind")
        app.app.dialogs.answer(app.app.dialogs.request["id"], "close", {})

    QTimer.singleShot(400, answer)
    assert app.app.dialogs.confirm("Wirklich?", "Test", "Ja") is False
    assert seen == {"open": True, "kind": "confirm"}
    pump(0.3)
    assert not app.app.dialogs.open


def test_settings_contain_only_global_options(app) -> None:
    app.navigate("settings")
    assert app.item("settingsPage") is not None
    assert [entry["value"] for entry in app.settings.themes] == ["system", "light", "dark"]
    assert [entry["value"] for entry in app.settings.profiles] == ["full", "reduced", "off"]


def test_theme_accent_and_profile_apply_live_and_persist(app, config_file: Path) -> None:
    app.navigate("create")
    light_background = app.theme.colors["layer"]
    app.settings.setTheme("dark")
    pump(0.4)
    assert app.theme.dark and app.theme.colors["layer"] != light_background
    app.settings.setAccent("#C239B3")
    pump(0.2)
    assert app.theme.accentChoice == "#C239B3"
    app.settings.setProfile("reduced")
    pump(0.2)
    assert app.theme.effectiveProfile == "reduced"
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["theme"] == "dark" and data["accent"] == "#C239B3" and data["animationsprofil"] == "reduced"
    neu = neustart(app)
    assert neu.theme.mode == "dark" and neu.theme.accentChoice == "#C239B3" and neu.theme.profile == "reduced"


def test_nav_compact_toggle_persists(app, config_file: Path) -> None:
    app.app.setNavCompact(True)
    pump(0.4)
    app.app.persist()
    assert json.loads(config_file.read_text(encoding="utf-8"))["nav_kompakt"] is True
    neu = neustart(app)
    assert neu.app.navCompact is True


def test_breakpoint_hysteresis_and_toggle(app) -> None:
    """Knapp unter einem Breakpoint bleibt der bisherige Zustand (8 px Hysterese wie 2.6.1); die
    Menüschaltfläche klappt die Navigation auch im schmalen Fenster aus, ein Breakpoint setzt das
    zurück und stellt sofort um – ohne Animation."""
    shell = app.item("shell")
    for width, mode in ((1010, "wide"), (1004, "wide"), (998, "medium"), (1004, "medium"), (1008, "wide"), (814, "medium"), (810, "compact"), (818, "compact"), (820, "medium")):
        app.window.resize(width, 700)
        pump(0.02)
        assert shell.property("mode") == mode, width
    assert shell.property("paneExpanded") is False
    shell.togglePane()
    pump(0.4)
    assert shell.property("paneExpanded") is True and shell.property("userExpanded") is True
    app.window.resize(1100, 700)
    pump(0.02)
    assert shell.property("mode") == "wide" and shell.property("userExpanded") is False
    assert not shell.property("paneAnimated")


def test_pane_toggle_lays_out_the_page_once(app) -> None:
    """Ein- und Ausklappen der Navigation: Die Seite erhält ihre neue Breite sofort – einmal, nicht in
    jedem Bild der Animation; nur die Inhaltsebene gleitet mit (wie 2.6.1)."""
    from qtutil import qml_type

    app.window.resize(1100, 700)
    app.navigate("create", 0.4)
    shell = app.item("shell")
    stack = [app.window.contentItem()]
    host = None
    while stack and host is None:
        current = stack.pop()
        if qml_type(current) == "PageHost":
            host = current
        stack.extend(current.childItems())
    assert host is not None
    for expanded in (False, True):
        widths: list[float] = []
        host.widthChanged.connect(lambda: widths.append(host.width()))
        shell.togglePane()
        pump(0.5)
        host.widthChanged.disconnect()
        assert shell.property("paneExpanded") is expanded
        assert len(widths) == 1, widths
        assert widths[0] == 1100 - (240 if expanded else 48) - 1


@pytest.mark.parametrize("size", [(760, 560), (1024, 700), (1920, 1080), (3000, 1800)])
def test_scaling_and_sizes_do_not_break(app, size) -> None:
    app.window.resize(*size)
    for page in ("home", "create", "layout", "preview", "batch", "repair", "settings"):
        app.navigate(page, 0.2)
    pump(0.3)
    assert not app.messages()


def test_window_geometry_is_saved_and_validated(app, config_file: Path) -> None:
    app.window.setX(40)
    app.window.setY(30)
    app.window.resize(1000, 700)
    pump(0.2)
    app.app.persist()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["fenster_qt"]["w"] == 1000 and data["fenster_qt"]["h"] == 700
    # Unmögliche Lage (Monitor abgesteckt): beim nächsten Start sichtbar auf dem Bildschirm
    data["fenster_qt"].update({"x": 90000, "y": 90000})
    config_file.write_text(json.dumps(data), encoding="utf-8")
    neu = neustart(app)
    screen = neu.window.screen().availableGeometry()
    assert screen.intersects(neu.window.geometry())


def test_drop_on_start_page_routes_by_file_type(app, tmp_path: Path, excel_file: Path) -> None:
    pdf = tmp_path / "x.pdf"
    import pdfsamples

    pdfsamples.healthy(pdf, pages=1)
    assert app.app.currentPage == "home"
    assert app.app.dragEnter([pdf.as_uri()]) is True
    app.app.drop([pdf.as_uri()])
    assert app.app.currentPage == "repair"
    assert wait_until(lambda: app.repair.analysis is not None, 60)
    app.navigate("home")
    app.app.drop([excel_file.as_uri()])
    assert app.app.currentPage == "create"
    assert wait_until(lambda: app.overview.analysis() is not None, 60)
    assert app.app.dragEnter([str(tmp_path / "notiz.txt")]) is False
    app.app.dragLeave()


def test_closing_saves_and_leaves_nothing_running(app, config_file: Path) -> None:
    app.overview.firma = "Schließen GmbH"
    assert app.app.requestClose() is True
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["firmenname"] == "Schließen GmbH"
    assert app.app.timers.count() == 0


def _motion(app) -> dict:
    """Werte des QML-Singletons ``Motion`` (wie die Oberfläche sie sieht)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent

    component = QQmlComponent(app.engine)
    component.setData(
        b"import QtQuick\nimport PdfTool.Style\nQtObject {\n"
        b"  property var values: ({ enabled: Motion.enabled, moves: Motion.moves, pageOut: Motion.pageOut, pageIn: Motion.pageIn,"
        b" pageShift: Motion.pageShift, menu: Motion.menu, menuShift: Motion.menuShift, dialog: Motion.dialog, dialogScale: Motion.dialogScale,"
        b" expand: Motion.expand, infoBar: Motion.infoBar, fast: Motion.fast, fade: Motion.fade, tooltip: Motion.tooltip, scroll: Motion.scroll })\n}\n",
        QUrl.fromLocalFile(str(app.appmod.QML_DIR / "motion-probe.qml")),
    )
    probe = component.create()
    assert probe is not None, component.errorString()
    values = probe.property("values")
    values = values.toVariant() if hasattr(values, "toVariant") else dict(values)
    probe.deleteLater()
    return values


def test_animation_profiles_follow_the_design_rules(app) -> None:
    app.settings.setProfile("full")
    pump(0.1)
    full = _motion(app)
    assert full["enabled"] and full["moves"]
    assert 140 <= full["pageOut"] + full["pageIn"] <= 200  # Seitenwechsel: aus- und einblenden
    assert 120 <= full["menu"] <= 160 and full["menuShift"] > 0  # Menüs: Deckkraft + leichte Bewegung
    assert full["dialog"] > 0 and full["dialogScale"] < 1  # Dialoge: Einblenden + leichtes Skalieren
    assert full["expand"] > 0 and full["infoBar"] > 0 and full["tooltip"] > 0
    app.settings.setProfile("reduced")
    pump(0.1)
    reduced = _motion(app)
    assert reduced["enabled"] and not reduced["moves"]
    assert reduced["pageShift"] == 0 and reduced["menuShift"] == 0 and reduced["dialogScale"] == 1  # keine Bewegung
    assert reduced["expand"] == 0 and reduced["scroll"] == 0 and 0 < reduced["fade"] <= full["fade"]
    app.settings.setProfile("off")
    pump(0.1)
    off = _motion(app)
    assert not off["enabled"] and all(off[key] == 0 for key in ("pageOut", "pageIn", "menu", "dialog", "expand", "infoBar", "fast", "fade", "tooltip"))
    app.settings.setProfile("full")
