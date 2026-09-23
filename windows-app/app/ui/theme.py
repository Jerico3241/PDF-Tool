"""Farben, Schriften und Maße nach den Windows-11-Designrichtlinien (WinUI 3).

Die Farbnamen folgen den WinUI-Ressourcen. Transparente WinUI-Pinsel sind als
deckende Farben für die jeweilige Unterlage vorberechnet, weil Tk keine
halbtransparenten Flächen zeichnen kann.
"""

from __future__ import annotations

import colorsys
import os
from dataclasses import dataclass, field, replace
from typing import Callable

import tkinter as tk
import tkinter.font as tkfont

from . import windows

# --- Farbrechnung ---------------------------------------------------------------


def rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def hexcolor(red: float, green: float, blue: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(round(c)))) for c in (red, green, blue)))


def mix(start: str, end: str, amount: float) -> str:
    """Lineare Mischung: amount=0 → start, amount=1 → end."""
    sr, sg, sb = rgb(start)
    er, eg, eb = rgb(end)
    return hexcolor(sr + (er - sr) * amount, sg + (eg - sg) * amount, sb + (eb - sb) * amount)


def overlay(surface: str, color: str, alpha: float) -> str:
    """Halbtransparente Farbe (color, alpha) auf einer deckenden Unterlage."""
    return mix(surface, color, alpha)


def luminance(value: str) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    red, green, blue = rgb(value)
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _with_lightness(value: str, lightness: float, min_saturation: float = 0.0) -> str:
    red, green, blue = (c / 255 for c in rgb(value))
    hue, _light, saturation = colorsys.rgb_to_hls(red, green, blue)
    saturation = max(saturation, min_saturation) if saturation > 0.05 else saturation
    r2, g2, b2 = colorsys.hls_to_rgb(hue, max(0.0, min(1.0, lightness)), saturation)
    return hexcolor(r2 * 255, g2 * 255, b2 * 255)


def _lightness(value: str) -> float:
    red, green, blue = (c / 255 for c in rgb(value))
    return colorsys.rgb_to_hls(red, green, blue)[1]


# --- Akzentfarben ----------------------------------------------------------------

SYSTEM_ACCENT = "system"

ACCENTS: tuple[tuple[str, str], ...] = (
    ("Blau", "#005FB8"),
    ("Rot", "#C42B1E"),
    ("Grün", "#0F7B0F"),
    ("Orange", "#D06B00"),
    ("Violett", "#6B4C9A"),
    ("Türkis", "#0E7C86"),
    ("Pink", "#C239B3"),
)

DEFAULT_ACCENT = "#005FB8"


@dataclass(frozen=True)
class Accent:
    """Akzent in beiden Designs: Füllung (Buttons, Auswahl) und Textfarbe (Links)."""

    light_fill: str
    light_text: str
    dark_fill: str
    dark_text: str


def derive_accent(fill_for_light: str) -> Accent:
    """Leitet aus einer Füllfarbe für das helle Design die Windows-typischen Abstufungen ab.

    Windows verwendet im hellen Design »Dark1« und im dunklen Design »Light2«
    der Akzentpalette. Für eigene Farben wird die Palette über die Helligkeit
    nachgebildet.
    """
    base = fill_for_light.upper()
    light_l = _lightness(base)
    if light_l > 0.46:
        base = _with_lightness(base, 0.40)
        light_l = 0.40
    # Weißer Text auf der Akzentfläche braucht mindestens 4,5:1 (WCAG AA).
    while contrast(base, "#FFFFFF") < 4.5 and light_l > 0.12:
        light_l -= 0.02
        base = _with_lightness(base, light_l)
    dark_l = 0.70
    dark_fill = _with_lightness(base, dark_l, 0.55)
    while contrast(dark_fill, "#000000") < 4.5 and dark_l < 0.9:
        dark_l += 0.02
        dark_fill = _with_lightness(base, dark_l, 0.55)
    return Accent(
        light_fill=base,
        light_text=_with_lightness(base, light_l * 0.85),
        dark_fill=dark_fill,
        dark_text=_with_lightness(base, 0.80, 0.5),
    )


def system_accent() -> Accent:
    palette = windows.accent_palette()
    if not palette:
        return derive_accent(DEFAULT_ACCENT)
    if "dark1" in palette:
        return Accent(
            light_fill=palette["dark1"],
            light_text=palette["dark2"],
            dark_fill=palette["light2"],
            dark_text=palette["light3"],
        )
    return derive_accent(palette["base"])


def resolve_accent(choice: str) -> Accent:
    if choice == SYSTEM_ACCENT:
        return system_accent()
    try:
        rgb(choice)
    except (ValueError, IndexError):
        choice = DEFAULT_ACCENT
    return derive_accent(choice)


