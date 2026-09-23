"""Gemeinsamer Zustand der Oberfläche: Design, Schriften, Animationen, Bildcache."""

from __future__ import annotations

import tkinter as tk

from .animations import Animator
from .render import ImageCache
from .theme import Fonts, Palette, ThemeManager, build_fonts, init_scale


class UIContext:
    def __init__(self, root: tk.Tk, theme: ThemeManager, animations: bool = True) -> None:
        self.root = root
        self.scale = init_scale(root)
        self.theme = theme
        self.fonts: Fonts = build_fonts(root)
        self.anim = Animator(root, enabled=animations)
        self.images = ImageCache(root)
        self.keyboard_mode = False
        self._focus_listeners: dict[str, object] = {}
        # Haken für Popups: Mausklicks irgendwo in der App und Bewegungen des Hauptfensters
        self.press_hooks: list = []
        self.window_hooks: list = []
        root.bind_all("<KeyPress>", self._on_key, add="+")
        root.bind_all("<ButtonPress>", self._on_mouse, add="+")
        root.bind("<Configure>", self._on_root_configure, add="+")

    @property
    def pal(self) -> Palette:
        return self.theme.palette

    @property
    def icons_available(self) -> bool:
        return self.fonts.icon is not None

    def _on_key(self, event) -> None:
        if event.keysym in {"Tab", "ISO_Left_Tab", "Up", "Down", "Left", "Right", "Home", "End", "Prior", "Next"}:
            if not self.keyboard_mode:
                self.keyboard_mode = True
                self._notify_focus_mode()

    def _on_mouse(self, event) -> None:
        if self.keyboard_mode:
            self.keyboard_mode = False
            self._notify_focus_mode()
        for hook in list(self.press_hooks):
            try:
                hook(event)
            except Exception:
                pass

    def _on_root_configure(self, event) -> None:
        if event.widget is not self.root:
            return
        for hook in list(self.window_hooks):
            try:
                hook(event)
            except Exception:
                pass

    def on_focus_mode(self, widget: tk.Misc, callback) -> None:
        """Rückruf, wenn zwischen Maus- und Tastaturbedienung gewechselt wird (Fokusrahmen)."""
        key = str(widget)
        self._focus_listeners[key] = callback
        widget.bind("<Destroy>", lambda event, k=key, w=widget: self._focus_listeners.pop(k, None) if event.widget is w else None, add="+")

    def _notify_focus_mode(self) -> None:
        for callback in list(self._focus_listeners.values()):
            try:
                callback()
            except tk.TclError:
                pass


CTX: UIContext | None = None


def init(root: tk.Tk, theme: ThemeManager, animations: bool = True) -> UIContext:
    global CTX
    CTX = UIContext(root, theme, animations)
    return CTX


def ctx() -> UIContext:
    if CTX is None:
        raise RuntimeError("UI-Kontext ist nicht initialisiert")
    return CTX


def surface_of(widget: tk.Misc | None, default: str = "layer") -> str:
    """Palettenrolle der Fläche, auf der ein Widget liegt (z. B. "card")."""
    current = widget
    while current is not None:
        role = getattr(current, "surface_role", None)
        if role:
            return role
        current = getattr(current, "master", None)
    return default


def surface_color(widget: tk.Misc | None, default: str = "layer") -> str:
    role = surface_of(widget, default)
    if role.startswith("#"):
        return role
    return getattr(ctx().pal, role)
