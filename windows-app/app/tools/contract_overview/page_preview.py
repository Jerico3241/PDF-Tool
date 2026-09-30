"""Vertragsübersichten – Ansicht »Vorschau«: die PDF so, wie »PDF erstellen« sie erzeugt.

Seiten blättern (Bild ↑/↓, ←/→), zoomen (+/−, »An Breite anpassen«) und breite Seiten mit
der Maus verschieben. Erzeugt wird im Hintergrund – siehe ``preview``.
"""

from __future__ import annotations

import time
import tkinter as tk
from typing import TYPE_CHECKING

from ui import diagnostics, icons
from ui.components import SelectorBar
from ui.context import bind_size, ctx, surface_color
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
        self._data: bytes | None = None  # Bilddaten des gezeigten Bildes (gleiche Daten: nicht neu dekodieren)
        self.decoded = 0  # dekodierte Seitenbilder (Tests, Diagnose)
        self._size = (0, 0)
        self._offset = 0  # horizontale Verschiebung, wenn die Seite breiter ist als die Ansicht
        self._drag: tuple[int, int] | None = None
        self._width = 0
        self.shown_page: tuple | None = None
        self._frame = self.create_rectangle(0, 0, 0, 0, width=1, state="hidden")
        self._image = self.create_image(0, 0, anchor="nw", state="hidden")
        bind_size(self, self._configured)
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
        if data is not self._data or self._photo is None:
            # Nur ein neues Bild wird dekodiert – dieselbe Seite (z. B. beim erneuten Öffnen) bleibt stehen.
            self._photo = tk.PhotoImage(master=self, data=data)
            self._data = data
            self.decoded += 1
            diagnostics.count("preview_decode")
            self.itemconfigure(self._image, image=self._photo)
        self.itemconfigure(self._image, state="normal")
        self.itemconfigure(self._frame, state="normal")
        if (width, height) != self._size:
            self._offset = 0
        self._size = (width, height)
        self.shown_page = page
        wanted = height + 2 * self.MARGIN
        if int(self.cget("height")) != wanted:
            self.configure(height=wanted)
        self._layout()

    def reserve(self, width: int, height: int) -> None:
        """Platz für eine Seite freihalten, deren Bild noch entsteht (kein Layoutsprung beim Eintreffen).

        Nur ohne gezeigtes Bild: Ein vorhandenes Bild bleibt stehen, bis das neue fertig ist.
        """
        if self._photo is not None or width <= 1 or height <= 1:
            return
        self._size = (width, height)
        self.itemconfigure(self._frame, state="normal")
        wanted = height + 2 * self.MARGIN
        if int(self.cget("height")) != wanted:
            self.configure(height=wanted)
        self._layout()

    def release(self) -> None:
        """Freigehaltenen Platz ohne Bild aufgeben (die Vorschau konnte nicht entstehen)."""
        if self._photo is None:
            self.clear()

    def clear(self) -> None:
        self._photo = None
        self._data = None
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


