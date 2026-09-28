"""NavigationView nach Windows 11: Navigationsbereich links (Mica), Inhaltsebene rechts.

* Auswahlindikator in Akzentfarbe, der beim Seitenwechsel zur neuen Seite gleitet
* Kompaktmodus (nur Symbole) bei schmalen Fenstern oder per Menüschaltfläche
* Alle Seiten werden einmal beim Start aufgebaut und danach nur noch gewechselt.
  Eine Zielseite wird verdeckt fertig angeordnet und erst dann gezeigt; der
  Übergang bewegt die ganze Seite als Einheit (16 px von rechts).
* Responsive Layoutzustände (breit, mittel, kompakt) werden zentral aus der
  Fensterbreite bestimmt und nur beim Überschreiten eines Breakpoints gewechselt.
"""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass
from typing import Callable

from PIL import Image

from . import animations as motion
from . import icons
from .context import MODE_COMPACT, MODE_MEDIUM, MODE_WIDE, ctx, settle
from .render import rounded_box, to_photo
from .scroll import ScrollArea
from .theme import px
from .widgets import CONTROL_RADIUS, OVERLAY_RADIUS, ProgressRing, Surface, Text, Tooltip, frame

PANE_EXPANDED = 240
PANE_COMPACT = 48
ITEM_HEIGHT = 36
ITEM_GAP = 4
HEADER_HEIGHT = 32  # Abschnittsüberschrift, z. B. »Tools«

# Breakpoints (effektive Pixel Fensterbreite), abgestimmt auf die Kartenbreiten der Seiten.
# Ab 1008 px ist die Navigation ausgeklappt (wie WinUI »ExpandedModeThresholdWidth«).
WIDE_FROM = 1008
MEDIUM_FROM = 820
BREAKPOINT_HYSTERESIS = 8
# Mindestbreite des Seiteninhalts für zwei Kartenspalten
TWO_COLUMNS_FROM = 680
COLUMNS_HYSTERESIS = 12
PAGE_PADDING = (36, 28)  # links, rechts
COMPACT_BELOW = WIDE_FROM  # früherer Name
# Nicht sichtbare Seiten liegen fertig angeordnet außerhalb des sichtbaren Bereichs.
PARK_X = -20000


@dataclass
class NavItem:
    """Eintrag der Navigation. Ein Werkzeug kann mehrere Seiten haben (``pages``);
    ``header`` kennzeichnet eine nicht auswählbare Abschnittsüberschrift."""

    key: str
    label: str
    glyph: str = ""
    footer: bool = False
    pages: tuple[str, ...] = ()
    header: bool = False

    def owns(self, page: str) -> bool:
        return page == self.key or page in self.pages


