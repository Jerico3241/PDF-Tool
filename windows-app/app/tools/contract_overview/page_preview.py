"""Vertragsübersichten – Ansicht »Vorschau«: die PDF so, wie »PDF erstellen« sie erzeugt.

Seiten blättern (Bild ↑/↓, ←/→), zoomen (+/−, »An Breite anpassen«) und breite Seiten mit
der Maus verschieben. Erzeugt wird im Hintergrund – siehe ``preview``.
"""

from __future__ import annotations

import time
import tkinter as tk
from typing import TYPE_CHECKING

from ui import icons
from ui.components import SelectorBar
from ui.context import ctx, surface_color
from ui.navigation import Page
from ui.theme import px
from ui.widgets import Button, FlowRow, Icon, IconButton, InfoBar, ProgressRing, RoundedFrame, Text, frame

from .page_create import TITLE, VIEWS
from .preview import PLACEHOLDER_KD

if TYPE_CHECKING:
    from vertragdesk import App

EMPTY_TITLE = "Noch keine Vorschau"
EMPTY_HINT = "Die Vorschau erscheint, sobald eine geprüfte Excel-Liste mit aktiven Verträgen und ein Logo vorliegen. Eine fehlende Kundennummer steht hier als »–«."


class PreviewCanvas(tk.Canvas):
    """Zeigt eine Seite als Bild – zentriert, mit Rahmen; breite Seiten lassen sich verschieben."""

    def __init__(self, master, app: "App", page: Page) -> None:
        super().__init__(master, highlightthickness=0, bd=0, takefocus=1, height=px(420))
        self.app = app
        self.page = page
        self.MARGIN = px(16)
        self._photo: tk.PhotoImage | None = None
        self._size = (0, 0)
        self._offset = 0  # horizontale Verschiebung, wenn die Seite breiter ist als die Ansicht
        self._drag: tuple[int, int] | None = None
        self._width = 0
        self.shown_page: tuple | None = None
        self._frame = self.create_rectangle(0, 0, 0, 0, width=1, state="hidden")
        self._image = self.create_image(0, 0, anchor="nw", state="hidden")
        self.bind("<Configure>", self._configured, add="+")
        self.bind("<ButtonPress-1>", self._press, add="+")
        self.bind("<B1-Motion>", self._motion, add="+")
        self.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_drag", None), add="+")
        self.bind("<Shift-MouseWheel>", lambda e: (self.pan(-e.delta // 2), "break")[1], add="+")
        for key, action in (
            ("Prior", lambda: app.preview_step(-1)),
            ("Next", lambda: app.preview_step(1)),
            ("Home", lambda: app.preview_goto(0)),
            ("End", lambda: app.preview_goto(10**6)),
            ("plus", lambda: app.preview_zoom(1)),
            ("KP_Add", lambda: app.preview_zoom(1)),
            ("minus", lambda: app.preview_zoom(-1)),
            ("KP_Subtract", lambda: app.preview_zoom(-1)),
            ("0", lambda: app.preview_zoom(0)),
            ("Left", lambda: self.pan(-px(60))),
            ("Right", lambda: self.pan(px(60))),
        ):
            self.bind(f"<KeyPress-{key}>", lambda _e, a=action: (a(), "break")[1], add="+")
        ctx().theme.subscribe(self._theme_changed, owner=self)
        self._theme_changed()

    def _theme_changed(self) -> None:
        pal = ctx().pal
        self.configure(bg=surface_color(self.master))
        self.itemconfigure(self._frame, outline=pal.card_stroke, fill=pal.card)

    def view_width(self) -> int:
        return max(1, self._width or self.winfo_width())

    def _configured(self, event) -> None:
        if event.width != self._width:
            self._width = event.width
            self._layout()
            self.app.preview_resized()

    def show(self, data: bytes, width: int, height: int, page: tuple | None = None) -> None:
        self._photo = tk.PhotoImage(master=self, data=data)
        self.itemconfigure(self._image, image=self._photo, state="normal")
        self.itemconfigure(self._frame, state="normal")
        if (width, height) != self._size:
            self._offset = 0
        self._size = (width, height)
        self.shown_page = page
        wanted = height + 2 * self.MARGIN
        if int(self.cget("height")) != wanted:
            self.configure(height=wanted)
        self._layout()

    def clear(self) -> None:
        self._photo = None
        self._size = (0, 0)
        self.shown_page = None
        self.itemconfigure(self._image, image="", state="hidden")
        self.itemconfigure(self._frame, state="hidden")
        self.configure(height=px(1))

    def _layout(self) -> None:
        width, height = self._size
        if not width:
            return
        view = self.view_width()
        spare = view - width - 2 * self.MARGIN
        if spare >= 0:
            self._offset = 0
            x = spare // 2 + self.MARGIN
            self.configure(cursor="")
        else:
            self._offset = max(0, min(-spare, self._offset))
            x = self.MARGIN - self._offset
            self.configure(cursor="fleur")
        y = self.MARGIN
        self.coords(self._image, x, y)
        self.coords(self._frame, x - 1, y - 1, x + width, y + height)

    def pan(self, delta: int) -> None:
        self._offset += int(delta)
        self._layout()

    def _press(self, event) -> None:
        self.focus_set()
        self._drag = (event.x, self._offset)

    def _motion(self, event) -> None:
        if self._drag is not None:
            start_x, start_offset = self._drag
            self._offset = start_offset - (event.x - start_x)
            self._layout()

    def scroll_to_top(self) -> None:
        try:
            self.page.scroll.scroll_to_widget(self)
        except tk.TclError:
            pass


class PreviewTools:
    """Werkzeugleiste: Seiten, Zoom, Aktualisieren und Zustand der Vorschau."""

    def __init__(self, master, app: "App") -> None:
        self.row = FlowRow(master, gap=6, row_gap=8)
        pages = frame(self.row)
        self.prev = IconButton(pages, icons.CHEVRON_LEFT, lambda: app.preview_step(-1), tooltip="Vorherige Seite (Bild ↑)")
        self.prev.pack(side="left")
        self.page_text = Text(pages, "Seite –", style="body")
        self.page_text.pack(side="left", padx=px(8))
        self.next = IconButton(pages, icons.CHEVRON_RIGHT, lambda: app.preview_step(1), tooltip="Nächste Seite (Bild ↓)")
        self.next.pack(side="left")
        self.row.add(pages)
        zoom = frame(self.row)
        self.zoom_out = IconButton(zoom, icons.ZOOM_OUT, lambda: app.preview_zoom(-1), tooltip="Verkleinern (−)")
        self.zoom_out.pack(side="left", padx=(px(12), 0))
        self.zoom_text = Text(zoom, "An Breite", style="body")
        self.zoom_text.pack(side="left", padx=px(8))
        self.zoom_in = IconButton(zoom, icons.ZOOM_IN, lambda: app.preview_zoom(1), tooltip="Vergrößern (+)")
        self.zoom_in.pack(side="left")
        self.row.add(zoom)
        self.fit = Button(self.row, "An Breite anpassen", lambda: app.preview_zoom(0), icon=icons.FIT_PAGE, kind="subtle", tooltip="Seite an die Breite der Ansicht anpassen (0)")
        self.row.add(self.fit)
        self.refresh = Button(self.row, "Aktualisieren", lambda: app.refresh_preview(force=True), icon=icons.REFRESH, tooltip="Vorschau neu erzeugen (z. B. nach Änderungen an der Excel-Datei)")
        self.row.add(self.refresh)
        state = frame(self.row)
        self.ring = ProgressRing(state, size=16)
        self.ring.pack(side="left", padx=(px(12), px(8)))
        self.state_text = Text(state, "", style="caption", color="text2")
        self.state_text.pack(side="left")
        self.row.add(state)

    def update(self, app: "App") -> None:
        doc = app._preview_doc
        pages = doc.pages if doc is not None else 0
        index = app._preview_page
        self.page_text.configure(text=f"Seite {index + 1} von {pages}" if pages else "Seite –")
        self.prev.set_enabled(pages > 0 and index > 0)
        self.next.set_enabled(pages > 0 and index < pages - 1)
        zoom = app._preview_zoom
        self.zoom_text.configure(text="An Breite" if zoom is None else f"{round(zoom * 100)} %")
        self.fit.set_enabled(zoom is not None)
        for button in (self.zoom_in, self.zoom_out):
            button.set_enabled(pages > 0)

    def set_busy(self, busy: bool, text: str) -> None:
        if busy:
            self.ring.start()
        else:
            self.ring.stop()
        self.state_text.configure(text=text)


class PreviewView:
    """Inhalt der Ansicht: Werkzeugleiste, Hinweis, leerer Zustand oder Seitenbild."""

    def __init__(self, app: "App", page: Page) -> None:
        self.app = app
        ui = app.ui
        self.tools = PreviewTools(page.content, app)
        page.add_section(self.tools.row)
        ui.preview_tools = self.tools
        ui.preview_info = InfoBar(page.content)
        page.add_section(ui.preview_info, pady=(px(8), 0))
        self.empty = RoundedFrame(page.content, fill="card", stroke="card_stroke")
        inner = frame(self.empty)
        inner.pack(fill="x", padx=px(24), pady=px(28))
        if ctx().icons_available:
            Icon(inner, icons.VIEW, color="text2", size="icon_large").pack(anchor="w")
        Text(inner, EMPTY_TITLE, style="body_strong").pack(anchor="w", pady=(px(10), px(4)))
        self.empty_reason = Text(inner, "", style="body", color="caution", wrap=True)
        self.empty_reason.pack(anchor="w", fill="x")
        Text(inner, EMPTY_HINT, style="body", color="text2", wrap=True).pack(anchor="w", fill="x", pady=(px(6), 0))
        Button(inner, "Zu »Übersicht erstellen«", lambda: app.nav.navigate("create"), icon=icons.DOCUMENT, kind="accent").pack(anchor="w", pady=(px(14), 0))
        self.canvas = PreviewCanvas(page.content, app, page)
        ui.preview_canvas = self.canvas
        page.add_section(self.canvas, pady=(px(8), 0))
        self.empty.pack(fill="x", pady=(px(12), 0), before=self.canvas)
        self.canvas.pack_forget()
        self.state = "empty"

    def set_state(self, state: str, problem: str = "") -> None:
        self.state = state
        app = self.app
        if state == "empty":
            self.canvas.pack_forget()
            if not self.empty.winfo_manager():
                self.empty.pack(fill="x", pady=(px(12), 0))
            self.empty_reason.configure(text=problem or "")
            self.tools.set_busy(False, "")
            app.hide_notice("preview_info")
            return
        if self.empty.winfo_manager():
            self.empty.pack_forget()
        if not self.canvas.winfo_manager():
            self.canvas.pack(fill="x", pady=(px(8), 0))
        if state == "busy":
            self.tools.set_busy(True, "Vorschau wird erstellt …")
        elif state == "stale":
            self.tools.set_busy(True, "Änderungen – Vorschau wird aktualisiert …")
        elif state == "current":
            placeholder = app.var_kd.get().strip() == "" and app._preview_doc is not None
            note = f" · Kundennummer fehlt (in der Vorschau »{PLACEHOLDER_KD}«)" if placeholder else ""
            self.tools.set_busy(False, f"Aktuell · {time.strftime('%H:%M:%S')}{note}")
            app.hide_notice("preview_info")
        elif state == "error":
            self.tools.set_busy(False, "Vorschau nicht möglich")
            app.notify("preview_info", "error", problem or "Unbekannter Fehler", title="Vorschau konnte nicht erstellt werden", status=False)


def build(app: "App", host) -> Page:
    ui = app.ui
    page = Page(host, TITLE, "Vorschau: die PDF so, wie sie erstellt wird – aktualisiert sich bei jeder Änderung.")
    ui.selector_preview = SelectorBar(page.content, VIEWS, "preview", lambda key: app.nav.navigate(key))
    page.add_section(ui.selector_preview, fill="none", anchor="w", pady=(0, px(16)))
    ui.preview_view = PreviewView(app, page)
    ui.preview_page = page
    return page
