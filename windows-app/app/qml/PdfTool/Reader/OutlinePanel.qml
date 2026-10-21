import QtQuick
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Lesezeichen (Gliederung) des PDFs als aufklappbarer Baum. Klick auf den Titel springt zur Seite. Rechtsklick
// (oder Umschalt+F10) bearbeitet: Lesezeichen dahinter oder darunter anlegen, umbenennen (F2), auf die angezeigte
// Seite setzen, verschieben, ein- und ausrücken, löschen (Entf). Jede Änderung lässt sich rückgängig machen.
Item {
    id: root
    objectName: "readerOutline"
    property var doc: null

    PEmptyState {
        objectName: "readerOutlineEmpty"
        anchors.fill: parent
        visible: root.doc !== null && !root.doc.hasOutline
        iconName: "bookmark"
        title: I18n.tr("Keine Lesezeichen", I18n.revision)
        text: I18n.tr("Dieses PDF enthält kein Inhaltsverzeichnis. Seiten finden Sie über die Miniaturen oder die Suche.", I18n.revision)
        PButton {
            objectName: "readerOutlineAddFirst"
            // unter dem Hinweis (der leere Zustand steht im oberen Drittel)
            x: (parent.width - width) / 2
            y: Math.max(Metrics.s24, parent.height * parent.topShare) + 176
            iconName: "bookmark_add"
            text: I18n.tr("Lesezeichen für diese Seite", I18n.revision)
            onClicked: root.doc.addBookmark("", false)
        }
    }
    ListView {
        id: list
        PWheelScroll { flickable: list }  // Mausrad: gleiche Strecke je Raste, Rasten addieren sich
        anchors.fill: parent
        anchors.bottomMargin: addRow.visible ? addRow.height : 0
        model: root.doc ? root.doc.outline : null
        clip: true
        reuseItems: true
        topMargin: 4
        bottomMargin: 8
        boundsBehavior: Flickable.StopAtBounds
        activeFocusOnTab: true
        T.ScrollBar.vertical: PScrollBar {}
        Accessible.role: Accessible.Tree
        Accessible.name: I18n.tr("Lesezeichen", I18n.revision)

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
            Accessible.name: I18n.tr(title, I18n.revision)

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
                tip: I18n.tr(row.expanded ? "Zuklappen" : "Aufklappen", I18n.revision)
                onClicked: root.doc.toggleOutline(row.key)
            }
            PText {
                id: label
                x: chevron.x + 28
                width: parent.width - x - 44
                anchors.verticalCenter: parent.verticalCenter
                text: I18n.tr(row.title, I18n.revision)
                wrap: true
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            PText {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                text: I18n.tr(row.page >= 0 ? String(row.page + 1) : "", I18n.revision)
                textStyle: "caption"
                tone: "secondary"
            }
            TapHandler {
                onTapped: {
                    list.currentIndex = row.index
                    root.doc.openOutline(row.key)
                }
            }
            TapHandler {
                acceptedButtons: Qt.RightButton
                onTapped: (point) => {
                    list.currentIndex = row.index
                    entryMenu.entry = { key: row.key, title: row.title, level: row.level, hasChildren: row.hasChildren }
                    entryMenu.popup(row, point.position.x, point.position.y)
                }
            }
        }
        Keys.onReturnPressed: if (currentItem) root.doc.openOutline(currentItem.key)
        Keys.onRightPressed: if (currentItem && currentItem.hasChildren && !currentItem.expanded) root.doc.toggleOutline(currentItem.key)
        Keys.onLeftPressed: if (currentItem && currentItem.hasChildren && currentItem.expanded) root.doc.toggleOutline(currentItem.key)
        Keys.onPressed: (event) => {
            if (!currentItem) return
            if (event.key === Qt.Key_F2) { root.doc.renameBookmark(currentItem.key); event.accepted = true }
            else if (event.key === Qt.Key_Delete) { root.doc.deleteBookmark(currentItem.key); event.accepted = true }
            else if (event.key === Qt.Key_Menu || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))) {
                entryMenu.entry = { key: currentItem.key, title: currentItem.title, level: currentItem.level, hasChildren: currentItem.hasChildren }
                entryMenu.popup(currentItem, 24, currentItem.height)
                event.accepted = true
            }
        }
    }

    // Unten: Lesezeichen zur angezeigten Seite hinzufügen (der Kopf bleibt wie in allen Seitenleisten)
    Rectangle {
        id: addRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Metrics.controlHeight + Metrics.s16
        visible: root.doc !== null && root.doc.hasOutline
        color: Theme.layer
        Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; height: 1; color: Theme.divider }
        PButton {
            objectName: "readerOutlineAdd"
            anchors.left: parent.left
            anchors.leftMargin: Metrics.s8
            anchors.verticalCenter: parent.verticalCenter
            kind: "subtle"
            iconName: "bookmark_add"
            text: I18n.tr("Lesezeichen für Seite " + (root.doc ? root.doc.currentPage + 1 : 1), I18n.revision)
            tip: I18n.tr("Neues Lesezeichen zur angezeigten Seite – hinter dem gewählten Eintrag (sonst am Ende)", I18n.revision)
            onClicked: root.doc.addBookmark(list.currentItem ? list.currentItem.key : "", false)
        }
    }

    PMenu {
        id: entryMenu
        objectName: "readerOutlineMenu"
        property var entry: ({})
        PMenuItem { text: I18n.tr("Gehe zu", I18n.revision); iconName: "arrow_right"; onTriggered: root.doc.openOutline(entryMenu.entry.key) }
        PMenuItem { text: I18n.tr("Neues Lesezeichen dahinter …", I18n.revision); iconName: "bookmark_add"; onTriggered: { var d = root.doc, key = entryMenu.entry.key; entryMenu.afterClose = function() { d.addBookmark(key, false) } } }
        PMenuItem { text: I18n.tr("Neues Lesezeichen darunter …", I18n.revision); iconName: "add"; onTriggered: { var d = root.doc, key = entryMenu.entry.key; entryMenu.afterClose = function() { d.addBookmark(key, true) } } }
        PMenuItem { text: I18n.tr("Umbenennen … (F2)", I18n.revision); iconName: "edit"; onTriggered: { var d = root.doc, key = entryMenu.entry.key; entryMenu.afterClose = function() { d.renameBookmark(key) } } }
        PMenuItem { text: I18n.tr("Auf die angezeigte Seite setzen (" + (root.doc ? root.doc.currentPage + 1 : 1) + ")", I18n.revision); iconName: "bookmark"; onTriggered: root.doc.bookmarkCurrentPage(entryMenu.entry.key) }
        PMenuItem { text: I18n.tr("Nach oben", I18n.revision); iconName: "chevron_up"; onTriggered: root.doc.moveBookmark(entryMenu.entry.key, "up") }
        PMenuItem { text: I18n.tr("Nach unten", I18n.revision); iconName: "chevron_down"; onTriggered: root.doc.moveBookmark(entryMenu.entry.key, "down") }
        PMenuItem { text: I18n.tr("Einrücken (Unterpunkt des vorigen)", I18n.revision); iconName: "chevron_right"; onTriggered: root.doc.moveBookmark(entryMenu.entry.key, "in") }
        PMenuItem { text: I18n.tr("Ausrücken", I18n.revision); iconName: "chevron_left"; enabled: (entryMenu.entry.level || 0) > 0; onTriggered: root.doc.moveBookmark(entryMenu.entry.key, "out") }
        PMenuItem { text: I18n.tr("Löschen (Entf)", I18n.revision); iconName: "delete"; onTriggered: { var d = root.doc, key = entryMenu.entry.key; entryMenu.afterClose = function() { d.deleteBookmark(key) } } }
    }
}
