"""Rich-Text-Editor für Kopf- und Fußzeile im Fluent-Stil.

Aufbau: eine kompakte Formatierungsleiste (Schriftart, Größe, Fett, Kursiv,
Unterstrichen, Durchgestrichen, Schriftfarbe, Ausrichtung) über einem Textfeld.
Das Textfeld zeigt den Text wie in der PDF: auf weißem »Papier«, in Schrift,
Größe und Farbe der Formatierung (leicht vergrößert, damit 8 pt gut lesbar sind).

Technik
-------
* Jedes Zeichen trägt genau ein Format-Tag, jeder Absatz ein Ausrichtungs-Tag.
  Die Tags sind die einzige Quelle für die Formatierung (kein Schattenmodell).
* Einfügen, Löschen und Ersetzen laufen über einen kleinen Tcl-Vermittler vor dem
  Befehl des Textfelds: Neu eingegebener Text erhält das aktive Eingabeformat.
  Alle anderen Befehle gehen unverändert und ohne Umweg über Python an Tk.
* Rückgängig/Wiederholen (Strg+Z/Strg+Y) verwaltet der Editor selbst – für Text
  *und* Formatierung; Tippen wird zu sinnvollen Schritten zusammengefasst.
* Die Leiste wird zusammengefasst im Leerlauf aktualisiert (keine Dauerschleife,
  kein Neuaufbau), die Höhe des Felds wächst mit dem Inhalt bis zu einer Grenze.
"""

from __future__ import annotations

import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
from typing import Callable, Iterable

from richtext import ALIGNMENTS, FONT_SIZES, CharStyle, RichText, size_text, valid_color, valid_size

from . import animations as motion
from . import icons, windows
from .context import ctx, reveal, surface_of
from .inputs import ComboBox, _FieldBase
from .theme import mix, px
from .widgets import Button, FlowRow, Swatch, Text, frame

PAPER = "#FFFFFF"  # Hintergrund wie in der PDF
PAPER_TEXT = "#333333"
ZOOM = 1.25  # Darstellungsgröße im Editor: 8 pt ≈ Größe der Oberflächenschrift
MAX_LINES = 14  # bis zu dieser Höhe wächst das Feld mit, danach scrollt es
UNDO_LIMIT = 200
TYPING_PAUSE = 1.5  # Sekunden: längere Pausen beginnen einen neuen Rückgängig-Schritt

QUICK_COLORS = (
    ("Dunkel", "#333333"),
    ("Grau", "#6B6B6B"),
    ("Rot", "#B51F1F"),
    ("Blau", "#1F5AA6"),
    ("Grün", "#2E7D32"),
)
ALIGN_TAGS = {name: f"al-{name}" for name in ALIGNMENTS}
ALIGN_LABELS = {"left": "Linksbündig (Strg+L)", "center": "Zentriert (Strg+E)", "right": "Rechtsbündig (Strg+R)"}


def font_families() -> list[str]:
    from pdffonts import available_families

    return available_families()


def _pixels(size: float) -> int:
    """Schriftgröße in Punkt → Bildschirmpixel im Editor."""
    return max(6, px(float(size) * 4 / 3 * ZOOM))


def _tk_font(style: CharStyle) -> tuple:
    parts: list = [style.font, -_pixels(style.size)]
    if style.bold:
        parts.append("bold")
    if style.italic:
        parts.append("italic")
    return tuple(parts)


# ---------------------------------------------------------------------------
# Bausteine der Formatierungsleiste
# ---------------------------------------------------------------------------


class FormatToggle(Button):
    """Umschaltfläche: an (Akzentfläche wie WinUI-ToggleButton), aus oder gemischt."""

    def __init__(self, master, text: str = "", command=None, tooltip: str | None = None, font=None, icon: str | None = None, fallback: str = "") -> None:
        use_icon = bool(icon) and ctx().icons_available
        label = "" if use_icon else (text or fallback)
        self.checked: bool | None = False  # an, aus oder None (gemischt)
        super().__init__(master, label, command, icon=icon if use_icon else None, kind="subtle", tooltip=tooltip, height=32, min_width=32, padding=6)
        if font is not None and not use_icon:
            self._font = font
            self._resize()
            self.redraw(animate=False)

    def set_state(self, state: bool | None) -> None:
        if state == self.checked:
            return
        self.checked = state
        self._kind = "accent" if state is True else "subtle"
        self.redraw(animate=False)

    def _target(self) -> dict[str, str]:
        target = super()._target()
        if self.checked is None and self._kind == "subtle" and self._enabled:
            # gemischte Auswahl: dezente, dauerhafte Fläche (wie ein halb gedrückter Zustand)
            pal = self.pal
            fill = mix(self.surface(), pal.strong_stroke, 0.22 if not self._pressed else 0.3)
            target = {**target, "fill": fill, "stroke": fill, "edge": fill}
        return target