class NavigationPane(tk.Canvas):
    """Navigationsbereich. Alle Canvas-Elemente bestehen dauerhaft und werden nur angepasst."""

    def __init__(self, master, items: list[NavItem], on_select: Callable[[str], None], on_toggle: Callable[[], None], title: str = "") -> None:
        self.c = ctx()
        super().__init__(master, width=px(PANE_EXPANDED), highlightthickness=0, bd=0, takefocus=1)
        self.surface_role = "mica"
        self.items = items
        self.title = title
        self.on_select = on_select
        self.on_toggle = on_toggle
        self.selected: str | None = None
        self.hover: str | None = None
        self.pressed: str | None = None
        self.focus_key: str | None = None
        self.expanded_amount = 1.0
        self._indicator_y: float | None = None
        self._indicator_h = float(px(16))
        self._backdrop_img: tk.PhotoImage | None = None
        self._height = 0
        self._applied: dict[int, tuple] = {}
        self._backdrop = self.create_image(0, 0, anchor="nw", state="hidden")
        self._slots: dict[str, dict[str, int]] = {"__toggle__": self._make_slot()}
        for item in items:
            self._slots[item.key] = self._make_header_slot() if item.header else self._make_slot()
        self._title_item = self.create_text(0, 0, text=title, anchor="w", state="hidden")
        self._pill = self.create_image(0, 0, anchor="w", state="hidden")
        self._tooltip = Tooltip(self, "")
        self._tooltip_key: str | None = None
        self.configure(bg=self.c.pal.mica)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", self._configured)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", lambda _e: self.redraw())
        for key, delta in (("Up", -1), ("Down", 1)):
            self.bind(f"<KeyPress-{key}>", lambda _e, d=delta: self._move_focus(d))
        for key in ("Return", "space", "KP_Enter"):
            self.bind(f"<KeyPress-{key}>", lambda _e: self._activate_focus())
        self.c.theme.subscribe(self._theme_changed, owner=self)
        self.c.on_focus_mode(self, self.redraw)

    def _make_slot(self) -> dict[str, int]:
        return {
            "overlay": self.create_image(0, 0, anchor="nw", state="hidden"),
            "icon": self.create_text(0, 0, text="", anchor="center"),
            "label": self.create_text(0, 0, text="", anchor="w", state="hidden"),
            "focus": self.create_image(0, 0, anchor="nw", state="hidden"),
        }

    def _make_header_slot(self) -> dict[str, int]:
        return {
            "label": self.create_text(0, 0, text="", anchor="w", state="hidden"),
            "line": self.create_line(0, 0, 0, 0, state="hidden"),
        }

    def _selectable(self) -> list[NavItem]:
        return [item for item in self.items if not item.header]

    def _theme_changed(self) -> None:
        self.configure(bg=self.c.pal.mica)
        self.redraw()

    def _configured(self, event) -> None:
        # Die Breite steuert NavigationView über expanded_amount; neu zu zeichnen ist nur
        # bei geänderter Höhe (Position der unteren Einträge).
        if event.height != self._height:
            self._height = event.height
            self.redraw()

    # Geometrie ----------------------------------------------------------------
    def visual_width(self) -> int:
        return int(round(px(PANE_COMPACT) + (px(PANE_EXPANDED) - px(PANE_COMPACT)) * self.expanded_amount))

    def _toggle_rect(self) -> tuple[int, int, int, int]:
        x0 = px(4)
        y0 = px(4)
        return x0, y0, x0 + px(40), y0 + px(ITEM_HEIGHT)

    def _item_rects(self) -> dict[str, tuple[int, int, int, int]]:
        width = self.visual_width()
        height = max(self._height, self.winfo_height())
        rects = {}
        y = px(4) + px(ITEM_HEIGHT) + px(8)
        top_items = [item for item in self.items if not item.footer]
        foot_items = [item for item in self.items if item.footer]
        for item in top_items:
            item_h = px(HEADER_HEIGHT) if item.header else px(ITEM_HEIGHT)
            rects[item.key] = (px(4), y, width - px(4), y + item_h)
            y += item_h + px(ITEM_GAP)
        y = height - px(4) - px(ITEM_HEIGHT)
        for item in reversed(foot_items):
            rects[item.key] = (px(4), y, width - px(4), y + px(ITEM_HEIGHT))
            y -= px(ITEM_HEIGHT) + px(ITEM_GAP)
        return rects

    def _hit(self, x: int, y: int) -> str | None:
        tx0, ty0, tx1, ty1 = self._toggle_rect()
        if tx0 <= x < tx1 and ty0 <= y < ty1:
            return "__toggle__"
        headers = {item.key for item in self.items if item.header}
        for key, (x0, y0, x1, y1) in self._item_rects().items():
            if key not in headers and x0 <= x < x1 and y0 <= y < y1:
                return key
        return None

    # Hintergrund -------------------------------------------------------------------
    def set_backdrop(self, photo: tk.PhotoImage | None) -> None:
        self._backdrop_img = photo
        if photo is None:
            self.itemconfigure(self._backdrop, state="hidden")
        else:
            self.itemconfigure(self._backdrop, image=photo, state="normal")

    # Ereignisse -----------------------------------------------------------------------
    def _motion(self, event) -> None:
        key = self._hit(event.x, event.y)
        if key != self.hover:
            self.hover = key
            self.redraw()
            self._update_tooltip()

    def _update_tooltip(self) -> None:
        self._tooltip.hide()
        label = ""
        if self.hover == "__toggle__":
            label = "Navigation einklappen" if self.expanded_amount > 0.5 else "Navigation ausklappen"
        elif self.hover and self.expanded_amount < 0.5:
            label = next((item.label for item in self.items if item.key == self.hover), "")
        self._tooltip.text = label
        if label:
            self._tooltip._schedule()

    def _leave(self, _event=None) -> None:
        self.hover = None
        self.pressed = None
        self._tooltip.hide()
        self.redraw()

    def _press(self, event) -> None:
        self.pressed = self._hit(event.x, event.y)
        self._tooltip.hide()
        self.redraw()

    def _release(self, event) -> None:
        key = self._hit(event.x, event.y)
        pressed = self.pressed
        self.pressed = None
        if key and key == pressed:
            if key == "__toggle__":
                self.on_toggle()
            else:
                self.on_select(key)
        self.redraw()

    def _focus_in(self, _event=None) -> None:
        if self.focus_key is None:
            selectable = self._selectable()
            self.focus_key = self.selected or (selectable[0].key if selectable else None)
        self.redraw()

    def _order(self) -> list[str]:
        selectable = self._selectable()
        return ["__toggle__"] + [item.key for item in selectable if not item.footer] + [item.key for item in selectable if item.footer]

    def _move_focus(self, delta: int) -> str:
        order = self._order()
        current = self.focus_key if self.focus_key in order else (self.selected or order[0])
        self.focus_key = order[(order.index(current) + delta) % len(order)]
        self.redraw()
        return "break"

    def _activate_focus(self) -> str:
        if self.focus_key == "__toggle__":
            self.on_toggle()
        elif self.focus_key:
            self.on_select(self.focus_key)
        return "break"

    # Auswahl mit Indikator-Animation ------------------------------------------------------------
    def select(self, key: str, animate: bool = True) -> None:
        rects = self._item_rects()
        old = self.selected
        self.selected = key
        self.focus_key = key
        if key not in rects:
            self.redraw()
            return
        target = (rects[key][1] + rects[key][3]) / 2
        if old is None or self._indicator_y is None or not animate:
            self.c.anim.cancel(f"navind:{self}")
            self._indicator_y = target
            self._indicator_h = float(px(16))
            self.redraw()
            return
        start = self._indicator_y
        distance = abs(target - start)

        def step(t: float) -> None:
            self._indicator_y = start + (target - start) * t
            # In der Mitte der Bewegung wird der Indikator gestreckt (wie in WinUI).
            self._indicator_h = px(16) + min(distance * 0.5, px(28)) * math.sin(math.pi * t)
            self.redraw()

        self.c.anim.run(f"navind:{self}", motion.PAGE, step, easing=motion.POINT_TO_POINT, widget=self)

    # Zeichnen ----------------------------------------------------------------------
    def _set(self, item: int, coords: tuple | None = None, **options) -> None:
        """itemconfigure/coords nur bei tatsächlicher Änderung (vermeidet unnötiges Neuzeichnen)."""
        state = (coords, tuple(sorted((k, str(v)) for k, v in options.items())))
        if self._applied.get(item) == state:
            return
        self._applied[item] = state
        if coords is not None:
            self.coords(item, *coords)
        if options:
            self.itemconfigure(item, **options)

    def _paint_slot(self, slot: dict[str, int], rect: tuple, overlay: str | None, glyph: str, label: str | None, show_label: bool, focused: bool) -> None:
        c = self.c
        pal = c.pal
        x0, y0, x1, y1 = rect
        radius = px(CONTROL_RADIUS)
        if overlay:
            alpha = pal.subtle_pressed_alpha if overlay == "pressed" else pal.subtle_hover_alpha
            img = c.images.box(x1 - x0, y1 - y0, radius, pal.subtle_color, alpha=alpha)
            self._set(slot["overlay"], (x0, y0), image=img, state="normal")
        else:
            self._set(slot["overlay"], None, state="hidden")
        cy = (y0 + y1) / 2
        if c.icons_available:
            self._set(slot["icon"], (x0 + px(20), cy), text=glyph, font=c.fonts.icon, fill=pal.text, state="normal")
        elif label is None:
            self._set(slot["icon"], ((x0 + x1) / 2, cy), text="≡", font=c.fonts.body_large, fill=pal.text, state="normal")
        elif not show_label:
            self._set(slot["icon"], (x0 + px(20), cy), text=label[:1], font=c.fonts.body_strong, fill=pal.text, state="normal")
        else:
            self._set(slot["icon"], None, state="hidden")
        if label is not None and show_label:
            label_x = x0 + (px(44) if c.icons_available else px(12))
            self._set(slot["label"], (label_x, cy), text=label, font=c.fonts.body, fill=pal.text, state="normal")
        else:
            self._set(slot["label"], None, state="hidden")
        if focused:
            ring = c.images.ring(x1 - x0 + px(6), y1 - y0 + px(6), radius + px(3), pal.focus_outer, pal.focus_inner)
            self._set(slot["focus"], (x0 - px(3), y0 - px(3)), image=ring, state="normal")
        else:
            self._set(slot["focus"], None, state="hidden")

    def _paint_header(self, slot: dict[str, int], rect: tuple, label: str, show_label: bool) -> None:
        """Abschnittsüberschrift: ausgeklappt als Text, eingeklappt als Trennlinie (wie WinUI)."""
        pal = self.c.pal
        x0, y0, x1, y1 = rect
        cy = (y0 + y1) / 2 + px(4)
        if show_label:
            self._set(slot["label"], (x0 + px(12), cy), text=label, font=self.c.fonts.body_strong, fill=pal.text2, state="normal")
            self._set(slot["line"], None, state="hidden")
        else:
            self._set(slot["label"], None, state="hidden")
            self._set(slot["line"], (x0 + px(8), cy, x1 - px(8), cy), fill=pal.divider, width=1, state="normal")

    def redraw(self) -> None:
        c = self.c
        try:
            keyboard = c.keyboard_mode and self.focus_get() is self
        except (tk.TclError, KeyError):
            keyboard = False

        def overlay_state(key: str) -> str | None:
            if key == self.pressed or (key == self.selected and key == self.hover):
                return "pressed" if key == self.pressed else "hover"
            if key == self.selected or key == self.hover:
                return "hover"
            return None

        toggle_overlay = "pressed" if self.pressed == "__toggle__" else ("hover" if self.hover == "__toggle__" else None)
        toggle = self._toggle_rect()
        self._paint_slot(self._slots["__toggle__"], toggle, toggle_overlay, icons.GLOBAL_NAV, None, False, keyboard and self.focus_key == "__toggle__")
        rects = self._item_rects()
        show_labels = self.expanded_amount > 0.55
        if self.title and show_labels:
            self._set(self._title_item, (toggle[2] + px(8), (toggle[1] + toggle[3]) / 2), text=self.title, font=c.fonts.body, fill=c.pal.text, state="normal")
        else:
            self._set(self._title_item, None, state="hidden")
        for item in self.items:
            if item.header:
                self._paint_header(self._slots[item.key], rects[item.key], item.label, show_labels)
                continue
            self._paint_slot(self._slots[item.key], rects[item.key], overlay_state(item.key), item.glyph, item.label, show_labels, keyboard and self.focus_key == item.key)
        if self.selected in rects and not c.anim.running(f"navind:{self}"):
            sel = rects[self.selected]
            self._indicator_y = (sel[1] + sel[3]) / 2
            self._indicator_h = float(px(16))
        if self.selected in rects and self._indicator_y is not None:
            x0 = rects[self.selected][0]
            h = max(px(8), int(self._indicator_h))
            pill = c.images.box(px(3), h, px(1.5), c.pal.accent)
            self._set(self._pill, (x0, self._indicator_y), image=pill, state="normal")
        else:
            self._set(self._pill, None, state="hidden")


