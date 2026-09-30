import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Farbfeld (Akzentfarben, Schriftfarben) mit Auswahlrahmen und Tooltip.
T.AbstractButton {
    id: control
    property color swatchColor: "#000000"
    property bool selected: false
    property string iconName: ""
    property string tip: ""
    property int size: 32
    implicitWidth: size
    implicitHeight: size
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.RadioButton
    Accessible.name: tip
    Accessible.checked: selected

    background: Item {
        Rectangle {
            anchors.fill: parent
            radius: Metrics.radiusControl + 2
            color: "transparent"
            border.width: 2
            border.color: control.selected ? Theme.textPrimary : (control.hovered ? Theme.strongStroke : "transparent")
            Behavior on border.color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: 4
            radius: Metrics.radiusControl
            color: control.swatchColor
            border.width: 1
            border.color: Qt.rgba(0, 0, 0, 0.12)
            scale: control.pressed && Motion.moves ? 0.92 : 1
            Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.fast } }
            PIcon {
                anchors.centerIn: parent
                name: control.iconName
                size: 14
                color: "#FFFFFF"
            }
        }
        PFocusRing { visible: control.visualFocus; inset: -2 }
    }
    PToolTip {
        text: control.tip
        visible: control.tip !== "" && control.hovered
    }
}
