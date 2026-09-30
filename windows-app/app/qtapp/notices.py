"""Hinweise (InfoBars) je Bereich – z. B. »pdf_info«, »kunde_match«, »repair_info«.

Jeder Bereich ist ein eigenes, dauerhaftes ``Notice``-Objekt. QML holt es einmal
(``Notices.area("pdf_info")``) und bindet an seine Properties; Aktionen laufen über
``trigger(index)``. Die Ablauflogik ruft wie bisher ``notify(area, …)`` bzw. ``hide(area)``.
"""

from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import QObject, Slot

from .base import Observable, prop
from .timers import Timers

Action = tuple[str, Callable[[], None]]


class Notice(Observable):
    """Eine InfoBar: Stufe, Titel, Text und Aktionen."""

    shownChanged, shown = prop(bool, "shown", False)
    severityChanged, severity = prop(str, "severity", "info")
    titleChanged, title = prop(str, "title", "")
    messageChanged, message = prop(str, "message", "")
    actionsChanged, actions = prop(list, "actions", [])
    animateChanged, animate = prop(bool, "animate", True)
    serialChanged, serial = prop(int, "serial", 0)

    def __init__(self, name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self._callbacks: list[Callable[[], None]] = []
        self.on_close: Callable[[], None] | None = None

    def show(self, severity: str, message: str, title: str = "", actions: Sequence[Action] = (), animate: bool = True) -> None:
        self.animate = animate
        self._callbacks = [callback for _label, callback in actions]
        self.severity = severity if severity in ("info", "success", "warning", "error", "neutral") else "info"
        self.title = title
        self.message = message
        self.actions = [label for label, _callback in actions]
        self.serial = self.serial + 1
        self.shown = True

    def hide(self, animate: bool = True) -> None:
        if self.shown:
            self.animate = animate
            self.shown = False
        self._callbacks = []

    @Slot(int)
    def trigger(self, index: int) -> None:
        if 0 <= index < len(self._callbacks):
            self._callbacks[index]()

    @Slot()
    def close(self) -> None:
        """Vom Benutzer geschlossen (×)."""
        self.hide()
        if self.on_close is not None:
            self.on_close()


class NoticeCenter(QObject):
    """Alle Hinweisbereiche der App."""

    def __init__(self, timers: Timers, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timers = timers
        self._areas: dict[str, Notice] = {}

    @Slot(str, result=QObject)
    def area(self, name: str) -> Notice:
        notice = self._areas.get(name)
        if notice is None:
            notice = self._areas[name] = Notice(name, self)
        return notice

    def get(self, name: str) -> Notice:
        return self.area(name)

    def notify(self, name: str, severity: str, message: str, title: str = "", actions: Sequence[Action] = (), auto_hide: int | None = None, animate: bool = True) -> None:
        self._timers.cancel(f"hide:{name}")
        self.area(name).show(severity, message, title, actions, animate=animate)
        if auto_hide:
            self._timers.later(f"hide:{name}", auto_hide, lambda: self.hide(name))

    def hide(self, name: str, animate: bool = True) -> None:
        self._timers.cancel(f"hide:{name}")
        notice = self._areas.get(name)
        if notice is not None:
            notice.hide(animate=animate)

    def on_close(self, name: str, callback: Callable[[], None]) -> None:
        self.area(name).on_close = callback