class ColorButton(Button):
    """Schaltfläche »Schriftfarbe«: Buchstabe A mit Farbbalken der aktuellen Farbe."""

    def __init__(self, master, command, tooltip: str = "Schriftfarbe") -> None:
        self._color: str | None = PAPER_TEXT
        super().__init__(master, "A", command, kind="subtle", tooltip=tooltip, height=32, min_width=36, padding=8, font="body_strong")
        self._bar = self.create_rectangle(0, 0, 0, 0, width=1)
        self.redraw(animate=False)

    def set_color(self, color: str | None) -> None:
        if color != self._color:
            self._color = color
            self.redraw(animate=False)

    def _paint(self, colors: dict[str, str], width: int) -> None:
        super()._paint(colors, width)
        bar = getattr(self, "_bar", None)
        if bar is None:
            return
        fp, h = self._fp, self._h
        cx = width / 2
        self.coords(self._text_item, cx, fp + h / 2 - px(3))
        y0 = fp + h - px(9)
        color = self._color or colors["fill"]
        # neutraler Rahmen: auch Dunkelgrau bleibt auf dunkler Fläche sichtbar
        outline = self.pal.strong_stroke
        self.coords(bar, cx - px(8), y0, cx + px(8), y0 + px(4))
        self.itemconfigure(bar, fill=color, outline=outline)


class ColorFlyout:
    """Aufklappfläche mit Schnellfarben und freier Farbauswahl.

    Wie die Liste einer Auswahlbox übernimmt sie nicht den Fokus: Das Hauptfenster
    bleibt aktiv, die Tastatur bleibt auf der Farbschaltfläche (←/→ wählen,
    Eingabe übernimmt, Escape schließt).
    """

    def __init__(self, anchor: tk.Misc, current: str | None, on_pick: Callable[[str], None], on_close: Callable[[], None] | None = None) -> None:
        c = ctx()
        pal = c.pal
        self.c = c
        self.anchor = anchor
        self.current = current
        self._on_pick = on_pick
        self._on_close = on_close
        self.win = tk.Toplevel(anchor)
        self.win.withdraw()
        self.win.overrideredirect(True)
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.border = tk.Frame(self.win, bd=0, bg=pal.flyout_stroke)
        self.border.pack(fill="both", expand=True)
        body = tk.Frame(self.border, bd=0, bg=pal.flyout)
        body.surface_role = "flyout"  # type: ignore[attr-defined]
        body.pack(fill="both", expand=True, padx=1, pady=1)
        inner = frame(body)
        inner.pack(padx=px(12), pady=(px(10), px(12)))
        Text(inner, "Schriftfarbe", style="caption", color="text2").pack(anchor="w", pady=(0, px(6)))
        row = frame(inner)
        row.pack(anchor="w")
        self.swatches: list[Swatch] = []
        for name, value in QUICK_COLORS:
            swatch = Swatch(row, lambda v=value: v, lambda v=value: self.pick(v), tooltip=f"{name} ({value})", selected_fn=lambda v=value: (self.current or "").upper() == v)
            swatch.configure(takefocus=0)
            swatch.pack(side="left", padx=(0, px(2)))
            self.swatches.append(swatch)
        self.more = Button(inner, "Weitere Farben …", self.more_colors, icon=icons.COLOR, kind="standard")
        self.more.configure(takefocus=0)
        self.more.pack(anchor="w", fill="x", pady=(px(10), 0))
        self.win.update_idletasks()
        width, height = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + px(4)
        if y + height > anchor.winfo_screenheight() - px(40):
            y = anchor.winfo_rooty() - height - px(4)
        x = max(0, min(x, anchor.winfo_screenwidth() - width))
        self.win.geometry(f"+{x}+{y}")
        # Fensterstil, runde Ecken und Transparenz vor dem Anzeigen setzen (kein Aufblitzen).
        hwnd = windows.frame_hwnd(self.win)
        windows.set_no_activate(hwnd)
        if windows.round_popup(hwnd, border=pal.flyout_stroke):
            self.border.configure(bg=pal.flyout)
        fade = c.anim.allowed()
        if fade:
            try:
                self.win.attributes("-alpha", 0.0)
            except tk.TclError:
                fade = False
        reveal(self.win, position=(x, y), prepare=False)
        c.press_hooks.append(self._global_press)
        c.window_hooks.append(self._window_moved)
        if fade:
            c.anim.run(f"flyout:{self.win}", motion.FAST, lambda t: self.win.attributes("-alpha", t), easing=motion.DECELERATE, widget=self.win)

    # Tastatur (über die Farbschaltfläche) --------------------------------------------------------
    def step(self, delta: int) -> None:
        values = [value for _name, value in QUICK_COLORS]
        current = (self.current or "").upper()
        index = values.index(current) if current in values else (-1 if delta > 0 else 0)
        self.current = values[(index + delta) % len(values)]
        for swatch in self.swatches:
            swatch.redraw()

    def choose_current(self) -> None:
        if self.current:
            self.pick(self.current)
        else:
            self.close()

    def _global_press(self, event) -> None:
        try:
            if str(event.widget).startswith(str(self.win)):
                return
        except Exception:
            pass
        if event.widget is self.anchor:
            return
        self.anchor.after_idle(self.close)

    def _window_moved(self, _event=None) -> None:
        self.anchor.after_idle(self.close)

    def pick(self, color: str) -> None:
        self.close()
        self._on_pick(valid_color(color))

    def more_colors(self) -> None:
        current = self.current or PAPER_TEXT
        self.close()
        from tkinter import colorchooser

        try:
            _rgb, chosen = colorchooser.askcolor(color=current, parent=self.anchor.winfo_toplevel(), title="Schriftfarbe wählen")
        except tk.TclError:
            chosen = None
        if chosen:
            self._on_pick(valid_color(str(chosen)))

    def close(self) -> None:
        for hooks, hook in ((self.c.press_hooks, self._global_press), (self.c.window_hooks, self._window_moved)):
            if hook in hooks:
                hooks.remove(hook)
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self._on_close is not None:
            callback, self._on_close = self._on_close, None
            callback()


