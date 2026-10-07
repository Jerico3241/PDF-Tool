import QtQuick
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Lesezeichen (Gliederung) des PDFs als aufklappbarer Baum. Klick auf den Titel springt zur Seite.
Item {
    id: root
    objectName: "readerOutline"
    property var doc: null

    PEmptyState {
        objectName: "readerOutlineEmpty"
        anchors.fill: parent
        visible: root.doc !== null && !root.doc.hasOutline
        iconName: "bookmark"
        title: "Keine Lesezeichen"
        text: "Dieses PDF enthält kein Inhaltsverzeichnis. Seiten finden Sie über die Miniaturen oder die Suche."
    }
    ListView {
        id: list
        PWheelScroll { flickable: list }  // Mausrad: gleiche Strecke je Raste, Rasten addieren sich
        anchors.fill: parent
        model: root.doc ? root.doc.outline : null
        clip: true
        reuseItems: true
        topMargin: 4
        bottomMargin: 8
        boundsBehavior: Flickable.StopAtBounds
        activeFocusOnTab: true
        T.ScrollBar.vertical: PScrollBar {}
        Accessible.role: Accessible.Tree
        Accessible.name: "Lesezeichen"

        delegate: Item {
            id: row
            required property string key
            required property int level
            required property string title
            required property int page
            required property bool hasChildren
            required property bool expanded
            required property int index
            width: list.width
            height: Math.max(32, label.implicitHeight + 12)
            Accessible.role: Accessible.TreeItem
            Accessible.name: title

            PListItem {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4
                hovered: hover.hovered
                focused: list.activeFocus && list.currentIndex === row.index
            }
            HoverHandler { id: hover }
            PIconButton {
                id: chevron
                x: 4 + row.level * 14
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: 24
                implicitHeight: 24
                visible: row.hasChildren
                iconName: row.expanded ? "chevron_down" : "chevron_right"
                tip: row.expanded ? "Zuklappen" : "Aufklappen"
                onClicked: root.doc.toggleOutline(row.key)
            }
            PText {
                id: label
                x: chevron.x + 28
                width: parent.width - x - 44
                anchors.verticalCenter: parent.verticalCenter
                text: row.title
                wrap: true
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            PText {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                text: row.page >= 0 ? String(row.page + 1) : ""
                textStyle: "caption"
                tone: "secondary"
            }
            TapHandler {
                onTapped: {
                    list.currentIndex = row.index
                    root.doc.openOutline(row.key)
                }
            }
        }
        Keys.onReturnPressed: if (currentItem) root.doc.openOutline(currentItem.key)
        Keys.onRightPressed: if (currentItem && currentItem.hasChildren && !currentItem.expanded) root.doc.toggleOutline(currentItem.key)
        Keys.onLeftPressed: if (currentItem && currentItem.hasChildren && currentItem.expanded) root.doc.toggleOutline(currentItem.key)
    }
}
