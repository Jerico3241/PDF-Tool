import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Umschaltfläche der Formatleiste (Fett, Kursiv, Ausrichtung …): zeigt ihren Zustand an.
T.AbstractButton {
    id: control
    property bool active: false
    property string iconName: ""
    property string glyph: ""
    property font glyphFont: Typography.bodyStrong
    property string tip: ""
    implicitWidth: 32
    implicitHeight: 32
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    Accessible.role: Accessible.CheckBox
    Accessible.name: tip
    Accessible.checked: active

    background: Rectangle {
        radius: Metrics.radiusControl
        color: control.pressed ? Theme.subtlePressed : (control.active ? Theme.subtleHover : (control.hovered ? Theme.subtleHover : "transparent"))
        border.width: control.active ? 1 : 0
        border.color: Theme.controlStroke
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        PFocusRing { visible: control.visualFocus }
    }
    contentItem: Item {
        PIcon {
            anchors.centerIn: parent
            name: control.iconName
            color: control.active ? Theme.accentText : Theme.textPrimary
        }
        Text {
            anchors.centerIn: parent
            visible: control.iconName === ""
            text: control.glyph
            font: control.glyphFont
            color: control.active ? Theme.accentText : Theme.textPrimary
        }
    }
    PToolTip { text: control.tip; visible: control.tip !== "" && control.hovered }
}
