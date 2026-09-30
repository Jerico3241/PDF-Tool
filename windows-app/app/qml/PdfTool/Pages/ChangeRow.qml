import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

// Zeile eines geänderten, neuen, entfernten oder unveränderten Vertrags. Geänderte Verträge
// klappen weich auf und zeigen die geänderten Felder (»Netto: 250,00 € → 270,00 €«).
Item {
    id: row
    required property int index
    required property string key
    required property string kind
    required property string kindLabel
    required property string tone
    required property string title
    required property string summary
    required property var details
    required property bool expandable
    required property bool expanded
    property Item listPage: null    // PListPage (Seitenspalte) – ohne: volle Breite
    property QtObject view: null
    property bool animateHeight: false

    readonly property real columnX: listPage ? listPage.columnX : 0
    readonly property real columnWidth: listPage ? listPage.columnWidth : width
    width: listPage ? listPage.width : (parent ? parent.width : 400)
    height: 44 + (expanded ? detailsColumn.implicitHeight + 10 : 0)
    clip: true
    Behavior on height {
        enabled: row.animateHeight && Motion.expand > 0
        NumberAnimation { duration: Motion.expand; easing.type: Motion.decelerate; onRunningChanged: if (!running) row.animateHeight = false }
    }
    ListView.onReused: animateHeight = false
    Accessible.role: Accessible.ListItem
    Accessible.name: kindLabel + ": " + title + (summary !== "" ? ", " + summary : "")

    function toggle() {
        if (!expandable || !view) return
        animateHeight = true
        view.toggle(key)
    }

    PListItem {
        x: row.columnX + 6
        y: 2
        width: row.columnWidth - 12
        height: row.height - 4
        hovered: mouse.containsMouse && row.expandable
        pressed: mouse.pressed && row.expandable
        focused: row.ListView.view !== null && row.ListView.view.activeFocus && row.ListView.isCurrentItem
    }
    Rectangle {
        visible: row.index > 0
        x: row.columnX + 14
        width: row.columnWidth - 28
        height: 1
        color: Theme.divider
    }
    RowLayout {
        x: row.columnX + 16
        width: row.columnWidth - 32
        height: 44
        spacing: 12
        PBadge {
            text: row.kindLabel
            tone: row.tone
            Layout.preferredWidth: 96
            scale: 1
        }
        PText { text: row.title; elide: Text.ElideRight; Layout.fillWidth: true }
        PText { text: row.summary; tone: "secondary"; elide: Text.ElideRight; Layout.maximumWidth: row.columnWidth * 0.45 }
        PIcon {
            visible: row.expandable
            name: "chevron_down"
            size: 12
            color: Theme.textSecondary
            rotation: row.expanded ? 180 : 0
            Behavior on rotation { enabled: Motion.moves; NumberAnimation { duration: Motion.expand; easing.type: Motion.decelerate } }
        }
    }
    ColumnLayout {
        id: detailsColumn
        x: row.columnX + 16 + 96 + 12
        y: 42
        width: row.columnWidth - 32 - 96 - 12
        spacing: 2
        opacity: row.expanded ? 1 : 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade } }
        Repeater {
            model: row.expanded ? row.details : []
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 12
                PText { text: modelData.field; textStyle: "caption"; tone: "secondary"; Layout.preferredWidth: 120 }
                PText { text: modelData.change; textStyle: "caption"; wrap: true; Layout.fillWidth: true }
            }
        }
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: row.expandable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: {
            if (row.ListView.view) row.ListView.view.currentIndex = row.index
            row.toggle()
        }
    }
}
