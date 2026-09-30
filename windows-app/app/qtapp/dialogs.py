"""Dialoge in QML, aus Python modal aufgerufen.

``ask()`` legt eine Anfrage an (Art, Titel, Text, Schaltflächen, Daten), die der einzige
``DialogHost`` in QML anzeigt, und wartet in einer eigenen Ereignisschleife auf die Antwort –
wie ``QDialog.exec()``. So bleibt die Ablauflogik linear (»Wirklich löschen? – dann …«).
Reine Informationsdialoge (Kurzanleitung, Über, Neuerungen) blockieren nicht.

``AUTO_ANSWER`` beantwortet Rückfragen in Tests ohne Oberfläche.
"""

from __future__ import annotations

from itertools import count
from typing import Any

from PySide6.QtCore import QEventLoop, QObject, Slot

from .base import Observable, prop

PRIMARY = "primary"
SECONDARY = "secondary"
CLOSE = "close"
AUTO_ANSWER: str | None = None  # Tests: »primary«, »secondary« oder »close«

_IDS = count(1)


class DialogService(Observable):
    """Eine Anfrage nach der anderen (gestapelt, falls ein Dialog einen weiteren öffnet)."""

    requestChanged, request = prop(dict, "request", {})
    openChanged, open = prop(bool, "open", False)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stack: list[dict[str, Any]] = []
        self.history: list[dict] = []  # zuletzt gestellte Anfragen (Tests, Diagnose)

    # Modal ----------------------------------------------------------------------
    def ask(
        self,
        kind: str,
        title: str,
        message: str = "",
        primary: str = "OK",
        secondary: str = "",
        close: str = "Abbrechen",
        danger: bool = False,
        default: str = PRIMARY,
        data: dict | None = None,
        width: int = 460,
    ) -> tuple[str, dict]:
        request = {
            "id": next(_IDS),
            "kind": kind,
            "title": title,
            "message": message,
            "primary": primary,
            "secondary": secondary,
            "close": close,
            "danger": danger,
            "default": default,
            "data": dict(data or {}),
            "width": width,
            "modal": True,
        }
        self.history.append(request)
        del self.history[:-20]
        if AUTO_ANSWER is not None:
            return AUTO_ANSWER, dict(data or {})
        entry: dict[str, Any] = {"request": request, "answer": CLOSE, "result": {}, "loop": QEventLoop()}
        self._stack.append(entry)
        self._publish()
        entry["loop"].exec()
        return entry["answer"], entry["result"]

    def confirm(self, title: str, message: str, confirm: str, danger: bool = True) -> bool:
        answer, _data = self.ask("confirm", title, message, primary=confirm, danger=danger)
        return answer == PRIMARY

    # Nicht blockierend -----------------------------------------------------------------
    def show(self, kind: str, title: str, data: dict | None = None, width: int = 520) -> None:
        """Informationsdialog (nur »Schließen«) – die Oberfläche bleibt bedienbar, der Aufruf kehrt sofort zurück."""
        request = {
            "id": next(_IDS),
            "kind": kind,
            "title": title,
            "message": "",
            "primary": "",
            "secondary": "",
            "close": "Schließen",
            "danger": False,
            "default": CLOSE,
            "data": dict(data or {}),
            "width": width,
            "modal": False,
        }
        self.history.append(request)
        del self.history[:-20]
        if AUTO_ANSWER is not None:
            return
        self._stack.append({"request": request, "answer": CLOSE, "result": {}, "loop": None})
        self._publish()

    # Aus QML -----------------------------------------------------------------------------
    @Slot(int, str, "QVariantMap")
    def answer(self, request_id: int, button: str, data: dict) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            entry = self._stack[index]
            if entry["request"]["id"] == request_id:
                del self._stack[index]
                entry["answer"] = button if button in (PRIMARY, SECONDARY, CLOSE) else CLOSE
                entry["result"] = dict(data or {})
                self._publish()
                if entry["loop"] is not None:
                    entry["loop"].quit()
                return

    def _publish(self) -> None:
        if self._stack:
            self.request = dict(self._stack[-1]["request"])
            self.open = True
        else:
            self.open = False

    def pending(self) -> int:
        return len(self._stack)

    def shutdown(self) -> None:
        """Beim Beenden offene Rückfragen mit »Abbrechen« beantworten."""
        for entry in list(self._stack):
            self.answer(entry["request"]["id"], CLOSE, {})
