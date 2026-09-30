import QtQuick
import QtQuick.Layouts
import PdfTool.Style

// Zustandszeile (z. B. »Bereit zum Erstellen«): Symbol bzw. Fortschrittsring und Text, weich
// überblendet. Mit ``clickable`` führt ein Klick zum ersten offenen Punkt.
Item {
    id: root
    // success, busy, caution/warning, critical/error, info, neutral
    property string kind: "neutral"
    property string text: ""
    property bool clickable: false
    signal activated()

    implicitHeight: 36
    implicitWidth: row.implicitWidth + 24
    Accessible.role: clickable ? Accessible.Button : Accessible.StaticText
    Accessible.name: text

    Rectangle {
        anchors.fill: parent
        radius: Metrics.radiusControl
        color: root.kind === "busy" || root.kind === "neutral" ? Theme.surfaceSecondary : Theme.toneBackground(root.kind)
        border.width: 1
        border.color: Theme.border
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.status } }
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: area.pressed ? Theme.subtlePressed : (area.containsMouse ? Theme.subtleHover : "transparent")
            visible: root.clickable
        }
        PFocusRing { visible: root.activeFocus && root.clickable }
    }
    RowLayout {
        id: row
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 10
        Item {
            implicitWidth: 16
            implicitHeight: 16
            PIcon {
                anchors.centerIn: parent
                name: Theme.toneIcon(root.kind)
                color: Theme.toneIconColor(root.kind)
                opacity: root.kind === "busy" ? 0 : 1
                Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.status } }
            }
            PProgressRing {
                anchors.centerIn: parent
                size: 16
                opacity: root.kind === "busy" ? 1 : 0
                visible: opacity > 0
                running: root.kind === "busy"
                Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.status } }
            }
        }
        PCrossfadeText {
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: root.text
            font: Typography.body
            color: Theme.textPrimary
        }
        PIcon {
            visible: root.clickable && root.kind !== "success" && root.kind !== "busy"
            name: "chevron_right"
            size: 12
            color: Theme.textSecondary
        }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        enabled: root.clickable
        hoverEnabled: root.clickable
        cursorShape: root.clickable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.activated()
    }
    activeFocusOnTab: clickable
    Keys.onReturnPressed: if (clickable) activated()
    Keys.onSpacePressed: if (clickable) activated()
}