class ContentLayer(Surface):
    """Inhaltsebene rechts: leicht hellere Fläche mit runder Ecke oben links (WinUI-Layer)."""

    def __init__(self, master) -> None:
        super().__init__(master, role="layer")
        self._corner = tk.Canvas(self, width=px(OVERLAY_RADIUS), height=px(OVERLAY_RADIUS), highlightthickness=0, bd=0)
        self._corner_item = self._corner.create_image(0, 0, anchor="nw")
        self._corner_img = None
        self._top = tk.Frame(self, height=1, bd=0)
        self._left = tk.Frame(self, width=1, bd=0)
        self._top.place(x=px(OVERLAY_RADIUS), y=0, relwidth=1.0, height=1)
        self._left.place(x=0, y=px(OVERLAY_RADIUS), width=1, relheight=1.0)
        self._corner.place(x=0, y=0)
        self._mica_corner: Image.Image | None = None
        ctx().theme.subscribe(self.refresh_corner, owner=self)
        self.refresh_corner()

    def set_mica_corner(self, image: Image.Image | None) -> None:
        self._mica_corner = image
        self.refresh_corner()

    def refresh_corner(self) -> None:
        pal = ctx().pal
        self._top.configure(bg=pal.layer_stroke)
        self._left.configure(bg=pal.layer_stroke)
        r = px(OVERLAY_RADIUS)
        shape = rounded_box(r * 2, r * 2, r, pal.layer, pal.layer_stroke).crop((0, 0, r, r))
        base = self._mica_corner.convert("RGBA").resize((r, r)) if self._mica_corner is not None else Image.new("RGBA", (r, r), pal.mica)
        base.alpha_composite(shape)
        self._corner.configure(bg=pal.mica)
        self._corner_img = to_photo(self, base.convert("RGB"))
        self._corner.itemconfigure(self._corner_item, image=self._corner_img)
        tk.Misc.lift(self._corner)
        self._top.lift()
        self._left.lift()


