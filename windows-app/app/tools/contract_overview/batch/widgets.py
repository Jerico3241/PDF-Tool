"""Bausteine der Ansicht »Stapel«: die Liste der Einträge.

Die Liste zeichnet alle Zeilen auf einem Canvas (wie die Kundenliste): Beim Aktualisieren
werden nur geänderte Zeilen neu beschriftet – keine Widgets zerstört oder neu aufgebaut.
So bleibt sie mit Dutzenden Einträgen flüssig, und Ergebnisse erscheinen gesammelt statt
Zeile für Zeile.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Sequence

from ui import icons
from ui.context import ctx, surface_color
from ui.inputs import elide_middle
from ui.theme import px
from ui.widgets import CONTROL_RADIUS


@dataclass(frozen=True)
class RowData:
    """Was eine Zeile zeigt – bewusst knapp: Status und das Wichtigste, Details im Eintrag."""

    id: str
    title: str  # Dateiname
    facts: str  # »5 aktive · 3 inaktiv ausgeblendet · rechnung@kunde.de«
    detail: str  # »Kunde erkannt: Beispiel GmbH · 123456«, fehlende Angabe, Fehler oder Ergebnis
    detail_tone: str  # Farbrolle: text2, caution, critical, success
    status: str  # »Bereit«, »Angaben erforderlich« …
    tone: str  # Farbe des Statuspunkts: success, caution, critical, accent, neutral
    selected: bool = False


class BatchList(tk.Canvas):
    """Fluent-Liste der Stapel-Einträge: Kontrollkästchen, Hover, Tastatur (↑ ↓ Pos1 Ende, Leertaste, Eingabe)."""

    ROW = 70
    CHECK = 20

    def __init__(self, master, on_open: Callable[[str], None], on_toggle: Callable[[str, bool], None]) -> None:
        super().__init__(master, height=px(self.ROW), highlightthickness=0, bd=0, takefocus=1)
        self.surface_role = getattr(master, "surface_role", "card")
        self.on_open = on_open
        self.on_toggle = on_toggle
        self.rows: list[RowData] = []
        self.focus_index: int | None = None
        self.hover: int | None = None
        self._items: list[dict] = []
        self._drawn: list[tuple] = []
        self._width = 0
        self._images: dict = {}
        self._hover_img = self.create_image(0, 0, anchor="nw", state="hidden")
        self._focus_img = self.create_image(0, 0, anchor="nw", state="hidden")
        self.bind("<Configure>", self._configured, add="+")
        self.bind("<Motion>", self._motion, add="+")
        self.bind("<Leave>", lambda _e: self._set_hover(None), add="+")
        self.bind("<ButtonRelease-1>", self._click, add="+")
        self.bind("<FocusIn>", lambda _e: self._paint_state(), add="+")
        self.bind("<FocusOut>", lambda _e: self._paint_state(), add="+")
        for key, delta in (("Down", 1), ("Up", -1), ("Next", 5), ("Prior", -5)):
            self.bind(f"<KeyPress-{key}>", lambda _e, d=delta: (self.move(d), "break")[1], add="+")
        self.bind("<KeyPress-Home>", lambda _e: (self.set_focus(0), "break")[1], add="+")
        self.bind("<KeyPress-End>", lambda _e: (self.set_focus(len(self.rows) - 1), "break")[1], add="+")
        self.bind("<KeyPress-space>", lambda _e: (self._toggle_focus(), "break")[1], add="+")
        for key in ("Return", "KP_Enter"):
            self.bind(f"<KeyPress-{key}>", lambda _e: (self._open_focus(), "break")[1], add="+")
        c = ctx()
        c.theme.subscribe(self._theme_changed, owner=self)
        c.on_focus_mode(self, self._paint_state)
        self._theme_changed()

    # Daten -------------------------------------------------------------------------------------
    def set_rows(self, rows: Sequence[RowData]) -> None:
        keep = self.rows[self.focus_index].id if self.focus_index is not None and self.focus_index < len(self.rows) else None
        self.rows = list(rows)
        self.focus_index = next((i for i, row in enumerate(self.rows) if row.id == keep), None)
        height = max(1, len(self.rows)) * px(self.ROW)
        if int(self.cget("height")) != height:
            self.configure(height=height)
        self._draw()

    def row_ids(self) -> list[str]:
        return [row.id for row in self.rows]

    def row(self, item_id: str) -> RowData | None:
        return next((row for row in self.rows if row.id == item_id), None)

    # Zeichnen ---------------------------------------------------------------------------------------
    def _theme_changed(self) -> None:
        self.configure(bg=surface_color(self.master))
        self._drawn = []
        self._draw()

    def _configured(self, event) -> None:
        if event.width != self._width:
            self._width = event.width
            self._drawn = []
            self._draw()

    def _row_items(self, index: int) -> dict:
        while len(self._items) <= index:
            c = ctx()
            self._items.append(
                {
                    "check": self.create_image(0, 0, anchor="center"),
                    "mark": self.create_text(0, 0, anchor="center"),
                    "title": self.create_text(0, 0, anchor="w", font=c.fonts.body_strong),
                    "facts": self.create_text(0, 0, anchor="w", font=c.fonts.caption),
                    "detail": self.create_text(0, 0, anchor="w", font=c.fonts.caption),
                    "dot": self.create_image(0, 0, anchor="center"),
                    "status": self.create_text(0, 0, anchor="e", font=c.fonts.caption),
                    "chevron": self.create_text(0, 0, anchor="center", font=c.fonts.icon_small or c.fonts.caption),
                    "line": self.create_line(0, 0, 0, 0),
                }
            )
        return self._items[index]

    def _tone(self, name: str) -> str:
        pal = ctx().pal
        return {"success": pal.success, "caution": pal.caution, "critical": pal.critical, "accent": pal.accent, "neutral": pal.neutral}.get(name, pal.neutral)

    def _text_color(self, role: str) -> str:
        pal = ctx().pal
        return {"text2": pal.text2, "caution": pal.text, "critical": pal.critical, "success": pal.text2, "accent": pal.accent_text}.get(role, pal.text2)

    def _draw(self) -> None:
        c = ctx()
        pal = c.pal
        width = max(self._width, self.winfo_width(), px(260))
        row_h = px(self.ROW)
        pad = px(12)
        check = px(self.CHECK)
        text_x = pad + check + px(12)
        chevron_w = px(24)
        surface = surface_color(self.master)
        drawn: list[tuple] = []
        for index, row in enumerate(self.rows):
            items = self._row_items(index)
            y = index * row_h
            status_w = c.fonts.caption.measure(row.status) + px(16)
            title_w = max(px(60), width - text_x - pad - chevron_w - status_w - px(12))
            line_w = max(px(60), width - text_x - pad - chevron_w)
            title = elide_middle(c.fonts.body_strong, row.title, title_w)
            facts = elide_middle(c.fonts.caption, row.facts, line_w)
            detail = elide_middle(c.fonts.caption, row.detail, line_w)
            state = (row, title, facts, detail, width, pal.text, surface)
            drawn.append(state)
            if index < len(self._drawn) and self._drawn[index] == state:
                continue
            top = y + row_h * 0.27
            # Kontrollkästchen
            if row.selected:
                box = c.images.box(check, check, px(CONTROL_RADIUS), pal.accent, background=surface)
                mark = icons.CHECK_MARK if c.icons_available else "✓"
            else:
                box = c.images.box(check, check, px(CONTROL_RADIUS), pal.control, pal.strong_stroke, background=surface)
                mark = ""
            self._images[("check", index)] = box
            self.itemconfigure(items["check"], image=box, state="normal")
            self.coords(items["check"], pad + check / 2, top)
            glyph_font = (c.fonts.families["icons"], -px(12)) if c.icons_available else c.fonts.caption
            self.itemconfigure(items["mark"], text=mark, fill=pal.on_accent, font=glyph_font, state="normal")
            self.coords(items["mark"], pad + check / 2, top)
            # Texte
            self.itemconfigure(items["title"], text=title, fill=pal.text, state="normal")
            self.coords(items["title"], text_x, top)
            # Ohne Prüfergebnis rückt die zweite Zeile nach oben – keine Lücke in der Zeile.
            self.itemconfigure(items["facts"], text=facts, fill=pal.text2, state="normal" if facts else "hidden")
            self.coords(items["facts"], text_x, y + row_h * 0.55)
            self.itemconfigure(items["detail"], text=detail, fill=self._text_color(row.detail_tone), state="normal" if detail else "hidden")
            self.coords(items["detail"], text_x, y + row_h * (0.79 if facts else 0.55))
            # Status: Punkt und Text rechts oben
            status_x = width - pad - chevron_w
            dot = c.images.circle(px(8), self._tone(row.tone), background=surface)
            self._images[("dot", index)] = dot
            text_w = c.fonts.caption.measure(row.status)
            self.itemconfigure(items["dot"], image=dot, state="normal")
            self.coords(items["dot"], status_x - text_w - px(10), top)
            self.itemconfigure(items["status"], text=row.status, fill=pal.text, state="normal")
            self.coords(items["status"], status_x, top)
            self.itemconfigure(items["chevron"], text=icons.CHEVRON_RIGHT if c.icons_available else "›", fill=pal.text2, state="normal")
            self.coords(items["chevron"], width - pad - chevron_w / 2 + px(4), y + row_h * 0.5)
            self.itemconfigure(items["line"], fill=pal.divider, state="normal" if index else "hidden")
            self.coords(items["line"], pad, y, width - pad, y)
        for index in range(len(self.rows), len(self._items)):
            for item in self._items[index].values():
                self.itemconfigure(item, state="hidden")
        self._drawn = drawn
        self._paint_state()

    def _box(self, index: int | None, handle: int, fill: str, alpha: float) -> None:
        if index is None or index >= len(self.rows):
            self.itemconfigure(handle, state="hidden")
            return
        width = max(self._width, self.winfo_width(), px(260))
        row_h = px(self.ROW)
        img = ctx().images.box(width - px(4), row_h - px(4), px(4), fill, alpha=alpha)
        self._images[handle] = img
        self.itemconfigure(handle, image=img, state="normal")
        self.coords(handle, px(2), index * row_h + px(2))
        self.tag_lower(handle)

    def _paint_state(self) -> None:
        c = ctx()
        pal = c.pal
        try:
            focused = self.focus_get() is self
        except (tk.TclError, KeyError):
            focused = False
        self._box(self.hover, self._hover_img, pal.subtle_color, pal.subtle_hover_alpha)
        if focused and c.keyboard_mode and self.focus_index is not None and self.focus_index < len(self.rows):
            width = max(self._width, self.winfo_width(), px(260))
            row_h = px(self.ROW)
            ring = c.images.ring(width - px(2), row_h - px(2), px(5), pal.focus_outer, pal.focus_inner)
            self._images["ring"] = ring
            self.itemconfigure(self._focus_img, image=ring, state="normal")
            self.coords(self._focus_img, px(1), self.focus_index * row_h + px(1))
            self.tag_raise(self._focus_img)
        else:
            self.itemconfigure(self._focus_img, state="hidden")

    # Bedienung --------------------------------------------------------------------------------------------
    def _index_at(self, y: int) -> int | None:
        index = int(y // px(self.ROW))
        return index if 0 <= index < len(self.rows) else None

    def _in_check(self, x: int) -> bool:
        return x < px(12) + px(self.CHECK) + px(8)

    def _set_hover(self, index: int | None) -> None:
        if index != self.hover:
            self.hover = index
            self.configure(cursor="hand2" if index is not None else "")
            self._paint_state()

    def _motion(self, event) -> None:
        self._set_hover(self._index_at(event.y))

    def _click(self, event) -> None:
        index = self._index_at(event.y)
        if index is None:
            return
        self.focus_set()
        self.focus_index = index
        self._paint_state()
        row = self.rows[index]
        if self._in_check(event.x):
            self.on_toggle(row.id, not row.selected)
        else:
            self.on_open(row.id)

    def set_focus(self, index: int) -> None:
        if not self.rows:
            return
        self.focus_index = max(0, min(len(self.rows) - 1, index))
        self._paint_state()
        self._reveal()

    def move(self, delta: int) -> None:
        if not self.rows:
            return
        start = -1 if self.focus_index is None and delta > 0 else (len(self.rows) if self.focus_index is None else self.focus_index)
        self.set_focus(start + delta)

    def _toggle_focus(self) -> None:
        if self.focus_index is not None and self.focus_index < len(self.rows):
            row = self.rows[self.focus_index]
            self.on_toggle(row.id, not row.selected)

    def _open_focus(self) -> None:
        if self.focus_index is not None and self.focus_index < len(self.rows):
            self.on_open(self.rows[self.focus_index].id)

    def _reveal(self) -> None:
        widget = self.master
        while widget is not None and not hasattr(widget, "scroll_into_view"):
            widget = getattr(widget, "master", None)
        if widget is not None and self.focus_index is not None:
            widget.scroll_into_view(self, self.focus_index * px(self.ROW), px(self.ROW))
