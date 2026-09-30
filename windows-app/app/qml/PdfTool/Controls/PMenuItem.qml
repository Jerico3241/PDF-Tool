import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

T.MenuItem {
    id: control
    property string iconName: ""
    implicitWidth: Math.max(160, contentItem.implicitWidth + leftPadding + rightPadding)
    implicitHeight: 34
    leftPadding: 12
    rightPadding: 16
    hoverEnabled: true
    font: Typography.body
    Accessible.role: Accessible.MenuItem
    Accessible.name: text

    contentItem: Row {
        spacing: 12
        PIcon {
            anchors.verticalCenter: parent.verticalCenter
            name: control.iconName
            color: control.enabled ? Theme.textPrimary : Theme.disabled
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: control.text
            font: control.font
            color: control.enabled ? Theme.textPrimary : Theme.disabled
            textFormat: Text.PlainText
        }
    }
    background: Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        radius: Metrics.radiusControl
        color: control.down ? Theme.subtlePressed : (control.highlighted || control.hovered ? Theme.subtleHover : "transparent")
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
    }
}
