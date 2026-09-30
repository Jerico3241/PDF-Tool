"""Design der App: Hell/Dunkel/System, Akzentfarbe, Animationsprofil und Mica.

Die Farben entstehen wie in 2.6 aus ``design`` (WinUI-Palette, Windows-Akzent). QML erhält
sie als Design-Tokens (``colors``) und entscheidet selbst über Darstellung und Übergänge.

Animationsprofile: ``full`` (Vollständig), ``reduced`` (Reduziert: kurze Überblendungen und
Farbwechsel, keine größeren Bewegungen) und ``off`` (Aus: Zustände wechseln sofort). Ist in
Windows »Animationseffekte« ausgeschaltet, gilt mindestens »Reduziert«.
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import QGuiApplication

import design
import winsys
from mica import MicaSource

from .base import Observable, prop

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEMES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)
THEME_LABELS = {THEME_SYSTEM: "Wie Windows", THEME_LIGHT: "Hell", THEME_DARK: "Dunkel"}
PROFILE_FULL = "full"
PROFILE_REDUCED = "reduced"
PROFILE_OFF = "off"
PROFILES = (PROFILE_FULL, PROFILE_REDUCED, PROFILE_OFF)
PROFILE_LABELS = {PROFILE_FULL: "Vollständig", PROFILE_REDUCED: "Reduziert", PROFILE_OFF: "Aus"}
CONFIG_PROFILE = "animationsprofil"
CONFIG_LEGACY_ANIMATIONS = "animationen"  # bis 2.6: an/aus bzw. »wie Windows« (fehlt)


def valid_accent(value) -> str:
    if value == design.SYSTEM_ACCENT:
        return design.SYSTEM_ACCENT
    text = str(value or "")
    try:
        design.rgb(text)
    except (ValueError, IndexError):
        return design.SYSTEM_ACCENT
    return text.upper() if text.startswith("#") and len(text) == 7 else design.SYSTEM_ACCENT


def profile_from_config(cfg: dict) -> str:
    """Gespeichertes Profil; aus 2.6 übernommen: »aus« bleibt aus, sonst Vollständig."""
    value = cfg.get(CONFIG_PROFILE)
    if value in PROFILES:
        return value
    legacy = cfg.get(CONFIG_LEGACY_ANIMATIONS)
    if legacy is False:
        return PROFILE_OFF
    return PROFILE_FULL


class ThemeController(Observable):
    modeChanged, mode = prop(str, "mode", THEME_SYSTEM)
    darkChanged, dark = prop(bool, "dark", False)
    accentChoiceChanged, accentChoice = prop(str, "accentChoice", design.SYSTEM_ACCENT)
    accentNameChanged, accentName = prop(str, "accentName", "")
    colorsChanged, colors = prop(dict, "colors", {})
    accentsChanged, accents = prop(list, "accents", [])
    profileChanged, profile = prop(str, "profile", PROFILE_FULL)
    systemReducedMotionChanged, systemReducedMotion = prop(bool, "systemReducedMotion", False)
    effectiveProfileChanged, effectiveProfile = prop(str, "effectiveProfile", PROFILE_FULL)
    profileNoteChanged, profileNote = prop(str, "profileNote", "")
    micaEnabledChanged, micaEnabled = prop(bool, "micaEnabled", True)
    micaAvailableChanged, micaAvailable = prop(bool, "micaAvailable", False)
    micaSourceChanged, micaSource = prop(str, "micaSource", "")
    micaDescriptionChanged, micaDescription = prop(str, "micaDescription", "")
    fontFamilyChanged, fontFamily = prop(str, "fontFamily", "")
    displayFamilyChanged, displayFamily = prop(str, "displayFamily", "")
    revisionChanged, revision = prop(int, "revision", 0)

    def __init__(self, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        mode = cfg.get("theme")
        self._mode = mode if mode in THEMES else THEME_SYSTEM
        self.set_quietly("mode", self._mode)
        self.set_quietly("accentChoice", valid_accent(cfg.get("accent", design.SYSTEM_ACCENT)))
        self.set_quietly("profile", profile_from_config(cfg))
        self.set_quietly("micaEnabled", bool(cfg.get("mica", True)))
        self.set_quietly("micaAvailable", winsys.mica_supported())
        self.mica = MicaSource()
        self._mica_thread: threading.Thread | None = None
        self._wallpaper = None
        self._palette: design.Palette | None = None
        self._pick_fonts()
        self._refresh_motion()
        self._apply(initial=True)
        self._describe_mica()
        hints = QGuiApplication.styleHints()
        try:
            hints.colorSchemeChanged.connect(lambda _scheme: self.refresh_system())
        except AttributeError:  # ältere Qt-Versionen
            pass
        if self.micaWanted():
            self._load_mica()

    # Zustand -------------------------------------------------------------------------------
    @property
    def palette(self) -> design.Palette:
        assert self._palette is not None
        return self._palette

    def is_dark(self) -> bool:
        if self.mode == THEME_DARK:
            return True
        if self.mode == THEME_LIGHT:
            return False
        if winsys.IS_WINDOWS:
            return not winsys.apps_use_light_theme()
        scheme = QGuiApplication.styleHints().colorScheme()
        return scheme == Qt.ColorScheme.Dark

    def _apply(self, initial: bool = False) -> bool:
        palette = design.build_palette(self.is_dark(), design.resolve_accent(self.accentChoice))
        if palette == self._palette:
            return False
        self._palette = palette
        tokens = design.palette_tokens(palette)
        # Halbtransparente Hover- und Druckflächen für die üblichen Unterlagen (vorberechnet wie in 2.6)
        for surface in ("card", "layer", "mica", "flyout", "card_secondary", "dialog"):
            tokens[f"hover_{surface}"] = palette.subtle_hover(getattr(palette, surface))
            tokens[f"pressed_{surface}"] = palette.subtle_pressed(getattr(palette, surface))
        tokens["subtle_hover_rgba"] = _rgba(palette.subtle_color, palette.subtle_hover_alpha)
        tokens["subtle_pressed_rgba"] = _rgba(palette.subtle_color, palette.subtle_pressed_alpha)
        tokens["smoke"] = "#4D000000" if not palette.dark else "#66000000"  # Abdunkelung hinter Dialogen
        tokens["shadow"] = "#24000000" if not palette.dark else "#52000000"
        self.dark = palette.dark
        self.colors = tokens
        self.accentName = design.accent_name(self.accentChoice)
        self.accents = self._accent_items()
        self.micaSource = self._mica_url()
        if not initial:
            self.revision = self.revision + 1
        return True

    def _accent_items(self) -> list[dict]:
        dark = self._palette.dark if self._palette else False
        system = design.system_accent()
        items = [{"value": design.SYSTEM_ACCENT, "name": "Windows-Akzentfarbe", "color": system.dark_fill if dark else system.light_fill, "system": True}]
        for name, value in design.ACCENTS:
            accent = design.derive_accent(value)
            items.append({"value": value, "name": name, "color": accent.dark_fill if dark else accent.light_fill, "system": False})
        return items

    def _pick_fonts(self) -> None:
        from PySide6.QtGui import QFontDatabase

        families = set(QFontDatabase.families())
        text = next((name for name in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI") if name in families), "")
        display = next((name for name in ("Segoe UI Variable Display", "Segoe UI Variable", "Segoe UI") if name in families), "")
        default = QGuiApplication.font().family()
        self.fontFamily = text or default
        self.displayFamily = display or self.fontFamily

    # Animationen ------------------------------------------------------------------------------
    def _refresh_motion(self) -> None:
        reduced = not winsys.client_area_animations()
        self.systemReducedMotion = reduced
        if os.environ.get("UE_NO_ANIMATIONS"):
            effective = PROFILE_OFF
        elif self.profile == PROFILE_FULL and reduced:
            effective = PROFILE_REDUCED
        else:
            effective = self.profile
        self.effectiveProfile = effective
        if self.profile == PROFILE_FULL and reduced:
            self.profileNote = "In Windows sind die Animationseffekte ausgeschaltet – es gilt »Reduziert«."
        else:
            self.profileNote = ""

    @Slot(str)
    def setProfile(self, profile: str) -> None:
        if profile in PROFILES and profile != self.profile:
            self.profile = profile
            self._refresh_motion()

    # Design und Akzent ------------------------------------------------------------------------
    @Slot(str)
    def setMode(self, mode: str) -> None:
        if mode in THEMES:
            self.mode = mode
            self._apply()

    @Slot(str)
    def setAccent(self, value: str) -> None:
        self.accentChoice = valid_accent(value)
        self._apply()

    @Slot()
    def refresh_system(self) -> None:
        """Systemeinstellungen neu lesen (Design, Akzent, Animationseffekte, Hintergrundbild) – nur echte Änderungen wirken."""
        self._refresh_motion()
        self.micaAvailable = winsys.mica_supported()
        changed = self._apply()
        if not changed:
            self.accents = self._accent_items()  # das Farbfeld »Windows-Akzentfarbe« folgt dem System
        self._describe_mica()
        if self.micaWanted() and winsys.wallpaper_state() != self._wallpaper:
            self._load_mica()

    # Mica ----------------------------------------------------------------------------------------
    def micaWanted(self) -> bool:
        return self.micaEnabled and self.micaAvailable

    @Slot(bool)
    def setMica(self, enabled: bool) -> None:
        self.micaEnabled = bool(enabled)
        if self.micaWanted() and not self.mica.available:
            self._load_mica()
        self.micaSource = self._mica_url()
        self._describe_mica()

    def _describe_mica(self) -> None:
        if not self.micaAvailable:
            self.micaDescription = "Nicht verfügbar: erfordert Windows 11 mit aktivierten Transparenzeffekten."
        else:
            self.micaDescription = "Titelleiste und Navigation erhalten den dezenten Farbton des Desktophintergrunds."

    def _load_mica(self) -> None:
        if self._mica_thread is not None and self._mica_thread.is_alive():
            return
        self._wallpaper = winsys.wallpaper_state()

        def load() -> None:
            self.mica.load()

        self._mica_thread = threading.Thread(target=load, name="mica", daemon=True)
        self._mica_thread.start()
        self._poll_mica()

    def _poll_mica(self) -> None:
        from PySide6.QtCore import QTimer

        if self._mica_thread is not None and self._mica_thread.is_alive():
            QTimer.singleShot(80, self._poll_mica)
            return
        self.micaSource = self._mica_url()

    def _mica_url(self) -> str:
        if not self.micaWanted() or not self.mica.available:
            return ""
        return f"image://mica/{self.mica.generation}/{'dark' if self.dark else 'light'}"

    # Speichern ------------------------------------------------------------------------------------
    def config(self) -> dict:
        data = {"theme": self.mode, "accent": self.accentChoice, "mica": bool(self.micaEnabled), CONFIG_PROFILE: self.profile}
        # Für ältere Versionen (bis 2.6): »aus« bleibt aus, sonst wie Windows.
        data[CONFIG_LEGACY_ANIMATIONS] = False if self.profile == PROFILE_OFF else None
        return data


def _rgba(color: str, alpha: float) -> str:
    """»#RRGGBB« + Deckkraft → »#AARRGGBB« (QML-Farbschreibweise)."""
    return "#{:02X}{}".format(max(0, min(255, round(alpha * 255))), color.lstrip("#").upper())
