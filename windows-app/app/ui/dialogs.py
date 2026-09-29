"""Dialoge im Stil des WinUI-ContentDialog.

Aufbau: Inhaltsbereich (Titel 20 px, Text) und darunter eine Schaltflächenleiste
mit gleich breiten Schaltflächen. Enter löst die Standardschaltfläche aus,
Escape schließt den Dialog. Der Dialog blendet sich weich ein.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

from . import animations as motion
from . import windows
from .context import ctx, reveal, settle
from .theme import px
from .widgets import Button, Surface, Text, frame

PRIMARY = "primary"
SECONDARY = "secondary"
CLOSE = "close"

# Für automatisierte Tests: Rückgabewert statt Anzeige (None = normal anzeigen)
AUTO_ANSWER: str | None = None


class ContentDialog:
    WIDTH = 460

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        message: str | None = None,
        primary: str | None = "OK",
        secondary: str | None = None,
        close: str | None = "Abbrechen",
        default: str = PRIMARY,
        danger: bool = False,
        build: Callable[[tk.Frame], None] | None = None,
        window_title: str = "PDF Tool",
        icon: Path | None = None,
        width: int | None = None,
    ) -> None:
        self.parent = parent
        self.result = CLOSE
        self.focus_widget: tk.Misc | None = None  # Fokus beim Öffnen (sonst die Standardschaltfläche)
        self.c = ctx()
        c = self.c
        root = parent.winfo_toplevel()
        self.win = tk.Toplevel(root)
        win = self.win
        win.withdraw()
        win.title(window_title)
        win.transient(root)
        win.resizable(False, False)
        if icon and icon.is_file():
            try:
                win.iconbitmap(str(icon))
            except tk.TclError:
                pass
        win.protocol("WM_DELETE_WINDOW", lambda: self._finish(CLOSE))
        body = Surface(win, role="dialog")
        body.pack(fill="both", expand=True)
        dialog_w = px(width or self.WIDTH)
        spacer = frame(body, width=dialog_w, height=1)
        spacer.pack(side="top")
        inner = frame(body)
        inner.pack(fill="both", expand=True, padx=px(24), pady=(px(22), px(24)))
        # Umbruchbreite gleich der Inhaltsbreite: Die Höhe steht schon vor dem Anzeigen fest.
        text_w = (width or self.WIDTH) - 48
        Text(inner, title, style="subtitle", wrap=True, wrap_width=text_w).pack(anchor="w", fill="x")
        if message:
            Text(inner, message, style="body", wrap=True, wrap_width=text_w).pack(anchor="w", fill="x", pady=(px(12), 0))
        if build:
            holder = frame(inner)
            holder.pack(fill="both", expand=True, pady=(px(12), 0))
            build(holder)
        line = tk.Frame(win, height=1, bd=0)
        c.theme.style(line, bg="card_stroke")
        line.pack(fill="x")
        footer = Surface(win, role="dialog_footer")
        footer.pack(fill="x")
        buttons = frame(footer)
        buttons.pack(fill="x", padx=px(21), pady=px(21))
        specs = []
        if primary:
            specs.append((PRIMARY, primary, "danger" if danger else "accent" if default == PRIMARY else "standard"))
        if secondary:
            specs.append((SECONDARY, secondary, "accent" if default == SECONDARY else "standard"))
        if close:
            specs.append((CLOSE, close, "accent" if default == CLOSE and not primary else "standard"))
        self.buttons: dict[str, Button] = {}
        for column, (result, text, kind) in enumerate(specs):
            button = Button(buttons, text, lambda r=result: self._finish(r), kind=kind, min_width=96)
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else px(2), 0))
            buttons.columnconfigure(column, weight=1, uniform="buttons")
            self.buttons[result] = button
        self.default = default if default in self.buttons else (specs[0][0] if specs else CLOSE)
        win.bind("<Escape>", lambda _e: self._finish(CLOSE if close or not primary else PRIMARY))
        win.bind("<Return>", self._return_key)
        win.bind("<KP_Enter>", self._return_key)
        # Verborgen fertig anordnen (auch Textumbrüche), dann Position aus der endgültigen Höhe.
        settle(win)
        height = win.winfo_reqheight()
        rx, ry = root.winfo_rootx(), root.winfo_rooty()
        rw, rh = root.winfo_width(), root.winfo_height()
        x = rx + max(0, (rw - dialog_w) // 2)
        y = ry + max(0, (rh - height) // 3)
        win.geometry(f"+{x}+{y}")
        self._position = (x, y)

    def _return_key(self, event):
        focused = self.win.focus_get()
        if isinstance(focused, Button):
            return None  # die fokussierte Schaltfläche verarbeitet Enter selbst
        self._finish(self.default)
        return "break"

    def _finish(self, result: str) -> None:
        self.result = result
        win = self.win
        c = self.c

        def close() -> None:
            try:
                win.grab_release()
            except tk.TclError:
                pass
            try:
                win.destroy()
            except tk.TclError:
                pass

        if c.anim.allowed():
            try:
                win.attributes("-alpha", 1.0)
                c.anim.run(f"dlgout:{win}", 90, lambda t: win.attributes("-alpha", 1.0 - t), close, easing=motion.ACCELERATE, widget=win)
                return
            except tk.TclError:
                pass
        close()

    def show(self) -> str:
        if AUTO_ANSWER is not None:
            answer = AUTO_ANSWER
            self.win.destroy()
            return answer
        c = self.c
        win = self.win
        pal = c.pal
        # Titelleiste vor dem Anzeigen einfärben: kein kurz heller Rahmen im dunklen Design.
        windows.apply_window_chrome(windows.frame_hwnd(win), pal.dark, caption=pal.dialog, text=pal.text, mica=False)
        fade = c.anim.allowed()
        if fade:
            try:
                win.attributes("-alpha", 0.0)
            except tk.TclError:
                fade = False
        # Erst vollständig gezeichnet sichtbar machen, danach (optional) einblenden.
        reveal(win, position=self._position, prepare=False)
        win.lift()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        target = self.focus_widget or self.buttons.get(self.default)
        if target is not None:
            target.focus_set()
        else:
            win.focus_set()
        if fade:
            c.anim.run(f"dlgin:{win}", motion.SLOW, lambda t: win.attributes("-alpha", t), easing=motion.DECELERATE, widget=win)
        win.wait_window()
        return self.result


def confirm(parent, title: str, message: str, primary: str, danger: bool = True, close: str = "Abbrechen", icon: Path | None = None) -> bool:
    dialog = ContentDialog(parent, title, message, primary=primary, close=close, default=CLOSE if danger else PRIMARY, danger=danger, icon=icon)
    return dialog.show() == PRIMARY


def info(parent, title: str, message: str | None = None, build=None, close: str = "Schließen", icon: Path | None = None, width: int | None = None) -> None:
    ContentDialog(parent, title, message, primary=None, close=close, default=CLOSE, build=build, icon=icon, width=width).show()
