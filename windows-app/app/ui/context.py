"""Gemeinsamer Zustand der Oberfläche: Design, Schriften, Animationen, Bildcache, Layout."""

from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace
from typing import Callable

import _tkinter

from . import windows
from .animations import AnimationManager
from .render import ImageCache
from .theme import Fonts, Palette, ThemeManager, build_fonts, init_scale

# Nach dieser Pause ohne Größenänderung gilt ein Resize als abgeschlossen (Millisekunden, entprellt).
RESIZE_SETTLE_MS = 80

# Responsive Layoutzustände des Hauptfensters
MODE_WIDE = "wide"  # Navigation ausgeklappt
MODE_MEDIUM = "medium"  # Navigation kompakt (nur Symbole), Karten zweispaltig
MODE_COMPACT = "compact"  # Navigation kompakt, Karten einspaltig


class LayoutState:
    """Zentral berechneter Layoutzustand. Ändert sich nur beim Überschreiten eines Breakpoints."""

    def __init__(self) -> None:
        self.mode = MODE_WIDE
        self.columns = 2
        self._listeners: dict[int, Callable[[], None]] = {}
        self._next = 0

    def subscribe(self, callback: Callable[[], None], owner: tk.Misc | None = None) -> int:
        token = self._next
        self._next += 1
        self._listeners[token] = callback
        if owner is not None:
            owner.bind("<Destroy>", lambda event, t=token, o=owner: self._listeners.pop(t, None) if event.widget is o else None, add="+")
        return token

    def set(self, mode: str, columns: int) -> bool:
        if (mode, columns) == (self.mode, self.columns):
            return False
        self.mode, self.columns = mode, columns
        for callback in list(self._listeners.values()):
            try:
                callback()
            except tk.TclError:
                pass
        return True


class UIContext:
    def __init__(self, root: tk.Tk, theme: ThemeManager, animations: bool = True, reduce_motion: bool = False) -> None:
        self.root = root
        self.scale = init_scale(root)
        self.theme = theme
        self.fonts: Fonts = build_fonts(root)
        self.anim = AnimationManager(root, enabled=animations, reduce_motion=reduce_motion)
        self.images = ImageCache(root)
        self.layout = LayoutState()
        self.keyboard_mode = False
        # Erst nach dem Anzeigen des Hauptfensters zählen Größenänderungen als Resize.
        self.ready = False
        self._root_size: tuple[int, int] | None = None
        self._after_resize: dict[str, Callable[[], None]] = {}
        self._focus_blocked: set[str] = set()
        self._focus_listeners: dict[str, object] = {}
        # Haken für Popups: Mausklicks irgendwo in der App und Bewegungen des Hauptfensters
        self.press_hooks: list = []
        self.window_hooks: list = []
        root.bind_all("<KeyPress>", self._on_key, add="+")
        root.bind_all("<ButtonPress>", self._on_mouse, add="+")
        self._bind_root_configure()
        self._install_focus_filter()

    # Tastaturfokus ---------------------------------------------------------------------
    def block_focus(self, widget: tk.Misc, blocked: bool) -> None:
        """Tab/Umschalt+Tab überspringen ``widget`` samt Inhalt (abgelegte Seiten, eingeklappte Bereiche).

        Solche Bereiche bleiben abgebildet (kein Neuaufbau beim Zeigen), sind aber nicht zu sehen.
        """
        if blocked:
            self._focus_blocked.add(str(widget))
        else:
            self._focus_blocked.discard(str(widget))

    def focus_blocked(self, path: str) -> bool:
        path = str(path)
        return any(path == blocked or path.startswith(blocked + ".") for blocked in self._focus_blocked)

    def _install_focus_filter(self) -> None:
        """Tk-Tabulatorreihenfolge (::tk::FocusOK) um die gesperrten Bereiche ergänzen."""
        interp = self.root.tk
        try:
            interp.call("auto_load", "::tk::FocusOK")
            if not interp.call("info", "procs", "::tk::FocusOK"):
                return
            if interp.call("info", "procs", "::tk::FocusOK_ue"):
                return
            command = self.root.register(lambda path: 1 if self.focus_blocked(path) else 0)
            interp.eval(
                "rename ::tk::FocusOK ::tk::FocusOK_ue\n"
                f"proc ::tk::FocusOK {{w}} {{ if {{[{command} $w]}} {{return 0}}\n return [::tk::FocusOK_ue $w] }}"
            )
        except tk.TclError:
            pass

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

    def _bind_root_configure(self) -> None:
        """Größe und Lage des Hauptfensters verfolgen.

        Eine Bindung an das Hauptfenster erhält über die Bindtags die ``<Configure>``-Ereignisse
        aller Widgets darin – beim Start und bei jedem Resize Tausende. Gefiltert wird deshalb
        schon in Tcl: Python wird nur für das Hauptfenster selbst aufgerufen, und nur mit Breite
        und Höhe (ohne die teure Umwandlung in ein Ereignisobjekt).
        """
        root = self.root
        command = root.register(self._root_configured)
        path = str(root)
        root.tk.call("bind", path, "<Configure>", f'+if {{"%W" eq "{path}"}} {{{command} %w %h}}')

    def _root_configured(self, width: str, height: str) -> None:
        try:
            event = SimpleNamespace(widget=self.root, width=int(width), height=int(height))
        except ValueError:
            return
        self._on_root_configure(event)

    def _on_root_configure(self, event) -> None:
        if event.widget is not self.root:
            return
        size = (event.width, event.height)
        if size != self._root_size:
            self._root_size = size
            if self.ready:
                self._resize_activity()
        for hook in list(self.window_hooks):
            try:
                hook(event)
            except Exception:
                import traceback

                traceback.print_exc()

    # Resize ---------------------------------------------------------------------------
    def _resize_activity(self) -> None:
        """Größenänderung: Animationen pausieren, Ende nach kurzer Ruhe feststellen (Debounce)."""
        self.anim.is_resizing = True
        self.anim.later("ui:resize-end", RESIZE_SETTLE_MS, self._resize_finished)

    def _resize_finished(self) -> None:
        self.anim.is_resizing = False
        calls = list(self._after_resize.values())
        self._after_resize.clear()
        for call in calls:
            try:
                call()
            except tk.TclError:
                pass

    def after_resize(self, key: str, func: Callable[[], None]) -> None:
        """``func`` sofort ausführen – oder, während eines Resize, einmalig an dessen Ende."""
        if self.anim.is_resizing:
            self._after_resize[key] = func
        else:
            func()

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


