"""Übernahme der Vorlagen bis 2.7 (``gui-config.json`` → ``vorlagen``) in Vorlagen 2.0.

* Einmalig beim ersten Start von 2.8: Jede gespeicherte Vorlage erhält eine eigene Datei mit
  stabiler ID. Name, Darstellung, Kopf-/Fußzeile (samt Formatierung) und Zyklus-Regeln bleiben
  exakt erhalten – das Anwenden ergibt dasselbe wie vorher.
* Die bisherige Liste in ``gui-config.json`` bleibt unverändert stehen (keine Datenverluste,
  eine ältere Version findet ihre Vorlagen weiterhin). Die Markierung ``MIGRATED_KEY`` sorgt
  dafür, dass sie nur einmal übernommen wird – auch wenn später Vorlagen gelöscht werden.
* Die Reihenfolge bleibt: zuletzt gespeicherte Vorlage zuerst.
* Schlägt das Schreiben fehl, bleibt die Markierung aus; der nächste Start versucht es erneut
  (bereits übernommene Namen werden dabei nicht doppelt angelegt).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import Template, clean_name
from .repository import TemplateStore

MIGRATED_KEY = "vorlagen_2"  # Wert: Version, mit der übernommen wurde


def legacy_entries(cfg: dict) -> list[dict]:
    return [entry for entry in cfg.get("vorlagen") or [] if isinstance(entry, dict) and clean_name(entry.get("name"))]


def needs_migration(cfg: dict) -> bool:
    return not cfg.get(MIGRATED_KEY) and bool(legacy_entries(cfg))


def migrate(store: TemplateStore, cfg: dict, version: str) -> tuple[int, list[str]]:
    """Vorlagen übernehmen. Rückgabe: (Anzahl neu angelegt, Fehlermeldungen).

    Setzt ``cfg[MIGRATED_KEY]`` nur, wenn alles geschrieben werden konnte (der Aufrufer speichert).
    """
    if cfg.get(MIGRATED_KEY):
        return 0, []
    entries = legacy_entries(cfg)
    created = 0
    errors: list[str] = []
    base = datetime.now().astimezone()
    # Neueste Vorlage zuerst in der Liste – sie erhält den jüngsten Zeitstempel.
    for index, entry in enumerate(entries):
        name = clean_name(entry.get("name"))
        if store.name_taken(name):
            continue  # bereits übernommen (früherer, unterbrochener Versuch)
        stamp = (base - timedelta(seconds=index)).isoformat(timespec="microseconds")
        template = Template.from_entry(entry, created_at=stamp, updated_at=stamp)
        if store.put(template):
            created += 1
        else:
            errors.append(store.last_error)
    if not errors:
        cfg[MIGRATED_KEY] = version
    return created, errors
