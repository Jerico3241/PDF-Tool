import QtQuick

// Menüpunkte aus einem Modell für ein PMenu (statt eines Repeaters im Menü). Ein Repeater erzeugt seine Einträge
// asynchron, wenn die Seite asynchron geladen wird – dann in wechselnder Reihenfolge, und die QML-Engine meldet
// »stackBefore … must be a sibling« (gelegentlich in der Windows-Prüfung). Instantiator erzeugt synchron und der
// Reihe nach; die Einträge landen über insertItem im Menü, nach ``offset`` festen Einträgen.
Instantiator {
    id: items
    required property var menu
    property int offset: 0
    onObjectAdded: (index, object) => items.menu.insertItem(items.offset + index, object)
    onObjectRemoved: (index, object) => items.menu.removeItem(object)
}
