"""PDF Tool – Hauptfenster (Windows-App mit Fluent-Oberfläche).

Das Hauptfenster stellt die gemeinsame Infrastruktur: Fenster, Design, Mica,
Navigation, Statuszeile, Hinweise, Dialoge, Speichern. Die Werkzeuge liegen in
eigenen Paketen unter ``tools/``:

* ``tools/contract_overview`` – Vertragsübersichten aus Excel-Listen
* ``tools/pdf_repair`` – beschädigte PDF-Dateien analysieren und reparieren

Die Version steht nur in ``windows-app/VERSION``. Der Modulname ``vertragdesk``
bleibt aus Kompatibilitätsgründen (Starter, Tests) bestehen.
"""

from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path
from types import SimpleNamespace
from tkinter import filedialog  # noqa: F401 - Tests ersetzen Dateidialoge über dieses Modul
import tkinter as tk

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from appstate import (  # noqa: E402
    APP_NAME,
    DEVELOPER,
    ERROR_LOG,
    ICON_FILE,
    NEUERUNGEN,
    VERSION,
    State,
    desktop_dir,
    load_config,
    major_minor,
    save_config,
)
from tools.contract_overview import page_create, page_customers, page_layout, page_preview  # noqa: E402
from tools.contract_overview.batch import page as page_batch  # noqa: E402
from tools.contract_overview.controller import BATCH_HINT  # noqa: E402
from tools.contract_overview.controller import HINT as CONTRACT_HINT  # noqa: E402
from tools.contract_overview.controller import ContractOverviewTool  # noqa: E402
from tools.pdf_repair import page as page_repair  # noqa: E402
from tools.pdf_repair.page import RepairTool  # noqa: E402
from tools.registry import CONTRACTS, REPAIR, TOOLS, tool_for_page  # noqa: E402
from ui import context as ui_context  # noqa: E402
from ui import dialogs, icons, windows  # noqa: E402
from ui.mica import MicaSource  # noqa: E402
from ui.navigation import NavigationView, NavItem  # noqa: E402
from ui.pages import home as page_home  # noqa: E402
from ui.pages import settings as page_settings  # noqa: E402
from ui.scroll import install_wheel_router  # noqa: E402
from ui.tasks import Worker  # noqa: E402
from ui.theme import SYSTEM_ACCENT, THEME_DARK, THEME_LIGHT, THEME_SYSTEM, ThemeManager, px, rgb  # noqa: E402
from ui.widgets import Text, frame  # noqa: E402

__all__ = ["App", "main", "VERSION", "APP_NAME"]

NAV = (
    NavItem("home", "Start", icons.HOME),
    NavItem("tools", "Tools", header=True),
    *(NavItem(tool.key, tool.title, tool.glyph, pages=tool.pages) for tool in TOOLS),
    NavItem("settings", "Einstellungen", icons.SETTINGS, footer=True),
)
# Strg+1 … Strg+4
SHORTCUT_TARGETS = ("home", CONTRACTS.key, REPAIR.key, "settings")
HOME_HINT = "Strg+2  Vertragsübersichten   ·   Strg+3  PDF reparieren"
ABOUT_TEXT = (
    "Lokale Windows-App mit Werkzeugen für PDF-Dateien: Vertragsübersichten aus Excel-Listen "
    "erstellen sowie beschädigte PDF-Dateien analysieren und reparieren. Alle Dateien werden "
    "lokal auf diesem PC verarbeitet. Python und alle Pakete sind im Setup enthalten."
)
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


def _valid_accent(value) -> str:
    if value == SYSTEM_ACCENT:
        return SYSTEM_ACCENT
    try:
        rgb(str(value))
        return str(value).upper() if str(value).startswith("#") and len(str(value)) == 7 else SYSTEM_ACCENT
    except (ValueError, IndexError):
        return SYSTEM_ACCENT


