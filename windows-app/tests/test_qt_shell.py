"""Qt-Oberfläche: Start, Navigation, Tastenkürzel, Hilfe, Design und Fenster (2.7.0).

Ersetzt die Tk-Tests der Oberfläche (test_app_ui/test_app_v23). Die App läuft mit QML im
Fenster (offscreen); nach jedem Test darf die QML-Engine keine Warnung gemeldet haben.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from conftest import _prepare, neustart, pump, wait_until

import appstate
from qtapp.app import window_title
from tools.registry import CONTRACTS, READER, REPAIR


def test_start_and_version(app) -> None:
    assert app.app.version == appstate.VERSION
    assert app.window.title() == window_title(appstate.VERSION) == app.app.windowTitle  # »PDF Tool« (Beta: mit Version)
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
    pages = ["reader", "create", "batch", "layout", "preview", "templates", "rules", "comparison", "customers", "repair", "settings", "home"]
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
    assert [tool["key"] for tool in tools] == [READER.key, CONTRACTS.key, REPAIR.key]
    assert [tool["title"] for tool in tools] == ["PDF Reader & Editor", "Vertragsübersichten", "PDF reparieren"]
    assert [tool["shortcut"] for tool in tools] == ["Strg+5", "Strg+2", "Strg+3"]


def _szene(item) -> tuple[float, float, float, float]:
    from PySide6.QtCore import QPointF

    p = item.mapToScene(QPointF(0, 0))
    return (p.x(), p.y(), item.width(), item.height())


def _kind(karte, name: str):
    stapel = [karte]
    while stapel:
        aktuell = stapel.pop()
        if aktuell.objectName() == name:
            return aktuell
        stapel.extend(aktuell.childItems())
    raise AssertionError(name)


def _teil(karte, name: str) -> tuple[float, float, float, float]:
    """Lage eines Teils relativ zu seinem Werkzeug (Symbol, Titel, »Öffnen«, Tastenkürzel …)."""
    x, y, w, h = _szene(_kind(karte, name))
    kx, ky, _kw, _kh = _szene(karte)
    return (x - kx, y - ky, w, h)


def _ganze_woerter(werkzeug) -> None:
    """Name und Beschreibung brechen nur zwischen Wörtern um: Jedes Wort passt in die Breite seines Textes (sonst
    stehen die Werkzeuge untereinander)."""
    from PySide6.QtGui import QFontMetricsF

    for name in ("toolTitle", "toolDescription"):
        text = _kind(werkzeug, name)
        metrik = QFontMetricsF(text.property("font"))
        breitestes = max(metrik.horizontalAdvance(wort) for wort in text.property("text").split())
        assert breitestes <= text.width(), (name, text.property("text"), breitestes, text.width())


WERKZEUGE = ("toolCard_reader", "toolCard_contracts", "toolCard_repair")  # Reihenfolge wie auf der Startseite


def _pruefe_startseite(h) -> tuple[bool, int]:
    """Aufbau der Startseite (Adobe-Prinzip); liefert (Werkzeuge und Ablagefläche nebeneinander, Spalten der Werkzeuge).

    Die Gruppe steht mittig (gleiche Ränder – nur bei ungerader Breite ein Pixel Unterschied), höchstens 1080 px
    breit, Ränder mindestens 36 px; Titel, Werkzeuge, »Zuletzt verwendet« und Datenschutzhinweis an derselben
    linken Kante. Breit: Werkzeuge und Ablagefläche (260 px) nebeneinander, gleich hoch, 16 px Abstand; schmal:
    untereinander. Die Werkzeuge: gleich breit, auf ganzen Pixeln, mittig in ihrer Karte, kein Wort mitten im Wort
    umbrochen; nebeneinander gleich hoch mit »Öffnen ›« und Tastenkürzel auf einer Linie."""
    oben, karte, ablage, zuletzt, hinweis = (h.item(n) for n in ("homeTop", "homeTools", "homeDropZone", "homeRecent", "homePrivacy"))
    flaeche = oben.parentItem()
    while flaeche is not None and not flaeche.inherits("QQuickFlickable"):
        flaeche = flaeche.parentItem()
    fx0, _fy0, fbreite, _fh0 = _szene(flaeche)
    gx, _gy, gbreite, _gh = _szene(oben)
    links, rechts = gx - fx0, fx0 + fbreite - (gx + gbreite)
    assert abs(links - rechts) == int(fbreite) % 2, (links, rechts, fbreite)
    assert gbreite <= 1080 and min(links, rechts) >= 36
    for teil in (zuletzt, hinweis):
        assert _szene(teil)[0] == gx and _szene(teil)[2] == gbreite, teil.objectName()
    titel = next(k for k in _alle(h.item("homePage")) if k.objectName() == "pageHeader")
    assert _szene(titel)[0] == gx
    k, a = _szene(karte), _szene(ablage)
    nebeneinander = a[1] == k[1]
    if nebeneinander:
        assert k[0] == gx and a[2] == 260 and a[3] == k[3] and a[0] - (k[0] + k[2]) == 16 and a[0] + a[2] == gx + gbreite
    else:
        assert k[0] == a[0] == gx and k[2] == a[2] == gbreite and a[1] - (k[1] + k[3]) == 16
    assert _szene(zuletzt)[1] - max(k[1] + k[3], a[1] + a[3]) == 16
    werkzeuge = [h.item(name) for name in WERKZEUGE]
    lagen = [_szene(w) for w in werkzeuge]
    for lage in lagen:
        assert lage[2] == lagen[0][2] and all(float(wert).is_integer() for wert in lage), lage
    for werkzeug in werkzeuge:
        _ganze_woerter(werkzeug)
    spalten = len({lage[0] for lage in lagen})
    if spalten > 1:
        assert len({lage[1] for lage in lagen}) == 1 and len({lage[3] for lage in lagen}) == 1  # eine Zeile, gleich hoch
        for teil in ("toolIcon", "toolTitle", "toolOpen"):
            for werkzeug in werkzeuge[1:]:
                assert _teil(werkzeuge[0], teil)[:2] == _teil(werkzeug, teil)[:2], teil
        rechte_kanten = {round(_teil(w, "toolShortcut")[0] + _teil(w, "toolShortcut")[2]) for w in werkzeuge}
        assert len(rechte_kanten) == 1  # Tastenkürzel rechtsbündig
        for vorher, danach in zip(lagen, lagen[1:]):
            assert danach[0] - (vorher[0] + vorher[2]) == 8
    erste, letzte = min(lage[0] for lage in lagen), max(lage[0] + lage[2] for lage in lagen)
    assert abs((erste - k[0]) - (k[0] + k[2] - letzte)) <= 1  # mittig in der Karte
    return nebeneinander, spalten


def _alle(wurzel) -> list:
    alle, stapel = [], [wurzel]
    while stapel:
        aktuell = stapel.pop()
        alle.append(aktuell)
        stapel.extend(aktuell.childItems())
    return alle


# Fenstergrößen (geräteunabhängige Pixel) und erwarteter Aufbau: (Werkzeuge und Ablagefläche nebeneinander,
# Spalten der Werkzeuge). 760: kleinste Fensterbreite; 1093 × 614: 1366 × 768 bei 125 %; 1280 × 720: 1920 × 1080
# bei 150 %.
GROESSEN = (((1920, 1080), (True, 3)), ((2560, 1440), (True, 3)), ((1366, 768), (True, 3)), ((1280, 720), (True, 3)),
            ((1093, 614), (True, 3)), ((900, 700), (False, 3)), ((760, 700), (False, 1)))


@pytest.mark.parametrize("groesse,aufbau", GROESSEN)
def test_start_page_is_symmetric(ui_app, groesse, aufbau) -> None:
    h = ui_app
    h.window.resize(*groesse)
    pump(0.6)
    assert _pruefe_startseite(h) == aufbau
    if aufbau[0] and groesse[0] >= 1280:
        assert _szene(h.item("homeTop"))[2] == 1080  # volle Gruppe


def test_start_page_at_this_scale(ui_app) -> None:
    """Alle Fenstergrößen bei der Skalierung dieses Prozesses (``QT_SCALE_FACTOR``, sonst 100 %)."""
    h = ui_app
    assert h.window.devicePixelRatio() == pytest.approx(float(os.environ.get("QT_SCALE_FACTOR") or 1))
    for groesse, aufbau in GROESSEN:
        h.window.resize(*groesse)
        pump(0.4)
        assert _pruefe_startseite(h) == aufbau, groesse


@pytest.mark.parametrize("skalierung", ["1.25", "1.5", "1.75", "2"])
def test_start_page_is_symmetric_at_every_scale(skalierung: str) -> None:
    """Windows-Skalierung 125 … 200 %: Qt liest ``QT_SCALE_FACTOR`` nur beim Start – je Skalierung
    prüft ein eigener Prozess ``test_start_page_at_this_scale`` (100 % prüfen die Tests oben)."""
    env = {**os.environ, "QT_SCALE_FACTOR": skalierung, "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen")}
    test = f"{Path(__file__).resolve()}::test_start_page_at_this_scale"
    lauf = subprocess.run([sys.executable, "-m", "pytest", test, "-q", "-p", "no:cacheprovider"], cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=600)
    assert lauf.returncode == 0, lauf.stdout[-6000:] + lauf.stderr[-3000:]
    assert "1 passed" in lauf.stdout


def test_start_page_footer_stays_aligned_with_longer_text(ui_app) -> None:
    h = ui_app
    for groesse, aufbau in (((1366, 768), (True, 3)), ((900, 700), (False, 3))):
        h.window.resize(*groesse)
        pump(0.4)
        werkzeuge = [h.item(name) for name in WERKZEUGE]
        beschreibung = werkzeuge[1].property("description")
        vorher = _szene(werkzeuge[0])[3]
        werkzeuge[1].setProperty("description", "Eine deutlich längere Beschreibung, die in dieser Breite über mehrere Zeilen läuft und das Werkzeug höher macht, als es sonst wäre.")
        pump(0.3)
        assert _szene(werkzeuge[0])[3] > vorher  # alle Werkzeuge der Zeile wachsen gemeinsam …
        assert _pruefe_startseite(h) == aufbau  # … »Öffnen ›« und Tastenkürzel bleiben auf einer Linie
        werkzeuge[1].setProperty("description", beschreibung)
        pump(0.3)


def test_start_page_puts_tools_below_each_other_when_their_footer_does_not_fit(ui_app) -> None:
    """Nebeneinander nur, wenn jedes Werkzeug »Öffnen ›« und sein Tastenkürzel ganz zeigen kann (unter Windows
    bestimmen Schrift und Skalierung die Breite) – sonst untereinander, nie über den Rand der Karte hinaus."""
    h = ui_app
    h.window.resize(1093, 614)
    pump(0.4)
    assert _pruefe_startseite(h) == (True, 3)
    werkzeug = h.item(WERKZEUGE[0])
    kuerzel = werkzeug.property("shortcut")
    werkzeug.setProperty("shortcut", "Strg+Umschalt+Alt+F12")  # Fußzeile breiter als ein Drittel der Karte
    pump(0.4)
    assert _pruefe_startseite(h) == (True, 1)
    rest = _szene(werkzeug)[2] - (_teil(werkzeug, "toolShortcut")[0] + _teil(werkzeug, "toolShortcut")[2])
    assert rest >= 12  # Innenabstand rechts bleibt frei
    werkzeug.setProperty("shortcut", kuerzel)
    pump(0.4)
    assert _pruefe_startseite(h) == (True, 3)


def test_start_page_tools_open_their_tool(app) -> None:
    """Ein Klick auf ein Werkzeug öffnet es (mit Tab); »PDF Reader & Editor« ohne geöffnetes PDF fragt nach einer
    PDF – einen leeren Reader gibt es nicht."""
    from qtapp import files

    for name, page in (("toolCard_contracts", "create"), ("toolCard_repair", "repair")):
        app.navigate("home", 0.4)
        item = app.item(name)
        QTest.mouseClick(app.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint())
        pump(0.4)
        assert app.app.currentPage == page
    app.navigate("home", 0.4)
    karten = [app.item(name) for name in WERKZEUGE]
    assert [karte.findChild(QObject, "toolOpen").property("text") for karte in karten] == ["Öffnen"] * 3
    files.RESPONSES.append([])  # Dateiauswahl: abbrechen
    item = app.item("toolCard_reader")
    QTest.mouseClick(app.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint())
    pump(0.4)
    assert files.RESPONSES == [] and app.app.currentPage == "home"  # gefragt, abgebrochen: bleibt auf Start
    assert not app.messages()


def test_window_title_marks_beta_versions() -> None:
    """Fenstertitel aus der Versionsnummer: Stable »PDF Tool«, Beta »PDF Tool X.Y.Z Beta«."""
    assert window_title("2.8.0") == "PDF Tool"
    assert window_title("2.8.0-beta.1") == "PDF Tool 2.8.0 Beta"
    assert window_title("10.20.30-beta.12") == "PDF Tool 10.20.30 Beta"
    assert window_title("kaputt") == "PDF Tool"


@pytest.mark.parametrize("version,titel", [("4.2.0-beta.3", "PDF Tool 4.2.0 Beta"), ("4.2.0", "PDF Tool")])
def test_beta_is_marked_in_window_title_and_settings(qt_application, config_file: Path, monkeypatch, version: str, titel: str) -> None:
    """Beta: Fenstertitel mit Version und das Etikett »Beta« in der Info-Karte der Einstellungen –
    dasselbe wie in der Karte »Updates«; Stable: »PDF Tool«, kein Etikett."""
    from qtutil import Harness

    from qtapp import app as appmodule

    monkeypatch.setattr(appmodule, "VERSION", version)
    _prepare(config_file, monkeypatch, "full")
    h = Harness(ui=True)
    try:
        assert h.app.windowTitle == titel and h.window.title() == titel
        h.navigate("settings", 0.3)
        etikett, updates = h.item("infoBeta"), h.item("updateCurrentBeta")
        beta = version != "4.2.0"
        assert etikett.property("visible") is beta and etikett.property("text") == ("Beta" if beta else "")
        assert etikett.property("tone") == updates.property("tone") == "accent"
        assert etikett.property("height") == updates.property("height")  # gleiches, dezentes Etikett
        if beta:  # in der Zeile der Info-Karte, mittig neben »Über«
            karte = h.item("infoCard")
            ueber = next(e for e in _alle(karte) if e.property("text") == "Über" and e.inherits("QQuickAbstractButton"))
            ex, ey, ew, eh = _szene(etikett)
            ux, uy, _uw, uh = _szene(ueber)
            assert ex + ew <= ux and abs((ey + eh / 2) - (uy + uh / 2)) <= 0.5
        messages = h.messages()
    finally:
        h.close()
    assert not messages, "QML-Meldungen:\n" + "\n".join(messages)


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
    # Strg+5 ohne geöffnetes PDF: eine PDF wählen (Dateiauswahl) – es gibt keinen leeren Reader
    from qtapp import files

    files.RESPONSES.append([])  # abbrechen
    app.app.openShortcut(5)
    pump(0.2)
    assert files.RESPONSES == [] and app.app.currentPage == "settings"
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

    for page, title in (("home", "Kurzanleitung – PDF Tool"), ("reader", "Kurzanleitung – PDF Reader & Editor"), ("create", "Kurzanleitung – Vertragsübersichten"), ("repair", "Kurzanleitung – PDF reparieren")):
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


def test_tools_open_as_tabs_next_to_start_and_close_again(app) -> None:
    """Adobe-Prinzip: Werkzeuge erscheinen beim Öffnen als Tab neben ⌂ Start (in der Reihenfolge des Öffnens) und
    bleiben, bis man sie schließt – Eingaben bleiben dabei erhalten. Ist der geschlossene Tab zu sehen, folgt der
    rechts daneben, sonst der links daneben bzw. Start. Strg+W schließt den Tab des sichtbaren Werkzeugs."""
    a = app.app
    assert app.item("navigationPane") is None and app.item("appTabs").isVisible()
    assert a.openTabs == [] and app.item("tabHome").property("active") is True
    app.navigate("repair", 0.3)
    app.navigate("layout", 0.3)  # eine Ansicht der Vertragsübersichten
    app.navigate("settings", 0.3)
    assert a.openTabs == ["repair", "contracts", "settings"]
    assert app.item("tab_settings").property("active") and not app.item("tab_repair").property("active")
    app.navigate("home", 0.3)
    assert a.openTabs == ["repair", "contracts", "settings"] and app.item("tabHome").property("active")
    # Klick auf einen Tab: das Werkzeug mit seiner zuletzt gezeigten Ansicht
    tab = app.item("tab_contracts")
    QTest.mouseClick(app.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, tab.mapToScene(QPointF(30, tab.height() / 2)).toPoint())
    pump(0.4)
    assert a.currentPage == "layout" and tab.property("active")
    # den sichtbaren Tab schließen: der rechts daneben folgt
    a.closeTab("contracts")
    pump(0.3)
    assert a.openTabs == ["repair", "settings"] and a.currentPage == "settings"
    # Strg+W: Tab des sichtbaren Werkzeugs – ganz rechts, also folgt der links daneben
    QTest.keyClick(app.window, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    pump(0.3)
    assert a.openTabs == ["repair"] and a.currentPage == "repair"
    # wieder geöffnet: die zuletzt gezeigte Ansicht – Eingaben bleiben erhalten
    a.openTool(CONTRACTS.key)
    pump(0.3)
    assert a.openTabs == ["repair", "contracts"] and a.currentPage == "layout"
    # einen anderen Tab schließen: die Seite bleibt
    a.closeTab("repair")
    pump(0.3)
    assert a.openTabs == ["contracts"] and a.currentPage == "layout"
    # der letzte Tab: Start
    a.closeTab("contracts")
    pump(0.3)
    assert a.openTabs == [] and a.currentPage == "home"
    assert not app.messages()


def test_tab_marker_glides_to_the_active_tab_and_stays_under_it(app) -> None:
    """Die Akzentmarkierung gleitet zum neuen Tab (nur »Vollständig«) und steht danach genau darunter – auch wenn
    links davon ein Tab wegfällt."""
    app.settings.setProfile("full")
    marker = app.item("tabIndicator")

    def mitte(item) -> float:
        return item.mapToScene(QPointF(item.width() / 2, 0)).x()

    app.navigate("repair", 0.6)
    assert abs(mitte(marker) - mitte(app.item("tab_repair"))) < 1
    vorher, ziel = mitte(marker), mitte(app.item("tabHome"))
    app.app.navigate("home")
    lagen = []
    for _ in range(30):
        pump(0.01)
        lagen.append(mitte(marker))
    assert any(ziel + 2 < lage < vorher - 2 for lage in lagen) == (app.theme.effectiveProfile == "full")  # unterwegs (nur »Vollständig«)
    pump(0.4)
    assert abs(mitte(marker) - ziel) < 1
    app.navigate("settings", 0.4)
    app.navigate("layout", 0.6)
    assert abs(mitte(marker) - mitte(app.item("tab_contracts"))) < 1
    app.app.closeTab("settings")  # links vom aktiven Tab: dieser rückt nach, die Markierung bleibt darunter
    pump(0.6)
    assert app.app.currentPage == "layout" and abs(mitte(marker) - mitte(app.item("tab_contracts"))) < 1
    app.settings.setProfile("off")
    app.navigate("home", 0.1)
    assert abs(mitte(marker) - mitte(app.item("tabHome"))) < 1  # »Aus«: sofort
    app.settings.setProfile("full")
    assert not app.messages()


def test_menu_offers_open_settings_help_and_about(app) -> None:
    """≡ Menü: PDF öffnen, Start, Einstellungen, Kurzanleitung, Neuerungen, Über – ein Eintrag führt dorthin."""
    button = app.item("appMenuButton")
    QTest.mouseClick(app.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint())
    pump(0.4)
    assert app.item("appMenu").property("opened") is True
    names = ("menuOpen", "menuHome", "menuSettings", "menuHelp", "menuNews", "menuAbout")
    assert [app.item(name).property("text") for name in names] == ["PDF öffnen …", "Start", "Einstellungen", "Kurzanleitung", "Neu in dieser Version", "Über PDF Tool"]
    entry = app.item("menuSettings")
    QTest.mouseClick(app.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, entry.mapToScene(QPointF(entry.width() / 2, entry.height() / 2)).toPoint())
    pump(0.5)
    assert app.app.currentPage == "settings" and app.item("appMenu").property("opened") is False
    assert not app.messages()


@pytest.mark.parametrize("size", [(760, 560), (1024, 700), (1920, 1080), (3000, 1800)])
def test_scaling_and_sizes_do_not_break(app, size) -> None:
    app.window.resize(*size)
    for page in ("home", "reader", "create", "layout", "preview", "batch", "repair", "settings"):
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
    app.app.drop([pdf.as_uri()])  # seit 3.0.0: PDFs öffnet der PDF Reader – er erscheint mit dem geöffneten Dokument
    reader = app.runtime.reader.controller
    assert wait_until(lambda: reader.current is not None and reader.current.pageCount == 1, 60)
    assert wait_until(lambda: app.app.currentPage == "reader", 5)
    reader.closeCurrent()  # das letzte Dokument: zurück zur Startseite
    assert wait_until(lambda: app.app.currentPage == "home", 5)
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


def test_mouse_wheel_moves_the_same_distance_for_every_notch(app) -> None:
    """Mausrad wie in anderen Windows-Programmen: Jede Raste verschiebt gleich weit – auch schnell gedreht
    (Qts eigene Bewegung begann bei jeder Raste neu und verlor dabei bis zur Hälfte der Strecke) –, rund
    32 px je Zeile der Windows-Einstellung; am Ende des Inhalts bleibt die Seite stehen."""
    import time

    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QGuiApplication, QWheelEvent

    from qtapp import application as appmod

    hints = QGuiApplication.styleHints()
    lines = hints.wheelScrollLines()
    appmod.tune_wheel(app.qt)  # einmal je Anwendung – ein zweiter Aufruf ändert nichts
    assert hints.wheelScrollLines() == lines
    app.app.dialogs.shutdown()
    app.navigate("settings", 0.4)
    scrollers = [item for item in app.items("wheelScroll") if item.isVisible()]
    assert len(scrollers) == 1
    flick = scrollers[0].parentItem().parentItem()  # Inhalt → Ansicht
    end = flick.property("contentHeight") - flick.height()
    step = lines * 24
    assert end > 7 * step
    point = flick.mapToScene(QPointF(flick.width() / 2, flick.height() / 2))

    def notch(delta: int = -120) -> None:
        event = QWheelEvent(point, QPointF(app.window.mapToGlobal(point.toPoint())), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        event.setTimestamp(int(time.monotonic() * 1000))
        QGuiApplication.sendEvent(app.window, event)

    assert flick.property("contentY") == 0
    notch()
    pump(0.4)
    assert abs(flick.property("contentY") - step) < 1
    for _ in range(5):  # schnell gedreht: die Rasten addieren sich
        notch()
        pump(0.02)
    pump(0.5)
    assert abs(flick.property("contentY") - 6 * step) < 1
    notch(120)
    pump(0.4)
    assert abs(flick.property("contentY") - 5 * step) < 1
    for _ in range(40):  # weit über das Ende hinaus
        notch()
        pump(0.01)
    pump(0.5)
    assert abs(flick.property("contentY") - end) < 1
