"""NavigationView nach Windows 11: Navigationsbereich links (Mica), Inhaltsebene rechts.

* Auswahlindikator in Akzentfarbe, der beim Seitenwechsel zur neuen Seite gleitet
* Kompaktmodus (nur Symbole) bei schmalen Fenstern oder per Menüschaltfläche
* Seitenübergang: neue Seite gleitet 16 px von rechts ein, Abschnitte erscheinen gestaffelt
"""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass
from typing import Callable

from PIL import Image

from . import animations as motion
from . import icons
from .context import ctx
from .render import rounded_box, to_photo
from .scroll import ScrollArea
from .theme import px
from .widgets import CONTROL_RADIUS, OVERLAY_RADIUS, ProgressRing, Surface, Text, Tooltip, frame

PANE_EXPANDED = 240
PANE_COMPACT = 48
ITEM_HEIGHT = 36
ITEM_GAP = 4
COMPACT_BELOW = 900  # Fensterbreite (effektive Pixel), unter der die Navigation kompakt wird


@dataclass
class NavItem:
    key: str
    label: str
    glyph: str
    footer: bool = False


class NavigationPane(tk.Canvas):
    def __init__(self, master, items: list[NavItem], on_select: Callable[[str], None], on_toggle: Callable[[], None]) -> None:
        self.c = ctx()
        super().__init__(master, width=px(PANE_EXPANDED), highlightthickness=0, bd=0, takefocus=1)
        self.surface_role = "mica"
        self.items = items
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
        self._images: dict = {}
        self._backdrop = self.create_image(0, 0, anchor="nw")
        self._tooltip = Tooltip(self, "")
        self._tooltip_key: str | None = None
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", lambda _e: self.redraw())
        for key, delta in (("Up", -1), ("Down", 1)):
            self.bind(f"<KeyPress-{key}>", lambda _e, d=delta: self._move_focus(d))
        for key in ("Return", "space", "KP_Enter"):
            self.bind(f"<KeyPress-{key}>", lambda _e: self._activate_focus())
        self.c.theme.subscribe(self.redraw, owner=self)
        self.c.on_focus_mode(self, self.redraw)

    # Geometrie ----------------------------------------------------------------
    def _toggle_rect(self) -> tuple[int, int, int, int]:
        x0 = px(4)
        y0 = px(4)
        return x0, y0, x0 + px(40), y0 + px(ITEM_HEIGHT)

    def _item_rects(self) -> dict[str, tuple[int, int, int, int]]:
        width = max(px(PANE_COMPACT), self.winfo_width())
        height = self.winfo_height()
        rects = {}
        y = px(4) + px(ITEM_HEIGHT) + px(8)
        top_items = [item for item in self.items if not item.footer]
        foot_items = [item for item in self.items if item.footer]
        for item in top_items:
            rects[item.key] = (px(4), y, width - px(4), y + px(ITEM_HEIGHT))
            y += px(ITEM_HEIGHT) + px(ITEM_GAP)
        y = height - px(4) - px(ITEM_HEIGHT)
        for item in reversed(foot_items):
            rects[item.key] = (px(4), y, width - px(4), y + px(ITEM_HEIGHT))
            y -= px(ITEM_HEIGHT) + px(ITEM_GAP)
        return rects

    def _hit(self, x: int, y: int) -> str | None:
        tx0, ty0, tx1, ty1 = self._toggle_rect()
        if tx0 <= x < tx1 and ty0 <= y < ty1:
            return "__toggle__"
        for key, (x0, y0, x1, y1) in self._item_rects().items():
            if x0 <= x < x1 and y0 <= y < y1:
                return key
        return None

    # Hintergrund -------------------------------------------------------------------
    def set_backdrop(self, image: Image.Image | None) -> None:
        if image is None:
            self._backdrop_img = None
            self.itemconfigure(self._backdrop, state="hidden")
        else:
            self._backdrop_img = to_photo(self, image)
            self.itemconfigure(self._backdrop, image=self._backdrop_img, state="normal")
        self.redraw()

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
            self.focus_key = self.selected or (self.items[0].key if self.items else None)
        self.redraw()

    def _order(self) -> list[str]:
        return ["__toggle__"] + [item.key for item in self.items if not item.footer] + [item.key for item in self.items if item.footer]

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

        self.c.anim.run(f"navind:{self}", 300, step, easing=motion.POINT_TO_POINT, widget=self)

    # Zeichnen ----------------------------------------------------------------------
    def redraw(self) -> None:
        c = self.c
        pal = c.pal
        self.delete("fg")
        self.configure(bg=pal.mica)
        width = max(1, self.winfo_width())
        radius = px(CONTROL_RADIUS)
        keyboard = c.keyboard_mode and self.focus_get() is self

        def overlay(x0, y0, x1, y1, pressed: bool) -> None:
            alpha = pal.subtle_pressed_alpha if pressed else pal.subtle_hover_alpha
            img = c.images.box(x1 - x0, y1 - y0, radius, pal.subtle_color, alpha=alpha)
            self._images[f"ov{x0}{y0}"] = img
            self.create_image(x0, y0, anchor="nw", image=img, tags="fg")

        def focus_rect(x0, y0, x1, y1) -> None:
            ring = c.images.ring(x1 - x0 + px(6), y1 - y0 + px(6), radius + px(3), pal.focus_outer, pal.focus_inner)
            self._images[f"fr{x0}{y0}"] = ring
            self.create_image(x0 - px(3), y0 - px(3), anchor="nw", image=ring, tags="fg")

        self._images = {}
        # Menüschaltfläche
        tx0, ty0, tx1, ty1 = self._toggle_rect()
        if self.hover == "__toggle__" or self.pressed == "__toggle__":
            overlay(tx0, ty0, tx1, ty1, self.pressed == "__toggle__")
        if c.icons_available:
            self.create_text((tx0 + tx1) / 2, (ty0 + ty1) / 2, text=icons.GLOBAL_NAV, font=c.fonts.icon, fill=pal.text, tags="fg")
        else:
            self.create_text((tx0 + tx1) / 2, (ty0 + ty1) / 2, text="≡", font=c.fonts.body_large, fill=pal.text, tags="fg")
        if keyboard and self.focus_key == "__toggle__":
            focus_rect(tx0, ty0, tx1, ty1)
        rects = self._item_rects()
        show_labels = self.expanded_amount > 0.55
        for item in self.items:
            x0, y0, x1, y1 = rects[item.key]
            is_sel = item.key == self.selected
            if is_sel or item.key == self.hover or item.key == self.pressed:
                overlay(x0, y0, x1, y1, item.key == self.pressed or (is_sel and item.key == self.hover))
            cy = (y0 + y1) / 2
            if c.icons_available:
                self.create_text(x0 + px(20), cy, text=item.glyph, font=c.fonts.icon, fill=pal.text, tags="fg", anchor="center")
            elif not show_labels:
                self.create_text(x0 + px(20), cy, text=item.label[:1], font=c.fonts.body_strong, fill=pal.text, tags="fg")
            if show_labels:
                label_x = x0 + (px(44) if c.icons_available else px(12))
                self.create_text(label_x, cy, text=item.label, font=c.fonts.body, fill=pal.text, anchor="w", tags="fg")
            if keyboard and self.focus_key == item.key:
                focus_rect(x0, y0, x1, y1)
        if self.selected in rects and not c.anim.running(f"navind:{self}"):
            sel = rects[self.selected]
            self._indicator_y = (sel[1] + sel[3]) / 2
            self._indicator_h = float(px(16))
        if self.selected in rects and self._indicator_y is not None:
            x0 = rects[self.selected][0]
            h = max(px(8), int(self._indicator_h))
            pill = c.images.box(px(3), h, px(1.5), pal.accent)
            self._images["pill"] = pill
            self.create_image(x0, self._indicator_y, anchor="w", image=pill, tags="fg")


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
        self._corner_img = to_photo(self, base.convert("RGB"))
        self._corner.itemconfigure(self._corner_item, image=self._corner_img)
        tk.Misc.lift(self._corner)
        self._top.lift()
        self._left.lift()


