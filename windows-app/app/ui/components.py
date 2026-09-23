"""Zusammengesetzte Bausteine für die Seiten: Einstellungskarten, Dateizeilen, Formularfelder."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

from .context import ctx, surface_of
from .inputs import elide_middle
from .theme import px
from .widgets import Card, Icon, RoundedFrame, Text, frame


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
        self.bind("<Configure>", lambda _e: self.lift_corners(), add="+")

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
        self.value = Text(texts, "", style="caption", color="text2")
        self.value.pack(anchor="w", fill="x")
        self._full = ""
        self.value.bind("<Configure>", lambda _e: self._render(), add="+")
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

    def _render(self) -> None:
        width = self.value.winfo_width()
        text = self._full
        if width > 20:
            text = elide_middle(ctx().fonts.caption, text, width - px(4))
        if self.value.cget("text") != text:
            self.value.configure(text=text)


def path_caption(path: str, empty: str) -> tuple[str, str]:
    if not path:
        return empty, ""
    p = Path(path)
    parent = p.parent.name or str(p.parent)
    if p.suffix:
        return f"{p.name}  ·  {parent}", str(p)
    return (p.name or str(p)), str(p)


class ResponsiveColumns(tk.Frame):
    """Zwei Karten nebeneinander bei breitem Fenster, untereinander bei schmalem."""

    def __init__(self, master, breakpoint: int = 780, gap: int = 12) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = surface_of(master)
        ctx().theme.style(self, bg=self.surface_role)
        self._breakpoint = px(breakpoint)
        self._gap = px(gap)
        self._children: list[tk.Widget] = []
        self._wide: bool | None = None
        self.bind("<Configure>", self._layout, add="+")

    def add(self, widget: tk.Widget) -> tk.Widget:
        self._children.append(widget)
        self._wide = None
        self._layout()
        return widget

    def _layout(self, _event=None) -> None:
        width = self.winfo_width()
        wide = width >= self._breakpoint if width > 1 else True
        if wide == self._wide:
            return
        self._wide = wide
        for index, child in enumerate(self._children):
            child.grid_forget()
            if wide:
                pad = (0, self._gap // 2) if index == 0 else (self._gap // 2, 0)
                child.grid(row=0, column=index, sticky="nsew", padx=pad, pady=0)
            else:
                child.grid(row=index, column=0, sticky="nsew", padx=0, pady=(0 if index == 0 else self._gap, 0))
        for column in range(max(2, len(self._children))):
            self.columnconfigure(column, weight=1 if (wide or column == 0) else 0, uniform="cols" if wide else "")
        self.rowconfigure(0, weight=1)


def card(master, title: str, icon: str | None = None, description: str | None = None) -> Card:
    return Card(master, title=title, icon=icon, description=description)
