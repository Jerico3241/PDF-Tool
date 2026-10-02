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
// Bewegung (»Vollständig«): Beim Ziehen werden die gewählten Seiten zu Platzhaltern an der neuen Stelle,
// eine kleine Vorschau mit Schatten folgt dem Zeiger, die übrigen Seiten rücken weich in die neue
// Reihenfolge; nach dem Ablegen rasten die Seiten ein. Gelöschte Seiten blenden aus, eingefügte blenden
// ein, die übrigen rücken weich nach. Jede Zelle wechselt erst dann auf ihre neue Lage, wenn ihr neues
// Bild da ist – so steht nie eine falsche Seite an einer Stelle. »Reduziert«: Überblenden und
// Einfügemarke statt Vorschau; »Aus«: alles sofort.
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
    onDocChanged: { selection = ({}); anchorIndex = -1; pending = null }

    // --- Bewegung ------------------------------------------------------------------------------------------
    function cellX(n) { return (n % grid.columns) * grid.cellWidth }
    function cellY(n) { return Math.floor(n / grid.columns) * grid.cellHeight }
    // Vorschau beim Ziehen (nur »Vollständig«): an welcher Stelle Seite ``i`` nach dem Ablegen stünde
    readonly property bool previewing: dragArea.dragging && Motion.moves && dragArea.target >= 0 && hasSelection
    function insertionAt(target) {
        var at = target
        for (var j = 0; j < selectedPages.length; ++j)
            if (selectedPages[j] < target) at -= 1
        return at
    }
    function previewIndex(i) {
        var sel = selectedPages, k = sel.length, before = 0
        var at = insertionAt(dragArea.target)
        for (var j = 0; j < k; ++j) {
            if (sel[j] === i) return at + j
            if (sel[j] < i) before += 1
        }
        var rank = i - before
        return rank >= at ? rank + k : rank
    }
    function cells() {
        var list = []
        var children = grid.contentItem.children
        for (var i = 0; i < children.length; ++i)
            if (children[i].isCell === true) list.push(children[i])
        return list
    }
    function updatePreview() {
        var list = cells()
        for (var i = 0; i < list.length; ++i)
            list[i].place(previewing ? previewIndex(list[i].index) : list[i].index, true)
    }
    onPreviewingChanged: if (previewing || pending === null) updatePreview()
    readonly property int dragTarget: dragArea.target
    onDragTargetChanged: if (previewing) updatePreview()

    // Laufende Seitenänderung aus dieser Ansicht. ``count``: erwartete Seitenzahl (-1: unbekannt),
    // ``from(n)``: neuer Index → alter Index (-1: neue Seite), ``snap``: Lage stimmt schon (nach dem Ziehen),
    // ``select``: Auswahl danach
    property var pending: null
    property int settleSerial: 0
    property var settleFrom: null
    property bool settleSnap: false
    property bool settleActive: false  // kurz nach einer Änderung: Zellen gleiten bzw. rasten ein
    readonly property int revision: doc ? doc.revision : 0
    onRevisionChanged: {
        var op = pending
        pending = null
        expiry.stop()
        if (!op || !doc || (op.count >= 0 && doc.pageCount !== op.count)) {
            if (op && op.snap) updatePreview()  // anders als erwartet: ohne Bewegung an die eigene Stelle
            return
        }
        // verschobene Seiten bleiben gewählt (an ihrer neuen Stelle) – in jedem Animationsprofil
        if (op.select) Qt.callLater(function() { root.selection = op.select })
        if (!Motion.enabled) {
            if (op.snap) updatePreview()
            return
        }
        settleFrom = op.from
        settleSnap = op.snap === true
        settleSerial += 1
        settleActive = true
        settleWindow.restart()
        var list = cells()
        for (var i = 0; i < list.length; ++i) list[i].settleWhenReady()
    }
    Timer { id: settleWindow; interval: 1500; onTriggered: root.settleActive = false }
    // Wird eine Änderung abgelehnt, abgebrochen oder schlägt sie fehl, kommt keine neue Fassung: dann gleich
    // (bzw. spätestens nach einigen Sekunden) zurück an die eigene Stelle – nichts bleibt hängen
    readonly property bool busy: doc ? doc.busy : false
    onBusyChanged: if (!busy && pending !== null) Qt.callLater(function() { if (root.pending !== null && !root.busy) expiry.triggered() })
    Timer {
        id: expiry
        interval: 8000
        onTriggered: { var op = root.pending; root.pending = null; if (op && op.snap) root.updatePreview() }
    }
    function begin(op) {
        pending = op
        expiry.restart()
    }
    // Seitenbefehle mit Bewegung; ohne Bewegung (Animationen aus) wie bisher
    function deleteChosen() {
        var list = chosen()
        var gone = {}
        for (var i = 0; i < list.length; ++i) gone[list[i]] = true
        var survivors = []
        for (var n = 0; n < pages; ++n) if (!gone[n]) survivors.push(n)
        begin({ count: survivors.length, from: function(index) { return index < survivors.length ? survivors[index] : -1 }, removing: gone })
        doc.deletePages(list)
        if (!doc.busy) pending = null  // abgebrochen oder nicht erlaubt
    }
    function duplicateChosen() {
        var list = chosen()
        var order = []
        for (var n = 0; n < pages; ++n) {
            order.push(n)
            if (list.indexOf(n) >= 0) order.push(-1)  // die Kopie folgt direkt auf ihre Seite
        }
        begin({ count: order.length, from: function(index) { return index < order.length ? order[index] : -1 } })
        doc.duplicatePages(list)
        if (!doc.busy) pending = null
    }
    function insertBlankAfter() {
        var list = chosen()
        var at = list[list.length - 1] + 1
        begin({ count: pages + 1, from: function(index) { return index < at ? index : (index === at ? -1 : index - 1) } })
        doc.insertBlankPage(at)
        if (!doc.busy) pending = null
    }
    function insertFileAfter() {
        var list = chosen()
        var at = list[list.length - 1] + 1
        var before = pages
        begin({ count: -1, from: function(index) {
            var added = root.pages - before
            return index < at ? index : (index < at + added ? -1 : index - added)
        } })
        doc.insertFromFile(at)
        if (!doc.busy) pending = null
    }
    function moveTo(target) {
        var sel = selectedPages
        var at = insertionAt(target)
        var order = []
        var rest = []
        for (var n = 0; n < pages; ++n) if (sel.indexOf(n) < 0) rest.push(n)
        order = rest.slice(0, at).concat(sel).concat(rest.slice(at))
        var unchanged = true
        for (n = 0; n < order.length; ++n) if (order[n] !== n) unchanged = false
        if (unchanged) return
        var next = {}
        for (var j = 0; j < sel.length; ++j) next[at + j] = true
        begin({ count: pages, snap: true, select: next, from: function(index) { return order[index] } })
        doc.movePages(sel, target)
        if (!doc.busy) pending = null
    }

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
                PIconButton { objectName: "readerOrganizeDelete"; iconName: "delete"; tip: "Löschen (Entf)"; onClicked: root.deleteChosen() }
                PIconButton { iconName: "document_copy"; tip: "Duplizieren"; onClicked: root.duplicateChosen() }
                PIconButton { iconName: "document_add"; tip: "Leere Seite danach einfügen"; onClicked: root.insertBlankAfter() }
                PIconButton { iconName: "document_arrow_up"; tip: "Seiten aus PDF danach einfügen …"; onClicked: root.insertFileAfter() }
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
                readonly property bool isCell: true
                readonly property var size: root.doc && index < root.doc.pageSizes.length ? root.doc.pageSizes[index] : [595, 842]
                readonly property real fit: Math.min(root.thumbBox / size[0], root.thumbBox * 1.42 / size[1])
                readonly property bool chosen: root.selection[index] === true
                // gezogene Seiten: Platzhalter an der neuen Stelle – Rahmen im Akzentton, Seite abgeblendet (die
                // Vorschau am Zeiger zeigt die Seite)
                readonly property bool lifted: root.previewing && chosen
                // gelöschte Seiten blenden aus, sobald das Löschen läuft
                readonly property bool removing: root.pending !== null && root.pending.removing !== undefined && root.pending.removing[index] === true && root.doc !== null && root.doc.busy
                width: grid.cellWidth
                height: grid.cellHeight
                Accessible.role: Accessible.ListItem
                Accessible.name: "Seite " + (index + 1)
                Accessible.selected: chosen

                // Lage: die eigene Zelle oder (beim Ziehen, nach einer Änderung) eine andere Stelle, von der aus
                // die Zelle weich an ihren Platz gleitet. ``shownAt``: Stelle, deren Nummer darunter steht
                property int shownAt: index
                property real offsetX: 0
                property real offsetY: 0
                property bool gliding: false
                transform: Translate { x: cell.offsetX; y: cell.offsetY }
                Behavior on offsetX { enabled: cell.gliding; NumberAnimation { duration: Motion.expand; easing.type: Motion.decelerate } }
                Behavior on offsetY { enabled: cell.gliding; NumberAnimation { duration: Motion.expand; easing.type: Motion.decelerate } }
                function place(at, animated) {
                    gliding = animated && Motion.moves
                    shownAt = at
                    offsetX = root.cellX(at) - root.cellX(index)
                    offsetY = root.cellY(at) - root.cellY(index)
                }
                GridView.onReused: { image.ready = false; settled = root.settleSerial; place(index, false); opacity = 1; scale = 1 }
                onIndexChanged: image.ready = false
                z: lifted ? 3 : 0

                // nach einer Änderung: sobald das neue Bild da ist, an die neue Lage (gleitend oder einrastend)
                property int settled: -1
                function settleWhenReady() { if (image.ready && image.status === Image.Ready && image.fresh) settle() }
                function settle() {
                    if (!root.settleActive || settled === root.settleSerial || root.settleFrom === null) return
                    settled = root.settleSerial
                    if (root.settleSnap) {
                        place(index, false)
                        if (root.settleFrom(index) !== index && root.selection[index] === true) drop.restart()
                        return
                    }
                    var from = root.settleFrom(index)
                    opacity = 1
                    if (from < 0) { arrive.restart(); return }
                    if (from !== index) {
                        place(from, false)
                        place(index, true)
                    }
                }
                Component.onCompleted: if (root.previewing) place(root.previewIndex(index), false)

                ParallelAnimation {
                    id: arrive
                    NumberAnimation { target: cell; property: "opacity"; from: 0; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
                    NumberAnimation { target: cell; property: "scale"; from: Motion.menuScale; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
                }
                NumberAnimation { id: drop; target: cell; property: "scale"; from: 1.04; to: 1; duration: Motion.expand; easing.type: Motion.decelerate }

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 4
                    radius: Metrics.radiusCard
                    color: cell.lifted ? "transparent" : (cell.chosen ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16) : (hover.hovered ? Theme.subtleHover : "transparent"))
                    border.width: cell.chosen ? 2 : 0
                    border.color: Theme.accent
                    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
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
                    opacity: cell.lifted ? 0.35 : (cell.removing ? 0 : 1)
                    scale: cell.removing ? Motion.menuScale : 1
                    Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast; easing.type: Motion.decelerate } }
                    Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.fast; easing.type: Motion.decelerate } }
                    Image {
                        id: image
                        // erstes fertiges Bild dieser Zelle: kurz einblenden; neue Fassungen ohne Blinken
                        property bool ready: false
                        property int loadedRevision: -1
                        readonly property bool fresh: loadedRevision === root.revision
                        anchors.fill: parent
                        anchors.margins: 1
                        asynchronous: true
                        retainWhileLoading: true
                        cache: false
                        smooth: true
                        source: root.doc ? "image://pdfpage/" + root.doc.docId + "/" + cell.index + "/" + Math.round(thumb.width * root.ratio) + "/" + root.doc.revision + "/thumb" : ""
                        onStatusChanged: {
                            if (status !== Image.Ready) return
                            ready = true
                            loadedRevision = root.revision
                            cell.settle()
                        }
                        opacity: ready ? 1 : 0
                        Behavior on opacity { enabled: Motion.enabled && image.ready; NumberAnimation { duration: Motion.renderFade; easing.type: Motion.decelerate } }
                    }
                }
                PText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 8
                    text: String(cell.shownAt + 1)
                    tone: cell.chosen ? "accent" : "secondary"
                    textStyle: "caption"
                }
            }

            // Einfügemarke beim Ziehen (ohne Vorschau: »Reduziert« und »Aus«)
            Rectangle {
                id: marker
                visible: dragArea.dragging && dragArea.target >= 0 && !root.previewing
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
                property real pointerX: 0
                property real pointerY: 0
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
                    pointerX = event.x
                    pointerY = event.y
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
                        // erst den Befehl (die Vorschau bleibt stehen, bis die neue Fassung da ist), dann Ende
                        if (target >= 0 && root.hasSelection) root.moveTo(target)
                        dragging = false
                        target = -1
                        if (root.pending === null) root.updatePreview()
                    } else if (pressIndex >= 0 && !(event.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)) && event.button === Qt.LeftButton) {
                        root.select(pressIndex, 0)
                    }
                    target = -1
                    pressIndex = -1
                }
                onCanceled: {
                    scroller.speed = 0
                    dragging = false
                    target = -1
                    pressIndex = -1
                    root.updatePreview()
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
                else if (event.key === Qt.Key_Delete) { root.deleteChosen(); event.accepted = true }
                else if (event.key === Qt.Key_Escape) {
                    if (dragArea.dragging) { dragArea.dragging = false; dragArea.target = -1; root.updatePreview() }
                    else if (root.hasSelection) root.selection = ({})
                    else Reader.setOrganize(false)
                    event.accepted = true
                }
            }
        }
    }
    // Vorschau der gezogenen Seiten am Zeiger: angehoben, mit Schatten und Anzahl
    Item {
        id: ghost
        objectName: "readerOrganizeGhost"
        readonly property int first: root.selectedPages.length > 0 ? root.selectedPages[0] : -1
        readonly property var size: root.doc && first >= 0 && first < root.doc.pageSizes.length ? root.doc.pageSizes[first] : [595, 842]
        readonly property real fit: Math.min(root.thumbBox * 0.6 / size[0], root.thumbBox * 0.85 / size[1])
        readonly property point at: grid.mapToItem(root, dragArea.pointerX, dragArea.pointerY)
        visible: opacity > 0
        opacity: dragArea.dragging && Motion.enabled && first >= 0 ? 0.95 : 0
        scale: dragArea.dragging ? 1 : Motion.menuScale
        x: at.x + 14
        y: at.y + 10
        width: size[0] * fit
        height: size[1] * fit
        z: 10
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast; easing.type: Motion.decelerate } }
        Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.fast; easing.type: Motion.decelerate } }
        PShadow { radius: 2 }
        Rectangle {
            anchors.fill: parent
            color: Theme.paper
            border.color: Theme.border
            Image {
                anchors.fill: parent
                anchors.margins: 1
                asynchronous: true
                cache: false
                smooth: true
                source: root.doc && ghost.first >= 0 && dragArea.dragging ? "image://pdfpage/" + root.doc.docId + "/" + ghost.first + "/" + Math.round(ghost.width * root.ratio) + "/" + root.doc.revision + "/thumb" : ""
            }
        }
        Rectangle {
            visible: root.selectedPages.length > 1
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: -8
            width: Math.max(22, countText.implicitWidth + 10)
            height: 22
            radius: 11
            color: Theme.accent
            PText { id: countText; anchors.centerIn: parent; text: String(root.selectedPages.length); color: Theme.textOnAccent; textStyle: "caption" }
        }
    }
    PMenu {
        id: pageMenu
        PMenuItem { text: "Nach rechts drehen"; iconName: "arrow_rotate_clockwise"; onTriggered: root.doc.rotatePages(root.chosen(), 90) }
        PMenuItem { text: "Nach links drehen"; iconName: "arrow_rotate_counterclockwise"; onTriggered: root.doc.rotatePages(root.chosen(), -90) }
        PMenuItem { text: "Duplizieren"; iconName: "document_copy"; onTriggered: root.duplicateChosen() }
        PMenuItem { text: "Als neue PDF speichern …"; iconName: "arrow_export"; onTriggered: root.doc.extractPages(root.chosen()) }
        PMenuItem { text: "Löschen"; iconName: "delete"; onTriggered: root.deleteChosen() }
        PMenuItem { text: "Anzeigen"; iconName: "eye"; onTriggered: { Reader.setOrganize(false); root.doc.goTo(root.chosen()[0]) } }
    }
}