class Page(tk.Frame):
    """Seite mit Titel, Untertitel und Abschnitten. Wird einmal aufgebaut und bleibt bestehen."""

    MAX_WIDTH = 1180

    def __init__(self, master, title: str, subtitle: str | None = None) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = "layer"
        ctx().theme.style(self, bg="layer")
        self.scroll = ScrollArea(self, max_width=self.MAX_WIDTH)
        self.scroll.pack(fill="both", expand=True)
        self.content = frame(self.scroll.body)
        self.content.pack(fill="both", expand=True, padx=(px(PAGE_PADDING[0]), px(PAGE_PADDING[1])), pady=(px(28), px(28)))
        self._sections: list[tuple[tk.Widget, dict]] = []
        header = frame(self.content)
        Text(header, title, style="title").pack(anchor="w")
        if subtitle:
            Text(header, subtitle, style="body", color="text2").pack(anchor="w", pady=(px(2), 0))
        self.add_section(header, pady=(0, px(20)))

    def add_section(self, widget: tk.Widget, **pack) -> tk.Widget:
        options = {"fill": "x", "anchor": "n"}
        options.update(pack)
        widget.pack(**options)
        self._sections.append((widget, options))
        return widget

    def section_title(self, text: str) -> tk.Widget:
        label = Text(self.content, text, style="body_strong")
        return self.add_section(label, pady=(px(20), px(8)))

    def enter(self, animate: bool) -> None:
        """Übergang als Einheit: Die fertig aufgebaute Seite gleitet 16 px von rechts ein."""
        c = ctx()
        key = f"page:{self}"
        c.anim.cancel_prefix(key)
        self.scroll.to_top()
        if not animate or not c.anim.allowed():
            self.scroll.set_offset(0)
            return
        shift = px(16)

        def slide(t: float) -> None:
            self.scroll.set_offset(int(round(shift * (1 - t))))

        c.anim.run(f"{key}:slide", motion.PAGE, slide, easing=motion.DECELERATE, widget=self)

    def leave(self) -> None:
        ctx().anim.cancel_prefix(f"page:{self}")
        self.scroll.set_offset(0)


