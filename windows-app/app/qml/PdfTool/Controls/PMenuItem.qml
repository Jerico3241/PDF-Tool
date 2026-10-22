import QtQuick
import QtQuick.Templates as T
import PdfTool.Style
import PdfTool.Backend

T.MenuItem {
    id: control
    property string iconName: ""
    property url imageSource: ""  // farbiges Symbol (Dateiart) statt eines Fluent-Symbols
    property string hint: ""  // rechts, grau: Tastenkürzel (»F1«)
    implicitWidth: Math.max(160, contentItem.implicitWidth + leftPadding + rightPadding)
    implicitHeight: 34
    height: visible ? implicitHeight : 0  // ausgeblendete Einträge nehmen im Menü keinen Platz ein
    leftPadding: 12
    rightPadding: 16
    hoverEnabled: true
    font: Typography.body
    Accessible.role: Accessible.MenuItem
    Accessible.name: I18n.tr(text, I18n.revision)

    contentItem: Item {
        implicitWidth: entry.implicitWidth + (hintText.visible ? hintText.implicitWidth + 32 : 0)
        implicitHeight: entry.implicitHeight
        Row {
            id: entry
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12
            PIcon {
                anchors.verticalCenter: parent.verticalCenter
                name: control.iconName
                color: control.enabled ? Theme.textPrimary : Theme.disabled
                visible: control.imageSource == ""
            }
            Image {
                anchors.verticalCenter: parent.verticalCenter
                width: Metrics.iconSize
                height: Metrics.iconSize
                source: control.imageSource
                sourceSize: Qt.size(Metrics.iconSize, Metrics.iconSize)
                visible: control.imageSource != ""
                Accessible.ignored: true
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: I18n.tr(control.text, I18n.revision)
                font: control.font
                color: control.enabled ? Theme.textPrimary : Theme.disabled
                textFormat: Text.PlainText
            }
        }
        Text {
            id: hintText
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            visible: control.hint !== ""
            text: I18n.tr(control.hint, I18n.revision)
            font: Typography.caption
            color: Theme.textSecondary
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
