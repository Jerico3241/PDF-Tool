"""Zeitbasierte Animationen für Tk.

Alle Animationen laufen über einen gemeinsamen Takt, der nur aktiv ist,
solange tatsächlich etwas animiert wird (keine CPU-Last im Leerlauf).
``Animator.enabled`` schaltet sämtliche Bewegung zentral ab: Animationen
springen dann sofort in ihren Endzustand.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import tkinter as tk

from . import windows

# Dauer nach den Windows-Motion-Richtlinien (Millisekunden)
FAST = 83  # Farbwechsel bei Hover
NORMAL = 167  # Zustandswechsel, Schalter
PAGE = 220  # Seitenwechsel
SLOW = 250


def cubic_bezier(x1: float, y1: float, x2: float, y2: float) -> Callable[[float], float]:
    """Easing-Funktion wie CSS cubic-bezier()."""

    def sample(a1: float, a2: float, t: float) -> float:
        return ((1 - 3 * a2 + 3 * a1) * t + (3 * a2 - 6 * a1)) * t * t + 3 * a1 * t

    def slope(a1: float, a2: float, t: float) -> float:
        return 3 * (1 - 3 * a2 + 3 * a1) * t * t + 2 * (3 * a2 - 6 * a1) * t + 3 * a1

    def ease(x: float) -> float:
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        t = x
        for _ in range(8):
            s = slope(x1, x2, t)
            if abs(s) < 1e-6:
                break
            t -= (sample(x1, x2, t) - x) / s
        lo, hi = 0.0, 1.0
        t = max(0.0, min(1.0, t))
        if abs(sample(x1, x2, t) - x) > 1e-4:
            t = x
            for _ in range(30):
                value = sample(x1, x2, t)
                if abs(value - x) < 1e-5:
                    break
                if value < x:
                    lo = t
                else:
                    hi = t
                t = (lo + hi) / 2
        return sample(y1, y2, t)

    return ease


# Windows-Kurven: »Decelerate« für eintretende Elemente, »Point to point« für Bewegungen
DECELERATE = cubic_bezier(0.0, 0.0, 0.0, 1.0)
EASE_OUT = cubic_bezier(0.1, 0.9, 0.2, 1.0)
POINT_TO_POINT = cubic_bezier(0.55, 0.55, 0.0, 1.0)
EASE_IN_OUT = cubic_bezier(0.65, 0.0, 0.35, 1.0)
ACCELERATE = cubic_bezier(1.0, 0.0, 1.0, 1.0)


def linear(t: float) -> float:
    return t


@dataclass
class _Anim:
    start: float
    duration: float
    step: Callable[[float], None]
    done: Callable[[], None] | None
    easing: Callable[[float], float]
    widget: tk.Misc | None


class Animator:
    FRAME_MS = 15

    def __init__(self, root: tk.Tk, enabled: bool = True) -> None:
        self.root = root
        self.enabled = enabled
        self._anims: dict[str, _Anim] = {}
        self._timers: dict[str, str] = {}
        self._tick_id: str | None = None
        self._timer_res = windows.TimerResolution()

    # Animationen ---------------------------------------------------------
    def run(
        self,
        key: str,
        duration: float,
        step: Callable[[float], None],
        done: Callable[[], None] | None = None,
        easing: Callable[[float], float] = DECELERATE,
        widget: tk.Misc | None = None,
    ) -> None:
        """Startet (oder ersetzt) die Animation ``key``. ``step`` erhält 0…1 nach Easing."""
        self._anims.pop(key, None)
        if not self.enabled or duration <= 0:
            self._safe_call(step, 1.0)
            if done:
                self._safe_call(done)
            return
        self._anims[key] = _Anim(time.perf_counter(), duration / 1000.0, step, done, easing, widget)
        self._safe_call(step, easing(0.0))
        self._ensure_tick()

    def cancel(self, key: str, finish: bool = False) -> None:
        anim = self._anims.pop(key, None)
        if anim and finish:
            self._safe_call(anim.step, 1.0)
            if anim.done:
                self._safe_call(anim.done)

    def running(self, key: str) -> bool:
        return key in self._anims

    # Zeitgeber ----------------------------------------------------------------
    def later(self, key: str, delay_ms: int, func: Callable[[], None]) -> None:
        """Einmaliger, abbrechbarer Zeitgeber (ersetzt einen gleichnamigen)."""
        self.cancel_later(key)

        def fire() -> None:
            self._timers.pop(key, None)
            self._safe_call(func)

        try:
            self._timers[key] = self.root.after(max(0, int(delay_ms)), fire)
        except tk.TclError:
            pass

    def cancel_later(self, key: str) -> None:
        timer = self._timers.pop(key, None)
        if timer:
            try:
                self.root.after_cancel(timer)
            except tk.TclError:
                pass

    def cancel_prefix(self, prefix: str) -> None:
        for key in [k for k in self._anims if k.startswith(prefix)]:
            self._anims.pop(key, None)
        for key in [k for k in self._timers if k.startswith(prefix)]:
            self.cancel_later(key)

    # Intern ------------------------------------------------------------------
    @staticmethod
    def _safe_call(func: Callable, *args) -> bool:
        try:
            func(*args)
            return True
        except tk.TclError:
            return False
        except Exception:
            import traceback

            traceback.print_exc()
            return False

    def _ensure_tick(self) -> None:
        if self._tick_id is None:
            self._timer_res.acquire()
            try:
                self._tick_id = self.root.after(self.FRAME_MS, self._tick)
            except tk.TclError:
                self._tick_id = None

    def _tick(self) -> None:
        self._tick_id = None
        now = time.perf_counter()
        for key, anim in list(self._anims.items()):
            if self._anims.get(key) is not anim:
                continue
            if anim.widget is not None:
                try:
                    alive = bool(anim.widget.winfo_exists())
                except tk.TclError:
                    alive = False
                if not alive:
                    self._anims.pop(key, None)
                    continue
            progress = (now - anim.start) / anim.duration if anim.duration > 0 else 1.0
            if progress >= 1.0:
                self._anims.pop(key, None)
                self._safe_call(anim.step, 1.0)
                if anim.done:
                    self._safe_call(anim.done)
                continue
            if not self._safe_call(anim.step, anim.easing(progress)):
                self._anims.pop(key, None)
        if self._anims:
            self._ensure_tick()
        else:
            self._timer_res.release()

    def shutdown(self) -> None:
        self._anims.clear()
        for key in list(self._timers):
            self.cancel_later(key)
        if self._tick_id:
            try:
                self.root.after_cancel(self._tick_id)
            except tk.TclError:
                pass
            self._tick_id = None
        self._timer_res.release()


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t
