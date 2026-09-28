"""Übersichten-Ersteller – Windows-App mit Fluent-Oberfläche.

Dieses Modul verbindet Oberfläche (Paket ``ui``), gespeicherte Daten
(``appstate``) und PDF-Erzeugung (``engine``). Die Version steht nur in
``windows-app/VERSION``.
"""

from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path
from types import SimpleNamespace
from tkinter import filedialog
import tkinter as tk

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from appstate import (  # noqa: E402
    APP_NAME,
    DEFAULT_DATEINAME,
    DEFAULT_LOGO,
    DEFAULT_LOGO_BREITE,
    DEFAULT_TITEL,
    DEFAULT_UNTERTITEL,
    DEVELOPER,
    ERROR_LOG,
    FOOTER_EXPLICIT,
    FOOTER_FORMAT,
    HEADER_FORMAT,
    ICON_FILE,
    NEUERUNGEN,
    VERSION,
    State,
    baustein_rich,
    customer_footer_rich,
    customer_header_rich,
    default_footer_rich,
    desktop_dir,
    footer_rich_from,
    header_rich_from,
    load_config,
    major_minor,
    save_config,
)
from richtext import RichText  # noqa: E402
from ui import context as ui_context  # noqa: E402
from ui import dialogs, icons, windows  # noqa: E402
from ui.mica import MicaSource  # noqa: E402
from ui.navigation import NavigationView, NavItem  # noqa: E402
from ui.pages import create as page_create  # noqa: E402
from ui.pages import layout as page_layout  # noqa: E402
from ui.pages import settings as page_settings  # noqa: E402
from ui.scroll import install_wheel_router  # noqa: E402
from ui.tasks import Worker  # noqa: E402
from ui.theme import SYSTEM_ACCENT, THEME_DARK, THEME_LIGHT, THEME_SYSTEM, ThemeManager, px, rgb  # noqa: E402
from ui.widgets import Text, frame  # noqa: E402

__all__ = ["App", "main", "VERSION", "APP_NAME"]

