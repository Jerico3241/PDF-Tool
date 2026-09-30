"""Grundbausteine der Qt-Anwendungsschicht: Properties für QML und beobachtbare Werte."""

from __future__ import annotations

import copy
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, Signal


def prop(type_, name: str, default: Any = None):
    """Qt-Property samt Änderungssignal in einem Schritt – für QML lesbar und schreibbar.

    ::

        class Form(Observable):
            firmaChanged, firma = prop(str, "firma", "")

    Das Signal meldet QML jede echte Änderung (gleiche Werte lösen nichts aus). Python-Code
    kann zusätzlich mit ``observe()`` auf Änderungen hören – auch auf solche aus QML.
    """
    signal = Signal()
    attr = "_prop_" + name

    def getter(self):
        value = self.__dict__.get(attr, _MISSING)
        if value is _MISSING:
            value = copy.copy(default)
            self.__dict__[attr] = value
        return value

    def setter(self, value):
        if value is None and type_ is str:
            value = ""
        old = self.__dict__.get(attr, _MISSING)
        if old is not _MISSING and old == value and type(old) is type(value):
            return
        self.__dict__[attr] = value
        getattr(self, name + "Changed").emit()
        observers = self.__dict__.get("_observers")
        if observers:
            for callback in list(observers.get(name, ())):
                callback(value)

    return signal, Property(type_, getter, setter, notify=signal)


_MISSING = object()


class Observable(QObject):
    """QObject mit ``observe(name, callback)`` für Properties aus ``prop()`` (Beobachter je Property)."""

    def observe(self, name: str, callback: Callable[[Any], None]) -> None:
        observers = self.__dict__.setdefault("_observers", {})
        observers.setdefault(name, []).append(callback)

    def set_quietly(self, name: str, value: Any) -> None:
        """Wert setzen und QML benachrichtigen, aber keine Python-Beobachter auslösen."""
        observers = self.__dict__.get("_observers")
        saved = observers.pop(name, None) if observers else None
        try:
            setattr(self, name, value)
        finally:
            if saved is not None:
                observers[name] = saved


class Var:
    """Formularwert mit ``get``/``set``/``trace_add`` – dieselbe Schnittstelle wie ``tk.StringVar``.

    So bleibt die bewährte Ablauflogik der Werkzeuge unverändert lesbar, während der Wert
    als Property eines ``Observable`` in QML erscheint.
    """

    __slots__ = ("owner", "name")

    def __init__(self, owner: Observable, name: str) -> None:
        self.owner = owner
        self.name = name

    def get(self):
        return getattr(self.owner, self.name)

    def set(self, value) -> None:
        setattr(self.owner, self.name, value)

    def trace_add(self, _mode: str, callback: Callable[..., None]) -> None:
        self.owner.observe(self.name, lambda _value: callback())
