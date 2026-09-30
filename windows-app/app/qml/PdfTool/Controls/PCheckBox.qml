import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Kontrollkästchen: Häkchen blendet weich ein; Text daneben (mehrzeilig möglich).
T.CheckBox {
    id: control
    property bool wrap: true
    implicitWidth: Math.ceil(indicator.width + (text !== "" ? 8 + label.implicitWidth : 0))
    implicitHeight: Math.max(Metrics.controlHeight, label.implicitHeight + 8)
    padding: 0
    spacing: 8
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    font: Typography.body
    Accessible.role: Accessible.CheckBox
    Accessible.name: text
    Accessible.checked: checked

    indicator: Rectangle {
        x: 0
        y: control.topPadding + (control.availableHeight - height) / 2
        implicitWidth: 20
        implicitHeight: 20
        radius: Metrics.radiusControl
        readonly property bool on: control.checkState !== Qt.Unchecked
        color: {
            if (!control.enabled) return on ? Theme.accentDisabled : Theme.controlDisabled
            if (on) return control.pressed ? Theme.accentPressed : (control.hovered ? Theme.accentHover : Theme.accent)
            return control.pressed ? Theme.subtlePressed : (control.hovered ? Theme.subtleHover : Theme.control)
        }
        border.width: on ? 0 : 1
        border.color: control.enabled ? Theme.strongStroke : Theme.disabled
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        PIcon {
            anchors.centerIn: parent
            name: control.checkState === Qt.PartiallyChecked ? "subtract" : "checkmark"
            size: 14
            color: control.enabled ? Theme.textOnAccent : Theme.textOnAccentDisabled
            opacity: parent.on ? 1 : 0
            scale: parent.on || !Motion.moves ? 1 : 0.6
            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
            Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Easing.OutBack } }
        }
        PFocusRing { visible: control.visualFocus }
    }

    contentItem: Text {
        id: label
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        font: control.font
        color: control.enabled ? Theme.textPrimary : Theme.disabled
        wrapMode: control.wrap ? Text.Wrap : Text.NoWrap
        verticalAlignment: Text.AlignVCenter
        textFormat: Text.PlainText
    }
}