PAGES = (
    NavItem("create", "Erstellen", icons.DOCUMENT),
    NavItem("layout", "Darstellung", icons.COLOR),
    NavItem("settings", "Einstellungen", icons.SETTINGS, footer=True),
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


class App(tk.Tk):
    app_name = APP_NAME
    version = VERSION
    developer = DEVELOPER

    def __init__(self) -> None:
        super().__init__(className="Uebersichten-Ersteller")
        self.withdraw()
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

        # Formularwerte (Namen und Bedeutung wie in 2.0.5) ------------------------------
        self.var_firma = tk.StringVar(self, cfg.get("firmenname", ""))
        self.var_kd = tk.StringVar(self, cfg.get("kundennummer", ""))
        self.var_mail = tk.StringVar(self, cfg.get("rechnungsempfaenger", ""))
        self.var_excel = tk.StringVar(self, cfg.get("excel", ""))
        self.var_logo = tk.StringVar(self, cfg.get("logo") or (str(DEFAULT_LOGO) if DEFAULT_LOGO.is_file() else ""))
        self.var_ziel = tk.StringVar(self, cfg.get("zielordner") or str(desktop_dir()))
        self.var_name = tk.StringVar(self, cfg.get("dateiname", DEFAULT_DATEINAME))
        self.var_format = tk.StringVar(self, cfg.get("format", "hoch") if cfg.get("format") in ("hoch", "quer") else "hoch")
        self.var_breite = tk.StringVar(self, str(cfg.get("logo_breite", DEFAULT_LOGO_BREITE)))
        self.var_titel = tk.StringVar(self, cfg.get("titel", DEFAULT_TITEL))
        self.var_untertitel = tk.StringVar(self, cfg.get("untertitel", DEFAULT_UNTERTITEL))
        self.var_open = tk.BooleanVar(self, bool(cfg.get("pdf_oeffnen", True)))
        self.var_baustein = tk.StringVar(self, cfg.get("baustein_name", ""))
        self.var_vorlage = tk.StringVar(self, "")
        self.var_regel_such = tk.StringVar(self, "")
        self.var_regel_zyk = tk.StringVar(self, "")
        self.var_mica = tk.BooleanVar(self, bool(cfg.get("mica", True)))
        self.var_anim = tk.BooleanVar(self, animations)
        # Kopf- und Fußzeile samt Formatierung. Ohne bewusst gespeicherte Fußzeile gilt die
        # Standard-Fußzeile (auch nach einem Update), ohne gespeicherte Formatierung das Standardformat.
        self._fuss_start: RichText = footer_rich_from(cfg)
        self._kopf_start: RichText = header_rich_from(cfg)
        self._excel_mails: list[str] = []
        # Ergebnis der Excel-Prüfung für die gewählte Datei (``None``: Prüfung läuft bzw. keine Datei)
        self._analysis: dict | None = None
        self._analysis_path = ""
        self._undo_overview: tuple[str, str, str, str] | None = None
        # zuletzt verwendete Ordner für die Dateiauswahl
        self._dirs = {key: str(cfg.get(f"ordner_{key}") or "") for key in ("excel", "logo")}
        self._drop: windows.DropTarget | None = None
        self._drag_saved: tuple | None = None
        self._ready_job = None
        self._recent_by_label: dict[str, dict] = {}
        self._pdf_by_label: dict[str, str] = {}
        self._undo_customer: tuple[str, str, str] | None = None
        self.busy = False
        self.kd_required = False
        self.ui = SimpleNamespace()
        self.worker = Worker(self)
        self.mica = MicaSource()
        self._chrome = "none"
        self._active = True
        self._hook: windows.WindowHook | None = None
        self._closing = False
        self._start_zoomed = False
        self._start_position: tuple[int, int] | None = None
        self._initial_check = False
        # Das Mica-Material (Desktophintergrund) lädt parallel zum Aufbau der Oberfläche.
        self._mica_thread = self._start_mica_load()

        self.configure(bg=self.theme.palette.mica)
        install_wheel_router(self)
        # Alle Seiten werden jetzt aufgebaut – das Fenster ist noch verborgen.
        self.nav = NavigationView(
            self,
            list(PAGES),
            {
                "create": lambda host: page_create.build(self, host),
                "layout": lambda host: page_layout.build(self, host),
                "settings": lambda host: page_settings.build(self, host),
            },
            on_change=self._page_changed,
            compact=bool(cfg.get("nav_kompakt", False)),
            status_hint="Strg+Enter  PDF erstellen   ·   Strg+O  Excel öffnen",
            on_layout=self._layout_changed,
        )
        self.nav.pack(fill="both", expand=True)
        self.theme.subscribe(self._theme_changed)
        self.nav.navigate("create", animate=False)

        # Eingaben automatisch speichern – verzögert, nicht bei jedem Tastendruck.
        for var in (
            self.var_firma, self.var_kd, self.var_mail, self.var_excel, self.var_logo, self.var_ziel,
            self.var_name, self.var_format, self.var_breite, self.var_titel, self.var_untertitel,
            self.var_open, self.var_baustein,
        ):
            var.trace_add("write", lambda *_a: self.schedule_save())
        # »Bereit zum Erstellen« folgt jeder Änderung einer Pflichtangabe.
        for var in (self.var_kd, self.var_mail, self.var_excel, self.var_logo, self.var_ziel, self.var_breite):
            var.trace_add("write", lambda *_a: self.update_readiness())
        self.update_readiness(now=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        for sequence in ("<Control-Return>", "<Control-KP_Enter>"):
            self.bind_all(sequence, lambda _e: (self.start_pdf(), "break")[1])
        for sequence in ("<Control-o>", "<Control-O>"):
            self.bind_all(sequence, lambda _e: (self.pick_excel(), "break")[1])
        self.bind_all("<F1>", lambda _e: self.show_help())
        for number, key in enumerate(("create", "layout", "settings"), start=1):
            self.bind_all(f"<Control-Key-{number}>", lambda _e, k=key: self.nav.navigate(k))
        self.bind("<Activate>", self._on_activate, add="+")
        self.bind("<Deactivate>", self._on_deactivate, add="+")
        self.ctx.window_hooks.append(lambda _e: self._schedule_backdrop())

        self._restore_geometry()
        # Eine gespeicherte Excel-Liste wird im Hintergrund geprüft; der Hinweis
        # »Excel wird geprüft …« gehört damit schon zum ersten sichtbaren Bild.
        excel = self.var_excel.get().strip()
        if excel and Path(excel).is_file():
            self._initial_check = True
            self.inspect_excel(excel)
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
            accept=lambda files: bool(_excel_in(files)),
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
        if key == "settings":
            page_settings.refresh(self)

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
    def refresh_files(self) -> None:
        from ui.components import path_caption

        rows = (
            ("row_excel", self.var_excel.get().strip(), "Keine Datei gewählt"),
            ("row_logo", self.var_logo.get().strip(), "Kein Logo gewählt"),
            ("row_ziel", self.var_ziel.get().strip(), "Keine Auswahl"),
        )
        for attr, value, empty in rows:
            row = getattr(self.ui, attr, None)
            if row is None:
                continue
            if attr == "row_ziel" and value:
                text, full = (Path(value).name or value), value
            else:
                text, full = path_caption(value, empty)
            row.set_value(text, full)

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

    def pick_excel(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Excel-Liste wählen",
            initialdir=self._initial_dir("excel", self.var_excel.get().strip()),
            filetypes=[("Excel", "*.xlsx *.xlsm *.xls"), ("Alle Dateien", "*.*")],
        )
        if path:
            self.use_excel(path)

    def use_excel(self, path: str) -> None:
        self._remember_dir("excel", path)
        self.var_excel.set(path)
        self.refresh_files()
        self.inspect_excel(path)

    def pick_logo(self) -> None:
        current = self.var_logo.get().strip()
        if current and Path(current).resolve().parent == DEFAULT_LOGO.resolve().parent:
            current = ""  # Standardlogo: lieber den zuletzt benutzten eigenen Ordner zeigen
        path = filedialog.askopenfilename(
            parent=self,
            title="Logo wählen",
            initialdir=self._initial_dir("logo", current),
            filetypes=[("Bilder", "*.png *.jpg *.jpeg *.webp"), ("Alle Dateien", "*.*")],
        )
        if path:
            self._remember_dir("logo", path)
            self.var_logo.set(path)
            self.refresh_files()
            self.set_status(f"Logo gewählt: {Path(path).name}", "success")

    def pick_ziel(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Zielordner für die PDF", initialdir=self._initial_dir("ziel", self.var_ziel.get().strip()))
        if path:
            self.var_ziel.set(path)
            self.refresh_files()
            self.set_status(f"Zielordner: {path}", "success")

    def target_folder(self) -> str:
        """Zielordner der PDF (ohne Auswahl: der Desktop)."""
        return self.var_ziel.get().strip() or str(desktop_dir())

    def use_default_logo(self) -> None:
        if DEFAULT_LOGO.is_file():
            self.var_logo.set(str(DEFAULT_LOGO))
            self.refresh_files()
            self.notify("dateien_info", "success", "Das Standardlogo wird verwendet.", auto_hide=4000)
        else:
            self.notify("dateien_info", "warning", "Es ist kein Standardlogo installiert.")

    def open_folder(self) -> None:
        ziel = self.var_ziel.get().strip()
        if not ziel or not Path(ziel).is_dir():
            self.notify("pdf_info", "warning", "Der Zielordner ist nicht vorhanden.", actions=(("Ordner wählen", self.pick_ziel),))
            return
        try:
            windows.open_path(ziel)
        except OSError as exc:
            self.notify("pdf_info", "error", str(exc), title="Ordner konnte nicht geöffnet werden")

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

    # Ziehen und Ablegen ---------------------------------------------------------------
    def _drag_enter(self, accepted: bool) -> None:
        """Datei wird über das Fenster gezogen: Excel-Bereich hervorheben."""
        if not accepted:
            return
        card = getattr(self.ui, "dateien_card", None)
        bar = getattr(self.ui, "info_excel", None)
        if self._drag_saved is None and bar is not None:
            self._drag_saved = (bar.severity, bar.message, bar.title)
        if card is not None:
            card.set_fill("card", stroke="accent")
        if bar is not None:
            bar.show("info", "Loslassen, um die Excel-Datei zu übernehmen und zu prüfen.", animate=False)
        if self.nav.current != "create":
            self.set_status("Excel-Datei loslassen – sie wird auf der Seite »Erstellen« geprüft.", "info")

    def _drag_leave(self) -> None:
        card = getattr(self.ui, "dateien_card", None)
        if card is not None:
            card.set_fill("card", stroke="card_stroke")
        saved, self._drag_saved = self._drag_saved, None
        bar = getattr(self.ui, "info_excel", None)
        if saved is not None and bar is not None and bar.message.startswith("Loslassen"):
            severity, message, title = saved
            bar.show(severity, message, title, animate=False)

    def _on_drop(self, dateien: list[str]) -> None:
        self._drag_leave()
        excel = next(iter(_excel_in(dateien)), "")
        if not excel:
            self.notify("info_excel", "warning", "Bitte eine Excel-Datei (.xlsx oder .xls) in das Fenster ziehen.")
            return
        if self.nav.current != "create":
            self.nav.navigate("create")
        self.use_excel(excel)

    # ------------------------------------------------------------------
    # Excel-Prüfung
    # ------------------------------------------------------------------
    def inspect_excel(self, path: str) -> None:
        self._analysis = None
        self._analysis_path = path
        self.notify("info_excel", "info", "Excel wird geprüft …", status=False)
        self.set_status("Excel wird geprüft …", "busy")
        self.update_readiness()
        regeln = [dict(r) for r in self.state.regeln]

        def work() -> dict:
            from engine import pruefe_excel

            return pruefe_excel(Path(path), regeln)

        def failed(exc, _tb) -> None:
            self._show_check(path, {"ok": False, "text": str(exc), "kunden": [], "mails": [], "firmen": [], "zeilen": []})

        self.worker.run(work, lambda result: self._show_check(path, result), failed)

    def _show_check(self, path: str, result: dict) -> None:
        if self.var_excel.get().strip() != path:
            return
        # Das Ergebnis der Prüfung beim Start erscheint ohne Ein-/Ausklapp-Animation.
        animate = not self._initial_check
        self._initial_check = False
        self._analysis = result
        self._analysis_path = path
        text = str(result.get("text", ""))
        if not result.get("ok"):
            self.notify("info_excel", "error", text or "Die Datei konnte nicht gelesen werden.", title="Excel-Prüfung fehlgeschlagen", animate=animate)
            self._set_mails([], animate=animate)
            self._show_facts([], animate)
            self.update_readiness()
            return
        mails = [str(mail) for mail in result.get("mails") or []]
        aktiv = int(result.get("aktiv", 0) or 0)
        inaktiv = int(result.get("inaktiv", 0) or 0)
        fehlend = [str(name) for name in result.get("fehlend") or []]
        vertraege = "1 aktiver Vertrag" if aktiv == 1 else f"{aktiv} aktive Verträge"
        if inaktiv:
            vertraege += f" · {inaktiv} inaktiv ausgeblendet"
        if fehlend:
            spalten = ", ".join(f"»{name}«" for name in fehlend)
            self.notify("info_excel", "error", f"Für die PDF fehlt {'die Spalte' if len(fehlend) == 1 else 'die Spalten'} {spalten}.", title="Spalten fehlen", status=False, animate=animate)
        elif aktiv == 0:
            self.notify("info_excel", "warning", "In der Datei steht kein aktiver Vertrag." + (f" {inaktiv} inaktive wurden ausgeblendet." if inaktiv else ""), title="Keine aktiven Verträge", status=False, animate=animate)
        else:
            self.notify("info_excel", "success", vertraege, title="Excel geprüft", status=False, animate=animate)
        self.set_status(f"Excel geprüft: {text}", "success" if aktiv and not fehlend else "warning")
        self._show_facts(self._facts_for(result), animate)
        self._set_mails(mails, animate=animate)
        # Nur Werte übernehmen, die tatsächlich in der Datei stehen – nie aus der E-Mail-Adresse raten.
        if not self.var_kd.get().strip() and len(result.get("kunden") or []) == 1:
            self.var_kd.set(result["kunden"][0])
        if not self.var_firma.get().strip() and len(result.get("firmen") or []) == 1:
            self.var_firma.set(result["firmen"][0])
        self.update_readiness()

    @staticmethod
    def _facts_for(result: dict) -> list[tuple[str, str, str]]:
        """Übersicht der Excel-Prüfung: nur Angaben, die tatsächlich in der Datei stehen."""
        facts: list[tuple[str, str, str]] = []
        aktiv = int(result.get("aktiv", 0) or 0)
        inaktiv = int(result.get("inaktiv", 0) or 0)
        facts.append(("Aktive Verträge", str(aktiv), "" if aktiv else "caution"))
        facts.append(("Ausgeblendet (inaktiv)", str(inaktiv), "muted"))
        mails = [str(mail) for mail in result.get("mails") or []]
        if len(mails) == 1:
            facts.append(("Rechnungsempfänger", mails[0], ""))
        elif len(mails) > 1:
            facts.append(("Rechnungsempfänger", f"{len(mails)} verschiedene – bitte bei den Kundendaten auswählen: " + ", ".join(mails), "caution"))
        else:
            facts.append(("Rechnungsempfänger", "keine Angabe in der Datei", "muted"))
        kunden = [str(kd) for kd in result.get("kunden") or []]
        if len(kunden) == 1:
            facts.append(("Kundennummer", f"{kunden[0]} (aus der Datei)", ""))
        elif len(kunden) > 1:
            facts.append(("Kundennummer", f"{len(kunden)} verschiedene in der Datei: " + ", ".join(kunden), "caution"))
        firmen = [str(firma) for firma in result.get("firmen") or []]
        if len(firmen) == 1:
            facts.append(("Firmenname", f"{firmen[0]} (aus der Datei)", ""))
        elif len(firmen) > 1:
            facts.append(("Firmenname", f"{len(firmen)} verschiedene in der Datei: " + ", ".join(firmen), "caution"))
        fett = int(result.get("fett", 0) or 0)
        if fett:
            facts.append(("Fettschrift", f"{fett} {'Zelle wird' if fett == 1 else 'Zellen werden'} fett in die PDF übernommen", "muted"))
        fehlend = [str(name) for name in result.get("fehlend") or []]
        if fehlend:
            facts.append(("Fehlende Spalten", ", ".join(fehlend), "critical"))
        for hinweis in result.get("hinweise") or []:
            facts.append(("Hinweis", str(hinweis), "muted"))
        return facts

    def _show_facts(self, facts: list[tuple[str, str, str]], animate: bool = True) -> None:
        details = getattr(self.ui, "excel_details", None)
        facts_list = getattr(self.ui, "excel_facts", None)
        if details is None or facts_list is None:
            return
        facts_list.set(facts)
        if facts:
            details.expand(animate=animate)
        else:
            details.collapse(animate=animate)

    def _set_mails(self, mails: list[str], animate: bool = True) -> None:
        self._excel_mails = mails
        combo = getattr(self.ui, "mail_combo", None)
        area = getattr(self.ui, "mail_area", None)
        if combo is None or area is None:
            return
        if len(mails) > 1:
            combo.set_values(mails, keep=True)
            current = self.var_mail.get().strip()
            if current in mails:
                combo.set(current)
            area.expand(animate=animate)
        else:
            combo.set_values([], keep=False)
            area.collapse(animate=animate)

    def on_mail_pick(self, mail: str) -> None:
        """Empfänger aus der Excel wählen: übernimmt die Adresse in das Feld Rechnungsempfänger."""
        if mail:
            self.var_mail.set(mail)
            self.set_status(f"Rechnungsempfänger: {mail}", "success")

    # ------------------------------------------------------------------
    # Bereit zum Erstellen
    # ------------------------------------------------------------------
    def readiness(self) -> list[tuple[str, str]]:
        """Offene Punkte vor dem Erstellen als (Bereich, Text); leer = bereit.

        Bereich ``busy`` bedeutet: Die Excel-Prüfung läuft noch.
        """
        issues: list[tuple[str, str]] = []
        excel = self.var_excel.get().strip()
        if not excel:
            issues.append(("excel", "Excel-Datei fehlt"))
        elif not Path(excel).is_file():
            issues.append(("excel", "Excel-Datei nicht gefunden"))
        elif self._analysis_path != excel or self._analysis is None:
            issues.append(("busy", "Excel wird geprüft …"))
        elif not self._analysis.get("ok"):
            issues.append(("excel", "Excel-Datei konnte nicht gelesen werden"))
        elif self._analysis.get("fehlend"):
            fehlend = list(self._analysis.get("fehlend") or [])
            issues.append(("excel", f"Spalte »{fehlend[0]}« fehlt in der Excel" if len(fehlend) == 1 else f"{len(fehlend)} Spalten fehlen in der Excel"))
        elif not int(self._analysis.get("aktiv", 0) or 0):
            issues.append(("excel", "Keine aktiven Verträge in der Excel"))
        if not self.var_kd.get().strip():
            issues.append(("kd", "Kundennummer fehlt"))
        if len(self._excel_mails) > 1 and not self.var_mail.get().strip():
            issues.append(("mail", "Bitte Rechnungsempfänger auswählen"))
        logo = self.var_logo.get().strip()
        if not logo:
            issues.append(("logo", "Logo fehlt"))
        elif not Path(logo).is_file():
            issues.append(("logo", "Logo-Datei nicht gefunden"))
        if not _valid_width(self.var_breite.get()):
            issues.append(("breite", "Logo-Breite ungültig"))
        if not _target_reachable(self.target_folder()):
            issues.append(("ziel", "Zielordner nicht erreichbar"))
        return issues

    def update_readiness(self, now: bool = False) -> None:
        """Anzeige »Bereit zum Erstellen« aktualisieren – gesammelt im Leerlauf."""
        if now:
            self._run_readiness()
        elif self._ready_job is None:
            try:
                self._ready_job = self.after_idle(self._run_readiness)
            except tk.TclError:
                self._ready_job = None

    def _run_readiness(self) -> None:
        self._ready_job = None
        line = getattr(self.ui, "ready", None)
        if line is None:
            return
        issues = self.readiness()
        if not issues:
            line.set("success", "Bereit zum Erstellen")
        elif issues[0][0] == "busy" and len(issues) == 1:
            line.set("busy", issues[0][1])
        else:
            texts = [text for area, text in issues if area != "busy"]
            more = len(texts) - 2
            label = " · ".join(texts[:2]) + (f" · {more} weitere" if more > 0 else "")
            kind = "critical" if any(area == "excel" for area, _t in issues) and self.var_excel.get().strip() else "caution"
            line.set(kind, label)

    def fix_readiness(self) -> None:
        """Zum ersten offenen Punkt springen (Klick auf die Bereitschaftsanzeige)."""
        issues = [issue for issue in self.readiness() if issue[0] != "busy"]
        if not issues:
            return
        area, text = issues[0]
        if area == "excel":
            if self.var_excel.get().strip() and Path(self.var_excel.get().strip()).is_file():
                self.notify("pdf_info", "warning", text, actions=(("Andere Excel wählen", self.pick_excel),))
            else:
                self.pick_excel()
        elif area == "kd":
            self.kd_required = True
            field = getattr(self.ui, "field_kd", None)
            if field is not None:
                field.set_error(True)
                field.focus()
        elif area == "mail":
            combo = getattr(self.ui, "mail_combo", None)
            if combo is not None:
                combo.focus_set()
                combo.open_popup()
        elif area == "logo":
            self.notify("pdf_info", "warning", text, actions=(("Logo wählen", self.pick_logo), ("Standardlogo", self.use_default_logo)))
        elif area == "breite":
            self.nav.navigate("layout")
            self.after(50, lambda: self._require(False, "Die Logo-Breite muss eine positive Zahl sein (z. B. 62).", getattr(self.ui, "field_breite", None), page="layout"))
        elif area == "ziel":
            self.notify("pdf_info", "warning", text, actions=(("Ordner wählen", self.pick_ziel),))

    # ------------------------------------------------------------------
    # Kundenakte
    # ------------------------------------------------------------------
    def reload_recent(self) -> None:
        combo = getattr(self.ui, "recent_combo", None)
        self._recent_by_label = self.state.customer_labels()
        if combo is None:
            return
        combo.set_values(list(self._recent_by_label), keep=False)
        combo.set_placeholder("Kunden aus dem Verlauf wählen" if self._recent_by_label else "Noch keine Einträge")

    def on_recent_pick(self, label: str) -> None:
        eintrag = self._recent_by_label.get(label)
        if eintrag:
            self._apply_customer(eintrag)
        combo = getattr(self.ui, "recent_combo", None)
        if combo is not None:
            combo.set(None)

    def _apply_customer(self, eintrag: dict) -> None:
        self.var_firma.set(eintrag.get("firmenname", ""))
        self.var_kd.set(eintrag.get("kundennummer", ""))
        self.var_mail.set(eintrag.get("rechnungsempfaenger", ""))
        excel = str(eintrag.get("excel") or "").strip()
        if excel and Path(excel).is_file():
            self.var_excel.set(excel)
            self.refresh_files()
            self.inspect_excel(excel)
        logo = str(eintrag.get("logo") or "").strip()
        if logo and Path(logo).is_file():
            self.var_logo.set(logo)
            self.refresh_files()
        # Nur eine sinnvolle eigene Fußzeile der Kundenakte übernehmen (samt Formatierung) –
        # ein leerer Wert aus älteren Versionen lässt die aktuell gültige Fußzeile stehen.
        fusszeile = customer_footer_rich(eintrag)
        if fusszeile is not None:
            self._set_rich("txt_fuss", "_fuss_start", fusszeile)
        kopfzeile = customer_header_rich(eintrag)
        if kopfzeile is not None:
            self._set_rich("txt_kopf", "_kopf_start", kopfzeile)
        pdf = str(eintrag.get("pdf") or "").strip()
        if pdf and Path(pdf).is_file():
            self._remember_pdf(Path(pdf))
        self.set_status(f"Kundenakte übernommen: {eintrag.get('firmenname') or eintrag.get('kundennummer')}", "success")

    def _remember_customer(self, pdf: str | None = None) -> None:
        fuss = self.footer_rich()
        kopf = self.header_rich()
        if self.state.remember_customer(
            self.var_firma.get(),
            self.var_kd.get(),
            self.var_mail.get(),
            self.var_excel.get(),
            self.var_logo.get(),
            fuss.text,
            kopf.text,
            pdf,
            fusszeile_format=fuss.to_dict(),
            kopfzeile_format=kopf.to_dict(),
        ):
            self.reload_recent()

    def clear_customer(self) -> None:
        previous = (self.var_firma.get(), self.var_kd.get(), self.var_mail.get())
        self.var_firma.set("")
        self.var_kd.set("")
        self.var_mail.set("")
        if any(value.strip() for value in previous):
            self._undo_customer = previous
            self.notify("kunde_info", "info", "Kundendaten wurden geleert.", actions=(("Rückgängig", self._undo_clear),), auto_hide=8000)

    def _undo_clear(self) -> None:
        if self._undo_customer:
            firma, kd, mail = self._undo_customer
            self.var_firma.set(firma)
            self.var_kd.set(kd)
            self.var_mail.set(mail)
            self._undo_customer = None
            self.hide_notice("kunde_info")
            self.set_status("Kundendaten wiederhergestellt.", "success")

    def clear_history(self) -> None:
        if not dialogs.confirm(self, "Verlauf löschen?", "Die Listen »Zuletzt verwendet« und »Zuletzt erstellt« werden geleert. Erstellte PDF-Dateien bleiben erhalten.", "Verlauf löschen", icon=ICON_FILE):
            return
        self.state.kunden = []
        self.state.pdfs = []
        self.reload_recent()
        self.reload_pdfs()
        self.persist()
        self.notify("settings_info", "success", "Der Verlauf wurde gelöscht.", auto_hide=5000)

    # ------------------------------------------------------------------
    # Zuletzt erstellte PDFs
    # ------------------------------------------------------------------
    def reload_pdfs(self) -> None:
        self._pdf_by_label = self.state.existing_pdfs()
        combo = getattr(self.ui, "pdf_combo", None)
        if combo is None:
            return
        labels = list(self._pdf_by_label)
        combo.set_values(labels, keep=False)
        if labels:
            combo.set(labels[0])
        combo.set_placeholder("Noch keine PDF erstellt")

    def _remember_pdf(self, path: Path) -> None:
        self.state.remember_pdf(str(path))
        self.reload_pdfs()

    def open_recent_pdf(self) -> None:
        combo = getattr(self.ui, "pdf_combo", None)
        pfad = self._pdf_by_label.get(combo.get()) if combo is not None else None
        if not pfad or not Path(pfad).is_file():
            self.notify("pdf_info", "warning", "Keine gespeicherte PDF zum Öffnen.")
            return
        self._open_pdf(Path(pfad))

    def _open_pdf(self, path: Path) -> None:
        try:
            windows.open_path(path)
            self.set_status(f"Geöffnet: {path.name}", "success")
        except OSError as exc:
            self.notify("pdf_info", "error", str(exc), title="PDF konnte nicht geöffnet werden")

    def _open_folder_of(self, path: Path) -> None:
        try:
            windows.open_path(path.parent)
        except OSError as exc:
            self.notify("pdf_info", "error", str(exc), title="Ordner konnte nicht geöffnet werden")

    # ------------------------------------------------------------------
    # Kopf- und Fußzeile, Textbausteine
    # ------------------------------------------------------------------
    def header_rich(self) -> RichText:
        """Aktuelle Kopfzeile mit Formatierung (Inhalt des Editors; vorher der geladene Wert)."""
        widget = getattr(self.ui, "txt_kopf", None)
        if widget is None:
            return self._kopf_start
        return widget.get_rich()

    def footer_rich(self) -> RichText:
        """Aktuelle Fußzeile mit Formatierung – exakt mit allen Zeilenumbrüchen."""
        widget = getattr(self.ui, "txt_fuss", None)
        if widget is None:
            return self._fuss_start
        return widget.get_rich()

    def header_text(self) -> str:
        return self.header_rich().text

    def footer_text(self) -> str:
        """Aktuelle Fußzeile als reiner Text: immer der Inhalt des Editors, exakt.

        Nur bevor der Editor existiert, gilt der geladene Startwert.
        """
        return self.footer_rich().text

    def _set_rich(self, widget_name: str, start_name: str, rich: RichText) -> None:
        setattr(self, start_name, rich)
        widget = getattr(self.ui, widget_name, None)
        if widget is not None:
            widget.set_rich(rich)

    def save_header(self) -> None:
        self._kopf_start = self.header_rich()
        self.persist()
        if not self._kopf_start.is_blank():
            self.notify("kopf_info", "success", "Die Kopfzeile wurde gespeichert.", auto_hide=5000)
        else:
            self.notify("kopf_info", "info", "Die Kopfzeile ist leer und erscheint nicht in der PDF.", auto_hide=6000)

    def save_footer(self) -> None:
        name = self.var_baustein.get().strip()
        rich = self.footer_rich()  # aktueller Inhalt des Editors samt Formatierung
        self._fuss_start = rich
        if name:
            self.state.save_baustein(name, rich.text, rich.to_dict())
        self.persist()
        self.reload_bausteine()
        if name:
            self.notify("fuss_info", "success", f"Die Fußzeile und der Textbaustein „{name}“ wurden gespeichert.", auto_hide=5000)
        else:
            self.notify("fuss_info", "success", "Die Fußzeile wurde gespeichert.", auto_hide=5000)

    def restore_default_footer(self) -> None:
        """Standardtext und Standardformatierung wiederherstellen (rückgängig machbar, daher ohne Rückfrage)."""
        previous = self.footer_rich()
        default = default_footer_rich()
        widget = getattr(self.ui, "txt_fuss", None)
        if widget is not None:
            widget.replace_rich(default)
        self._fuss_start = default
        self.persist()
        actions = ()
        if previous != default:
            actions = (("Rückgängig", lambda: self._undo_footer(previous)),)
        self.notify("fuss_info", "success", "Standard-Fußzeile wiederhergestellt.", actions=actions, auto_hide=8000)

    def _undo_footer(self, previous: RichText) -> None:
        widget = getattr(self.ui, "txt_fuss", None)
        if widget is not None:
            widget.replace_rich(previous)
        self._fuss_start = previous
        self.persist()
        self.hide_notice("fuss_info")
        self.set_status("Vorherige Fußzeile wiederhergestellt.", "success")

    def schedule_save(self) -> None:
        """Änderungen verzögert speichern (800 ms nach der letzten Änderung, nicht bei jedem Tastendruck)."""
        if self._closing:
            return
        self.ctx.anim.later("autosave", 800, self._autosave)

    # Kopf- und Fußzeile melden Änderungen über denselben verzögerten Weg.
    schedule_text_save = schedule_save

    def _autosave(self) -> None:
        if self._closing:
            return
        self._fuss_start = self.footer_rich()
        self._kopf_start = self.header_rich()
        self.persist()

    def reload_bausteine(self) -> None:
        combo = getattr(self.ui, "baustein_combo", None)
        if combo is None:
            return
        labels = [str(eintrag.get("name", "")) for eintrag in self.state.bausteine]
        combo.set_values(labels, keep=False)
        current = self.var_baustein.get().strip()
        combo.set(current if current in labels else None)
        combo.set_placeholder("Textbaustein wählen" if labels else "Noch kein Textbaustein")

    def on_baustein_pick(self, label: str) -> None:
        eintrag = self.state.find_baustein(label)
        if eintrag:
            self._apply_baustein(eintrag)

    def _apply_baustein(self, eintrag: dict) -> None:
        self.var_baustein.set(str(eintrag.get("name", "")))
        # Alte Bausteine (nur Text) erhalten die Standardformatierung.
        self._set_rich("txt_fuss", "_fuss_start", baustein_rich(eintrag))
        self.schedule_save()
        self.set_status(f"Textbaustein „{eintrag.get('name', '')}“ geladen.", "success")

    def delete_baustein(self) -> None:
        name = self.var_baustein.get().strip()
        if not name:
            self.notify("fuss_info", "warning", "Bitte zuerst einen Textbaustein wählen oder seinen Namen eintragen.")
            return
        if self.state.find_baustein(name) is None:
            self.notify("fuss_info", "warning", f"Kein Textbaustein mit dem Namen „{name}“.")
            return
        if not dialogs.confirm(self, "Textbaustein löschen?", f"Der Textbaustein „{name}“ wird dauerhaft entfernt.", "Löschen", icon=ICON_FILE):
            return
        self.state.delete_baustein(name)
        self.var_baustein.set("")
        self.persist()
        self.reload_bausteine()
        self.notify("fuss_info", "success", f"Textbaustein „{name}“ gelöscht.", auto_hide=5000)

    # ------------------------------------------------------------------
    # Vorlagen
    # ------------------------------------------------------------------
    def reload_vorlagen(self) -> None:
        combo = getattr(self.ui, "vorlage_combo", None)
        if combo is None:
            return
        labels = [str(eintrag.get("name", "")) for eintrag in self.state.vorlagen]
        combo.set_values(labels, keep=False)
        current = self.var_vorlage.get().strip()
        combo.set(current if current in labels else None)
        combo.set_placeholder("Vorlage wählen" if labels else "Noch keine Vorlage")

    def on_vorlage_pick(self, label: str) -> None:
        eintrag = self.state.find_vorlage(label)
        if eintrag:
            self._apply_vorlage(eintrag)

    def _apply_vorlage(self, eintrag: dict) -> None:
        self.var_vorlage.set(str(eintrag.get("name", "")))
        logo = str(eintrag.get("logo") or "").strip()
        if logo and Path(logo).is_file():
            self.var_logo.set(logo)
            self.refresh_files()
        if eintrag.get("format") in ("hoch", "quer"):
            self.var_format.set(str(eintrag.get("format")))
        if eintrag.get("dateiname"):
            self.var_name.set(str(eintrag.get("dateiname")))
        if eintrag.get("logo_breite"):
            self.var_breite.set(str(eintrag.get("logo_breite")))
        if eintrag.get("titel"):
            self.var_titel.set(str(eintrag.get("titel")))
        if eintrag.get("untertitel"):
            self.var_untertitel.set(str(eintrag.get("untertitel")))
        self._set_rich("txt_kopf", "_kopf_start", header_rich_from(eintrag))
        # Vorlage mit eigener Fußzeile: diese (mit Formatierung); alte Vorlage ohne gültigen Wert:
        # Standard. Fehlt die Formatierung (Vorlagen bis 2.1), gilt das Standardformat.
        self._set_rich("txt_fuss", "_fuss_start", footer_rich_from(eintrag))
        from appstate import normalize_regeln

        self.state.regeln = normalize_regeln(eintrag.get("regeln") or [])
        self.reload_regeln()
        self.persist()
        excel = self.var_excel.get().strip()
        if excel and Path(excel).is_file():
            self.inspect_excel(excel)
        self.notify("vorlagen_info", "success", f"Vorlage „{eintrag.get('name', '')}“ geladen.", auto_hide=5000)

    def save_vorlage(self) -> None:
        name = self.var_vorlage.get().strip()
        field = getattr(self.ui, "field_vorlage", None)
        if not name:
            if field is not None:
                field.set_error(True)
                field.focus()
            self.notify("vorlagen_info", "warning", "Bitte zuerst einen Namen für die Vorlage eintragen.")
            return
        if field is not None:
            field.set_error(False)
        kopf = self.header_rich()
        fuss = self.footer_rich()
        self.state.save_vorlage(
            {
                "name": name,
                "logo": self.var_logo.get().strip(),
                "format": self.var_format.get(),
                "dateiname": self.var_name.get().strip(),
                "logo_breite": self.var_breite.get().strip(),
                "titel": self.var_titel.get().strip(),
                "untertitel": self.var_untertitel.get().strip(),
                "kopfzeile": kopf.text,
                HEADER_FORMAT: kopf.to_dict(),
                "fusszeile": fuss.text,
                FOOTER_FORMAT: fuss.to_dict(),
                FOOTER_EXPLICIT: True,
                "regeln": [dict(regel) for regel in self.state.regeln],
            }
        )
        self.reload_vorlagen()
        self.persist()
        self.notify("vorlagen_info", "success", f"Die Vorlage „{name}“ wurde gespeichert.", auto_hide=5000)

    def delete_vorlage(self) -> None:
        name = self.var_vorlage.get().strip()
        if not name or self.state.find_vorlage(name) is None:
            self.notify("vorlagen_info", "warning", "Bitte zuerst eine gespeicherte Vorlage auswählen.")
            return
        if not dialogs.confirm(self, "Vorlage löschen?", f"Die Vorlage „{name}“ wird dauerhaft entfernt. Die aktuellen Einstellungen bleiben unverändert.", "Löschen", icon=ICON_FILE):
            return
        self.state.delete_vorlage(name)
        self.var_vorlage.set("")
        self.reload_vorlagen()
        self.persist()
        self.notify("vorlagen_info", "success", f"Vorlage „{name}“ gelöscht.", auto_hide=5000)

    def reset_pdf_settings(self) -> None:
        if not dialogs.confirm(self, "PDF-Einstellungen zurücksetzen?", "Titel, Untertitel, Dateiname, Logo-Breite und Seitenformat erhalten wieder ihre Standardwerte.", "Zurücksetzen", icon=ICON_FILE):
            return
        self.var_titel.set(DEFAULT_TITEL)
        self.var_untertitel.set(DEFAULT_UNTERTITEL)
        self.var_name.set(DEFAULT_DATEINAME)
        self.var_breite.set(DEFAULT_LOGO_BREITE)
        self.var_format.set("hoch")
        self.persist()
        self.notify("pdf_settings_info", "success", "Die Standardwerte wurden wiederhergestellt.", auto_hide=5000)

    # ------------------------------------------------------------------
    # Zyklus-Regeln
    # ------------------------------------------------------------------
    def reload_regeln(self) -> None:
        page_layout.render_rules(self)

    def edit_regel(self, regel: dict) -> None:
        self.var_regel_such.set(regel.get("enthaelt", ""))
        self.var_regel_zyk.set(regel.get("zyklus", ""))
        field = getattr(self.ui, "field_regel_zyk", None)
        if field is not None:
            field.focus()

    def add_regel(self) -> None:
        nadel = self.var_regel_such.get().strip()
        ziel = self.var_regel_zyk.get().strip()
        such_field = getattr(self.ui, "field_regel_such", None)
        zyk_field = getattr(self.ui, "field_regel_zyk", None)
        if not nadel or not ziel:
            if such_field is not None:
                such_field.set_error(not nadel)
            if zyk_field is not None:
                zyk_field.set_error(not ziel)
            self.notify("regeln_info", "warning", "Bitte Begriff und Zyklus eintragen, zum Beispiel Hott-KI und jährlich.")
            return
        for field in (such_field, zyk_field):
            if field is not None:
                field.set_error(False)
        self.state.add_regel(nadel, ziel)
        self.var_regel_such.set("")
        self.var_regel_zyk.set("")
        self.reload_regeln()
        self.persist()
        self._recheck_excel()
        self.notify("regeln_info", "success", f"Regel „{nadel}“ gespeichert.", auto_hide=5000)

    def delete_regel(self, index: int) -> None:
        if not (0 <= index < len(self.state.regeln)):
            return
        name = self.state.regeln[index]["enthaelt"]
        if not dialogs.confirm(self, "Regel löschen?", f"Die Zyklus-Regel „{name}“ wird entfernt.", "Löschen", icon=ICON_FILE):
            return
        self.state.delete_regel(index)
        self.reload_regeln()
        self.persist()
        self._recheck_excel()
        self.notify("regeln_info", "success", f"Regel „{name}“ gelöscht.", auto_hide=5000)

    def _recheck_excel(self) -> None:
        excel = self.var_excel.get().strip()
        if excel and Path(excel).is_file():
            self.inspect_excel(excel)

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

        dialogs.info(self, f"Neu in Version {'.'.join(major_minor(VERSION))}", build=build, icon=ICON_FILE, width=520)

    def _zeige_neuerungen(self) -> None:
        self.state.gesehen = VERSION
        self.persist()
        self.show_changelog()

    def show_help(self) -> None:
        schritte = (
            "Firmenname und Kundennummer eintragen oder unter »Zuletzt verwendet« wählen.",
            "Die Excel-Datei wählen (Strg+O) oder in das Fenster ziehen.",
            "Die Kurzinfo unter der Excel-Datei lesen: aktive Verträge, Kundennummer, Empfänger.",
            "Optional Logo, Zielordner sowie Kopf- und Fußzeile unter »Darstellung« setzen.",
            "Auf »PDF erstellen« klicken oder Strg+Enter drücken.",
        )
        hinweise = (
            "Stehen mehrere Rechnungsempfänger in der Excel, bitte einen auswählen.",
            "Zyklus-Regeln stehen unter »Darstellung«. Hott-KI wird standardmäßig jährlich ausgegeben.",
            "Zuletzt erstellte PDFs lassen sich auf der Seite »Erstellen« wieder öffnen.",
            "Hotline-Zeilen werden als Supportvertrag ausgegeben. Nur Netto, kein Brutto.",
        )

        def build(holder) -> None:
            for number, schritt in enumerate(schritte, start=1):
                row = frame(holder)
                row.pack(fill="x", pady=(0, px(6)))
                Text(row, f"{number}.", style="body_strong", color="accent_text").pack(side="left", anchor="n", padx=(0, px(8)))
                Text(row, schritt, style="body", wrap=True).pack(side="left", fill="x", expand=True)
            Text(holder, "Hinweise", style="body_strong").pack(anchor="w", pady=(px(10), px(4)))
            for hinweis in hinweise:
                Text(holder, hinweis, style="caption", color="text2", wrap=True).pack(anchor="w", fill="x", pady=(0, px(3)))

        dialogs.info(self, "Kurzanleitung", build=build, icon=ICON_FILE, width=540)

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
            Text(holder, "Lokale Windows-App für Vertragsübersichten aus Excel-Listen. Python und alle Pakete sind im Setup enthalten.", style="body", wrap=True).pack(anchor="w", fill="x", pady=(px(16), 0))
            quote = frame(holder)
            quote.pack(fill="x", pady=(px(14), 0))
            bar = tk.Frame(quote, width=px(3), bd=0)
            self.theme.style(bar, bg="accent")
            bar.pack(side="left", fill="y", padx=(0, px(12)))
            Text(quote, "„Ich beleidige seine Mutter, weil wenn ich seine Mutter beleidige, beleidige ich nur ihn oder maximal noch seine Mutter.“", style="body", color="text2", wrap=True).pack(anchor="w", fill="x")
            Text(quote, "— Manuelsen", style="caption", color="text3").pack(anchor="w", pady=(px(4), 0))

        dialogs.info(self, "Über", build=build, icon=ICON_FILE, width=500)

    # ------------------------------------------------------------------
    # PDF
    # ------------------------------------------------------------------
    def _require(self, ok: bool, message: str, field=None, actions=(), page: str = "create") -> bool:
        if ok:
            return True
        if self.nav.current != page:
            self.nav.navigate(page)
        if field is not None:
            try:
                field.set_error(True)
                field.focus()
            except (tk.TclError, AttributeError):
                pass
        self.notify("pdf_info" if page == "create" else "pdf_settings_info", "error", message, actions=actions)
        return False

    def start_pdf(self) -> None:
        if self.busy:
            return
        excel = self.var_excel.get().strip()
        logo = self.var_logo.get().strip()
        kd = self.var_kd.get().strip()
        if not self._require(bool(excel) and Path(excel).is_file(), "Bitte zuerst die Excel-Liste wählen.", actions=(("Excel wählen", self.pick_excel),)):
            return
        self.kd_required = True
        if not self._require(bool(kd), "Bitte die Kundennummer eintragen.", getattr(self.ui, "field_kd", None)):
            return
        if not self._require(bool(logo) and Path(logo).is_file(), "Bitte eine Logo-Datei wählen.", actions=(("Logo wählen", self.pick_logo), ("Standardlogo", self.use_default_logo))):
            return
        try:
            breite = float(self.var_breite.get().replace(",", "."))
            if breite <= 0:
                raise ValueError
        except ValueError:
            self.nav.navigate("layout")
            self.after(50, lambda: self._require(False, "Die Logo-Breite muss eine Zahl sein (z. B. 62).", getattr(self.ui, "field_breite", None), page="layout"))
            return
        empfaenger = self.var_mail.get().strip()
        if not empfaenger and len(self._excel_mails) > 1:
            combo = getattr(self.ui, "mail_combo", None)
            wahl = combo.get().strip() if combo is not None else ""
            if wahl not in self._excel_mails:
                if combo is not None:
                    combo.focus_set()
                self.notify("pdf_info", "warning", "In der Excel stehen mehrere Rechnungsempfänger. Bitte einen auswählen oder ins Feld eintragen.")
                return
            empfaenger = wahl
        regeln = [dict(eintrag) for eintrag in self.state.regeln]
        ziel = Path(self.target_folder())
        fuss = self.footer_rich()
        kopf = self.header_rich()
        auftrag = dict(
            excel=Path(excel),
            logo=Path(logo),
            kundennummer=kd,
            firmenname=self.var_firma.get().strip(),
            rechnungsempfaenger=empfaenger,
            zielordner=ziel,
            dateiname=self.var_name.get().strip(),
            seitenformat=self.var_format.get(),
            logo_breite=breite,
            titel=self.var_titel.get().strip() or DEFAULT_TITEL,
            untertitel=self.var_untertitel.get().strip() or DEFAULT_UNTERTITEL,
            fusszeile=fuss.text,
            fusszeile_format=fuss.to_dict(),
            kopfzeile=kopf.text,
            kopfzeile_format=kopf.to_dict(),
            regeln=regeln,
        )
        self.persist()
        self.busy = True
        self.hide_notice("pdf_info")
        button = getattr(self.ui, "btn_pdf", None)
        if button is not None:
            button.set_busy(True, "PDF wird erstellt …")
        self.set_status("PDF wird erstellt …", "busy")

        def work():
            from engine import PdfAuftrag, erstelle_pdf

            return erstelle_pdf(PdfAuftrag(**auftrag, pdf_oeffnen=False, status=lambda msg: self.worker.post(self.set_status, msg, "busy")))

        self.worker.run(work, self._done, self._fail)

    def _finish_busy(self) -> None:
        self.busy = False
        button = getattr(self.ui, "btn_pdf", None)
        if button is not None:
            button.set_busy(False)

    def _done(self, path: Path) -> None:
        self._finish_busy()
        path = Path(path)
        self._remember_pdf(path)
        self._remember_customer(str(path))
        self.persist()
        self.notify(
            "pdf_info",
            "success",
            path.name,
            title="PDF wurde erfolgreich erstellt.",
            actions=(
                ("Öffnen", lambda: self._open_pdf(path)),
                ("Ordner öffnen", lambda: self._open_folder_of(path)),
                ("Pfad kopieren", lambda: self.copy_path(path)),
                ("Neue Übersicht", self.new_overview),
            ),
            status=False,
        )
        self.set_status(f"PDF gespeichert: {path}", "success")
        if self.var_open.get():
            self._open_pdf(path)

    def new_overview(self) -> None:
        """Nur die kundenspezifischen Arbeitsdaten zurücksetzen (Firma, Kundennummer, Empfänger, Excel).

        Logo, Zielordner, Darstellung, Vorlage, Kopf-/Fußzeile, Design und Regeln bleiben.
        """
        previous = (self.var_firma.get(), self.var_kd.get(), self.var_mail.get(), self.var_excel.get())
        self._undo_overview = previous if any(value.strip() for value in previous) else None
        self._reset_work(("", "", "", ""))
        self.hide_notice("pdf_info")
        actions = (("Rückgängig", self._undo_new_overview),) if self._undo_overview else ()
        self.notify("kunde_info", "info", "Bereit für eine neue Übersicht: Kundendaten und Excel-Datei wurden zurückgesetzt.", actions=actions, auto_hide=10000)
        field = getattr(self.ui, "field_firma", None)
        if field is not None:
            try:
                field.focus()
            except tk.TclError:
                pass

    def _reset_work(self, values: tuple[str, str, str, str]) -> None:
        firma, kd, mail, excel = values
        self.kd_required = False
        for name in ("field_kd", "field_firma"):
            field = getattr(self.ui, name, None)
            if field is not None:
                field.set_error(False)
        self.var_firma.set(firma)
        self.var_kd.set(kd)
        self.var_mail.set(mail)
        self.var_excel.set(excel)
        self.refresh_files()
        if excel and Path(excel).is_file():
            self.inspect_excel(excel)
        else:
            self._analysis = None
            self._analysis_path = ""
            self._set_mails([])
            self._show_facts([])
            bar = getattr(self.ui, "info_excel", None)
            if bar is not None:
                from ui.pages.create import EXCEL_EMPTY

                bar.show("neutral", EXCEL_EMPTY)
        self.update_readiness()
        self.persist()

    def _undo_new_overview(self) -> None:
        if self._undo_overview is not None:
            values, self._undo_overview = self._undo_overview, None
            self._reset_work(values)
            self.hide_notice("kunde_info")
            self.set_status("Kundendaten und Excel-Datei wiederhergestellt.", "success")

    def _fail(self, exc: BaseException, tb: str) -> None:
        self._finish_busy()
        _write_log(tb)
        self.notify("pdf_info", "error", str(exc) or exc.__class__.__name__, title="PDF konnte nicht erstellt werden")

    # ------------------------------------------------------------------
    # Speichern und Beenden
    # ------------------------------------------------------------------
    def persist(self) -> None:
        # Ein ausstehendes verzögertes Speichern ist damit erledigt.
        self.ctx.anim.cancel_later("autosave")
        fuss = self.footer_rich()
        kopf = self.header_rich()
        data = dict(self.cfg)
        data.update(
            {
                "firmenname": self.var_firma.get().strip(),
                "kundennummer": self.var_kd.get().strip(),
                "rechnungsempfaenger": self.var_mail.get().strip(),
                "excel": self.var_excel.get().strip(),
                "logo": self.var_logo.get().strip(),
                "zielordner": self.var_ziel.get().strip(),
                "dateiname": self.var_name.get().strip(),
                "format": self.var_format.get(),
                "logo_breite": self.var_breite.get().strip(),
                "titel": self.var_titel.get().strip(),
                "untertitel": self.var_untertitel.get().strip(),
                "fusszeile": fuss.text,
                FOOTER_FORMAT: fuss.to_dict(),
                FOOTER_EXPLICIT: True,
                "kopfzeile": kopf.text,
                HEADER_FORMAT: kopf.to_dict(),
                "baustein_name": self.var_baustein.get().strip(),
                "bausteine": self.state.bausteine,
                "kunden": self.state.kunden,
                "pdfs": self.state.pdfs[:8],
                "regeln": self.state.regeln,
                "vorlagen": self.state.vorlagen,
                "staende": self.state.staende,
                "gesehen": self.state.gesehen,
                "pdf_oeffnen": bool(self.var_open.get()),
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
        self._closing = True
        self.ctx.anim.cancel_later("autosave")
        try:
            self._remember_customer()
            self.persist()
        finally:
            self.ctx.anim.shutdown()
            self.worker.shutdown()
            if self._drop is not None:
                self._drop.remove()
            if self._hook is not None:
                self._hook.remove()
            self.destroy()

    def report_callback_exception(self, exc, val, tb) -> None:  # noqa: D401 - Tk-Schnittstelle
        text = "".join(traceback.format_exception(exc, val, tb))
        _write_log(text)
        try:
            self.set_status(f"Unerwarteter Fehler: {val} – Details in fehler.log", "error")
        except Exception:
            pass


def _valid_width(value: str) -> bool:
    try:
        width = float(str(value).replace(",", "."))
    except ValueError:
        return False
    return 0 < width <= 400


def _excel_in(files: list[str]) -> list[str]:
    return [path for path in files if str(path).lower().endswith((".xlsx", ".xlsm", ".xls"))]


def _target_reachable(path: str) -> bool:
    """Zielordner vorhanden und beschreibbar – oder anlegbar (nächster vorhandener Ordner beschreibbar)."""
    folder = Path(path)
    if folder.is_dir():
        return os.access(folder, os.W_OK)
    if folder.exists():
        return False
    parent = folder.parent
    while not parent.exists() and parent.parent != parent:
        parent = parent.parent
    return parent.is_dir() and os.access(parent, os.W_OK)


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
