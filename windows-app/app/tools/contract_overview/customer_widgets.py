"""Bausteine der Kundenakte für die Oberfläche: Liste, Auswahlfeld, Such- und Anlegedialog.

Die Kundenliste zeichnet alle Einträge auf einem Canvas: Beim Filtern werden nur
Texte und Positionen geändert – keine Widgets zerstört und neu aufgebaut. So bleibt
die Liste auch mit einigen hundert Kundenakten flüssig.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timedelta
from typing import Callable, Sequence

from appstate import ICON_FILE
from ui import dialogs, icons
from ui.context import ctx, surface_color
from ui.inputs import ComboBox, TextField, elide_middle
from ui.theme import px
from ui.widgets import Text, ToggleSwitch, frame

from .customers.models import Customer, parse_time

MAX_ROWS = 200  # mehr Treffer: »Suche verfeinern«


def format_when(value: str, empty: str = "–") -> str:
    """ISO-Zeitstempel für die Oberfläche: »Heute, 15:32«, »Gestern, 09:10« oder »28.09.2026«."""
    moment = parse_time(value)
    if moment is None:
        return empty
    local = moment.astimezone()
    today = datetime.now().astimezone().date()
    if local.date() == today:
        return f"Heute, {local:%H:%M}"
    if local.date() == today - timedelta(days=1):
        return f"Gestern, {local:%H:%M}"
    return f"{local:%d.%m.%Y}"


def email_summary(customer: Customer) -> str:
    if not customer.emails:
        return "keine E-Mail zugeordnet"
    more = len(customer.emails) - 1
    return customer.emails[0] + (f" (+{more} weitere)" if more > 0 else "")


class CustomerList(tk.Canvas):
    """Fluent-Liste der Kundenakten: Zeilen mit Hover, Auswahl, Tastatur (↑ ↓ Pos1 Ende, Eingabe)."""

    ROW = 60

    def __init__(self, master, on_open: Callable[[str], None], on_select: Callable[[str], None] | None = None, show_activity: bool = True) -> None:
        super().__init__(master, height=px(self.ROW), highlightthickness=0, bd=0, takefocus=1)
        self.surface_role = getattr(master, "surface_role", "card")
        self.on_open = on_open
        self.on_select = on_select
        self.show_activity = show_activity
        self.items: list[Customer] = []
        self.selected: int | None = None
        self.hover: int | None = None
        self._rows: list[dict] = []
        self._width = 0
        self._drawn: list[tuple] = []
        self._bg = self.create_image(0, 0, anchor="nw", state="hidden")
        self._hover_img = self.create_image(0, 0, anchor="nw", state="hidden")
        self._focus = self.create_image(0, 0, anchor="nw", state="hidden")
        self.bind("<Configure>", self._configured, add="+")
        self.bind("<Motion>", self._motion, add="+")
        self.bind("<Leave>", lambda _e: self._set_hover(None), add="+")
        self.bind("<ButtonRelease-1>", self._click, add="+")
        self.bind("<FocusIn>", lambda _e: self._paint_state(), add="+")
        self.bind("<FocusOut>", lambda _e: self._paint_state(), add="+")
        for key, delta in (("Down", 1), ("Up", -1), ("Next", 5), ("Prior", -5)):
            self.bind(f"<KeyPress-{key}>", lambda _e, d=delta: (self.move(d), "break")[1], add="+")
        self.bind("<KeyPress-Home>", lambda _e: (self.select(0), "break")[1], add="+")
        self.bind("<KeyPress-End>", lambda _e: (self.select(len(self.items) - 1), "break")[1], add="+")
        for key in ("Return", "KP_Enter", "space"):
            self.bind(f"<KeyPress-{key}>", lambda _e: (self.open_selected(), "break")[1], add="+")
        c = ctx()
        c.theme.subscribe(self._theme_changed, owner=self)
        c.on_focus_mode(self, self._paint_state)
        self._theme_changed()

    # Daten -----------------------------------------------------------------------------
    def set_items(self, items: Sequence[Customer]) -> None:
        keep = self.items[self.selected].id if self.selected is not None and self.selected < len(self.items) else None
        self.items = list(items)[:MAX_ROWS]
        self.selected = next((i for i, item in enumerate(self.items) if item.id == keep), None)
        self.hover = None
        height = max(1, len(self.items)) * px(self.ROW)
        if int(self.cget("height")) != height:
            self.configure(height=height)
        self._draw()

    def selected_id(self) -> str | None:
        if self.selected is None or self.selected >= len(self.items):
            return None
        return self.items[self.selected].id

    # Zeichnen ------------------------------------------------------------------------------
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
        while len(self._rows) <= index:
            c = ctx()
            self._rows.append(
                {
                    "title": self.create_text(0, 0, anchor="w", font=c.fonts.body_strong),
                    "sub": self.create_text(0, 0, anchor="w", font=c.fonts.caption),
                    "when": self.create_text(0, 0, anchor="e", font=c.fonts.caption),
                    "chevron": self.create_text(0, 0, anchor="center", font=c.fonts.icon_small or c.fonts.caption),
                    "line": self.create_line(0, 0, 0, 0),
                }
            )
        return self._rows[index]

    def _draw(self) -> None:
        c = ctx()
        pal = c.pal
        width = max(self._width, self.winfo_width(), px(200))
        row_h = px(self.ROW)
        pad = px(14)
        chevron_w = px(28)
        when_w = px(110) if self.show_activity and width > px(420) else 0
        drawn: list[tuple] = []
        for index, customer in enumerate(self.items):
            items = self._row_items(index)
            y = index * row_h
            title_w = width - 2 * pad - chevron_w - when_w
            title = elide_middle(c.fonts.body_strong, customer.company or "Ohne Namen", title_w)
            sub = elide_middle(c.fonts.caption, f"Kd.-Nr. {customer.number or '–'}  ·  {email_summary(customer)}", title_w)
            when = format_when(customer.last_used_at, "") if when_w else ""
            state = (customer.id, title, sub, when, width)
            drawn.append(state)
            if index < len(self._drawn) and self._drawn[index] == state:
                continue
            self.itemconfigure(items["title"], text=title, fill=pal.text, state="normal")
            self.coords(items["title"], pad, y + row_h * 0.36)
            self.itemconfigure(items["sub"], text=sub, fill=pal.text2, state="normal")
            self.coords(items["sub"], pad, y + row_h * 0.68)
            self.itemconfigure(items["when"], text=when, fill=pal.text2, state="normal" if when else "hidden")
            self.coords(items["when"], width - pad - chevron_w, y + row_h * 0.5)
            self.itemconfigure(items["chevron"], text=icons.CHEVRON_RIGHT if c.icons_available else "›", fill=pal.text2, state="normal")
            self.coords(items["chevron"], width - pad - chevron_w / 2 + px(6), y + row_h * 0.5)
            self.itemconfigure(items["line"], fill=pal.divider, state="normal" if index else "hidden")
            self.coords(items["line"], pad, y, width - pad, y)
        for index in range(len(self.items), len(self._rows)):
            for item in self._rows[index].values():
                self.itemconfigure(item, state="hidden")
        self._drawn = drawn
        self._paint_state()

    def _box(self, index: int | None, handle: int, fill: str, alpha: float = 1.0) -> None:
        if index is None or index >= len(self.items):
            self.itemconfigure(handle, state="hidden")
            return
        width = max(self._width, self.winfo_width(), px(200))
        row_h = px(self.ROW)
        c = ctx()
        img = c.images.box(width - px(4), row_h - px(4), px(4), fill, alpha=alpha)
        self._images = getattr(self, "_images", {})
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
        self._box(self.selected, self._bg, pal.subtle_color, alpha=pal.subtle_pressed_alpha)
        hover = self.hover if self.hover != self.selected else None
        self._box(hover, self._hover_img, pal.subtle_color, alpha=pal.subtle_hover_alpha)
        if focused and c.keyboard_mode and self.selected is not None and self.selected < len(self.items):
            width = max(self._width, self.winfo_width(), px(200))
            row_h = px(self.ROW)
            ring = c.images.ring(width - px(2), row_h - px(2), px(5), pal.focus_outer, pal.focus_inner)
            self._ring_img = ring
            self.itemconfigure(self._focus, image=ring, state="normal")
            self.coords(self._focus, px(1), self.selected * row_h + px(1))
            self.tag_raise(self._focus)
        else:
            self.itemconfigure(self._focus, state="hidden")

    # Bedienung ---------------------------------------------------------------------------------
    def _index_at(self, y: int) -> int | None:
        index = int(y // px(self.ROW))
        return index if 0 <= index < len(self.items) else None

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
        self.select(index, reveal=False)
        self.open_selected()

    def select(self, index: int, reveal: bool = True) -> None:
        if not self.items:
            return
        self.selected = max(0, min(len(self.items) - 1, index))
        self._paint_state()
        if self.on_select is not None:
            self.on_select(self.items[self.selected].id)
        if reveal:
            self._reveal()

    def move(self, delta: int) -> None:
        if not self.items:
            return
        start = -1 if self.selected is None and delta > 0 else (len(self.items) if self.selected is None else self.selected)
        self.select(start + delta)

    def open_selected(self) -> None:
        ident = self.selected_id()
        if ident is not None:
            self.on_open(ident)

    def _reveal(self) -> None:
        """Ausgewählte Zeile im umgebenden Scrollbereich sichtbar machen."""
        widget = self.master
        while widget is not None and not hasattr(widget, "scroll_into_view"):
            widget = getattr(widget, "master", None)
        if widget is not None and self.selected is not None:
            widget.scroll_into_view(self, self.selected * px(self.ROW), px(self.ROW))


class PickerBox(ComboBox):
    """Sieht aus wie eine Auswahlliste, öffnet aber einen Suchdialog (viele Einträge)."""

    def __init__(self, master, command: Callable[[], None], placeholder: str, width: int = 240, tooltip: str | None = None) -> None:
        self._open_command = command
        super().__init__(master, placeholder=placeholder, width=width, tooltip=tooltip)

    def open_popup(self) -> None:
        if self._enabled:
            self._open_command()

    def _step(self, delta: int) -> None:
        if delta > 0:
            self.open_popup()

    def _jump(self, index: int) -> None:
        pass

    def show_label(self, label: str | None) -> None:
        if self.values() != ([label] if label else []) or self.get() != (label or ""):
            self.set_values([label] if label else [], keep=False)
            self.set(label)


def choose_customer(parent, store, candidates: Sequence[str] | None = None, title: str = "Bekannten Kunden auswählen", message: str | None = None, exclude: str | None = None) -> str | None:
    """Dialog mit Suche: gibt die ID der gewählten Kundenakte zurück (oder ``None``)."""
    from .customers.repository import ORDER_RECENT

    pool = [store.get(ident) for ident in candidates] if candidates else store.ordered(ORDER_RECENT)
    pool = [customer for customer in pool if customer is not None and customer.id != exclude]
    chosen: dict[str, str | None] = {"id": None}
    widgets: dict = {}
    var = tk.StringVar(parent, "")

    def build(holder) -> None:
        if not candidates:
            field = TextField(holder, var, placeholder="Firma, Kundennummer oder E-Mail suchen", width=420)
            field.pack(fill="x")
            widgets["field"] = field
        box = frame(holder)
        box.pack(fill="both", expand=True, pady=(px(10), 0))
        count = Text(box, "", style="caption", color="text2")
        count.pack(anchor="w", pady=(0, px(4)))
        viewport = tk.Canvas(box, height=px(CustomerList.ROW * 5), highlightthickness=0, bd=0)
        viewport.configure(bg=surface_color(box))
        viewport.pack(fill="x")
        inner = frame(viewport)
        viewport.create_window(0, 0, window=inner, anchor="nw", tags="inner")

        def pick(ident: str) -> None:
            chosen["id"] = ident
            dialog.buttons[dialogs.PRIMARY].set_enabled(True)

        def open_(ident: str) -> None:
            chosen["id"] = ident
            dialog._finish(dialogs.PRIMARY)

        listing = CustomerList(inner, on_open=open_, on_select=pick, show_activity=True)
        listing.pack(fill="x")
        widgets["list"] = listing

        def scroll_into_view(_widget, top: int, height: int) -> None:
            view = viewport.winfo_height()
            total = max(1, listing.winfo_reqheight())
            first = viewport.canvasy(0)
            if top < first:
                viewport.yview_moveto(top / total)
            elif top + height > first + view:
                viewport.yview_moveto((top + height - view) / total)

        inner.scroll_into_view = scroll_into_view  # type: ignore[attr-defined]

        def resize(event) -> None:
            viewport.itemconfigure("inner", width=event.width)

        viewport.bind("<Configure>", resize, add="+")
        inner.bind("<Configure>", lambda _e: viewport.configure(scrollregion=(0, 0, inner.winfo_reqwidth(), inner.winfo_reqheight())), add="+")
        viewport.bind("<MouseWheel>", lambda e: (viewport.yview_scroll(int(-e.delta / 40) or (-1 if e.delta > 0 else 1), "units"), "break")[1], add="+")

        def refresh(*_args) -> None:
            items = store.search(var.get(), pool)
            listing.set_items(items)
            shown = min(len(items), MAX_ROWS)
            count.configure(text="Keine Treffer" if not items else (f"{len(items)} Kundenakten" if shown == len(items) else f"{shown} von {len(items)} – Suche verfeinern"))
            viewport.yview_moveto(0)

        job = {"id": None}

        def debounced(*_args) -> None:
            if job["id"] is not None:
                try:
                    holder.after_cancel(job["id"])
                except tk.TclError:
                    pass
            job["id"] = holder.after(180, refresh)

        var.trace_add("write", debounced)
        refresh()
        widgets["refresh"] = refresh

    dialog = dialogs.ContentDialog(parent, title, message, primary="Übernehmen", close="Abbrechen", build=build, icon=ICON_FILE, width=520)
    dialog.buttons[dialogs.PRIMARY].set_enabled(False)
    field = widgets.get("field")
    listing = widgets.get("list")
    if field is not None:
        field.entry.bind("<KeyPress-Down>", lambda _e: (listing.focus_set(), listing.select(0), "break")[2], add="+")
        field.entry.bind("<Return>", lambda _e: (listing.select(0), listing.open_selected(), "break")[2] if listing.items else None, add="+")
        dialog.focus_widget = field.entry
    elif listing is not None:
        dialog.focus_widget = listing
    answer = dialog.show()
    if dialogs.AUTO_ANSWER is not None:  # Tests: erster Treffer
        return pool[0].id if pool and answer == dialogs.PRIMARY else None
    return chosen["id"] if answer == dialogs.PRIMARY else None


def ask_new_customer(parent, company: str, number: str, email: str, hints: Sequence[str] = ()) -> tuple[bool, bool]:
    """Kundenakte anlegen? Rückgabe (anlegen, E-Mail-Zuordnung merken)."""
    remember = tk.BooleanVar(parent, bool(email))

    def build(holder) -> None:
        Text(holder, f"{company or 'Ohne Namen'} · Kundennummer {number or '–'}", style="body_strong", wrap=True).pack(anchor="w", fill="x")
        if email:
            row = frame(holder)
            row.pack(fill="x", pady=(px(12), 0))
            ToggleSwitch(row, remember, show_text=False).pack(side="left")
            Text(row, f"Zuordnung merken: {email} künftig diesem Kunden zuordnen", style="body", wrap=True).pack(side="left", fill="x", expand=True, padx=(px(10), 0))
        for hint in hints:
            Text(holder, hint, style="caption", color="caution", wrap=True).pack(anchor="w", fill="x", pady=(px(8), 0))
        Text(holder, "Kundendaten werden ausschließlich lokal auf diesem PC gespeichert.", style="caption", color="text2", wrap=True).pack(anchor="w", fill="x", pady=(px(12), 0))

    message = "Firmenname, Kundennummer, Logo, Zielordner, Vorlage sowie Kopf- und Fußzeile werden als Kundenakte gespeichert."
    dialog = dialogs.ContentDialog(parent, "Als Kundenakte speichern", message, primary="Speichern", close="Abbrechen", build=build, icon=ICON_FILE, width=500, default=dialogs.PRIMARY)
    answer = dialog.show()
    return answer == dialogs.PRIMARY, bool(remember.get()) and bool(email)


def ask_email_conflict(parent, email: str, owners: Sequence[Customer], target_label: str) -> str:
    """Konflikt: Adresse gehört schon einer anderen Kundenakte. Rückgabe »move«, »keep« oder »cancel«."""
    names = ", ".join(f"„{owner.label}“" for owner in owners)
    dialog = dialogs.ContentDialog(
        parent,
        "E-Mail bereits zugeordnet",
        f"Diese E-Mail ist bereits der Kundenakte {names} zugeordnet:\n{email}\n\n"
        f"»Zuordnung verschieben« ordnet sie „{target_label}“ zu. »Bestehende Zuordnung verwenden« lässt sie bei {names}.",
        primary="Zuordnung verschieben",
        secondary="Bestehende Zuordnung verwenden",
        close="Abbrechen",
        default=dialogs.CLOSE,
        icon=ICON_FILE,
        width=520,
    )
    answer = dialog.show()
    return {dialogs.PRIMARY: "move", dialogs.SECONDARY: "keep"}.get(answer, "cancel")


def ask_customer_update(parent, label: str, changes: Sequence[tuple[str, str, str, str]]) -> list[str]:
    """»Kundenakte aktualisieren«: Abweichungen einzeln wählbar. ``changes``: (Schlüssel, Feld, bisher, neu).

    Rückgabe: gewählte Schlüssel (leer bei Abbruch).
    """
    chosen = {key: tk.BooleanVar(parent, True) for key, _field, _old, _new in changes}

    def build(holder) -> None:
        for index, (key, name, old, new) in enumerate(changes):
            row = frame(holder)
            row.pack(fill="x", pady=(0 if index == 0 else px(8), 0))
            ToggleSwitch(row, chosen[key], show_text=False).pack(side="left", anchor="n")
            texts = frame(row)
            texts.pack(side="left", fill="x", expand=True, padx=(px(10), 0))
            Text(texts, name, style="body_strong").pack(anchor="w")
            Text(texts, f"{old}  →  {new}", style="caption", color="text2", wrap=True, wrap_width=380).pack(anchor="w", fill="x")
        Text(holder, "Nur gewählte Angaben werden in der Kundenakte gespeichert. PDF- und Excel-Dateien bleiben unberührt.", style="caption", color="text2", wrap=True).pack(anchor="w", fill="x", pady=(px(14), 0))

    dialog = dialogs.ContentDialog(parent, "Kundenakte aktualisieren", f"Diese Angaben der aktuellen Übersicht in „{label}“ übernehmen:", primary="Speichern", close="Abbrechen", build=build, icon=ICON_FILE, width=520)
    if dialog.show() != dialogs.PRIMARY:
        return []
    return [key for key, _field, _old, _new in changes if chosen[key].get()]


def ask_customer_fields(parent) -> tuple[str, str, str] | None:
    """»Neue Kundenakte«: Firmenname, Kundennummer und optional eine E-Mail-Adresse."""
    company = tk.StringVar(parent, "")
    number = tk.StringVar(parent, "")
    email = tk.StringVar(parent, "")
    fields: dict = {}

    def build(holder) -> None:
        for index, (label, var, hint) in enumerate(
            (("Firmenname", company, "z. B. Muster GmbH"), ("Kundennummer", number, "z. B. 10042"), ("Rechnungsempfänger-E-Mail (optional)", email, "rechnung@kunde.de"))
        ):
            Text(holder, label, style="body").pack(anchor="w", pady=(0 if index == 0 else px(10), px(4)))
            field = TextField(holder, var, placeholder=hint, width=400)
            field.pack(fill="x")
            fields.setdefault("first", field)
        Text(holder, "Kundendaten werden ausschließlich lokal auf diesem PC gespeichert.", style="caption", color="text2", wrap=True).pack(anchor="w", fill="x", pady=(px(12), 0))

    dialog = dialogs.ContentDialog(parent, "Neue Kundenakte", None, primary="Anlegen", close="Abbrechen", build=build, icon=ICON_FILE, width=480)
    if "first" in fields:
        dialog.focus_widget = fields["first"].entry
    if dialog.show() != dialogs.PRIMARY:
        return None
    return company.get().strip(), number.get().strip(), email.get().strip()
