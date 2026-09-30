import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Statuszeile: aktueller Zustand (weich überblendet) links, Tastenhinweise rechts.
Item {
    id: bar
    implicitHeight: Metrics.statusBarHeight
    Accessible.role: Accessible.StatusBar
    Accessible.name: App.statusText

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 1
        color: Theme.divider
    }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        spacing: 8
        Item {
            implicitWidth: 16
            implicitHeight: 16
            PProgressRing {
                anchors.centerIn: parent
                size: 14
                visible: App.statusKind === "busy"
                running: visible
            }
            PIcon {
                anchors.centerIn: parent
                size: 14
                visible: App.statusKind !== "busy" && App.statusKind !== "neutral"
                name: Theme.toneIcon(App.statusKind)
                color: Theme.toneIconColor(App.statusKind)
            }
        }
        PCrossfadeText {
            id: status
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: App.statusText
            font: Typography.caption
            color: Theme.textSecondary
            // Gekürzte Meldung: vollständig als Tooltip (wie bis 2.6.1)
            MouseArea {
                id: statusHover
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }
            PToolTip {
                text: App.statusText
                visible: statusHover.containsMouse && status.truncated
            }
        }
        Text {
            Layout.maximumWidth: bar.width * 0.55
            text: App.hint
            font: Typography.caption
            color: Theme.textTertiary
            elide: Text.ElideLeft
            textFormat: Text.PlainText
            visible: bar.width > 640
        }
    }
}
