import QtQuick
import QtQuick.Templates as T
import PdfTool.Style
import PdfTool.Backend

// Sieht aus wie ein Auswahlfeld, öffnet aber einen Suchdialog (viele Einträge, z. B. Kundenakten).
T.AbstractButton {
    id: control
    property string placeholder: ""
    property string tip: ""
    property string iconName: "search"
    implicitWidth: 240
    implicitHeight: Metrics.controlHeight
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.ComboBox
    Accessible.name: I18n.tr(tip !== "" ? tip : placeholder, I18n.revision)

    background: Rectangle {
        radius: Metrics.radiusControl
        color: !control.enabled ? Theme.controlDisabled : (control.pressed ? Theme.controlPressed : (control.hovered ? Theme.controlHover : Theme.control))
        border.width: 1
        border.color: Theme.controlStroke
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: Metrics.radiusControl
            anchors.rightMargin: Metrics.radiusControl
            height: 1
            color: Theme.controlEdge
            opacity: 0.8
        }
        PFocusRing { visible: control.visualFocus }
    }
    contentItem: Item {
        Text {
            x: 11
            width: parent.width - 11 - 34
            anchors.verticalCenter: parent.verticalCenter
            text: I18n.tr(control.text !== "" ? control.text : control.placeholder, I18n.revision)
            font: Typography.body
            color: !control.enabled ? Theme.disabled : (control.text !== "" ? Theme.textPrimary : Theme.textSecondary)
            elide: Text.ElideRight
            textFormat: Text.PlainText
        }
        PIcon {
            x: parent.width - width - 12
            anchors.verticalCenter: parent.verticalCenter
            name: control.iconName
            size: 14
            color: Theme.textSecondary
        }
    }
    PToolTip { text: I18n.tr(control.tip, I18n.revision); visible: control.tip !== "" && control.hovered }
}
