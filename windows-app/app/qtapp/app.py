"""AppController: Navigation, Statuszeile, Hinweise, Speichern, Dateien und Tastenkürzel.

Der AppController stellt nur die gemeinsame Infrastruktur bereit. Was ein Werkzeug bei
Strg+Enter, Strg+O, Strg+F, F1 oder beim Ablegen einer Datei tut, entscheidet das Werkzeug
selbst (``ToolHooks``); Fachlogik steht in den Controllern der Werkzeuge.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable, Protocol, Sequence

from PySide6.QtCore import QObject, Property, Signal, Slot

from appstate import APP_NAME, DEVELOPER, ERROR_LOG, NEUERUNGEN, VERSION, State, major_minor, save_config
from tools.registry import CONTRACTS, REPAIR, TOOLS, tool_for_page

import winsys

from . import files
from .base import Observable, prop
from .dialogs import DialogService
from .notices import Action, NoticeCenter
from .tasks import Worker
from .timers import Timers

HOME = "home"
SETTINGS = "settings"
PAGES = (HOME, *(page for tool in TOOLS for page in tool.pages), SETTINGS)
SHORTCUT_TARGETS = (HOME, CONTRACTS.key, REPAIR.key, SETTINGS)  # Strg+1 … Strg+4
HOME_HINT = "Strg+2  Vertragsübersichten   ·   Strg+3  PDF reparieren"
SAVE_DELAY = 800
ABOUT_TEXT = (
    "Lokale Windows-App mit Werkzeugen für PDF-Dateien: Vertragsübersichten aus Excel-Listen "
    "erstellen sowie beschädigte PDF-Dateien analysieren und reparieren. Alle Dateien werden "
    "lokal auf diesem PC verarbeitet. Python und alle Pakete sind im Setup enthalten."
)
ABOUT_QUOTE = "„Ich beleidige seine Mutter, weil wenn ich seine Mutter beleidige, beleidige ich nur ihn oder maximal noch seine Mutter.“"
ABOUT_QUOTE_AUTHOR = "— Manuelsen"
HOME_STEPS = (
    "Auf der Startseite ein Werkzeug wählen – oder links in der Navigation unter »Tools«.",
    "»Vertragsübersichten« erstellt aus einer Excel-Liste eine PDF (Strg+2).",
    "»PDF reparieren« analysiert beschädigte PDF-Dateien und überträgt lesbare Inhalte in eine neue PDF (Strg+3).",
)
HOME_NOTES = (
    "Eine Datei kann auch direkt in das Fenster gezogen werden: Eine PDF öffnet »PDF reparieren«, eine Excel-Liste »Vertragsübersichten«.",
    "Design, Akzentfarbe, Mica und Animationen stehen unter »Einstellungen« (Strg+4).",
    "Alle Dateien werden lokal verarbeitet; es wird nichts hochgeladen.",
)
SEVERITY_TO_STATUS = {"success": "success", "error": "error", "warning": "warning", "info": "info", "neutral": "neutral"}


class ToolHooks(Protocol):
    """Was ein Werkzeug dem AppController anbietet (alle Methoden erhalten die sichtbare Seite)."""

    def primary_action(self, page: str) -> None: ...
    def open_action(self, page: str) -> None: ...
    def find_action(self, page: str) -> None: ...
    def show_help(self, page: str) -> None: ...
    def hint(self, page: str) -> str: ...
    def accepts(self, files: list[str], page: str) -> bool: ...
    def drag_enter(self, accepted: bool, page: str) -> None: ...
    def drag_leave(self) -> None: ...
    def drop(self, files: list[str], page: str) -> None: ...
    def page_prepare(self, page: str) -> None: ...
    def page_left(self, page: str) -> None: ...
    def config(self) -> dict: ...
    def autosave(self) -> None: ...
    def changed(self) -> None: ...
    def confirm_close(self) -> bool: ...
    def close(self) -> None: ...


class AppController(Observable):
    """Gemeinsame Infrastruktur aller Werkzeuge (in QML: ``App``)."""

    currentPageChanged, currentPage = prop(str, "currentPage", "")
    currentToolChanged, currentTool = prop(str, "currentTool", "")
    unavailablePagesChanged, unavailablePages = prop(list, "unavailablePages", [])
    navCompactChanged, navCompact = prop(bool, "navCompact", False)
    statusTextChanged, statusText = prop(str, "statusText", "Bereit")
    statusKindChanged, statusKind = prop(str, "statusKind", "neutral")
    statusSerialChanged, statusSerial = prop(int, "statusSerial", 0)
    hintChanged, hint = prop(str, "hint", HOME_HINT)
    dragActiveChanged, dragActive = prop(bool, "dragActive", False)
    dragAcceptedChanged, dragAccepted = prop(bool, "dragAccepted", False)
    readyChanged, ready = prop(bool, "ready", False)

    closeAccepted = Signal()  # QML schließt danach das Fenster
    focusRequested = Signal(str)  # Name eines Eingabefelds (z. B. »kd«), das den Fokus erhalten soll

    def __init__(self, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.state = State(cfg)
        self.timers = Timers(self, on_exception=self.report_exception)
        self.worker = Worker(self, on_exception=self.report_exception)
        self.notices = NoticeCenter(self.timers, self)
        self.dialogs = DialogService(self)
        self.window = None  # QQuickWindow (nach dem Laden von QML)
        self.geometry = None  # WindowState (Fensterlage)
        self.theme = None  # ThemeController
        self.chrome = "none"  # Titelleiste: »mica«, »solid« oder »none«
        self.closing = False
        self._tools: dict[str, ToolHooks] = {}
        self._config_parts: list[Callable[[], dict]] = []
        self._at_shutdown: list[Callable[[], None]] = []
        self._last_page: dict[str, str] = {}
        self._dirs = {key: str(cfg.get(f"ordner_{key}") or "") for key in ("excel", "logo")}
        self.set_quietly("navCompact", bool(cfg.get("nav_kompakt", False)))
        self.navigations = 0  # Seitenwechsel (Tests, Diagnose)

    # Konstante Angaben für QML ------------------------------------------------------------
    def _app_name(self) -> str:
        return APP_NAME

    def _version(self) -> str:
        return VERSION

    def _developer(self) -> str:
        return DEVELOPER

    def _tools_list(self) -> list[dict]:
        return [
            {"key": tool.key, "title": tool.title, "description": tool.description, "icon": tool.icon, "shortcut": tool.shortcut, "pages": list(tool.pages)}
            for tool in TOOLS
        ]

    _constant = Signal()
    appName = Property(str, _app_name, notify=_constant)
    version = Property(str, _version, notify=_constant)
    developer = Property(str, _developer, notify=_constant)
    tools = Property(list, _tools_list, notify=_constant)

    # Werkzeuge ---------------------------------------------------------------------------------
    def register_tool(self, key: str, hooks: ToolHooks) -> None:
        self._tools[key] = hooks
        self._config_parts.append(hooks.config)

    def register_config(self, part: Callable[[], dict]) -> None:
        """Weitere Einstellungen, die beim Speichern gesammelt werden (Design, Kundenakte …)."""
        self._config_parts.append(part)

    def at_shutdown(self, callback: Callable[[], None]) -> None:
        """Beim Beenden aufräumen (z. B. Beobachtung der Windows-Einstellungen beenden)."""
        self._at_shutdown.append(callback)

    def tool(self, key: str) -> ToolHooks | None:
        return self._tools.get(key)

    def _page_tool(self, page: str | None = None) -> tuple[str, ToolHooks | None]:
        info = tool_for_page(page if page is not None else self.currentPage)
        if info is None:
            return "", None
        return info.key, self._tools.get(info.key)

    # Navigation -----------------------------------------------------------------------------------
    def available(self, page: str) -> bool:
        return page in PAGES and page not in self.unavailablePages

    def set_available(self, page: str, available: bool) -> None:
        """Seite zulassen bzw. sperren (z. B. »Kunden« nur mit Kundenakte)."""
        blocked = [key for key in self.unavailablePages if key != page]
        if not available:
            blocked.append(page)
        self.unavailablePages = blocked
        if not available:
            for item, last in list(self._last_page.items()):
                if last == page:
                    del self._last_page[item]
            if self.currentPage == page:
                info = tool_for_page(page)
                self.navigate(self._page_for(info.key) if info else HOME)

    def _page_for(self, key: str) -> str:
        """Seite zu einem Navigationseintrag: die zuletzt gezeigte bzw. die erste verfügbare."""
        info = next((tool for tool in TOOLS if tool.key == key), None)
        if info is None:
            return key
        last = self._last_page.get(key)
        if last and self.available(last):
            return last
        return next((page for page in info.pages if self.available(page)), info.pages[0])

    @Slot(str)
    def navigate(self, key: str) -> None:
        """Seite bzw. Werkzeug öffnen. Die Zielseite wird vorbereitet, bevor QML sie zeigt."""
        page = self._page_for(key)
        if not self.available(page) or page == self.currentPage:
            return
        previous = self.currentPage
        if previous:
            _tool, hooks = self._page_tool(previous)
            if hooks is not None:
                hooks.page_left(previous)
        tool_key, hooks = self._page_tool(page)
        if hooks is not None:
            hooks.page_prepare(page)
        if tool_key:
            self._last_page[tool_key] = page
        self.navigations += 1
        self.currentTool = tool_key
        self.currentPage = page
        self.refresh_hint()

    @Slot(str)
    def openTool(self, key: str) -> None:  # noqa: N802 - QML-Schreibweise
        self.navigate(key)

    @Slot(int)
    def openShortcut(self, number: int) -> None:  # noqa: N802
        if 1 <= number <= len(SHORTCUT_TARGETS):
            self.navigate(SHORTCUT_TARGETS[number - 1])

    @Slot(bool)
    def setNavCompact(self, compact: bool) -> None:  # noqa: N802
        if bool(compact) != self.navCompact:
            self.navCompact = bool(compact)
            self.schedule_save()

    def refresh_hint(self) -> None:
        _key, hooks = self._page_tool()
        self.hint = hooks.hint(self.currentPage) if hooks is not None else HOME_HINT

    # Tastenkürzel ------------------------------------------------------------------------------------
    @Slot()
    def primaryAction(self) -> None:  # noqa: N802
        _key, hooks = self._page_tool()
        if hooks is not None:
            hooks.primary_action(self.currentPage)

    @Slot()
    def openAction(self) -> None:  # noqa: N802
        _key, hooks = self._page_tool()
        if hooks is not None:
            hooks.open_action(self.currentPage)

    @Slot()
    def findAction(self) -> None:  # noqa: N802
        _key, hooks = self._page_tool()
        if hooks is not None:
            hooks.find_action(self.currentPage)

    @Slot()
    def showHelp(self) -> None:  # noqa: N802
        """F1: Kurzanleitung des sichtbaren Werkzeugs – sonst ein Überblick."""
        _key, hooks = self._page_tool()
        if hooks is not None:
            hooks.show_help(self.currentPage)
        else:
            self.show_steps(f"Kurzanleitung – {APP_NAME}", HOME_STEPS, HOME_NOTES)

    def show_steps(self, title: str, steps: Sequence[str], notes: Sequence[str] = ()) -> None:
        self.dialogs.show("steps", title, {"steps": list(steps), "notes": list(notes)}, width=560)

    @Slot()
    def showAbout(self) -> None:  # noqa: N802
        self.dialogs.show(
            "about",
            "Über",
            {"name": APP_NAME, "version": VERSION, "developer": DEVELOPER, "text": ABOUT_TEXT, "quote": ABOUT_QUOTE, "author": ABOUT_QUOTE_AUTHOR},
            width=520,
        )

    @Slot()
    def showChangelog(self) -> None:  # noqa: N802
        self.dialogs.show("changelog", f"Neu in Version {VERSION}", {"items": list(NEUERUNGEN)}, width=540)

    def after_start(self) -> None:
        """Nach dem ersten Bild: Neuerungen einer neuen Version einmal zeigen."""
        self.ready = True
        if major_minor(self.state.gesehen) != major_minor(VERSION):
            self.timers.later("changelog", 500, self._show_news)

    def _show_news(self) -> None:
        self.state.gesehen = VERSION
        self.persist()
        self.showChangelog()

    # Ziehen und Ablegen (das sichtbare Werkzeug entscheidet) ---------------------------------------------
    def _drop_target(self, paths: list[str]) -> str | None:
        key, hooks = self._page_tool()
        if hooks is not None:
            return key if hooks.accepts(paths, self.currentPage) else None
        # Startseite und Einstellungen: nach Dateiart
        for tool_key in (CONTRACTS.key, REPAIR.key):
            other = self._tools.get(tool_key)
            if other is not None and other.accepts(paths, ""):
                return tool_key
        return None

    @Slot("QVariantList", result=bool)
    def dragEnter(self, urls: list) -> bool:  # noqa: N802
        paths = files.local_paths(urls)
        target = self._drop_target(paths)
        self.dragActive = True
        self.dragAccepted = target is not None
        key, hooks = self._page_tool()
        if hooks is not None:
            hooks.drag_enter(target is not None, self.currentPage)
        elif target is not None:
            self.set_status("Loslassen: eine PDF öffnet »PDF reparieren«, eine Excel-Liste »Vertragsübersichten«.", "info")
        return target is not None

    @Slot()
    def dragLeave(self) -> None:  # noqa: N802
        self.dragActive = False
        self.dragAccepted = False
        for hooks in self._tools.values():
            hooks.drag_leave()

    @Slot("QVariantList")
    def drop(self, urls: list) -> None:
        paths = files.local_paths(urls)
        target = self._drop_target(paths)
        self.dragLeave()
        page_tool, _hooks = self._page_tool()
        key = target or page_tool or CONTRACTS.key
        hooks = self._tools.get(key)
        if hooks is None:
            return
        if page_tool != key:
            self.navigate(key)
        hooks.drop(paths, self.currentPage)

    # Fensterrahmen ----------------------------------------------------------------------------------------
    def apply_chrome(self) -> None:
        """Titelleiste (DWM) in das Design einbinden: dunkel/hell, Farbe der App oder Mica."""
        if self.window is None or self.theme is None:
            return
        palette = self.theme.palette
        self.chrome = winsys.apply_window_chrome(int(self.window.winId()), palette.dark, caption=palette.mica, text=palette.text, mica=self.theme.micaWanted())

    # Status und Hinweise ------------------------------------------------------------------------------------
    def set_status(self, text: str, kind: str = "neutral") -> None:
        """Statuszeile: busy (mit Fortschrittsring), success, error, warning, info, neutral."""
        self.statusKind = kind if kind in ("busy", "success", "error", "warning", "info", "neutral") else "neutral"
        self.statusText = str(text)
        self.statusSerial = self.statusSerial + 1

    def notify(self, area: str, severity: str, message: str, title: str = "", actions: Sequence[Action] = (), status: bool = True, auto_hide: int | None = None, animate: bool = True) -> None:
        self.notices.notify(area, severity, message, title, actions, auto_hide=auto_hide, animate=animate)
        if status:
            self.set_status(f"{title}: {message}" if title else message, SEVERITY_TO_STATUS.get(severity, "neutral"))

    def hide_notice(self, area: str, animate: bool = True) -> None:
        self.notices.hide(area, animate=animate)

    # Dateien ---------------------------------------------------------------------------------------------------
    def initial_dir(self, key: str, current: str) -> str:
        """Startordner der Dateiauswahl: Ordner der aktuellen Datei, sonst der zuletzt verwendete."""
        return files.start_dir(current, self._dirs.get(key, ""))

    def remember_dir(self, key: str, path: str) -> None:
        folder = str(Path(path).parent)
        if self._dirs.get(key) != folder:
            self._dirs[key] = folder
            self.schedule_save()

    def open_file(self, path: str | Path, area: str) -> None:
        """Datei mit dem Standardprogramm öffnen; Fehler erscheinen im Hinweisbereich ``area``."""
        path = Path(path)
        try:
            files.open_path(path)
            self.set_status(f"Geöffnet: {path.name}", "success")
        except OSError as exc:
            self.notify(area, "error", str(exc), title="Datei konnte nicht geöffnet werden")

    def open_folder_of(self, path: str | Path, area: str) -> None:
        try:
            files.open_path(Path(path).parent)
        except OSError as exc:
            self.notify(area, "error", str(exc), title="Ordner konnte nicht geöffnet werden")

    @Slot(str)
    def copyPath(self, path: str) -> None:  # noqa: N802
        """Vollständigen Pfad in die Zwischenablage kopieren."""
        text = str(path or "").strip()
        if not text:
            self.set_status("Kein Pfad zum Kopieren vorhanden.", "warning")
            return
        try:
            files.copy_text(text)
        except Exception as exc:  # noqa: BLE001 - Zwischenablage nicht verfügbar
            self.set_status(f"Pfad konnte nicht kopiert werden: {exc}", "error")
            return
        self.set_status(f"Pfad kopiert: {text}", "success")

    def copy_path(self, path) -> None:
        self.copyPath(str(path or ""))

    def copy_text(self, text: str, done: str) -> None:
        try:
            files.copy_text(text)
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Kopieren nicht möglich: {exc}", "error")
            return
        self.set_status(done, "success")

    # Fehler -------------------------------------------------------------------------------------------------------
    def write_error_log(self, text: str) -> None:
        try:
            ERROR_LOG.write_text(text, encoding="utf-8")
        except OSError:
            pass

    def report_exception(self, text: str) -> None:
        """Unerwarteter Fehler in einer Rückmeldung: protokollieren und in der Statuszeile nennen."""
        self.write_error_log(text)
        last = text.strip().splitlines()[-1] if text.strip() else "Unbekannter Fehler"
        try:
            self.set_status(f"Unerwarteter Fehler: {last} – Details in fehler.log", "error")
        except RuntimeError:
            pass

    # Speichern ---------------------------------------------------------------------------------------------------
    def schedule_save(self) -> None:
        """Änderungen verzögert speichern (800 ms nach der letzten Änderung, nicht bei jedem Tastendruck)."""
        if self.closing:
            return
        self.timers.later("autosave", SAVE_DELAY, self._autosave)
        for hooks in self._tools.values():
            hooks.changed()

    @Slot()
    def scheduleSave(self) -> None:  # noqa: N802
        self.schedule_save()

    def _autosave(self) -> None:
        if self.closing:
            return
        for hooks in self._tools.values():
            hooks.autosave()
        self.persist()

    def persist(self) -> None:
        self.timers.cancel("autosave")
        data = dict(self.cfg)
        for part in self._config_parts:
            data.update(part())
        data.update(
            {
                "gesehen": self.state.gesehen,
                "nav_kompakt": bool(self.navCompact),
                "ordner_excel": self._dirs.get("excel", ""),
                "ordner_logo": self._dirs.get("logo", ""),
            }
        )
        if self.geometry is not None:
            data.update(self.geometry.config())
        # ``None`` bedeutet: Schlüssel entfernen (z. B. »animationen« folgt Windows)
        data = {key: value for key, value in data.items() if value is not None}
        self.cfg = data
        save_config(data)

    # Beenden ------------------------------------------------------------------------------------------------------
    @Slot(result=bool)
    def requestClose(self) -> bool:  # noqa: N802
        """Fenster soll schließen: Werkzeuge dürfen nachfragen (z. B. laufender Stapel)."""
        if self.closing:
            return True
        for hooks in self._tools.values():
            if not hooks.confirm_close():
                return False
        self.shutdown()
        return True

    def shutdown(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.timers.cancel("autosave")
        try:
            for hooks in self._tools.values():
                try:
                    hooks.close()
                except Exception:  # noqa: BLE001 - Beenden darf nicht scheitern
                    self.write_error_log(traceback.format_exc())
            self.persist()
        finally:
            for callback in self._at_shutdown:
                try:
                    callback()
                except Exception:  # noqa: BLE001
                    self.write_error_log(traceback.format_exc())
            self.dialogs.shutdown()
            self.timers.shutdown()
            self.worker.shutdown()