def accent_name(choice: str) -> str:
    if choice == SYSTEM_ACCENT:
        return "Windows-Akzentfarbe"
    for name, value in ACCENTS:
        if value.lower() == str(choice).lower():
            return name
    return "Benutzerdefiniert"


# --- Palette ------------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    dark: bool
    # Flächen
    mica: str  # Fensterhintergrund / Navigationsbereich (SolidBackgroundFillColorBase)
    layer: str  # Inhaltsebene rechts (LayerFillColorDefault auf Mica)
    layer_stroke: str
    card: str  # CardBackgroundFillColorDefault auf der Inhaltsebene
    card_stroke: str
    card_secondary: str
    divider: str
    flyout: str  # Aufklappmenüs, Tooltips
    flyout_stroke: str
    dialog: str
    dialog_footer: str
    # Text
    text: str
    text2: str
    text3: str
    text_disabled: str
    # Steuerelemente
    control: str
    control_hover: str
    control_pressed: str
    control_disabled: str
    control_stroke: str
    control_edge: str  # untere (hell) bzw. obere (dunkel) Kante: Elevation-Border
    input_focus: str
    input_edge: str
    strong: str  # ControlStrongFillColorDefault: Schalter, Scrollbar
    strong_stroke: str
    subtle_color: str  # Basis für halbtransparente Hover-Flächen
    subtle_hover_alpha: float
    subtle_pressed_alpha: float
    # Akzent
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_disabled: str
    accent_text: str
    on_accent: str
    on_accent_pressed: str
    on_accent_disabled: str
    accent_stroke: str
    accent_edge: str
    # Fokus
    focus_outer: str
    focus_inner: str
    # Status
    success: str
    success_bg: str
    caution: str
    caution_bg: str
    critical: str
    critical_bg: str
    info_bg: str
    neutral: str
    on_status: str
    critical_hover: str = ""
    critical_pressed: str = ""
    extras: dict = field(default_factory=dict)

    def subtle_hover(self, surface: str) -> str:
        return overlay(surface, self.subtle_color, self.subtle_hover_alpha)

    def subtle_pressed(self, surface: str) -> str:
        return overlay(surface, self.subtle_color, self.subtle_pressed_alpha)

    def get(self, name: str) -> str:
        return getattr(self, name)


def build_palette(dark: bool, accent: Accent) -> Palette:
    if not dark:
        fill = accent.light_fill
        layer = "#F9F9F9"
        card = "#FDFDFD"
        pal = Palette(
            dark=False,
            mica="#F3F3F3",
            layer=layer,
            layer_stroke="#E5E5E5",
            card=card,
            card_stroke="#E5E5E5",
            card_secondary="#F6F6F6",
            divider="#EBEBEB",
            flyout="#F9F9F9",
            flyout_stroke="#D2D2D2",
            dialog="#FFFFFF",
            dialog_footer="#F3F3F3",
            text="#1A1A1A",
            text2="#5D5D5D",
            text3="#8A8A8A",
            text_disabled="#A0A0A0",
            control="#FEFEFE",
            control_hover="#F6F6F6",
            control_pressed="#F1F1F1",
            control_disabled="#F7F7F7",
            control_stroke="#E3E3E3",
            control_edge="#C9C9C9",
            input_focus="#FFFFFF",
            input_edge="#868686",
            strong="#5D5D5D",
            strong_stroke="#8A8A8A",
            subtle_color="#000000",
            subtle_hover_alpha=0.042,
            subtle_pressed_alpha=0.026,
            accent=fill,
            accent_hover=mix(fill, card, 0.10),
            accent_pressed=mix(fill, card, 0.20),
            accent_disabled="#C5C5C5",
            accent_text=accent.light_text,
            on_accent="#FFFFFF",
            on_accent_pressed=mix("#FFFFFF", fill, 0.25),
            on_accent_disabled="#FFFFFF",
            accent_stroke=mix(fill, "#FFFFFF", 0.08),
            accent_edge=mix(fill, "#000000", 0.32),
            focus_outer="#1A1A1A",
            focus_inner="#FFFFFF",
            success="#0F7B0F",
            success_bg="#DFF6DD",
            caution="#9D5D00",
            caution_bg="#FFF4CE",
            critical="#C42B1E",
            critical_bg="#FDE7E9",
            info_bg="#F6F6F6",
            neutral="#8A8A8A",
            on_status="#FFFFFF",
        )
    else:
        fill = accent.dark_fill
        layer = "#282828"
        card = "#2C2C2C"
        pal = Palette(
            dark=True,
            mica="#202020",
            layer=layer,
            layer_stroke="#1C1C1C",
            card=card,
            card_stroke="#1D1D1D",
            card_secondary="#313131",
            divider="#3B3B3B",
            flyout="#2C2C2C",
            flyout_stroke="#474747",
            dialog="#2B2B2B",
            dialog_footer="#202020",
            text="#FFFFFF",
            text2="#CFCFCF",
            text3="#9A9A9A",
            text_disabled="#717171",
            control="#383838",
            control_hover="#3E3E3E",
            control_pressed="#333333",
            control_disabled="#323232",
            control_stroke="#444444",
            control_edge="#4E4E4E",
            input_focus="#1F1F1F",
            input_edge="#9E9E9E",
            strong="#CFCFCF",
            strong_stroke="#9E9E9E",
            subtle_color="#FFFFFF",
            subtle_hover_alpha=0.060,
            subtle_pressed_alpha=0.040,
            accent=fill,
            accent_hover=mix(fill, card, 0.10),
            accent_pressed=mix(fill, card, 0.20),
            accent_disabled="#4A4A4A",
            accent_text=accent.dark_text,
            on_accent="#000000",
            on_accent_pressed=mix("#000000", fill, 0.45),
            on_accent_disabled="#878787",
            accent_stroke=mix(fill, "#FFFFFF", 0.10),
            accent_edge=mix(fill, "#000000", 0.14),
            focus_outer="#FFFFFF",
            focus_inner="#000000",
            success="#6CCB5F",
            success_bg="#393D1B",
            caution="#FCE100",
            caution_bg="#433519",
            critical="#FF99A4",
            critical_bg="#442726",
            info_bg="#313131",
            neutral="#9A9A9A",
            on_status="#000000",
        )
    return replace(
        pal,
        critical_hover=mix(pal.critical, pal.card, 0.10),
        critical_pressed=mix(pal.critical, pal.card, 0.20),
    )