# ---------------------------------------------------------------------------
# Textfeld
# ---------------------------------------------------------------------------


class RichTextArea(_FieldBase):
    """Mehrzeiliges Textfeld mit Formatierung je Zeichen und Ausrichtung je Absatz."""

    def __init__(self, master, default: CharStyle, align: str = "left", lines: int = 4, width: int = 320, on_change: Callable[[], None] | None = None, on_state: Callable[[], None] | None = None) -> None:
        self.default = default
        self.default_align = align if align in ALIGNMENTS else "left"
        self._min_lines = max(2, lines)
        self._line_px = int(_pixels(default.size) * 1.3)
        height = self._min_lines * self._line_px + px(14)
        super().__init__(master, px(width), height)
        self._on_change = on_change
        self._on_state = on_state
        self.text = tk.Text(self, height=lines, wrap="word", undo=False, relief="flat", bd=0, highlightthickness=0, padx=0, pady=0, font=_tk_font(default), exportselection=True)
        fp = self._fp
        self._item = self.create_window(fp + px(11), fp + px(7), anchor="nw", window=self.text)
        self._tags: dict[CharStyle, str] = {}
        self._styles: dict[str, CharStyle] = {}
        for name, tag in ALIGN_TAGS.items():
            self.text.tag_configure(tag, justify=name)
        # Eingabeformat für neuen Text (gesetzt über die Leiste ohne Markierung)
        self.pending: CharStyle | None = None
        self._replaced: tuple[int, CharStyle] | None = None
        self._raw = False
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self._group: tuple | None = None
        self._state_job = None
        self._fit_job = None
        self._install_proxy()
        self.text.bind("<FocusIn>", lambda _e: self._set_focus(True), add="+")
        self.text.bind("<FocusOut>", lambda _e: self._set_focus(False), add="+")
        self.text.bind("<Tab>", self._tab, add="+")
        self.text.bind("<Shift-Tab>", self._shift_tab, add="+")
        self.text.bind("<<Selection>>", lambda _e: self._schedule_state(), add="+")
        self.text.bind("<Control-KeyPress>", self._control_key, add="+")
        self.text.bind("<Configure>", self._text_configured, add="+")
        self.bind("<Button-1>", lambda _e: self.text.focus_set(), add="+")
        self._bind_hover(self.text)
        self._text_width = 0
        self.redraw()
        self._layout()

    # Vermittler vor dem Tk-Befehl --------------------------------------------------------
    def _install_proxy(self) -> None:
        path = self.text._w
        self._orig = path + "_ue"
        tk_call = self.tk.call
        tk_call("rename", path, self._orig)
        edit = self.register(self._proxy_edit)
        moved = self.register(self._cursor_moved)

        def q(name: str) -> str:
            # Befehlsnamen als Tcl-Wort in geschweiften Klammern (Widgetpfade enthalten keine Klammern)
            return "{" + str(name) + "}"

        body = (
            "set op [lindex $args 0]\n"
            'if {$op eq "insert" || $op eq "delete" || $op eq "replace"} {\n'
            f"    set r [{q(edit)} {{*}}$args]\n"
            '    if {[string index $r 0] eq "E"} {return -code error [string range $r 1 end]}\n'
            "    return [string range $r 1 end]\n"
            "}\n"
            f"set r [{q(self._orig)} {{*}}$args]\n"
            f'if {{$op eq "mark" && [lindex $args 1] eq "set" && [lindex $args 2] eq "insert"}} {{{q(moved)}}}\n'
            "return $r\n"
        )
        tk_call("proc", path, "args", body)
        self.text.bind("<Destroy>", self._remove_proxy, add="+")

    def _remove_proxy(self, event) -> None:
        if event.widget is self.text:
            try:
                self.tk.call("rename", self.text._w, "")
            except tk.TclError:
                pass

    def _tk(self, *args):
        return self.tk.call(self._orig, *args)

    def _proxy_edit(self, *args) -> str:
        op = args[0]
        try:
            if op == "insert":
                result = self._do_insert(args[1:])
            elif op == "delete":
                result = self._do_delete(args[1:])
            else:
                result = self._do_replace(args[1:])
            return "R" + ("" if result is None else str(result))
        except tk.TclError as exc:
            return "E" + str(exc)
        except Exception:  # noqa: BLE001 - Eingaben dürfen nie verloren gehen
            traceback.print_exc()
            try:
                return "R" + str(self._tk(op, *args[1:]) or "")
            except tk.TclError as exc:
                return "E" + str(exc)

    # Positionen ----------------------------------------------------------------------------
    @staticmethod
    def _index(offset: int) -> str:
        return f"1.0 + {max(0, int(offset))} chars"

    def _offset(self, index: str) -> int:
        value = self._tk("count", "-chars", "1.0", index)
        if isinstance(value, tuple):
            value = value[0] if value else 0
        return int(value or 0)

    def _length(self) -> int:
        return self._offset("end-1c")

    def _line_of(self, index: str) -> int:
        return int(str(self._tk("index", index)).split(".")[0])

    def _last_line(self) -> int:
        return self._line_of("end-1c")

    def cursor(self) -> int:
        return self._offset("insert")

    def selection(self) -> tuple[int, int] | None:
        ranges = self._tk("tag", "ranges", "sel")
        if not ranges:
            return None
        start, end = self._offset(str(ranges[0])), self._offset(str(ranges[-1]))
        return (start, end) if end > start else None

    # Formate --------------------------------------------------------------------------------
    def _tag_for(self, style: CharStyle) -> str:
        tag = self._tags.get(style)
        if tag is None:
            tag = f"cs{len(self._tags)}"
            self._tags[style] = tag
            self._styles[tag] = style
            self._tk("tag", "configure", tag, "-font", _tk_font(style), "-foreground", style.color, "-underline", int(style.underline), "-overstrike", int(style.strike))
            self._tk("tag", "raise", "sel")
        return tag

    def _style_from_tags(self, names: Iterable[str]) -> CharStyle:
        for name in names:
            style = self._styles.get(str(name))
            if style is not None:
                return style
        return self.default

    def style_at(self, offset: int) -> CharStyle:
        return self._style_from_tags(self._tk("tag", "names", self._index(offset)))

    def _char(self, offset: int) -> str:
        return str(self._tk("get", self._index(offset)))

    def insert_style(self, offset: int) -> CharStyle:
        """Format für an ``offset`` eingegebenen Text: das Zeichen davor, am Absatzanfang das danach."""
        if self.pending is not None:
            return self.pending
        if self._replaced is not None and self._replaced[0] == offset:
            return self._replaced[1]
        length = self._length()
        if offset > 0 and self._char(offset - 1) != "\n":
            return self.style_at(offset - 1)
        if offset < length:
            return self.style_at(offset)
        if offset > 0:
            return self.style_at(offset - 1)
        return self.default

    def styles_in(self, start: int, end: int) -> set[CharStyle]:
        found: set[CharStyle] = set()
        active: set[str] = {str(n) for n in self._tk("tag", "names", self._index(start))}
        for key, value, _index in self._dump(self._index(start), self._index(end)):
            if key == "tagon":
                active.add(value)
            elif key == "tagoff":
                active.discard(value)
            elif key == "text" and value:
                found.add(self._style_from_tags(active))
        return found or {self.style_at(start)}

    def _dump(self, start: str, end: str) -> list[tuple[str, str, str]]:
        raw = self._tk("dump", "-text", "-tag", start, end)
        if isinstance(raw, str):
            raw = self.tk.splitlist(raw)
        items = list(raw)
        return [(str(items[i]), str(items[i + 1]), str(items[i + 2])) for i in range(0, len(items) - 2, 3)]

    def line_align(self, line: int) -> str:
        for name in self._tk("tag", "names", f"{line}.0"):
            if str(name).startswith("al-"):
                return str(name)[3:]
        return self.default_align

    def _apply_line_align(self, line: int, align: str) -> None:
        start, end = f"{line}.0", f"{line}.0 lineend + 1c"
        for tag in ALIGN_TAGS.values():
            self._tk("tag", "remove", tag, start, end)
        self._tk("tag", "add", ALIGN_TAGS.get(align, ALIGN_TAGS[self.default_align]), start, end)

    def _normalize_lines(self, first: int, last: int) -> None:
        """Jeder Absatz hat genau eine Ausrichtung – die seines ersten Zeichens."""
        for line in range(max(1, first), min(last, self._last_line()) + 1):
            self._apply_line_align(line, self.line_align(line))

    # Bearbeiten (vom Vermittler) --------------------------------------------------------------
    def _do_insert(self, args: tuple):
        index = args[0]
        chars = "".join(str(piece) for piece in args[1::2])
        if self._raw or not chars:
            return self._tk("insert", *args)
        offset = self._offset(index)
        style = self.insert_style(offset)
        self._record("type" if len(chars) == 1 and chars != "\n" else "insert", offset, len(chars))
        line = self._line_of(index)
        align = self.line_align(line)
        self._tk("insert", index, chars, (self._tag_for(style), ALIGN_TAGS[align]))
        self._replaced = None
        if "\n" in chars:
            self._normalize_lines(line, line + chars.count("\n"))
        self._changed()
        return ""

    def _do_delete(self, args: tuple):
        if self._raw:
            return self._tk("delete", *args)
        if len(args) > 2:  # mehrere Bereiche: einzeln löschen (selten, nur aus Skripten)
            for pair in range(len(args) - 2, -1, -2):
                self._do_delete(args[pair : pair + 2])
            return ""
        start = self._offset(args[0])
        end = self._offset(args[1]) if len(args) > 1 else start + 1
        end = min(end, self._length())
        if end <= start:
            return ""
        removed = str(self._tk("get", self._index(start), self._index(end)))
        style = self.style_at(start)
        cursor = self.cursor()
        kind = "back" if end - start == 1 and cursor == end else "del" if end - start == 1 else "cut"
        self._record(kind, start, end - start)
        line = self._line_of(self._index(start))
        self._tk("delete", self._index(start), self._index(end))
        # Überschreibt der Nutzer eine Markierung, erhält der neue Text deren Format.
        self._replaced = (start, style)
        if "\n" in removed:
            self._normalize_lines(line, line)
        self._changed()
        return ""

    def _do_replace(self, args: tuple):
        if self._raw:
            return self._tk("replace", *args)
        start = self._offset(args[0])
        end = self._offset(args[1])
        style = self.style_at(start) if end > start else self.insert_style(start)
        chars = "".join(str(piece) for piece in args[2::2])  # replace i1 i2 text ?tags text tags …?
        self._record("cut", start, end - start)
        line = self._line_of(self._index(start))
        align = self.line_align(line)
        self._tk("delete", self._index(start), self._index(end))
        if chars:
            self._tk("insert", self._index(start), chars, (self._tag_for(style), ALIGN_TAGS[align]))
        self._normalize_lines(line, line + chars.count("\n"))
        self._changed()
        return ""

    def _cursor_moved(self) -> None:
        # Cursor bewegt: Das zuvor gewählte Eingabeformat gilt nicht mehr.
        if self.pending is not None:
            self.pending = None
        self._replaced = None
        self._group = None
        self._schedule_state()

    # Rückgängig ---------------------------------------------------------------------------------
    def _snapshot(self) -> tuple:
        return (self.get_rich(), self.cursor(), self.selection())

    def _record(self, kind: str, offset: int, count: int) -> None:
        now = time.monotonic()
        group = self._group
        if group is not None and now - group[2] < TYPING_PAUSE:
            last_kind, last_pos = group[0], group[1]
            if kind == "type" == last_kind and offset == last_pos:
                self._group = (kind, offset + count, now)
                return
            if kind == "back" == last_kind and offset + count == last_pos:
                self._group = (kind, offset, now)
                return
            if kind == "del" == last_kind and offset == last_pos:
                self._group = (kind, offset, now)
                return
        self.push_undo()
        end = offset + count if kind == "type" else offset
        self._group = (kind, end, now) if kind in ("type", "back", "del") else None

    def push_undo(self) -> None:
        self._undo.append(self._snapshot())
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self._group = None

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        return True

    def _restore(self, state: tuple) -> None:
        rich, cursor, selection = state
        self._load(rich)
        self._tk("mark", "set", "insert", self._index(cursor))
        if selection:
            self._tk("tag", "add", "sel", self._index(selection[0]), self._index(selection[1]))
        self._tk("see", "insert")
        self.pending = None
        self._replaced = None
        self._group = None
        self._changed()

    # Laden und Lesen ---------------------------------------------------------------------------
    def _load(self, rich: RichText) -> None:
        self._raw = True
        try:
            self._tk("delete", "1.0", "end")
            for start, end, style in rich.runs():
                self._tk("insert", "end-1c", rich.text[start:end], (self._tag_for(style),))
            for line, (_s, _e, align) in enumerate(rich.paragraphs(), start=1):
                self._apply_line_align(line, align)
            self._tk("tag", "remove", "sel", "1.0", "end")
        finally:
            self._raw = False

    def get_rich(self) -> RichText:
        text = str(self._tk("get", "1.0", "end-1c"))
        styles: list[CharStyle] = []
        active: set[str] = {str(n) for n in self._tk("tag", "names", "1.0")}
        for key, value, _index in self._dump("1.0", "end-1c"):
            if key == "tagon":
                active.add(value)
            elif key == "tagoff":
                active.discard(value)
            elif key == "text":
                styles.extend([self._style_from_tags(active)] * len(value))
        aligns = [self.line_align(line) for line in range(1, text.count("\n") + 2)]
        return RichText(text, styles, aligns, self.default, self.default_align)

    def set_rich(self, rich: RichText) -> None:
        """Inhalt setzen (z. B. beim Laden); leert den Rückgängig-Verlauf."""
        self._load(rich)
        self._tk("mark", "set", "insert", "1.0")
        self._undo.clear()
        self._redo.clear()
        self.pending = None
        self._group = None
        self._schedule_state()
        self._schedule_fit()

    def replace_rich(self, rich: RichText) -> None:
        """Inhalt ersetzen – mit Strg+Z in einem Schritt rückgängig zu machen."""
        self.push_undo()
        self._load(rich)
        self._tk("mark", "set", "insert", "1.0")
        self.pending = None
        self._changed()

    def get(self) -> str:
        return str(self._tk("get", "1.0", "end-1c"))

    # Formatieren ----------------------------------------------------------------------------------
    def _runs(self, start: int, end: int) -> list[tuple[int, int, CharStyle]]:
        rich = self.get_rich()
        return rich.runs(start, end)

    def format_range(self, start: int, end: int, change: Callable[[CharStyle], CharStyle]) -> None:
        self.push_undo()
        for s, e, style in self._runs(start, end):
            new = change(style)
            if new != style:
                self._tk("tag", "remove", self._tag_for(style), self._index(s), self._index(e))
                self._tk("tag", "add", self._tag_for(new), self._index(s), self._index(e))
        self._changed()

    def apply(self, change: Callable[[CharStyle], CharStyle]) -> None:
        """Format ändern: markierter Text – oder ohne Markierung das Eingabeformat."""
        selection = self.selection()
        if selection is None:
            self.pending = change(self.insert_style(self.cursor()))
            self._schedule_state()
            return
        self.format_range(selection[0], selection[1], change)

    def set_alignment(self, align: str) -> None:
        if align not in ALIGNMENTS:
            return
        selection = self.selection()
        if selection is None:
            first = last = self._line_of("insert")
        else:
            first = self._line_of(self._index(selection[0]))
            last = self._line_of(self._index(max(selection[0], selection[1] - 1)))
        if all(self.line_align(line) == align for line in range(first, last + 1)):
            return
        self.push_undo()
        for line in range(first, last + 1):
            self._apply_line_align(line, align)
        self._changed()

    def current(self) -> tuple[set[CharStyle], set[str]]:
        """Formate und Ausrichtungen an Cursor bzw. Markierung (für die Leiste)."""
        selection = self.selection()
        if selection is None:
            offset = self.cursor()
            line = self._line_of("insert")
            return {self.insert_style(offset)}, {self.line_align(line)}
        first = self._line_of(self._index(selection[0]))
        last = self._line_of(self._index(max(selection[0], selection[1] - 1)))
        return self.styles_in(*selection), {self.line_align(line) for line in range(first, last + 1)}

    # Rückmeldungen ----------------------------------------------------------------------------------
    def _changed(self) -> None:
        self._schedule_state()
        self._schedule_fit()
        if self._on_change is not None:
            self._on_change()

    def _schedule_state(self) -> None:
        if self._state_job is None and self._on_state is not None:
            self._state_job = self.after_idle(self._run_state)

    def _run_state(self) -> None:
        self._state_job = None
        if self._on_state is not None:
            try:
                self._on_state()
            except tk.TclError:
                pass

    def _schedule_fit(self) -> None:
        if self._fit_job is None:
            self._fit_job = self.after_idle(self._fit_height)

    def _fit_height(self) -> None:
        """Feldhöhe an den Inhalt anpassen (mindestens ``lines``, höchstens ``MAX_LINES`` Zeilen)."""
        self._fit_job = None
        try:
            content = self._tk("count", "-update", "-ypixels", "1.0", "end")
        except tk.TclError:
            return
        if isinstance(content, tuple):
            content = content[0] if content else 0
        content = int(content or 0)
        fp = self._fp
        minimum = self._min_lines * self._line_px
        maximum = MAX_LINES * self._line_px
        inner = max(minimum, min(maximum, content + px(4)))
        height = inner + px(14) + 2 * fp
        if abs(int(self.cget("height")) - height) > 2:
            self.configure(height=height)

    def _text_configured(self, event) -> None:
        if event.width != self._text_width:
            self._text_width = event.width
            ctx().after_resize(f"richfit:{self}", self._schedule_fit)

    # Tastatur -----------------------------------------------------------------------------------------
    def _tab(self, _event=None):
        self.text.tk_focusNext().focus_set()
        return "break"

    def _shift_tab(self, _event=None):
        self.text.tk_focusPrev().focus_set()
        return "break"

    def _control_key(self, event):
        key = str(event.keysym).lower()
        shift = bool(int(event.state) & 0x1)
        editor = getattr(self, "editor", None)
        actions = {
            "b": lambda: editor.toggle("bold"),
            "i": lambda: editor.toggle("italic"),
            "u": lambda: editor.toggle("underline"),
            "l": lambda: editor.align("left"),
            "e": lambda: editor.align("center"),
            "r": lambda: editor.align("right"),
        } if editor is not None else {}
        if key == "z":
            self.redo() if shift else self.undo()
            return "break"
        if key == "y":
            self.redo()
            return "break"
        if key == "a":
            self._tk("tag", "add", "sel", "1.0", "end-1c")
            self._tk("mark", "set", "insert", "end-1c")
            self._schedule_state()
            return "break"
        if key in actions:
            actions[key]()
            return "break"
        if key in ("o", "return", "kp_enter"):
            # Tastenkürzel der App (Excel öffnen, PDF erstellen) – ohne Zeilenumbruch im Text
            sequence = "<Control-o>" if key == "o" else "<Control-Return>"
            self.after_idle(lambda: self.winfo_toplevel().event_generate(sequence))
            return "break"
        return None

    # Darstellung -------------------------------------------------------------------------------------
    def fill_color(self) -> str:
        if not self._enabled:
            return self.c.pal.control_disabled
        return PAPER

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
        self.text.configure(
            bg=fill,
            fg=PAPER_TEXT,
            insertbackground="#000000",
            selectbackground=pal.accent if not pal.dark else mix(pal.accent, "#000000", 0.35),
            selectforeground="#FFFFFF",
            inactiveselectbackground="#D6D6D6",
        )


