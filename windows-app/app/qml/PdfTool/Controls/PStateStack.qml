import QtQuick
import PdfTool.Style

// Mehrere Zustände an derselben Stelle (z. B. Leer → Wird erstellt → Ergebnis). Beim Wechsel
// blenden alter und neuer Zustand ineinander über; die Höhe folgt weich dem neuen Inhalt.
// Nicht sichtbare Zustände werden nicht gezeichnet.
Item {
    id: root
    property int currentIndex: 0
    property bool animateHeight: true
    readonly property Item currentItem: currentIndex >= 0 && currentIndex < children.length ? children[currentIndex] : null

    implicitWidth: currentItem ? currentItem.implicitWidth : 0
    implicitHeight: currentItem ? currentItem.implicitHeight : 0
    clip: heightAnim.running
    Behavior on implicitHeight {
        enabled: root.animateHeight && Motion.expand > 0
        NumberAnimation { id: heightAnim; duration: Motion.expand; easing.type: Motion.decelerate }
    }

    function sync() {
        for (var i = 0; i < children.length; ++i) {
            var child = children[i]
            child.width = Qt.binding(function() { return root.width })
            child.opacity = Qt.binding((function(index) { return function() { return root.currentIndex === index ? 1 : 0 } })(i))
            child.visible = Qt.binding((function(item) { return function() { return item.opacity > 0.001 } })(child))
        }
    }
    Component.onCompleted: sync()
    onChildrenChanged: sync()
}