# --- Skalierung ---------------------------------------------------------------------

_SCALE = 1.0


def init_scale(root: tk.Misc) -> float:
    """Skalierungsfaktor relativ zu 96 DPI (100 %). UE_SCALE überschreibt ihn für Tests."""
    global _SCALE
    forced = os.environ.get("UE_SCALE")
    if forced:
        try:
            _SCALE = max(0.75, min(4.0, float(forced)))
            return _SCALE
        except ValueError:
            pass
    try:
        _SCALE = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except tk.TclError:
        _SCALE = 1.0
    return _SCALE


def scale() -> float:
    return _SCALE


def px(value: float) -> int:
    """Effektive Pixel (Windows-Designmaße bei 100 %) in Bildschirmpixel."""
    if value == 0:
        return 0
    result = int(round(value * _SCALE))
    if result == 0:
        return 1 if value > 0 else -1
    return result


# --- Schriften ------------------------------------------------------------------------

FAMILY_CANDIDATES = {
    "text": ("Segoe UI Variable Text", "Segoe UI Variable Static Text", "Segoe UI"),
    "text_semibold": (
        "Segoe UI Variable Text Semibold",
        "Segoe UI Variable Static Text Semibold",
        "Segoe UI Semibold",
    ),
    "small": ("Segoe UI Variable Small", "Segoe UI Variable Static Small", "Segoe UI"),
    "display_semibold": (
        "Segoe UI Variable Display Semibold",
        "Segoe UI Variable Static Display Semibold",
        "Segoe UI Semibold",
    ),
    "icons": ("Segoe Fluent Icons", "Segoe MDL2 Assets"),
}


def _family_available(root: tk.Misc, family: str) -> bool:
    try:
        probe = tkfont.Font(root=root, family=family, size=-12)
        actual = str(probe.actual("family"))
    except tk.TclError:
        return False
    return actual.casefold() == family.casefold()


@dataclass
class Fonts:
    caption: tkfont.Font
    caption_strong: tkfont.Font
    body: tkfont.Font
    body_strong: tkfont.Font
    body_large: tkfont.Font
    subtitle: tkfont.Font
    title: tkfont.Font
    icon: tkfont.Font | None
    icon_small: tkfont.Font | None
    icon_large: tkfont.Font | None
    families: dict


def _make_font(root: tk.Misc, families: dict, role: str, size: int, fallback_bold: bool = False) -> tkfont.Font:
    family = families.get(role)
    weight = "normal"
    if family is None:
        base = families.get("text") or "TkDefaultFont"
        family = base
        weight = "bold" if fallback_bold else "normal"
    return tkfont.Font(root=root, family=family, size=-px(size), weight=weight)


