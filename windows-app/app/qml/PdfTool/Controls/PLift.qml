import QtQuick
import PdfTool.Style

// Tiefe im 3D-Design (seit 5.0 Beta 10, Entwürfe 7/8): Licht von oben, die Fläche schwebt. Gestaffelte, nach unten
// versetzte Ringe statt eines Weichzeichners (MultiEffect fehlt in der Laufzeit) – günstig und überall gleich.
// ``high``: stärker angehoben (aktiver Tab); ``glowColor``: farbiger Schein im Neon-Modus (aktiver Tab, gewählte Karte).
Item {
    id: root
    property real radius: Metrics.radiusFloat
    property bool high: false
    property real strength: 1.0
    property color glowColor: "transparent"
    readonly property int depth: high ? 14 : 10
    anchors.fill: parent
    z: -1

    // Tiefer, weicher Schatten: Ringe wachsen nach außen und wandern nach unten
    Repeater {
        model: root.depth
        Rectangle {
            required property int index
            readonly property real grow: index * (root.high ? 1.6 : 1.3)
            x: -grow
            y: -grow + 1 + index * (root.high ? 0.9 : 0.7)
            width: root.width + 2 * grow
            height: root.height + 2 * grow
            radius: root.radius + grow
            color: "transparent"
            border.width: root.high ? 1.6 : 1.3
            border.color: Theme.liftShadow
            opacity: root.strength * Theme.liftStrength * 0.085 * Math.pow(1 - index / root.depth, 1.6)
        }
    }
    // Neon: Schein in der Farbe (stärker mit der Leuchtstärke)
    Repeater {
        model: root.glowColor.a > 0 && Theme.glow > 0 ? 8 : 0
        Rectangle {
            required property int index
            x: -index * 1.5
            y: -index * 1.5
            width: root.width + index * 3
            height: root.height + index * 3
            radius: root.radius + index * 1.5
            color: "transparent"
            border.width: 1.5
            border.color: root.glowColor
            opacity: Math.min(1, 0.22 * Theme.glow) * (1 - index / 8)
        }
    }
}
