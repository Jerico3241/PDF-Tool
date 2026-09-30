import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Optionsfeld: der innere Punkt wächst bzw. schrumpft beim Wechsel.
T.RadioButton {
    id: control
    implicitWidth: Math.ceil(indicator.width + (text !== "" ? 8 + label.implicitWidth : 0))
    implicitHeight: Metrics.controlHeight
    padding: 0
    spacing: 8
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    font: Typography.body
    Accessible.role: Accessible.RadioButton
    Accessible.name: text
    Accessible.checked: checked

    indicator: Rectangle {
        x: 0
        y: (control.height - height) / 2
        implicitWidth: 20
        implicitHeight: 20
        radius: 10
        color: {
            if (!control.enabled) return control.checked ? Theme.accentDisabled : Theme.controlDisabled
            if (control.checked) return control.pressed ? Theme.accentPressed : (control.hovered ? Theme.accentHover : Theme.accent)
            return control.pressed ? Theme.subtlePressed : (control.hovered ? Theme.subtleHover : Theme.control)
        }
        border.width: control.checked ? 0 : 1
        border.color: control.enabled ? Theme.strongStroke : Theme.disabled
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        Rectangle {
            anchors.centerIn: parent
            readonly property real size: control.checked ? (control.pressed ? 10 : (control.hovered ? 14 : 12)) : (control.pressed ? 10 : 0)
            width: size
            height: size
            radius: size / 2
            color: control.checked ? Theme.textOnAccent : Theme.strong
            Behavior on width { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }
            Behavior on height { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }
        }
        PFocusRing { visible: control.visualFocus; radius_: 10 }
    }

    contentItem: Text {
        id: label
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        font: control.font
        color: control.enabled ? Theme.textPrimary : Theme.disabled
        verticalAlignment: Text.AlignVCenter
        textFormat: Text.PlainText
    }
}
