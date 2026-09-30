import QtQuick
import QtQuick.Layouts
import PdfTool.Style

// Einstellungskarte (wie Windows 11): Symbol, Titel und Beschreibung links, Steuerelement rechts.
// Mit ``expandable`` klappt darunter ein weiterer Bereich weich auf.
Rectangle {
    id: card
    property string title: ""
    property string description: ""
    property string iconName: ""
    property bool expandable: false
    property bool expanded: false
    default property alias control: controlSlot.data
    property alias extra: extraSlot.data

    implicitWidth: 400
    implicitHeight: column.implicitHeight
    radius: Metrics.radiusCard
    color: headerArea.containsMouse && expandable ? Theme.c.hover_card || Theme.surface : Theme.surface
    border.width: 1
    border.color: Theme.border
    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 0

        Item {
            Layout.fillWidth: true
            implicitHeight: Math.max(68, header.implicitHeight + 28)
            MouseArea {
                id: headerArea
                anchors.fill: parent
                hoverEnabled: card.expandable
                enabled: card.expandable
                cursorShape: card.expandable ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: card.expanded = !card.expanded
            }
            RowLayout {
                id: header
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 16
                PIcon {
                    name: card.iconName
                    size: Metrics.iconSizeMedium
                    visible: card.iconName !== ""
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    PText {
                        text: card.title
                        Layout.fillWidth: true
                    }
                    PText {
                        text: card.description
                        textStyle: "caption"
                        tone: "secondary"
                        wrap: true
                        visible: text !== ""
                        Layout.fillWidth: true
                    }
                }
                Row {
                    id: controlSlot
                    spacing: 8
                    Layout.alignment: Qt.AlignVCenter
                }
                PIconButton {
                    visible: card.expandable
                    iconName: "chevron_down"
                    tip: card.expanded ? "Zuklappen" : "Aufklappen"
                    rotation: card.expanded ? 180 : 0
                    Behavior on rotation { enabled: Motion.moves; NumberAnimation { duration: Motion.expand; easing.type: Motion.decelerate } }
                    onClicked: card.expanded = !card.expanded
                    Accessible.name: card.title + (card.expanded ? " zuklappen" : " aufklappen")
                }
            }
        }

        PCollapse {
            Layout.fillWidth: true
            expanded: card.expandable && card.expanded
            Rectangle {
                width: parent.width
                height: 1
                color: Theme.divider
            }
            Column {
                id: extraSlot
                y: 1
                width: parent.width
                padding: 16
                leftPadding: 52
                spacing: 8
            }
        }
    }
}
