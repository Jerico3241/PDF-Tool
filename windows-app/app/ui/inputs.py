"""Eingabefelder: Textfeld, mehrzeiliges Textfeld und Auswahlliste (ComboBox)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Sequence

from . import animations as motion
from . import icons
from . import windows
from .context import bind_size, ctx, reveal, surface_color
from .theme import px
from .widgets import CONTROL_RADIUS, FOCUS_PAD, CanvasControl, StretchBox


def _pointer_inside(widget: tk.Misc) -> bool:
    try:
        target = widget.winfo_containing(widget.winfo_pointerx(), widget.winfo_pointery())
    except (tk.TclError, KeyError):
        return False
    while target is not None:
        if target is widget:
            return True
        target = getattr(target, "master", None)
    return False


class _FieldBase(tk.Canvas):
    """Gemeinsame Optik für Text- und Mehrzeilenfelder (WinUI TextBox)."""

    def __init__(self, master, width: int, height: int) -> None:
        self.c = ctx()
        self._fp = px(FOCUS_PAD)
        super().__init__(master, width=width + 2 * self._fp, height=height + 2 * self._fp, highlightthickness=0, bd=0, takefocus=0)
        self._hover = False
        self._focused = False
        self._enabled = True
        self._error = False
        self._images: dict[str, tk.PhotoImage] = {}
        self._field_size = (width + 2 * self._fp, height + 2 * self._fp)
        self._bg = StretchBox(self)
        self.configure(bg=self.surface())
        self.c.theme.subscribe(self._theme_changed, owner=self)
        bind_size(self, self._on_configure)

    def _on_configure(self, event) -> None:
        size = (event.width, event.height)
        if size == self._field_size:
            return  # nur verschoben: nichts neu zu zeichnen
        self._field_size = size
        self.redraw()
        self._layout()

    def _layout(self) -> None:
        pass

    def _theme_changed(self) -> None:
        self.configure(bg=self.surface())
        self.redraw()

    def _bind_hover(self, *widgets: tk.Misc) -> None:
        for widget in (self, *widgets):
            widget.bind("<Enter>", self._enter, add="+")
            widget.bind("<Leave>", self._leave, add="+")

    def _enter(self, _event=None) -> None:
        if not self._hover:
            self._hover = True
            self.redraw()

    def _leave(self, _event=None) -> None:
        if self._hover and not _pointer_inside(self):
            self._hover = False
            self.redraw()

    def surface(self) -> str:
        return surface_color(self.master)

    def fill_color(self) -> str:
        pal = self.c.pal
        if not self._enabled:
            return pal.control_disabled
        if self._focused:
            return pal.input_focus
        if self._hover:
            return pal.control_hover
        return pal.control

    def set_error(self, error: bool) -> None:
        self._error = bool(error)
        self.redraw()

    def redraw(self) -> None:
        pal = self.c.pal
        surface = self.surface()
        try:
            width = self.winfo_width()
            if width <= 1:
                width = int(self.cget("width"))
            height = int(self.cget("height"))
        except tk.TclError:
            return
        fp = self._fp
        w, h = max(8, width - 2 * fp), max(8, height - 2 * fp)
        fill = self.fill_color()
        if not self._enabled:
            stroke, edge, edge_w = pal.control_stroke, pal.control_stroke, 1
        elif self._error:
            stroke, edge, edge_w = pal.critical, pal.critical, 2 if self._focused else 1
        elif self._focused:
            stroke, edge, edge_w = pal.control_stroke, pal.accent, 2
        else:
            stroke, edge, edge_w = pal.control_stroke, pal.input_edge, 1
        slices = self.c.images.box_slices(h, px(CONTROL_RADIUS), fill, stroke, edge, "bottom", background=surface, edge_width=px(edge_w) if edge_w > 1 else 1)
        self._bg.show(slices, fp, fp, w)
        self._restyle_inner(fill)

    def _restyle_inner(self, fill: str) -> None:
        pass


class TextField(_FieldBase):
    """Einzeiliges Eingabefeld mit Platzhalter, Fokuslinie in Akzentfarbe und Fehlerzustand."""

    def __init__(self, master, variable: tk.StringVar | None = None, placeholder: str = "", width: int = 220, on_submit: Callable[[], None] | None = None, validate: Callable[[str], bool] | None = None, justify: str = "left") -> None:
        c = ctx()
        self.var = variable if variable is not None else tk.StringVar(master)
        super().__init__(master, px(width), px(32))
        self._validate = validate
        self.entry = tk.Entry(self, textvariable=self.var, relief="flat", bd=0, highlightthickness=0, font=c.fonts.body, justify=justify)
        self._placeholder_text = placeholder
        self.placeholder = tk.Label(self, text=placeholder, font=c.fonts.body, bd=0, padx=0, pady=0, anchor="w", cursor="xterm")
        fp = self._fp
        self._entry_item = self.create_window(fp + px(11), fp + px(16), anchor="w", window=self.entry)
        self._ph_item = self.create_window(fp + px(11), fp + px(16), anchor="w", window=self.placeholder)
        self.placeholder.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.bind("<Button-1>", lambda _e: self.entry.focus_set(), add="+")
        self.entry.bind("<FocusIn>", self._focus_in, add="+")
        self.entry.bind("<FocusOut>", self._focus_out, add="+")
        if on_submit:
            self.entry.bind("<Return>", lambda _e: (on_submit(), "break")[1], add="+")
        self._bind_hover(self.entry, self.placeholder)
        self._trace = self.var.trace_add("write", lambda *_a: self._changed())
        self.bind("<Destroy>", self._untrace, add="+")
        self._changed()
        self.redraw()
        self._layout()

    def _untrace(self, event) -> None:
        if event.widget is self:
            try:
                self.var.trace_remove("write", self._trace)
            except (tk.TclError, ValueError):
                pass

    def _layout(self) -> None:
        fp = self._fp
        inner = max(20, self._field_size[0] - 2 * fp - px(22))
        self.itemconfigure(self._entry_item, width=inner)
        self.itemconfigure(self._ph_item, width=inner)

    def _changed(self) -> None:
        empty = not self.var.get()
        state = "normal" if (empty and not self._focused and self._placeholder_text) else "hidden"
        try:
            self.itemconfigure(self._ph_item, state=state)
        except tk.TclError:
            return
        if self._error and self._validate and self._validate(self.var.get()):
            self.set_error(False)

    def _focus_in(self, _event=None) -> None:
        self._focused = True
        self._changed()
        self.redraw()

    def _focus_out(self, _event=None) -> None:
        self._focused = False
        self._changed()
        if self._validate is not None:
            self._error = not self._validate(self.var.get())
        self.redraw()

    def _restyle_inner(self, fill: str) -> None:
        pal = self.c.pal
        self.entry.configure(
            bg=fill,
            fg=pal.text if self._enabled else pal.text_disabled,
            insertbackground=pal.text,
            selectbackground=pal.accent,
            selectforeground=pal.on_accent,
            disabledbackground=fill,
            disabledforeground=pal.text_disabled,
            readonlybackground=fill,
        )
        self.placeholder.configure(bg=fill, fg=pal.text2 if self._enabled else pal.text_disabled)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.entry.configure(state="normal" if enabled else "disabled")
        self.redraw()

    def focus(self) -> None:
        self.entry.focus_set()
        self.entry.icursor("end")

    def get(self) -> str:
        return self.var.get()

    def set_placeholder(self, text: str) -> None:
        self._placeholder_text = text
        self.placeholder.configure(text=text)
        self._changed()


class TextArea(_FieldBase):
    """Mehrzeiliges Textfeld mit Rückgängig-Funktion.

    ``on_change`` wird bei jeder inhaltlichen Änderung aufgerufen (für verzögertes Speichern).
    ``get()`` liefert den Inhalt exakt – nur der technische Schlusszeilenumbruch von Tk fehlt.
    """

    def __init__(self, master, lines: int = 4, width: int = 320, on_change: Callable[[], None] | None = None) -> None:
        c = ctx()
        line_h = c.fonts.body.metrics("linespace")
        height = lines * line_h + px(14)
        super().__init__(master, px(width), height)
        self.text = tk.Text(self, height=lines, wrap="word", undo=True, maxundo=200, relief="flat", bd=0, highlightthickness=0, font=c.fonts.body, padx=0, pady=0)
        fp = self._fp
        self._item = self.create_window(fp + px(11), fp + px(7), anchor="nw", window=self.text)
        self.text.bind("<FocusIn>", lambda _e: self._set_focus(True), add="+")
        self.text.bind("<FocusOut>", lambda _e: self._set_focus(False), add="+")
        self.text.bind("<Tab>", self._tab, add="+")
        self.text.bind("<Shift-Tab>", self._shift_tab, add="+")
        self.bind("<Button-1>", lambda _e: self.text.focus_set(), add="+")
        self._bind_hover(self.text)
        self._on_change = on_change
        self.text.bind("<<Modified>>", self._modified, add="+")
        self.redraw()
        self._layout()

    def _modified(self, _event=None) -> None:
        # Tk meldet <<Modified>> nur beim Wechsel des Änderungskennzeichens: zurücksetzen,
        # damit auch die nächste Änderung gemeldet wird.
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if self._on_change is not None:
            self._on_change()

    def _tab(self, _event=None):
        self.text.tk_focusNext().focus_set()
        return "break"

    def _shift_tab(self, _event=None):
        self.text.tk_focusPrev().focus_set()
        return "break"

    def _layout(self) -> None:
        fp = self._fp
        width = max(20, self._field_size[0] - 2 * fp - px(22))
        height = max(20, self._field_size[1] - 2 * fp - px(14))
        self.itemconfigure(self._item, width=width, height=height)

    def _set_focus(self, focused: bool) -> None:
        self._focused = focused
        self.redraw()

    def _restyle_inner(self, fill: str) -> None:
        pal = self.c.pal
        self.text.configure(bg=fill, fg=pal.text, insertbackground=pal.text, selectbackground=pal.accent, selectforeground=pal.on_accent, inactiveselectbackground=pal.divider)

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set(self, value: str) -> None:
        self.text.delete("1.0", "end")
        if value:
            self.text.insert("1.0", value)
        self.text.edit_reset()

    def replace(self, value: str) -> None:
        """Inhalt ersetzen – mit Strg+Z in einem Schritt rückgängig zu machen."""
        auto = self.text.cget("autoseparators")
        self.text.configure(autoseparators=False)
        try:
            self.text.edit_separator()
            self.text.delete("1.0", "end")
            if value:
                self.text.insert("1.0", value)
            self.text.edit_separator()
        finally:
            self.text.configure(autoseparators=auto)


# ---------------------------------------------------------------------------
# ComboBox
# ---------------------------------------------------------------------------


class ComboBox(CanvasControl):
    """Auswahlliste im Stil von Windows 11 mit eigener Aufklappliste.

    Die Tastatur bleibt im Feld: Pfeiltasten wählen direkt, Alt+↓, Leertaste
    oder Eingabe öffnen die Liste, Escape schließt sie.
    """

    def __init__(self, master, values: Sequence[str] = (), command: Callable[[str], None] | None = None, placeholder: str = "", width: int = 220, tooltip: str | None = None) -> None:
        c = ctx()
        self._values: list[str] = list(values)
        self._command = command
        self._placeholder = placeholder
        self._index: int | None = None
        self._fp = px(FOCUS_PAD)
        self._h = px(32)
        self._popup: _ComboPopup | None = None
        super().__init__(master, px(width) + 2 * self._fp, self._h + 2 * self._fp)
        self._bg = StretchBox(self)
        self._ring = StretchBox(self)
        self._label = self.create_text(0, 0, anchor="w", font=c.fonts.body)
        self._chevron = self.create_text(0, 0, anchor="center", text=icons.CHEVRON_DOWN if c.icons_available else "▾", font=c.fonts.icon_small or c.fonts.caption)
        for key, handler in (
            ("<KeyPress-Down>", lambda _e: self._step(1)),
            ("<KeyPress-Up>", lambda _e: self._step(-1)),
            ("<KeyPress-Home>", lambda _e: self._jump(0)),
            ("<KeyPress-End>", lambda _e: self._jump(len(self._values) - 1)),
            ("<Alt-KeyPress-Down>", lambda _e: self._toggle_popup()),
            ("<KeyPress-F4>", lambda _e: self._toggle_popup()),
            ("<KeyPress-space>", lambda _e: self._toggle_popup()),
            ("<KeyPress-Return>", lambda _e: self._enter_key()),
            ("<KeyPress-Escape>", lambda _e: self._escape()),
            ("<KeyPress-Tab>", lambda _e: self.close_popup()),
        ):
            self.bind(key, lambda event, h=handler: (h(event), "break")[1] if not (event.keysym == "Tab") else h(event), add="+")
        if tooltip:
            self.set_tooltip(tooltip)
        self.redraw()

    # Werte ---------------------------------------------------------------
    def set_values(self, values: Sequence[str], keep: bool = True) -> None:
        current = self.get()
        self._values = list(values)
        if keep and current in self._values:
            self._index = self._values.index(current)
        else:
            self._index = None
        self.redraw()

    def values(self) -> list[str]:
        return list(self._values)

    def set(self, value: str | None) -> None:
        """Auswahl ohne Rückruf setzen. Unbekannte Werte leeren die Auswahl."""
        if value in self._values:
            self._index = self._values.index(value)  # type: ignore[arg-type]
        else:
            self._index = None
        self.redraw()

    def get(self) -> str:
        if self._index is None or self._index >= len(self._values):
            return ""
        return self._values[self._index]

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self.redraw()

    def select_index(self, index: int, notify: bool = True) -> None:
        if not self._values:
            return
        index = max(0, min(len(self._values) - 1, index))
        changed = index != self._index
        self._index = index
        self.redraw()
        if notify and self._command and changed:
            self._command(self._values[index])
        elif notify and self._command and not changed:
            self._command(self._values[index])

    def _step(self, delta: int) -> None:
        if self._popup is not None:
            self._popup.move(delta)
            return
        if not self._values:
            return
        start = -1 if self._index is None else self._index
        if self._index is None and delta < 0:
            start = len(self._values)
        self.select_index(start + delta)

    def _jump(self, index: int) -> None:
        if self._popup is not None:
            self._popup.highlight(index)
        elif self._values:
            self.select_index(index)

    def _enter_key(self) -> None:
        if self._popup is not None:
            self._popup.choose_highlighted()
        else:
            self.open_popup()

    def _escape(self) -> None:
        self.close_popup()

    # Aufklappliste ------------------------------------------------------------
    def activate(self) -> None:
        self._toggle_popup()

    def _toggle_popup(self) -> None:
        if self._popup is not None:
            self.close_popup()
        else:
            self.open_popup()

    def open_popup(self) -> None:
        if not self._enabled or self._popup is not None:
            return
        self._popup = _ComboPopup(self)
        self.redraw()

    def close_popup(self) -> None:
        popup = self._popup
        self._popup = None
        if popup is not None:
            popup.close()
            try:
                self.redraw()
            except tk.TclError:
                pass

    def _chosen(self, index: int) -> None:
        self.close_popup()
        self.focus_set()
        self.select_index(index)

    def _on_focus_out(self, _event=None) -> None:
        super()._on_focus_out(_event)
        self.after(120, self._check_focus)

    def _check_focus(self) -> None:
        try:
            focus = self.focus_get()
        except (tk.TclError, KeyError):
            focus = None
        if focus is not self and self._popup is not None and not self._popup.pointer_inside():
            self.close_popup()

    # Zeichnen ---------------------------------------------------------------------
    def redraw(self, animate: bool = True) -> None:
        c = self.c
        pal = self.pal
        surface = self.surface()
        try:
            width = max(self.winfo_width(), int(self.cget("width")))
        except tk.TclError:
            return
        fp, h = self._fp, self._h
        if not self._enabled:
            fill, edge, fg = pal.control_disabled, pal.control_stroke, pal.text_disabled
        elif self._pressed or self._popup is not None:
            fill, edge, fg = pal.control_pressed, pal.control_stroke, pal.text
        elif self._hover:
            fill, edge, fg = pal.control_hover, pal.control_edge, pal.text
        else:
            fill, edge, fg = pal.control, pal.control_edge, pal.text
        side = "bottom" if not pal.dark else "top"
        self._bg.show(c.images.box_slices(h, px(CONTROL_RADIUS), fill, pal.control_stroke, edge, side, background=surface), fp, fp, width - 2 * fp)
        if self.show_focus():
            self._ring.show(c.images.ring_slices(h + 2 * fp, px(CONTROL_RADIUS) + fp, pal.focus_outer, pal.focus_inner), 0, 0, width)
        else:
            self._ring.hide()
        value = self.get()
        text = value or self._placeholder
        color = fg if value else (pal.text2 if self._enabled else pal.text_disabled)
        max_w = width - 2 * fp - px(11) - px(40)
        text = _elide(c.fonts.body, text, max_w)
        self.itemconfigure(self._label, text=text, fill=color)
        self.coords(self._label, fp + px(11), fp + h / 2)
        self.itemconfigure(self._chevron, fill=pal.text2 if self._enabled else pal.text_disabled)
        self.coords(self._chevron, width - fp - px(20), fp + h / 2)


def _elide(font, text: str, max_width: int) -> str:
    if max_width <= 0 or font.measure(text) <= max_width:
        return text
    ellipsis = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + ellipsis) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ellipsis


_ELIDED: dict[tuple, str] = {}
_ELIDED_MAX = 4096


def elide_middle(font, text: str, max_width: int) -> str:
    """Kürzt lange Pfade in der Mitte: C:\\Users\\…\\Datei.xlsx

    Ergebnisse werden je Schrift, Text und Breite gemerkt: Listen mit vielen Zeilen messen
    beim Neuzeichnen nicht jeden Text erneut.
    """
    if max_width <= 0:
        return text
    key = (str(font), text, max_width)
    found = _ELIDED.get(key)
    if found is None:
        found = _elide_in_middle(font, text, max_width)
        if len(_ELIDED) >= _ELIDED_MAX:
            _ELIDED.clear()
        _ELIDED[key] = found
    return found


def _elide_in_middle(font, text: str, max_width: int) -> str:
    if font.measure(text) <= max_width:
        return text
    ellipsis = "…"
    # Wie viele Zeichen passen? Binäre Suche statt Zeichen für Zeichen (wenige Messungen).
    low, high = 0, len(text)
    while low < high:
        keep = (low + high + 1) // 2
        right = keep // 2
        left = keep - right
        candidate = text[:left] + ellipsis + (text[len(text) - right :] if right else "")
        if font.measure(candidate) <= max_width:
            low = keep
        else:
            high = keep - 1
    right = low // 2
    left = low - right
    return text[:left] + ellipsis + (text[len(text) - right :] if right else "")


class _ComboPopup:
    ROW = 36
    MAX_ROWS = 8

    def __init__(self, combo: ComboBox) -> None:
        self.combo = combo
        c = ctx()
        pal = c.pal
        self.c = c
        self.win = tk.Toplevel(combo)
        self.win.withdraw()
        self.win.overrideredirect(True)
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        values = combo.values()
        self.values = values
        self.row = px(self.ROW)
        self.pad = px(4)
        visible = max(1, min(self.MAX_ROWS, len(values)))
        fp = combo._fp
        self.width = max(px(120), combo.winfo_width() - 2 * fp)
        self.height = visible * self.row + 2 * self.pad if values else self.row + 2 * self.pad
        self.border = tk.Frame(self.win, bd=0, bg=pal.flyout_stroke)
        self.border.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.border, width=self.width - 2, height=self.height - 2, highlightthickness=0, bd=0, bg=pal.flyout)
        self.canvas.pack(padx=1, pady=1)
        self.canvas.surface_role = "flyout"  # type: ignore[attr-defined]
        self.canvas._combo_popup_canvas = True  # type: ignore[attr-defined]
        self.hover: int | None = None
        self.highlighted = combo._index if combo._index is not None else (0 if values else None)
        self.offset = 0
        self._images: list = []
        self._draw()
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        self.canvas.bind("<ButtonRelease-1>", self._click)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda _e: self.scroll(-1))
        self.canvas.bind("<Button-5>", lambda _e: self.scroll(1))
        self._ensure_visible(self.highlighted)
        x = combo.winfo_rootx() + fp
        y = combo.winfo_rooty() + fp + combo._h + px(4)
        screen_h = combo.winfo_screenheight()
        if y + self.height > screen_h - px(40):
            y = combo.winfo_rooty() + fp - self.height - px(4)
        self.x, self.y = x, y
        fade = c.anim.allowed()
        start_y = (y - px(8) if y > combo.winfo_rooty() else y + px(8)) if fade else y
        self.win.geometry(f"{self.width}x{self.height}+{x}+{start_y}")
        # Fensterstil, runde Ecken und Transparenz vor dem Anzeigen setzen (kein Aufblitzen).
        self.win.update_idletasks()
        hwnd = windows.frame_hwnd(self.win)
        windows.set_no_activate(hwnd)
        if windows.round_popup(hwnd, border=pal.flyout_stroke):
            self.border.configure(bg=pal.flyout)
        if fade:
            try:
                self.win.attributes("-alpha", 0.0)
            except tk.TclError:
                fade = False
        # Vollständig gezeichnet sichtbar machen, danach einblenden und hineingleiten lassen.
        reveal(self.win, position=(x, start_y), prepare=False)
        c.press_hooks.append(self._global_press)
        c.window_hooks.append(self._window_moved)
        if fade:
            def step(t: float) -> None:
                self.win.attributes("-alpha", t)
                yy = int(start_y + (y - start_y) * t)
                self.win.geometry(f"+{x}+{yy}")

            c.anim.run(f"popup:{self.win}", motion.NORMAL, step, easing=motion.DECELERATE, widget=self.win, motion=True)

    def pointer_inside(self) -> bool:
        try:
            px_, py_ = self.win.winfo_pointerx(), self.win.winfo_pointery()
            return self.x <= px_ < self.x + self.width and self.y <= py_ < self.y + self.height
        except tk.TclError:
            return False

    def _global_press(self, event) -> None:
        try:
            if str(event.widget).startswith(str(self.win)):
                return
        except Exception:
            pass
        if event.widget is self.combo:
            return
        self.combo.after_idle(self.combo.close_popup)

    def _window_moved(self, _event=None) -> None:
        self.combo.after_idle(self.combo.close_popup)

    def close(self) -> None:
        for hooks, hook in ((self.c.press_hooks, self._global_press), (self.c.window_hooks, self._window_moved)):
            if hook in hooks:
                hooks.remove(hook)
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    # Darstellung ------------------------------------------------------------
    def _draw(self) -> None:
        c = self.c
        pal = c.pal
        canvas = self.canvas
        canvas.delete("all")
        self._images.clear()
        width = self.width - 2
        if not self.values:
            canvas.create_text(px(12), self.pad + self.row / 2, anchor="w", text="Keine Einträge", fill=pal.text2, font=c.fonts.body)
            return
        radius = px(CONTROL_RADIUS)
        for index, value in enumerate(self.values):
            top = self.pad + (index - self.offset) * self.row
            if top + self.row < 0 or top > self.height:
                continue
            selected = index == self.combo._index
            is_hl = index == self.highlighted and self.combo.c.keyboard_mode
            hovered = index == self.hover
            if selected or hovered or is_hl:
                fill = pal.subtle_pressed(pal.flyout) if (hovered and selected) else pal.subtle_hover(pal.flyout)
                img = c.images.box(width - 2 * px(5), self.row - px(4), radius, fill, background=pal.flyout)
                self._images.append(img)
                canvas.create_image(px(5), top + px(2), anchor="nw", image=img)
            if selected:
                pill = c.images.box(px(3), px(16), px(1.5), pal.accent, background=subtle_bg(pal, hovered))
                self._images.append(pill)
                canvas.create_image(px(5), top + self.row / 2, anchor="w", image=pill)
            text = _elide(c.fonts.body, value, width - px(40))
            canvas.create_text(px(16), top + self.row / 2, anchor="w", text=text, fill=pal.text, font=c.fonts.body)
        if len(self.values) > self.MAX_ROWS:
            total = len(self.values)
            track_h = self.height - 2 * self.pad
            thumb_h = max(px(16), track_h * self.MAX_ROWS / total)
            max_off = total - self.MAX_ROWS
            y0 = self.pad + (track_h - thumb_h) * (self.offset / max_off if max_off else 0)
            bar = c.images.box(px(3), int(thumb_h), px(1.5), pal.strong_stroke, background=pal.flyout)
            self._images.append(bar)
            canvas.create_image(width - px(5), y0, anchor="ne", image=bar)

    def _index_at(self, y: int) -> int | None:
        index = int((y - self.pad) // self.row) + self.offset
        if 0 <= index < len(self.values) and y >= self.pad:
            return index
        return None

    def _set_hover(self, index: int | None) -> None:
        if index != self.hover:
            self.hover = index
            self._draw()

    def _motion(self, event) -> None:
        self._set_hover(self._index_at(event.y))

    def _click(self, event) -> None:
        index = self._index_at(event.y)
        if index is not None:
            self.combo._chosen(index)

    def _wheel(self, event):
        self.scroll(-1 if event.delta > 0 else 1)
        return "break"

    def scroll(self, delta: int) -> None:
        max_off = max(0, len(self.values) - self.MAX_ROWS)
        new = max(0, min(max_off, self.offset + delta))
        if new != self.offset:
            self.offset = new
            self._draw()

    def _ensure_visible(self, index: int | None) -> None:
        if index is None:
            return
        if index < self.offset:
            self.offset = index
        elif index >= self.offset + self.MAX_ROWS:
            self.offset = index - self.MAX_ROWS + 1
        self._draw()

    def move(self, delta: int) -> None:
        if not self.values:
            return
        current = self.highlighted if self.highlighted is not None else -1
        self.highlight(max(0, min(len(self.values) - 1, current + delta)))

    def highlight(self, index: int) -> None:
        if not self.values:
            return
        self.highlighted = max(0, min(len(self.values) - 1, index))
        self._ensure_visible(self.highlighted)

    def choose_highlighted(self) -> None:
        if self.highlighted is not None:
            self.combo._chosen(self.highlighted)
        else:
            self.combo.close_popup()


def subtle_bg(pal, hovered: bool) -> str:
    return pal.subtle_pressed(pal.flyout) if hovered else pal.subtle_hover(pal.flyout)
