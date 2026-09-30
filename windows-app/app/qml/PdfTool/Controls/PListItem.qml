import QtQuick
import PdfTool.Style

// Hintergrund einer Listenzeile: Hover, Druck, Auswahl (mit Markierung links) und Tastaturfokus.
Rectangle {
    id: root
    property bool hovered: false
    property bool pressed: false
    property bool selected: false
    property bool focused: false
    radius: Metrics.radiusControl
    color: pressed ? Theme.subtlePressed : (selected ? Theme.subtleHover : (hovered ? Theme.subtleHover : "transparent"))
    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
    Rectangle {
        width: 3
        height: root.selected ? 16 : 0
        radius: 1.5
        color: Theme.accent
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        Behavior on height { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }
    }
    PFocusRing { visible: root.focused; inset: -1 }
}