class StatusBar(Surface):
    """Statuszeile am unteren Rand der Inhaltsebene."""

    def __init__(self, master, hint: str = "") -> None:
        super().__init__(master, role="layer")
        c = ctx()
        line = tk.Frame(self, height=1, bd=0)
        c.theme.style(line, bg="divider")
        line.pack(fill="x", side="top")
        row = frame(self)
        row.pack(fill="x", padx=px(16), pady=(px(5), px(6)))
        self.ring = ProgressRing(row, size=14)
        self.icon = tk.Label(row, text="", bd=0, padx=0, pady=0, font=c.fonts.icon_small or c.fonts.caption)
        c.theme.style(self.icon, bg="layer", fg="text2")
        self.icon.pack(side="left", padx=(0, px(8)))
        # Die Tastenhinweise werden zuerst gepackt und behalten ihren Platz;
        # lange Meldungen werden gekürzt und stehen vollständig im Tooltip.
        self.hint = Text(row, hint, style="caption", color="text3", anchor="e")
        self.hint.pack(side="right", padx=(px(12), 0))
        self.label = Text(row, "Bereit", style="caption", color="text2", width=1)
        self.hint_text = hint
        self.label.pack(side="left", fill="x", expand=True)
        self.text = "Bereit"
        self._label_width = 0
        self._tooltip = Tooltip(self.label, "")
        self.label.bind("<Configure>", self._label_configured, add="+")
        self._kind = "neutral"
        c.theme.subscribe(self._recolor, owner=self)

    def set_hint(self, text: str) -> None:
        """Tastenhinweise rechts – je Seite passend (z. B. Strg+O öffnet eine Excel bzw. PDF)."""
        if text != self.hint_text:
            self.hint_text = text
            self.hint.configure(text=text)
            if text and not self.hint.winfo_manager():
                self.hint.pack(side="right", padx=(px(12), 0), before=self.label)
            elif not text and self.hint.winfo_manager():
                self.hint.pack_forget()

    def _label_configured(self, event) -> None:
        if event.width != self._label_width:
            self._label_width = event.width
            self._fit()

    def _fit(self) -> None:
        font = ctx().fonts.caption
        width = self.label.winfo_width()
        text = self.text
        if width > 1 and font.measure(text) > width:
            while text and font.measure(text + "…") > width:
                text = text[:-1]
            text = text.rstrip() + "…"
        if self.label.cget("text") != text:
            self.label.configure(text=text)
        self._tooltip.text = self.text if text != self.text else ""

    def set(self, text: str, kind: str = "neutral") -> None:
        c = ctx()
        self._kind = kind
        self.text = text
        self._fit()
        if kind == "busy":
            self.icon.pack_forget()
            if not self.ring.winfo_ismapped():
                self.ring.pack(side="left", padx=(0, px(8)), before=self.label)
            self.ring.start()
        else:
            self.ring.stop()
            self.ring.pack_forget()
            glyphs = {
                "success": icons.COMPLETED,
                "error": icons.WARNING,
                "warning": icons.WARNING,
                "info": icons.INFO,
            }
            glyph = glyphs.get(kind, "")
            if glyph and c.icons_available:
                self.icon.configure(text=glyph)
                if not self.icon.winfo_ismapped():
                    self.icon.pack(side="left", padx=(0, px(8)), before=self.label)
            else:
                self.icon.pack_forget()
        self._recolor()

    def _recolor(self) -> None:
        pal = ctx().pal
        color = {"success": pal.success, "error": pal.critical, "warning": pal.caution, "info": pal.accent}.get(self._kind, pal.text2)
        self.icon.configure(fg=color, bg=pal.layer)
        self.label.configure(fg=pal.critical if self._kind == "error" else pal.text2)


