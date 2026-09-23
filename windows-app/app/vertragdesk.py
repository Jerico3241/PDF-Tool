"""Übersichten-Ersteller 2.0.0."""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
import tkinter.font as tkfont

APP_DIR = Path(__file__).resolve().parent
INSTALL_DIR = APP_DIR.parent
ASSETS_DIR = INSTALL_DIR / "assets"
DEFAULT_LOGO = ASSETS_DIR / "hott_logo_final.png"
CONFIG_FILE = INSTALL_DIR / "gui-config.json"
VERSION = "2.0.5"
APP_NAME = "Übersichten-Ersteller"

NEUERUNGEN = (
    "Vorlagen speichern Logo, Format, Dateiname, Kopfzeile, Fußzeile und Zyklus-Regeln unter einem Namen.",
    "Die Kundenakte merkt sich pro Kunde Excel, Logo, Fußzeile und die letzte PDF.",
    "Die App lässt sich über die Windows-Einstellungen deinstallieren.",
)


RED = "#C42B1E"
RED_DARK = "#A4262C"
RED_PRESS = "#8E1B16"
INK = "#1A1A1A"
MUTED = "#5D5D5D"
LINE = "#D1D1D1"
STROKE_HOVER = "#A6A6A6"
BG = "#F3F3F3"
CARD = "#FFFFFF"
FIELD = "#FFFFFF"
HOVER = "#F5F5F5"
DANGER = "#C42B1E"
LIGHT = True


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(channel))) for channel in rgb))


def _mix(start: str, end: str, amount: float) -> str:
    sr, sg, sb = _rgb(start)
    er, eg, eb = _rgb(end)
    return _hex((sr + (er - sr) * amount, sg + (eg - sg) * amount, sb + (eb - sb) * amount))


def windows_uses_light_theme() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return bool(value)
    except OSError:
        return True


def windows_accent() -> str:
    if sys.platform != "win32":
        return "#C42B1E"
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
            value, _kind = winreg.QueryValueEx(key, "AccentColor")
        red = value & 0xFF
        green = (value >> 8) & 0xFF
        blue = (value >> 16) & 0xFF
        return f"#{red:02X}{green:02X}{blue:02X}"
    except OSError:
        return "#C42B1E"


ACCENTS = (
    ("Blau", "#005fb8"),
    ("Rot", "#c42b1e"),
    ("Grün", "#0f7b0f"),
    ("Orange", "#d06b00"),
    ("Violett", "#6b4c9a"),
    ("Türkis", "#0e7c86"),
    ("Pink", "#c239b3"),
)


def apply_palette(light: bool | None = None, accent: str | None = None) -> None:
    global RED, RED_DARK, RED_PRESS, INK, MUTED, LINE, STROKE_HOVER
    global BG, CARD, FIELD, HOVER, DANGER, LIGHT
    LIGHT = windows_uses_light_theme() if light is None else light
    chosen = accent or "#005fb8"
    RED = chosen
    RED_DARK = _mix(chosen, "#FFFFFF", 0.18)
    RED_PRESS = _mix(chosen, "#000000", 0.2)
    if LIGHT:
        INK, MUTED = "#1c1c1c", "#6e6e6e"
        LINE, STROKE_HOVER = "#d0d0d0", "#8a8a8a"
        BG, CARD, FIELD, HOVER = "#fafafa", "#ffffff", "#ffffff", "#f3f3f3"
        DANGER = "#c42b1e"
    else:
        INK, MUTED = "#fafafa", "#a0a0a0"
        LINE, STROKE_HOVER = "#3a3a3a", "#5a5a5a"
        BG, CARD, FIELD, HOVER = "#1c1c1c", "#2a2a2a", "#323232", "#333333"
        DANGER = "#ff99a4"


def _enable_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            from ctypes import windll

            windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def desktop_dir() -> Path:
    home = Path.home()
    for name in ("Desktop", "Schreibtisch"):
        p = home / name
        if p.is_dir():
            return p
    return home


def load_config() -> dict:
    if CONFIG_FILE.is_file():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_config(data: dict) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def filename_of(path: str) -> str:
    if not path:
        return "Keine Datei gewählt"
    name = Path(path).name
    return name or path


MICA_KEY = "#010101"


