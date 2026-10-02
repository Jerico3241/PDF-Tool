import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import QtQuick.Window
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Seiten organisieren«: alle Seiten als Raster (virtualisiert). Auswahl mit Klick, Strg+Klick und
// Umschalt+Klick (Strg+A: alle); ausgewählte Seiten per Ziehen an eine neue Stelle verschieben.
// Befehle: drehen, löschen, duplizieren, leere Seite, Seiten aus einer PDF einfügen, als neue PDF
// speichern (extrahieren), teilen, als Bilder exportieren. Alles lässt sich rückgängig machen.
FocusScope {
    id: root
    objectName: "readerOrganizeView"
    property var doc: null
    property var selection: ({})
    property int anchorIndex: -1
    readonly property var selectedPages: {
        var list = []
        for (var key in selection) list.push(Number(key))
        return list.sort(function(a, b) { return a - b })
    }
    readonly property bool hasSelection: selectedPages.length > 0
    readonly property real ratio: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1
    readonly property int thumbBox: 150

    function select(index, modifiers) {
        var next = {}
        if (modifiers & Qt.ShiftModifier && anchorIndex >= 0) {
            if (modifiers & Qt.ControlModifier) next = Object.assign({}, selection)
            var a = Math.min(anchorIndex, index), b = Math.max(anchorIndex, index)
            for (var i = a; i <= b; ++i) next[i] = true
        } else if (modifiers & Qt.ControlModifier) {
            next = Object.assign({}, selection)
            if (next[index]) delete next[index]
            else next[index] = true
            anchorIndex = index
        } else {
            next[index] = true
            anchorIndex = index
        }
        selection = next
    }
    function selectAll() {
        var next = {}
        for (var i = 0; doc && i < doc.pageCount; ++i) next[i] = true
        selection = next
    }
    function chosen() { return hasSelection ? selectedPages : (doc ? [doc.currentPage] : []) }
    readonly property int pages: doc ? doc.pageCount : 0
    onPagesChanged: { selection = ({}); anchorIndex = -1 }
    onDocChanged: { selection = ({}); anchorIndex = -1 }

    Rectangle { anchors.fill: parent; color: Theme.viewer }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Metrics.controlHeight + 16
            color: Theme.layer
            Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.divider }
            Flow {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 4
                PIconButton { iconName: "arrow_rotate_counterclockwise"; tip: "Nach links drehen"; onClicked: root.doc.rotatePages(root.chosen(), -90) }
                PIconButton { objectName: "readerOrganizeRotate"; iconName: "arrow_rotate_clockwise"; tip: "Nach rechts drehen"; onClicked: root.doc.rotatePages(root.chosen(), 90) }
                PIconButton { objectName: "readerOrganizeDelete"; iconName: "delete"; tip: "Löschen (Entf)"; onClicked: root.doc.deletePages(root.chosen()) }
                PIconButton { iconName: "document_copy"; tip: "Duplizieren"; onClicked: root.doc.duplicatePages(root.chosen()) }
                PIconButton { iconName: "document_add"; tip: "Leere Seite danach einfügen"; onClicked: root.doc.insertBlankPage(root.chosen()[root.chosen().length - 1] + 1) }
                PIconButton { iconName: "document_arrow_up"; tip: "Seiten aus PDF danach einfügen …"; onClicked: root.doc.insertFromFile(root.chosen()[root.chosen().length - 1] + 1) }
                PButton { iconName: "arrow_export"; text: "Als neue PDF"; tip: "Gewählte Seiten als neue PDF speichern (extrahieren)"; onClicked: root.doc.extractPages(root.chosen()) }
                PButton { iconName: "document_landscape_split"; text: "Teilen …"; onClicked: root.doc.splitDocument("") }
                PButton { iconName: "image"; text: "Als Bilder"; tip: "Gewählte Seiten als PNG (150 dpi) speichern"; onClicked: root.doc.exportImages(root.chosen(), "png", 150) }
                PText {
                    height: Metrics.controlHeight
                    leftPadding: 8
                    text: root.hasSelection ? root.selectedPages.length + " von " + root.doc.pageCount + " Seiten gewählt" : (root.doc ? root.doc.pageCount + " Seiten – klicken zum Auswählen, ziehen zum Verschieben" : "")
                    tone: "secondary"
                    textStyle: "caption"
                }
            }
        }
        GridView {
            id: grid
            objectName: "readerOrganizeGrid"
            Layout.fillWidth: true
            Layout.fillHeight: true
            focus: true
            clip: true
            model: root.doc ? root.doc.pageCount : 0
            cellWidth: Math.max(root.thumbBox + 24, Math.floor((width - 16) / Math.max(1, Math.floor((width - 16) / (root.thumbBox + 24)))))
            cellHeight: root.thumbBox * 1.42 + 40
            leftMargin: 8
            rightMargin: 8
            topMargin: 12
            bottomMargin: 12
            reuseItems: true
            cacheBuffer: 600
            acceptedButtons: Qt.NoButton
            boundsBehavior: Flickable.StopAtBounds
            T.ScrollBar.vertical: PScrollBar {}
            Accessible.role: Accessible.List
            Accessible.name: "Seiten"

            delegate: Item {
                id: cell
                required property int index
                readonly property var size: root.doc && index < root.doc.pageSizes.length ? root.doc.pageSizes[index] : [595, 842]
                readonly property real fit: Math.min(root.thumbBox / size[0], root.thumbBox * 1.42 / size[1])
                readonly property bool chosen: root.selection[index] === true
                width: grid.cellWidth
                height: grid.cellHeight
                Accessible.role: Accessible.ListItem
                Accessible.name: "Seite " + (index + 1)
                Accessible.selected: chosen

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 4
                    radius: Metrics.radiusCard
                    color: cell.chosen ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16) : (hover.hovered ? Theme.subtleHover : "transparent")
                    border.width: cell.chosen ? 2 : 0
                    border.color: Theme.accent
                }
                HoverHandler { id: hover }
                Rectangle {
                    id: thumb
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 10 + (root.thumbBox * 1.42 - height) / 2
                    width: cell.size[0] * cell.fit
                    height: cell.size[1] * cell.fit
                    color: Theme.paper
                    border.color: Theme.border
                    Image {
                        anchors.fill: parent
                        anchors.margins: 1
                        asynchronous: true
                        retainWhileLoading: true
                        cache: false
                        smooth: true
                        source: root.doc ? "image://pdfpage/" + root.doc.docId + "/" + cell.index + "/" + Math.round(thumb.width * root.ratio) + "/" + root.doc.revision + "/thumb" : ""
                    }
                }
                PText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 8
                    text: String(cell.index + 1)
                    tone: cell.chosen ? "accent" : "secondary"
                    textStyle: "caption"
                }
            }

            // Einfügemarke beim Ziehen
            Rectangle {
                id: marker
                visible: dragArea.dragging && dragArea.target >= 0
                width: 3
                radius: 1.5
                color: Theme.accent
                height: grid.cellHeight - 16
                z: 5
                readonly property int at: Math.min(dragArea.target, Math.max(0, grid.count - 1))
                readonly property bool after: dragArea.target >= grid.count
                x: grid.count > 0 ? (at % grid.columns) * grid.cellWidth + (after ? grid.cellWidth : 0) - 2 : 0
                y: grid.count > 0 ? Math.floor(at / grid.columns) * grid.cellHeight + 8 : 0
            }
            readonly property int columns: Math.max(1, Math.floor((width - leftMargin - rightMargin) / cellWidth))

            MouseArea {
                id: dragArea
                parent: grid
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                property bool dragging: false
                property int pressIndex: -1
                property real pressX: 0
                property real pressY: 0
                property int target: -1
                function cellAt(x, y) { return grid.indexAt(x + grid.contentX, y + grid.contentY) }
                function insertionAt(x, y) {
                    var cx = x + grid.contentX, cy = y + grid.contentY
                    var index = grid.indexAt(cx, cy)
                    if (index < 0) return grid.count
                    var item = grid.itemAtIndex(index)
                    if (item && cx > item.x + item.width / 2) return index + 1
                    return index
                }
                onPressed: (event) => {
                    grid.forceActiveFocus()
                    pressIndex = cellAt(event.x, event.y)
                    pressX = event.x
                    pressY = event.y
                    if (pressIndex < 0) { if (!(event.modifiers & (Qt.ControlModifier | Qt.ShiftModifier))) root.selection = ({}); return }
                    if (event.button === Qt.RightButton) {
                        if (!root.selection[pressIndex]) root.select(pressIndex, 0)
                        pageMenu.popup()
                        return
                    }
                    if (!root.selection[pressIndex] || (event.modifiers & (Qt.ControlModifier | Qt.ShiftModifier))) root.select(pressIndex, event.modifiers)
                }
                onPositionChanged: (event) => {
                    if (pressIndex < 0 || !pressed) return
                    if (!dragging && Math.abs(event.x - pressX) + Math.abs(event.y - pressY) > 8) dragging = true
                    if (dragging) {
                        target = insertionAt(event.x, event.y)
                        scroller.speed = event.y < 40 ? -12 : (event.y > height - 40 ? 12 : 0)
                    }
                }
                onReleased: (event) => {
                    scroller.speed = 0
                    if (dragging) {
                        dragging = false
                        if (target >= 0 && root.hasSelection) root.doc.movePages(root.selectedPages, target)
                    } else if (pressIndex >= 0 && !(event.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)) && event.button === Qt.LeftButton) {
                        root.select(pressIndex, 0)
                    }
                    target = -1
                    pressIndex = -1
                }
                onDoubleClicked: (event) => {
                    var index = cellAt(event.x, event.y)
                    if (index < 0) return
                    Reader.setOrganize(false)
                    root.doc.goTo(index)
                }
            }
            Timer {
                id: scroller
                property real speed: 0
                interval: 16
                repeat: true
                running: speed !== 0
                onTriggered: grid.contentY = Math.max(grid.originY, Math.min(grid.contentY + speed, grid.originY + grid.contentHeight - grid.height))
            }
            Keys.onPressed: (event) => {
                if (event.key === Qt.Key_A && (event.modifiers & Qt.ControlModifier)) { root.selectAll(); event.accepted = true }
                else if (event.key === Qt.Key_Delete) { root.doc.deletePages(root.chosen()); event.accepted = true }
                else if (event.key === Qt.Key_Escape) { if (root.hasSelection) root.selection = ({}); else Reader.setOrganize(false); event.accepted = true }
            }
        }
    }
    PMenu {
        id: pageMenu
        PMenuItem { text: "Nach rechts drehen"; iconName: "arrow_rotate_clockwise"; onTriggered: root.doc.rotatePages(root.chosen(), 90) }
        PMenuItem { text: "Nach links drehen"; iconName: "arrow_rotate_counterclockwise"; onTriggered: root.doc.rotatePages(root.chosen(), -90) }
        PMenuItem { text: "Duplizieren"; iconName: "document_copy"; onTriggered: root.doc.duplicatePages(root.chosen()) }
        PMenuItem { text: "Als neue PDF speichern …"; iconName: "arrow_export"; onTriggered: root.doc.extractPages(root.chosen()) }
        PMenuItem { text: "Löschen"; iconName: "delete"; onTriggered: root.doc.deletePages(root.chosen()) }
        PMenuItem { text: "Anzeigen"; iconName: "eye"; onTriggered: { Reader.setOrganize(false); root.doc.goTo(root.chosen()[0]) } }
    }
}
