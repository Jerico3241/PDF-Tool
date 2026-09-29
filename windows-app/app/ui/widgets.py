"""Fluent-Steuerelemente für Tk.

Alle selbst gezeichneten Steuerelemente beziehen Farben aus dem aktiven
Design, zeichnen sich bei einem Designwechsel neu und nutzen den zentralen
Animator (abschaltbar über die Einstellung »Animationen«).
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable, Iterable

from . import animations as motion
from . import icons
from .context import ctx, surface_color, surface_of
from .theme import mix, px

FOCUS_PAD = 3  # Abstand für den Fokusrahmen außerhalb des Steuerelements (WinUI: FocusVisualMargin)
WRAP_STEP = 32  # Mindeständerung (effektive Pixel), ab der Text während eines Resize neu umbricht
CONTROL_RADIUS = 4  # ControlCornerRadius
OVERLAY_RADIUS = 8  # OverlayCornerRadius (Karten, Dialoge, Aufklappmenüs)


def _lerp_color(a: str, b: str, t: float) -> str:
    if a == b or t >= 1:
        return b
    if t <= 0:
        return a
    return mix(a, b, t)


def _quantize(t: float, steps: int = 6) -> float:
    return round(t * steps) / steps


# ---------------------------------------------------------------------------
# Einfache Bausteine: Flächen und Beschriftungen
# ---------------------------------------------------------------------------


class Surface(tk.Frame):
    """Frame, der eine Palettenfläche darstellt (z. B. »card« oder »layer«)."""

    def __init__(self, master, role: str | None = None, **kwargs) -> None:
        role = role or surface_of(master)
        super().__init__(master, bd=0, highlightthickness=0, **kwargs)
        self.surface_role = role
        ctx().theme.style(self, bg=role)


def frame(master, **kwargs) -> tk.Frame:
    """Transparenter Container: übernimmt die Fläche des übergeordneten Widgets."""
    widget = tk.Frame(master, bd=0, highlightthickness=0, **kwargs)
    role = surface_of(master)
    widget.surface_role = role  # type: ignore[attr-defined]
    ctx().theme.style(widget, bg=role)
    return widget


TEXT_STYLES = {
    "caption": "caption",
    "caption_strong": "caption_strong",
    "body": "body",
    "body_strong": "body_strong",
    "body_large": "body_large",
    "subtitle": "subtitle",
    "title": "title",
}


class Text(tk.Label):
    """Beschriftung mit Typografie-Stil und Farbrolle.

    ``wrap=True`` bricht Text automatisch an der verfügbaren Breite um.
    """

    def __init__(self, master, text: str = "", style: str = "body", color: str = "text", wrap: bool = False, anchor: str = "w", justify: str = "left", wrap_width: int = 400, **kwargs) -> None:
        c = ctx()
        font = getattr(c.fonts, TEXT_STYLES.get(style, "body"))
        super().__init__(master, text=text, font=font, anchor=anchor, justify=justify, bd=0, padx=0, pady=0, highlightthickness=0, **kwargs)
        self._color = color
        c.theme.style(self, bg=surface_of(master), fg=color)
        self._wrap = wrap
        if wrap:
            self.configure(wraplength=px(wrap_width))
            self.bind("<Configure>", self._rewrap, add="+")

    def _rewrap(self, event) -> None:
        width = max(40, event.width)
        current = int(self.cget("wraplength") or 0)
        if abs(current - width) <= 2:
            return
        c = ctx()
        if width > current and c.anim.is_resizing and width - current < px(WRAP_STEP):
            # Breiter geworden: während des Ziehens nur in groben Schritten neu umbrechen,
            # genau erst am Ende. Schmaler wird sofort umbrochen, sonst würde Text abgeschnitten.
            c.after_resize(f"wrap:{self}", self._rewrap_now)
            return
        self.configure(wraplength=width)

    def _rewrap_now(self) -> None:
        try:
            width = self.winfo_width()
        except tk.TclError:
            return
        if width > 1 and abs(int(self.cget("wraplength") or 0) - max(40, width)) > 2:
            self.configure(wraplength=max(40, width))

    def set_color(self, role: str) -> None:
        self._color = role
        ctx().theme.style(self, bg=surface_of(self.master), fg=role)


class Icon(tk.Label):
    """Einzelnes Fluent-Symbol. Ohne Symbolschrift bleibt die Fläche leer."""

    def __init__(self, master, glyph: str, color: str = "text", size: str = "icon", **kwargs) -> None:
        c = ctx()
        font = getattr(c.fonts, size) or c.fonts.body
        super().__init__(master, text=glyph if c.icons_available else "", font=font, bd=0, padx=0, pady=0, **kwargs)
        c.theme.style(self, bg=surface_of(master), fg=color)


class Divider(tk.Frame):
    def __init__(self, master, vertical: bool = False) -> None:
        super().__init__(master, bd=0, highlightthickness=0, width=1 if vertical else 0, height=0 if vertical else 1)
        ctx().theme.style(self, bg="divider")


# ---------------------------------------------------------------------------
# Abgerundete Rahmen (Karten, InfoBar, Inhaltsebene)
# ---------------------------------------------------------------------------


class RoundedFrame(tk.Frame):
    """Frame mit kantengeglätteten runden Ecken und 1-px-Rahmen.

    Die Ecken sind kleine Canvas-Flächen, die über den eckigen Rahmen gelegt
    werden. Innenabstände müssen mindestens dem Radius entsprechen.
    """

    def __init__(self, master, fill: str = "card", stroke: str | None = "card_stroke", radius: int = OVERLAY_RADIUS, corners: str = "nw ne sw se", **kwargs) -> None:
        super().__init__(master, bd=0, **kwargs)
        self.surface_role = fill
        self._fill_role = fill
        self._stroke_role = stroke
        self._radius = max(1, px(radius))
        self._corner_names = corners.split()
        self._corners: dict[str, tk.Canvas] = {}
        self._corner_imgs: dict[str, tk.PhotoImage] = {}
        for name in self._corner_names:
            canvas = tk.Canvas(self, width=self._radius, height=self._radius, highlightthickness=0, bd=0)
            item = canvas.create_image(0, 0, anchor="nw")
            canvas._item = item  # type: ignore[attr-defined]
            self._corners[name] = canvas
        ctx().theme.subscribe(self.refresh, owner=self)
        self.refresh()

    def set_fill(self, fill: str, stroke: str | None = None) -> None:
        self._fill_role = fill
        self.surface_role = fill
        if stroke is not None:
            self._stroke_role = stroke
        self.refresh()

    def refresh(self) -> None:
        c = ctx()
        pal = c.pal
        fill = getattr(pal, self._fill_role) if not self._fill_role.startswith("#") else self._fill_role
        stroke = None
        if self._stroke_role:
            stroke = getattr(pal, self._stroke_role) if not self._stroke_role.startswith("#") else self._stroke_role
        outside = surface_color(self.master)
        if stroke:
            self.configure(bg=fill, highlightthickness=1, highlightbackground=stroke, highlightcolor=stroke)
        else:
            self.configure(bg=fill, highlightthickness=0)
        border = 1 if stroke else 0
        for name, canvas in self._corners.items():
            # Die Ecke überdeckt auch den 1-px-Rahmen: Platzierung außerhalb des Innenbereichs.
            relx = 1.0 if "e" in name else 0.0
            rely = 1.0 if "s" in name else 0.0
            anchor = ("s" if "s" in name else "n") + ("e" if "e" in name else "w")
            canvas.place(relx=relx, rely=rely, anchor=anchor, x=border if "e" in name else -border, y=border if "s" in name else -border)
            img = c.images.corner(self._radius, name, outside, fill, stroke)
            self._corner_imgs[name] = img
            canvas.configure(bg=outside)
            canvas.itemconfigure(canvas._item, image=img)  # type: ignore[attr-defined]
            tk.Misc.lift(canvas)

    def lift_corners(self) -> None:
        for canvas in self._corners.values():
            tk.Misc.lift(canvas)


class Card(RoundedFrame):
    """Karte mit optionalem Kopf (Symbol, Titel, Beschreibung, Aktion rechts)."""

    def __init__(self, master, title: str | None = None, icon: str | None = None, description: str | None = None, padding: int = 16, **kwargs) -> None:
        super().__init__(master, fill="card", stroke="card_stroke", **kwargs)
        pad = px(padding)
        self.header = None
        self.header_right = None
        if title:
            self.header = frame(self)
            self.header.pack(fill="x", padx=pad, pady=(pad, 0))
            if icon and ctx().icons_available:
                Icon(self.header, icon, color="text").pack(side="left", padx=(0, px(12)))
            titles = frame(self.header)
            titles.pack(side="left", fill="x", expand=True)
            Text(titles, title, style="body_strong").pack(anchor="w")
            if description:
                Text(titles, description, style="caption", color="text2", wrap=True).pack(anchor="w", fill="x", pady=(px(2), 0))
            self.header_right = frame(self.header)
            self.header_right.pack(side="right")
        self.body = frame(self)
        self.body.pack(fill="both", expand=True, padx=pad, pady=(px(12) if title else pad, pad))
        self.lift_corners()


# ---------------------------------------------------------------------------
# Basis für Canvas-Steuerelemente
# ---------------------------------------------------------------------------


class StretchBox:
    """Abgerundete Fläche auf einem Canvas als 3-Slice (zwei Eckbilder, Mittelstreifen).

    Ändert sich nur die Breite, werden vorhandene Canvas-Elemente per ``coords``
    verschoben – es wird kein Bild neu gerendert und nichts gelöscht.
    """

    def __init__(self, canvas: tk.Canvas, bands: int = 4) -> None:
        self.canvas = canvas
        self._left = canvas.create_image(0, 0, anchor="nw", state="hidden")
        self._right = canvas.create_image(0, 0, anchor="nw", state="hidden")
        self._bands: list[int] = [canvas.create_rectangle(0, 0, 0, 0, outline="", width=0, state="hidden") for _ in range(bands)]
        self._slices: tuple | None = None
        self._geometry: tuple | None = None
        self._shown = False

    def show(self, slices: tuple, x: float, y: float, width: int) -> None:
        canvas = self.canvas
        left, right, runs, cap = slices
        if slices is not self._slices:
            self._slices = slices
            canvas.itemconfigure(self._left, image=left)
            canvas.itemconfigure(self._right, image=right)
            for index, (_y0, _y1, color) in enumerate(runs):
                if index >= len(self._bands):
                    band = canvas.create_rectangle(0, 0, 0, 0, outline="", width=0)
                    canvas.tag_raise(band, self._left)  # direkt über dem eigenen Eckbild, unter Text
                    self._bands.append(band)
                canvas.itemconfigure(self._bands[index], fill=color)
            self._geometry = None
        geometry = (x, y, width)
        if geometry == self._geometry and self._shown:
            return
        self._geometry = geometry
        self._shown = True
        canvas.coords(self._left, x, y)
        canvas.coords(self._right, x + max(cap, width - cap), y)
        canvas.itemconfigure(self._left, state="normal")
        canvas.itemconfigure(self._right, state="normal")
        middle = width - 2 * cap
        for index, band in enumerate(self._bands):
            if index < len(runs) and middle > 0:
                y0, y1, _color = runs[index]
                canvas.coords(band, x + cap, y + y0, x + width - cap, y + y1)
                canvas.itemconfigure(band, state="normal")
            else:
                canvas.itemconfigure(band, state="hidden")

    def hide(self) -> None:
        if not self._shown:
            return
        self._shown = False
        for item in (self._left, self._right, *self._bands):
            self.canvas.itemconfigure(item, state="hidden")


class CanvasControl(tk.Canvas):
    """Basis für selbst gezeichnete Steuerelemente.

    Neu gezeichnet wird nur bei echten Änderungen (Größe, Zustand, Design) –
    reine Verschiebungen durch das Layout lösen kein Neuzeichnen aus.
    """

    def __init__(self, master, width: int, height: int, focusable: bool = True, cursor: str = "") -> None:
        super().__init__(master, width=width, height=height, highlightthickness=0, bd=0, takefocus=1 if focusable else 0, cursor=cursor)
        self.c = ctx()
        self._images: dict[str, tk.PhotoImage] = {}
        self._hover = False
        self._pressed = False
        self._focused = False
        self._enabled = True
        self._tooltip: Tooltip | None = None
        self._last_size = (int(width), int(height))
        self.configure(bg=self.surface())
        self.c.theme.subscribe(self._theme_changed, owner=self)
        self.c.on_focus_mode(self, self.redraw)
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")
        self.bind("<FocusIn>", self._on_focus_in, add="+")
        self.bind("<FocusOut>", self._on_focus_out, add="+")
        self.bind("<Configure>", self._on_configure, add="+")

    def _on_configure(self, event) -> None:
        size = (event.width, event.height)
        if size == self._last_size:
            return
        self._last_size = size
        self.size_changed()

    def size_changed(self) -> None:
        self.redraw(animate=False)

    # Hilfen ------------------------------------------------------------------
    @property
    def pal(self):
        return self.c.pal

    def surface(self) -> str:
        return surface_color(self.master)

    def show_focus(self) -> bool:
        return self._focused and self.c.keyboard_mode and self._enabled

    def _theme_changed(self) -> None:
        # Designwechsel ohne Überblendung: alle Flächen wechseln gleichzeitig.
        self.configure(bg=self.surface())
        self.redraw(animate=False)

    def set_tooltip(self, text: str | None) -> None:
        if text:
            if self._tooltip is None:
                self._tooltip = Tooltip(self, text)
            else:
                self._tooltip.text = text
        elif self._tooltip is not None:
            self._tooltip.text = ""

    # Ereignisse ------------------------------------------------------------------
    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self.state_changed()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self.state_changed()

    def _on_press(self, _event=None) -> None:
        if not self._enabled:
            return
        self._pressed = True
        if int(self.cget("takefocus") or 0):
            self.focus_set()
        self.state_changed()

    def _on_release(self, event=None) -> None:
        was = self._pressed
        self._pressed = False
        inside = True
        if event is not None:
            inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
            self._hover = inside
        self.state_changed()
        if was and inside and self._enabled:
            self.activate()

    def _on_focus_in(self, _event=None) -> None:
        self._focused = True
        self.redraw()

    def _on_focus_out(self, _event=None) -> None:
        self._focused = False
        self._pressed = False
        self.redraw()

    # Überschreiben ----------------------------------------------------------------
    def state_changed(self) -> None:
        self.redraw()

    def activate(self) -> None:
        pass

    def redraw(self, animate: bool = True) -> None:  # noqa: ARG002
        pass

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.configure(takefocus=1 if enabled else 0, cursor="" if enabled else "")
        if not enabled:
            self._pressed = False
        self.state_changed()

    def enabled(self) -> bool:
        return self._enabled

    def _image(self, slot: str, img: tk.PhotoImage) -> tk.PhotoImage:
        self._images[slot] = img
        return img


# ---------------------------------------------------------------------------
# Fortschrittsring
# ---------------------------------------------------------------------------

RING_FRAMES = 60
RING_PERIOD_MS = 1600


def _ring_geometry(t: float) -> tuple[float, float]:
    """Unbestimmter Fortschrittsring: rotierender Bogen, der wächst und schrumpft."""
    grow = 270.0
    base = 180.0 * t
    k = math.floor(t * 2)
    phase = t * 2 - k
    ease = motion.EASE_IN_OUT
    if phase < 0.5:
        start = base + grow * k
        extent = 10 + grow * ease(phase * 2)
    else:
        shrink = ease((phase - 0.5) * 2)
        start = base + grow * k + grow * shrink
        extent = 10 + grow - grow * shrink
    return start % 360, extent


def ring_frames(diameter: int, color: str, background: str) -> list[tk.PhotoImage]:
    c = ctx()
    thickness = max(1.5, diameter / 9.5)
    frames = []
    for index in range(RING_FRAMES):
        start, extent = _ring_geometry(index / RING_FRAMES)
        frames.append(c.images.arc(diameter, thickness, start, extent, color, background))
    return frames


class RingSpinner:
    """Zeichnet einen animierten Ring als Bild auf einen vorhandenen Canvas."""

    def __init__(self, canvas: tk.Canvas, diameter: int) -> None:
        self.canvas = canvas
        self.diameter = diameter
        self.item = None
        self.frames: list[tk.PhotoImage] = []
        self._key = (None, None)
        self._index = 0
        self._job = None
        self.running = False
        # Mit dem Canvas endet auch der Zeitgeber (sonst ruft er einen gelöschten Befehl auf).
        canvas.bind("<Destroy>", lambda event: self.stop() if event.widget is canvas else None, add="+")

    def place(self, x: float, y: float, color: str, background: str) -> None:
        if (color, background) != self._key:
            self.frames = ring_frames(self.diameter, color, background)
            self._key = (color, background)
        if self.item is None:
            self.item = self.canvas.create_image(x, y, anchor="center", image=self.frames[self._index % RING_FRAMES])
        else:
            self.canvas.coords(self.item, x, y)
            self.canvas.itemconfigure(self.item, image=self.frames[self._index % RING_FRAMES])

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._schedule()

    def _schedule(self) -> None:
        interval = RING_PERIOD_MS // RING_FRAMES
        try:
            self._job = self.canvas.after(interval, self._step)
        except tk.TclError:
            self.running = False

    def _step(self) -> None:
        self._job = None
        if not self.running:
            return
        try:
            if not self.canvas.winfo_exists():
                self.running = False
                return
            if self.canvas.winfo_ismapped() and self.item is not None and self.frames:
                self._index = (self._index + 1) % RING_FRAMES
                self.canvas.itemconfigure(self.item, image=self.frames[self._index])
        except tk.TclError:
            self.running = False
            return
        self._schedule()

    def stop(self) -> None:
        self.running = False
        if self._job:
            try:
                self.canvas.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        if self.item is not None:
            try:
                self.canvas.delete(self.item)
            except tk.TclError:
                pass
            self.item = None


class ProgressRing(CanvasControl):
    """Eigenständiger Fortschrittsring (unbestimmt) in Akzentfarbe."""

    def __init__(self, master, size: int = 16, active: bool = False) -> None:
        self._size = px(size)
        super().__init__(master, self._size, self._size, focusable=False)
        self.spinner = RingSpinner(self, self._size)
        self._active = False
        if active:
            self.start()

    def start(self) -> None:
        self._active = True
        self.redraw()
        self.spinner.start()

    def stop(self) -> None:
        self._active = False
        self.spinner.stop()

    def redraw(self, animate: bool = True) -> None:
        if not self._active:
            return
        self.spinner.place(self._size / 2, self._size / 2, self.pal.accent, self.surface())


class ProgressBar(CanvasControl):
    """WinUI-ProgressBar (bestimmt): feine Spur und Akzentbalken mit runden Enden.

    ``set(value)`` mit 0…1. Die Breite folgt dem Layout (``pack(fill="x")``); gezeichnet wird
    nur bei einer Änderung von Wert, Größe oder Design.
    """

    HEIGHT = 12

    def __init__(self, master, width: int = 240) -> None:
        super().__init__(master, px(width), px(self.HEIGHT), focusable=False)
        self._value = 0.0
        self._error = False
        self._track = self.create_image(0, 0, anchor="w")
        self._bar = self.create_image(0, 0, anchor="w", state="hidden")
        self._drawn: tuple | None = None
        self.redraw()

    def set(self, value: float, error: bool = False) -> None:
        value = max(0.0, min(1.0, float(value)))
        if (value, error) != (self._value, self._error):
            self._value, self._error = value, error
            self.redraw()

    def value(self) -> float:
        return self._value

    def redraw(self, animate: bool = True) -> None:
        try:
            width = max(self.winfo_width(), 1) if self.winfo_ismapped() else int(self.cget("width"))
            height = int(self.cget("height"))
        except tk.TclError:
            return
        pal = self.pal
        surface = self.surface()
        color = pal.critical if self._error else pal.accent
        state = (width, height, self._value, color, pal.strong_stroke, surface)
        if state == self._drawn:
            return
        self._drawn = state
        c = self.c
        cy = height / 2
        track = c.images.box(max(2, width), px(1), 0, pal.strong_stroke, background=surface)
        self._image("track", track)
        self.itemconfigure(self._track, image=track)
        self.coords(self._track, 0, cy)
        bar_w = int(round(width * self._value))
        if bar_w >= px(3):
            bar = c.images.box(bar_w, px(3), px(1.5), color, background=surface)
            self._image("bar", bar)
            self.itemconfigure(self._bar, image=bar, state="normal")
            self.coords(self._bar, 0, cy)
        else:
            self.itemconfigure(self._bar, state="hidden")


class CheckBox(CanvasControl):
    """Windows-11-Kontrollkästchen mit Beschriftung; ``state`` True, False oder None (gemischt).

    Ein Klick ruft nur ``command`` auf – den neuen Zustand setzt der Besitzer (``set_state``),
    z. B. »Alle auswählen« über einer Liste.
    """

    SIZE = 20

    def __init__(self, master, text: str, command: Callable[[], None] | None = None, state: bool | None = False) -> None:
        c = ctx()
        self._text = text
        self._command = command
        self._state: bool | None = state
        self._fp = px(FOCUS_PAD)
        self._d = px(self.SIZE)
        width = self._d + 2 * self._fp + (px(8) + c.fonts.body.measure(text) if text else 0) + self._fp
        height = max(px(32), self._d + 2 * self._fp)
        super().__init__(master, width, height)
        self._box = self.create_image(0, 0, anchor="center")
        self._glyph = self.create_text(0, 0, text="", anchor="center")
        self._ring = self.create_image(0, 0, anchor="nw", state="hidden")
        self._label = self.create_text(0, 0, text=text, anchor="w", font=c.fonts.body)
        self.bind("<KeyPress-space>", lambda _e: (self.activate(), "break")[1], add="+")
        self.redraw()

    def activate(self) -> None:
        if self._enabled and self._command:
            self._command()

    def set_state(self, state: bool | None) -> None:
        if state != self._state:
            self._state = state
            self.redraw()

    def state(self) -> bool | None:
        return self._state

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            width = self._d + 2 * self._fp + (px(8) + self.c.fonts.body.measure(text) if text else 0) + self._fp
            self.configure(width=width)
            self.itemconfigure(self._label, text=text)
            self.redraw()

    def redraw(self, animate: bool = True) -> None:
        c = self.c
        pal = self.pal
        surface = self.surface()
        try:
            height = int(self.cget("height"))
        except tk.TclError:
            return
        fp, d = self._fp, self._d
        cx, cy = fp + d / 2, height / 2
        on = self._state is not False
        if not self._enabled:
            fill, stroke = (pal.accent_disabled, None) if on else (surface, pal.text_disabled)
        elif on:
            fill = pal.accent_pressed if self._pressed else pal.accent_hover if self._hover else pal.accent
            stroke = None
        else:
            fill = pal.subtle_pressed(surface) if self._pressed else pal.subtle_hover(surface) if self._hover else pal.control
            stroke = pal.strong_stroke
        box = c.images.box(d, d, px(CONTROL_RADIUS), fill, stroke, background=surface)
        self._image("box", box)
        self.itemconfigure(self._box, image=box)
        self.coords(self._box, cx, cy)
        if on:
            if self._state is None:
                glyph, font = "–", (c.fonts.families.get("text_semibold") or c.fonts.families["text"], -px(12), "bold")
            else:
                glyph = icons.CHECK_MARK if c.icons_available else "✓"
                font = (c.fonts.families["icons"], -px(12)) if c.icons_available else c.fonts.caption
            self.itemconfigure(self._glyph, text=glyph, fill=pal.on_accent if self._enabled else pal.on_accent_disabled, font=font)
            self.coords(self._glyph, cx, cy)
        else:
            self.itemconfigure(self._glyph, text="")
        if self.show_focus():
            width = int(self.cget("width"))
            ring = c.images.ring(width, height, px(CONTROL_RADIUS) + fp, pal.focus_outer, pal.focus_inner)
            self._image("ring", ring)
            self.itemconfigure(self._ring, image=ring, state="normal")
            self.coords(self._ring, 0, 0)
        else:
            self.itemconfigure(self._ring, state="hidden")
        self.itemconfigure(self._label, fill=pal.text if self._enabled else pal.text_disabled)
        self.coords(self._label, fp + d + px(8), cy)


# ---------------------------------------------------------------------------
# Schaltflächen
# ---------------------------------------------------------------------------


class Button(CanvasControl):
    """Windows-11-Schaltfläche.

    ``kind``: "standard", "accent", "subtle" oder "danger". Zustände: Rest,
    Hover, Pressed, Fokus (nur bei Tastaturbedienung), Deaktiviert und Busy.
    Farbwechsel werden kurz überblendet (83 ms Hover, 150 ms Loslassen).
    """

    def __init__(
        self,
        master,
        text: str = "",
        command: Callable[[], None] | None = None,
        icon: str | None = None,
        kind: str = "standard",
        tooltip: str | None = None,
        height: int = 32,
        min_width: int = 0,
        font: str = "body",
        icon_only: bool = False,
        padding: int = 12,
    ) -> None:
        self._text = text
        self._icon = icon if (icon and ctx().icons_available) else None
        self._kind = kind
        self._command = command
        self._font = getattr(ctx().fonts, font)
        self._icon_only = icon_only or (not text and bool(self._icon))
        self._h = px(height)
        self._fp = px(FOCUS_PAD)
        self._min_w = px(min_width)
        self._pad = px(padding)
        self._busy = False
        self._busy_text = ""
        self._fill_x = False
        self._current: dict[str, str] | None = None
        width = self._natural_width()
        super().__init__(master, width, self._h + 2 * self._fp, cursor="")
        self._bg = StretchBox(self)
        self._ring = StretchBox(self)
        self._icon_item = self.create_text(0, 0, text="", anchor="center")
        self._text_item = self.create_text(0, 0, text="", anchor="center")
        self._spinner = RingSpinner(self, px(16))
        self.bind("<KeyPress-space>", self._key_press, add="+")
        self.bind("<KeyRelease-space>", self._key_release, add="+")
        self.bind("<KeyPress-Return>", self._key_invoke, add="+")
        self.bind("<KeyPress-KP_Enter>", self._key_invoke, add="+")
        if tooltip:
            self.set_tooltip(tooltip)
        self.redraw(animate=False)

    # Größe --------------------------------------------------------------------
    def _natural_width(self) -> int:
        fp = self._fp
        if self._icon_only:
            return self._h + 2 * fp
        text = self._busy_text if self._busy else self._text
        width = self._font.measure(text) + 2 * self._pad
        if self._icon or self._busy:
            width += px(16) + px(8)
        return max(self._min_w, width) + 2 * fp

    def _resize(self) -> None:
        width = self._natural_width()
        if not self._fill_x or self.winfo_width() < width:
            super().configure(width=width)

    def pack(self, *args, **kwargs):  # type: ignore[override]
        self._fill_x = kwargs.get("fill") in ("x", "both")
        return super().pack(*args, **kwargs)

    def grid(self, *args, **kwargs):  # type: ignore[override]
        sticky = str(kwargs.get("sticky", ""))
        self._fill_x = "e" in sticky and "w" in sticky
        return super().grid(*args, **kwargs)

    # Öffentliche API --------------------------------------------------------------
    def set_text(self, text: str) -> None:
        self._text = text
        self._resize()
        self.redraw(animate=False)

    def text(self) -> str:
        return self._text

    def set_kind(self, kind: str) -> None:
        if kind != self._kind:
            self._kind = kind
            self.redraw()

    def set_command(self, command: Callable[[], None] | None) -> None:
        self._command = command

    def set_busy(self, busy: bool, text: str | None = None) -> None:
        self._busy = bool(busy)
        self._busy_text = text or self._text
        self._resize()
        if busy:
            self._pressed = False
            self._spinner.start()
        else:
            self._spinner.stop()
        self.configure(takefocus=0 if busy else (1 if self._enabled else 0))
        self.redraw(animate=False)

    def busy(self) -> bool:
        return self._busy

    def invoke(self) -> None:
        if self._enabled and not self._busy and self._command:
            self._command()

    def activate(self) -> None:
        self.invoke()

    # Tastatur -------------------------------------------------------------------------
    def _key_press(self, _event=None):
        if self._enabled and not self._busy:
            self._pressed = True
            self.state_changed()
        return "break"

    def _key_release(self, _event=None):
        if self._pressed:
            self._pressed = False
            self.state_changed()
            self.invoke()
        return "break"

    def _key_invoke(self, _event=None):
        if not self._enabled or self._busy:
            return "break"
        self._pressed = True
        self.state_changed()

        def release() -> None:
            self._pressed = False
            try:
                self.state_changed()
            except tk.TclError:
                return
            self.invoke()

        self.after(90, release)
        return "break"

    def _on_press(self, event=None) -> None:
        if self._busy:
            return
        super()._on_press(event)

    # Zeichnen --------------------------------------------------------------------------
    def _target(self) -> dict[str, str]:
        pal = self.pal
        surface = self.surface()
        kind = self._kind
        disabled = not self._enabled or self._busy
        state = "disabled" if disabled else "pressed" if self._pressed else "hover" if self._hover else "rest"
        edge_side = "bottom" if not pal.dark else "top"
        if kind in ("accent", "danger"):
            if kind == "accent":
                fills = {"rest": pal.accent, "hover": pal.accent_hover, "pressed": pal.accent_pressed, "disabled": pal.accent_disabled}
                fg = {"rest": pal.on_accent, "hover": pal.on_accent, "pressed": pal.on_accent_pressed, "disabled": pal.on_accent_disabled}
                base = pal.accent
            else:
                fills = {"rest": pal.critical, "hover": pal.critical_hover, "pressed": pal.critical_pressed, "disabled": pal.accent_disabled}
                fg = {"rest": pal.on_status, "hover": pal.on_status, "pressed": mix(pal.on_status, pal.critical, 0.3), "disabled": pal.on_accent_disabled}
                base = pal.critical
            if state == "disabled":
                stroke, edge = fills["disabled"], fills["disabled"]
            else:
                stroke = mix(fills[state], "#FFFFFF", 0.08)
                edge = mix(base, "#000000", 0.32 if not pal.dark else 0.14) if state != "pressed" else stroke
            return {"fill": fills[state], "stroke": stroke, "edge": edge, "fg": fg[state], "edge_side": "bottom"}
        if kind == "subtle":
            fills = {"rest": surface, "hover": pal.subtle_hover(surface), "pressed": pal.subtle_pressed(surface), "disabled": surface}
            fg = {"rest": pal.text, "hover": pal.text, "pressed": pal.text2, "disabled": pal.text_disabled}
            return {"fill": fills[state], "stroke": fills[state], "edge": fills[state], "fg": fg[state], "edge_side": edge_side}
        fills = {"rest": pal.control, "hover": pal.control_hover, "pressed": pal.control_pressed, "disabled": pal.control_disabled}
        fg = {"rest": pal.text, "hover": pal.text, "pressed": pal.text2, "disabled": pal.text_disabled}
        edge = pal.control_edge if state in ("rest", "hover") else pal.control_stroke
        return {"fill": fills[state], "stroke": pal.control_stroke, "edge": edge, "fg": fg[state], "edge_side": edge_side}

    def state_changed(self) -> None:
        self.redraw(animate=True)

    def redraw(self, animate: bool = True) -> None:
        try:
            width = max(self.winfo_width(), int(self.cget("width")))
        except tk.TclError:
            return
        target = self._target()
        start = self._current
        key = f"btn:{self}"
        if not animate or start is None or start == target:
            self.c.anim.cancel(key)
            self._paint(target, width)
            return
        duration = motion.FAST if (self._hover or self._pressed) else 150

        def step(t: float) -> None:
            q = 1.0 if t >= 1 else _quantize(t)
            mixed = {name: _lerp_color(start[name], target[name], q) if name != "edge_side" else target[name] for name in target}
            self._paint(mixed, max(self.winfo_width(), int(self.cget("width"))))

        self.c.anim.run(key, duration, step, easing=motion.linear, widget=self)

    def _paint(self, colors: dict[str, str], width: int) -> None:
        self._current = dict(colors)
        c = self.c
        pal = self.pal
        fp = self._fp
        height = self._h
        visual_w = max(4, width - 2 * fp)
        surface = self.surface()
        radius = px(CONTROL_RADIUS)
        if self._kind == "subtle" and colors["fill"] == surface:
            self._bg.hide()
        else:
            slices = c.images.box_slices(height, radius, colors["fill"], colors["stroke"], colors["edge"], colors["edge_side"], background=surface)
            self._bg.show(slices, fp, fp, visual_w)
        if self.show_focus():
            self._ring.show(c.images.ring_slices(height + 2 * fp, radius + fp, pal.focus_outer, pal.focus_inner), 0, 0, width)
        else:
            self._ring.hide()
        cy = fp + height / 2
        label = self._busy_text if self._busy else self._text
        fg = colors["fg"]
        has_lead = bool(self._icon) or self._busy
        if self._icon_only:
            self.itemconfigure(self._text_item, text="")
            self.itemconfigure(self._icon_item, text=self._icon or "", fill=fg, font=c.fonts.icon)
            self.coords(self._icon_item, width / 2, cy)
            return
        text_w = self._font.measure(label)
        lead_w = (px(16) + px(8)) if has_lead else 0
        total = lead_w + text_w
        x0 = width / 2 - total / 2
        if self._busy:
            self.itemconfigure(self._icon_item, text="")
            self._spinner.place(x0 + px(8), cy, pal.accent if self._kind != "subtle" else pal.accent, colors["fill"])
        else:
            self._spinner.stop() if self._spinner.item is not None else None
            self.itemconfigure(self._icon_item, text=self._icon or "", fill=fg, font=c.fonts.icon)
            self.coords(self._icon_item, x0 + px(8), cy)
        self.itemconfigure(self._text_item, text=label, fill=fg, font=self._font)
        self.coords(self._text_item, x0 + lead_w + text_w / 2, cy)


class IconButton(Button):
    """Quadratische Symbolschaltfläche (subtil) mit Tooltip."""

    def __init__(self, master, icon: str, command=None, tooltip: str | None = None, size: int = 32, kind: str = "subtle") -> None:
        super().__init__(master, "", command, icon=icon, kind=kind, tooltip=tooltip, height=size, icon_only=True)
        if not ctx().icons_available:
            # Ohne Symbolschrift einen kurzen Text anzeigen, damit die Aktion erreichbar bleibt.
            self._icon_only = False
            self._text = (tooltip or "…").split(" ")[0]
            self._resize()
            self.redraw(animate=False)


# ---------------------------------------------------------------------------
# Umschalter (ToggleSwitch)
# ---------------------------------------------------------------------------


class ToggleSwitch(CanvasControl):
    """Windows-11-Umschalter mit gleitendem Knopf und »Ein«/»Aus«-Beschriftung."""

    TRACK_W = 40
    TRACK_H = 20

    def __init__(self, master, variable: tk.BooleanVar, command: Callable[[], None] | None = None, on_text: str = "Ein", off_text: str = "Aus", show_text: bool = True, text_side: str = "left") -> None:
        c = ctx()
        self.var = variable
        self._command = command
        self._on_text, self._off_text = on_text, off_text
        self._show_text = show_text
        self._text_side = text_side
        self._fp = px(FOCUS_PAD)
        self._tw, self._th = px(self.TRACK_W), px(self.TRACK_H)
        self._text_w = max(c.fonts.body.measure(on_text), c.fonts.body.measure(off_text)) if show_text else 0
        self._gap = px(12) if show_text else 0
        width = self._tw + 2 * self._fp + self._text_w + self._gap
        height = max(px(32), self._th + 2 * self._fp)
        self._pos = 1.0 if variable.get() else 0.0
        super().__init__(master, width, height)
        self._track = self.create_image(0, 0, anchor="nw")
        self._ring = self.create_image(0, 0, anchor="nw", state="hidden")
        self._knob = self.create_image(0, 0, anchor="center")
        self._label = self.create_text(0, 0, text="", anchor="w", font=c.fonts.body)
        self.bind("<KeyPress-space>", self._key_toggle, add="+")
        self.bind("<KeyPress-Return>", self._key_toggle, add="+")
        self._trace = variable.trace_add("write", lambda *_a: self._sync_from_var())
        self.bind("<Destroy>", self._untrace, add="+")
        self.redraw()

    def _untrace(self, event) -> None:
        if event.widget is self:
            try:
                self.var.trace_remove("write", self._trace)
            except (tk.TclError, ValueError):
                pass

    def _key_toggle(self, _event=None):
        if self._enabled:
            self.toggle()
        return "break"

    def activate(self) -> None:
        self.toggle()

    def toggle(self) -> None:
        self.var.set(not bool(self.var.get()))
        if self._command:
            self._command()

    def _sync_from_var(self) -> None:
        try:
            target = 1.0 if self.var.get() else 0.0
        except tk.TclError:
            return
        if target == self._pos:
            self.redraw()
            return
        start = self._pos

        def step(t: float) -> None:
            self._pos = start + (target - start) * t
            self.redraw()

        self.c.anim.run(f"toggle:{self}", motion.NORMAL, step, easing=motion.POINT_TO_POINT, widget=self)

    def redraw(self, animate: bool = True) -> None:
        c = self.c
        pal = self.pal
        surface = self.surface()
        fp = self._fp
        try:
            height = int(self.cget("height"))
        except tk.TclError:
            return
        on = self._pos >= 0.5
        track_x = fp + (self._text_w + self._gap if self._text_side == "left" else 0)
        track_y = (height - self._th) / 2
        if not self._enabled:
            fill = pal.accent_disabled if on else surface
            stroke = None if on else pal.text_disabled
            knob_color = pal.on_accent_disabled if on else pal.text_disabled
        elif on:
            fill = pal.accent_pressed if self._pressed else pal.accent_hover if self._hover else pal.accent
            stroke = None
            knob_color = pal.on_accent
        else:
            fill = pal.subtle_pressed(surface) if self._pressed else pal.subtle_hover(surface) if self._hover else surface
            stroke = pal.strong_stroke
            knob_color = pal.strong
        radius = self._th / 2
        img = c.images.box(self._tw, self._th, radius, fill, stroke, background=surface)
        self._image("track", img)
        self.itemconfigure(self._track, image=img)
        self.coords(self._track, track_x, track_y)
        if self.show_focus():
            ring = c.images.ring(self._tw + 2 * fp, self._th + 2 * fp, radius + fp, pal.focus_outer, pal.focus_inner)
            self._image("ring", ring)
            self.itemconfigure(self._ring, image=ring, state="normal")
            self.coords(self._ring, track_x - fp, track_y - fp)
        else:
            self.itemconfigure(self._ring, state="hidden")
        knob_d = px(14) if (self._hover and self._enabled) else px(12)
        travel = self._tw - px(20)
        kx = track_x + px(10) + travel * self._pos
        ky = track_y + self._th / 2
        knob_bg = fill
        knob = c.images.circle(knob_d, knob_color, background=knob_bg)
        self._image("knob", knob)
        self.itemconfigure(self._knob, image=knob)
        self.coords(self._knob, kx, ky)
        if self._show_text:
            label = self._on_text if bool(self.var.get()) else self._off_text
            text_x = fp if self._text_side == "left" else track_x + self._tw + self._gap
            if self._text_side == "left":
                self.itemconfigure(self._label, anchor="e")
                text_x = track_x - self._gap
            self.itemconfigure(self._label, text=label, fill=pal.text if self._enabled else pal.text_disabled)
            self.coords(self._label, text_x, height / 2)


# ---------------------------------------------------------------------------
# Optionsfelder (RadioButton)
# ---------------------------------------------------------------------------


class RadioButton(CanvasControl):
    SIZE = 20

    def __init__(self, master, text: str, value: str, variable: tk.StringVar, command=None, group: "RadioGroup | None" = None) -> None:
        c = ctx()
        self.var = variable
        self.value = value
        self._text = text
        self._command = command
        self.group = group
        self._fp = px(FOCUS_PAD)
        self._d = px(self.SIZE)
        width = self._d + 2 * self._fp + px(8) + c.fonts.body.measure(text) + self._fp
        height = max(px(32), self._d + 2 * self._fp)
        super().__init__(master, width, height)
        self._circle = self.create_image(0, 0, anchor="center")
        self._dot = self.create_image(0, 0, anchor="center")
        self._ring = self.create_image(0, 0, anchor="nw", state="hidden")
        self._label = self.create_text(0, 0, text=text, anchor="w", font=c.fonts.body)
        self._trace = variable.trace_add("write", lambda *_a: self.redraw())
        self.bind("<Destroy>", self._untrace, add="+")
        self.bind("<KeyPress-space>", lambda _e: (self.activate(), "break")[1], add="+")
        for key in ("Up", "Left"):
            self.bind(f"<KeyPress-{key}>", lambda _e: self._move(-1), add="+")
        for key in ("Down", "Right"):
            self.bind(f"<KeyPress-{key}>", lambda _e: self._move(1), add="+")
        self.redraw()

    def _untrace(self, event) -> None:
        if event.widget is self:
            try:
                self.var.trace_remove("write", self._trace)
            except (tk.TclError, ValueError):
                pass

    def _move(self, delta: int):
        if self.group:
            self.group.move(self, delta)
        return "break"

    def activate(self) -> None:
        if self.var.get() != self.value:
            self.var.set(self.value)
            if self._command:
                self._command()

    def selected(self) -> bool:
        return self.var.get() == self.value

    def redraw(self, animate: bool = True) -> None:
        c = self.c
        pal = self.pal
        surface = self.surface()
        try:
            height = int(self.cget("height"))
        except tk.TclError:
            return
        fp, d = self._fp, self._d
        cx, cy = fp + d / 2, height / 2
        selected = self.selected()
        if selected:
            fill = pal.accent_disabled if not self._enabled else pal.accent_pressed if self._pressed else pal.accent_hover if self._hover else pal.accent
            outer = c.images.circle(d, fill, background=surface)
            dot_d = px(10) if self._pressed else px(14) if self._hover else px(12)
            dot = c.images.circle(dot_d, pal.on_accent if self._enabled else pal.on_accent_disabled, background=fill)
            self._image("dot", dot)
            self.itemconfigure(self._dot, image=dot, state="normal")
            self.coords(self._dot, cx, cy)
        else:
            fill = pal.subtle_pressed(surface) if self._pressed else pal.subtle_hover(surface) if self._hover else pal.control
            stroke = pal.text_disabled if not self._enabled else pal.strong_stroke
            outer = c.images.circle(d, fill, stroke, background=surface)
            if self._pressed:
                dot = c.images.circle(px(10), pal.strong, background=fill)
                self._image("dot", dot)
                self.itemconfigure(self._dot, image=dot, state="normal")
                self.coords(self._dot, cx, cy)
            else:
                self.itemconfigure(self._dot, state="hidden")
        self._image("outer", outer)
        self.itemconfigure(self._circle, image=outer)
        self.coords(self._circle, cx, cy)
        if self.show_focus():
            width = int(self.cget("width"))
            ring = c.images.ring(width, height, px(CONTROL_RADIUS) + fp, pal.focus_outer, pal.focus_inner)
            self._image("ring", ring)
            self.itemconfigure(self._ring, image=ring, state="normal")
            self.coords(self._ring, 0, 0)
        else:
            self.itemconfigure(self._ring, state="hidden")
        self.itemconfigure(self._label, fill=pal.text if self._enabled else pal.text_disabled)
        self.coords(self._label, fp + d + px(8), cy)


class RadioGroup:
    """Verbindet Optionsfelder: Pfeiltasten wechseln die Auswahl."""

    def __init__(self, master, variable: tk.StringVar, options: Iterable[tuple[str, str]], command=None, horizontal: bool = True) -> None:
        self.buttons: list[RadioButton] = []
        self.frame = frame(master)
        for value, text in options:
            button = RadioButton(self.frame, text, value, variable, command, group=self)
            if horizontal:
                button.pack(side="left", padx=(0, px(16)))
            else:
                button.pack(anchor="w")
            self.buttons.append(button)

    def move(self, button: RadioButton, delta: int) -> None:
        index = self.buttons.index(button)
        target = self.buttons[(index + delta) % len(self.buttons)]
        target.focus_set()
        target.activate()

    def pack(self, **kwargs):
        return self.frame.pack(**kwargs)

    def grid(self, **kwargs):
        return self.frame.grid(**kwargs)


# ---------------------------------------------------------------------------
# Farbfelder für die Akzentauswahl
# ---------------------------------------------------------------------------


class Swatch(CanvasControl):
    """Rundes Farbfeld. Auswahl: Ring in Textfarbe mit Abstand und Häkchen."""

    SIZE = 32

    def __init__(self, master, color_fn: Callable[[], str], command: Callable[[], None], tooltip: str, selected_fn: Callable[[], bool], glyph: str | None = None) -> None:
        self._color_fn = color_fn
        self._command = command
        self._selected_fn = selected_fn
        self._glyph = glyph if ctx().icons_available else None
        self._d = px(self.SIZE)
        self._size = self._d + 2 * px(FOCUS_PAD) + px(6)
        super().__init__(master, self._size, self._size)
        center = self._size / 2
        self._img = self.create_image(center, center, anchor="center")
        self._mark = self.create_text(center, center, text="", anchor="center")
        self._ring = self.create_image(0, 0, anchor="nw", state="hidden")
        self.bind("<KeyPress-space>", lambda _e: (self.activate(), "break")[1], add="+")
        self.bind("<KeyPress-Return>", lambda _e: (self.activate(), "break")[1], add="+")
        self.set_tooltip(tooltip)
        self.redraw()

    def activate(self) -> None:
        self._command()

    def redraw(self, animate: bool = True) -> None:
        c = self.c
        pal = self.pal
        surface = self.surface()
        color = self._color_fn()
        selected = self._selected_fn()
        hover = self._hover and self._enabled
        if selected:
            ring_color, ring_w, gap = pal.text, px(2), px(2)
        elif hover:
            ring_color, ring_w, gap = pal.strong_stroke, px(1), px(2)
        else:
            ring_color, ring_w, gap = None, 0, 0
        outer = self._d + 2 * (ring_w + gap) if ring_color else self._d
        inner = self._d - (px(2) if self._pressed else 0)
        key = ("swatch", self._size, color, ring_color, ring_w, gap, inner, surface)
        img = c.images.get(key, lambda: _swatch_image(self._size, outer, inner, color, ring_color, ring_w, gap, surface))
        self._image("img", img)
        self.itemconfigure(self._img, image=img)
        on_color = "#FFFFFF" if _contrast_white(color) else "#000000"
        if selected:
            text = icons.CHECK_MARK if c.icons_available else "✓"
            font = c.fonts.icon_small if c.icons_available else c.fonts.caption
        else:
            text = self._glyph or ""
            font = c.fonts.icon_small or c.fonts.caption
        self.itemconfigure(self._mark, text=text, fill=on_color, font=font)
        if self.show_focus():
            ring = c.images.ring(self._size, self._size, self._size / 2, pal.focus_outer, pal.focus_inner)
            self._image("ring", ring)
            self.itemconfigure(self._ring, image=ring, state="normal")
            self.tag_raise(self._ring)
        else:
            self.itemconfigure(self._ring, state="hidden")


def _swatch_image(size: int, outer: int, inner: int, color: str, ring: str | None, ring_w: int, gap: int, surface: str):
    from PIL import Image

    from .render import circle

    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if ring:
        ring_img = circle(outer, ring)
        base.alpha_composite(ring_img, ((size - outer) // 2, (size - outer) // 2))
        hole = outer - 2 * ring_w
        hole_img = circle(hole, surface)
        base.alpha_composite(hole_img, ((size - hole) // 2, (size - hole) // 2))
    dot = circle(inner, color, stroke=mix(color, "#000000", 0.18))
    base.alpha_composite(dot, ((size - inner) // 2, (size - inner) // 2))
    background = Image.new("RGBA", (size, size), surface)
    background.alpha_composite(base)
    return background.convert("RGB")


def _contrast_white(color: str) -> bool:
    from .theme import contrast

    return contrast(color, "#FFFFFF") >= contrast(color, "#000000")


# ---------------------------------------------------------------------------
# InfoBar
# ---------------------------------------------------------------------------

SEVERITY = ("neutral", "info", "success", "warning", "error")


class InfoBar(tk.Frame):
    """WinUI-InfoBar: Symbol, Titel, Meldung, optionale Aktion und Schließen-Knopf.

    Liegt in einem ausklappbaren Container: ``show()`` und ``hide()`` blenden
    die Leiste mit einer Höhenanimation ein bzw. aus.
    """

    def __init__(self, master, closable: bool = True, on_close: Callable[[], None] | None = None) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = surface_of(master)
        ctx().theme.style(self, bg=self.surface_role)
        self.collapsible = Collapsible(self)
        self.collapsible.pack(fill="x")
        self.box = RoundedFrame(self.collapsible.content, fill="info_bg", stroke="card_stroke", radius=CONTROL_RADIUS)
        self.box.pack(fill="x")
        self.severity = "neutral"
        self.title = ""
        self.message = ""
        self._on_close = on_close
        c = ctx()
        pad = px(12)
        inner = tk.Frame(self.box, bd=0, highlightthickness=0)
        inner.pack(fill="x", padx=(px(14), px(6)), pady=px(6))
        inner.surface_role = "info_bg"  # type: ignore[attr-defined]
        self._inner = inner
        self._icon = tk.Canvas(inner, width=px(20), height=px(20), highlightthickness=0, bd=0)
        self._icon.pack(side="left", anchor="n", pady=(px(8), 0))
        self._icon_bg = self._icon.create_image(px(10), px(10), anchor="center")
        self._icon_glyph = self._icon.create_text(px(10), px(10), text="", anchor="center")
        self._icon_img = None
        texts = tk.Frame(inner, bd=0, highlightthickness=0)
        texts.pack(side="left", fill="x", expand=True, padx=(pad, px(8)), pady=(px(7), px(7)))
        self._texts = texts
        self._title = tk.Label(texts, text="", font=c.fonts.body_strong, anchor="w", justify="left", bd=0)
        # width=1: Die Meldung bestimmt nicht die Breite der Leiste – sie bricht nur in der
        # zugewiesenen Breite um. Sonst ändert jeder Umbruch die angeforderte Breite, damit die
        # zugewiesene Breite und wieder den Umbruch: je nach Text und Schriftmetrik endlos.
        self._message = tk.Label(texts, text="", font=c.fonts.body, anchor="w", justify="left", bd=0, width=1)
        self._mode = None
        # Aktionen stehen neben dem Text – bei mehr als zwei Aktionen darunter (wie in WinUI).
        # Das Kind der Box lässt sich in beide Bereiche einordnen (pack -in).
        self._actions = tk.Frame(self.box, bd=0, highlightthickness=0)
        self._actions.pack(in_=inner, side="left", anchor="n", pady=(px(1), 0))
        self._actions.surface_role = "info_bg"  # type: ignore[attr-defined]
        self._actions_below = False
        self._close = None
        if closable:
            self._close = IconButton(inner, icons.CANCEL, self._close_clicked, tooltip="Schließen", size=32)
            self._close.pack(side="right", anchor="n")
        self._texts_width = 0
        texts.bind("<Configure>", self._texts_configured, add="+")
        c.theme.subscribe(self._repaint, owner=self)
        self._repaint()

    def _close_clicked(self) -> None:
        self.hide()
        if self._on_close:
            self._on_close()

    def _texts_configured(self, event) -> None:
        if event.width != self._texts_width:
            self._texts_width = event.width
            self._relayout()

    def _relayout(self, _event=None) -> None:
        width = self._texts.winfo_width()
        if width <= 1:
            return
        gap = px(12)
        has_title = bool(self.title)
        title_w = self._title.winfo_reqwidth() if has_title else 0
        msg_w = ctx().fonts.body.measure(self.message)
        inline = (not has_title) or (title_w + gap + msg_w <= width)
        mode = ("inline" if inline else "stacked", has_title)
        if mode != self._mode:
            self._mode = mode
            # pack_configure ändert nur die Anordnung – die Beschriftungen bleiben abgebildet.
            if has_title:
                title = {"side": "left", "anchor": "n"} if inline else {"side": "top", "anchor": "w"}
                if self._message.winfo_manager():
                    title["before"] = self._message
                self._title.pack_configure(**title)
            elif self._title.winfo_manager():
                self._title.pack_forget()
            if inline:
                self._message.pack_configure(side="left", anchor="n", fill="x", expand=True, padx=(gap if has_title else 0, 0))
            else:
                self._message.pack_configure(side="top", anchor="w", fill="x", expand=False, padx=0)
        wrap = width - (title_w + gap if (inline and has_title) else 0)
        if int(self._message.cget("wraplength") or 0) != max(40, wrap):
            self._message.configure(wraplength=max(40, wrap))

    def _colors(self) -> tuple[str, str, str]:
        pal = ctx().pal
        return {
            "neutral": (pal.info_bg, pal.neutral, pal.on_status),
            "info": (pal.info_bg, pal.accent, pal.on_accent),
            "success": (pal.success_bg, pal.success, pal.on_status),
            "warning": (pal.caution_bg, pal.caution, "#000000"),
            "error": (pal.critical_bg, pal.critical, pal.on_status),
        }[self.severity]

    def _repaint(self) -> None:
        c = ctx()
        pal = c.pal
        bg, icon_color, glyph_color = self._colors()
        self.box.set_fill(bg)
        self._inner.surface_role = None  # type: ignore[attr-defined]
        for widget in (self._inner, self._texts, self._actions, self._icon):
            widget.configure(bg=bg)
        self._title.configure(bg=bg, fg=pal.text)
        self._message.configure(bg=bg, fg=pal.text)
        img = c.images.circle(px(16), icon_color, background=bg)
        self._icon_img = img
        self._icon.itemconfigure(self._icon_bg, image=img)
        glyphs = {
            "neutral": ("i", False),
            "info": ("i", False),
            "success": (icons.CHECK_MARK, True),
            "warning": ("!", False),
            "error": (icons.CANCEL, True),
        }
        glyph, is_icon = glyphs[self.severity]
        if is_icon and c.icons_available:
            font = c.fonts.icon_small
            size = -max(6, px(9))
            font = (c.fonts.families["icons"], size)
        else:
            glyph = {"success": "✓", "error": "×"}.get(self.severity, glyph)
            font = (c.fonts.families.get("text_semibold") or c.fonts.families["text"], -px(11), "bold")
        self._icon.itemconfigure(self._icon_glyph, text=glyph, fill=glyph_color, font=font)
        self._inner.surface_role = bg  # type: ignore[attr-defined]
        if self._close is not None:
            self._close.configure(bg=bg)
            self._close.redraw(animate=False)
        for child in self._actions.winfo_children():
            if isinstance(child, CanvasControl):
                child.configure(bg=bg)
                child.redraw()

    def set(self, severity: str, message: str, title: str = "", actions: Iterable[tuple[str, Callable[[], None]]] = ()) -> None:
        self.severity = severity if severity in SEVERITY else "neutral"
        self.title = title
        self.message = message
        self._title.configure(text=title)
        self._message.configure(text=message)
        self._mode = None
        if not self._message.winfo_manager():
            self._message.pack(side="left", anchor="n", fill="x", expand=True)
        for child in self._actions.winfo_children():
            child.destroy()
        actions = list(actions)
        bg = self._colors()[0]
        self._actions.surface_role = bg  # type: ignore[attr-defined]
        below = len(actions) > 2
        if below != self._actions_below:
            self._actions_below = below
            if below:
                # unter dem Text, bündig mit ihm (Symbol 20 px + Abstand 12 px)
                self._actions.pack_configure(in_=self.box, side="top", anchor="w", padx=(px(14) + px(20) + px(12) - px(4), px(12)), pady=(0, px(10)))
            else:
                self._actions.pack_configure(in_=self._inner, side="left", anchor="n", padx=0, pady=(px(1), 0), before=self._close if self._close is not None else None)
            self.box.lift_corners()
        for index, (text, command) in enumerate(actions):
            pad = (px(4), 0) if not below else ((0 if index == 0 else px(8)), 0)
            Button(self._actions, text, command, kind="standard").pack(side="left", padx=pad, pady=(px(4), 0) if not below else 0)
        self._repaint()
        self.after_idle(self._relayout)

    def show(self, severity: str | None = None, message: str | None = None, title: str = "", actions: Iterable[tuple[str, Callable[[], None]]] = (), animate: bool = True) -> None:
        if message is not None:
            self.set(severity or self.severity, message, title, actions)
        self.collapsible.expand(animate=animate)

    def hide(self, animate: bool = True) -> None:
        self.collapsible.collapse(animate=animate)

    def visible(self) -> bool:
        return self.collapsible.expanded


# ---------------------------------------------------------------------------
# Ein- und ausklappbarer Bereich
# ---------------------------------------------------------------------------


class Collapsible(tk.Frame):
    """Container, dessen Inhalt mit einer Höhenanimation ein- und ausklappt.

    Der Inhalt bleibt dauerhaft abgebildet (per ``place``); verändert wird nur die
    sichtbare Höhe. So wird beim Ein- und Ausklappen nichts ab- und wieder
    eingeblendet – kein Neuaufbau des Inhalts, kein Nachzeichnen.
    """

    def __init__(self, master, expanded: bool = False) -> None:
        super().__init__(master, bd=0, highlightthickness=0, height=1)
        self.surface_role = surface_of(master)
        c = ctx()
        c.theme.style(self, bg=self.surface_role)
        self.content = tk.Frame(self, bd=0, highlightthickness=0)
        self.content.surface_role = self.surface_role  # type: ignore[attr-defined]
        c.theme.style(self.content, bg=self.surface_role)
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.expanded = expanded
        self._key = f"collapse:{self}"
        # Eingeklappt liegt der Inhalt knapp unterhalb der 1-px-Fläche und ist unsichtbar.
        self.content.place(x=0, y=0 if expanded else 1, relwidth=1)
        self.content.bind("<Configure>", self._content_configured, add="+")
        c.block_focus(self.content, not expanded)

    def _natural_height(self) -> int:
        self.content.update_idletasks()
        return max(1, self.content.winfo_reqheight())

    def _content_configured(self, event) -> None:
        # Der Inhalt hat eine neue natürliche Höhe (z. B. längerer Text): Höhe nachführen.
        if self.expanded and not ctx().anim.running(self._key):
            height = max(1, event.height)
            if int(self.cget("height")) != height:
                self.configure(height=height)

    def expand(self, animate: bool = True) -> None:
        c = ctx()
        if self.expanded and not c.anim.running(self._key):
            return
        self.expanded = True
        c.block_focus(self.content, False)
        start = max(1, self.winfo_height()) if self.winfo_ismapped() else 1
        self.content.place_configure(y=0)
        target = self._natural_height()

        def step(t: float) -> None:
            self.configure(height=max(1, int(start + (target - start) * t)))

        def done() -> None:
            self.configure(height=self._natural_height())

        c.anim.run(self._key, motion.NORMAL if animate else 0, step, done, easing=motion.DECELERATE, widget=self)

    def collapse(self, animate: bool = True) -> None:
        c = ctx()
        if not self.expanded and not c.anim.running(self._key):
            return
        self.expanded = False
        c.block_focus(self.content, True)
        start = self.winfo_height() if self.winfo_ismapped() else 1

        def step(t: float) -> None:
            self.configure(height=max(1, int(start * (1 - t))))

        def done() -> None:
            self.configure(height=1)
            self.content.place_configure(y=1)

        c.anim.run(self._key, motion.NORMAL if animate else 0, step, done, easing=motion.ACCELERATE if animate else motion.linear, widget=self)


# ---------------------------------------------------------------------------
# Tooltip
# ---------------------------------------------------------------------------


class Tooltip:
    """Dezenter Tooltip mit Verzögerung, runden Ecken (Windows 11) und Designfarben."""

    DELAY_MS = 600

    def __init__(self, widget: tk.Misc, text: str) -> None:
        self.widget = widget
        self.text = text
        self._window: tk.Toplevel | None = None
        self._job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        if self.text:
            try:
                self._job = self.widget.after(self.DELAY_MS, self.show)
            except tk.TclError:
                pass

    def _cancel(self) -> None:
        if self._job:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def show(self) -> None:
        self._job = None
        if not self.text or self._window is not None:
            return
        try:
            if not self.widget.winfo_ismapped():
                return
        except tk.TclError:
            return
        from . import windows

        c = ctx()
        pal = c.pal
        win = tk.Toplevel(self.widget)
        win.withdraw()
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        rounded = False
        border = tk.Frame(win, bg=pal.flyout_stroke, bd=0)
        border.pack(fill="both", expand=True)
        label = tk.Label(border, text=self.text, font=c.fonts.caption, bg=pal.flyout, fg=pal.text, justify="left", wraplength=px(320), padx=px(8), pady=px(5))
        label.pack(fill="both", expand=True, padx=1, pady=1)
        win.update_idletasks()
        width, height = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.widget.winfo_pointerx() - width // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + px(6)
        screen_w, screen_h = win.winfo_screenwidth(), win.winfo_screenheight()
        if y + height > screen_h - px(8):
            y = self.widget.winfo_rooty() - height - px(6)
        x = max(px(4), min(x, screen_w - width - px(4)))
        win.geometry(f"+{x}+{y}")
        # Ecken und Transparenz vor dem Anzeigen setzen: kein kurz eckiges oder deckendes Fenster.
        try:
            rounded = windows.round_popup(windows.frame_hwnd(win), small=True, border=pal.flyout_stroke)
        except Exception:
            rounded = False
        if rounded:
            label.pack_configure(padx=0, pady=0)
        fade = c.anim.allowed()
        if fade:
            try:
                win.attributes("-alpha", 0.0)
            except tk.TclError:
                fade = False
        from .context import reveal

        reveal(win, position=(x, y), prepare=False)
        self._window = win
        if fade:
            c.anim.run(f"tip:{win}", 120, lambda t: win.attributes("-alpha", t), widget=win)

    def hide(self, _event=None) -> None:
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None


# ---------------------------------------------------------------------------
# Umbrechende Zeile (für Schaltflächengruppen)
# ---------------------------------------------------------------------------


class FlowRow(tk.Frame):
    """Ordnet Kinder nebeneinander an und bricht bei wenig Platz in neue Zeilen um."""

    def __init__(self, master, gap: int = 8, row_gap: int = 8) -> None:
        super().__init__(master, bd=0, highlightthickness=0, height=1)
        self.surface_role = surface_of(master)
        ctx().theme.style(self, bg=self.surface_role)
        self._gap = px(gap)
        self._row_gap = px(row_gap)
        self._items: list[tuple[tk.Widget, str]] = []
        self._placed: tuple = ()
        self._height = 0
        self._width = 0
        self._sizes: dict[str, tuple[int, int]] = {}
        self._hidden: set[str] = set()
        self._pending = False
        self.bind("<Configure>", self._configured, add="+")

    def set_visible(self, widget: tk.Widget, visible: bool) -> None:
        """Element ein- oder ausblenden, ohne die übrige Reihenfolge zu ändern."""
        key = str(widget)
        if visible == (key not in self._hidden):
            return
        if visible:
            self._hidden.discard(key)
        else:
            self._hidden.add(key)
            widget.place_forget()
        self._placed = ()
        self._schedule()

    def is_visible(self, widget: tk.Widget) -> bool:
        return str(widget) not in self._hidden

    def _configured(self, event) -> None:
        if event.width != self._width:
            self._width = event.width
            self._layout()

    def add(self, widget: tk.Widget, align: str = "left") -> tk.Widget:
        self._items.append((widget, align))
        widget.bind("<Configure>", lambda event, w=widget: self._child_configured(w, event), add="+")
        self._schedule()
        return widget

    def _child_configured(self, widget: tk.Widget, event) -> None:
        # Nur Größenänderungen eines Elements erfordern eine neue Anordnung, keine Verschiebungen.
        size = (event.width, event.height)
        if self._sizes.get(str(widget)) != size:
            self._sizes[str(widget)] = size
            self._schedule()

    def _schedule(self) -> None:
        if not self._pending:
            self._pending = True
            self.after_idle(self._run_layout)

    def _run_layout(self) -> None:
        self._pending = False
        self._layout()

    def _layout(self) -> None:
        try:
            width = self.winfo_width()
        except tk.TclError:
            return
        if width <= 1:
            width = sum(w.winfo_reqwidth() for w, _ in self._items if str(w) not in self._hidden) + self._gap * len(self._items)
        x = y = 0
        line_h = 0
        rows: list[list[tuple[tk.Widget, int, int]]] = [[]]
        for widget, _align in self._items:
            if not widget.winfo_exists() or str(widget) in self._hidden:
                continue
            w, h = widget.winfo_reqwidth(), widget.winfo_reqheight()
            if x > 0 and x + w > width:
                x = 0
                y += line_h + self._row_gap
                line_h = 0
                rows.append([])
            rows[-1].append((widget, x, y))
            x += w + self._gap
            line_h = max(line_h, h)
        total_h = y + line_h
        placement = []
        for row in rows:
            row_h = max((wd.winfo_reqheight() for wd, _x, _y in row), default=0)
            for widget, wx, wy in row:
                placement.append((widget, wx, wy + (row_h - widget.winfo_reqheight()) // 2))
        # Beim Ziehen am Fensterrand ändert sich meist nur die Breite, nicht die Anordnung:
        # dann weder neu platzieren noch eine neue Höhe anfordern.
        placed = tuple((str(widget), wx, wy) for widget, wx, wy in placement)
        if placed != self._placed:
            self._placed = placed
            for widget, wx, wy in placement:
                widget.place(x=wx, y=wy)
        if total_h != self._height:
            self._height = total_h
            self.configure(height=max(1, total_h))