def build_fonts(root: tk.Misc) -> Fonts:
    """Typografie-Rampe von Windows 11: Caption 12, Body 14, Subtitle 20, Title 28."""
    families: dict[str, str | None] = {}
    for role, candidates in FAMILY_CANDIDATES.items():
        families[role] = next((name for name in candidates if _family_available(root, name)), None)
    if families["text"] is None:
        families["text"] = str(tkfont.nametofont("TkDefaultFont", root=root).actual("family"))
    if families["small"] is None:
        families["small"] = families["text"]
    semibold_real = families["text_semibold"] is not None
    fonts = Fonts(
        caption=_make_font(root, families, "small", 12),
        caption_strong=_make_font(root, families, "text_semibold", 12, True),
        body=_make_font(root, families, "text", 14),
        body_strong=_make_font(root, families, "text_semibold", 14, True),
        body_large=_make_font(root, families, "text", 18),
        subtitle=_make_font(root, families, "display_semibold", 20, True),
        title=_make_font(root, families, "display_semibold", 28, True),
        icon=None,
        icon_small=None,
        icon_large=None,
        families={**families, "semibold_real": semibold_real},
    )
    if families["icons"]:
        fonts.icon = tkfont.Font(root=root, family=families["icons"], size=-px(16))
        fonts.icon_small = tkfont.Font(root=root, family=families["icons"], size=-px(12))
        fonts.icon_large = tkfont.Font(root=root, family=families["icons"], size=-px(20))
    # Standardschriften von Tk angleichen, damit Dateidialoge-Fallbacks und Menüs passen.
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
        try:
            tkfont.nametofont(name, root=root).configure(family=families["text"], size=-px(14))
        except tk.TclError:
            pass
    try:
        tkfont.nametofont("TkTooltipFont", root=root).configure(family=families["small"], size=-px(12))
        tkfont.nametofont("TkSmallCaptionFont", root=root).configure(family=families["small"], size=-px(12))
    except tk.TclError:
        pass
    return fonts


# --- Theme-Verwaltung --------------------------------------------------------------

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"


class ThemeManager:
    """Hält das aktive Design und benachrichtigt registrierte Widgets bei Änderungen."""

    def __init__(self, root: tk.Tk, mode: str = THEME_SYSTEM, accent: str = SYSTEM_ACCENT) -> None:
        self.root = root
        self.mode = mode if mode in (THEME_SYSTEM, THEME_LIGHT, THEME_DARK) else THEME_SYSTEM
        self.accent_choice = accent or SYSTEM_ACCENT
        self._listeners: dict[int, Callable[[], None]] = {}
        self._plain: dict[str, tuple[tk.Misc, dict[str, str]]] = {}
        self._next = 0
        self.palette = build_palette(self.is_dark(), resolve_accent(self.accent_choice))

    # Zustand -------------------------------------------------------------
    def is_dark(self) -> bool:
        if self.mode == THEME_DARK:
            return True
        if self.mode == THEME_LIGHT:
            return False
        return not windows.apps_use_light_theme()

    def set(self, mode: str | None = None, accent: str | None = None, force: bool = False) -> bool:
        if mode is not None:
            self.mode = mode
        if accent is not None:
            self.accent_choice = accent
        palette = build_palette(self.is_dark(), resolve_accent(self.accent_choice))
        if palette == self.palette and not force:
            return False
        self.palette = palette
        self._notify()
        return True

    # Registrierung -----------------------------------------------------------
    def subscribe(self, callback: Callable[[], None], owner: tk.Misc | None = None) -> int:
        token = self._next
        self._next += 1
        self._listeners[token] = callback
        if owner is not None:
            try:
                owner.bind("<Destroy>", lambda event, t=token, o=owner: self._drop(t, event, o), add="+")
            except tk.TclError:
                pass
        return token

    def unsubscribe(self, token: int) -> None:
        self._listeners.pop(token, None)

    def _drop(self, token: int, event, owner) -> None:
        if event.widget is owner:
            self._listeners.pop(token, None)

    def style(self, widget: tk.Misc, **roles: str) -> tk.Misc:
        """Einfache Tk-Widgets einfärben und bei Designwechseln automatisch nachziehen.

        Beispiel: ``theme.style(label, bg="card", fg="text2")``.
        """
        key = str(widget)
        self._plain[key] = (widget, roles)
        self._apply_plain(widget, roles)
        try:
            widget.bind("<Destroy>", lambda event, k=key, w=widget: self._forget_plain(event, k, w), add="+")
        except tk.TclError:
            pass
        return widget

    def _forget_plain(self, event, key: str, widget) -> None:
        if event.widget is widget:
            self._plain.pop(key, None)

    def _apply_plain(self, widget: tk.Misc, roles: dict[str, str]) -> None:
        options = {}
        for option, role in roles.items():
            options[option] = getattr(self.palette, role) if not role.startswith("#") else role
        try:
            widget.configure(**options)
        except tk.TclError:
            pass

    def _notify(self) -> None:
        for widget, roles in list(self._plain.values()):
            self._apply_plain(widget, roles)
        for callback in list(self._listeners.values()):
            try:
                callback()
            except tk.TclError:
                pass
            except Exception:
                import traceback

                traceback.print_exc()
