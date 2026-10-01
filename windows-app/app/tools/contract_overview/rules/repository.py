"""Ablage der Regelwerke: je Regelwerk eine JSON-Datei ``regelwerke\\<id>.json``.

Wie die Vorlagen: atomar geschrieben, beschädigte oder neuere Dateien werden übersprungen und
gemeldet (nie gelöscht), ohne Ordner nur im Arbeitsspeicher (Tests).
"""

from __future__ import annotations

from dataclasses import replace

from storage import JsonFolderStore

from ..templates.repository import unique_name
from .models import KIND, MAX_NAME, Rule, RuleSet, clean_name, new_id, now_iso

FOLDER = "regelwerke"
COPY_SUFFIX = " – Kopie"


class RuleSetStore(JsonFolderStore):
    kind = KIND

    def parse(self, data) -> RuleSet:
        return RuleSet.from_dict(data)

    def serialize(self, item: RuleSet) -> dict:
        return item.to_dict()

    def rule_sets(self) -> list[RuleSet]:
        """Alle Regelwerke, alphabetisch."""
        return sorted(self.values(), key=lambda item: (item.name.casefold(), item.id))

    def by_name(self, name: str) -> RuleSet | None:
        folded = clean_name(name).casefold()
        return next((item for item in self.rule_sets() if item.name.casefold() == folded), None)

    def name_taken(self, name: str, except_id: str | None = None) -> bool:
        folded = clean_name(name).casefold()
        return any(item.name.casefold() == folded and item.id != except_id for item in self.values())

    def unique_name(self, base: str, except_id: str | None = None) -> str:
        return unique_name((item.name for item in self.values() if item.id != except_id), base, "Regelwerk")

    def create(self, name: str, description: str = "", rules: tuple[Rule, ...] = ()) -> RuleSet | None:
        stamp = now_iso()
        rule_set = RuleSet(id=new_id(), name=clean_name(name), description=description.strip(), rules=tuple(rules), created_at=stamp, updated_at=stamp)
        return rule_set if self.put(rule_set) else None

    def update(self, rule_set: RuleSet) -> RuleSet | None:
        changed = rule_set.with_(updated_at=now_iso())
        return changed if self.put(changed) else None

    def rename(self, rule_set_id: str, name: str) -> RuleSet | None:
        rule_set = self.get(rule_set_id)
        return None if rule_set is None else self.update(rule_set.with_(name=clean_name(name)))

    def duplicate(self, rule_set_id: str) -> RuleSet | None:
        """Kopie mit neuen IDs (Regelwerk und Regeln) und dem Namen »… – Kopie«."""
        rule_set = self.get(rule_set_id)
        if rule_set is None:
            return None
        stamp = now_iso()
        copy = replace(
            rule_set,
            id=new_id(),
            name=self.unique_name(rule_set.name[: MAX_NAME - len(COPY_SUFFIX) - 3] + COPY_SUFFIX),
            rules=tuple(replace(rule, id=new_id()) for rule in rule_set.rules),
            created_at=stamp,
            updated_at=stamp,
        )
        return copy if self.put(copy) else None

    def delete(self, rule_set_id: str) -> bool:
        return self.remove(rule_set_id)