class NavigationView(tk.Frame):
    """Navigationsbereich und Inhaltsebene mit dauerhaft bestehenden Seiten.

    Aufbau: Hintergrund (Mica) · Inhaltsebene ab x = Breite der Navigation ·
    Navigationsbereich darüber. Beim Ein- und Ausklappen wird der Inhalt genau
    einmal auf seine Endposition angeordnet; animiert wird nur der
    Navigationsbereich, der dabei über der Inhaltsebene liegt.
    """

    PANE_MS = 180

    def __init__(
        self,
        master,
        items: list[NavItem],
        factories: dict[str, Callable[[tk.Misc], Page]],
        on_change: Callable[[str], None] | None = None,
        compact: bool = False,
        status_hint: str = "",
        on_layout: Callable[[], None] | None = None,
        title: str = "",
    ) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = "mica"
        c = ctx()
        c.theme.style(self, bg="mica")
        self.factories = factories
        self.items = items
        # zuletzt gezeigte Seite je Navigationseintrag (ein Werkzeug kann mehrere Seiten haben)
        self._last_page: dict[str, str] = {}
        self.pages: dict[str, Page] = {}
        self.current: str | None = None
        self.on_change = on_change
        self.on_layout = on_layout
        self.user_compact = compact
        self.user_expanded = False  # bei schmalem Fenster per Menüschaltfläche ausgeklappt
        self.mode = MODE_WIDE
        self._width = 0
        self._layer_x: int | None = None
        self._navigating = False
        self._pending: tuple[str, bool] | None = None
        # Hintergrund mit demselben Material wie der Navigationsbereich: Beim Ausklappen
        # entsteht so keine sichtbare Kante zwischen Navigation und Inhaltsebene.
        self.backdrop = tk.Canvas(self, highlightthickness=0, bd=0)
        self._backdrop_item = self.backdrop.create_image(0, 0, anchor="nw", state="hidden")
        self._backdrop_photo: tk.PhotoImage | None = None
        c.theme.style(self.backdrop, bg="mica")
        self.backdrop.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self.layer = ContentLayer(self)
        self.pane = NavigationPane(self, items, self._select_item, self.toggle_pane, title=title)
        self.host = Surface(self.layer, role="layer")
        self.host.pack(fill="both", expand=True, padx=(1, 0), pady=(1, 0))
        self.status = StatusBar(self.layer, status_hint)
        self.status.pack(fill="x", side="bottom", before=self.host, padx=(1, 0))
        self._apply_pane(animate=False)
        c.window_hooks.append(self._window_resized)
        # Alle Seiten sofort aufbauen (das Fenster ist dabei noch unsichtbar).
        for key in factories:
            self.page(key)

    # Seiten -----------------------------------------------------------------
    def page(self, key: str) -> Page:
        if key not in self.pages:
            page = self.factories[key](self.host)
            self.pages[key] = page
            # Beim Start liegen alle Seiten übereinander und werden verdeckt fertig angeordnet.
            page.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            if self.current in self.pages:
                tk.Misc.lower(page, self.pages[self.current])
        return self.pages[key]

    def park_hidden_pages(self) -> None:
        """Nicht sichtbare Seiten fertig angeordnet außerhalb des Sichtbereichs ablegen.

        Sie bleiben abgebildet (ein Wechsel muss nichts neu aufbauen), haben aber
        eine feste Größe: Beim Ändern der Fenstergröße arbeitet nur die sichtbare Seite.
        """
        width, height = self.host.winfo_width(), self.host.winfo_height()
        for key, page in self.pages.items():
            if key != self.current:
                self._park(page, width, height)

    def _park(self, page: Page, width: int, height: int) -> None:
        page.place(x=PARK_X, y=0, width=max(1, width), height=max(1, height), relwidth=0, relheight=0)
        ctx().block_focus(page, True)

    def item_for_page(self, page: str) -> str | None:
        """Navigationseintrag, zu dem eine Seite gehört."""
        return next((item.key for item in self.items if not item.header and item.owns(page)), None)

    def page_for_item(self, key: str) -> str | None:
        """Seite, die ein Navigationseintrag öffnet: die zuletzt gezeigte bzw. die erste."""
        item = next((item for item in self.items if item.key == key and not item.header), None)
        if item is None:
            return key if key in self.factories else None
        if key in self._last_page:
            return self._last_page[key]
        if item.pages:
            return item.pages[0]
        return key if key in self.factories else None

    def _select_item(self, key: str) -> None:
        page = self.page_for_item(key)
        if page is not None:
            self.navigate(page)

    def navigate(self, key: str, animate: bool = True) -> None:
        if key not in self.factories:
            resolved = self.page_for_item(key)
            if resolved is None or resolved not in self.factories:
                return
            key = resolved
        if key == self.current:
            return
        if self._navigating:
            self._pending = (key, animate)
            return
        self._navigating = True
        try:
            c = ctx()
            old = self.pages.get(self.current) if self.current else None
            page = self.page(key)
            width, height = self.host.winfo_width(), self.host.winfo_height()
            if old is not None:
                if (page.winfo_width(), page.winfo_height()) != (width, height):
                    # Fenstergröße hat sich geändert: Seite außerhalb des Sichtbereichs neu anordnen.
                    page.place(x=PARK_X, y=0, width=max(1, width), height=max(1, height), relwidth=0, relheight=0)
                    self._settle()
                self._release_focus(old)
                old.leave()
            # Die fertige Seite wird nur noch hereingeholt …
            c.block_focus(page, False)
            page.place(x=0, y=0, width=0, height=0, relwidth=1.0, relheight=1.0)
            tk.Misc.lift(page)
            # … und die bisherige Seite abgelegt.
            if old is not None:
                self._park(old, width, height)
            self.current = key
            allowed = animate and c.anim.allowed()
            item = self.item_for_page(key) or key
            self._last_page[item] = key
            self.pane.select(item, animate=allowed and self.pane.selected != item)
            page.enter(allowed)
            if self.on_change:
                self.on_change(key)
        finally:
            self._navigating = False
        if self._pending is not None:
            pending, self._pending = self._pending, None
            self.after_idle(lambda: self.navigate(*pending))

    def _settle(self) -> None:
        settle(self)

    def _release_focus(self, page: Page) -> None:
        """Tastaturfokus nicht auf einer abgelegten Seite zurücklassen."""
        try:
            focus = self.focus_get()
        except (tk.TclError, KeyError):
            return
        if focus is not None and str(focus).startswith(str(page) + "."):
            self.pane.focus_set()

    # Responsives Layout ------------------------------------------------------------
    def _window_resized(self, event) -> None:
        if event.width == self._width:
            return
        self.apply_layout(event.width)

    def apply_layout(self, width: int) -> None:
        """Layoutzustand für eine Fensterbreite bestimmen; umgestellt wird nur an Breakpoints."""
        self._width = width
        mode = self._mode_for(width)
        if mode != self.mode:
            if mode == MODE_WIDE or self.mode == MODE_WIDE:
                self.user_expanded = False
            self.mode = mode
            self._apply_pane(animate=False)  # sofort, ohne Animation
        else:
            self._update_columns()

    def _mode_for(self, width: int) -> str:
        hysteresis = px(BREAKPOINT_HYSTERESIS)
        wide_from = px(WIDE_FROM) - (hysteresis if self.mode == MODE_WIDE else 0)
        medium_from = px(MEDIUM_FROM) - (hysteresis if self.mode in (MODE_WIDE, MODE_MEDIUM) else 0)
        if width >= wide_from:
            return MODE_WIDE
        if width >= medium_from:
            return MODE_MEDIUM
        return MODE_COMPACT

    def _update_columns(self) -> None:
        c = ctx()
        if self._width <= 1 or self._layer_x is None:
            return
        content = min(self._width - self._layer_x - 1, px(Page.MAX_WIDTH)) - px(PAGE_PADDING[0] + PAGE_PADDING[1])
        need = px(TWO_COLUMNS_FROM) - (px(COLUMNS_HYSTERESIS) if c.layout.columns >= 2 else 0)
        columns = 2 if (self.mode != MODE_COMPACT and content >= need) else 1
        c.layout.set(self.mode, columns)

    # Navigationsbereich ------------------------------------------------------------
    def pane_expanded(self) -> bool:
        if self.user_compact:
            return False
        if self.mode == MODE_WIDE:
            return True
        return self.user_expanded

    def is_compact(self) -> bool:
        return not self.pane_expanded()

    @property
    def auto_compact(self) -> bool:
        return self.mode != MODE_WIDE

    def toggle_pane(self) -> None:
        if self.pane_expanded():
            self.user_compact = True
            self.user_expanded = False
        else:
            self.user_compact = False
            # Auch bei schmalem Fenster klappt die Menüschaltfläche die Navigation aus.
            self.user_expanded = self.mode != MODE_WIDE
        self._apply_pane(animate=True)
        if self.on_change and self.current:
            self.on_change(self.current)

    def _apply_pane(self, animate: bool) -> None:
        c = ctx()
        target = 1.0 if self.pane_expanded() else 0.0
        compact_w, expanded_w = px(PANE_COMPACT), px(PANE_EXPANDED)
        layer_x = int(round(compact_w + (expanded_w - compact_w) * target))
        # Der Inhalt springt einmal auf seine Endposition; animiert wird nur die Navigation.
        if layer_x != self._layer_x:
            self._layer_x = layer_x
            self.layer.place(x=layer_x, y=0, relheight=1.0, relwidth=1.0, width=-layer_x)
        self._update_columns()
        start = self.pane.expanded_amount

        def step(t: float) -> None:
            self._set_amount(start + (target - start) * t)

        if start == target:
            self._set_amount(target)
        else:
            c.anim.run(f"pane:{self}", self.PANE_MS if animate else 0, step, easing=motion.DECELERATE, widget=self)
        tk.Misc.lift(self.pane)
        if self.on_layout:
            self.on_layout()

    def _set_amount(self, amount: float) -> None:
        self.pane.expanded_amount = amount
        self.pane.place(x=0, y=0, relheight=1.0, width=self.pane.visual_width())
        self.pane.redraw()

    # Hintergrund (Mica) ------------------------------------------------------------
    def set_backdrop(self, image: Image.Image | None) -> None:
        if image is None:
            self._backdrop_photo = None
            self.backdrop.itemconfigure(self._backdrop_item, state="hidden")
            self.pane.set_backdrop(None)
            return
        self._backdrop_photo = to_photo(self, image)
        self.backdrop.itemconfigure(self._backdrop_item, image=self._backdrop_photo, state="normal")
        self.pane.set_backdrop(self._backdrop_photo)
