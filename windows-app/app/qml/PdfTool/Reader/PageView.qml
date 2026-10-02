import QtQuick
import QtQuick.Shapes
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Eine Seite in der Ansicht: Papier, Seitenbild, bei hohem Zoom zusätzlich der sichtbare Ausschnitt
// in voller Schärfe, darüber Suchtreffer, Textauswahl und die Ebene des gewählten Werkzeugs.
// Das Seitenbild bleibt stehen, bis das neue fertig ist (Zoomen, Änderungen) – kein Flackern. Kommt eine
// Seite neu an diesen Platz (Scrollen, anderes Dokument), steht sofort das weiße Blatt und ihr Bild
// blendet kurz ein – nur Deckkraft, nie Lage oder Größe: die Seiten folgen dem Scrollen unmittelbar.
// Koordinaten aus Python sind Anzeige-Punkte der Seite; hier mal ``s`` (Pixel je Punkt).
Item {
    id: root
    required property int index
    property var host: null
    property var doc: null

    readonly property int page: host && index < host.slotPages.length ? host.slotPages[index] : -1
    readonly property rect area: host && page >= 0 ? host.pageRectFor(page, host.layoutSerial) : Qt.rect(0, 0, 0, 0)
    readonly property real s: host ? host.zoomScale : 1
    readonly property string tool: doc ? doc.tool : "select"
    readonly property string key: String(page)
    readonly property string base: doc && page >= 0 ? "image://pdfpage/" + doc.docId + "/" + page + "/" : ""
    readonly property int revision: doc ? doc.revision : 0
    readonly property int wantedWidth: Math.max(8, Math.round(width * (host ? host.ratio : 1)))
    readonly property bool capped: host !== null && width * host.ratio * height * host.ratio > Reader.maxPagePixels

    visible: page >= 0 && area.width > 0
    x: area.x
    y: area.y
    width: area.width
    height: area.height
    objectName: "readerPage_" + page
    Accessible.role: Accessible.Graphic
    Accessible.name: "Seite " + (page + 1)

    // --- Seitenbild ----------------------------------------------------------------------------------------
    property int shownPage: -1
    property string shownBase: ""
    property int requestedWidth: 0
    function requestImage() {
        // Beim Wechsel des Dokuments kann die Seite noch zum vorigen gehören – dann nichts anfragen
        if (base === "" || page >= doc.pageCount) {
            pageImage.source = ""
            dropPrevious()
            shownPage = -1
            shownBase = ""
            requestedWidth = 0
            return
        }
        if (width < 16) return  // Ansicht noch nicht angeordnet
        if (shownPage !== page || shownBase !== base) {
            pageImage.source = ""  // andere Seite oder anderes Dokument: nicht das Bild der vorigen zeigen
            dropPrevious()
            shownPage = page
            shownBase = base
        }
        requestedWidth = wantedWidth
        pageImage.source = base + wantedWidth + "/" + revision
    }
    onPageChanged: {
        widthTimer.stop()
        requestImage()
        detailTimer.restart()
        if (wantsObjects) doc.loadObjects(page)  // Objektmodus: auch die neue Seite dieses Platzes analysieren
    }
    // Änderung an diesem Dokument (Text, Kommentar, Rückgängig …): das bisherige Bild bleibt als Schnappschuss
    // über dem neuen stehen und blendet aus, sobald das neue fertig ist – die Änderung erscheint weich
    property bool crossfading: false
    function dropPrevious() {
        crossfading = false
        previousFade.stop()
        previousImage.visible = false
    }
    onRevisionChanged: {
        if (Motion.enabled && pageImage.ready && pageImage.status === Image.Ready && shownPage === page) {
            previousImage.scheduleUpdate()
            previousFade.stop()
            previousImage.opacity = 1
            previousImage.visible = true
            crossfading = true
        }
        requestImage()
    }
    onBaseChanged: requestImage()
    // Kleine Zoomschritte gesammelt (kurz warten), große Sprünge und das erste Bild sofort
    onWantedWidthChanged: {
        if (requestedWidth === 0 || wantedWidth > requestedWidth * 1.6 || wantedWidth < requestedWidth * 0.4) requestImage()
        else widthTimer.restart()
    }
    Timer { id: widthTimer; interval: 140; onTriggered: root.requestImage() }
    Component.onCompleted: requestImage()

    Rectangle {
        anchors.fill: parent
        anchors.margins: -1
        color: Theme.paper
        border.width: 1
        border.color: Theme.border
    }
    PageImage {
        id: pageImage
        // erstes Bild dieser Seite an diesem Platz: kurz einblenden; neue Fassungen (Zoom, Änderung) ohne Blinken
        anchors.fill: parent
        mipmap: false
        fillMode: Image.Stretch
        onStatusChanged: if (status === Image.Error) root.dropPrevious()
        onImageReady: {
            if (!root.crossfading) return
            root.crossfading = false
            previousFade.restart()
        }
    }
    ShaderEffectSource {
        id: previousImage
        objectName: "readerPagePrevious"
        anchors.fill: pageImage
        sourceItem: pageImage
        live: false
        visible: false
        NumberAnimation {
            id: previousFade
            target: previousImage
            property: "opacity"
            to: 0
            duration: Motion.renderFade
            easing.type: Motion.decelerate
            onFinished: previousImage.visible = false
        }
    }

    // Ausschnitt in voller Schärfe (nur wenn das ganze Seitenbild an seine Grenze stößt)
    property var detailRegion: null
    property var pendingRegion: null
    Timer { id: detailTimer; interval: 180; onTriggered: root.requestDetail() }
    readonly property int scrollSerial: host ? host.scrollSerial : 0
    onScrollSerialChanged: if (capped) detailTimer.restart()
    onCappedChanged: detailTimer.restart()
    onWidthChanged: if (capped) detailTimer.restart()
    function requestDetail() {
        if (!capped || base === "" || !host || page >= doc.pageCount) {
            detail.source = ""
            detailRegion = null
            return
        }
        var vx0 = (host.contentX - x) / s, vy0 = (host.contentY - y) / s
        var vx1 = vx0 + host.width / s, vy1 = vy0 + host.height / s
        var mx = (vx1 - vx0) * 0.25, my = (vy1 - vy0) * 0.25
        var x0 = Math.max(0, Math.floor((vx0 - mx) / 16) * 16)
        var y0 = Math.max(0, Math.floor((vy0 - my) / 16) * 16)
        var x1 = Math.min(width / s, Math.ceil((vx1 + mx) / 16) * 16)
        var y1 = Math.min(height / s, Math.ceil((vy1 + my) / 16) * 16)
        if (x1 - x0 < 1 || y1 - y0 < 1) return
        pendingRegion = [x0, y0, x1, y1]
        detail.source = base + wantedWidth + "/" + revision + "/region/" + Math.round(x0 * 10) + "/" + Math.round(y0 * 10) + "/" + Math.round(x1 * 10) + "/" + Math.round(y1 * 10)
    }
    Image {
        id: detail
        readonly property var r: root.detailRegion
        visible: root.capped && r !== null && status === Image.Ready
        x: r ? r[0] * root.s : 0
        y: r ? r[1] * root.s : 0
        width: r ? (r[2] - r[0]) * root.s : 0
        height: r ? (r[3] - r[1]) * root.s : 0
        asynchronous: true
        retainWhileLoading: true
        cache: false
        smooth: true
        onStatusChanged: if (status === Image.Ready) root.detailRegion = root.pendingRegion
    }

    // --- Suchtreffer und Auswahl ---------------------------------------------------------------------------
    // Treffer einer Seite blenden einmal ein, wenn die Seite ihre ersten Treffer bekommt (neue Treffer auf
    // anderen Seiten lösen hier nichts aus); der aktuelle Treffer bekommt einen kräftigeren Rahmen, der sich
    // beim Wechsel kurz auf den Treffer zusammenzieht – ohne Blinken, das Dokument selbst bewegt sich nicht.
    Item {
        id: hitLayer
        objectName: "readerHitLayer"
        readonly property var rects: root.doc && root.page >= 0 ? (root.doc.hitRects[root.key] || []) : []
        anchors.fill: parent
        opacity: rects.length > 0 ? 1 : 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
        Repeater {
            model: hitLayer.rects
            Rectangle {
                required property var modelData
                x: modelData[0] * root.s
                y: modelData[1] * root.s
                width: Math.max(2, (modelData[2] - modelData[0]) * root.s)
                height: Math.max(2, (modelData[3] - modelData[1]) * root.s)
                color: Theme.searchHit
            }
        }
    }
    Repeater {
        model: root.doc && root.doc.currentHit.page === root.page ? root.doc.currentHit.rects : []
        Rectangle {
            id: currentHit
            required property var modelData
            property real grow: 0  // zusätzlicher Abstand des Rahmens, zieht sich beim Erscheinen auf 0 zusammen
            objectName: "readerCurrentHit"
            x: modelData[0] * root.s - 2 - grow
            y: modelData[1] * root.s - 2 - grow
            width: (modelData[2] - modelData[0]) * root.s + 4 + 2 * grow
            height: (modelData[3] - modelData[1]) * root.s + 4 + 2 * grow
            color: "transparent"
            radius: 2 + grow / 2
            border.width: 2
            border.color: Theme.searchHitCurrent
            Component.onCompleted: if (Motion.enabled) arrive.start()
            ParallelAnimation {
                id: arrive
                NumberAnimation { target: currentHit; property: "opacity"; from: 0; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
                NumberAnimation { target: currentHit; property: "grow"; from: Motion.moves ? 6 : 0; to: 0; duration: Motion.expand; easing.type: Motion.decelerate }
            }
        }
    }
    Repeater {
        model: root.doc && root.doc.selectionPage === root.page ? root.doc.selectionRects : []
        Rectangle {
            required property var modelData
            x: modelData[0] * root.s
            y: modelData[1] * root.s
            width: (modelData[2] - modelData[0]) * root.s
            height: (modelData[3] - modelData[1]) * root.s
            color: Theme.selection
        }
    }

    // --- Hilfen: Treffer unter dem Zeiger ----------------------------------------------------------------
    function inRect(rect, u, v, pad) {
        return u >= rect[0] - pad && u <= rect[2] + pad && v >= rect[1] - pad && v <= rect[3] + pad
    }
    function smallestAt(items, u, v, pad) {
        var best = null, bestArea = 1e18
        for (var i = 0; i < items.length; ++i) {
            var r = items[i].view
            if (!inRect(r, u, v, pad)) continue
            var size = (r[2] - r[0]) * (r[3] - r[1])
            if (size < bestArea) { best = items[i]; bestArea = size }
        }
        return best
    }
    readonly property var annotationsHere: doc && page >= 0 ? (doc.annotationPages[key] || []) : []
    readonly property var blocksHere: doc && doc.blocksPage === page && tool === "editText" ? doc.blocks : []
    readonly property var imagesHere: doc && doc.imagesPage === page && tool === "image" ? doc.images : []
    readonly property var fieldsHere: doc && page >= 0 && tool === "form" ? (doc.fieldPages[key] || []) : []
    readonly property var selected: doc ? doc.selectedObject : ({})
    readonly property bool selectedHere: selected.page === page && selected.kind !== undefined

    // --- Objekt bearbeiten: Objekte dieser Seite, Auswahl, Treffer -----------------------------------------
    readonly property var objectsHere: doc && page >= 0 && tool === "objects" ? (doc.objectPages[key] || null) : null
    readonly property var objectItems: objectsHere ? objectsHere.segments.concat(objectsHere.images) : []
    // Räumlicher Index: Objekte je waagerechtem Band von 24 pt (Anzeige-Punkte, einmal je Seitenstand) –
    // beim Bewegen der Maus wird nur das Band unter dem Zeiger geprüft, nicht jedes Objekt der Seite
    readonly property real objectBand: 24
    readonly property var objectIndex: {
        var bands = ({})
        for (var i = 0; i < objectItems.length; ++i) {
            var r = objectItems[i].view
            for (var b = Math.floor((r[1] - 1) / objectBand); b <= Math.floor((r[3] + 1) / objectBand); ++b)
                (bands[b] = bands[b] || []).push(objectItems[i])
        }
        return bands
    }
    function objectsNear(v) { return objectIndex[Math.floor(v / objectBand)] || [] }
    function segmentAt(u, v) {
        var near = objectsNear(v), texts = []
        for (var i = 0; i < near.length; ++i)
            if (near[i].kind === "text") texts.push(near[i])
        return smallestAt(texts, u, v, 1)
    }
    readonly property var objectSelected: {
        if (!doc || tool !== "objects") return []
        var mine = []
        for (var i = 0; i < doc.objectSelection.length; ++i)
            if (doc.objectSelection[i].page === page) mine.push(doc.objectSelection[i])
        return mine
    }
    // Objekte nachladen, sobald diese Seite im Objektmodus sichtbar ist (auch nach einem Seitenwechsel des Platzes)
    readonly property bool wantsObjects: tool === "objects" && objectsHere === null && page >= 0 && doc !== null && visible
    onWantsObjectsChanged: if (wantsObjects) doc.loadObjects(page)
    function isChosen(id) {
        for (var i = 0; i < objectSelected.length; ++i)
            if (objectSelected[i].id === id) return true
        return false
    }
    // Objekt unter dem Zeiger: im gewählten Segment das Wort darunter (Wörter erst nach dem ersten Klick)
    function objectAt(u, v) {
        var hit = smallestAt(objectsNear(v), u, v, 1)
        var single = objectSelected.length === 1 ? objectSelected[0] : null
        if (hit && single && hit.words && (single.id === hit.id || single.segment === hit.id)) {
            var word = smallestAt(hit.words, u, v, 1)
            if (word && hit.words.length > 1)
                return { id: word.id, kind: "word", text: word.text, view: word.view, segment: hit.id, font: hit.font, size: hit.size, color: hit.color, native: hit.native, reason: hit.reason }
        }
        return hit
    }
    function caretAt(item, u) {
        // Cursor an der angeklickten Stelle (anteilig im Wort – Schriften mit Unterschneidung genügt das)
        var words = item.words || [{ text: item.text, view: item.view }]
        var offset = 0
        for (var i = 0; i < words.length; ++i) {
            var w = words[i]
            if (u <= w.view[2] || i === words.length - 1) {
                var share = Math.max(0, Math.min(1, (u - w.view[0]) / Math.max(0.1, w.view[2] - w.view[0])))
                return offset + Math.round(share * w.text.length)
            }
            offset += w.text.length + 1
        }
        return item.text.length
    }
    function editObject(item, u) {
        if (!item || item.kind === "image" || !host) return
        host.openEditor({ kind: "object", page: page, rect: item.view, text: item.text, object: item, caret: u === undefined ? item.text.length : caretAt(item, u) })
    }
    function editParagraph(item) {
        if (!item || !host || !doc) return
        host.pendingBlock = { page: page, u: (item.view[0] + item.view[2]) / 2, v: (item.view[1] + item.view[3]) / 2 }
        doc.setTool("editText")
        doc.loadBlocks(page)
    }
    onBlocksHereChanged: {
        var wanted = host ? host.pendingBlock : null
        if (!wanted || wanted.page !== page || blocksHere.length === 0) return
        host.pendingBlock = null
        var block = smallestAt(blocksHere, wanted.u, wanted.v, 2)
        if (block) host.openEditor({ kind: "block", page: page, rect: block.view, block: block, text: block.text })
    }

    // --- Kommentare (Werkzeug »Auswählen«) -----------------------------------------------------------
    Repeater {
        model: root.tool === "select" ? root.annotationsHere : []
        Rectangle {
            required property var modelData
            readonly property bool chosen: root.selectedHere && root.selected.kind === "annotation" && root.selected.key === modelData.key
            readonly property bool moving: chosen && pointer.action === "moveAnnotation"
            x: (modelData.view[0] + (moving ? pointer.du : 0)) * root.s - 2
            y: (modelData.view[1] + (moving ? pointer.dv : 0)) * root.s - 2
            width: (modelData.view[2] - modelData.view[0]) * root.s + 4
            height: (modelData.view[3] - modelData.view[1]) * root.s + 4
            color: "transparent"
            radius: 2
            border.width: chosen ? 2 : 1
            border.color: Theme.accent
            opacity: chosen ? 1 : (pointer.hoverKey === modelData.key ? 0.8 : 0)
            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
        }
    }

    // --- Textblöcke (Werkzeug »Text bearbeiten«) ---------------------------------------------------------
    Repeater {
        model: root.blocksHere
        Item {
            id: blockItem
            required property var modelData
            readonly property bool hovered: pointer.hoverKey === modelData.id
            x: modelData.view[0] * root.s - 3
            y: modelData.view[1] * root.s - 2
            width: (modelData.view[2] - modelData.view[0]) * root.s + 6
            height: (modelData.view[3] - modelData.view[1]) * root.s + 4
            visible: !(root.host && root.host.editing && root.host.editing.kind === "block" && root.host.editing.block.id === modelData.id)
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeWidth: blockItem.hovered ? 2 : 1
                    strokeColor: blockItem.modelData.native ? Theme.accent : Theme.warning
                    strokeStyle: blockItem.hovered ? ShapePath.SolidLine : ShapePath.DashLine
                    dashPattern: [3, 3]
                    fillColor: blockItem.hovered ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.08) : "transparent"
                    startX: 0.5; startY: 0.5
                    PathLine { x: blockItem.width - 0.5; y: 0.5 }
                    PathLine { x: blockItem.width - 0.5; y: blockItem.height - 0.5 }
                    PathLine { x: 0.5; y: blockItem.height - 0.5 }
                    PathLine { x: 0.5; y: 0.5 }
                }
            }
        }
    }

    // --- Bilder (Werkzeug »Bilder«) ------------------------------------------------------------------------
    Repeater {
        model: root.imagesHere
        Rectangle {
            id: imageBox
            required property var modelData
            readonly property bool chosen: root.selectedHere && root.selected.kind === "image" && root.selected.index === modelData.index
            readonly property var r: chosen && pointer.preview ? pointer.preview : modelData.view
            x: r[0] * root.s
            y: r[1] * root.s
            width: (r[2] - r[0]) * root.s
            height: (r[3] - r[1]) * root.s
            color: chosen ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.08) : "transparent"
            border.width: chosen || pointer.hoverKey === "image" + modelData.index ? 2 : 1
            border.color: modelData.editable ? Theme.accent : Theme.warning
            opacity: chosen || pointer.hoverKey === "image" + modelData.index ? 1 : 0.55
            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
            Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
            // Anfasser an den Ecken (Größe ändern; Seitenverhältnis bleibt, Umschalt: frei) – blenden kurz ein
            Repeater {
                model: imageBox.chosen && imageBox.modelData.editable ? 4 : 0
                Rectangle {
                    required property int index
                    width: Metrics.readerHandle
                    height: Metrics.readerHandle
                    radius: 2
                    x: (index % 2 === 0 ? 0 : imageBox.width) - width / 2
                    y: (index < 2 ? 0 : imageBox.height) - height / 2
                    color: Theme.surface
                    border.width: 2
                    border.color: Theme.accent
                    opacity: 0
                    Component.onCompleted: opacity = 1
                    Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast; easing.type: Motion.decelerate } }
                }
            }
        }
    }

    // --- Objekt bearbeiten: Hover, Auswahl, Ziehen, Auswahlrechteck ------------------------------------------
    // Nur das Objekt unter dem Zeiger erhält einen dezenten Rahmen – die Seite bleibt lesbar
    Rectangle {
        id: objectHover
        objectName: "readerObjectHover"
        readonly property var item: root.tool === "objects" && pointer.hoverItem && pointer.action === "" && !root.isChosen(pointer.hoverItem.id) ? pointer.hoverItem : null
        visible: item !== null
        x: item ? item.view[0] * root.s - 2 : 0
        y: item ? item.view[1] * root.s - 2 : 0
        width: item ? (item.view[2] - item.view[0]) * root.s + 4 : 0
        height: item ? (item.view[3] - item.view[1]) * root.s + 4 : 0
        radius: 2
        color: "transparent"
        border.width: 1
        border.color: item && item.native === false ? Theme.warning : Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.75)
    }
    Repeater {
        model: root.objectSelected
        Item {
            id: chosenBox
            required property var modelData
            readonly property bool moving: pointer.action === "moveObjects"
            readonly property bool resizing: modelData.kind === "image" && pointer.action === "resizeImage" && pointer.preview !== null
            readonly property var r: resizing ? pointer.preview : modelData.view
            objectName: "readerObjectSelection"
            x: (r[0] + (moving ? pointer.du : 0)) * root.s - 3
            y: (r[1] + (moving ? pointer.dv : 0)) * root.s - 3
            width: (r[2] - r[0]) * root.s + 6
            height: (r[3] - r[1]) * root.s + 6
            z: 5
            // Neue Auswahl sanft einblenden (kurz; Animationen aus: sofort)
            opacity: 0
            Component.onCompleted: opacity = 1
            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast; easing.type: Motion.decelerate } }
            // Beim Ziehen: Inhalt 1:1 mit dem Zeiger, Original abgeblendet
            Rectangle {
                parent: root
                visible: chosenBox.moving
                x: chosenBox.modelData.view[0] * root.s - 1
                y: chosenBox.modelData.view[1] * root.s - 1
                width: (chosenBox.modelData.view[2] - chosenBox.modelData.view[0]) * root.s + 2
                height: (chosenBox.modelData.view[3] - chosenBox.modelData.view[1]) * root.s + 2
                color: Theme.paper
                opacity: 0.65
                z: 4
            }
            ShaderEffectSource {
                anchors.fill: parent
                anchors.margins: 3
                visible: chosenBox.moving
                live: chosenBox.moving
                sourceItem: pageImage
                sourceRect: Qt.rect(chosenBox.modelData.view[0] * root.s, chosenBox.modelData.view[1] * root.s, (chosenBox.modelData.view[2] - chosenBox.modelData.view[0]) * root.s, (chosenBox.modelData.view[3] - chosenBox.modelData.view[1]) * root.s)
            }
            Rectangle {
                anchors.fill: parent
                radius: 2
                color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, chosenBox.moving ? 0.04 : 0.08)
                border.width: 2
                border.color: chosenBox.modelData.native === false ? Theme.warning : Theme.accent
            }
            // Anfasser an den Ecken (Bilder: Größe ändern; Seitenverhältnis bleibt, Umschalt: frei)
            Repeater {
                model: chosenBox.modelData.kind === "image" && chosenBox.modelData.editable && root.objectSelected.length === 1 ? 4 : 0
                Rectangle {
                    required property int index
                    width: Metrics.readerHandle
                    height: Metrics.readerHandle
                    radius: 2
                    x: (index % 2 === 0 ? 3 : chosenBox.width - 3) - width / 2
                    y: (index < 2 ? 3 : chosenBox.height - 3) - height / 2
                    color: Theme.surface
                    border.width: 2
                    border.color: Theme.accent
                }
            }
        }
    }
    Rectangle {
        objectName: "readerObjectMarquee"
        visible: pointer.action === "marquee" && (root.dragX1 - root.dragX0 > 2 || root.dragY1 - root.dragY0 > 2)
        x: root.dragX0
        y: root.dragY0
        width: root.dragX1 - root.dragX0
        height: root.dragY1 - root.dragY0
        z: 6
        color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.08)
        border.width: 1
        border.color: Theme.accent
    }

    // --- Formularfelder (Werkzeug »Formular ausfüllen«) ---------------------------------------------------
    Repeater {
        model: root.fieldsHere
        FieldOverlay {
            required property var modelData
            field: modelData
            doc: root.doc
            host: root.host
            s: root.s
            z: 10
        }
    }

    // --- Zeichnen: Freihand, Formen, Rahmen ------------------------------------------------------------------
    Shape {
        id: liveStroke
        anchors.fill: parent
        visible: pointer.action === "stroke"
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root.doc ? root.doc.toolColor : Theme.accent
            strokeWidth: Math.max(1, (root.doc ? root.doc.strokeWidth : 2) * root.s)
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathPolyline { path: pointer.strokePath }
        }
    }
    // Rahmen beim Aufziehen (Rechteck, Textfeld, Platz für ein Bild), Ellipse, Linie/Pfeil
    readonly property real dragX0: Math.min(pointer.startU, pointer.endU) * s
    readonly property real dragY0: Math.min(pointer.startV, pointer.endV) * s
    readonly property real dragX1: Math.max(pointer.startU, pointer.endU) * s
    readonly property real dragY1: Math.max(pointer.startV, pointer.endV) * s
    readonly property color drawColor: doc ? doc.toolColor : Theme.accent
    readonly property real drawWidth: Math.max(1, (doc ? doc.strokeWidth : 2) * s)
    Shape {
        anchors.fill: parent
        visible: pointer.action === "placeImage" || (pointer.action === "shape" && (root.tool === "rect" || root.tool === "textbox"))
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: pointer.action === "placeImage" || root.tool === "textbox" ? Theme.accent : root.drawColor
            strokeWidth: pointer.action === "placeImage" || root.tool === "textbox" ? 1 : root.drawWidth
            strokeStyle: pointer.action === "placeImage" || root.tool === "textbox" ? ShapePath.DashLine : ShapePath.SolidLine
            dashPattern: [4, 3]
            fillColor: "transparent"
            PathRectangle { x: root.dragX0; y: root.dragY0; width: root.dragX1 - root.dragX0; height: root.dragY1 - root.dragY0 }
        }
    }
    Shape {
        anchors.fill: parent
        visible: pointer.action === "shape" && root.tool === "ellipse"
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root.drawColor
            strokeWidth: root.drawWidth
            fillColor: "transparent"
            PathAngleArc {
                centerX: (root.dragX0 + root.dragX1) / 2
                centerY: (root.dragY0 + root.dragY1) / 2
                radiusX: Math.max(0.5, (root.dragX1 - root.dragX0) / 2)
                radiusY: Math.max(0.5, (root.dragY1 - root.dragY0) / 2)
                startAngle: 0
                sweepAngle: 360
            }
        }
    }
    Shape {
        anchors.fill: parent
        visible: pointer.action === "shape" && (root.tool === "line" || root.tool === "arrow")
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root.drawColor
            strokeWidth: root.drawWidth
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            startX: pointer.startU * root.s
            startY: pointer.startV * root.s
            PathLine { x: pointer.endU * root.s; y: pointer.endV * root.s }
        }
    }

    // --- Maus: je nach Werkzeug -------------------------------------------------------------------------------
    MouseArea {
        id: pointer
        anchors.fill: parent
        enabled: root.page >= 0 && root.tool !== "form"
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: root.tool === "select" || root.tool === "editText" || root.tool === "image" || root.tool === "objects"
        cursorShape: {
            switch (root.tool) {
            case "objects": return hoverCorner ? Qt.SizeFDiagCursor : (hoverItem ? (hoverItem.native === false && hoverItem.kind !== "image" ? Qt.PointingHandCursor : Qt.SizeAllCursor) : Qt.ArrowCursor)
            case "select": return hoverKey !== "" ? Qt.SizeAllCursor : Qt.IBeamCursor
            case "highlight": case "underline": case "strikeout": return Qt.IBeamCursor
            case "editText": return hoverKey !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor
            case "image": return hoverKey !== "" ? Qt.SizeAllCursor : Qt.CrossCursor
            default: return Qt.CrossCursor
            }
        }

        property string action: ""      // text, moveAnnotation, moveImage, resizeImage, stroke, shape, placeImage, moveObjects, marquee
        property string hoverKey: ""
        property var hoverItem: null    // Objekt unter dem Zeiger (Objekt bearbeiten)
        property bool hoverCorner: false
        property bool drill: false      // erneuter Klick aufs gewählte Segment: beim Loslassen das Wort wählen
        property string drilledFrom: ""  // Segment, aus dem der letzte Klick ins Wort gewechselt hat (Doppelklick)
        property real drilledAt: 0
        property string narrowTo: ""    // Klick ohne Ziehen auf ein Objekt einer Mehrfachauswahl: nur noch dieses
        property bool additive: false
        property real startU: 0
        property real startV: 0
        property real endU: 0
        property real endV: 0
        property real du: 0
        property real dv: 0
        property var preview: null      // neue Lage des Bildes beim Verschieben/Größe ändern
        property var stroke: []
        property var strokePath: []
        property int corner: -1
        property var target: null

        function point(mouse) {
            return { u: Math.max(0, Math.min(root.width, mouse.x)) / root.s, v: Math.max(0, Math.min(root.height, mouse.y)) / root.s }
        }
        onPositionChanged: (mouse) => {
            var p = point(mouse)
            if (!pressed) { updateHover(p); return }
            root.dragTo(p, mouse)
        }
        onExited: { hoverKey = ""; hoverItem = null; hoverCorner = false }
        onPressed: (mouse) => root.press(point(mouse), mouse)
        onReleased: (mouse) => root.release(point(mouse), mouse)
        onDoubleClicked: (mouse) => {
            var p = point(mouse)
            if (root.tool === "select" && root.doc) root.doc.selectWord(root.page, p.u, p.v)
            if (root.tool === "objects" && root.doc) {
                // Doppelklick: genau dieses Segment (bzw. ein zuvor gewähltes Wort) bearbeiten – nicht den Absatz.
                // Hat erst der erste Klick des Doppelklicks ins Wort gewechselt, gilt wieder das Segment.
                action = ""
                var hit = root.segmentAt(p.u, p.v)
                if (!hit) return
                var single = root.objectSelected.length === 1 ? root.objectSelected[0] : null
                var drilledNow = drilledFrom === hit.id && Date.now() - drilledAt <= Qt.styleHints.mouseDoubleClickInterval + 50
                drilledFrom = ""
                if (single && single.kind === "word" && single.segment === hit.id && !drilledNow) {
                    root.editObject(single, p.u)
                    return
                }
                if (!root.isChosen(hit.id)) root.doc.selectObject(root.page, hit.id, false)
                root.editObject(hit, p.u)
            }
        }
        onCanceled: { action = ""; preview = null; strokePath = [] }

        function updateHover(p) {
            var hit = null
            if (root.tool === "select") {
                hit = root.smallestAt(root.annotationsHere, p.u, p.v, 2)
                hoverKey = hit ? hit.key : ""
            } else if (root.tool === "editText") {
                hit = root.smallestAt(root.blocksHere, p.u, p.v, 2)
                hoverKey = hit ? hit.id : ""
            } else if (root.tool === "image") {
                hit = root.smallestAt(root.imagesHere, p.u, p.v, 0)
                hoverKey = hit ? "image" + hit.index : ""
            } else if (root.tool === "objects") {
                hoverCorner = root.selectedCorner(p) >= 0
                hit = hoverCorner ? null : root.objectAt(p.u, p.v)
                hoverItem = hit
                hoverKey = hit ? hit.id : ""
            }
        }
    }

    function press(p, mouse) {
        if (!doc) return
        host.focusByPointer()
        pointer.startU = pointer.endU = p.u
        pointer.startV = pointer.endV = p.v
        pointer.du = pointer.dv = 0
        pointer.action = ""
        if (mouse.button === Qt.RightButton) {
            if (tool === "objects" && objectsHere) {
                // Rechtsklick: die bestehende Auswahl bleibt (gewählte Zeile bleibt Zeile, gewähltes Wort
                // bleibt Wort); ein anderes Objekt wird gewählt – ins Wort wechselt nur der Linksklick
                var target = smallestAt(objectsNear(p.v), p.u, p.v, 1)
                if (target) {
                    var one = objectSelected.length === 1 ? objectSelected[0] : null
                    if (one && one.kind === "word" && one.segment === target.id) {
                        var word = smallestAt(target.words, p.u, p.v, 1)
                        if (word && word.id !== one.id) doc.selectObject(page, word.id, false)
                    } else if (!isChosen(target.id)) {
                        doc.selectObject(page, target.id, false)
                    }
                    var menu = target.kind === "image" ? imageObjectMenu : textObjectMenu
                    menu.u = p.u
                    menu.popup(pointer, mouse.x, mouse.y)
                    return
                }
            }
            contextMenu.u = p.u
            contextMenu.v = p.v
            contextMenu.popup(pointer, mouse.x, mouse.y)
            return
        }
        switch (tool) {
        case "select": {
            var annotation = smallestAt(annotationsHere, p.u, p.v, 2)
            if (annotation) {
                doc.selectedObject = { kind: "annotation", page: page, key: annotation.key, view: annotation.view }
                pointer.action = "moveAnnotation"
                return
            }
            doc.selectedObject = ({})
            doc.loadText(page)
            doc.clearSelection()
            pointer.action = "text"
            return
        }
        case "highlight": case "underline": case "strikeout":
            doc.loadText(page)
            doc.clearSelection()
            pointer.action = "text"
            return
        case "editText": {
            if (doc.blocksPage !== page) { doc.loadBlocks(page); return }
            var block = smallestAt(blocksHere, p.u, p.v, 2)
            if (block) host.openEditor({ kind: "block", page: page, rect: block.view, block: block, text: block.text })
            else host.editing = null
            return
        }
        case "objects": {
            if (!objectsHere) { doc.loadObjects(page); return }
            var handle = selectedCorner(p)
            if (handle >= 0) {
                pointer.corner = handle
                pointer.target = selectedImage()
                pointer.action = "resizeImage"
                return
            }
            var hit = smallestAt(objectsNear(p.v), p.u, p.v, 1)
            pointer.additive = (mouse.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)) !== 0
            pointer.drill = false
            if (!hit) {
                if (!pointer.additive) doc.clearObjectSelection()
                pointer.action = "marquee"
                return
            }
            if (mouse.modifiers & Qt.ControlModifier) {
                doc.selectObject(page, hit.id, true)  // Strg+Klick: hinzufügen bzw. entfernen
                return
            }
            var single = objectSelected.length === 1 ? objectSelected[0] : null
            pointer.narrowTo = objectSelected.length > 1 && isChosen(hit.id) && !pointer.additive ? hit.id : ""
            if (single && single.kind === "word" && single.segment === hit.id) {
                var word = smallestAt(hit.words, p.u, p.v, 1)
                if (word && word.id !== single.id) doc.selectObject(page, word.id, false)
            } else if (single && single.id === hit.id && hit.kind === "text") {
                pointer.drill = true  // erneuter Klick aufs gewählte Segment: Wort wählen (ohne Ziehen)
            } else if (!isChosen(hit.id)) {
                doc.selectObject(page, hit.id, false)
            }
            pointer.action = "moveObjects"
            return
        }
        case "addText":
            host.openEditor({ kind: "text", page: page, rect: [p.u, p.v, p.u + 200, p.v + 40], text: "" })
            return
        case "note":
            host.openEditor({ kind: "note", page: page, rect: [p.u, p.v, p.u + 220, p.v + 80], text: "" })
            return
        case "image": {
            if (doc.imagesPage !== page) { doc.loadImages(page); return }
            var corner = selectedCorner(p)
            if (corner >= 0) {
                pointer.corner = corner
                pointer.target = selectedImage()
                pointer.action = "resizeImage"
                return
            }
            var image = smallestAt(imagesHere, p.u, p.v, 0)
            if (image) {
                doc.selectedObject = { kind: "image", page: page, index: image.index, view: image.view, editable: image.editable, reason: image.reason }
                pointer.target = image
                pointer.action = image.editable ? "moveImage" : ""
            } else {
                doc.selectedObject = ({})
                pointer.action = "placeImage"
            }
            return
        }
        case "ink":
            pointer.stroke = [[p.u, p.v]]
            pointer.strokePath = [Qt.point(p.u * s, p.v * s)]
            pointer.action = "stroke"
            return
        case "rect": case "ellipse": case "line": case "arrow": case "textbox":
            pointer.action = "shape"
            return
        }
    }
    function selectedImage() {
        if (tool === "objects")
            return objectSelected.length === 1 && objectSelected[0].kind === "image" ? objectSelected[0] : null
        if (!(selectedHere && selected.kind === "image")) return null
        for (var i = 0; i < imagesHere.length; ++i)
            if (imagesHere[i].index === selected.index) return imagesHere[i]
        return null
    }
    function selectedCorner(p) {
        var image = selectedImage()
        if (!image || !image.editable) return -1
        var r = image.view, pad = Metrics.readerHandle / s
        var corners = [[r[0], r[1]], [r[2], r[1]], [r[0], r[3]], [r[2], r[3]]]
        for (var i = 0; i < 4; ++i)
            if (Math.abs(p.u - corners[i][0]) <= pad && Math.abs(p.v - corners[i][1]) <= pad) return i
        return -1
    }
    function dragTo(p, mouse) {
        pointer.endU = p.u
        pointer.endV = p.v
        pointer.du = p.u - pointer.startU
        pointer.dv = p.v - pointer.startV
        switch (pointer.action) {
        case "text":
            doc.selectRange(page, pointer.startU, pointer.startV, p.u, p.v)
            break
        case "moveImage": {
            var r = pointer.target.view
            pointer.preview = [r[0] + pointer.du, r[1] + pointer.dv, r[2] + pointer.du, r[3] + pointer.dv]
            break
        }
        case "resizeImage": {
            var box = pointer.target.view.slice()
            var c = pointer.corner
            var fx = c % 2 === 0 ? 0 : 2, fy = c < 2 ? 1 : 3           // gezogene Ecke
            var ox = c % 2 === 0 ? 2 : 0, oy = c < 2 ? 3 : 1           // feste Ecke gegenüber
            var w = Math.max(4, Math.abs(p.u - box[ox])), h = Math.max(4, Math.abs(p.v - box[oy]))
            if (!(mouse.modifiers & Qt.ShiftModifier)) {
                var ratio = (box[2] - box[0]) / Math.max(0.01, box[3] - box[1])
                if (w / h > ratio) h = w / ratio
                else w = h * ratio
            }
            var nx = box[ox] + (p.u >= box[ox] ? w : -w)
            var ny = box[oy] + (p.v >= box[oy] ? h : -h)
            pointer.preview = [Math.min(box[ox], nx), Math.min(box[oy], ny), Math.max(box[ox], nx), Math.max(box[oy], ny)]
            break
        }
        case "stroke": {
            var last = pointer.stroke[pointer.stroke.length - 1]
            if (Math.abs(last[0] - p.u) + Math.abs(last[1] - p.v) < 0.8) return
            pointer.stroke.push([p.u, p.v])
            var path = pointer.strokePath.slice()
            path.push(Qt.point(p.u * s, p.v * s))
            pointer.strokePath = path
            break
        }
        }
    }
    function release(p, mouse) {
        var action = pointer.action
        pointer.action = ""
        if (!doc) return
        var moved = Math.abs(pointer.du) + Math.abs(pointer.dv) > 0.5
        var rect = [Math.min(pointer.startU, p.u), Math.min(pointer.startV, p.v), Math.max(pointer.startU, p.u), Math.max(pointer.startV, p.v)]
        var big = rect[2] - rect[0] >= 4 || rect[3] - rect[1] >= 4
        switch (action) {
        case "text":
            if (tool !== "select" && doc.selectionPage === page) doc.markSelection(tool)
            break
        case "moveAnnotation":
            if (moved) doc.moveAnnotation(selected.key, pointer.du, pointer.dv)
            break
        case "moveImage":
            if (moved) doc.moveImage(page, pointer.target.index, pointer.du, pointer.dv)
            break
        case "resizeImage":
            if (pointer.preview) {
                if (tool === "objects") doc.resizeObjectImage(page, pointer.target.index, pointer.preview)
                else doc.resizeImage(page, pointer.target.index, pointer.preview)
            }
            break
        case "moveObjects":
            if (moved) {
                doc.moveObjects(pointer.du, pointer.dv)
            } else if (pointer.narrowTo !== "") {
                doc.selectObject(page, pointer.narrowTo, false)
            } else if (pointer.drill) {
                var segment = segmentAt(p.u, p.v)
                var word = segment && segment.words.length > 1 ? smallestAt(segment.words, p.u, p.v, 1) : null
                if (word) {
                    doc.selectObject(page, word.id, false)
                    pointer.drilledFrom = segment.id
                    pointer.drilledAt = Date.now()
                }
            }
            break
        case "marquee":
            if (big) doc.selectObjectsIn(page, rect, pointer.additive)
            break
        case "stroke":
            if (pointer.stroke.length >= 2) doc.addInk(page, [pointer.stroke])
            break
        case "shape":
            if (tool === "line" || tool === "arrow") {
                if (big) doc.addShape(page, tool, [pointer.startU, pointer.startV, p.u, p.v])
            } else if (tool === "textbox") {
                if (!big) rect = [p.u, p.v, p.u + 180, p.v + 48]
                host.openEditor({ kind: "textbox", page: page, rect: rect, text: "" })
            } else if (big) {
                doc.addShape(page, tool, rect)
            }
            break
        case "placeImage":
            if (big) doc.insertImage(page, rect)
            break
        }
        pointer.preview = null
        pointer.strokePath = []
        pointer.stroke = []
    }

    // Kontextmenüs im Objektmodus (Text, Bild) – keine dauerhafte Leiste
    PMenu {
        id: textObjectMenu
        objectName: "readerObjectMenu"
        property real u: 0
        readonly property var chosen: root.objectSelected
        readonly property var first: chosen.length ? chosen[0] : null
        PMenuItem {
            text: "Bearbeiten"
            iconName: "edit"
            enabled: textObjectMenu.chosen.length === 1
            onTriggered: {
                var item = textObjectMenu.first, u = textObjectMenu.u
                textObjectMenu.afterClose = function() { root.editObject(item, u) }
            }
        }
        PMenuItem { text: "Text bearbeiten (ganzer Absatz)"; iconName: "text_edit_style"; enabled: textObjectMenu.chosen.length === 1; onTriggered: root.editParagraph(textObjectMenu.first) }
        PMenuItem { text: "Kopieren"; iconName: "copy"; onTriggered: root.doc.copyObjects() }
        PMenuItem { text: "Ausschneiden"; iconName: "document_dismiss"; onTriggered: root.doc.cutObjects() }
        PMenuItem { text: "Duplizieren"; iconName: "document_copy"; enabled: textObjectMenu.chosen.length === 1; onTriggered: root.doc.duplicateObject() }
        PMenuItem { text: "Löschen"; iconName: "delete"; onTriggered: root.doc.deleteObjects() }
        PMenuItem { text: "Eigenschaften"; iconName: "text_font"; onTriggered: Reader.showRightPanel("properties") }
    }
    PMenu {
        id: imageObjectMenu
        objectName: "readerImageObjectMenu"
        property real u: 0
        readonly property var first: root.objectSelected.length ? root.objectSelected[0] : null
        readonly property bool editable: first !== null && first.kind === "image" && first.editable === true
        PMenuItem { text: "Ersetzen …"; iconName: "image"; enabled: imageObjectMenu.editable; onTriggered: root.doc.replaceImage(root.page, imageObjectMenu.first.index) }
        PMenuItem { text: "Drehen (90° im Uhrzeigersinn)"; iconName: "arrow_rotate_clockwise"; enabled: imageObjectMenu.editable; onTriggered: root.doc.rotateImage(root.page, imageObjectMenu.first.index, true) }
        PMenuItem { text: "Löschen"; iconName: "delete"; enabled: imageObjectMenu.editable; onTriggered: root.doc.deleteObjects() }
        PMenuItem { text: "Eigenschaften"; iconName: "image"; onTriggered: Reader.showRightPanel("properties") }
    }

    // Kontextmenü der Seite
    PMenu {
        id: contextMenu
        objectName: "readerContextMenu"
        property real u: 0
        property real v: 0
        readonly property bool hasSelection: root.doc !== null && root.doc.selectionPage === root.page
        PMenuItem { text: "Kopieren"; iconName: "copy"; enabled: contextMenu.hasSelection; onTriggered: root.doc.copySelection() }
        PMenuItem { text: "Alles auswählen (Seite)"; iconName: "select_all_on"; onTriggered: root.doc.selectAll(root.page) }
        PMenuItem { text: "Markieren"; iconName: "highlight"; enabled: contextMenu.hasSelection; onTriggered: root.doc.markSelection("highlight") }
        PMenuItem { text: "Unterstreichen"; iconName: "text_underline"; enabled: contextMenu.hasSelection; onTriggered: root.doc.markSelection("underline") }
        PMenuItem { text: "Durchstreichen"; iconName: "text_strikethrough"; enabled: contextMenu.hasSelection; onTriggered: root.doc.markSelection("strikeout") }
        PMenuItem {
            text: "Notiz hier hinzufügen"
            iconName: "comment"
            onTriggered: {
                var request = { kind: "note", page: root.page, rect: [contextMenu.u, contextMenu.v, contextMenu.u + 220, contextMenu.v + 80], text: "" }
                contextMenu.afterClose = function() { root.host.openEditor(request) }
            }
        }
        PMenuItem { text: "Seite drehen"; iconName: "arrow_rotate_clockwise"; onTriggered: root.doc.rotatePages([root.page], 90) }
    }
}
