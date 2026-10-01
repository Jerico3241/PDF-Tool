"""Wann automatisch geprüft wird: höchstens alle 24 Stunden – gezählt ab der letzten
*erfolgreichen* Prüfung. Eine fehlgeschlagene Prüfung (z. B. offline) zählt nicht.

Zeitpunkte werden in UTC gespeichert (``2026-10-01T09:30:00Z``). Liegt der gespeicherte
Zeitpunkt in der Zukunft (Uhr zurückgestellt), gilt die Prüfung als fällig – sonst würde
nie wieder geprüft.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

INTERVAL = timedelta(hours=24)
CLOCK_TOLERANCE = timedelta(minutes=5)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: object) -> datetime | None:
    """Gespeicherter Zeitpunkt → ``datetime`` (UTC); fehlend oder ungültig → ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def format_time(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def due(last_success: datetime | None, now: datetime | None = None, interval: timedelta = INTERVAL) -> bool:
    """Ist eine automatische Prüfung fällig?"""
    if last_success is None:
        return True
    current = now or now_utc()
    if last_success > current + CLOCK_TOLERANCE:
        return True
    return current - last_success >= interval
