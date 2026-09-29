"""Scrollbereich mit Windows-11-Bildlaufleiste und weichem Scrollen."""

from __future__ import annotations

import tkinter as tk

from . import animations as motion
from .context import ctx, surface_color, surface_of
from .theme import px


class FluentScrollbar(tk.Canvas):
    """Schmale Bildlaufleiste: im Ruhezustand ein dünner Strich, beim Überfahren breiter."""

    WIDTH = 12

    def __init__(self, master, command) -> None:
        self.c = ctx()
        super().__init__(master, width=px(self.WIDTH), highlightthickness=0, bd=0, cursor="")
        self._command = command
        self._first, self._last = 0.0, 1.0
        self._expand = 0.0  # 0 = dünn, 1 = breit
        self._drag: tuple[int, float] | None = None
        self._images: dict = {}
        self._height = 0
        self._drawn: tuple | None = None
        self._track = self.create_image(0, 0, anchor="nw")
        self._thumb = self.create_image(0, 0, anchor="nw")
        self.bind("<Enter>", lambda _e: self._animate(1.0), add="+")
        self.bind("<Leave>", lambda _e: self._animate(0.0) if self._drag is None else None, add="+")
        self.bind("<ButtonPress-1>", self._press, add="+")
        self.bind("<B1-Motion>", self._motion, add="+")
        self.bind("<ButtonRelease-1>", self._release, add="+")
        self.bind("<Configure>", self._configured, add="+")
        self.c.theme.subscribe(self._theme_changed, owner=self)
        self.configure(bg=surface_color(self.master))

    def _configured(self, event) -> None:
        if event.height != self._height:
            self._height = event.height
            self.redraw()

    def _theme_changed(self) -> None:
        self.configure(bg=surface_color(self.master))
        self._drawn = None
        self.redraw()

    def set(self, first, last) -> None:
        first, last = float(first), float(last)
        if (first, last) == (self._first, self._last):
            return
        self._first, self._last = first, last
        self.redraw()

    def needed(self) -> bool:
        return self._last - self._first < 0.999

    def _animate(self, target: float) -> None:
        start = self._expand

        def step(t: float) -> None:
            self._expand = start + (target - start) * t
            self.redraw()

        self.c.anim.run(f"sb:{self}", motion.FAST if target > start else motion.NORMAL, step, widget=self)

    def _geometry(self) -> tuple[float, float, int]:
        height = max(1, self.winfo_height())
        margin = px(4)
        track = max(1, height - 2 * margin)
        thumb_h = max(px(24), track * (self._last - self._first))
        free = max(0.0, track - thumb_h)
        span = max(1e-6, 1.0 - (self._last - self._first))
        y = margin + free * (self._first / span if span > 1e-6 else 0)
        return y, thumb_h, track

    def redraw(self) -> None:
        pal = self.c.pal
        surface = surface_color(self.master)
        width = px(self.WIDTH)
        if not self.needed():
            if self._drawn != ("hidden",):
                self._drawn = ("hidden",)
                self.itemconfigure(self._thumb, state="hidden")
                self.itemconfigure(self._track, state="hidden")
            return
        y, thumb_h, _track = self._geometry()
        state = (round(y, 1), round(thumb_h, 1), round(self._expand, 3), self.winfo_height(), surface)
        if state == self._drawn:
            return
        self._drawn = state
        thick = px(2) + (px(6) - px(2)) * self._expand
        thick = max(1, int(round(thick)))
        if self._expand > 0.05:
            track_bg = mix_track(pal, surface, self._expand)
            track = self.c.images.box(px(8), max(4, self.winfo_height() - px(2)), px(4), track_bg, background=surface)
            self._images["track"] = track
            self.itemconfigure(self._track, image=track, state="normal")
            self.coords(self._track, width - px(10), px(1))
            thumb_bg = track_bg
        else:
            self.itemconfigure(self._track, state="hidden")
            thumb_bg = surface
        thumb = self.c.images.box(thick, max(4, int(thumb_h)), thick / 2, pal.strong_stroke, background=thumb_bg)
        self._images["thumb"] = thumb
        x = width - px(6) - thick / 2
        self.itemconfigure(self._thumb, image=thumb, state="normal")
        self.coords(self._thumb, x, y)
        self.tag_raise(self._thumb)

    def _press(self, event) -> None:
        if not self.needed():
            return
        y, thumb_h, _track = self._geometry()
        if y <= event.y <= y + thumb_h:
            self._drag = (event.y, self._first)
        else:
            self._command("scroll", 1 if event.y > y else -1, "pages")

    def _motion(self, event) -> None:
        if self._drag is None:
            return
        start_y, start_first = self._drag
        _y, thumb_h, track = self._geometry()
        free = max(1.0, track - thumb_h)
        span = 1.0 - (self._last - self._first)
        delta = (event.y - start_y) / free * span
        self._command("moveto", max(0.0, min(span, start_first + delta)))

    def _release(self, _event) -> None:
        self._drag = None


def mix_track(pal, surface: str, amount: float) -> str:
    from .theme import mix

    target = pal.subtle_hover(surface)
    return mix(surface, target, amount)


