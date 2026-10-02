"""Rückgängig/Wiederholen für alle Bearbeitungen – je Dokument ein eigener Verlauf.

Jede Änderung am pikepdf-Stand läuft über ``record()``: Vorher werden die betroffenen Einträge
gemerkt, dann wird geändert, danach der neue Stand gemerkt. Gemerkt werden **Verweise** auf
Objekte (Inhaltsströme, Ressourcen, Anmerkungslisten …), keine Kopien großer Daten.
Rückgängig/Wiederholen setzt nur diese Verweise zurück.

Damit das trägt, gelten für alle Änderungen zwei Regeln:

* Bestehende Streams (Inhalte, Bilder, Schriften) werden nie in place verändert, sondern durch
  neue Objekte ersetzt.
* Gemeinsam genutzte Dictionaries (z. B. dieselben ``/Resources`` für mehrere Seiten) werden vor
  einer Änderung für die Seite kopiert (``own_dict``).

Was nach einem Rückgängig niemand mehr erreicht, schreibt qpdf beim Speichern nicht mit – der
Verlauf bläht die Datei nicht auf.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

import pikepdf

from .document import EditorDocument

PAGE_KEYS = ("/Contents", "/Resources", "/Annots", "/Rotate", "/MediaBox", "/CropBox", "/Group", "/UserUnit")
HISTORY_LIMIT = 100


@dataclass
class ObjectState:
    """Ausgewählte Einträge eines Dictionaries (``None`` = Eintrag fehlt)."""

    obj: pikepdf.Object
    values: dict[str, object]

    @classmethod
    def capture(cls, obj: pikepdf.Object, keys) -> "ObjectState":
        return cls(obj, {key: obj.get(key) for key in keys})

    def restore(self) -> None:
        for key, value in self.values.items():
            if value is None:
                if key in self.obj:
                    del self.obj[key]
            else:
                self.obj[key] = value


@dataclass
class PageOrder:
    """Reihenfolge der Seitenobjekte (Identität bleibt beim Entfernen/Einfügen erhalten)."""

    pages: list[pikepdf.Object]

    @classmethod
    def capture(cls, pdf: pikepdf.Pdf) -> "PageOrder":
        return cls([page.obj for page in pdf.pages])

    def restore(self, pdf: pikepdf.Pdf) -> None:
        current = [page.obj.objgen for page in pdf.pages]
        if current == [obj.objgen for obj in self.pages]:
            return
        while len(pdf.pages):
            del pdf.pages[-1]
        for obj in self.pages:
            pdf.pages.append(pikepdf.Page(obj))


@dataclass
class Snapshot:
    objects: list[ObjectState] = field(default_factory=list)
    order: PageOrder | None = None

    def restore(self, pdf: pikepdf.Pdf) -> None:
        if self.order is not None:
            self.order.restore(pdf)
        for state in self.objects:
            state.restore()


@dataclass
class Command:
    """Eine rückgängig machbare Änderung."""

    title: str  # für »Rückgängig: …« (z. B. »Text bearbeiten«)
    before: Snapshot
    after: Snapshot
    pages: tuple[int, ...] = ()  # betroffene Seiten (Index nach der Änderung) – zum Neuzeichnen
    structure: bool = False  # Seitenzahl oder -reihenfolge geändert
    info: dict = field(default_factory=dict)  # z. B. Bearbeitungsmodus eines Textes

    def undo(self, document: EditorDocument) -> None:
        self.before.restore(document.pdf)
        document.touch()

    def redo(self, document: EditorDocument) -> None:
        self.after.restore(document.pdf)
        document.touch()


class Recorder:
    """Sammelt, was eine Änderung betrifft – vor der Änderung festlegen."""

    def __init__(self, document: EditorDocument) -> None:
        self.document = document
        self._objects: list[tuple[pikepdf.Object, tuple[str, ...]]] = []
        self.structure = False

    def page(self, index: int, keys=PAGE_KEYS) -> pikepdf.Object:
        obj = self.document.pdf.pages[index].obj
        self.object(obj, keys)
        return obj

    def object(self, obj: pikepdf.Object, keys) -> None:
        self._objects.append((obj, tuple(keys)))

    def root(self, keys) -> None:
        self.object(self.document.pdf.Root, keys)

    def page_order(self) -> None:
        self.structure = True

    def _snapshot(self) -> Snapshot:
        pdf = self.document.pdf
        return Snapshot(
            objects=[ObjectState.capture(obj, keys) for obj, keys in self._objects],
            order=PageOrder.capture(pdf) if self.structure else None,
        )


class History:
    """Verlauf eines Dokuments (begrenzt auf ``limit`` Schritte)."""

    def __init__(self, limit: int = HISTORY_LIMIT) -> None:
        self.limit = limit
        self._done: list[Command] = []
        self._undone: list[Command] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)

    @property
    def undo_title(self) -> str:
        return self._done[-1].title if self._done else ""

    @property
    def redo_title(self) -> str:
        return self._undone[-1].title if self._undone else ""

    def push(self, command: Command) -> None:
        self._done.append(command)
        self._undone.clear()
        del self._done[: max(0, len(self._done) - self.limit)]

    def undo(self, document: EditorDocument) -> Command | None:
        if not self._done:
            return None
        command = self._done.pop()
        command.undo(document)
        self._undone.append(command)
        return command

    def redo(self, document: EditorDocument) -> Command | None:
        if not self._undone:
            return None
        command = self._undone.pop()
        command.redo(document)
        self._done.append(command)
        return command

    def clear(self) -> None:
        self._done.clear()
        self._undone.clear()


@contextmanager
def record(document: EditorDocument, history: History, title: str, *, pages: tuple[int, ...] = ()) -> Iterator[Recorder]:
    """``with record(doc, history, "Text bearbeiten", pages=(3,)) as rec: rec.page(3); …ändern…``

    Die Einträge werden **vor** dem ersten Ändern festgelegt (``rec.page``, ``rec.object`` …),
    der Zustand davor wird beim Verlassen des ``with``-Blocks nachträglich nicht mehr erfasst –
    deshalb hält ``Recorder`` sofort beim Festlegen den Vorher-Stand fest. Wirft der Block, wird
    der Vorher-Stand wiederhergestellt und nichts in den Verlauf geschrieben.
    """
    recorder = _EagerRecorder(document)
    try:
        yield recorder
    except BaseException:
        recorder.rollback()
        document.touch()
        raise
    command = Command(title, recorder.before(), recorder._snapshot(), pages=tuple(pages), structure=recorder.structure, info=dict(recorder.info))
    history.push(command)
    if not recorder.fresh:
        document.touch()


class _EagerRecorder(Recorder):
    """Recorder, der den Vorher-Stand jedes Eintrags beim Festlegen erfasst."""

    def __init__(self, document: EditorDocument) -> None:
        super().__init__(document)
        self._before: list[ObjectState] = []
        self._order: PageOrder | None = None
        self.info: dict = {}
        # ``True``: Die Änderung ist abgeschlossen und die Darstellung wurde danach schon neu
        # geladen (z. B. zur Prüfung) – dann kein weiteres ``touch()`` (spart ein Serialisieren).
        self.fresh = False

    def object(self, obj: pikepdf.Object, keys) -> None:
        keys = tuple(keys)
        if any(existing.objgen == obj.objgen and existing_keys == keys for existing, existing_keys in self._objects if obj.is_indirect):
            return
        super().object(obj, keys)
        self._before.append(ObjectState.capture(obj, keys))

    def page_order(self) -> None:
        if self._order is None:
            self._order = PageOrder.capture(self.document.pdf)
        super().page_order()

    def before(self) -> Snapshot:
        return Snapshot(objects=list(self._before), order=self._order)

    def rollback(self) -> None:
        self.before().restore(self.document.pdf)


def own_dict(container: pikepdf.Object, key: str, pdf: pikepdf.Pdf) -> pikepdf.Dictionary:
    """``container[key]`` als eigenes (neues) Dictionary dieser Seite – vorhandene Einträge werden
    flach übernommen (Verweise auf Schriften, Bilder … bleiben dieselben Objekte)."""
    current = container.get(key)
    fresh = pikepdf.Dictionary()
    if isinstance(current, pikepdf.Dictionary):
        for name, value in current.items():
            fresh[name] = value
    container[key] = fresh
    return container[key]


def own_resources(page: pikepdf.Object, pdf: pikepdf.Pdf, *categories: str) -> pikepdf.Dictionary:
    """Eigene ``/Resources`` der Seite samt eigenen Unter-Dictionaries (``/Font``, ``/XObject`` …)
    – vererbte Ressourcen werden dabei übernommen, damit nichts verloren geht."""
    from .document import inherited

    inherited_resources = inherited(page, "/Resources")
    resources = pikepdf.Dictionary()
    if isinstance(inherited_resources, pikepdf.Dictionary):
        for name, value in inherited_resources.items():
            resources[name] = value
    page["/Resources"] = resources
    resources = page["/Resources"]
    for category in categories:
        own_dict(resources, category, pdf)
    return resources
