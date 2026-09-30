"""Anzeige des Vertragsvergleichs – in »Übersicht erstellen« und in der Detailansicht des Stapels.

* ``CountBar``: »● 2 neu  ● 1 entfernt  ● 3 geändert  ● 4 unverändert« in den Statusfarben
* ``ChangeList``: Neu, Entfernt, Geändert (aufklappbar mit den geänderten Feldern) –
  auf einem Canvas gezeichnet wie die Stapel-Liste: keine Widgets werden auf- und
  abgebaut, die Liste erscheint in einem Zug
* ``ComparisonView``: alles zusammen mit »Vergleichen mit«, Stand-Angaben und
  »Änderungen kopieren«
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Sequence

from ui import icons
from ui.components import FactList
from ui.context import bind_size, ctx, surface_color
from ui.inputs import ComboBox, elide_middle
from ui.theme import px
from ui.widgets import Button, FlowRow, InfoBar, Text, frame

from .history import report
from .history.models import ChangeKind, ContractComparison

TONES = {ChangeKind.ADDED: "success", ChangeKind.REMOVED: "critical", ChangeKind.CHANGED: "caution", ChangeKind.UNCHANGED: "neutral"}


@dataclass(frozen=True)
class ChangeRow:
    key: str
    kind: ChangeKind
    title: str  # »10001 GetSolar«
    summary: str  # rechts: »Netto 250,00 € → 270,00 €« oder »3 Änderungen«
    details: tuple[tuple[str, str], ...] = ()  # (Feld, »alt → neu«)


def rows_for(comparison: ContractComparison, include_unchanged: bool = False) -> list[ChangeRow]:
    rows = []
    for change in comparison.changes(include_unchanged):
        details = tuple((report.FIELD_LABELS.get(f.field, f.field), f"{report.format_value(f.field, f.old_value)} → {report.format_value(f.field, f.new_value)}") for f in change.fields)
        if change.kind is ChangeKind.CHANGED:
            summary = f"{details[0][0]} {details[0][1]}" if len(details) == 1 else f"{len(details)} Änderungen"
        elif change.kind is ChangeKind.ADDED:
            summary = report.euro(change.record.net_amount) if change.record.net_amount else change.record.net_text
        elif change.kind is ChangeKind.REMOVED:
            summary = "nicht mehr in der Excel"
        else:
            summary = ""
        rows.append(ChangeRow(change.key, change.kind, report.contract_title(change.record), summary, details))
    return rows


def _tone(name: str) -> str:
    pal = ctx().pal
    return {"success": pal.success, "caution": pal.caution, "critical": pal.critical}.get(name, pal.neutral)


class CountBar(tk.Canvas):
    """Zähler der Kategorien als farbige Punkte mit Text."""

    def __init__(self, master) -> None:
        super().__init__(master, height=px(22), highlightthickness=0, bd=0)
        self.surface_role = getattr(master, "surface_role", "card")
        self.items: list[tuple[str, str]] = []  # (Text, Ton)
        self._images: list = []
        ctx().theme.subscribe(self._draw, owner=self)
        self._draw()

    def set_counts(self, items: Sequence[tuple[str, str]]) -> None:
        items = list(items)
        if items != self.items:
            self.items = items
            self._draw()

    def text(self) -> str:
        return " · ".join(label for label, _tone in self.items)

    def _draw(self) -> None:
        c = ctx()
        self.configure(bg=surface_color(self.master))
        self.delete("all")
        self._images = []
        x = 0
        mid = px(11)
        for label, tone in self.items:
            dot = c.images.circle(px(8), _tone(tone), background=surface_color(self.master))
            self._images.append(dot)
            self.create_image(x + px(4), mid, image=dot, anchor="center")
            self.create_text(x + px(14), mid, text=label, anchor="w", font=c.fonts.body, fill=c.pal.text)
            x += px(14) + c.fonts.body.measure(label) + px(18)


class ChangeList(tk.Canvas):
    """Änderungen als Liste; geänderte Verträge klappen per Klick, Eingabe oder Leertaste auf."""

    ROW = 38
    DETAIL = 22
    KIND_W = 96

    def __init__(self, master) -> None:
        super().__init__(master, height=1, highlightthickness=0, bd=0, takefocus=1)
        self.surface_role = getattr(master, "surface_role", "card")
        self.rows: list[ChangeRow] = []
        self.expanded: set[str] = set()
        self.focus_index: int | None = None
        self.hover: int | None = None
        self._tops: list[int] = []
        self._width = 0
        self._images: dict = {}
        bind_size(self, self._configured)
        self.bind("<Motion>", lambda e: self._set_hover(self._index_at(e.y)), add="+")
        self.bind("<Leave>", lambda _e: self._set_hover(None), add="+")
        self.bind("<ButtonRelease-1>", self._click, add="+")
        self.bind("<FocusIn>", lambda _e: self._draw(), add="+")
        self.bind("<FocusOut>", lambda _e: self._draw(), add="+")
        self.bind("<KeyPress-Down>", lambda _e: (self._move(1), "break")[1], add="+")
        self.bind("<KeyPress-Up>", lambda _e: (self._move(-1), "break")[1], add="+")
        for key in ("Return", "KP_Enter", "space"):
            self.bind(f"<KeyPress-{key}>", lambda _e: (self._toggle_focus(), "break")[1], add="+")
        c = ctx()
        c.theme.subscribe(self._draw, owner=self)
        c.on_focus_mode(self, self._draw)

    # Daten ---------------------------------------------------------------------------------------
    def set_rows(self, rows: Sequence[ChangeRow]) -> None:
        rows = list(rows)
        keys = {row.key for row in rows}
        self.expanded &= keys
        if rows == self.rows:
            return
        keep = self.rows[self.focus_index].key if self.focus_index is not None and self.focus_index < len(self.rows) else None
        self.rows = rows
        self.focus_index = next((i for i, row in enumerate(rows) if row.key == keep), None)
        self._draw()

    def toggle(self, key: str) -> None:
        row = next((row for row in self.rows if row.key == key), None)
        if row is None or not row.details:
            return
        self.expanded ^= {key}
        self._draw()

    def visible_text(self) -> list[str]:
        """Sichtbare Zeilen (für Tests und Barrierefreiheit)."""
        lines = []
        for row in self.rows:
            lines.append(f"{report.KIND_LABELS[row.kind]}: {row.title}" + (f" – {row.summary}" if row.summary else ""))
            if row.key in self.expanded:
                lines += [f"  {label}: {value}" for label, value in row.details]
        return lines

    # Zeichnen ---------------------------------------------------------------------------------------
    def _configured(self, event) -> None:
        if event.width != self._width:
            self._width = event.width
            self._draw()

    def _draw(self) -> None:
        c = ctx()
        pal = c.pal
        surface = surface_color(self.master)
        self.configure(bg=surface)
        self.delete("all")
        width = max(self._width, self.winfo_width(), px(260))
        row_h, detail_h = px(self.ROW), px(self.DETAIL)
        pad = px(4)
        title_x = pad + px(self.KIND_W)
        chevron_w = px(22)
        y = 0
        self._tops = []
        try:
            focused = self.focus_get() is self
        except (tk.TclError, KeyError):
            focused = False
        for index, row in enumerate(self.rows):
            open_ = row.key in self.expanded
            height = row_h + (len(row.details) * detail_h + px(6) if open_ else 0)
            self._tops.append(y)
            if index == self.hover:
                img = c.images.box(width - px(2), height - px(2), px(4), pal.subtle_color, alpha=pal.subtle_hover_alpha)
                self._images[("hover", index)] = img
                self.create_image(px(1), y + px(1), image=img, anchor="nw")
            if index:
                self.create_line(pad, y, width - pad, y, fill=pal.divider)
            mid = y + row_h / 2
            dot = c.images.circle(px(8), _tone(TONES[row.kind]), background=surface)
            self._images[("dot", index)] = dot
            self.create_image(pad + px(6), mid, image=dot, anchor="center")
            self.create_text(pad + px(16), mid, text=report.KIND_LABELS[row.kind], anchor="w", font=c.fonts.caption, fill=pal.text2)
            summary_w = min(c.fonts.caption.measure(row.summary), int(width * 0.45)) if row.summary else 0
            right = width - pad - (chevron_w if row.details else 0)
            title_w = max(px(60), right - title_x - summary_w - px(16))
            self.create_text(title_x, mid, text=elide_middle(c.fonts.body, row.title, title_w), anchor="w", font=c.fonts.body, fill=pal.text)
            if row.summary:
                self.create_text(right - px(4), mid, text=elide_middle(c.fonts.caption, row.summary, summary_w), anchor="e", font=c.fonts.caption, fill=pal.text2)
            if row.details:
                glyph = (icons.CHEVRON_UP if open_ else icons.CHEVRON_DOWN) if c.icons_available else ("▴" if open_ else "▾")
                self.create_text(width - pad - chevron_w / 2, mid, text=glyph, anchor="center", font=c.fonts.icon_small or c.fonts.caption, fill=pal.text2)
            if open_:
                line_y = y + row_h
                for label, value in row.details:
                    self.create_text(title_x, line_y + detail_h / 2, text=label, anchor="w", font=c.fonts.caption, fill=pal.text2)
                    self.create_text(title_x + px(140), line_y + detail_h / 2, text=elide_middle(c.fonts.body, value, max(px(60), width - title_x - px(150))), anchor="w", font=c.fonts.body, fill=pal.text)
                    line_y += detail_h
            if focused and c.keyboard_mode and index == self.focus_index:
                ring = c.images.ring(width - px(2), height - px(2), px(5), pal.focus_outer, pal.focus_inner)
                self._images["ring"] = ring
                self.create_image(px(1), y + px(1), image=ring, anchor="nw")
            y += height
        total = max(1, y)
        if int(self.cget("height")) != total:
            self.configure(height=total)

    # Bedienung ----------------------------------------------------------------------------------------
    def _index_at(self, y: int) -> int | None:
        for index in range(len(self._tops) - 1, -1, -1):
            if y >= self._tops[index]:
                return index if index < len(self.rows) else None
        return None

    def _set_hover(self, index: int | None) -> None:
        if index != self.hover:
            self.hover = index
            row = self.rows[index] if index is not None else None
            self.configure(cursor="hand2" if row is not None and row.details else "")
            self._draw()

    def _click(self, event) -> None:
        index = self._index_at(event.y)
        if index is None:
            return
        self.focus_set()
        self.focus_index = index
        self.toggle(self.rows[index].key)
        self._draw()

    def _move(self, delta: int) -> None:
        if not self.rows:
            return
        start = -1 if self.focus_index is None else self.focus_index
        self.focus_index = max(0, min(len(self.rows) - 1, start + delta))
        self._draw()

    def _toggle_focus(self) -> None:
        if self.focus_index is not None and self.focus_index < len(self.rows):
            self.toggle(self.rows[self.focus_index].key)


class ComparisonView(tk.Frame):
    """Vertragsänderungen: Hinweis oder Vergleich mit »Vergleichen mit«, Liste und Stand-Angaben."""

    LATEST = "Letzter Stand"

    def __init__(self, master, on_baseline: Callable[[str], None], on_copy: Callable[[], None]) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = getattr(master, "surface_role", "card")
        ctx().theme.style(self, bg=self.surface_role)
        self.on_baseline = on_baseline
        self.comparison: ContractComparison | None = None
        self.show_unchanged = False
        self._choices: list[tuple[str, str]] = []  # (Stand-ID, Beschriftung)
        self.info = InfoBar(self, closable=False)
        self.info.pack(fill="x")
        self.body = frame(self)
        head = frame(self.body)
        head.pack(fill="x")
        self.headline = Text(head, "", style="body_strong", wrap=True, width=1)
        self.headline.pack(side="left", fill="x", expand=True, anchor="w")
        self.baseline = ComboBox(head, command=self._picked, width=230, tooltip="Früheren Vertragsstand dieses Kunden zum Vergleich wählen")
        self.baseline.pack(side="right")
        Text(head, "Vergleichen mit", style="caption", color="text2").pack(side="right", padx=(px(12), px(8)))
        self.counts = CountBar(self.body)
        self.counts.pack(fill="x", pady=(px(8), 0))
        self.changes = ChangeList(self.body)
        self.changes.pack(fill="x", pady=(px(6), 0))
        buttons = FlowRow(self.body, gap=8, row_gap=8)
        buttons.pack(fill="x", pady=(px(8), 0))
        self.btn_unchanged = Button(buttons, "", self._toggle_unchanged, icon=icons.BULLETED_LIST, kind="subtle")
        buttons.add(self.btn_unchanged)
        self.btn_copy = Button(buttons, "Änderungen kopieren", on_copy, icon=icons.COPY, kind="subtle", tooltip="Änderungen als Text in die Zwischenablage kopieren")
        buttons.add(self.btn_copy)
        self.buttons = buttons
        self.meta = FactList(self.body, label_width=110)
        self.meta.pack(fill="x", pady=(px(8), 0))

    # Zustände --------------------------------------------------------------------------------------------
    def show_message(self, severity: str, message: str, title: str = "") -> None:
        """Nur ein Hinweis (ohne Kundenakte, noch kein früherer Stand)."""
        self.comparison = None
        self.info.show(severity, message, title, animate=False)
        if self.body.winfo_manager():
            self.body.pack_forget()

    def show_comparison(
        self,
        comparison: ContractComparison,
        choices: Sequence[tuple[str, str]],
        selected: str,
        meta: Sequence[tuple[str, str, str]],
        note: tuple[str, str, str] | None = None,
    ) -> None:
        """Vergleich anzeigen. ``choices``: (Stand-ID, Beschriftung), neueste zuerst."""
        if comparison is not self.comparison and (self.comparison is None or comparison.baseline != self.comparison.baseline):
            self.show_unchanged = False
        self.comparison = comparison
        if note is not None:
            self.info.show(note[0], note[1], note[2], animate=False)
        else:
            self.info.hide(animate=False)
        self._choices = list(choices)
        labels = [label for _id, label in self._choices]
        self.baseline.set_values(labels, keep=False)
        current = next((label for snapshot_id, label in self._choices if snapshot_id == selected), labels[0] if labels else "")
        self.baseline.set(current)
        baseline = comparison.baseline
        since = report.stand_label(baseline, with_time=False) if baseline is not None else ""
        self.headline.configure(text=f"Seit {since}" if comparison.has_changes else f"Keine Änderungen seit {since}")
        counts = comparison.counts()
        items = []
        for kind, label in ((ChangeKind.ADDED, "neu"), (ChangeKind.REMOVED, "entfernt"), (ChangeKind.CHANGED, "geändert"), (ChangeKind.UNCHANGED, "unverändert")):
            if counts[kind]:
                items.append((f"{counts[kind]} {label}", TONES[kind]))
        self.counts.set_counts(items)
        unchanged = counts[ChangeKind.UNCHANGED]
        self.buttons.set_visible(self.btn_unchanged, bool(unchanged))
        self.btn_unchanged.set_text(("Unveränderte ausblenden" if self.show_unchanged else f"{unchanged} unveränderte anzeigen") if unchanged != 1 or self.show_unchanged else "1 unveränderten anzeigen")
        self.buttons.set_visible(self.btn_copy, comparison.has_changes)
        rows = rows_for(comparison, self.show_unchanged)
        self.changes.set_rows(rows)
        if rows:
            if not self.changes.winfo_manager():
                self.changes.pack(fill="x", pady=(px(6), 0), after=self.counts)
        elif self.changes.winfo_manager():
            self.changes.pack_forget()
        self.meta.set(list(meta))
        if not self.body.winfo_manager():
            self.body.pack(fill="x", pady=(px(8) if note is not None else 0, 0))

    def selected_label(self) -> str:
        return self.baseline.get()

    # Bedienung ------------------------------------------------------------------------------------------------
    def _picked(self, label: str) -> None:
        snapshot_id = next((snapshot_id for snapshot_id, text in self._choices if text == label), "")
        if snapshot_id:
            self.on_baseline(snapshot_id)

    def _toggle_unchanged(self) -> None:
        self.show_unchanged = not self.show_unchanged
        if self.comparison is not None:
            counts = self.comparison.counts()[ChangeKind.UNCHANGED]
            self.btn_unchanged.set_text("Unveränderte ausblenden" if self.show_unchanged else (f"{counts} unveränderte anzeigen" if counts != 1 else "1 unveränderten anzeigen"))
            self.changes.set_rows(rows_for(self.comparison, self.show_unchanged))
            if self.changes.rows and not self.changes.winfo_manager():
                self.changes.pack(fill="x", pady=(px(6), 0), after=self.counts)
