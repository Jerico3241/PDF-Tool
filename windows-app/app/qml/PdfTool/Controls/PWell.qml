import QtQuick
import PdfTool.Style

// Mulde im 3D-Design (Entwurf 7): die Arbeitsfläche liegt tiefer – innerer Schatten oben, feine Kontur
// (im Neon-Modus im Neon-Ton). Liegt über dem Inhalt und lässt Klicks durch.
Item {
    id: root
    property real radius: Metrics.radiusFloat
    anchors.fill: parent
    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: "transparent"
        border.width: 1
        border.color: Theme.wellRim
    }
    Repeater {
        model: 6
        Rectangle {
            required property int index
            x: root.radius * 0.6
            y: 1 + index
            width: root.width - root.radius * 1.2
            height: 1
            color: Theme.wellInset
            opacity: Math.pow(1 - index / 6, 2) * 0.9
            visible: root.width > 2 * root.radius
        }
    }
}