def _round_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs):
    radius = max(1, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class RoundedButton(tk.Canvas):
    """Einheitlich abgerundete Schaltfläche für Akzent, Standard und Farbwahl."""

    def __init__(self, master, text: str, command, font, kind: str = "standard", fill: str | None = None) -> None:
        super().__init__(master, height=32, highlightthickness=0, bd=0, cursor="hand2")
        self._text = text
        self._command = command
        self._font = font
        self._kind = kind
        self._fill = fill
        self._enabled = True
        self._visual = "rest"
        self._selected = False
        self._drawing = False
        self._ready = True
        self._width = max(64, font.measure(text) + 28)
        super().configure(width=self._width, height=32)
        top = self.winfo_toplevel()
        bucket = getattr(top, "_rounded", None)
        if bucket is not None:
            bucket.append(self)
        self.bind("<Enter>", lambda _e: self._hover("hover"))
        self.bind("<Leave>", lambda _e: self._hover("rest"))
        self.bind("<ButtonPress-1>", lambda _e: self._hover("press"))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", self._on_resize)
        self._draw()

    def _on_resize(self, event) -> None:
        if event.width < 8 or event.width == getattr(self, "_drawn_w", -1):
            return
        self._drawn_w = event.width
        self._draw()

    def _ground(self) -> str:
        try:
            return str(self.master.cget("background"))
        except tk.TclError:
            return BG

    def _colors(self) -> tuple[str, str, str]:
        if self._kind == "chip":
            fill = self._fill or RED
            ring = "#ffffff" if self._selected else fill
            return fill, "#ffffff", ring
        if not self._enabled:
            return LINE, MUTED, LINE
        if self._kind == "accent":
            fill = {"rest": RED, "hover": RED_DARK, "press": RED_PRESS}[self._visual]
            return fill, "#ffffff", fill
        fill = {"rest": CARD, "hover": HOVER, "press": LINE}[self._visual]
        return fill, INK, LINE

    def _hover(self, visual: str) -> None:
        if self._enabled:
            self._visual = visual
        self._draw()

    def _draw(self) -> None:
        if not self._ready or self._drawing:
            return
        self._drawing = True
        try:
            self.delete("all")
            ground = self._ground()
            if str(self.cget("bg")) != ground:
                super().configure(bg=ground)
            width = max(self.winfo_width(), self._width)
            fill, fg, stroke = self._colors()
            _round_rect(self, 1, 1, width - 2, 30, 8, fill=fill, outline=stroke, width=2)
            self.create_text(width / 2, 16, text=self._text, fill=fg, font=self._font)
        finally:
            self._drawing = False

    def _release(self, event) -> None:
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self._hover("hover" if inside else "rest")
        if inside and self._enabled and self._command:
            self._command()

    def restyle(self) -> None:
        self._draw()

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self._draw()

    def mark(self, selected: bool) -> None:
        self._selected = selected
        self._draw()

    def configure(self, cnf=None, **kwargs):
        if not self._ready or cnf is not None:
            return super().configure(cnf, **kwargs)
        changed = False
        if "state" in kwargs:
            self._enabled = kwargs.pop("state") != "disabled"
            self._visual = "rest"
            changed = True
        if "text" in kwargs:
            self._text = kwargs.pop("text")
            self._width = max(64, self._font.measure(self._text) + 28)
            super().configure(width=self._width)
            changed = True
        if kwargs:
            super().configure(**kwargs)
        if changed:
            self._draw()
        return None

    def cget(self, key):
        if key == "state":
            return "normal" if self._enabled else "disabled"
        if key == "text":
            return self._text
        return super().cget(key)


class AccentButton(RoundedButton):
    def __init__(self, master, text: str, command, font) -> None:
        super().__init__(master, text, command, font, kind="accent")


class FluentButton(RoundedButton):
    def __init__(self, master, text: str, command, font=None, kind: str = "standard") -> None:
        super().__init__(master, text, command, font or tkfont.nametofont("TkDefaultFont"), kind=kind)


class FluentCheck(ttk.Checkbutton):
    def __init__(self, master, text: str, variable: tk.BooleanVar, font=None) -> None:
        super().__init__(master, text=text, variable=variable)


class InfoBar(tk.Frame):
    """WinUI-InfoBar: Streifen, Meldung, Info oder Fehler."""

    def __init__(self, master, font) -> None:
        super().__init__(master, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        self.stripe = tk.Frame(self, width=4, bg=LINE)
        self.stripe.pack(side="left", fill="y")
        self.stripe.pack_propagate(False)
        self.label = tk.Label(
            self, text="", bg=CARD, fg=MUTED, anchor="w", justify="left", wraplength=420, font=font
        )
        self.label.pack(fill="x", padx=8, pady=6)
        self.bind("<Configure>", self._refit)

    def _refit(self, _event=None) -> None:
        breite = max(80, self.winfo_width() - 28)
        if breite != getattr(self, "_wrap", 0):
            self._wrap = breite
            self.label.configure(wraplength=breite)

    def show(self, text: str, kind: str = "neutral") -> None:
        if kind == "error":
            fill = "#FDE7E9" if LIGHT else "#3F2426"
            stripe, fg = DANGER, DANGER
        elif kind == "info":
            base = "#FFFFFF" if LIGHT else "#202020"
            fill = _mix(RED, base, 0.86 if LIGHT else 0.7)
            stripe, fg = RED, INK
        else:
            fill, stripe, fg = CARD, LINE, MUTED
        self.configure(bg=fill, highlightbackground=stripe)
        self.stripe.configure(bg=stripe)
        self.label.configure(text=text, bg=fill, fg=fg)
        self._kind = kind


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.title(f"{APP_NAME}  {VERSION}")
        self.minsize(720, 480)
        self.geometry("960x700")
        cfg = load_config()
        saved_theme = cfg.get("theme")
        self._accent_name = cfg.get("accent", "#005fb8")
        if self._accent_name not in {farbe for _name, farbe in ACCENTS}:
            self._accent_name = "#005fb8"
        light = saved_theme == "light" if saved_theme in {"light", "dark"} else windows_uses_light_theme()
        apply_palette(light, self._accent_name)
        self.var_theme = tk.StringVar(value="light" if light else "dark")
        self.var_accent = tk.StringVar(value=self._accent_name)
        self._accent_buttons: list[AccentButton] = []
        self._rounded: list[RoundedButton] = []
        self._swatches: list[tuple[str, RoundedButton]] = []
        self._scroll_inners: list[tk.Frame] = []
        self._sun_valley()
        self._fonts()
        ico = ASSETS_DIR / "icon.ico"
        if ico.is_file():
            try:
                self.iconbitmap(default=str(ico))
            except tk.TclError:
                pass

        self.var_open = tk.BooleanVar(value=bool(cfg.get("pdf_oeffnen", True)))
        self.var_firma = tk.StringVar(value=cfg.get("firmenname", ""))
        self.var_kd = tk.StringVar(value=cfg.get("kundennummer", ""))
        self.var_mail = tk.StringVar(value=cfg.get("rechnungsempfaenger", ""))
        self.var_excel = tk.StringVar(value=cfg.get("excel", ""))
        self.var_logo = tk.StringVar(
            value=cfg.get("logo") or (str(DEFAULT_LOGO) if DEFAULT_LOGO.is_file() else "")
        )
        self.var_ziel = tk.StringVar(value=cfg.get("zielordner") or str(desktop_dir()))
        self.var_name = tk.StringVar(value=cfg.get("dateiname", "Vertragsuebersicht_Kd{kd}.pdf"))
        self.var_format = tk.StringVar(value=cfg.get("format", "hoch"))
        self.var_breite = tk.StringVar(value=str(cfg.get("logo_breite", "62")))
        self.var_titel = tk.StringVar(value=cfg.get("titel", "Vertragsübersicht"))
        self.var_untertitel = tk.StringVar(
            value=cfg.get("untertitel", "Wartungs- und Nutzungsverträge")
        )
        self.var_open = tk.BooleanVar(value=bool(cfg.get("pdf_oeffnen", True)))
        self._fuss_start = cfg.get("fusszeile", "")
        self._kopf_start = cfg.get("kopfzeile", "")
        self.kunden = [c for c in cfg.get("kunden", []) if isinstance(c, dict)][:12]
        self.bausteine = [b for b in cfg.get("bausteine", []) if isinstance(b, dict) and b.get("name")]
        self.var_baustein = tk.StringVar(value=cfg.get("baustein_name", ""))
        if "regeln" in cfg:
            self.regeln = []
            for eintrag in cfg.get("regeln") or []:
                if not isinstance(eintrag, dict):
                    continue
                nadel = str(eintrag.get("enthaelt") or "").strip()
                ziel = str(eintrag.get("zyklus") or "").strip()
                if nadel and ziel:
                    self.regeln.append({"enthaelt": nadel, "zyklus": ziel})
        else:
            self.regeln = [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}]
        self.pdfs = [pfad for pfad in cfg.get("pdfs", []) if isinstance(pfad, str)][:8]
        self.vorlagen = [
            eintrag for eintrag in cfg.get("vorlagen", []) if isinstance(eintrag, dict) and eintrag.get("name")
        ]
        roh_staende = cfg.get("staende", {})
        self.staende = roh_staende if isinstance(roh_staende, dict) else {}
        self._gesehen = str(cfg.get("gesehen", ""))
        self.var_vorlage = tk.StringVar()
        self._excel_mails: list[str] = []
        self.var_regel_such = tk.StringVar()
        self.var_regel_zyk = tk.StringVar()
        self.busy = False

        self._wheel_canvas: tk.Canvas | None = None
        self._header()
        self._tabs()
        self._status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-Return>", lambda _e: self.start_pdf())
        self.bind("<Control-o>", lambda _e: self.pick_excel())
        self.bind_all("<MouseWheel>", self._on_wheel)
        self._refresh_files()
        self.update_idletasks()
        self.deiconify()
        self.after_idle(self._win11_chrome)
        self.after(40, self._enable_drop)
        excel = self.var_excel.get().strip()
        if excel and Path(excel).is_file():
            self.after(40, lambda pfad=excel: self._inspect_excel(pfad))
        if self._gesehen.split(".")[:2] != VERSION.split(".")[:2]:
            self.after(400, self._zeige_neuerungen)

    def _sun_valley(self) -> None:
        import sv_ttk

        sv_ttk.set_theme("light" if LIGHT else "dark", self)
        self.configure(bg=BG)
        priority = getattr(self, "_opt_priority", 80) + 1
        self._opt_priority = priority
        for pattern, color in (
            ("*TCombobox*Listbox.background", CARD),
            ("*TCombobox*Listbox.foreground", INK),
            ("*TCombobox*Listbox.selectBackground", "#e6e6e6" if LIGHT else "#3a3a3a"),
            ("*TCombobox*Listbox.selectForeground", INK),
            ("*Listbox.background", CARD),
            ("*Listbox.foreground", INK),
            ("*Listbox.selectBackground", RED),
            ("*Listbox.selectForeground", "#ffffff"),
        ):
            self.option_add(pattern, color, priority)

    def _win11_chrome(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            dwm = ctypes.windll.dwmapi
            hwnds = []
            current = self.winfo_id()
            while current and current not in hwnds:
                hwnds.append(current)
                parent = user32.GetParent(current)
                if not parent or parent == current:
                    break
                current = parent

            def colorref(hex_color: str) -> int:
                red = int(hex_color[1:3], 16)
                green = int(hex_color[3:5], 16)
                blue = int(hex_color[5:7], 16)
                return red | (green << 8) | (blue << 16)

            dark = 0 if LIGHT else 1
            caption = colorref("#fafafa" if LIGHT else "#1c1c1c")
            text = colorref("#1c1c1c" if LIGHT else "#ffffff")
            for hwnd in hwnds:
                for index, value in ((19, dark), (20, dark), (35, caption), (36, text), (34, caption)):
                    raw = ctypes.c_int(value)
                    dwm.DwmSetWindowAttribute(hwnd, index, ctypes.byref(raw), ctypes.sizeof(raw))
        except Exception:
            return

    def _fonts(self) -> None:
        # Segoe UI ist auf Windows immer da. families() listet alle Schriften
        # und verzögert den Start spürbar.
        family = "Segoe UI"
        self.f_ui = tkfont.Font(root=self, family=family, size=10)
        self.f_bold = tkfont.Font(root=self, family=family, size=10, weight="bold")
        self.f_title = tkfont.Font(root=self, family=family, size=20, weight="bold")
        self.f_card = tkfont.Font(root=self, family=family, size=12, weight="bold")
        self.f_small = tkfont.Font(root=self, family=family, size=9)
        self.f_link = tkfont.Font(root=self, family=family, size=9, underline=True)
        self.f_tab = tkfont.Font(root=self, family=family, size=11)

    def _bind_fill(self, widget: tk.Widget, rest: str, hover: str) -> None:
        def enter(_event) -> None:
            if str(widget.cget("state")) != "disabled":
                widget.configure(bg=hover)

        def leave(_event) -> None:
            if str(widget.cget("state")) != "disabled":
                widget.configure(bg=rest)

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    def _bind_stroke(self, widget: tk.Widget) -> None:
        def paint(active: bool) -> None:
            widget.configure(highlightbackground=RED if active else LINE, highlightcolor=RED)

        widget.bind("<FocusIn>", lambda _e: paint(True))
        widget.bind("<FocusOut>", lambda _e: paint(False))
        widget.bind("<Enter>", lambda _e: widget.configure(highlightbackground=RED if widget.focus_get() == widget else STROKE_HOVER))
        widget.bind("<Leave>", lambda _e: widget.configure(highlightbackground=RED if widget.focus_get() == widget else LINE))

    def _menu(self) -> None:
        menubar = tk.Menu(self, bg=CARD, fg=INK, activebackground=RED, activeforeground="white", bd=0)
        datei = tk.Menu(menubar, tearoff=0, bg=CARD, fg=INK, activebackground=RED, activeforeground="white")
        datei.add_command(label="Excel-Datei wählen…", command=self.pick_excel, accelerator="Strg+O")
        datei.add_command(label="Logo wählen…", command=self.pick_logo)
        datei.add_command(label="Zielordner wählen…", command=self.pick_ziel)
        datei.add_command(label="Zielordner öffnen", command=self.open_folder)
        datei.add_separator()
        datei.add_command(label="Beenden", command=self._on_close)
        menubar.add_cascade(label="Datei", menu=datei)
        bearbeiten = tk.Menu(menubar, tearoff=0, bg=CARD, fg=INK, activebackground=RED, activeforeground="white")
        bearbeiten.add_command(label="Fußzeile speichern", command=self.save_footer)
        bearbeiten.add_command(label="Kundendaten leeren", command=self.clear_customer)
        bearbeiten.add_command(label="Standard-Logo", command=self.use_default_logo)
        menubar.add_cascade(label="Bearbeiten", menu=bearbeiten)
        hilfe = tk.Menu(menubar, tearoff=0, bg=CARD, fg=INK, activebackground=RED, activeforeground="white")
        hilfe.add_command(label="Kurzanleitung", command=self.show_help)
        hilfe.add_command(label="Über", command=self.show_about)
        menubar.add_cascade(label="Hilfe", menu=hilfe)
        self.config(menu=menubar)

    def _header(self) -> None:
        head = ttk.Frame(self)
        head.pack(fill="x", padx=16, pady=(12, 0))
        ttk.Label(head, text="Vertragsübersicht", font=self.f_title).pack(anchor="w")

    def _card(self, master, title: str) -> ttk.Frame:
        box = ttk.Frame(master, style="Card.TFrame", padding=(16, 14, 16, 14))
        ttk.Label(box, text=title, font=self.f_card).pack(anchor="w", pady=(0, 4))
        return box

    def _field(self, master, label: str, var: tk.StringVar) -> None:
        ttk.Label(master, text=label, font=self.f_small).pack(anchor="w", pady=(8, 2))
        ttk.Entry(master, textvariable=var).pack(fill="x")

    def _file_row(self, master, label: str, command, attr: str) -> None:
        ttk.Label(master, text=label, font=self.f_small).pack(anchor="w", pady=(8, 2))
        row = ttk.Frame(master)
        row.pack(fill="x", pady=(0, 4))
        name = ttk.Label(row, text="")
        name.pack(side="left", fill="x", expand=True, padx=(0, 8))
        RoundedButton(row, "Durchsuchen", command, self.f_small, "standard").pack(side="right")

        def fit(event, ziel=name) -> None:
            ziel.configure(wraplength=max(40, event.width - 130))

        row.bind("<Configure>", fit)
        setattr(self, attr, name)

    def _tabs(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        self.page_create = ttk.Frame(self.notebook, padding=12)
        self.page_layout = ttk.Frame(self.notebook)
        self.notebook.add(self.page_create, text="Erstellen")
        self.notebook.add(self.page_layout, text="Darstellung")
        self.page_settings = ttk.Frame(self.notebook)
        self.notebook.add(self.page_settings, text="Einstellungen")
        self._pages_ready: set[str] = set()
        self._create_canvas, create_inner = self._mount_scroll(self.page_create)
        self._build_create(create_inner)
        self._pages_ready.add("Erstellen")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab)
        self._wheel_canvas = self._create_canvas

    def _ensure_page(self, name: str) -> None:
        if name in self._pages_ready:
            return
        if name == "Darstellung":
            self._layout_canvas, inner = self._mount_scroll(self.page_layout)
            self._build_layout(inner)
        elif name == "Einstellungen":
            self._settings_canvas, inner = self._mount_scroll(self.page_settings)
            self._build_settings(inner)
        self._pages_ready.add(name)

    def _mount_scroll(self, page: tk.Frame) -> tuple[tk.Canvas, tk.Frame]:
        canvas = tk.Canvas(page, bg=BG, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_inner(_event=None) -> None:
            self._sync_scroll(canvas, inner, vsb)

        def on_canvas(event) -> None:
            canvas.itemconfigure(window, width=event.width)
            self._sync_scroll(canvas, inner, vsb)

        inner.bind("<Configure>", on_inner)
        canvas.bind("<Configure>", on_canvas)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        self._scroll_inners.append(inner)
        return canvas, inner

    def _sync_scroll(self, canvas: tk.Canvas, inner: tk.Frame, vsb: tk.Scrollbar) -> None:
        if getattr(canvas, "_syncing", False):
            return
        canvas._syncing = True  # type: ignore[attr-defined]
        try:
            height = inner.winfo_reqheight()
            width = max(inner.winfo_reqwidth(), 1)
            canvas.configure(scrollregion=(0, 0, width, height))
            visible = canvas.winfo_height()
            need = visible > 1 and height > visible + 2
            if not need:
                canvas.yview_moveto(0)
                if vsb.winfo_ismapped():
                    vsb.pack_forget()
            elif not vsb.winfo_ismapped():
                vsb.pack(side="right", fill="y")
        finally:
            canvas._syncing = False  # type: ignore[attr-defined]

    def _on_wheel(self, event) -> None:
        widget = event.widget
        if widget.winfo_class() in {"Text", "Listbox"}:
            return
        canvas = self._wheel_canvas
        if canvas is None:
            return
        top, bottom = canvas.yview()
        if bottom - top >= 0.999:
            return
        canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_tab(self, _event=None) -> None:
        current = self.notebook.tab(self.notebook.select(), "text")
        self._ensure_page(current)
        canvas = None
        if current == "Erstellen" and hasattr(self, "_create_canvas"):
            canvas = self._create_canvas
        elif current == "Darstellung" and hasattr(self, "_layout_canvas"):
            canvas = self._layout_canvas
        elif current == "Einstellungen" and hasattr(self, "_settings_canvas"):
            canvas = self._settings_canvas
        self._wheel_canvas = canvas
        if canvas is not None:
            self.after_idle(lambda ziel=canvas: ziel.yview_moveto(0))

    def _show_tab(self, name: str) -> None:
        self.notebook.select(0 if name == "create" else 1)

    def _build_create(self, parent: tk.Frame) -> None:
        pad = ttk.Frame(parent)
        pad.pack(fill="x", anchor="n", padx=4, pady=8)
        grid = ttk.Frame(pad)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        kunde = self._card(grid, "Kundendaten")
        kunde.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        recent = ttk.Frame(kunde)
        recent.pack(fill="x", pady=(0, 2))
        self.recent_combo = ttk.Combobox(recent, state="readonly", width=32, exportselection=False)
        self.recent_combo.pack(side="left", fill="x", expand=True)
        self.recent_combo.bind("<<ComboboxSelected>>", self._on_recent_pick)
        self.recent_combo.bind("<FocusIn>", lambda _e: self.after_idle(lambda: self._clear_hint(self.recent_combo)))
        self._reload_recent()
        self._field(kunde, "Firmenname", self.var_firma)
        self._field(kunde, "Kundennummer", self.var_kd)
        self._field(kunde, "Rechnungsempfänger (optional)", self.var_mail)
        self.mail_frame = ttk.Frame(kunde)
        ttk.Label(self.mail_frame, text="Mehrere Empfänger in der Excel", font=self.f_small).pack(
            anchor="w", pady=(8, 2)
        )
        self.mail_combo = ttk.Combobox(self.mail_frame, state="readonly", exportselection=False)
        self.mail_combo.pack(fill="x")
        self.mail_combo.bind("<FocusIn>", lambda _e: self.after_idle(lambda: self._clear_hint(self.mail_combo)))

        dateien = self._card(grid, "Dateien und Pfade")
        dateien.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._file_row(dateien, "Excel-Datei", self.pick_excel, "lbl_excel")
        self.info_excel = InfoBar(dateien, self.f_small)
        self.info_excel.pack(fill="x", pady=(2, 4))
        self.info_excel.show("Datei wählen oder hierher ziehen.", "neutral")
        self.lbl_check = self.info_excel.label
        self._file_row(dateien, "Logo", self.pick_logo, "lbl_logo")
        self._file_row(dateien, "Zielordner", self.pick_ziel, "lbl_ziel")

        action = ttk.Frame(pad, style="Card.TFrame", padding=(16, 12))
        action.pack(fill="x", pady=(12, 0))
        inner = ttk.Frame(action)
        inner.pack(fill="x")
        self.btn_pdf = AccentButton(inner, "PDF erstellen", self.start_pdf, self.f_bold)
        self.btn_pdf.pack(side="left")
        self._accent_buttons.append(self.btn_pdf)
        folder = FluentButton(inner, "Ordner öffnen", self.open_folder, self.f_small, "standard")
        folder.pack(side="left", padx=(10, 0))
        FluentCheck(inner, "PDF nach dem Erstellen öffnen", self.var_open, self.f_ui).pack(
            side="left", padx=(16, 0)
        )
        ttk.Label(inner, text="Strg+Enter", font=self.f_small).pack(side="right")
        zuletzt = ttk.Frame(action)
        zuletzt.pack(fill="x", pady=(10, 0))
        ttk.Label(zuletzt, text="Zuletzt erstellt", font=self.f_small).pack(side="left", padx=(0, 8))
        self.pdf_combo = ttk.Combobox(zuletzt, state="readonly", exportselection=False)
        self.pdf_combo.pack(side="left", fill="x", expand=True)
        self.pdf_combo.bind("<FocusIn>", lambda _e: self.after_idle(lambda: self._clear_hint(self.pdf_combo)))
        FluentButton(zuletzt, "Öffnen", self.open_recent_pdf, self.f_small, "standard").pack(side="left", padx=(8, 0))
        self._reload_pdfs()

    def _set_format(self, value: str) -> None:
        self.var_format.set(value)
        self._paint_format()

    def _paint_format(self) -> None:
        current = self.var_format.get()
        for value, button in self._fmt_btns.items():
            button.set_kind("accent" if value == current else "standard")

    def _build_layout(self, parent: tk.Frame) -> None:
        pad = ttk.Frame(parent)
        pad.pack(fill="x", anchor="n", padx=16, pady=14)
        vorlagen = self._card(pad, "Vorlagen")
        vorlagen.pack(fill="x")
        ttk.Label(
            vorlagen,
            text="Speichert Logo, Format, Dateiname, Kopfzeile, Fußzeile und Zyklus-Regeln.",
            font=self.f_small,
        ).pack(anchor="w")
        vrow = ttk.Frame(vorlagen)
        vrow.pack(fill="x", pady=(8, 0))
        self.vorlage_combo = ttk.Combobox(vrow, state="readonly", width=28, exportselection=False)
        self.vorlage_combo.pack(side="left")
        self.vorlage_combo.bind("<<ComboboxSelected>>", self._on_vorlage_pick)
        self.vorlage_combo.bind("<FocusIn>", lambda _e: self.after_idle(lambda: self._clear_hint(self.vorlage_combo)))
        ttk.Entry(vrow, textvariable=self.var_vorlage).pack(side="left", fill="x", expand=True, padx=8)
        self._reload_vorlagen()
        vbtns = ttk.Frame(vorlagen)
        vbtns.pack(fill="x", pady=(8, 0))
        save_vorlage = AccentButton(vbtns, "Vorlage speichern", self.save_vorlage, self.f_small)
        save_vorlage.pack(side="left")
        self._accent_buttons.append(save_vorlage)
        FluentButton(vbtns, "Vorlage löschen", self.delete_vorlage, self.f_small, "standard").pack(
            side="left", padx=(8, 0)
        )

        box = self._card(pad, "PDF-Einstellungen")
        box.pack(fill="x")
        self._field(box, "Titel", self.var_titel)
        self._field(box, "Untertitel", self.var_untertitel)
        self._field(box, "Dateiname", self.var_name)
        self._field(box, "Logo-Breite (mm)", self.var_breite)
        fmt = ttk.Frame(box)
        fmt.pack(fill="x", pady=(12, 0))
        ttk.Label(fmt, text="Seitenformat", font=self.f_small).pack(side="left", padx=(0, 12))
        self._fmt_btns: dict[str, FluentButton] = {}
        for value, text in (("hoch", "Hochformat A4"), ("quer", "Querformat A4")):
            button = FluentButton(
                fmt, text, lambda chosen=value: self._set_format(chosen), self.f_small, "standard"
            )
            button.pack(side="left", padx=(0, 8))
            self._fmt_btns[value] = button
        self._paint_format()

        kopf = self._card(pad, "Kopfzeile")
        kopf.pack(fill="x", pady=(12, 0))
        ttk.Label(
            kopf,
            text="Optional. Erscheint oben auf jeder Seite. Leer lassen, wenn keine Kopfzeile gewünscht ist.",
            font=self.f_small,
        ).pack(anchor="w")
        self.txt_kopf = tk.Text(
            kopf,
            height=3,
            wrap="word",
            undo=True,
            font=self.f_ui,
            bg=FIELD,
            fg=INK,
            insertbackground=INK,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=RED,
        )
        self.txt_kopf.pack(fill="x", pady=(8, 8))
        self._bind_stroke(self.txt_kopf)
        if self._kopf_start:
            self.txt_kopf.insert("1.0", self._kopf_start)
        kopf_row = ttk.Frame(kopf)
        kopf_row.pack(fill="x")
        save_kopf = AccentButton(kopf_row, "Kopfzeile speichern", self.save_header, self.f_small)
        save_kopf.pack(side="left")
        self._accent_buttons.append(save_kopf)
        ttk.Label(kopf_row, text="Platzhalter: {kd}  {kunde}  {datum}", font=self.f_small).pack(
            side="left", padx=12
        )

        fuss = self._card(pad, "Fußzeile")
        fuss.pack(fill="x", pady=(12, 0))
        ttk.Label(
            fuss,
            text="Erscheint unten auf jeder Seite. Die Seitenzahl wird automatisch ergänzt.",
            font=self.f_small,
        ).pack(anchor="w")
        baustein = ttk.Frame(fuss)
        baustein.pack(fill="x", pady=(8, 0))
        self.baustein_combo = ttk.Combobox(baustein, state="readonly", width=28, exportselection=False)
        self.baustein_combo.pack(side="left")
        self.baustein_combo.bind("<<ComboboxSelected>>", self._on_baustein_pick)
        self.baustein_combo.bind("<FocusIn>", lambda _e: self.after_idle(lambda: self._clear_hint(self.baustein_combo)))
        name = ttk.Entry(baustein, textvariable=self.var_baustein)
        name.pack(side="left", fill="x", expand=True, padx=8)
        self._reload_bausteine()
        self.txt_fuss = tk.Text(
            fuss,
            height=6,
            wrap="word",
            undo=True,
            font=self.f_ui,
            bg=FIELD,
            fg=INK,
            insertbackground=INK,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=RED,
        )
        self.txt_fuss.pack(fill="x", pady=(8, 8))
        self._bind_stroke(self.txt_fuss)
        if self._fuss_start:
            self.txt_fuss.insert("1.0", self._fuss_start)
        row = ttk.Frame(fuss)
        row.pack(fill="x", pady=(8, 0))
        save = AccentButton(row, "Fußzeile speichern", self.save_footer, self.f_small)
        save.pack(side="left")
        self._accent_buttons.append(save)
        delete = FluentButton(row, "Textbaustein löschen", self.delete_baustein, self.f_small, "standard")
        delete.pack(side="left", padx=(8, 0))
        ttk.Label(row, text="Platzhalter: {kd}  {kunde}  {datum}", font=self.f_small).pack(
            side="left", padx=12
        )

        regeln = self._card(pad, "Zyklus-Regeln")
        regeln.pack(fill="x", pady=(12, 0))
        ttk.Label(
            regeln,
            text="Wenn die Beschreibung den Begriff enthält, wird der Zyklus in der PDF angepasst. Das Datum bleibt stehen.",
            font=self.f_small,
        ).pack(anchor="w")
        self.regeln_list = tk.Listbox(
            regeln,
            height=4,
            activestyle="none",
            exportselection=False,
            font=self.f_small,
            bg=FIELD,
            fg=INK,
            selectbackground=RED,
            selectforeground="#ffffff",
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
        )
        self.regeln_list.pack(fill="x", pady=(8, 8))
        self._reload_regeln()
        such = ttk.Frame(regeln)
        such.pack(fill="x")
        ttk.Label(such, text="Begriff", font=self.f_small).pack(side="left")
        ttk.Entry(such, textvariable=self.var_regel_such, width=24).pack(side="left", padx=8)
        ttk.Label(such, text="Zyklus", font=self.f_small).pack(side="left")
        ttk.Entry(such, textvariable=self.var_regel_zyk, width=16).pack(side="left", padx=8)
        knopf = ttk.Frame(regeln)
        knopf.pack(fill="x", pady=(8, 0))
        add = AccentButton(knopf, "Regel speichern", self.add_regel, self.f_small)
        add.pack(side="left")
        self._accent_buttons.append(add)
        FluentButton(knopf, "Regel löschen", self.delete_regel, self.f_small, "standard").pack(
            side="left", padx=(8, 0)
        )

    def _build_settings(self, parent: tk.Frame) -> None:
        pad = ttk.Frame(parent)
        pad.pack(fill="x", padx=16, pady=14)
        look = self._card(pad, "Darstellung")
        look.pack(fill="x")
        ttk.Label(look, text="Helles oder dunkles Design. Wird sofort übernommen.", font=self.f_small).pack(
            anchor="w", pady=(0, 8)
        )
        row = ttk.Frame(look)
        row.pack(anchor="w")
        ttk.Radiobutton(
            row, text="Hell", value="light", variable=self.var_theme, command=self._apply_appearance
        ).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(
            row, text="Dunkel", value="dark", variable=self.var_theme, command=self._apply_appearance
        ).pack(side="left")

        farben = self._card(pad, "Akzentfarbe")
        farben.pack(fill="x", pady=(12, 0))
        ttk.Label(
            farben,
            text="Gilt für „PDF erstellen“, die Fußzeile und Hinweise.",
            font=self.f_small,
        ).pack(anchor="w", pady=(0, 8))
        chips = ttk.Frame(farben)
        chips.pack(anchor="w")
        for name, color in ACCENTS:
            button = RoundedButton(
                chips,
                name,
                lambda chosen=color: self._choose_accent(chosen),
                self.f_small,
                kind="chip",
                fill=color,
            )
            button.pack(side="left", padx=(0, 8))
            self._swatches.append((color, button))
        self._mark_swatches()

        extra = self._card(pad, "Weiteres")
        extra.pack(fill="x", pady=(12, 0))
        actions = ttk.Frame(extra)
        actions.pack(anchor="w")
        for text, command in (
            ("Kundendaten leeren", self.clear_customer),
            ("Standard-Logo", self.use_default_logo),
            ("Kurzanleitung", self.show_help),
            ("Neuerungen", self.show_changelog),
            ("Über", self.show_about),
        ):
            FluentButton(actions, text, command, self.f_small, "standard").pack(side="left", padx=(0, 8))

    def _mark_swatches(self) -> None:
        selected = self.var_accent.get()
        for color, button in self._swatches:
            button.mark(color == selected)

    def _choose_accent(self, color: str) -> None:
        self.var_accent.set(color)
        self._apply_appearance()

    def _apply_appearance(self) -> None:
        apply_palette(self.var_theme.get() == "light", self.var_accent.get())
        self._sun_valley()
        self.update_idletasks()
        for canvas in (
            getattr(self, "_create_canvas", None),
            getattr(self, "_layout_canvas", None),
            getattr(self, "_settings_canvas", None),
        ):
            if canvas is not None:
                canvas.configure(bg=BG)
        for inner in self._scroll_inners:
            inner.configure(bg=BG)
        if hasattr(self, "txt_fuss"):
            self.txt_fuss.configure(
                bg=FIELD,
                fg=INK,
                insertbackground=INK,
                highlightbackground=LINE,
                highlightcolor=RED,
            )
        if hasattr(self, "txt_kopf"):
            self.txt_kopf.configure(
                bg=FIELD,
                fg=INK,
                insertbackground=INK,
                highlightbackground=LINE,
                highlightcolor=RED,
            )
        if hasattr(self, "preview"):
            self.preview.configure(bg=CARD, fg=INK, highlightthickness=0)
        if hasattr(self, "diff_text"):
            self.diff_text.configure(bg=CARD, fg=INK, highlightthickness=0)
        if hasattr(self, "regeln_list"):
            self.regeln_list.configure(
                bg=FIELD,
                fg=INK,
                selectbackground=RED,
                selectforeground="#ffffff",
                highlightbackground=LINE,
            )
        for button in self._accent_buttons:
            button.restyle()
        self._mark_swatches()
        if hasattr(self, "info_excel"):
            self.info_excel.show(self.info_excel.label.cget("text"), getattr(self.info_excel, "_kind", "neutral"))
        for button in getattr(self, "_rounded", ()):
            button.restyle()
        self._win11_chrome()
        self.persist()

    def _status(self) -> None:
        self.status = ttk.Label(self, text="")

    def set_status(self, text: str) -> None:
        return

    def _refresh_files(self) -> None:
        self.lbl_excel.configure(text=filename_of(self.var_excel.get()))
        self.lbl_logo.configure(text=filename_of(self.var_logo.get()))
        ziel = self.var_ziel.get().strip()
        self.lbl_ziel.configure(text=Path(ziel).name if ziel else "Keine Auswahl")

    def pick_excel(self) -> None:
        path = filedialog.askopenfilename(
            title="Excel-Liste wählen",
            filetypes=[("Excel", "*.xlsx *.xls"), ("Alle Dateien", "*.*")],
        )
        if path:
            self.var_excel.set(path)
            self._refresh_files()
            self._inspect_excel(path)

    def pick_logo(self) -> None:
        path = filedialog.askopenfilename(
            title="Logo wählen",
            filetypes=[("Bilder", "*.png *.jpg *.jpeg *.webp"), ("Alle Dateien", "*.*")],
        )
        if path:
            self.var_logo.set(path)
            self._refresh_files()

    def pick_ziel(self) -> None:
        path = filedialog.askdirectory(title="Zielordner für die PDF")
        if path:
            self.var_ziel.set(path)
            self._refresh_files()

    def use_default_logo(self) -> None:
        if DEFAULT_LOGO.is_file():
            self.var_logo.set(str(DEFAULT_LOGO))
            self._refresh_files()
        else:
            messagebox.showwarning(APP_NAME, "Es ist kein Standard-Logo installiert.")

    def clear_customer(self) -> None:
        self.var_firma.set("")
        self.var_kd.set("")
        self.var_mail.set("")

    def _clear_hint(self, combo: ttk.Combobox) -> None:
        def weg() -> None:
            try:
                if combo.winfo_exists():
                    combo.selection_clear()
                    combo.selection_range(0, 0)
            except tk.TclError:
                pass

        self.after_idle(weg)
        self.after(80, weg)

    def _reload_recent(self) -> None:
        labels = []
        self._recent_by_label = {}
        for eintrag in self.kunden:
            label = f"{eintrag.get('firmenname') or 'Ohne Name'} · {eintrag.get('kundennummer') or '–'}"
            labels.append(label)
            self._recent_by_label[label] = eintrag
        self.recent_combo.configure(values=labels)
        self.recent_combo.set("Zuletzt wählen" if labels else "Noch keine Einträge")
        self.after_idle(lambda: self._clear_hint(self.recent_combo))

    def _on_recent_pick(self, _event=None) -> None:
        eintrag = self._recent_by_label.get(self.recent_combo.get())
        if eintrag:
            self._apply_customer(eintrag)
        self.recent_combo.set("Zuletzt wählen" if self.kunden else "Noch keine Einträge")
        self.after_idle(lambda: self._clear_hint(self.recent_combo))

    def _reload_bausteine(self) -> None:
        labels = [str(eintrag.get("name", "")) for eintrag in self.bausteine]
        self._baustein_by_label = {
            str(eintrag.get("name", "")): eintrag for eintrag in self.bausteine
        }
        if labels:
            self.baustein_combo.configure(values=labels)
            current = self.var_baustein.get().strip()
            self.baustein_combo.set(current if current in labels else "Textbaustein wählen")
        else:
            self.baustein_combo.configure(values=[])
            self.baustein_combo.set("Noch kein Textbaustein")
        self.after_idle(lambda: self._clear_hint(self.baustein_combo))

    def _on_baustein_pick(self, _event=None) -> None:
        eintrag = self._baustein_by_label.get(self.baustein_combo.get())
        if eintrag:
            self._apply_baustein(eintrag)

    def _fill_recent_menu(self) -> None:
        self._reload_recent()

    def _apply_customer(self, eintrag: dict) -> None:
        self.var_firma.set(eintrag.get("firmenname", ""))
        self.var_kd.set(eintrag.get("kundennummer", ""))
        self.var_mail.set(eintrag.get("rechnungsempfaenger", ""))
        excel = str(eintrag.get("excel") or "").strip()
        if excel and Path(excel).is_file():
            self.var_excel.set(excel)
            self._refresh_files()
            self._inspect_excel(excel)
        logo = str(eintrag.get("logo") or "").strip()
        if logo and Path(logo).is_file():
            self.var_logo.set(logo)
            self._refresh_files()
        if "fusszeile" in eintrag:
            self._set_long_text("txt_fuss", "_fuss_start", str(eintrag.get("fusszeile") or ""))
        if "kopfzeile" in eintrag:
            self._set_long_text("txt_kopf", "_kopf_start", str(eintrag.get("kopfzeile") or ""))
        pdf = str(eintrag.get("pdf") or "").strip()
        if pdf and Path(pdf).is_file():
            self._remember_pdf(Path(pdf))
        self.set_status("Kundenakte übernommen.")

    def _set_long_text(self, widget_name: str, start_name: str, text: str) -> None:
        setattr(self, start_name, text)
        widget = getattr(self, widget_name, None)
        if widget is None:
            return
        widget.delete("1.0", "end")
        if text:
            widget.insert("1.0", text)

    def _remember_customer(self, pdf: str | None = None) -> None:
        firma = self.var_firma.get().strip()
        kd = self.var_kd.get().strip()
        mail = self.var_mail.get().strip()
        if not firma and not kd:
            return
        schluessel = (firma.casefold(), kd)
        bisher = ""
        for alt in self.kunden:
            if (str(alt.get("firmenname", "")).casefold(), str(alt.get("kundennummer", ""))) == schluessel:
                bisher = str(alt.get("pdf") or "")
                break
        self.kunden = [
            alt
            for alt in self.kunden
            if (str(alt.get("firmenname", "")).casefold(), str(alt.get("kundennummer", ""))) != schluessel
        ]
        self.kunden.insert(
            0,
            {
                "firmenname": firma,
                "kundennummer": kd,
                "rechnungsempfaenger": mail,
                "excel": self.var_excel.get().strip(),
                "logo": self.var_logo.get().strip(),
                "fusszeile": self._footer_text(),
                "kopfzeile": self._header_text(),
                "pdf": bisher if pdf is None else pdf,
            },
        )
        self.kunden = self.kunden[:12]
        self._reload_recent()

    def _inspect_excel(self, path: str) -> None:
        if not hasattr(self, "lbl_check"):
            return
        self.info_excel.show("Excel wird geprüft …", "info")

        def work() -> None:
            try:
                from engine import pruefe_excel

                result = pruefe_excel(Path(path), list(self.regeln))
            except Exception as exc:
                result = {"ok": False, "text": str(exc), "kunden": [], "mails": [], "firmen": [], "zeilen": []}
            self.after(0, lambda: self._show_check(path, result))

        threading.Thread(target=work, daemon=True).start()

    def _show_check(self, path: str, result: dict) -> None:
        if self.var_excel.get().strip() != path:
            return
        self.info_excel.show(result.get("text", ""), "info" if result.get("ok") else "error")
        if not result.get("ok"):
            self.set_status("Excel-Prüfung fehlgeschlagen.")
            return
        self.set_status(result.get("text", "Excel geprüft."))
        self._excel_mails = [str(mail) for mail in result.get("mails") or []]
        if len(self._excel_mails) > 1:
            self.mail_combo.configure(values=self._excel_mails)
            if self.mail_combo.get() not in self._excel_mails:
                self.mail_combo.set("Empfänger wählen")
                self.after_idle(lambda: self._clear_hint(self.mail_combo))
            if not self.mail_frame.winfo_ismapped():
                self.mail_frame.pack(fill="x", pady=(4, 0))
        elif self.mail_frame.winfo_ismapped():
            self.mail_frame.pack_forget()
        if not self.var_kd.get().strip() and len(result.get("kunden") or []) == 1:
            self.var_kd.set(result["kunden"][0])
        if not self.var_firma.get().strip() and len(result.get("firmen") or []) == 1:
            self.var_firma.set(result["firmen"][0])

    def _reload_regeln(self) -> None:
        if not hasattr(self, "regeln_list"):
            return
        self.regeln_list.delete(0, "end")
        if not self.regeln:
            self.regeln_list.insert("end", "Keine Regeln")
            return
        for regel in self.regeln:
            self.regeln_list.insert("end", f"{regel['enthaelt']}  →  {regel['zyklus']}")

    def add_regel(self) -> None:
        nadel = self.var_regel_such.get().strip()
        ziel = self.var_regel_zyk.get().strip()
        if not nadel or not ziel:
            messagebox.showwarning(APP_NAME, "Bitte Begriff und Zyklus eintragen, zum Beispiel Hott-KI und jährlich.")
            return
        self.regeln = [alt for alt in self.regeln if str(alt.get("enthaelt", "")).lower() != nadel.lower()]
        self.regeln.append({"enthaelt": nadel, "zyklus": ziel})
        self.var_regel_such.set("")
        self.var_regel_zyk.set("")
        self._reload_regeln()
        self.persist()
        excel = self.var_excel.get().strip()
        if excel and Path(excel).is_file():
            self._inspect_excel(excel)
        self.set_status(f"Regel „{nadel}“ gespeichert.")

    def delete_regel(self) -> None:
        if not hasattr(self, "regeln_list"):
            return
        index = self.regeln_list.curselection()
        if not index or not self.regeln:
            messagebox.showwarning(APP_NAME, "Bitte zuerst eine Regel in der Liste auswählen.")
            return
        gewaehlt = index[0]
        if gewaehlt >= len(self.regeln):
            return
        name = self.regeln[gewaehlt]["enthaelt"]
        del self.regeln[gewaehlt]
        self._reload_regeln()
        self.persist()
        excel = self.var_excel.get().strip()
        if excel and Path(excel).is_file():
            self._inspect_excel(excel)
        self.set_status(f"Regel „{name}“ gelöscht.")

    def _reload_pdfs(self) -> None:
        self.pdfs = [pfad for pfad in self.pdfs if Path(pfad).is_file()][:8]
        self._pdf_by_label = {}
        labels = []
        for pfad in self.pdfs:
            label = Path(pfad).name
            if label in self._pdf_by_label:
                label = f"{Path(pfad).name} · {Path(pfad).parent.name}"
            self._pdf_by_label[label] = pfad
            labels.append(label)
        if labels:
            self.pdf_combo.configure(values=labels)
            self.pdf_combo.set(labels[0])
        else:
            self.pdf_combo.configure(values=[])
            self.pdf_combo.set("Noch keine PDF")
            self.after_idle(lambda: self._clear_hint(self.pdf_combo))

    def open_recent_pdf(self) -> None:
        pfad = self._pdf_by_label.get(self.pdf_combo.get()) if hasattr(self, "_pdf_by_label") else None
        if not pfad or not Path(pfad).is_file():
            messagebox.showwarning(APP_NAME, "Keine gespeicherte PDF zum Öffnen.")
            return
        self._open_pdf(Path(pfad))

    def _remember_pdf(self, path: Path) -> None:
        text = str(path)
        self.pdfs = [text] + [alt for alt in self.pdfs if alt != text]
        self._reload_pdfs()

    def open_folder(self) -> None:
        ziel = self.var_ziel.get().strip()
        if not ziel or not Path(ziel).is_dir():
            messagebox.showwarning(APP_NAME, "Der Zielordner ist nicht vorhanden.")
            return
        try:
            if hasattr(os, "startfile"):
                os.startfile(ziel)  # type: ignore[attr-defined]
            else:
                webbrowser.open(Path(ziel).as_uri())
        except OSError as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def _enable_drop(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            user32.GetWindowLongPtrW.restype = ctypes.c_void_p
            user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            user32.CallWindowProcW.restype = ctypes.c_longlong
            user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            old = user32.GetWindowLongPtrW(hwnd, -4)
            wndproc = ctypes.WINFUNCTYPE(
                ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )

            def proc(handle, msg, wparam, lparam):
                if msg == 0x0233:
                    anzahl = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                    dateien = []
                    puffer = ctypes.create_unicode_buffer(1024)
                    for index in range(anzahl):
                        shell32.DragQueryFileW(wparam, index, puffer, 1024)
                        dateien.append(puffer.value)
                    shell32.DragFinish(wparam)
                    self.after(0, lambda: self._on_drop(dateien))
                    return 0
                return user32.CallWindowProcW(old, handle, msg, wparam, lparam)

            self._drop_proc = wndproc(proc)
            user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(self._drop_proc, ctypes.c_void_p))
            shell32.DragAcceptFiles(hwnd, True)
        except Exception:
            return

    def _on_drop(self, dateien: list[str]) -> None:
        excel = next((pfad for pfad in dateien if pfad.lower().endswith((".xlsx", ".xls"))), "")
        if not excel:
            self.set_status("Bitte eine Excel-Datei ziehen.")
            return
        self.var_excel.set(excel)
        self._refresh_files()
        self._inspect_excel(excel)

    def _fill_baustein_menu(self) -> None:
        self._reload_bausteine()

    def _apply_baustein(self, eintrag: dict) -> None:
        self.var_baustein.set(str(eintrag.get("name", "")))
        self.txt_fuss.delete("1.0", "end")
        self.txt_fuss.insert("1.0", str(eintrag.get("text", "")))
        self.set_status(f"Textbaustein „{eintrag.get('name', '')}“ geladen.")

    def delete_baustein(self) -> None:
        name = self.var_baustein.get().strip()
        if not name:
            messagebox.showwarning(APP_NAME, "Bitte zuerst den Namen des Textbausteins eintragen.")
            return
        vorher = len(self.bausteine)
        self.bausteine = [alt for alt in self.bausteine if str(alt.get("name", "")) != name]
        if len(self.bausteine) == vorher:
            messagebox.showwarning(APP_NAME, f"Kein Textbaustein mit dem Namen „{name}“.")
            return
        self.persist()
        self._reload_bausteine()
        self.set_status(f"Textbaustein „{name}“ gelöscht.")

    def _header_text(self) -> str:
        if not hasattr(self, "txt_kopf"):
            return self._kopf_start
        return self.txt_kopf.get("1.0", "end-1c").strip()

    def save_header(self) -> None:
        self.persist()
        if self._header_text():
            self.set_status("Kopfzeile gespeichert.")
            messagebox.showinfo(APP_NAME, "Die Kopfzeile wurde gespeichert.")
        else:
            self.set_status("Kopfzeile ist leer und wird nicht gedruckt.")
            messagebox.showinfo(APP_NAME, "Die Kopfzeile ist leer und erscheint nicht in der PDF.")

    def _footer_text(self) -> str:
        if not hasattr(self, "txt_fuss"):
            return self._fuss_start
        return self.txt_fuss.get("1.0", "end-1c").strip()

    def save_footer(self) -> None:
        name = self.var_baustein.get().strip()
        text = self._footer_text()
        if name:
            self.bausteine = [alt for alt in self.bausteine if str(alt.get("name", "")) != name]
            self.bausteine.insert(0, {"name": name, "text": text})
            self.bausteine = self.bausteine[:20]
        self.persist()
        self._reload_bausteine()
        if name:
            self.set_status(f"Textbaustein „{name}“ gespeichert.")
            messagebox.showinfo(APP_NAME, f"Der Textbaustein „{name}“ wurde gespeichert.")
        else:
            self.set_status("Fußzeile gespeichert.")
            messagebox.showinfo(APP_NAME, "Die Fußzeile wurde gespeichert.")

    def _reload_vorlagen(self) -> None:
        if not hasattr(self, "vorlage_combo"):
            return
        labels = [str(eintrag.get("name", "")) for eintrag in self.vorlagen]
        self._vorlage_by_label = {str(eintrag.get("name", "")): eintrag for eintrag in self.vorlagen}
        if labels:
            self.vorlage_combo.configure(values=labels)
            current = self.var_vorlage.get().strip()
            self.vorlage_combo.set(current if current in labels else "Vorlage wählen")
        else:
            self.vorlage_combo.configure(values=[])
            self.vorlage_combo.set("Noch keine Vorlage")
        self.after_idle(lambda: self._clear_hint(self.vorlage_combo))

    def _on_vorlage_pick(self, _event=None) -> None:
        eintrag = getattr(self, "_vorlage_by_label", {}).get(self.vorlage_combo.get())
        if eintrag:
            self._apply_vorlage(eintrag)

    def _apply_vorlage(self, eintrag: dict) -> None:
        self.var_vorlage.set(str(eintrag.get("name", "")))
        logo = str(eintrag.get("logo") or "").strip()
        if logo and Path(logo).is_file():
            self.var_logo.set(logo)
            self._refresh_files()
        if eintrag.get("format"):
            self.var_format.set(str(eintrag.get("format")))
            if hasattr(self, "_fmt_btns"):
                self._paint_format()
        if eintrag.get("dateiname"):
            self.var_name.set(str(eintrag.get("dateiname")))
        if eintrag.get("logo_breite"):
            self.var_breite.set(str(eintrag.get("logo_breite")))
        if eintrag.get("titel"):
            self.var_titel.set(str(eintrag.get("titel")))
        if eintrag.get("untertitel"):
            self.var_untertitel.set(str(eintrag.get("untertitel")))
        self._set_long_text("txt_kopf", "_kopf_start", str(eintrag.get("kopfzeile") or ""))
        self._set_long_text("txt_fuss", "_fuss_start", str(eintrag.get("fusszeile") or ""))
        self.regeln = []
        for regel in eintrag.get("regeln") or []:
            if not isinstance(regel, dict):
                continue
            nadel = str(regel.get("enthaelt") or "").strip()
            ziel = str(regel.get("zyklus") or "").strip()
            if nadel and ziel:
                self.regeln.append({"enthaelt": nadel, "zyklus": ziel})
        self._reload_regeln()
        self.persist()
        excel = self.var_excel.get().strip()
        if excel and Path(excel).is_file():
            self._inspect_excel(excel)
        self.set_status(f"Vorlage „{eintrag.get('name', '')}“ geladen.")

    def save_vorlage(self) -> None:
        name = self.var_vorlage.get().strip()
        if not name or name in {"Vorlage wählen", "Noch keine Vorlage"}:
            messagebox.showwarning(APP_NAME, "Bitte zuerst einen Namen für die Vorlage eintragen.")
            return
        eintrag = {
            "name": name,
            "logo": self.var_logo.get().strip(),
            "format": self.var_format.get(),
            "dateiname": self.var_name.get().strip(),
            "logo_breite": self.var_breite.get().strip(),
            "titel": self.var_titel.get().strip(),
            "untertitel": self.var_untertitel.get().strip(),
            "kopfzeile": self._header_text(),
            "fusszeile": self._footer_text(),
            "regeln": [dict(regel) for regel in self.regeln],
        }
        self.vorlagen = [alt for alt in self.vorlagen if str(alt.get("name", "")) != name]
        self.vorlagen.insert(0, eintrag)
        self.vorlagen = self.vorlagen[:20]
        self._reload_vorlagen()
        self.persist()
        self.set_status(f"Vorlage „{name}“ gespeichert.")
        messagebox.showinfo(APP_NAME, f"Die Vorlage „{name}“ wurde gespeichert.")

    def delete_vorlage(self) -> None:
        name = self.var_vorlage.get().strip()
        if not name or name not in getattr(self, "_vorlage_by_label", {}):
            messagebox.showwarning(APP_NAME, "Bitte zuerst eine Vorlage auswählen.")
            return
        self.vorlagen = [alt for alt in self.vorlagen if str(alt.get("name", "")) != name]
        self.var_vorlage.set("")
        self._reload_vorlagen()
        self.persist()
        self.set_status(f"Vorlage „{name}“ gelöscht.")

    def show_changelog(self) -> None:
        messagebox.showinfo(APP_NAME, "Neu in Version 2.0.0\n\n" + "\n\n".join(f"• {punkt}" for punkt in NEUERUNGEN))

    def _zeige_neuerungen(self) -> None:
        self.show_changelog()
        self._gesehen = VERSION
        self.persist()

    def show_help(self) -> None:
        messagebox.showinfo(
            APP_NAME,
            "1. Firmenname und Kundennummer eintragen oder unter „Zuletzt“ wählen.\n"
            "2. Die Excel-Datei wählen oder ins Fenster ziehen.\n"
            "3. Die blaue Kurzinfo unter der Excel-Datei lesen.\n"
            "4. Optional Logo, Zielordner, Kopf- und Fußzeile setzen.\n"
            "5. Auf „PDF erstellen“ klicken oder Strg+Enter.\n\n"
            "Stehen mehrere Rechnungsempfänger in der Excel, bitte einen auswählen.\n"
            "Zyklus-Regeln stehen unter Darstellung. Hott-KI wird standardmäßig jährlich ausgegeben.\n"
            "Zuletzt erstellte PDFs lassen sich unten wieder öffnen.\n"
            "Hotline-Zeilen werden als Supportvertrag ausgegeben.\n"
            "Nur Netto, kein Brutto.",
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            APP_NAME,
            f"{APP_NAME}\nVersion {VERSION}\n\n"
            "Entwickler und Inhaber: Jerico\n\n"
            "„Ich beleidige seine Mutter, weil wenn ich seine Mutter beleidige, "
            "beleidige ich nur ihn oder maximal noch seine Mutter.“\n"
            "— Manuelsen\n\n"
            "Lokale Windows-App für Vertragsübersichten.\n"
            "Python und alle Pakete sind im Setup enthalten.",
        )

    def persist(self) -> None:
        save_config(
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
                "fusszeile": self._footer_text(),
                "kopfzeile": self._header_text(),
                "baustein_name": self.var_baustein.get().strip(),
                "bausteine": self.bausteine,
                "kunden": self.kunden,
                "pdfs": self.pdfs[:8],
                "regeln": self.regeln,
                "vorlagen": self.vorlagen,
                "staende": self.staende,
                "gesehen": self._gesehen,
                "pdf_oeffnen": bool(self.var_open.get()),
                "theme": self.var_theme.get(),
                "accent": self.var_accent.get(),
            }
        )

    def _on_close(self) -> None:
        self._remember_customer()
        self.persist()
        self.destroy()

    def start_pdf(self) -> None:
        if self.busy:
            return
        excel = self.var_excel.get().strip()
        logo = self.var_logo.get().strip()
        kd = self.var_kd.get().strip()
        if not excel or not Path(excel).is_file():
            messagebox.showwarning(APP_NAME, "Bitte zuerst die Excel-Liste wählen.")
            return
        if not kd:
            messagebox.showwarning(APP_NAME, "Bitte die Kundennummer eintragen.")
            return
        if not logo or not Path(logo).is_file():
            messagebox.showwarning(APP_NAME, "Bitte eine Logo-Datei wählen.")
            return
        try:
            breite = float(self.var_breite.get().replace(",", "."))
        except ValueError:
            messagebox.showwarning(APP_NAME, "Die Logo-Breite muss eine Zahl sein (z. B. 62).")
            return
        empfaenger = self.var_mail.get().strip()
        if not empfaenger and len(self._excel_mails) > 1:
            wahl = self.mail_combo.get().strip()
            if wahl not in self._excel_mails:
                messagebox.showwarning(
                    APP_NAME,
                    "In der Excel stehen mehrere Rechnungsempfänger.\nBitte einen auswählen oder ins Feld eintragen.",
                )
                return
            empfaenger = wahl
        regeln = [dict(eintrag) for eintrag in self.regeln]

        self.persist()
        self.busy = True
        self.btn_pdf.configure(state="disabled", text="PDF wird erstellt …")
        self.set_status("PDF wird erstellt …")

        def work() -> None:
            try:
                from engine import PdfAuftrag, erstelle_pdf

                path = erstelle_pdf(
                    PdfAuftrag(
                        excel=Path(excel),
                        logo=Path(logo),
                        kundennummer=kd,
                        firmenname=self.var_firma.get().strip(),
                        rechnungsempfaenger=empfaenger,
                        zielordner=Path(self.var_ziel.get().strip() or desktop_dir()),
                        dateiname=self.var_name.get().strip(),
                        seitenformat=self.var_format.get(),
                        logo_breite=breite,
                        titel=self.var_titel.get().strip() or "Vertragsübersicht",
                        untertitel=self.var_untertitel.get().strip()
                        or "Wartungs- und Nutzungsverträge",
                        fusszeile=self._footer_text(),
                        kopfzeile=self._header_text(),
                        regeln=regeln,
                        pdf_oeffnen=False,
                        status=lambda m: self.after(0, lambda msg=m: self.set_status(msg)),
                    )
                )
                self.after(0, lambda: self._done(path))
            except Exception as exc:
                tb = traceback.format_exc()
                self.after(0, lambda: self._fail(exc, tb))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, path: Path) -> None:
        self.busy = False
        self.btn_pdf.configure(state="normal", text="PDF erstellen")
        self._remember_pdf(path)
        self._remember_customer(str(path))
        self.persist()
        self.set_status(f"PDF gespeichert: {path.name}")
        if self.var_open.get():
            self._open_pdf(path)
        else:
            messagebox.showinfo(APP_NAME, f"PDF gespeichert:\n{path}")

    def _open_pdf(self, path: Path) -> None:
        try:
            if hasattr(os, "startfile"):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                webbrowser.open(path.as_uri())
        except OSError as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def _fail(self, exc: Exception, tb: str) -> None:
        self.busy = False
        self.btn_pdf.configure(state="normal", text="PDF erstellen")
        self.set_status(f"Fehler: {exc}")
        try:
            (INSTALL_DIR / "fehler.log").write_text(tb, encoding="utf-8")
        except OSError:
            pass
        messagebox.showerror(APP_NAME, str(exc))


def main() -> None:
    _enable_dpi()
    apply_palette()
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
