import QtQuick
import QtQuick.Shapes
import PdfTool.Style

// Ablagefläche für Drag & Drop: gestrichelter Rahmen; beim Darüberziehen wechseln Rahmen,
// Fläche und Symbol weich in die Akzentfarbe, das Symbol hebt sich leicht an.
Item {
    id: root
    property bool highlighted: false
    property string iconName: "document"
    property string title: ""
    property string text: ""
    property alias actions: actionRow.data
    implicitHeight: column.implicitHeight + 48
    implicitWidth: 320
    Accessible.role: Accessible.Grouping
    Accessible.name: title

    Rectangle {
        anchors.fill: parent
        radius: Metrics.radiusCard
        color: root.highlighted ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, Theme.dark ? 0.14 : 0.07) : Theme.surface
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.normal } }
    }
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: root.highlighted ? 2 : 1
            strokeColor: root.highlighted ? Theme.accent : Theme.strongStroke
            strokeStyle: ShapePath.DashLine
            dashPattern: [4, 3]
            fillColor: "transparent"
            startX: Metrics.radiusCard; startY: 0.5
            PathLine { x: root.width - Metrics.radiusCard; y: 0.5 }
            PathArc { x: root.width - 0.5; y: Metrics.radiusCard; radiusX: Metrics.radiusCard - 0.5; radiusY: Metrics.radiusCard - 0.5 }
            PathLine { x: root.width - 0.5; y: root.height - Metrics.radiusCard }
            PathArc { x: root.width - Metrics.radiusCard; y: root.height - 0.5; radiusX: Metrics.radiusCard - 0.5; radiusY: Metrics.radiusCard - 0.5 }
            PathLine { x: Metrics.radiusCard; y: root.height - 0.5 }
            PathArc { x: 0.5; y: root.height - Metrics.radiusCard; radiusX: Metrics.radiusCard - 0.5; radiusY: Metrics.radiusCard - 0.5 }
            PathLine { x: 0.5; y: Metrics.radiusCard }
            PathArc { x: Metrics.radiusCard; y: 0.5; radiusX: Metrics.radiusCard - 0.5; radiusY: Metrics.radiusCard - 0.5 }
        }
    }
    Column {
        id: column
        anchors.centerIn: parent
        width: Math.min(parent.width - 32, 520)
        spacing: 8
        PIcon {
            anchors.horizontalCenter: parent.horizontalCenter
            name: root.iconName
            size: Metrics.iconSizeHero
            color: root.highlighted ? Theme.accent : Theme.textSecondary
            scale: root.highlighted && Motion.moves ? 1.1 : 1.0
            Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Easing.OutBack } }
        }
        PText {
            width: parent.width
            text: root.title
            textStyle: "bodyStrong"
            horizontalAlignment: Text.AlignHCenter
            wrap: true
            visible: text !== ""
        }
        PText {
            width: parent.width
            text: root.text
            tone: "secondary"
            horizontalAlignment: Text.AlignHCenter
            wrap: true
            visible: text !== ""
        }
        Row {
            id: actionRow
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8
            topPadding: 6
        }
    }
}
