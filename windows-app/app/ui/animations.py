"""Zeitbasierte Animationen für Tk.

Alle Animationen laufen über einen gemeinsamen Takt, der nur aktiv ist,
solange tatsächlich etwas animiert wird (keine CPU-Last im Leerlauf). Der
``AnimationManager`` entscheidet zentral, ob überhaupt animiert wird: nicht
bei ausgeschalteten Animationen, nicht während die Oberfläche unsichtbar
aufgebaut wird und nicht, solange das Fenster in der Größe verändert wird.
Animationen springen dann sofort in ihren Endzustand.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import tkinter as tk

from . import windows

# Dauer nach den Windows-Motion-Richtlinien (Millisekunden). Alle Übergänge sind zeitbasiert,
# abbrechbar und laufen nie in einer Warteschlange: Ein neuer Übergang ersetzt den alten.
PRESS = 67  # Drücken (50–80 ms)
FAST = 83  # Farbwechsel bei Hover (70–100 ms)
HOVER_OUT = 100  # Hover verlassen
NORMAL = 167  # Zustandswechsel, Schalter, InfoBar, Ein-/Ausklappen (150–220 ms)
PAGE = 180  # Seitenwechsel und Auswahlindikator der Navigation (140–200 ms)
DIALOG = 167  # Dialoge einblenden (140–200 ms)
DIALOG_OUT = 120  # Dialoge ausblenden
SLOW = 250  # früherer Name für Dialoge


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
    essential: bool


class AnimationManager:
    """Zentrale Verwaltung aller Animationen und Zeitgeber der Oberfläche.

    * ``animations_enabled``: Einstellung »Animationen« (App oder Windows)
    * ``reduce_motion``: Windows meldet »Animationseffekte aus« – Bewegungen
      (``motion=True``: Gleiten, Ein-/Ausklappen, Scrollen) springen dann sofort
      in den Endzustand, dezente Überblendungen bleiben
    * ``is_resizing``: das Fenster wird gerade in der Größe verändert – nicht
      notwendige Animationen springen dann sofort in ihren Endzustand
    * ``is_navigating``: ein Seitenwechsel wird gerade ausgeführt
    * ``active_animations``: Anzahl laufender Animationen (im Leerlauf 0)
    * ``suspend()``: während die Oberfläche unsichtbar aufgebaut wird, laufen
      keine Animationen (kein gestaffeltes Einblenden beim Start)
    """

    FRAME_MS = 15

    def __init__(self, root: tk.Tk, enabled: bool = True, reduce_motion: bool = False) -> None:
        self.root = root
        self.enabled = enabled
        self.reduce_motion = reduce_motion
        self._resizing = False
        self.is_navigating = False
        self._suspended = 0
        self._anims: dict[str, _Anim] = {}
        self._timers: dict[str, str] = {}
        self._tick_id: str | None = None
        self._timer_res = windows.TimerResolution()

    # Zustand ----------------------------------------------------------------
    @property
    def animations_enabled(self) -> bool:
        return self.enabled

    @animations_enabled.setter
    def animations_enabled(self, value: bool) -> None:
        self.enabled = bool(value)
        if not self.enabled:
            self.finish_all(include_essential=True)

    @property
    def is_resizing(self) -> bool:
        return self._resizing

    @is_resizing.setter
    def is_resizing(self, value: bool) -> None:
        value = bool(value)
        if value and not self._resizing:
            # Laufende Übergänge sofort abschließen: das Layout ist dann endgültig.
            self.finish_all()
        self._resizing = value

    @property
    def active_animations(self) -> int:
        return len(self._anims)

    def allowed(self, essential: bool = False, motion: bool = False) -> bool:
        """Darf jetzt animiert werden? (Aus, beim Aufbau oder während eines Resize: nein;
        Bewegungen auch nicht bei »Animationseffekte aus« in Windows.)"""
        if not self.enabled or self._suspended:
            return False
        if motion and self.reduce_motion:
            return False
        return essential or not self._resizing

    def suspend(self) -> None:
        self._suspended += 1
        self.finish_all(include_essential=True)

    def resume(self) -> None:
        self._suspended = max(0, self._suspended - 1)

    # Animationen ---------------------------------------------------------
    def run(
        self,
        key: str,
        duration: float,
        step: Callable[[float], None],
        done: Callable[[], None] | None = None,
        easing: Callable[[float], float] = DECELERATE,
        widget: tk.Misc | None = None,
        essential: bool = False,
        motion: bool = False,
    ) -> None:
        """Startet (oder ersetzt) die Animation ``key``. ``step`` erhält 0…1 nach Easing.

        Ist Animation gerade nicht erlaubt, wird sofort der Endzustand gesetzt. ``motion``:
        eine Bewegung (entfällt bei »Animationseffekte aus«).
        """
        self._anims.pop(key, None)
        if duration <= 0 or not self.allowed(essential, motion):
            self._safe_call(step, 1.0)
            if done:
                self._safe_call(done)
            return
        self._anims[key] = _Anim(time.perf_counter(), duration / 1000.0, step, done, easing, widget, essential)
        self._safe_call(step, easing(0.0))
        self._ensure_tick()

    def cancel(self, key: str, finish: bool = False) -> None:
        anim = self._anims.pop(key, None)
        if anim and finish:
            self._finish(anim)

    def cancel_widget(self, widget: tk.Misc, finish: bool = True) -> None:
        """Alle Animationen eines Widgets beenden (standardmäßig im Endzustand)."""
        for key, anim in list(self._anims.items()):
            if anim.widget is widget:
                self._anims.pop(key, None)
                if finish:
                    self._finish(anim)

    def finish_all(self, include_essential: bool = False) -> None:
        for key, anim in list(self._anims.items()):
            if include_essential or not anim.essential:
                if self._anims.pop(key, None) is not None:
                    self._finish(anim)

    def running(self, key: str) -> bool:
        return key in self._anims

    def active(self) -> bool:
        """Läuft irgendeine Animation oder ein Zeitgeber? (Im Leerlauf: False.)"""
        return bool(self._anims) or bool(self._timers)

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
    def _finish(self, anim: _Anim) -> None:
        self._safe_call(anim.step, 1.0)
        if anim.done:
            self._safe_call(anim.done)

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
                self._finish(anim)
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


# Früherer Name
Animator = AnimationManager


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t
