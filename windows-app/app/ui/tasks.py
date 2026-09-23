"""Hintergrundarbeit ohne eingefrorene Oberfläche.

Threads rufen nie Tk direkt auf. Ergebnisse landen in einer Warteschlange,
die der Tk-Hauptthread abfragt – nur solange Aufgaben laufen.
"""

from __future__ import annotations

import queue
import threading
import traceback
from typing import Any, Callable

import tkinter as tk


class Worker:
    POLL_MS = 40

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self._queue: queue.Queue = queue.Queue()
        self._active = 0
        self._job = None

    def run(self, func: Callable[[], Any], on_done: Callable[[Any], None] | None = None, on_error: Callable[[BaseException, str], None] | None = None) -> None:
        self._active += 1

        def target() -> None:
            try:
                result = func()
            except BaseException as exc:  # noqa: BLE001 - Fehler gehen an die Oberfläche
                self._queue.put((on_error, (exc, traceback.format_exc()), True))
            else:
                self._queue.put((on_done, (result,), True))

        threading.Thread(target=target, daemon=True).start()
        self._ensure_poll()

    def post(self, callback: Callable[..., None], *args: Any) -> None:
        """Aus einem Hintergrund-Thread: ``callback(*args)`` im Tk-Thread ausführen."""
        self._queue.put((callback, args, False))

    def _ensure_poll(self) -> None:
        if self._job is None:
            try:
                self._job = self.root.after(self.POLL_MS, self._poll)
            except tk.TclError:
                self._job = None

    def _poll(self) -> None:
        self._job = None
        while True:
            try:
                callback, args, finished = self._queue.get_nowait()
            except queue.Empty:
                break
            if finished:
                self._active = max(0, self._active - 1)
            if callback is None:
                continue
            try:
                callback(*args)
            except tk.TclError:
                pass
            except Exception:
                traceback.print_exc()
        if self._active > 0 or not self._queue.empty():
            self._ensure_poll()

    def busy(self) -> bool:
        return self._active > 0
