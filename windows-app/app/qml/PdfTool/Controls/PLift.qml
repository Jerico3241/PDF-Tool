import QtQuick
import PdfTool.Style

// Tiefe im 3D-Design (seit 5.0 Beta 10, Entwürfe 7/8): Licht von oben, die Fläche schwebt. Ein weichgezeichnetes
// Schattenbild statt MultiEffect (fehlt in der Laufzeit) – günstig und überall gleich.
// ``high``: stärker angehoben (aktiver Tab); ``glowColor``: farbiger Schein im Neon-Modus (aktiver Tab, gewählte Karte).
Item {
    id: root
    property real radius: Metrics.radiusFloat
    property bool high: false
    property real strength: 1.0
    property color glowColor: "transparent"
    anchors.fill: parent
    z: -1

    // Weicher Schatten aus einem vorberechneten, weichgezeichneten Bild (neun Felder: Ecken bleiben, Mitte dehnt sich) –
    // wie ein echter Weichzeichner, ohne sichtbare Ringe; nach unten versetzt (Licht von oben)
    BorderImage {
        objectName: "liftShadow"
        source: "../../images/lift-shadow.png"
        x: -32
        y: -32 + (root.high ? 6 : 4)
        width: root.width + 64
        height: root.height + 64
        border { left: 48; right: 48; top: 48; bottom: 48 }
        opacity: Math.min(1, root.strength * Theme.liftStrength * (root.high ? 0.30 : 0.20))
    }
    // Kontaktschatten: dicht an der Kante, damit die Fläche nicht »schwimmt«
    BorderImage {
        source: "../../images/lift-shadow.png"
        x: -30
        y: -30 + 1
        width: root.width + 60
        height: root.height + 60
        border { left: 48; right: 48; top: 48; bottom: 48 }
        opacity: Math.min(1, root.strength * Theme.liftStrength * 0.10)
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
