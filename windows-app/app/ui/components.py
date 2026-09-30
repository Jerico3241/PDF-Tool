"""Zusammengesetzte Bausteine für die Seiten: Einstellungskarten, Dateizeilen, Formularfelder."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

from . import icons
from .context import bind_size, ctx, surface_color, surface_of
from .inputs import elide_middle
from .theme import px
from .widgets import Card, Icon, RingSpinner, RoundedFrame, Text, frame


def field_label(master, text: str, first: bool = False) -> Text:
    label = Text(master, text, style="body")
    label.pack(anchor="w", pady=(0 if first else px(12), px(4)))
    return label


class SettingsCard(RoundedFrame):
    """Karte wie in den Windows-11-Einstellungen: Symbol, Titel, Beschreibung, Steuerelement rechts."""

    def __init__(self, master, icon: str | None, title: str, description: str | None = None) -> None:
        super().__init__(master, fill="card", stroke="card_stroke")
        c = ctx()
        self.row = frame(self)
        self.row.pack(fill="x", padx=px(16), pady=px(12))
        if icon and c.icons_available:
            Icon(self.row, icon, color="text", size="icon_large").pack(side="left", padx=(px(2), px(16)))
        texts = frame(self.row)
        texts.pack(side="left", fill="x", expand=True)
        self.title = Text(texts, title, style="body")
        self.title.pack(anchor="w")
        self.description = None
        if description:
            self.description = Text(texts, description, style="caption", color="text2", wrap=True)
            self.description.pack(anchor="w", fill="x")
        self.control = frame(self.row)
        self.control.pack(side="right", padx=(px(16), 0))
        self.extra = frame(self)
        self.lift_corners()

    def set_description(self, text: str) -> None:
        if self.description is not None:
            self.description.configure(text=text)

    def show_extra(self) -> tk.Frame:
        self.extra.pack(fill="x", padx=px(16), pady=(0, px(14)))
        self.lift_corners()
        return self.extra


class FileRow(tk.Frame):
    """Zeile »Symbol · Bezeichnung · Dateiname« mit Schaltflächen rechts."""

    def __init__(self, master, icon: str, title: str) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = surface_of(master, "card")
        c = ctx()
        c.theme.style(self, bg=self.surface_role)
        if c.icons_available:
            Icon(self, icon, color="text2", size="icon_large").pack(side="left", anchor="n", padx=(0, px(12)), pady=(px(6), 0))
        texts = frame(self)
        texts.pack(side="left", fill="x", expand=True)
        Text(texts, title, style="body").pack(anchor="w")
        # width=1: Der Dateiname bestimmt nicht die Breite der Zeile. Sonst würde jede
        # Kürzung das Layout ändern und damit eine neue Kürzung auslösen.
        self.value = Text(texts, "", style="caption", color="text2", width=1)
        self.value.pack(anchor="w", fill="x")
        self._full = ""
        self._value_width = 0
        bind_size(self.value, self._value_configured)
        self.buttons = frame(self)
        self.buttons.pack(side="right", anchor="center", padx=(px(8), 0))
        self._tip = None

    def set_value(self, text: str, full: str | None = None) -> None:
        self._full = text
        self._render()
        from .widgets import Tooltip

        if full:
            if self._tip is None:
                self._tip = Tooltip(self.value, full)
            self._tip.text = full

    def _value_configured(self, event) -> None:
        if event.width != self._value_width:
            self._value_width = event.width
            self._render()

    def _render(self) -> None:
        width = self.value.winfo_width()
        text = self._full
        if width > 20:
            text = elide_middle(ctx().fonts.caption, text, width - px(4))
        if self.value.cget("text") != text:
            self.value.configure(text=text)


class FactList(tk.Frame):
    """Kompakte Zeilen »Bezeichnung  Wert« – z. B. das Ergebnis der Excel-Prüfung.

    ``tone`` färbt den Wert: "" (normal), "success", "caution", "critical", "muted".
    Neu aufgebaut wird nur, wenn sich die Angaben tatsächlich ändern.
    """

    TONES = {"": "text", "success": "success", "caution": "caution", "critical": "critical", "muted": "text2"}

    def __init__(self, master, label_width: int = 150) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = surface_of(master)
        ctx().theme.style(self, bg=self.surface_role)
        self._label_width = px(label_width)
        self._facts: list[tuple[str, str, str]] = []
        self.columnconfigure(1, weight=1)

    def facts(self) -> list[tuple[str, str, str]]:
        return list(self._facts)

    def set(self, facts: list[tuple[str, str, str]]) -> None:
        facts = [(str(label), str(value), tone if tone in self.TONES else "") for label, value, tone in facts]
        if facts == self._facts:
            return
        self._facts = facts
        for child in self.winfo_children():
            child.destroy()
        for row, (label, value, tone) in enumerate(facts):
            pad = (0 if row == 0 else px(4), 0)
            # Beschriftung (12 px) auf die Grundlinie des Werts (14 px) ausrichten
            label_pad = (pad[0] + px(2), 0)
            Text(self, label, style="caption", color="text2").grid(row=row, column=0, sticky="nw", padx=(0, px(12)), pady=label_pad)
            value_label = Text(self, value, style="body", color=self.TONES[tone], wrap=True, width=1)
            value_label.grid(row=row, column=1, sticky="ew", pady=pad)
        self.columnconfigure(0, minsize=self._label_width if facts else 0)


class StatusLine(tk.Frame):
    """Zustandsanzeige mit Symbol, z. B. »Bereit zum Erstellen« (Erfolg) oder was noch fehlt.

    ``kind``: "success", "caution", "critical", "busy" oder "neutral". Ein Klick
    ruft ``command`` auf (z. B. zum Feld springen, das noch fehlt).
    """

    def __init__(self, master, command: Callable[[], None] | None = None) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = surface_of(master)
        c = ctx()
        c.theme.style(self, bg=self.surface_role)
        self._command = command
        self.kind = "neutral"
        self.text = ""
        size = px(20)
        self._icon = tk.Canvas(self, width=size, height=size, highlightthickness=0, bd=0)
        self._icon.pack(side="left", padx=(0, px(10)))
        self._icon_bg = self._icon.create_image(size / 2, size / 2, anchor="center")
        self._icon_glyph = self._icon.create_text(size / 2, size / 2, text="", anchor="center")
        self._icon_img = None
        self._spinner = None
        # width=1 und Umbruch: Lange Texte brechen um, statt abgeschnitten zu werden – und die
        # Beschriftung bestimmt nie die Breite der Zeile (keine Rückkopplung beim Umbruch).
        self._label = Text(self, "", style="body_strong", wrap=True, width=1)
        self._label.pack(side="left", fill="x", expand=True)
        for widget in (self, self._icon, self._label):
            widget.bind("<Button-1>", self._clicked, add="+")
        c.theme.subscribe(self._repaint, owner=self)
        self._repaint()

    def _clicked(self, _event=None) -> None:
        if self._command is not None and self.kind in ("caution", "critical"):
            self._command()

    def set(self, kind: str, text: str) -> None:
        if (kind, text) == (self.kind, self.text):
            return
        self.kind = kind
        self.text = text
        self._label.configure(text=text)
        self._repaint()

    def _repaint(self) -> None:
        c = ctx()
        pal = c.pal
        surface = surface_color(self)
        self._icon.configure(bg=surface)
        colors = {
            "success": (pal.success, pal.on_status, icons.CHECK_MARK, "✓"),
            "caution": (pal.caution, "#000000", "!", "!"),
            "critical": (pal.critical, pal.on_status, icons.CANCEL, "×"),
            "neutral": (pal.neutral, pal.on_status, "i", "i"),
            "busy": (None, None, "", ""),
        }
        fill, glyph_color, glyph, fallback = colors.get(self.kind, colors["neutral"])
        size = px(20)
        if self.kind == "busy":
            if self._spinner is None:
                self._spinner = RingSpinner(self._icon, px(16))
            self._icon.itemconfigure(self._icon_bg, state="hidden")
            self._icon.itemconfigure(self._icon_glyph, text="")
            self._spinner.place(size / 2, size / 2, pal.accent, surface)
            self._spinner.start()
        else:
            if self._spinner is not None:
                self._spinner.stop()
            img = c.images.circle(px(16), fill, background=surface)
            self._icon_img = img
            self._icon.itemconfigure(self._icon_bg, image=img, state="normal")
            is_icon = glyph not in ("!", "i") and c.icons_available
            if is_icon:
                font = (c.fonts.families["icons"], -max(6, px(9)))
            else:
                glyph = fallback if glyph not in ("!", "i") else glyph
                font = (c.fonts.families.get("text_semibold") or c.fonts.families["text"], -px(11), "bold")
            self._icon.itemconfigure(self._icon_glyph, text=glyph, fill=glyph_color, font=font)
        role = {"success": "text", "caution": "text", "critical": "critical", "busy": "text2", "neutral": "text2"}.get(self.kind, "text")
        self._label.set_color(role)
        self.configure(cursor="hand2" if self._command is not None and self.kind in ("caution", "critical") else "")


def path_caption(path: str, empty: str) -> tuple[str, str]:
    if not path:
        return empty, ""
    p = Path(path)
    parent = p.parent.name or str(p.parent)
    if p.suffix:
        return f"{p.name}  ·  {parent}", str(p)
    return (p.name or str(p)), str(p)


class ResponsiveColumns(tk.Frame):
    """Zwei Bereiche nebeneinander bei ausreichender Breite, sonst untereinander.

    ``central=True``: folgt dem zentral berechneten Layoutzustand des Fensters
    (``ctx().layout.columns``). Sonst entscheidet die eigene Breite – mit
    Hysterese, damit kleine Bewegungen am Breakpoint kein Hin- und Herspringen
    auslösen. Umgestellt wird nur, wenn ein Breakpoint tatsächlich überschritten ist.
    """

    HYSTERESIS = 12

    def __init__(self, master, breakpoint: int = 780, gap: int = 12, central: bool = False) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = surface_of(master)
        ctx().theme.style(self, bg=self.surface_role)
        self._breakpoint = px(breakpoint)
        self._hysteresis = px(self.HYSTERESIS)
        self._gap = px(gap)
        self._children: list[tk.Widget] = []
        self._wide: bool | None = None
        self._central = central
        if central:
            ctx().layout.subscribe(self._layout, owner=self)
        else:
            bind_size(self, self._configured)

    def add(self, widget: tk.Widget) -> tk.Widget:
        self._children.append(widget)
        self._wide = None
        self._layout()
        return widget

    def _configured(self, event) -> None:
        if event.width > 1:
            self._layout()

    def _want_wide(self) -> bool:
        if self._central:
            return ctx().layout.columns >= 2
        width = self.winfo_width()
        if width <= 1:
            return True if self._wide is None else self._wide
        if self._wide is None:
            return width >= self._breakpoint
        if self._wide:
            return width >= self._breakpoint - self._hysteresis
        return width >= self._breakpoint

    def _layout(self, _event=None) -> None:
        wide = self._want_wide()
        if wide == self._wide:
            return
        self._wide = wide
        for index, child in enumerate(self._children):
            if wide:
                pad = (0, self._gap // 2) if index == 0 else (self._gap // 2, 0)
                options = {"row": 0, "column": index, "padx": pad, "pady": 0}
            else:
                options = {"row": index, "column": 0, "padx": 0, "pady": (0 if index == 0 else self._gap, 0)}
            # grid_configure verschiebt die Karte, ohne sie samt Inhalt ab- und wieder
            # einzublenden (das würde den ganzen Widget-Baum neu abbilden und zeichnen).
            child.grid_configure(sticky="nsew", **options)
        for column in range(max(2, len(self._children))):
            self.columnconfigure(column, weight=1 if (wide or column == 0) else 0, uniform="cols" if wide else "")
        self.rowconfigure(0, weight=1)


def card(master, title: str, icon: str | None = None, description: str | None = None) -> Card:
    return Card(master, title=title, icon=icon, description=description)


class SelectorBar(tk.Canvas):
    """Umschalter zwischen Ansichten einer Seite (WinUI 3 »SelectorBar«).

    Textelemente mit Hover-Fläche; das gewählte Element trägt einen kurzen Balken in
    Akzentfarbe. Bedienbar mit Maus sowie Pfeiltasten, Eingabe und Leertaste.
    """

    ITEM_HEIGHT = 36
    PAD = 12

    def __init__(self, master, items: list[tuple[str, str]], selected: str, command: Callable[[str], None]) -> None:
        c = ctx()
        super().__init__(master, height=px(self.ITEM_HEIGHT) + px(4), highlightthickness=0, bd=0, takefocus=1)
        self.surface_role = surface_of(master)
        self.items = list(items)
        self.selected = selected
        self.command = command
        self.hover: str | None = None
        self.pressed: str | None = None
        self.focus_key = selected
        self.hidden: frozenset[str] = frozenset()  # ausgeblendete Elemente (z. B. ausgeschaltetes Modul)
        self._texts = {key: self.create_text(0, 0, text=label, anchor="center") for key, label in self.items}
        self._overlays = {key: self.create_image(0, 0, anchor="nw", state="hidden") for key, _label in self.items}
        self._pill = self.create_image(0, 0, anchor="n", state="hidden")
        self._focus = self.create_image(0, 0, anchor="nw", state="hidden")
        self._rects: dict[str, tuple[int, int, int, int]] = {}
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<FocusIn>", lambda _e: self.redraw())
        self.bind("<FocusOut>", lambda _e: self.redraw())
        for key, delta in (("Left", -1), ("Right", 1)):
            self.bind(f"<KeyPress-{key}>", lambda _e, d=delta: self._move(d))
        for key in ("Return", "space", "KP_Enter"):
            self.bind(f"<KeyPress-{key}>", lambda _e: self._activate(self.focus_key))
        c.theme.subscribe(self.redraw, owner=self)
        c.on_focus_mode(self, self.redraw)
        self._layout()
        self.redraw()

    def _layout(self) -> None:
        font = ctx().fonts.body
        x = 0
        self._rects = {}
        for key, label in self.items:
            if key in self.hidden:
                continue
            width = font.measure(label) + 2 * px(self.PAD)
            self._rects[key] = (x, px(2), x + width, px(2) + px(self.ITEM_HEIGHT))
            x += width + px(4)
        self.configure(width=max(1, x - px(4)))

    def _hit(self, x: int, y: int) -> str | None:
        for key, (x0, y0, x1, y1) in self._rects.items():
            if x0 <= x < x1 and y0 <= y < y1:
                return key
        return None

    def _motion(self, event) -> None:
        key = self._hit(event.x, event.y)
        if key != self.hover:
            self.hover = key
            self.configure(cursor="hand2" if key else "")
            self.redraw()

    def _leave(self, _event=None) -> None:
        self.hover = self.pressed = None
        self.redraw()

    def _press(self, event) -> None:
        self.pressed = self._hit(event.x, event.y)
        self.redraw()

    def _release(self, event) -> None:
        key = self._hit(event.x, event.y)
        pressed, self.pressed = self.pressed, None
        if key and key == pressed:
            self._activate(key)
        self.redraw()

    def _move(self, delta: int) -> str:
        keys = [key for key, _label in self.items if key not in self.hidden]
        index = keys.index(self.focus_key) if self.focus_key in keys else 0
        self.focus_key = keys[(index + delta) % len(keys)]
        self._activate(self.focus_key)
        return "break"

    def _activate(self, key: str | None) -> str:
        if key and key != self.selected:
            self.command(key)
        return "break"

    def select(self, key: str) -> None:
        self.selected = self.focus_key = key
        self.redraw()

    def set_hidden(self, keys) -> None:
        """Elemente aus- bzw. wieder einblenden – nur bei echter Änderung, ohne Neuaufbau."""
        hidden = frozenset(keys)
        if hidden == self.hidden:
            return
        self.hidden = hidden
        for key, _label in self.items:
            self.itemconfigure(self._texts[key], state="hidden" if key in hidden else "normal")
            if key in hidden:
                self.itemconfigure(self._overlays[key], state="hidden")
        if self.hover in hidden:
            self.hover = None
        if self.focus_key in hidden:
            self.focus_key = self.selected
        self._layout()
        self.redraw()

    def set_labels(self, labels: dict[str, str]) -> None:
        """Beschriftungen ändern (z. B. Anzahlen in einem Filter) – nur bei echter Änderung."""
        items = [(key, labels.get(key, label)) for key, label in self.items]
        if items == self.items:
            return
        self.items = items
        for key, label in items:
            self.itemconfigure(self._texts[key], text=label)
        self._layout()
        self.redraw()

    def redraw(self) -> None:
        c = ctx()
        pal = c.pal
        try:
            self.configure(bg=surface_color(self.master))
            keyboard = c.keyboard_mode and self.focus_get() is self
        except (tk.TclError, KeyError):
            keyboard = False
        radius = px(4)
        for key, (x0, y0, x1, y1) in self._rects.items():
            active = key == self.selected
            color = pal.text if (active or key == self.hover) else pal.text2
            self.coords(self._texts[key], (x0 + x1) / 2, (y0 + y1) / 2 - px(1))
            self.itemconfigure(self._texts[key], fill=color, font=c.fonts.body)
            if key == self.hover or key == self.pressed:
                alpha = pal.subtle_pressed_alpha if key == self.pressed else pal.subtle_hover_alpha
                self.itemconfigure(self._overlays[key], image=c.images.box(x1 - x0, y1 - y0, radius, pal.subtle_color, alpha=alpha), state="normal")
                self.coords(self._overlays[key], x0, y0)
            else:
                self.itemconfigure(self._overlays[key], state="hidden")
        if self.selected in self._rects:
            x0, _y0, x1, y1 = self._rects[self.selected]
            pill = c.images.box(px(16), px(3), px(1.5), pal.accent)
            self.coords(self._pill, (x0 + x1) / 2, y1 - px(3))
            self.itemconfigure(self._pill, image=pill, state="normal")
        if keyboard and self.focus_key in self._rects:
            x0, y0, x1, y1 = self._rects[self.focus_key]
            ring = c.images.ring(x1 - x0, y1 - y0, radius + px(1), pal.focus_outer, pal.focus_inner)
            self.coords(self._focus, x0, y0)
            self.itemconfigure(self._focus, image=ring, state="normal")
        else:
            self.itemconfigure(self._focus, state="hidden")


class ToolCard(RoundedFrame):
    """Karte eines Werkzeugs auf der Startseite: Symbol, Titel, Beschreibung, »Öffnen«."""

    def __init__(self, master, glyph: str, title: str, description: str, command: Callable[[], None], shortcut: str = "") -> None:
        from .widgets import Button

        super().__init__(master, fill="card", stroke="card_stroke")
        c = ctx()
        self._command = command
        body = frame(self)
        body.pack(fill="both", expand=True, padx=px(20), pady=px(20))
        top = frame(body)
        top.pack(fill="x")
        if c.icons_available:
            tile = tk.Canvas(top, width=px(48), height=px(48), highlightthickness=0, bd=0)
            tile.pack(side="left", anchor="n")
            self._tile = tile
            self._tile_bg = tile.create_image(0, 0, anchor="nw")
            self._tile_glyph = tile.create_text(px(24), px(24), text=glyph, anchor="center")
        else:
            self._tile = None
        texts = frame(top)
        texts.pack(side="left", fill="x", expand=True, padx=(px(16) if self._tile else 0, 0))
        Text(texts, title, style="subtitle").pack(anchor="w")
        Text(texts, description, style="body", color="text2", wrap=True).pack(anchor="w", fill="x", pady=(px(4), 0))
        bottom = frame(body)
        bottom.pack(fill="x", pady=(px(16), 0))
        self.button = Button(bottom, "Öffnen", command, kind="accent", min_width=120, tooltip=f"{title} öffnen" + (f" ({shortcut})" if shortcut else ""))
        self.button.pack(side="left")
        if shortcut:
            Text(bottom, shortcut, style="caption", color="text3").pack(side="right")
        for widget in (self, body, top, texts):
            widget.bind("<Button-1>", self._clicked, add="+")
        c.theme.subscribe(self._paint_tile, owner=self)
        self._paint_tile()
        self.lift_corners()

    def _clicked(self, event) -> None:
        if event.widget is not self.button:
            self._command()

    def _paint_tile(self) -> None:
        if self._tile is None:
            return
        c = ctx()
        pal = c.pal
        self._tile.configure(bg=pal.card)
        self._tile_img = c.images.box(px(48), px(48), px(8), pal.accent)
        self._tile.itemconfigure(self._tile_bg, image=self._tile_img)
        self._tile.itemconfigure(self._tile_glyph, fill=pal.on_accent, font=c.fonts.icon_large or c.fonts.icon)


class DropZone(RoundedFrame):
    """Großer Ablagebereich für eine Datei: Symbol, Hinweis, Schaltfläche.

    ``set_highlight(True)`` hebt den Bereich beim Hineinziehen hervor.
    """

    def __init__(self, master, glyph: str, title: str, hint: str, button_text: str, command: Callable[[], None], button_icon: str | None = None) -> None:
        from .widgets import Button

        super().__init__(master, fill="card", stroke="card_stroke")
        c = ctx()
        body = frame(self)
        body.pack(fill="both", expand=True, padx=px(24), pady=px(28))
        if c.icons_available:
            Icon(body, glyph, color="accent_text", size="icon_large").pack(pady=(0, px(10)))
        self.title = Text(body, title, style="body_strong", anchor="center", justify="center")
        self.title.pack()
        self.hint = Text(body, hint, style="caption", color="text2", anchor="center", justify="center", wrap=True)
        self.hint.pack(fill="x", pady=(px(4), px(14)))
        self.button = Button(body, button_text, command, icon=button_icon, min_width=160)
        self.button.pack()
        self.highlighted = False
        self.lift_corners()

    def set_highlight(self, on: bool) -> None:
        if on == self.highlighted:
            return
        self.highlighted = on
        self.set_fill("card", "accent" if on else "card_stroke")
