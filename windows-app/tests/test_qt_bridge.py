"""Qt-Anwendungsschicht ohne Oberfläche: Properties, Listenmodelle, Hinweise, Dialoge, Zeitgeber,
Hintergrundarbeit, Design/Animationsprofile, Fensterlage und QML-Singletons (2.7.0)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from conftest import pump, wait_until


@pytest.fixture(autouse=True)
def _qt(qt_application):
    return qt_application


# --- Properties -------------------------------------------------------------------------------


def test_prop_notifies_only_real_changes_and_observers() -> None:
    from qtapp.base import Observable, Var, prop

    class Form(Observable):
        nameChanged, name = prop(str, "name", "")
        countChanged, count = prop(int, "count", 0)

    form = Form()
    signals, seen = [], []
    form.nameChanged.connect(lambda: signals.append(form.name))
    form.observe("name", seen.append)
    form.name = "A"
    form.name = "A"  # gleicher Wert: nichts
    form.name = None  # None bei Text: leer
    assert signals == ["A", ""] and seen == ["A", ""]
    form.set_quietly("name", "B")  # QML ja, Python-Beobachter nein
    assert signals[-1] == "B" and seen == ["A", ""]
    var = Var(form, "count")
    calls = []
    var.trace_add("write", lambda: calls.append(var.get()))
    var.set(3)
    assert form.count == 3 and calls == [3]


# --- Listenmodell -------------------------------------------------------------------------------


def _model():
    from qtapp.models import KeyedListModel

    return KeyedListModel(("name", "status"), key="key")


def test_list_model_changes_rows_incrementally() -> None:
    model = _model()
    events = []
    model.rowsInserted.connect(lambda _p, first, last: events.append(("insert", first, last)))
    model.rowsRemoved.connect(lambda _p, first, last: events.append(("remove", first, last)))
    model.rowsMoved.connect(lambda *_a: events.append(("move",)))
    model.dataChanged.connect(lambda top, bottom, roles: events.append(("data", top.row(), bottom.row())))
    model.set_items([{"key": k, "name": k.upper(), "status": "neu"} for k in "abc"])
    assert model.keys() == ["a", "b", "c"] and model.rowCount() == 3
    events.clear()
    model.update_item("b", status="fertig")
    assert events == [("data", 1, 1)] and model.item("b")["status"] == "fertig"
    events.clear()
    model.set_items([{"key": "a", "name": "A", "status": "neu"}, {"key": "c", "name": "C", "status": "neu"}, {"key": "d", "name": "D", "status": "neu"}])
    assert ("remove", 1, 1) in events and ("insert", 2, 2) in events
    assert model.keys() == ["a", "c", "d"]
    events.clear()
    model.set_items([{"key": "d", "name": "D", "status": "neu"}, {"key": "a", "name": "A", "status": "neu"}, {"key": "c", "name": "C", "status": "neu"}])
    assert model.keys() == ["d", "a", "c"] and ("move",) in events
    assert model.resets == 0  # nie ein Neuaufbau für kleine Änderungen
    assert model.get(0)["name"] == "D" and model.indexOf("c") == 2 and model.get(99) == {}


def test_list_model_with_500_entries_stays_incremental() -> None:
    model = _model()
    items = [{"key": f"k{i:03d}", "name": f"Kunde {i}", "status": "ok"} for i in range(500)]
    model.set_items(items)
    changed = [dict(item) for item in items]
    changed[250]["status"] = "neu"
    changes = []
    model.dataChanged.connect(lambda top, bottom, roles: changes.append((top.row(), bottom.row())))
    model.set_items(changed)
    assert changes == [(250, 250)] and model.resets == 0


# --- Hinweise und Dialoge ----------------------------------------------------------------------


def test_notices_show_hide_actions_and_auto_hide() -> None:
    from qtapp.notices import NoticeCenter
    from qtapp.timers import Timers

    timers = Timers()
    center = NoticeCenter(timers)
    triggered = []
    center.notify("pdf_info", "success", "Fertig", "PDF erstellt", actions=(("Öffnen", lambda: triggered.append("open")),), auto_hide=150)
    notice = center.get("pdf_info")
    assert notice.shown and notice.severity == "success" and notice.actions == ["Öffnen"] and center.area("pdf_info") is notice
    notice.trigger(0)
    notice.trigger(5)  # ungültig: nichts
    assert triggered == ["open"]
    assert wait_until(lambda: not notice.shown, 3)
    center.notify("pdf_info", "bogus", "x")
    assert notice.severity == "info"
    closed = []
    center.on_close("pdf_info", lambda: closed.append(True))
    notice.close()
    assert not notice.shown and closed == [True]


def test_dialog_service_answers_modal_and_shows_info(monkeypatch) -> None:
    from PySide6.QtCore import QTimer

    from qtapp import dialogs

    service = dialogs.DialogService()
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", "secondary")
    assert service.ask("confirm", "Titel", data={"x": 1}) == ("secondary", {"x": 1})
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    QTimer.singleShot(50, lambda: service.answer(service.request["id"], "primary", {"wahl": 2}))
    answer, data = service.ask("choose_template", "Vorlage", primary="Übernehmen")
    assert answer == "primary" and data == {"wahl": 2} and not service.open
    service.show("steps", "Kurzanleitung", {"steps": ["a"]})
    assert service.open and service.request["modal"] is False and service.pending() == 1
    service.shutdown()
    assert service.pending() == 0 and not service.open


# --- Zeitgeber und Hintergrundarbeit ---------------------------------------------------------------


def test_timers_replace_cancel_and_report_errors() -> None:
    from qtapp.timers import Timers

    errors, calls = [], []
    timers = Timers(on_exception=errors.append)
    timers.later("save", 80, lambda: calls.append("alt"))
    timers.later("save", 80, lambda: calls.append("neu"))  # ersetzt den ersten
    timers.soon("idle", lambda: calls.append("idle"))
    timers.soon("idle", lambda: calls.append("doppelt"))  # nur einmal je Schlüssel
    timers.later("weg", 50, lambda: calls.append("weg"))
    timers.cancel("weg")
    timers.later("fehler", 10, lambda: 1 / 0)
    pump(0.3)
    assert calls == ["idle", "neu"] and timers.count() == 0
    assert errors and "ZeroDivisionError" in errors[0]
    timers.shutdown()
    timers.later("danach", 0, lambda: calls.append("danach"))
    pump(0.05)
    assert "danach" not in calls


def test_worker_delivers_results_in_the_gui_thread() -> None:
    from qtapp.tasks import Worker

    worker = Worker()
    main = threading.get_ident()
    seen = {}
    worker.run(lambda: threading.get_ident(), lambda result: seen.update(done=(result != main, threading.get_ident() == main)))
    worker.run(lambda: 1 / 0, None, lambda exc, text: seen.update(error=(type(exc).__name__, threading.get_ident() == main)))
    assert wait_until(lambda: "done" in seen and "error" in seen, 5)
    assert seen["done"] == (True, True) and seen["error"] == ("ZeroDivisionError", True)
    worker.shutdown()
    late = []
    worker.run(lambda: 1, lambda _r: late.append(1))
    pump(0.2)
    assert late == []  # nach dem Beenden verfallen Ergebnisse


# --- Design, Animationsprofile, alte Einstellungen -----------------------------------------------


@pytest.mark.parametrize(
    "cfg,profile",
    [({}, "full"), ({"animationen": False}, "off"), ({"animationen": True}, "full"), ({"animationsprofil": "reduced", "animationen": False}, "reduced")],
)
def test_animation_profile_from_config(cfg, profile) -> None:
    from qtapp.theme import profile_from_config

    assert profile_from_config(cfg) == profile


def test_legacy_animation_setting_is_kept_for_older_versions(monkeypatch) -> None:
    monkeypatch.delenv("UE_NO_ANIMATIONS", raising=False)
    from qtapp.theme import ThemeController

    explicit = ThemeController({"animationen": True})
    assert explicit.config()["animationen"] is True  # ausdrückliches »an« bleibt
    explicit.setProfile("reduced")
    assert explicit.config()["animationen"] is None and explicit.config()["animationsprofil"] == "reduced"
    explicit.setProfile("off")
    assert explicit.config()["animationen"] is False
    following = ThemeController({})
    assert following.config()["animationen"] is None  # »wie Windows« (Schlüssel fehlt)


def test_windows_reduced_motion_means_at_least_reduced_and_applies_live(monkeypatch) -> None:
    monkeypatch.delenv("UE_NO_ANIMATIONS", raising=False)
    import winsys
    from qtapp.theme import ThemeController

    theme = ThemeController({"animationsprofil": "full"})
    monkeypatch.setattr(winsys, "client_area_animations", lambda: True)
    theme.refresh_system()
    assert theme.effectiveProfile == "full" and theme.profileNote == ""
    monkeypatch.setattr(winsys, "client_area_animations", lambda: False)
    theme.refresh_system()
    assert theme.effectiveProfile == "reduced" and "Reduziert" in theme.profileNote
    theme.setProfile("off")
    assert theme.effectiveProfile == "off"


def test_theme_tokens_accents_and_modes() -> None:
    from qtapp.theme import ThemeController, valid_accent

    theme = ThemeController({"theme": "dark", "accent": "#C239B3"})
    assert theme.dark and theme.accentChoice == "#C239B3"
    assert valid_accent("kaputt") == "system" and valid_accent("#00ff00") == "#00FF00"
    colors = dict(theme.colors)
    theme.setMode("light")
    assert not theme.dark and theme.colors != colors
    assert {"accent", "text", "layer", "card"} <= set(theme.colors)
    assert any(item["system"] for item in theme.accents)


def test_settings_watcher_collects_notifications(monkeypatch) -> None:
    from qtapp import system
    from qtapp.timers import Timers

    timers = Timers()
    calls = []
    watcher = system.SettingsWatcher(timers.later, lambda: calls.append(1))
    for _ in range(5):
        watcher.notify()
    assert wait_until(lambda: calls, 2)
    pump(0.3)
    assert calls == [1] and watcher.notifications == 5  # gesammelt: einmal neu lesen


# --- Fensterlage ------------------------------------------------------------------------------------


def test_window_placement_is_always_on_a_screen() -> None:
    from PySide6.QtGui import QGuiApplication

    from qtapp.geometry import CONFIG_KEY, LEGACY_KEY, initial_placement

    area = QGuiApplication.primaryScreen().availableGeometry()
    fresh = initial_placement({})
    assert area.contains(fresh.rect().center()) and not fresh.maximized
    gone = initial_placement({CONFIG_KEY: {"x": 90000, "y": 90000, "w": 1000, "h": 700, "max": False}})
    assert area.intersects(gone.rect())
    width, height = max(760, min(900, area.width() - 20)), max(540, min(650, area.height() - 20))
    kept = initial_placement({CONFIG_KEY: {"x": area.x() + 10, "y": area.y() + 10, "w": width, "h": height, "max": True}})
    assert (kept.x, kept.y, kept.width, kept.height, kept.maximized) == (area.x() + 10, area.y() + 10, min(width, area.width()), min(height, area.height()), True)
    tiny = initial_placement({CONFIG_KEY: {"x": area.x(), "y": area.y(), "w": 200, "h": 100, "max": False}})
    assert tiny.width == min(1140, int(area.width() * 0.9))  # zu klein gespeichert: Standardgröße
    huge = initial_placement({CONFIG_KEY: {"x": area.x(), "y": area.y(), "w": area.width() * 3, "h": area.height() * 3, "max": False}})
    assert huge.width <= area.width() and huge.height <= area.height()  # passt auf den Bildschirm
    legacy = initial_placement({LEGACY_KEY: {"x": area.x() + 10, "y": area.y() + 10, "w": 1000, "h": 700, "max": False}})
    assert area.intersects(legacy.rect())
    broken = initial_placement({CONFIG_KEY: {"x": "a"}})
    assert area.contains(broken.rect().center())


# --- QML-Singletons je Engine ---------------------------------------------------------------------------


def test_singletons_are_per_engine_and_types_must_match() -> None:
    from PySide6.QtCore import QObject

    from qtapp import application

    class Erster(QObject):
        pass

    class Zweiter(QObject):
        pass

    application.register_backend({"BridgeTestSingleton": Erster()})
    application.register_backend({"BridgeTestSingleton": Erster()})  # gleiche Art: erlaubt
    with pytest.raises(TypeError):
        application.register_backend({"BridgeTestSingleton": Zweiter()})


def test_app_controller_navigation_rules(backend) -> None:
    app = backend.app
    app.navigate("gibt-es-nicht")
    assert app.currentPage == "home"
    app.navigate("contracts")
    assert app.currentPage == "create" and app.currentTool == "contracts"
    app.set_available("layout", False)
    app.navigate("layout")
    assert app.currentPage == "create"
    app.set_available("layout", True)
    app.navigate("layout")
    app.set_available("layout", False)  # sichtbare Seite gesperrt: zurück zur ersten verfügbaren
    assert app.currentPage == "create"
    app.set_available("layout", True)
    app.openShortcut(9)
    assert app.currentPage == "create"


def test_save_is_debounced_and_drops_empty_keys(backend, config_file: Path) -> None:
    app = backend.app
    before = config_file.read_text(encoding="utf-8")
    for _ in range(10):
        app.schedule_save()
    assert app.timers.pending("autosave")
    assert config_file.read_text(encoding="utf-8") == before  # noch nicht gespeichert
    assert wait_until(lambda: not app.timers.pending("autosave"), 3)
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert "animationsprofil" in data and None not in data.values()


def test_copy_path_reports_empty_and_copies(backend) -> None:
    from PySide6.QtGui import QGuiApplication

    backend.app.copyPath("")
    assert backend.app.statusKind == "warning"
    backend.app.copyPath("C:/Daten/übersicht.pdf")
    assert QGuiApplication.clipboard().text() == "C:/Daten/übersicht.pdf" and backend.app.statusKind == "success"


def test_local_paths_from_drag_and_drop() -> None:
    from qtapp.files import local_paths

    assert local_paths(["file:///tmp/a%20b.pdf", "/tmp/c.xlsx", ""]) == ["/tmp/a b.pdf", "/tmp/c.xlsx"]