def init(root: tk.Tk, theme: ThemeManager, animations: bool = True, reduce_motion: bool = False) -> UIContext:
    global CTX
    CTX = UIContext(root, theme, animations, reduce_motion)
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


class SizeEvent:
    """Schlankes ``<Configure>``-Ereignis: nur Widget, Breite und Höhe."""

    __slots__ = ("widget", "width", "height")

    def __init__(self, widget: tk.Misc, width: int, height: int) -> None:
        self.widget = widget
        self.width = width
        self.height = height


def bind_size(widget: tk.Misc, callback: Callable[[SizeEvent], object]) -> None:
    """``<Configure>`` ohne teure Ereignisumwandlung – ``callback`` erhält nur Breite und Höhe.

    tkinter wandelt für jedes gebundene Ereignis 19 Felder um. Größenereignisse kommen beim
    Aufbau und bei jeder Änderung der Fenstergröße zu Tausenden; hier genügt ein schlankes
    Objekt mit ``widget``, ``width`` und ``height``.
    """

    def handler(width: str, height: str) -> None:
        try:
            event = SizeEvent(widget, int(width), int(height))
        except ValueError:
            return
        callback(event)

    command = widget.register(handler)
    widget.tk.call("bind", str(widget), "<Configure>", f"+{command} %w %h")


def bind_own(widget: tk.Misc, sequence: str, callback: Callable[[], None]) -> None:
    """Ereignis nur für ``widget`` selbst – nicht für alle Kinder.

    Bindungen an ein Toplevel gelten über die Bindtags auch für jedes Widget darin (z. B.
    ``<Activate>`` bei jedem Fensterwechsel für Hunderte Widgets). Gefiltert wird in Tcl;
    Python wird nur für das Fenster selbst aufgerufen, ohne teures Ereignisobjekt.
    """
    command = widget.register(callback)
    path = str(widget)
    widget.tk.call("bind", path, sequence, f'+if {{"%W" eq "{path}"}} {{{command}}}')


def settle(widget: tk.Misc, limit: int = 5000) -> None:
    """Geometrie-, Configure- und Zeichenereignisse abarbeiten, bis das Layout steht.

    Zeitgeber (Animationen, Hintergrundabfragen) laufen dabei bewusst nicht mit.
    Gedacht für verdeckte Zustände: unsichtbarer Aufbau, verdeckt vorbereitete Seiten.
    """
    flags = _tkinter.WINDOW_EVENTS | _tkinter.IDLE_EVENTS | _tkinter.DONT_WAIT
    for _ in range(limit):
        if not widget.tk.dooneevent(flags):
            return


OFFSCREEN = -32000  # Position außerhalb aller Monitore (wie Windows für minimierte Fenster)


def reveal(toplevel: tk.Misc, show: Callable[[], None] | None = None, position: tuple[int, int] | None = None, prepare: bool = True) -> None:
    """Ein verborgen aufgebautes Fenster fertig gezeichnet in einem Zug zeigen.

    Solange ein Toplevel zurückgezogen ist, bildet Tk seine Kinder nicht ab und
    liefert ihre ``<Configure>``-Ereignisse erst beim Abbilden aus. Das Fenster
    muss also angezeigt werden, damit die Oberfläche fertig entsteht – nur
    darf das niemand sehen:

    * Windows: DWM-Cloaking. Das Fenster ist angezeigt und zeichnet sich,
      DWM stellt es aber erst nach dem letzten Zeichenschritt dar.
    * sonst (Wine, Linux): zuerst außerhalb des Bildschirms anzeigen und
      fertig aufbauen, dann an die Zielposition ``position`` verschieben.
    """
    show = show or toplevel.deiconify
    if prepare:
        settle(toplevel)  # Geometrie berechnen, Rahmenfenster anlegen (noch verborgen)
    hwnd = windows.frame_hwnd(toplevel)
    if windows.can_cloak() and windows.set_cloak(hwnd, True):
        try:
            show()
            settle(toplevel)
        finally:
            windows.set_cloak(hwnd, False)
        return
    if position is None:
        show()
        settle(toplevel)
        return
    toplevel.geometry(f"+{OFFSCREEN}+{OFFSCREEN}")
    toplevel.deiconify()
    settle(toplevel)
    toplevel.geometry(f"+{position[0]}+{position[1]}")
    if show != toplevel.deiconify:
        show()
    settle(toplevel)