class Page(tk.Frame):
    """Seite mit Titel, Untertitel und gestaffelt erscheinenden Abschnitten."""

    MAX_WIDTH = 1180

    def __init__(self, master, title: str, subtitle: str | None = None) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = "layer"
        ctx().theme.style(self, bg="layer")
        self.scroll = ScrollArea(self)
        self.scroll.pack(fill="both", expand=True)
        self.scroll.canvas.bind("<Configure>", self._limit_width, add="+")
        self.content = frame(self.scroll.body)
        self.content.pack(fill="both", expand=True, padx=(px(36), px(28)), pady=(px(28), px(28)))
        self._sections: list[tuple[tk.Widget, dict]] = []
        header = frame(self.content)
        Text(header, title, style="title").pack(anchor="w")
        if subtitle:
            Text(header, subtitle, style="body", color="text2").pack(anchor="w", pady=(px(2), 0))
        self.add_section(header, pady=(0, px(20)))

    def _limit_width(self, event) -> None:
        limit = px(self.MAX_WIDTH)
        self.scroll.canvas.itemconfigure(self.scroll._window, width=min(event.width, limit))

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
        """Eintrittsanimation: Seite gleitet ein, Abschnitte erscheinen nacheinander."""
        c = ctx()
        key = f"page:{self}"
        c.anim.cancel_prefix(key)
        self.scroll.to_top()
        if not animate or not c.anim.enabled:
            self._show_all()
            self.scroll.set_offset(0)
            return
        for widget, _options in self._sections:
            widget.pack_forget()
        shift = px(16)

        def slide(t: float) -> None:
            self.scroll.set_offset(int(round(shift * (1 - t))))

        c.anim.run(f"{key}:slide", motion.PAGE, slide, easing=motion.DECELERATE, widget=self)
        visible = self._sections[:6]
        rest = self._sections[6:]
        for index, (widget, options) in enumerate(visible):
            c.anim.later(f"{key}:sec{index}", index * 45, lambda w=widget, o=options: w.pack(**o))
        if rest:
            c.anim.later(f"{key}:rest", len(visible) * 45, lambda: [w.pack(**o) for w, o in rest])

    def _show_all(self) -> None:
        for widget, options in self._sections:
            if not widget.winfo_manager():
                widget.pack(**options)

    def leave(self) -> None:
        c = ctx()
        c.anim.cancel_prefix(f"page:{self}")
        # Abgebrochene Staffelung vervollständigen, damit die Seite beim nächsten Besuch vollständig ist.
        for widget, _options in self._sections:
            widget.pack_forget()
        self._show_all()
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
        self.label.pack(side="left", fill="x", expand=True)
        self.text = "Bereit"
        self._tooltip = Tooltip(self.label, "")
        self.label.bind("<Configure>", lambda _e: self._fit(), add="+")
        self._kind = "neutral"
        c.theme.subscribe(self._recolor, owner=self)

    def _fit(self) -> None:
        font = ctx().fonts.caption
        width = self.label.winfo_width()
        text = self.text
        if width > 1 and font.measure(text) > width:
            while text and font.measure(text + "…") > width:
                text = text[:-1]
            text = text.rstrip() + "…"
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
    def __init__(self, master, items: list[NavItem], factories: dict[str, Callable[[tk.Misc], Page]], on_change: Callable[[str], None] | None = None, compact: bool = False, status_hint: str = "") -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.surface_role = "mica"
        c = ctx()
        c.theme.style(self, bg="mica")
        self.factories = factories
        self.pages: dict[str, Page] = {}
        self.current: str | None = None
        self.on_change = on_change
        self.user_compact = compact
        self.auto_compact = False
        self.pane = NavigationPane(self, items, self.navigate, self.toggle_pane)
        self.layer = ContentLayer(self)
        self.pane.grid(row=0, column=0, sticky="ns")
        self.layer.grid(row=0, column=1, sticky="nsew")
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.host = Surface(self.layer, role="layer")
        self.host.pack(fill="both", expand=True, padx=(1, 0), pady=(1, 0))
        self.status = StatusBar(self.layer, status_hint)
        self.status.pack(fill="x", side="bottom", before=self.host, padx=(1, 0))
        self._apply_width(animate=False)
        c.window_hooks.append(self._window_resized)

    # Seiten -----------------------------------------------------------------
    def page(self, key: str) -> Page:
        if key not in self.pages:
            page = self.factories[key](self.host)
            self.pages[key] = page
        return self.pages[key]

    def navigate(self, key: str, animate: bool = True) -> None:
        if key == self.current:
            return
        c = ctx()
        old = self.pages.get(self.current) if self.current else None
        page = self.page(key)
        if old is not None:
            old.leave()
            old.place_forget()
        page.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        page.lift()
        self.current = key
        self.pane.select(key, animate=animate and c.anim.enabled)
        page.enter(animate and c.anim.enabled)
        if self.on_change:
            self.on_change(key)

    # Kompaktmodus -----------------------------------------------------------
    def _window_resized(self, event) -> None:
        compact = event.width < px(COMPACT_BELOW)
        if compact != self.auto_compact:
            self.auto_compact = compact
            self._apply_width(animate=True)

    def is_compact(self) -> bool:
        return self.user_compact or self.auto_compact

    def toggle_pane(self) -> None:
        if self.is_compact():
            # Auch bei schmalem Fenster klappt die Menüschaltfläche die Navigation aus.
            self.user_compact = False
            self.auto_compact = False
        else:
            self.user_compact = True
        self._apply_width(animate=True)
        if self.on_change and self.current:
            self.on_change(self.current)

    def _apply_width(self, animate: bool) -> None:
        c = ctx()
        target = 0.0 if self.is_compact() else 1.0
        start = self.pane.expanded_amount
        if start == target:
            self._set_amount(target)
            return

        def step(t: float) -> None:
            self._set_amount(start + (target - start) * t)

        c.anim.run(f"pane:{self}", 180 if animate else 0, step, easing=motion.DECELERATE, widget=self)

    def _set_amount(self, amount: float) -> None:
        self.pane.expanded_amount = amount
        width = px(PANE_COMPACT) + (px(PANE_EXPANDED) - px(PANE_COMPACT)) * amount
        self.pane.configure(width=int(width))
        self.pane.redraw()