# ---------------------------------------------------------------------------
# Editor: Leiste + Textfeld
# ---------------------------------------------------------------------------


class RichTextEditor(tk.Frame):
    """Rich-Text-Feld mit Formatierungsleiste für Kopf- und Fußzeile."""

    def __init__(self, master, default: CharStyle, align: str = "left", lines: int = 4, on_change: Callable[[], None] | None = None) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = surface_of(master)
        c = ctx()
        c.theme.style(self, bg=self.surface_role)
        self.default = default
        self.default_align = align
        self._on_change = on_change
        self._flyout: ColorFlyout | None = None
        self.families = font_families()

        bar = FlowRow(self, gap=6, row_gap=6)
        bar.pack(fill="x", pady=(0, px(8)))
        self.toolbar = bar
        self.font_combo = ComboBox(bar, self.families, command=self._font_chosen, placeholder="Schriftart", width=150, tooltip="Schriftart")
        bar.add(self.font_combo)
        self.size_combo = ComboBox(bar, [str(size) for size in FONT_SIZES], command=self._size_chosen, placeholder="Größe", width=72, tooltip="Schriftgröße (pt)")
        bar.add(self.size_combo)

        family = c.fonts.families.get("text") or "TkDefaultFont"
        size = -px(15)
        # Die Buchstaben zeigen ihre Wirkung selbst: B fett, I kursiv, U unterstrichen, S durchgestrichen.
        self._glyph_fonts = {
            "bold": tkfont.Font(root=self, family=family, size=size, weight="bold"),
            "italic": tkfont.Font(root=self, family=family, size=size, slant="italic"),
            "underline": tkfont.Font(root=self, family=family, size=size, underline=True),
            "strike": tkfont.Font(root=self, family=family, size=size, overstrike=True),
        }
        group = frame(bar)
        self.btn_bold = FormatToggle(group, "B", lambda: self.toggle("bold"), "Fett (Strg+B)", font=self._glyph_fonts["bold"])
        self.btn_italic = FormatToggle(group, "I", lambda: self.toggle("italic"), "Kursiv (Strg+I)", font=self._glyph_fonts["italic"])
        self.btn_underline = FormatToggle(group, "U", lambda: self.toggle("underline"), "Unterstrichen (Strg+U)", font=self._glyph_fonts["underline"])
        self.btn_strike = FormatToggle(group, "S", lambda: self.toggle("strike"), "Durchgestrichen", font=self._glyph_fonts["strike"])
        for button in (self.btn_bold, self.btn_italic, self.btn_underline, self.btn_strike):
            button.pack(side="left", padx=(0, px(2)))
        bar.add(group)
        self.color_button = ColorButton(bar, self.open_colors)
        bar.add(self.color_button)
        self.color_button.bind("<KeyPress-Left>", lambda _e: self._flyout_key(-1), add="+")
        self.color_button.bind("<KeyPress-Right>", lambda _e: self._flyout_key(1), add="+")
        self.color_button.bind("<KeyPress-Escape>", lambda _e: self._close_flyout(), add="+")
        align_group = frame(bar)
        glyphs = {"left": icons.ALIGN_LEFT, "center": icons.ALIGN_CENTER, "right": icons.ALIGN_RIGHT}
        fallback = {"left": "⇤", "center": "↔", "right": "⇥"}
        self.align_buttons: dict[str, FormatToggle] = {}
        for name in ALIGNMENTS:
            button = FormatToggle(align_group, command=lambda n=name: self.align(n), tooltip=ALIGN_LABELS[name], icon=glyphs[name], fallback=fallback[name])
            button.pack(side="left", padx=(0, px(2)))
            self.align_buttons[name] = button
        bar.add(align_group)

        self.area = RichTextArea(self, default, align, lines=lines, on_change=self._changed, on_state=self.refresh_toolbar)
        self.area.editor = self  # type: ignore[attr-defined]
        self.area.pack(fill="x")
        self.text = self.area.text
        self.refresh_toolbar()

    # Öffentliche API ------------------------------------------------------------------------------
    def get(self) -> str:
        return self.area.get()

    def get_rich(self) -> RichText:
        return self.area.get_rich()

    def set_rich(self, rich: RichText) -> None:
        self.area.set_rich(rich)
        self.refresh_toolbar()

    def replace_rich(self, rich: RichText) -> None:
        self.area.replace_rich(rich)

    def set(self, value: str) -> None:
        self.set_rich(RichText.plain(value, self.default, self.default_align))

    def replace(self, value: str) -> None:
        self.replace_rich(RichText.plain(value, self.default, self.default_align))

    def undo(self) -> bool:
        return self.area.undo()

    def redo(self) -> bool:
        return self.area.redo()

    # Befehle der Leiste ----------------------------------------------------------------------------
    def toggle(self, attribute: str) -> None:
        styles, _aligns = self.area.current()
        turn_on = not all(getattr(style, attribute) for style in styles)
        self.area.apply(lambda style: style.with_(**{attribute: turn_on}))
        self._refocus()

    def align(self, name: str) -> None:
        self.area.set_alignment(name)
        self.refresh_toolbar()
        self._refocus()

    def set_font(self, family: str) -> None:
        if family:
            self.area.apply(lambda style: style.with_(font=family))
        self._refocus()

    def set_size(self, size) -> None:
        value = valid_size(size, 0)
        if value:
            self.area.apply(lambda style: style.with_(size=value))
        self._refocus()

    def set_color(self, color: str) -> None:
        value = valid_color(color, "")
        if value:
            self.area.apply(lambda style: style.with_(color=value))
        self._refocus()

    def open_colors(self) -> None:
        if self._flyout is not None:
            # Tastatur: Eingabe übernimmt die gewählte Farbe; Maus: erneuter Klick schließt.
            if ctx().keyboard_mode:
                self._flyout.choose_current()
            else:
                self._flyout.close()
            return
        styles, _aligns = self.area.current()
        colors = {style.color for style in styles}
        current = next(iter(colors)) if len(colors) == 1 else None

        def closed() -> None:
            self._flyout = None

        self._flyout = ColorFlyout(self.color_button, current, self.set_color, on_close=closed)

    def _flyout_key(self, delta: int):
        if self._flyout is None:
            return None
        self._flyout.step(delta)
        return "break"

    def _close_flyout(self):
        if self._flyout is None:
            return None
        self._flyout.close()
        return "break"

    def _font_chosen(self, family: str) -> None:
        self.set_font(family)

    def _size_chosen(self, value: str) -> None:
        self.set_size(value)

    def _refocus(self) -> None:
        try:
            self.text.focus_set()
        except tk.TclError:
            pass
        self.refresh_toolbar()

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    # Zustand der Leiste ----------------------------------------------------------------------------
    def refresh_toolbar(self) -> None:
        try:
            styles, aligns = self.area.current()
        except tk.TclError:
            return

        def common(attribute: str):
            values = {getattr(style, attribute) for style in styles}
            return next(iter(values)) if len(values) == 1 else None

        self.btn_bold.set_state(common("bold"))
        self.btn_italic.set_state(common("italic"))
        self.btn_underline.set_state(common("underline"))
        self.btn_strike.set_state(common("strike"))
        font = common("font")
        if self.font_combo.get() != (font or ""):
            if font and font not in self.font_combo.values():
                self.font_combo.set_values(self.families + [font], keep=False)
            self.font_combo.set(font)
        size = common("size")
        size_label = size_text(size) if size is not None else ""
        if self.size_combo.get() != size_label:
            if size_label and size_label not in self.size_combo.values():
                values = sorted({*(float(v) for v in self.size_combo.values()), float(size)})
                self.size_combo.set_values([size_text(v) for v in values], keep=False)
            self.size_combo.set(size_label or None)
        self.color_button.set_color(common("color"))
        single = next(iter(aligns)) if len(aligns) == 1 else None
        for name, button in self.align_buttons.items():
            button.set_state(True if single == name else False)
