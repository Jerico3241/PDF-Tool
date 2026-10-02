import QtQuick
import QtQuick.Shapes
import QtQuick.Templates as T
import QtQuick.Window
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Seiten eines Dokuments. Nur sichtbare Seiten (plus eine halbe Bildschirmhöhe Vorlauf) existieren
// als Elemente – auch 1000+ Seiten bleiben flüssig; die Elemente werden wiederverwendet. Die Lage
// jeder Seite ergibt sich exakt aus den Seitengrößen: fortlaufend, einzeln, zwei nebeneinander
// oder fortlaufend zweiseitig. Strg+Mausrad zoomt um den Mauszeiger, Sprünge (Lesezeichen,
// Treffer, Miniaturen) holen die Stelle in den Blick. Ziehen mit der linken Maustaste gehört den
// Werkzeugen (Auswahl, Zeichnen, Verschieben) – verschoben wird mit Mausrad, Bildlaufleisten,
// Tastatur oder mit gedrückter mittlerer Maustaste.
Flickable {
    id: view
    objectName: "readerView"
    property var doc: null

    readonly property real zoomScale: doc ? doc.scale : 1
    readonly property int margin: Metrics.readerViewMargin
    readonly property int gap: doc ? doc.pageGap : 12
    readonly property string mode: doc ? doc.viewMode : "continuous"
    readonly property bool paired: mode === "two" || mode === "continuousTwo"
    readonly property bool paged: mode === "single" || mode === "two"
    readonly property var sizes: doc ? doc.pageSizes : []
    readonly property int pageCount: sizes.length
    readonly property int current: doc ? doc.currentPage : 0
    readonly property real ratio: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1
    // Hinweis: Die Aufbau-Funktionen lesen ``sizes.length`` statt ``pageCount`` – ein Handler wie
    // onSizesChanged kann laufen, bevor abgeleitete Bindungen (pageCount) neu berechnet sind.
    function rowTotal() {
        var n = sizes.length
        return n === 0 ? 0 : (paged ? 1 : (paired ? Math.ceil(n / 2) : n))
    }

    // Aufbau (aus relayout())
    property var rowTops: []
    property var rowHeights: []
    property var rowWidths: []
    property int layoutSerial: 0
    property var slotPages: []          // Seite je wiederverwendbarem Element (-1 = frei)
    property var viewAnchor: null       // Stelle in der Mitte der Ansicht (bleibt beim Zoomen)
    property bool restoring: false
    property int pendingEdge: 0         // Seitenweise: nach dem Blättern oben (1) oder unten (-1) beginnen
    property var editing: null          // offener Texteditor: {kind, page, rect, …}
    property int scrollSerial: 0        // für Ausschnitte bei hohem Zoom

    clip: true
    boundsBehavior: Flickable.StopAtBounds
    acceptedButtons: Qt.NoButton
    pixelAligned: true
    activeFocusOnTab: true
    Accessible.role: Accessible.Pane
    Accessible.name: doc ? "Dokument " + doc.name : "Dokument"
    T.ScrollBar.vertical: PScrollBar { id: vbar }
    T.ScrollBar.horizontal: PScrollBar { id: hbar }

    // Hintergrund hinter den Seiten
    Rectangle {
        parent: view
        anchors.fill: parent
        z: -1
        color: Theme.viewer
    }

    // --- Aufbau ------------------------------------------------------------------------------------------
    function rowPages(row) {
        var n = sizes.length
        if (n === 0 || row < 0) return []
        if (mode === "single") return [Math.min(current, n - 1)]
        if (mode === "two") {
            var first = Math.min(current, n - 1)
            first -= first % 2
            return first + 1 < n ? [first, first + 1] : [first]
        }
        if (mode === "continuousTwo") {
            var a = row * 2
            return a + 1 < n ? [a, a + 1] : [a]
        }
        return row < n ? [row] : []
    }
    function rowOf(page) {
        if (paged) return rowPages(0).indexOf(page) >= 0 ? 0 : -1
        return paired ? Math.floor(page / 2) : page
    }
    function relayout() {
        var tops = [], heights = [], widths = []
        var y = margin, widest = 0
        var rows = rowTotal()
        for (var r = 0; r < rows; ++r) {
            var pages = rowPages(r)
            var w = 0, h = 0
            for (var i = 0; i < pages.length; ++i) {
                var size = sizes[pages[i]]
                if (!size) continue
                w += size[0] * zoomScale
                h = Math.max(h, size[1] * zoomScale)
            }
            w += gap * (pages.length - 1)
            tops.push(y)
            heights.push(h)
            widths.push(w)
            widest = Math.max(widest, w)
            y += h + gap
        }
        var total = rows > 0 ? y - gap + margin : 0
        // Passt alles in die Höhe, stehen die Seiten mittig
        var shift = Math.max(0, (height - total) / 2)
        if (shift > 0)
            for (var k = 0; k < tops.length; ++k) tops[k] += shift
        rowTops = tops
        rowHeights = heights
        rowWidths = widths
        contentWidth = Math.max(width, Math.ceil(widest + 2 * margin))
        contentHeight = Math.max(height, Math.ceil(total))
        layoutSerial += 1
        updateSlots()
    }
    function pageRect(page) {
        if (page < 0 || page >= sizes.length || !sizes[page]) return Qt.rect(0, 0, 0, 0)
        var row = rowOf(page)
        if (row < 0 || row >= rowTops.length) return Qt.rect(0, 0, 0, 0)
        var pages = rowPages(row)
        var x = (contentWidth - rowWidths[row]) / 2
        for (var i = 0; i < pages.length && pages[i] !== page; ++i)
            x += sizes[pages[i]][0] * zoomScale + gap
        var w = sizes[page][0] * zoomScale
        var h = sizes[page][1] * zoomScale
        return Qt.rect(Math.round(x), Math.round(rowTops[row] + (rowHeights[row] - h) / 2), w, h)
    }
    // für Bindungen: ``serial`` (layoutSerial) sorgt für eine neue Auswertung nach jedem Aufbau
    function pageRectFor(page, serial) { return pageRect(page) }
    function rowAtY(y) {
        var lo = 0, hi = rowTops.length - 1
        if (hi < 0) return -1
        while (lo < hi) {
            var mid = (lo + hi + 1) >> 1
            if (rowTops[mid] <= y) lo = mid
            else hi = mid - 1
        }
        return lo
    }
    function updateSlots() {
        var wanted = []
        if (rowTops.length > 0) {
            var first = Math.max(0, rowAtY(contentY - height * 0.5))
            var last = rowAtY(contentY + height * 1.5)
            for (var r = first; r <= last && wanted.length < 160; ++r)
                wanted = wanted.concat(rowPages(r))
        }
        var pages = slotPages.slice()
        var want = {}, have = {}, i
        for (i = 0; i < wanted.length; ++i) want[wanted[i]] = true
        for (i = 0; i < pages.length; ++i) {
            if (pages[i] >= 0 && want[pages[i]] && !have[pages[i]]) have[pages[i]] = true
            else pages[i] = -1
        }
        var free = 0
        for (i = 0; i < wanted.length; ++i) {
            var page = wanted[i]
            if (have[page]) continue
            while (free < pages.length && pages[free] >= 0) ++free
            if (free === pages.length) pages.push(-1)
            pages[free] = page
            have[page] = true
        }
        while (slotModel.count < pages.length) slotModel.append({})
        var changed = pages.length !== slotPages.length
        for (i = 0; !changed && i < pages.length; ++i) changed = pages[i] !== slotPages[i]
        if (changed) slotPages = pages
    }

    // --- Lage merken und wiederherstellen ---------------------------------------------------------------
    function clampX(x) { return Math.max(0, Math.min(x, contentWidth - width)) }
    function clampY(y) { return Math.max(0, Math.min(y, contentHeight - height)) }
    // Ansichtspunkt (x, y) → Seite und Anzeige-Punkt (u, v)
    function pointAt(x, y) {
        var cx = contentX + x, cy = contentY + y
        var row = rowAtY(cy)
        if (row < 0) return null
        var pages = rowPages(row)
        if (pages.length === 0) return null
        var best = pages[0]
        for (var i = 1; i < pages.length; ++i)
            if (cx >= pageRect(pages[i]).x - gap / 2) best = pages[i]
        var rect = pageRect(best)
        return { page: best, u: (cx - rect.x) / zoomScale, v: (cy - rect.y) / zoomScale, x: x, y: y }
    }
    function restorePoint(point) {
        if (!point) return
        var rect = pageRect(point.page)
        if (rect.width <= 0) return
        restoring = true
        contentX = clampX(rect.x + point.u * zoomScale - point.x)
        contentY = clampY(rect.y + point.v * zoomScale - point.y)
        restoring = false
    }
    function rememberAnchor() {
        if (!restoring) viewAnchor = pointAt(width / 2, height / 2)
    }
    function zoomAt(factor, x, y) {
        if (!doc) return
        var point = pointAt(x, y)
        restoring = true
        doc.zoomBy(factor)
        relayout()
        restoring = false
        restorePoint(point)
        rememberAnchor()
    }
    // Seite (und Stelle u, v in Anzeige-Punkten; < 0 = Seitenanfang) in den Blick holen
    function reveal(page, u, v) {
        if (paged) relayout()
        var rect = pageRect(page)
        if (rect.width <= 0) return
        restoring = true
        if (u < 0 || v < 0) {
            contentY = clampY(rect.y - margin)
            if (rect.width > width) contentX = clampX(rect.x - margin)
        } else {
            var px = rect.x + u * zoomScale
            var py = rect.y + v * zoomScale
            if (py < contentY + 32 || py > contentY + height - 64) contentY = clampY(py - height / 3)
            if (px < contentX + 16 || px > contentX + width - 48) contentX = clampX(px - width / 2)
        }
        restoring = false
        rememberAnchor()
        updateSlots()
    }
    // Aktuelle Seite aus der Lage (fortlaufende Ansichten)
    function trackCurrent() {
        if (!doc || paged || restoring || rowTops.length === 0) return
        var row = contentY >= contentHeight - height - 1 && contentY > 0 ? rowTops.length - 1 : rowAtY(contentY + height * 0.3)
        var pages = rowPages(row)
        if (pages.length === 0) return
        var page = pages.indexOf(current) >= 0 ? current : pages[0]
        if (page !== current) doc.setCurrentPage(page)
    }

    onZoomScaleChanged: {
        var point = restoring ? null : viewAnchor
        relayout()
        if (point) restorePoint(point)
        rememberAnchor()
    }
    onSizesChanged: {
        var point = viewAnchor
        relayout()
        if (point && point.page < sizes.length) restorePoint(point)
        rememberAnchor()
    }
    onModeChanged: Qt.callLater(function() { view.relayout(); view.reveal(view.current, -1, -1) })
    onCurrentChanged: {
        if (!paged) return
        relayout()
        restoring = true
        contentY = pendingEdge < 0 ? clampY(contentHeight) : 0
        restoring = false
        pendingEdge = 0
        rememberAnchor()
    }
    onWidthChanged: resized()
    onHeightChanged: resized()
    function resized() {
        if (!doc) return
        var point = viewAnchor
        doc.setViewport(width, height, ratio)
        relayout()
        if (point) restorePoint({ page: point.page, u: point.u, v: point.v, x: width / 2, y: height / 2 })
        rememberAnchor()
    }
    onContentYChanged: {
        updateSlots()
        trackCurrent()
        rememberAnchor()
        scrollSerial += 1
    }
    onContentXChanged: {
        rememberAnchor()
        scrollSerial += 1
    }
    onDocChanged: {
        slotPages = []
        editing = null
        takeRevealTarget()  // nur merken: ein neuer Tab zeigt seine aktuelle Seite
        if (!doc) return
        doc.setViewport(width, height, ratio)
        relayout()
        restoring = true
        contentX = clampX((contentWidth - width) / 2)
        contentY = 0
        restoring = false
        reveal(doc.currentPage, -1, -1)
    }
    Component.onCompleted: if (doc) { doc.setViewport(width, height, ratio); relayout() }

    // Aufträge des Dokuments: Stelle in den Blick holen; nach einer Änderung den Editor schließen
    // (nur neue Aufträge desselben Dokuments – beim Wechsel des Tabs zählt dessen aktuelle Seite)
    readonly property var revealTarget: doc ? doc.revealTarget : ({})
    property var revealDoc: null
    property int revealSerial: 0
    function takeRevealTarget() {
        var serial = revealTarget.serial !== undefined ? revealTarget.serial : 0
        var fresh = doc === revealDoc && serial !== revealSerial
        revealDoc = doc
        revealSerial = serial
        if (fresh) reveal(revealTarget.page, revealTarget.u, revealTarget.v)
    }
    onRevealTargetChanged: takeRevealTarget()
    readonly property int revision: doc ? doc.revision : 0
    onRevisionChanged: editing = null

    // --- Seiten ------------------------------------------------------------------------------------------
    ListModel { id: slotModel }
    Repeater {
        model: slotModel
        PageView {
            host: view
            doc: view.doc
        }
    }

    // Texteditor über der Seite (Text ändern oder hinzufügen, Notiz, Textfeld)
    TextEditor {
        id: editor
        host: view
        doc: view.doc
        request: view.editing
        z: 20
        onFinished: view.editing = null
    }
    function openEditor(request) {
        editing = request
        var rect = pageRect(request.page)
        var px = rect.x + request.rect[0] * zoomScale, py = rect.y + request.rect[1] * zoomScale
        restoring = true
        if (py < contentY || py + 120 > contentY + height) contentY = clampY(py - height / 4)
        if (px < contentX || px + 260 > contentX + width) contentX = clampX(px - 24)
        restoring = false
        rememberAnchor()
    }

    // --- Bedienung ---------------------------------------------------------------------------------------
    WheelHandler {
        id: zoomWheel
        acceptedModifiers: Qt.ControlModifier
        target: null
        onWheel: (event) => {
            var delta = event.angleDelta.y !== 0 ? event.angleDelta.y : event.angleDelta.x
            if (delta === 0 || !view.doc) return
            var at = zoomWheel.parent.mapToItem(view, zoomWheel.point.position.x, zoomWheel.point.position.y)
            view.zoomAt(Math.pow(1.0018, delta), at.x, at.y)
        }
    }
    // Seitenweise: am Rand der Seite blättert das Mausrad weiter
    WheelHandler {
        enabled: view.paged
        acceptedModifiers: Qt.NoModifier
        target: null
        onWheel: (event) => {
            var delta = event.angleDelta.y
            if (delta === 0 || !view.doc) return
            if (delta < 0 && view.contentY >= view.contentHeight - view.height - 1) {
                view.pendingEdge = 1
                view.doc.step(1)
            } else if (delta > 0 && view.contentY <= 0) {
                view.pendingEdge = -1
                view.doc.step(-1)
            } else {
                view.contentY = view.clampY(view.contentY - delta / 120 * 64)
            }
        }
    }
    DragHandler {
        id: pan
        acceptedButtons: Qt.MiddleButton
        target: null
        property real startX: 0
        property real startY: 0
        onActiveChanged: if (active) { startX = view.contentX; startY = view.contentY }
        onTranslationChanged: {
            view.contentX = view.clampX(startX - translation.x)
            view.contentY = view.clampY(startY - translation.y)
        }
        cursorShape: Qt.ClosedHandCursor
    }

    Keys.onPressed: (event) => {
        if (!view.doc) return
        var page = view.height * 0.9
        switch (event.key) {
        case Qt.Key_Down:
            view.contentY = view.clampY(view.contentY + 48); break
        case Qt.Key_Up:
            view.contentY = view.clampY(view.contentY - 48); break
        case Qt.Key_PageDown: case Qt.Key_Space:
            if (view.paged && view.contentY >= view.contentHeight - view.height - 1) view.doc.step(1)
            else view.contentY = view.clampY(view.contentY + page)
            break
        case Qt.Key_PageUp:
            if (view.paged && view.contentY <= 0) { view.pendingEdge = -1; view.doc.step(-1) }
            else view.contentY = view.clampY(view.contentY - page)
            break
        case Qt.Key_Right:
            if (view.contentWidth > view.width + 1) view.contentX = view.clampX(view.contentX + 48)
            else view.doc.step(1)
            break
        case Qt.Key_Left:
            if (view.contentWidth > view.width + 1) view.contentX = view.clampX(view.contentX - 48)
            else view.doc.step(-1)
            break
        case Qt.Key_Home:
            view.doc.goTo(0); break
        case Qt.Key_End:
            view.doc.goTo(view.pageCount - 1); break
        case Qt.Key_Escape:
            if (view.doc.selectionPage >= 0) view.doc.clearSelection()
            else if (view.doc.tool !== "select") view.doc.setTool("select")
            else { event.accepted = false; return }
            break
        default:
            event.accepted = false
            return
        }
        event.accepted = true
    }

    // Fokusrahmen nur bei Tastaturbedienung (ein Klick in die Seite setzt »pointerFocus«)
    property bool pointerFocus: false
    onActiveFocusChanged: if (!activeFocus) pointerFocus = false
    function focusByPointer() {
        pointerFocus = true
        forceActiveFocus(Qt.MouseFocusReason)
    }
    PFocusRing { parent: view; inset: 1; radius_: 0; visible: view.activeFocus && !view.pointerFocus }
}
