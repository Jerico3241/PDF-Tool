import QtQuick
import QtQuick.Layouts
import PdfTool.Style

// Dateizeile: Symbol, Beschriftung, Dateiname (voller Pfad im Tooltip) und Schaltflächen rechts.
Item {
    id: root
    property string iconName: "document"
    property string label: ""
    property string value: ""
    property string fullPath: ""
    property string valueTone: ""
    default property alias buttons: buttonRow.data

    implicitHeight: Math.max(44, layout.implicitHeight)
    implicitWidth: 320
    Accessible.role: Accessible.StaticText
    Accessible.name: label + ": " + value

    RowLayout {
        id: layout
        anchors.fill: parent
        spacing: 12
        Rectangle {
            implicitWidth: 36
            implicitHeight: 36
            radius: Metrics.radiusControl
            color: Theme.surfaceSecondary
            border.width: 1
            border.color: Theme.border
            PIcon {
                anchors.centerIn: parent
                name: root.iconName
                size: Metrics.iconSizeMedium
                color: Theme.textSecondary
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            PText {
                text: root.label
                textStyle: "caption"
                tone: "secondary"
                Layout.fillWidth: true
            }
            PText {
                id: valueText
                text: root.value
                tone: root.valueTone
                elide: Text.ElideMiddle
                Layout.fillWidth: true
                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                }
                PToolTip {
                    text: root.fullPath
                    visible: root.fullPath !== "" && hover.containsMouse && (valueText.truncated || root.fullPath !== root.value)
                }
            }
        }
        Row {
            id: buttonRow
            spacing: 4
            layoutDirection: Qt.RightToLeft
            Layout.alignment: Qt.AlignVCenter
        }
    }
}
