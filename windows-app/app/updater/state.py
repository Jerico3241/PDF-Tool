"""Zustandsautomat des Updaters: welche Übergänge erlaubt sind.

::

    IDLE ─▶ CHECKING ─▶ UP_TO_DATE | AVAILABLE | ERROR (bzw. still zurück nach IDLE)
    AVAILABLE ─▶ DOWNLOADING ─▶ VERIFYING ─▶ READY ─▶ INSTALLING
                    │               │                    │
                    ▼               ▼                    ▼
                CANCELLED        ERROR                ERROR / READY (Start abgelehnt)

READY ist nur über VERIFYING erreichbar (bzw. zurück aus INSTALLING, wenn der Start abgelehnt
wurde) – ein Setup gilt nie ohne bestandene SHA-256-Prüfung als bereit.

Ein unerlaubter Übergang ist ein Programmfehler (``StateError``) – so fällt ein falscher
Ablauf in den Tests sofort auf, statt still einen widersprüchlichen Zustand anzuzeigen.
"""

from __future__ import annotations

from .models import UpdateState as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.IDLE: frozenset({S.CHECKING, S.AVAILABLE, S.UP_TO_DATE}),
    S.CHECKING: frozenset({S.UP_TO_DATE, S.AVAILABLE, S.ERROR, S.IDLE}),
    S.UP_TO_DATE: frozenset({S.CHECKING, S.AVAILABLE, S.IDLE}),
    S.AVAILABLE: frozenset({S.CHECKING, S.DOWNLOADING, S.VERIFYING, S.IDLE, S.UP_TO_DATE}),
    S.DOWNLOADING: frozenset({S.VERIFYING, S.CANCELLED, S.ERROR, S.IDLE}),
    S.VERIFYING: frozenset({S.READY, S.CANCELLED, S.ERROR, S.IDLE, S.AVAILABLE}),
    S.READY: frozenset({S.INSTALLING, S.CHECKING, S.AVAILABLE, S.UP_TO_DATE, S.IDLE, S.ERROR}),
    S.INSTALLING: frozenset({S.READY, S.ERROR}),
    S.CANCELLED: frozenset({S.CHECKING, S.DOWNLOADING, S.VERIFYING, S.AVAILABLE, S.IDLE, S.UP_TO_DATE}),
    S.ERROR: frozenset({S.CHECKING, S.DOWNLOADING, S.VERIFYING, S.AVAILABLE, S.IDLE, S.UP_TO_DATE}),
}
BUSY = frozenset({S.CHECKING, S.DOWNLOADING, S.VERIFYING, S.INSTALLING})


class StateError(RuntimeError):
    """Unerlaubter Zustandswechsel."""


class StateMachine:
    """Hält den aktuellen Zustand und lässt nur erlaubte Wechsel zu."""

    def __init__(self, initial: S = S.IDLE) -> None:
        self.state = initial
        self.history: list[S] = [initial]

    def can(self, target: S) -> bool:
        return target == self.state or target in TRANSITIONS[self.state]

    def go(self, target: S) -> S:
        if not self.can(target):
            raise StateError(f"Unerlaubter Wechsel: {self.state.value} → {target.value}")
        if target != self.state:
            self.state = target
            self.history.append(target)
            del self.history[:-50]
        return target

    @property
    def busy(self) -> bool:
        """Läuft gerade etwas (Prüfen, Laden, Verifizieren, Installieren)?"""
        return self.state in BUSY
