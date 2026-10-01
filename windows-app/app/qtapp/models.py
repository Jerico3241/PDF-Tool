"""Listenmodelle für QML (``QAbstractListModel``) mit gezielten Änderungen.

``KeyedListModel`` hält Einträge als Wörterbücher mit eindeutigem Schlüssel. ``set_items()``
gleicht eine neue Liste mit der angezeigten ab und meldet nur die Unterschiede –
``removeRows``, ``insertRows``, ``moveRows`` und ``dataChanged`` für geänderte Rollen.
QML erzeugt dadurch keine Zeilen neu, die sich nicht geändert haben (Auswahl, Fokus und
laufende Animationen bleiben erhalten).
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from PySide6.QtCore import Property, QAbstractListModel, QByteArray, QModelIndex, QObject, Qt, Signal, Slot

# Ab so vielen Verschiebungen ist ein Neuaufbau günstiger als viele einzelne Meldungen
# (z. B. beim Wechsel der Sortierung einer langen Liste).
MOVE_LIMIT = 64


class KeyedListModel(QAbstractListModel):
    countChanged = Signal()

    def __init__(self, roles: Sequence[str], key: str = "key", parent: QObject | None = None) -> None:
        super().__init__(parent)
        if key not in roles:
            roles = (key, *roles)
        self._roles = tuple(roles)
        self._role_ids = {name: Qt.ItemDataRole.UserRole + 1 + index for index, name in enumerate(self._roles)}
        self._key = key
        self._items: list[dict[str, Any]] = []
        self.resets = 0  # Neuaufbauten (Tests, Diagnose)

    # Qt-Schnittstelle -------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._items)

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        return {role: QByteArray(name.encode()) for name, role in self._role_ids.items()}

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return item.get(self._key)
        for name, ident in self._role_ids.items():
            if ident == role:
                return item.get(name)
        return None

    def _count(self) -> int:
        return len(self._items)

    count = Property(int, _count, notify=countChanged)

    # Lesen ------------------------------------------------------------------------------
    @Slot(int, result="QVariantMap")
    def get(self, row: int) -> dict:
        return dict(self._items[row]) if 0 <= row < len(self._items) else {}

    @Slot(str, result=int)
    def indexOf(self, key: str) -> int:  # noqa: N802 - QML-Schreibweise
        for row, item in enumerate(self._items):
            if item.get(self._key) == key:
                return row
        return -1

    def items(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._items]

    def keys(self) -> list:
        return [item.get(self._key) for item in self._items]

    def item(self, key) -> dict[str, Any] | None:
        row = self.indexOf(key)
        return dict(self._items[row]) if row >= 0 else None

    # Ändern -----------------------------------------------------------------------------
    def set_items(self, items: Iterable[dict[str, Any]]) -> None:
        """Neuen Stand übernehmen – nur die Unterschiede werden gemeldet."""
        new = [self._normalize(item) for item in items]
        keys = [item[self._key] for item in new]
        if len(set(keys)) != len(keys):
            raise ValueError("Schlüssel der Listeneinträge sind nicht eindeutig")
        before = len(self._items)
        wanted = set(keys)
        # 1. Entfernte Einträge (zusammenhängende Bereiche von unten nach oben)
        row = len(self._items) - 1
        while row >= 0:
            if self._items[row][self._key] in wanted:
                row -= 1
                continue
            end = row
            while row - 1 >= 0 and self._items[row - 1][self._key] not in wanted:
                row -= 1
            self.beginRemoveRows(QModelIndex(), row, end)
            del self._items[row : end + 1]
            self.endRemoveRows()
            row -= 1
        # 2. Reihenfolge: viele Verschiebungen → einmal neu aufbauen
        current = [item[self._key] for item in self._items]
        order = [key for key in keys if key in set(current)]
        if _moves_needed(current, order) > MOVE_LIMIT:
            self.beginResetModel()
            self._items = new
            self.endResetModel()
            self.resets += 1
            if len(self._items) != before:
                self.countChanged.emit()
            return
        # 3. Einfügen und Verschieben an die Zielposition
        for target, item in enumerate(new):
            key = item[self._key]
            if target < len(self._items) and self._items[target][self._key] == key:
                self._update_row(target, item)
                continue
            source = next((row for row in range(target + 1, len(self._items)) if self._items[row][self._key] == key), -1)
            if source < 0:
                self.beginInsertRows(QModelIndex(), target, target)
                self._items.insert(target, item)
                self.endInsertRows()
                continue
            self.beginMoveRows(QModelIndex(), source, source, QModelIndex(), target)
            moved = self._items.pop(source)
            self._items.insert(target, moved)
            self.endMoveRows()
            self._update_row(target, item)
        if len(self._items) != before:
            self.countChanged.emit()

    def update_item(self, key, /, **changes: Any) -> bool:
        """Einzelne Rollen eines Eintrags ändern (``dataChanged`` nur für diese Rollen).

        ``changes`` darf auch den Schlüssel selbst enthalten (z. B. eine Rolle »key«) – er bleibt gleich."""
        row = self.indexOf(key)
        if row < 0:
            return False
        item = dict(self._items[row])
        item.update(changes)
        self._update_row(row, self._normalize(item))
        return True

    def clear(self) -> None:
        if self._items:
            self.set_items([])

    def _normalize(self, item: dict[str, Any]) -> dict[str, Any]:
        return {name: item.get(name) for name in self._roles}

    def _update_row(self, row: int, item: dict[str, Any]) -> None:
        old = self._items[row]
        changed = [self._role_ids[name] for name in self._roles if old.get(name) != item.get(name) or type(old.get(name)) is not type(item.get(name))]
        if not changed:
            return
        self._items[row] = item
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, changed)


def _moves_needed(current: list, order: list) -> int:
    """Grobe Zahl der Verschiebungen: Einträge außerhalb der längsten gleich geordneten Folge."""
    position = {key: index for index, key in enumerate(order)}
    sequence = [position[key] for key in current if key in position]
    # Länge der längsten steigenden Teilfolge (Patience Sorting)
    import bisect

    tails: list[int] = []
    for value in sequence:
        index = bisect.bisect_left(tails, value)
        if index == len(tails):
            tails.append(value)
        else:
            tails[index] = value
    return len(sequence) - len(tails)
