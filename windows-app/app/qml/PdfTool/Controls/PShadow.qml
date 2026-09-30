import QtQuick
import PdfTool.Style

// Dezenter Schatten unter Flyouts und Dialogen: wenige halbtransparente Ringe statt eines
// Weichzeichners – sparsam, günstig zu zeichnen und auf jedem Grafiksystem gleich.
Item {
    id: root
    property real radius: Metrics.radiusOverlay
    property int depth: 3        // Ringe (Breite des Schattens in px)
    property real strength: 1.0
    anchors.fill: parent
    z: -1
    Repeater {
        model: root.depth
        Rectangle {
            required property int index
            readonly property int grow: index + 1
            x: -grow
            y: -grow + 2
            width: root.width + 2 * grow
            height: root.height + 2 * grow
            radius: root.radius + grow
            color: "transparent"
            border.width: 1
            border.color: Theme.shadow
            opacity: root.strength * (1.0 - index / (root.depth + 1)) * 0.55
        }
    }
}
