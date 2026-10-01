"""Ablage der Vorlagen: je Vorlage eine kleine JSON-Datei im Datenordner.

::

    %APPDATA%\\PDF-Tool\\vorlagen\\
        3f2a9c1b-….json
        8d41e0aa-….json

* Dateiname ist die stabile ID – umbenennen ändert nur den Inhalt, nie den Namen der Datei.
* Jede Datei wird atomar geschrieben (``storage.write_json``).
* Eine beschädigte Datei betrifft nur diese eine Vorlage: Sie wird übersprungen und als Problem
  gemeldet (Diagnose), nie gelöscht oder überschrieben. Dasselbe gilt für Vorlagen einer neueren
  PDF-Tool-Version.
* Ohne Ordner (``folder=None``) arbeitet der Speicher nur im Arbeitsspeicher (Tests).
"""

from __future__ import annotations

from dataclasses import replace

from storage import JsonFolderStore, StoreProblem  # noqa: F401 - StoreProblem für Aufrufer

from .models import (
    KIND,
    MAX_NAME,
    Template,
    TemplateLayout,
    TemplateMetadata,
    TemplateRichText,
    TemplateRuleReference,
    clean_name,
    new_id,
    now_iso,
)

FOLDER = "vorlagen"
COPY_SUFFIX = " – Kopie"


def _sort_name(template: Template) -> tuple[str, str]:
    return (template.name.casefold(), template.id)


def unique_name(names, base: str, fallback: str) -> str:
    """``base``, sonst ``base 2``, ``base 3`` … – ohne Groß-/Kleinschreibung verglichen."""
    taken = {str(name).casefold() for name in names}
    base = clean_name(base) or fallback
    if base.casefold() not in taken:
        return base
    number = 2
    while True:
        suffix = f" {number}"
        candidate = base[: MAX_NAME - len(suffix)] + suffix
        if candidate.casefold() not in taken:
            return candidate
        number += 1


class TemplateStore(JsonFolderStore):
    """Alle Vorlagen. Änderungen werden sofort gespeichert (``last_error`` bei Schreibfehlern)."""

    kind = KIND

    def parse(self, data) -> Template:
        return Template.from_dict(data)

    def serialize(self, item: Template) -> dict:
        return item.to_dict()

    # Lesen ---------------------------------------------------------------------------------------------
    def templates(self) -> list[Template]:
        """Alle Vorlagen, alphabetisch."""
        return sorted(self.values(), key=_sort_name)

    def recent(self) -> list[Template]:
        """Zuletzt gespeicherte zuerst (Reihenfolge der Vorlagen bis 2.7)."""
        return sorted(self.values(), key=lambda t: (t.meta.updated_at, t.id), reverse=True)

    def by_name(self, name: str) -> Template | None:
        """Exakt gleicher Name (wie bis 2.7), sonst ohne Groß-/Kleinschreibung."""
        name = clean_name(name)
        if not name:
            return None
        for match in (lambda t: t.name == name, lambda t: t.name.casefold() == name.casefold()):
            found = [t for t in self.values() if match(t)]
            if found:
                return max(found, key=lambda t: t.meta.updated_at)
        return None

    def find(self, ref: str | None) -> Template | None:
        """Verweis auflösen: ID (ab 2.8) oder Name (Verweise aus 2.7)."""
        if not ref:
            return None
        return self.get(ref) or self.by_name(ref)

    def name_taken(self, name: str, except_id: str | None = None) -> bool:
        folded = clean_name(name).casefold()
        return any(t.name.casefold() == folded and t.id != except_id for t in self.values())

    def unique_name(self, base: str, except_id: str | None = None) -> str:
        return unique_name((t.name for t in self.values() if t.id != except_id), base, "Vorlage")

    # Schreiben -----------------------------------------------------------------------------------------
    def create(
        self,
        name: str,
        layout: TemplateLayout | None = None,
        header: TemplateRichText | None = None,
        footer: TemplateRichText | None = None,
        rules: TemplateRuleReference | None = None,
        description: str = "",
    ) -> Template | None:
        stamp = now_iso()
        template = Template(
            meta=TemplateMetadata(id=new_id(), name=clean_name(name), description=description.strip(), created_at=stamp, updated_at=stamp),
            layout=layout or TemplateLayout(),
            header=header or TemplateRichText.from_dict(None, True),
            footer=footer or TemplateRichText.from_dict(None, False),
            rules=rules or TemplateRuleReference(),
        )
        return template if self.put(template) else None

    def update(self, template: Template) -> Template | None:
        """Geänderte Vorlage speichern (Änderungsdatum neu)."""
        changed = template.with_meta(updated_at=now_iso())
        return changed if self.put(changed) else None

    def rename(self, template_id: str, name: str) -> Template | None:
        template = self.get(template_id)
        if template is None:
            return None
        return self.update(template.with_meta(name=clean_name(name)))

    def describe(self, template_id: str, description: str) -> Template | None:
        template = self.get(template_id)
        if template is None:
            return None
        return self.update(template.with_meta(description=description.strip()))

    def duplicate(self, template_id: str) -> Template | None:
        """Kopie mit neuer ID und dem Namen »… – Kopie« (eindeutig)."""
        template = self.get(template_id)
        if template is None:
            return None
        stamp = now_iso()
        copy = replace(
            template,
            meta=TemplateMetadata(
                id=new_id(),
                name=self.unique_name(template.name[: MAX_NAME - len(COPY_SUFFIX) - 3] + COPY_SUFFIX),
                description=template.meta.description,
                created_at=stamp,
                updated_at=stamp,
            ),
        )
        return copy if self.put(copy) else None

    def delete(self, template_id: str) -> bool:
        return self.remove(template_id)

    def using_rule_set(self, rule_set_id: str) -> list[Template]:
        """Vorlagen, die dieses Regelwerk festlegen."""
        return [template for template in self.templates() if rule_set_id and template.rules.rule_set_id == rule_set_id]

    def detach_rule_set(self, rule_set_id: str) -> int:
        """Gelöschtes Regelwerk: Vorlagen, die es festlegten, verwenden danach bewusst keines (``""``)."""
        changed = 0
        for template in self.using_rule_set(rule_set_id):
            if self.update(replace(template, rules=replace(template.rules, rule_set_id=""))) is not None:
                changed += 1
        return changed