def steady_width(label: Text, *samples: str) -> None:
    """Feste Breite für eine wechselnde Beschriftung (Tk zählt in Zeichen der Ziffer »0«).

    Sonst verschiebt »Seite –« → »Seite 1 von 3« alles, was in der Leiste danach kommt.
    """
    font = ctx().fonts.body
    zero = max(1, font.measure("0"))
    label.configure(width=max(-(-font.measure(sample) // zero) for sample in samples), anchor="center")


class PreviewTools:
    """Werkzeugleiste: Seiten, Zoom, Aktualisieren und Zustand der Vorschau."""

    def __init__(self, master, app: "App") -> None:
        self.row = FlowRow(master, gap=6, row_gap=8)
        pages = frame(self.row)
        self.prev = IconButton(pages, icons.CHEVRON_LEFT, lambda: app.preview_step(-1), tooltip="Vorherige Seite (Bild ↑)")
        self.prev.pack(side="left")
        self.page_text = Text(pages, "Seite –", style="body")
        steady_width(self.page_text, "Seite 88 von 88")
        self.page_text.pack(side="left", padx=px(8))
        self.next = IconButton(pages, icons.CHEVRON_RIGHT, lambda: app.preview_step(1), tooltip="Nächste Seite (Bild ↓)")
        self.next.pack(side="left")
        self.row.add(pages)
        zoom = frame(self.row)
        self.zoom_out = IconButton(zoom, icons.ZOOM_OUT, lambda: app.preview_zoom(-1), tooltip="Verkleinern (−)")
        self.zoom_out.pack(side="left", padx=(px(12), 0))
        self.zoom_text = Text(zoom, "An Breite", style="body")
        steady_width(self.zoom_text, "An Breite", "300 %")
        self.zoom_text.pack(side="left", padx=px(8))
        self.zoom_in = IconButton(zoom, icons.ZOOM_IN, lambda: app.preview_zoom(1), tooltip="Vergrößern (+)")
        self.zoom_in.pack(side="left")
        self.row.add(zoom)
        self.fit = Button(self.row, "An Breite anpassen", lambda: app.preview_zoom(0), icon=icons.FIT_PAGE, kind="subtle", tooltip="Seite an die Breite der Ansicht anpassen (0)")
        self.row.add(self.fit)
        self.refresh = Button(self.row, "Aktualisieren", lambda: app.refresh_preview(force=True), icon=icons.REFRESH, tooltip="Vorschau neu erzeugen (z. B. nach Änderungen an der Excel-Datei)")
        self.row.add(self.refresh)
        # Zustand in eigener Zeile: Sein Text wechselt in der Länge (»Vorschau wird erstellt …«,
        # »Aktuell · …«) und würde die Leiste sonst je nach Zustand umbrechen – die Seite spränge.
        self.state = frame(master)
        self.ring = ProgressRing(self.state, size=16)
        self.ring.pack(side="left", padx=(0, px(8)))
        self.state_text = Text(self.state, "", style="caption", color="text2")
        self.state_text.pack(side="left")

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
        if self.state_text.cget("text") != text:  # nur bei echter Änderung neu zeichnen
            self.state_text.configure(text=text)


class PreviewView:
    """Inhalt der Ansicht: Werkzeugleiste, Hinweis, leerer Zustand oder Seitenbild."""

    def __init__(self, app: "App", page: Page) -> None:
        self.app = app
        ui = app.ui
        # Aus dem Stapel geöffnet: welcher Eintrag gezeigt wird (sonst unsichtbar)
        ui.preview_source = InfoBar(page.content, closable=False)
        page.add_section(ui.preview_source, pady=(0, px(8)))
        self.tools = PreviewTools(page.content, app)
        page.add_section(self.tools.row)
        page.add_section(self.tools.state, pady=(px(8), 0))
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
        self.tools.state.pack_forget()  # ohne Vorschau gibt es keinen Zustand zu zeigen
        self.state = "empty"

    def set_state(self, state: str, problem: str = "") -> None:
        self.state = state
        app = self.app
        if state == "empty":
            self.canvas.pack_forget()
            self.tools.state.pack_forget()
            if not self.empty.winfo_manager():
                self.empty.pack(fill="x", pady=(px(12), 0))
            self.empty_reason.configure(text=problem or "")
            self.tools.set_busy(False, "")
            app.hide_notice("preview_info")
            return
        if self.empty.winfo_manager():
            self.empty.pack_forget()
        if not self.tools.state.winfo_manager():
            self.tools.state.pack(fill="x", anchor="n", pady=(px(8), 0), after=self.tools.row)
        if not self.canvas.winfo_manager():
            self.canvas.pack(fill="x", pady=(px(8), 0))
        if state == "busy":
            self.tools.set_busy(True, "Vorschau wird erstellt …")
        elif state == "stale":
            self.tools.set_busy(True, "Änderungen – Vorschau wird aktualisiert …")
        elif state == "current":
            doc = app._preview_doc
            placeholder = app.var_kd.get().strip() == "" and doc is not None
            note = f" · Kundennummer fehlt (in der Vorschau »{PLACEHOLDER_KD}«)" if placeholder else ""
            # Zeit der Erzeugung – ein erneutes Öffnen ohne Änderung erzeugt nichts neu und ändert nichts.
            built = time.localtime(doc.created) if doc is not None else time.localtime()
            self.tools.set_busy(False, f"Aktuell · {time.strftime('%H:%M:%S', built)}{note}")
            app.hide_notice("preview_info")
        elif state == "error":
            self.canvas.release()  # kein leerer Seitenrahmen unter der Fehlermeldung
            self.tools.set_busy(False, "Vorschau nicht möglich")
            app.notify("preview_info", "error", problem or "Unbekannter Fehler", title="Vorschau konnte nicht erstellt werden", status=False)


def build(app: "App", host) -> Page:
    ui = app.ui
    page = Page(host, TITLE, "Vorschau: die PDF so, wie sie erstellt wird – aktualisiert sich bei jeder Änderung.")
    ui.selector_preview = SelectorBar(page.content, VIEWS, "preview", lambda key: app.nav.navigate(key))
    page.add_section(ui.selector_preview, fill="none", anchor="w", pady=(0, px(16)))
    ui.preview_view = PreviewView(app, page)
    ui.preview_page = page
    # Vor dem Zeigen (noch verdeckt) prüfen, ob die Vorschau aktuell ist – gezeigt wird das fertige Bild.
    page.on("prepare", app.preview_shown)
    return page