class App(ContractOverviewTool, tk.Tk):
    app_name = APP_NAME
    version = VERSION
    developer = DEVELOPER

    def __init__(self) -> None:
        super().__init__(className="PDF-Tool")
        self.withdraw()
        # Excel-Prüfung, PDF-Erstellung und Vorschau laufen in Threads. Mit einem kürzeren Wechselintervall
        # kommt die Oberfläche nach jedem Tk-Aufruf schneller wieder an die Reihe und bleibt flüssig.
        sys.setswitchinterval(0.001)
        # Rahmenfenster jetzt anlegen (noch unsichtbar und leer): Titelleiste und Mica
        # lassen sich so vor dem ersten Anzeigen einstellen.
        self.update_idletasks()
        self.title(APP_NAME)
        cfg = load_config()
        self.cfg = cfg
        self.state = State(cfg)

        theme_mode = cfg.get("theme") if cfg.get("theme") in (THEME_SYSTEM, THEME_LIGHT, THEME_DARK) else THEME_SYSTEM
        accent = _valid_accent(cfg.get("accent", SYSTEM_ACCENT))
        # Design, Akzentfarbe und Schriften stehen fest, bevor das erste Widget entsteht.
        self.theme = ThemeManager(self, theme_mode, accent)
        self._anim_pref = cfg.get("animationen") if isinstance(cfg.get("animationen"), bool) else None
        animations = self._animations_wanted()
        self.ctx = ui_context.init(self, self.theme, animations, reduce_motion=not windows.client_area_animations())
        # Während des unsichtbaren Aufbaus läuft keine Animation (kein gestaffeltes Einblenden).
        self.ctx.anim.suspend()
        if ICON_FILE.is_file():
            try:
                self.iconbitmap(default=str(ICON_FILE))
            except tk.TclError:
                pass

        self.var_mica = tk.BooleanVar(self, bool(cfg.get("mica", True)))
        self.var_anim = tk.BooleanVar(self, animations)
        # zuletzt verwendete Ordner für die Dateiauswahl
        self._dirs = {key: str(cfg.get(f"ordner_{key}") or "") for key in ("excel", "logo")}
        self._drop: windows.DropTarget | None = None
        # Werkzeuge – jedes mit eigenen Daten
        self._init_contract_overview(cfg)
        self.repair = RepairTool(self, cfg)
        self.ui = SimpleNamespace()
        self.worker = Worker(self)
        self.mica = MicaSource()
        self._chrome = "none"
        self._active = True
        self._hook: windows.WindowHook | None = None
        self._closing = False
        self._page = ""
        self._start_zoomed = False
        self._start_position: tuple[int, int] | None = None
        # Das Mica-Material (Desktophintergrund) lädt parallel zum Aufbau der Oberfläche.
        self._mica_thread = self._start_mica_load()

        self.configure(bg=self.theme.palette.mica)
        install_wheel_router(self)
        # Alle Seiten werden jetzt aufgebaut – das Fenster ist noch verborgen.
        self.nav = NavigationView(
            self,
            list(NAV),
            {
                "home": lambda host: page_home.build(self, host),
                "create": lambda host: page_create.build(self, host),
                "batch": lambda host: page_batch.build(self, host),
                "layout": lambda host: page_layout.build(self, host),
                "preview": lambda host: page_preview.build(self, host),
                "customers": lambda host: page_customers.build(self, host),
                "repair": lambda host: page_repair.build(self, host),
                "settings": lambda host: page_settings.build(self, host),
            },
            on_change=self._page_changed,
            compact=bool(cfg.get("nav_kompakt", False)),
            status_hint=HOME_HINT,
            on_layout=self._layout_changed,
            title=APP_NAME,
        )
        self.nav.pack(fill="both", expand=True)
        self.theme.subscribe(self._theme_changed)
        # Nach dem Start zeigt PDF Tool die Startseite mit allen Werkzeugen.
        self.nav.navigate("home", animate=False)
        self._start_contract_overview()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        for sequence in ("<Control-Return>", "<Control-KP_Enter>"):
            self.bind_all(sequence, lambda _e: (self._primary_action(), "break")[1])
        for sequence in ("<Control-o>", "<Control-O>"):
            self.bind_all(sequence, lambda _e: (self._open_action(), "break")[1])
        for sequence in ("<Control-f>", "<Control-F>"):
            self.bind_all(sequence, lambda _e: (self._find_action(), "break")[1])
        self.bind_all("<F1>", lambda _e: self.show_help())
        for number, key in enumerate(SHORTCUT_TARGETS, start=1):
            self.bind_all(f"<Control-Key-{number}>", lambda _e, k=key: self.open_tool(k))
        self.bind("<Activate>", self._on_activate, add="+")
        self.bind("<Deactivate>", self._on_deactivate, add="+")
        self.ctx.window_hooks.append(lambda _e: self._schedule_backdrop())

        self._restore_geometry()
        self._show_when_ready()
        self.after_idle(self._after_show)

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------
    def _show_when_ready(self) -> None:
        """Hauptfenster erst zeigen, wenn die Oberfläche vollständig aufgebaut ist.

        1. Titelleiste (DWM), Mica und Drag & Drop einrichten, solange nichts sichtbar ist
        2. Alle Seiten bei der endgültigen Fenstergröße abbilden, anordnen und zeichnen –
           unsichtbar (DWM-Cloaking bzw. außerhalb des Bildschirms), dann in einem Zug zeigen
        3. Nicht sichtbare Seiten aus dem Layout nehmen
        """
        if self._mica_thread is not None:
            self._mica_thread.join(0.4)
        self._apply_chrome()
        self._hook = windows.WindowHook(windows.frame_hwnd(self), lambda func: self.after(0, func), on_drop=self._on_drop, on_settings=self._on_system_settings)
        # OLE-Ablageziel: hebt den Dateibereich schon beim Hineinziehen hervor (sonst WM_DROPFILES).
        self._drop = windows.DropTarget(
            windows.frame_hwnd(self),
            lambda func: self.after(0, func),
            accept=self._accepts_drop,
            on_enter=self._drag_enter,
            on_leave=self._drag_leave,
            on_drop=self._on_drop,
        )
        ui_context.reveal(self, self.state_zoomed if self._start_zoomed else self.deiconify, position=self._start_position, prepare=False)
        self.nav.park_hidden_pages()
        self._schedule_backdrop()
        self.ctx.ready = True
        self.ctx.anim.resume()

    def _after_show(self) -> None:
        if self._mica_thread is not None and self._mica_thread.is_alive():
            self._wait_for_mica()
        if major_minor(self.state.gesehen) != major_minor(VERSION):
            self.after(500, self._zeige_neuerungen)

    def _start_mica_load(self) -> threading.Thread | None:
        if not self._mica_wanted():
            return None
        thread = threading.Thread(target=self.mica.load, name="mica", daemon=True)
        thread.start()
        return thread

    def _wait_for_mica(self) -> None:
        if self._closing:
            return
        if self._mica_thread is not None and self._mica_thread.is_alive():
            self.after(80, self._wait_for_mica)
            return
        self._update_backdrop()

    def _animations_wanted(self) -> bool:
        if os.environ.get("UE_NO_ANIMATIONS"):
            return False
        if self._anim_pref is None:
            return windows.client_area_animations()
        return bool(self._anim_pref)

    def _restore_geometry(self) -> None:
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        # Unterhalb dieser Größe lässt sich das Layout nicht sinnvoll anordnen.
        min_w, min_h = min(px(760), screen_w), min(px(540), screen_h)
        self.minsize(min_w, min_h)
        saved = self.cfg.get("fenster") if isinstance(self.cfg.get("fenster"), dict) else {}
        width = int(saved.get("w", 0) or 0)
        height = int(saved.get("h", 0) or 0)
        if width < min_w or height < min_h or width > screen_w or height > screen_h:
            width = min(px(1140), int(screen_w * 0.9))
            height = min(px(800), int(screen_h * 0.86))
        x = saved.get("x")
        y = saved.get("y")
        if not isinstance(x, int) or not isinstance(y, int) or x < -px(40) or y < 0 or x + width > screen_w + px(40) or y + height > screen_h:
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self._start_position = (x, y)
        # Maximiert wird erst beim Anzeigen – »zoomed« würde das Fenster sofort sichtbar machen.
        self._start_zoomed = bool(saved.get("max"))

    def state_zoomed(self) -> None:
        try:
            if sys.platform == "win32":
                self.wm_state("zoomed")
            else:
                self.deiconify()
                self.attributes("-zoomed", True)
        except tk.TclError:
            self.deiconify()

    def _geometry_config(self) -> dict:
        try:
            zoomed = self.wm_state() == "zoomed" or bool(self.attributes("-zoomed")) if sys.platform != "win32" else self.wm_state() == "zoomed"
        except tk.TclError:
            zoomed = False
        saved = self.cfg.get("fenster") if isinstance(self.cfg.get("fenster"), dict) else {}
        if zoomed:
            return {**saved, "max": True}
        return {"w": self.winfo_width(), "h": self.winfo_height(), "x": self.winfo_x(), "y": self.winfo_y(), "max": False}

    # ------------------------------------------------------------------
    # Fensterrahmen, Mica, Design
    # ------------------------------------------------------------------
    def mica_possible(self) -> bool:
        return windows.mica_supported()

    def _mica_wanted(self) -> bool:
        return bool(self.var_mica.get()) and self.mica_possible()

    def mica_description(self) -> str:
        if not self.mica_possible():
            return "Nicht verfügbar: erfordert Windows 11 mit aktivierten Transparenzeffekten."
        return "Titelleiste und Navigation erhalten den dezenten Farbton des Desktophintergrunds."

    def animation_description(self) -> str:
        system = windows.client_area_animations()
        base = "Übergänge, Einblendungen und Bewegungen."
        if self._anim_pref is None:
            return base + (" Folgt der Windows-Einstellung (an)." if system else " Folgt der Windows-Einstellung (aus).")
        return base

    def _apply_chrome(self) -> None:
        pal = self.theme.palette
        self.configure(bg=pal.mica)
        self._chrome = windows.apply_window_chrome(windows.frame_hwnd(self), pal.dark, caption=pal.mica, text=pal.text, mica=self._mica_wanted())
        self._update_backdrop()

    def _schedule_backdrop(self) -> None:
        if self._chrome == "mica":
            self.ctx.anim.later("backdrop", 180, self._update_backdrop)

    def _layout_changed(self) -> None:
        # Die Inhaltsebene hat sich verschoben: runde Ecke mit passendem Mica-Ausschnitt nachziehen.
        if getattr(self, "nav", None) is not None:
            self._schedule_backdrop()

    def _update_backdrop(self) -> None:
        if self._closing:
            return
        use = self._chrome == "mica" and self.mica.available and self._active and self._mica_wanted()
        pane = self.nav.pane
        if not use:
            self.nav.set_backdrop(None)
            self.nav.layer.set_mica_corner(None)
            return
        rects = windows.monitor_rects(windows.frame_hwnd(self))
        if not rects:
            self.nav.set_backdrop(None)
            return
        monitor = rects[0]
        dark = self.theme.palette.dark
        x0, y0 = pane.winfo_rootx(), pane.winfo_rooty()
        width = px(240)
        height = max(pane.winfo_height(), self.winfo_screenheight() // 2)
        image = self.mica.region((x0, y0, x0 + width, y0 + height), (width, height), monitor, dark)
        self.nav.set_backdrop(image)
        layer = self.nav.layer
        lx, ly = layer.winfo_rootx(), layer.winfo_rooty()
        r = px(8)
        self.nav.layer.set_mica_corner(self.mica.region((lx, ly, lx + r, ly + r), (r, r), monitor, dark))

    def _on_activate(self, event) -> None:
        if event.widget is self and not self._active:
            self._active = True
            self._update_backdrop()

    def _on_deactivate(self, event) -> None:
        if event.widget is self and self._active:
            self._active = False
            # Wie Windows: inaktive Fenster zeigen die einfarbige Grundfläche statt Mica.
            self._update_backdrop()

    def _theme_changed(self) -> None:
        self._apply_chrome()
        page_settings.refresh(self)

    def set_theme(self, mode: str) -> None:
        self.theme.set(mode=mode)
        self.persist()
        labels = {THEME_SYSTEM: "wie Windows", THEME_LIGHT: "hell", THEME_DARK: "dunkel"}
        self.set_status(f"App-Design: {labels.get(mode, mode)}", "success")

    def set_accent(self, value: str) -> None:
        self.theme.set(accent=value)
        page_settings.refresh(self)
        self.persist()

    def apply_mica_setting(self) -> None:
        if self._mica_wanted() and not self.mica.available:
            self.worker.run(self.mica.load, lambda _ok: self._apply_chrome())
        self._apply_chrome()
        self.persist()

    def apply_animation_setting(self) -> None:
        self._anim_pref = bool(self.var_anim.get())
        self.ctx.anim.animations_enabled = self._anim_pref
        page_settings.refresh(self)
        self.persist()

    def _on_system_settings(self, area: str) -> None:
        # Design, Akzentfarbe, Hintergrundbild oder Animationseinstellung könnten sich geändert haben.
        self.ctx.anim.later("syschange", 300, self._reload_system_settings)

    def _reload_system_settings(self) -> None:
        self.ctx.anim.reduce_motion = not windows.client_area_animations()
        if self._anim_pref is None:
            self.ctx.anim.animations_enabled = self._animations_wanted()
            self.var_anim.set(self.ctx.anim.enabled)
        self.theme.set(force=True)
        if self._mica_wanted():
            self.worker.run(self.mica.load, lambda _ok: self._apply_chrome())

    def _page_changed(self, key: str) -> None:
        previous, self._page = self._page, key
        if key == "settings":
            page_settings.refresh(self)
        tool = tool_for_page(key)
        hint = {CONTRACTS.key: CONTRACT_HINT, REPAIR.key: page_repair.HINT}.get(tool.key if tool else "", HOME_HINT)
        self.nav.status.set_hint(BATCH_HINT if key == "batch" else hint)
        # Die Auswahlleisten aller Ansichten von »Vertragsübersichten« zeigen dieselbe Ansicht.
        if key in CONTRACTS.pages:
            for view in CONTRACTS.pages:
                selector = getattr(self.ui, f"selector_{view}", None)
                if selector is not None:
                    selector.select(key)
        if previous == "customers" and key != "customers" and self.customer_page is not None:
            self.customer_page.flush()
        if previous == "batch" and key != "batch" and self.batch_page is not None:
            self.batch_page.flush()
        if previous == "preview" and key != "preview":
            self.preview_left()
        if key == "preview":
            self.preview_shown()

    # ------------------------------------------------------------------
    # Werkzeuge
    # ------------------------------------------------------------------
    def open_tool(self, key: str) -> None:
        """Werkzeug (bzw. Seite) öffnen – über Startseite, Navigation oder Strg+1…4."""
        self.nav.navigate(key)

    def current_tool(self) -> str | None:
        tool = tool_for_page(self.nav.current or "")
        return tool.key if tool else None

    def _primary_action(self) -> None:
        """Strg+Enter: Hauptaktion des sichtbaren Werkzeugs."""
        tool = self.current_tool()
        if self.nav.current == "batch":
            self.batch_start()
        elif tool == CONTRACTS.key:
            self.start_pdf()
        elif tool == REPAIR.key:
            self.repair.start_repair()

    def _find_action(self) -> None:
        """Strg+F: in »Vertragsübersichten« einen bekannten Kunden suchen."""
        if self.nav.current == "batch":
            # Im Stapel: Kunden für den geöffneten Eintrag wählen
            if self.batch_page is not None and self.batch_page.item_id:
                self.batch_choose_customer(self.batch_page.item_id)
        elif self.current_tool() == CONTRACTS.key:
            self.find_customer()

    def _open_action(self) -> None:
        """Strg+O: Datei für das sichtbare Werkzeug wählen."""
        tool = self.current_tool()
        if self.nav.current == "batch":
            self.pick_batch_files()
        elif tool == CONTRACTS.key:
            self.pick_excel()
        elif tool == REPAIR.key:
            self.repair.pick()

    # Ziehen und Ablegen – das sichtbare Werkzeug entscheidet ------------------------
    def _drop_target(self, files: list[str]) -> str | None:
        tool = self.current_tool()
        if tool == REPAIR.key:
            return REPAIR.key if self.repair.accepts(files) else None
        if tool == CONTRACTS.key:
            return CONTRACTS.key if self.contract_accepts(files) else None
        # Startseite und Einstellungen: nach Dateiart
        if self.contract_accepts(files):
            return CONTRACTS.key
        if self.repair.accepts(files):
            return REPAIR.key
        return None

    def _accepts_drop(self, files: list[str]) -> bool:
        return self._drop_target(files) is not None

    def _drag_enter(self, accepted: bool) -> None:
        tool = self.current_tool()
        if tool == REPAIR.key:
            if accepted:
                self.repair.ui.drop.set_highlight(True)
        elif tool == CONTRACTS.key:
            self._contract_drag_enter(accepted)
        elif accepted:
            self.set_status("Loslassen: eine PDF öffnet »PDF reparieren«, eine Excel-Liste »Vertragsübersichten«.", "info")

    def _drag_leave(self) -> None:
        drop = getattr(self.repair.ui, "drop", None)
        if drop is not None:
            drop.set_highlight(False)
        self._contract_drag_leave()

    def _on_drop(self, dateien: list[str]) -> None:
        target = self._drop_target(dateien)
        self._drag_leave()
        if target == REPAIR.key:
            if self.current_tool() != REPAIR.key:
                self.open_tool(REPAIR.key)
            self.repair.drop(dateien)
        elif target == CONTRACTS.key:
            self._contract_drop(dateien)
        elif self.current_tool() == REPAIR.key:
            self.repair.drop(dateien)
        else:
            self._contract_drop(dateien)

    # ------------------------------------------------------------------
    # Status und Hinweise
    # ------------------------------------------------------------------
    def set_status(self, text: str, kind: str = "neutral") -> None:
        """Statuszeile unten: busy (mit Fortschrittsring), success, error, warning, info, neutral."""
        status = getattr(self.nav, "status", None)
        if status is None:
            return
        try:
            status.set(text, kind)
        except tk.TclError:
            pass

    def notify(self, area: str, severity: str, message: str, title: str = "", actions=(), status: bool = True, auto_hide: int | None = None, animate: bool = True) -> None:
        bar = getattr(self.ui, area, None)
        if bar is not None:
            try:
                if bar.winfo_exists():
                    self.ctx.anim.cancel_later(f"hide:{area}")
                    bar.show(severity, message, title, actions, animate=animate)
                    if auto_hide:
                        self.ctx.anim.later(f"hide:{area}", auto_hide, bar.hide)
            except tk.TclError:
                pass
        if status:
            self.set_status(f"{title}: {message}" if title else message, SEVERITY_TO_STATUS.get(severity, "neutral"))

    def hide_notice(self, area: str) -> None:
        bar = getattr(self.ui, area, None)
        if bar is not None:
            try:
                bar.hide()
            except tk.TclError:
                pass

    # ------------------------------------------------------------------
    # Dateien
    # ------------------------------------------------------------------

    def _initial_dir(self, key: str, current: str) -> str:
        """Startordner für die Dateiauswahl: Ordner der aktuellen Datei, sonst der zuletzt verwendete."""
        for candidate in (current, self._dirs.get(key, "")):
            if not candidate:
                continue
            path = Path(candidate)
            folder = path if path.is_dir() else path.parent
            if folder.is_dir():
                return str(folder)
        return str(desktop_dir())

    def _remember_dir(self, key: str, path: str) -> None:
        folder = str(Path(path).parent)
        if self._dirs.get(key) != folder:
            self._dirs[key] = folder
            self.schedule_save()

    def open_file(self, path: str | Path, area: str) -> None:
        """Datei mit dem Standardprogramm öffnen; Fehler erscheinen im Hinweisbereich ``area``."""
        path = Path(path)
        try:
            windows.open_path(path)
            self.set_status(f"Geöffnet: {path.name}", "success")
        except OSError as exc:
            self.notify(area, "error", str(exc), title="Datei konnte nicht geöffnet werden")

    def open_folder_of(self, path: str | Path, area: str) -> None:
        try:
            windows.open_path(Path(path).parent)
        except OSError as exc:
            self.notify(area, "error", str(exc), title="Ordner konnte nicht geöffnet werden")

    def write_error_log(self, text: str) -> None:
        _write_log(text)

    def copy_path(self, path: str | Path) -> None:
        """Vollständigen Pfad in die Windows-Zwischenablage kopieren."""
        text = str(path or "").strip()
        if not text:
            self.set_status("Kein Pfad zum Kopieren vorhanden.", "warning")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except tk.TclError as exc:
            self.set_status(f"Pfad konnte nicht kopiert werden: {exc}", "error")
            return
        self.set_status(f"Pfad kopiert: {text}", "success")

    # ------------------------------------------------------------------
    # Speichern
    # ------------------------------------------------------------------
    def schedule_save(self) -> None:
        """Änderungen verzögert speichern (800 ms nach der letzten Änderung, nicht bei jedem Tastendruck)."""
        if self._closing:
            return
        self.ctx.anim.later("autosave", 800, self._autosave)
        self._contract_changed()

    # Kopf- und Fußzeile melden Änderungen über denselben verzögerten Weg.
    schedule_text_save = schedule_save

    def _autosave(self) -> None:
        if self._closing:
            return
        self._contract_autosave()
        self.persist()

    # ------------------------------------------------------------------
    # Dialoge
    # ------------------------------------------------------------------
    def show_changelog(self) -> None:
        def build(holder) -> None:
            for punkt in NEUERUNGEN:
                row = frame(holder)
                row.pack(fill="x", pady=(0, px(6)))
                Text(row, "•", style="body", color="accent_text").pack(side="left", anchor="n", padx=(0, px(8)))
                Text(row, punkt, style="body", wrap=True).pack(side="left", fill="x", expand=True)

        dialogs.info(self, f"Neu in Version {VERSION}", build=build, icon=ICON_FILE, width=520)

    def _zeige_neuerungen(self) -> None:
        self.state.gesehen = VERSION
        self.persist()
        self.show_changelog()

    def show_help(self) -> None:
        """F1: Kurzanleitung des sichtbaren Werkzeugs – auf der Startseite ein Überblick."""
        tool = self.current_tool()
        if tool == CONTRACTS.key:
            self.show_contract_help()
        elif tool == REPAIR.key:
            self.show_steps("Kurzanleitung – PDF reparieren", page_repair.HELP_STEPS, page_repair.HELP_NOTES)
        else:
            self.show_steps(f"Kurzanleitung – {APP_NAME}", HOME_STEPS, HOME_NOTES)

    def show_steps(self, title: str, steps, notes=()) -> None:
        def build(holder) -> None:
            for number, schritt in enumerate(steps, start=1):
                row = frame(holder)
                row.pack(fill="x", pady=(0, px(6)))
                Text(row, f"{number}.", style="body_strong", color="accent_text").pack(side="left", anchor="n", padx=(0, px(8)))
                Text(row, schritt, style="body", wrap=True).pack(side="left", fill="x", expand=True)
            if notes:
                Text(holder, "Hinweise", style="body_strong").pack(anchor="w", pady=(px(10), px(4)))
                for hinweis in notes:
                    Text(holder, hinweis, style="caption", color="text2", wrap=True).pack(anchor="w", fill="x", pady=(0, px(3)))

        dialogs.info(self, title, build=build, icon=ICON_FILE, width=540)

    def show_about(self) -> None:
        def build(holder) -> None:
            from PIL import Image

            from ui.render import to_photo

            row = frame(holder)
            row.pack(fill="x")
            if ICON_FILE.is_file():
                try:
                    image = Image.open(ICON_FILE)
                    size = px(64)
                    image = image.convert("RGBA").resize((size, size), Image.LANCZOS)
                    photo = to_photo(holder, image)
                    label = tk.Label(row, image=photo, bd=0)
                    label.image = photo  # type: ignore[attr-defined]
                    self.theme.style(label, bg="dialog")
                    label.pack(side="left", anchor="n", padx=(0, px(16)))
                except Exception:
                    pass
            texts = frame(row)
            texts.pack(side="left", fill="x", expand=True)
            Text(texts, APP_NAME, style="body_large").pack(anchor="w")
            Text(texts, f"Version {VERSION}", style="body", color="text2").pack(anchor="w")
            Text(texts, f"Entwickler und Inhaber: {DEVELOPER}", style="body", color="text2").pack(anchor="w", pady=(px(2), 0))
            Text(holder, ABOUT_TEXT, style="body", wrap=True).pack(anchor="w", fill="x", pady=(px(16), 0))
            quote = frame(holder)
            quote.pack(fill="x", pady=(px(14), 0))
            bar = tk.Frame(quote, width=px(3), bd=0)
            self.theme.style(bar, bg="accent")
            bar.pack(side="left", fill="y", padx=(0, px(12)))
            Text(quote, "„Ich beleidige seine Mutter, weil wenn ich seine Mutter beleidige, beleidige ich nur ihn oder maximal noch seine Mutter.“", style="body", color="text2", wrap=True).pack(anchor="w", fill="x")
            Text(quote, "— Manuelsen", style="caption", color="text3").pack(anchor="w", pady=(px(4), 0))

        dialogs.info(self, "Über", build=build, icon=ICON_FILE, width=500)

    # ------------------------------------------------------------------
    # Speichern und Beenden
    # ------------------------------------------------------------------
    def persist(self) -> None:
        # Ein ausstehendes verzögertes Speichern ist damit erledigt.
        self.ctx.anim.cancel_later("autosave")
        data = dict(self.cfg)
        data.update(self.contract_config())
        data.update(self.repair.config())
        data.update(
            {
                "gesehen": self.state.gesehen,
                "theme": self.theme.mode,
                "accent": self.theme.accent_choice,
                "mica": bool(self.var_mica.get()),
                "nav_kompakt": bool(self.nav.user_compact) if hasattr(self, "nav") else False,
                "ordner_excel": self._dirs.get("excel", ""),
                "ordner_logo": self._dirs.get("logo", ""),
            }
        )
        if self._anim_pref is None:
            data.pop("animationen", None)
        else:
            data["animationen"] = self._anim_pref
        try:
            if self.winfo_ismapped():
                data["fenster"] = self._geometry_config()
        except tk.TclError:
            pass
        self.cfg = data
        save_config(data)

    def _on_close(self) -> None:
        if self._closing:
            return
        if not self.batch_confirm_close():
            return
        self._closing = True
        self.ctx.anim.cancel_later("autosave")
        try:
            self._contract_close()
            self.persist()
        finally:
            # Ein laufender Reparaturprozess wird beendet; sein Arbeitsordner wird gelöscht.
            if self.repair.job is not None:
                self.repair.job.cancel()
            self.ctx.anim.shutdown()
            self.worker.shutdown()
            if self._drop is not None:
                self._drop.remove()
            if self._hook is not None:
                self._hook.remove()
            self.destroy()

    def report_callback_exception(self, exc, val, tb) -> None:  # noqa: D401 - Tk-Schnittstelle
        text = "".join(traceback.format_exception(exc, val, tb))
        self.write_error_log(text)
        try:
            self.set_status(f"Unerwarteter Fehler: {val} – Details in fehler.log", "error")
        except Exception:
            pass


def _write_log(text: str) -> None:
    try:
        ERROR_LOG.write_text(text, encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    windows.enable_dpi_awareness()
    windows.register_app_identity()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
