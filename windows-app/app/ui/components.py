"""Zusammengesetzte Bausteine für die Seiten: Einstellungskarten, Dateizeilen, Formularfelder."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

from . import icons
from .context import ctx, surface_color, surface_of
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
        self.value.bind("<Configure>", self._value_configured, add="+")
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
        self._label = Text(self, "", style="body_strong")
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
            self.bind("<Configure>", self._configured, add="+")

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