class ScrollArea(tk.Frame):
    """Vertikal scrollbarer Bereich. Inhalte kommen in ``self.body``.

    ``max_width`` begrenzt die Breite des Inhalts (effektive Pixel). Breite und
    Scrollbereich werden nur gesetzt, wenn sie sich tatsächlich ändern.
    """

    def __init__(self, master, max_width: int | None = None) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = surface_of(master)
        c = ctx()
        c.theme.style(self, bg=self.surface_role)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, yscrollincrement=1)
        self.canvas.surface_role = self.surface_role  # type: ignore[attr-defined]
        c.theme.style(self.canvas, bg=self.surface_role)
        self.body = tk.Frame(self.canvas, bd=0, highlightthickness=0)
        self.body.surface_role = self.surface_role  # type: ignore[attr-defined]
        c.theme.style(self.body, bg=self.surface_role)
        self._window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.scrollbar = FluentScrollbar(self, self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(fill="both", expand=True)
        self.scrollbar.place(relx=1.0, x=-px(2), y=0, relheight=1.0, anchor="ne")
        self.body.bind("<Configure>", self._sync, add="+")
        self.canvas.bind("<Configure>", self._on_canvas, add="+")
        self._target: float | None = None
        self.offset_x = 0
        self._max_width = px(max_width) if max_width else None
        self._body_width: int | None = None
        self._region: tuple | None = None
        self._scrollbar_raised = False

    def _on_scroll(self, first, last) -> None:
        self.scrollbar.set(first, last)
        needed = self.scrollbar.needed()
        if needed and not self._scrollbar_raised:
            tk.Misc.lift(self.scrollbar)
        self._scrollbar_raised = needed

    def _on_canvas(self, event) -> None:
        width = event.width if self._max_width is None else min(event.width, self._max_width)
        if width != self._body_width:
            self._body_width = width
            self.canvas.itemconfigure(self._window, width=width)
        self._sync()

    def _sync(self, _event=None) -> None:
        height = self.body.winfo_reqheight()
        view_h = self.canvas.winfo_height()
        region = (0, 0, max(1, self.canvas.winfo_width()), max(height, view_h))
        if region != self._region:
            self._region = region
            self.canvas.configure(scrollregion=region)
        if height <= view_h and self.canvas.canvasy(0) != 0:
            self.canvas.yview_moveto(0)

    def set_offset(self, x: int) -> None:
        """Horizontaler Versatz für Seitenübergänge."""
        self.offset_x = x
        self.canvas.coords(self._window, x, 0)

    def scroll_units(self, notches: float) -> None:
        """Weiches Scrollen um ``notches`` Mausrad-Rasterstufen."""
        top, bottom = self.canvas.yview()
        visible = bottom - top
        if visible >= 0.999:
            return
        total = max(1, self.body.winfo_reqheight())
        step = px(48) / total
        base = self._target if self._target is not None else top
        target = max(0.0, min(1.0 - visible, base + notches * step))
        self._target = target
        start = top
        c = ctx()

        def step_fn(t: float) -> None:
            self.canvas.yview_moveto(start + (target - start) * t)

        def done() -> None:
            self._target = None

        c.anim.run(f"scroll:{self}", 140, step_fn, done, easing=motion.DECELERATE, widget=self)

    def scroll_to_widget(self, widget: tk.Misc) -> None:
        """Bringt ein Widget in den sichtbaren Bereich."""
        self.scroll_into_view(widget)

    def scroll_into_view(self, widget: tk.Misc, top: int = 0, height: int | None = None) -> None:
        """Bringt einen Bereich eines Widgets (``top``/``height`` relativ zum Widget) in den sichtbaren Bereich."""
        try:
            self.update_idletasks()
            y = widget.winfo_rooty() - self.body.winfo_rooty() + int(top)
            h = widget.winfo_height() if height is None else int(height)
        except tk.TclError:
            return
        total = max(1, self.body.winfo_reqheight())
        view_h = self.canvas.winfo_height()
        top, _bottom = self.canvas.yview()
        top_px = top * total
        if y < top_px + px(16):
            self.canvas.yview_moveto(max(0, (y - px(24)) / total))
        elif y + h > top_px + view_h - px(16):
            self.canvas.yview_moveto(max(0, (y + h - view_h + px(24)) / total))

    def to_top(self) -> None:
        self.canvas.yview_moveto(0)


def install_wheel_router(root: tk.Tk) -> None:
    """Mausrad scrollt den Bereich unter dem Mauszeiger (nicht nur den fokussierten)."""

    def find_area(widget) -> ScrollArea | None:
        while widget is not None:
            if isinstance(widget, ScrollArea):
                return widget
            widget = getattr(widget, "master", None)
        return None

    def route(event, notches: float) -> str | None:
        try:
            widget = root.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, KeyError):
            return None
        if widget is None:
            return None
        if widget.winfo_class() in ("Text", "Listbox"):
            try:
                first, last = widget.yview()
                if last - first < 0.999:
                    return None
            except tk.TclError:
                return None
        if hasattr(widget, "_combo_popup_canvas"):
            return None
        area = find_area(widget)
        if area is not None:
            area.scroll_units(notches)
            return "break"
        return None

    root.bind_all("<MouseWheel>", lambda e: route(e, -e.delta / 120), add="+")
    root.bind_all("<Button-4>", lambda e: route(e, -1), add="+")
    root.bind_all("<Button-5>", lambda e: route(e, 1), add="+")
