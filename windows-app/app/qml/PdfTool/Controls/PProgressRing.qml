import QtQuick
import PdfTool.Style

// Unbestimmter Fortschritt als drehender Bogen. Die Drehung läuft im Render-Thread und nur,
// solange der Ring sichtbar ist (keine Dauer-Animation auf verborgenen Seiten).
// Neu zeichnen über eigene Signal-Handler statt »Connections«: Der Ring steckt in jeder
// Schaltfläche und entsteht beim Laden der Seiten im Hintergrund – dort kann ein
// »Connections« mit Funktionen in Qt 6.11 beim Fertigstellen abstürzen.
Item {
    id: root
    property int size: 16
    property color color: Theme.accent
    property bool running: true
    readonly property bool active: running && visible && root.Window.visibility !== Window.Minimized && root.Window.visibility !== Window.Hidden

    width: size
    height: size
    Accessible.role: Accessible.Animation
    Accessible.name: "Wird bearbeitet"
    onColorChanged: arc.requestPaint()
    onSizeChanged: arc.requestPaint()

    Canvas {
        id: arc
        anchors.fill: parent
        antialiasing: true
        renderTarget: Canvas.Image
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var line = Math.max(1.5, root.size / 9)
            ctx.lineWidth = line
            ctx.lineCap = "round"
            ctx.strokeStyle = root.color
            ctx.beginPath()
            ctx.arc(width / 2, height / 2, (Math.min(width, height) - line) / 2, -Math.PI / 2, Math.PI * 0.9)
            ctx.stroke()
        }
        RotationAnimator on rotation {
            from: 0
            to: 360
            duration: 1000
            loops: Animation.Infinite
            running: root.active
        }
    }
}
