import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »PDF Reader & Editor«: Befehlsleiste, Leiste des Werkzeugs (die Dokument-Tabs stehen oben in der Leiste
// des Fensters); links die Seitenleiste mit Seiten, Lesezeichen oder Suche, rechts Kommentare oder
// Eigenschaften – jeweils mit ihren Umschaltern im eigenen Kopf, eingeklappt als schmaler Streifen mit
// Symbolen –, in der Mitte die Seiten (oder »Seiten organisieren«). Ohne Dokument (nur kurz, etwa während
// das erste geöffnet wird): ReaderStart; »Zuletzt verwendet« steht auf der Startseite. Rechts außerdem der
// KI-Assistent, wenn er in den Einstellungen eingeschaltet ist. In schmalen Fenstern
// liegen die Seitenleisten über der Ansicht.
// Tastenkürzel gelten nur, solange diese Seite zu sehen ist und kein Dialog offen ist.
FocusScope {
    id: page
    objectName: "readerPage"
    readonly property var doc: Reader.current
    readonly property bool narrow: width < Metrics.readerNarrowFrom
    readonly property bool active: App.currentPage === "reader" && !Dialogs.open
    readonly property bool editing: doc !== null && doc !== undefined
    property var dismissedNotices: ({})
    property var dismissedScans: ({})  // Hinweis »Gescannte Seiten« je Tab geschlossen
    // Hinweise zum Dokument (repariert, signiert, gescannt, Text nicht lesbar …) gehen nach 5 s von selbst zu
    // (seit 4.0.0-beta.2); ein Objekt-Hinweis erst wieder, wenn er sich ändert
    readonly property int noticeTime: 5000
    property string seenObjectMessage: ""
    // Objektmodus: die Eigenschaften öffnen sich mit dem Modus (nicht erst mit der ersten Auswahl – sonst
    // verschöbe sich die Seite unter dem Mauszeiger) und gehen beim Verlassen wieder zu, wenn sie dafür
    // geöffnet wurden. In schmalen Fenstern nie von selbst (dort überdecken sie die Seite).
    property bool propertiesOpenedForObjects: false
    // Linke Seitenleiste mit diesem Inhalt zeigen (Streifen oder Kopf); die Suche bekommt den Fokus
    function showLeft(key) {
        Reader.showLeftPanel(key)
        if (key === "search" && doc) doc.requestSearch()
    }
    // »Alle Werkzeuge« öffnen oder schließen (Befehlsleiste oder Schnellwerkzeuge)
    function toggleAllTools() {
        var panel = documentArea.item ? documentArea.item.allToolsPanel : null
        if (!panel || !doc) return
        if (panel.opened) panel.dismiss()
        else if (Date.now() - panel.closedAt > 300) panel.open()  // eben durch den Klick daneben geschlossen: zu lassen
    }
    // Einstellungen des Werkzeugs (Farbe, Stärke, Größe …): erst mit einem erneuten Klick auf das gewählte
    // Werkzeug; sie gehen wieder zu, sobald man in der Seite arbeitet, ein anderes Werkzeug oder PDF wählt
    property bool toolSettingsOpen: false
    onDocChanged: toolSettingsOpen = false
    readonly property string currentTool: doc ? doc.tool : ""
    onCurrentToolChanged: {
        toolSettingsOpen = false
        if (currentTool === "objects") {
            if (Reader.rightPanel === "" && !narrow) {
                Reader.showRightPanel("properties")
                propertiesOpenedForObjects = true
            }
            return
        }
        if (propertiesOpenedForObjects && Reader.rightPanel === "properties") Reader.setRightPanel("properties")
        propertiesOpenedForObjects = false
    }

    ReaderStart {
        anchors.fill: parent
        visible: !Reader.hasDocument
    }

    // Dokumentbereich (Tabs, Leisten, Ansicht, Seitenleisten, Tastenkürzel) – ohne Dokument nicht zu sehen.
    // Er entsteht erst nach der Seite im Hintergrund (asynchron, die Seite ist so schneller da); wird vorher
    // ein PDF geöffnet, sofort. Angestoßen wird er erst, wenn die Seite fertig ist (Qt.callLater): Entstünde
    // er beim Laden der Seite im Hintergrund mit, wartete die Seite auf ihn.
    Loader {
        id: documentArea
        objectName: "readerDocumentArea"
        property bool requested: false
        anchors.fill: parent
        visible: Reader.hasDocument
        focus: true
        active: requested || Reader.hasDocument
        asynchronous: !Reader.hasDocument
        sourceComponent: documentComponent
    }
    Component.onCompleted: Qt.callLater(function() { documentArea.requested = true })
    Component {
        id: documentComponent
        Item {
            readonly property var allToolsPanel: allTools
            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                // Die Dokument-Tabs stehen in der Leiste oben (AppTabs). Im Vollbild (F11) nur das Dokument mit den
                // schwebenden Leisten
                ReaderToolbar {
                    Layout.fillWidth: true
                    doc: page.doc
                    visible: !Reader.fullScreen
                    allToolsOpen: allTools.opened
                    onAllToolsRequested: page.toggleAllTools()
                    onSearchRequested: page.showLeft("search")
                }

                Item {
                    id: workspace
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    // Drei Ebenen: links und rechts je eine Seitenleiste mit fester Breite (springt nicht je nach
                    // Inhalt) – geschlossen ein schmaler Streifen mit ihren Symbolen –, dazwischen die
                    // Dokumentfläche. Öffnen/Schließen: die Leiste gleitet über ihren Streifen herein bzw. hinaus
                    // (»Reduziert«: blendet, »Aus«: sofort). Die Dokumentfläche nimmt ihre neue Breite einmal an.
                    readonly property bool leftOpen: Reader.leftPanel !== "" && !Reader.fullScreen
                    readonly property bool rightOpen: Reader.rightPanel !== "" && !Reader.fullScreen
                    readonly property int leftSpace: Reader.fullScreen ? 0 : (page.narrow || !leftOpen ? Metrics.readerRailWidth : Metrics.readerLeftPanelWidth)
                    // Schnellwerkzeuge zwischen linker Seitenleiste und Dokument (nicht im Vollbild und beim Organisieren)
                    readonly property bool quickShown: !Reader.fullScreen && !Reader.organize
                    readonly property int quickSpace: quickShown ? Metrics.readerQuickToolsWidth + 2 * Metrics.s8 : 0
                    readonly property int rightSpace: Reader.fullScreen ? 0 : (page.narrow || !rightOpen ? Metrics.readerRailWidth : Metrics.readerRightPanelWidth)
                    property real leftShown: leftOpen ? 1 : 0   // 0…1: wie weit die Leiste zu sehen ist
                    property real rightShown: rightOpen ? 1 : 0
                    Behavior on leftShown { enabled: Motion.enabled; NumberAnimation { duration: Motion.moves ? Motion.pane : Motion.fade; easing.type: Motion.decelerate } }
                    Behavior on rightShown { enabled: Motion.enabled; NumberAnimation { duration: Motion.moves ? Motion.pane : Motion.fade; easing.type: Motion.decelerate } }

                    Item {
                        id: center
                        anchors.fill: parent
                        // neue Breite sofort (einmal neu angeordnet, nicht in jedem Bild der Leisten-Animation)
                        anchors.leftMargin: workspace.leftSpace + workspace.quickSpace
                        anchors.rightMargin: workspace.rightSpace

                        // Geteilte Ansicht: links das aktuelle PDF, rechts ein zweites (nicht beim Organisieren und
                        // in der Präsentation)
                        readonly property bool split: Reader.splitDoc !== null && !Reader.organize && !Reader.presenting
                        // Geteilte Ansicht: Kopf mit dem Namen auch links, damit beide Seiten auf gleicher Höhe beginnen
                        Rectangle {
                            id: leftHeader
                            objectName: "readerSplitLeftHeader"
                            anchors.left: parent.left
                            anchors.top: parent.top
                            width: view.width
                            height: center.split ? Metrics.readerPanelHeaderHeight : 0
                            visible: center.split
                            color: Theme.layer
                            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.divider }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                x: Metrics.s8 + 12  // wie der Name im Kopf rechts (Schaltfläche mit Innenrand)
                                spacing: 8
                                PIcon { anchors.verticalCenter: parent.verticalCenter; name: "document_pdf"; color: Theme.textPrimary }
                                PText { anchors.verticalCenter: parent.verticalCenter; text: page.doc ? page.doc.name : "" }
                            }
                        }
                        DocumentView {
                            id: view
                            onInteracted: page.toolSettingsOpen = false
                            anchors.left: parent.left
                            anchors.top: leftHeader.bottom
                            anchors.bottom: parent.bottom
                            width: center.split ? Math.round(parent.width / 2) : parent.width
                            doc: page.doc
                            visible: !Reader.organize
                            focus: true
                        }
                        Loader {
                            anchors.left: view.right
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            active: center.split
                            visible: active
                            sourceComponent: SplitPane {}
                        }
                        Loader {
                            anchors.fill: parent
                            active: Reader.organize
                            sourceComponent: OrganizeView { doc: page.doc }
                            onLoaded: item.forceActiveFocus()
                        }
                        ViewControls {
                            id: controls
                            anchors.horizontalCenter: view.horizontalCenter
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 16
                            doc: page.doc
                            view: view
                            visible: !Reader.organize && !Reader.presenting && page.doc !== null
                        }
                        // Schwebend über der Seite: Leiste des Werkzeugs, Meldungen des Readers und Hinweis zum Dokument
                        // (signiert, repariert, XFA …) – untereinander, ohne die Seiten zu verschieben
                        ColumnLayout {
                            anchors.left: parent.left
                            anchors.right: view.right
                            anchors.top: parent.top
                            anchors.leftMargin: 16
                            anchors.rightMargin: 24
                            spacing: 0
                            visible: !Reader.presenting
                            ToolOptions {
                                Layout.fillWidth: true
                                doc: page.doc
                                settingsOpen: page.toolSettingsOpen
                                suppressed: Reader.fullScreen || Reader.organize
                            }
                            OcrProgress { Layout.fillWidth: true; doc: page.doc }
                            PInfoBar { Layout.fillWidth: true; notice: Notices.area("reader") }
                            PInfoBar {
                                objectName: "readerObjectNotice"
                                Layout.fillWidth: true
                                shown: page.doc !== null && page.doc.tool === "objects" && page.doc.objectMessage !== "" && page.doc.objectMessage !== page.seenObjectMessage
                                severity: "info"
                                message: page.doc ? page.doc.objectMessage : ""
                                closable: false
                                autoHide: page.noticeTime
                                onClosed: page.seenObjectMessage = message
                            }
                            // Gescanntes Dokument (Seiten ohne Text): Texterkennung anbieten – je Tab einmal schließbar
                            PInfoBar {
                                objectName: "readerScanNotice"
                                Layout.fillWidth: true
                                shown: page.doc !== null && page.doc.scanHint && !page.doc.ocrRunning && !page.dismissedScans[page.doc.docId] && !Reader.fullScreen
                                severity: "info"
                                title: "Gescannte Seiten"
                                message: "Dieses PDF enthält Seiten ohne erkannten Text – Suchen und Kopieren finden darauf nichts."
                                actions: ["Text erkennen …"]
                                autoHide: page.noticeTime
                                onActionTriggered: page.doc.recognizeText([])
                                onClosed: {
                                    var next = Object.assign({}, page.dismissedScans)
                                    next[page.doc.docId] = true
                                    page.dismissedScans = next
                                }
                            }
                            PInfoBar {
                                objectName: "readerDocumentNotice"
                                Layout.fillWidth: true
                                shown: page.doc !== null && page.doc.notice !== "" && !page.dismissedNotices[page.doc.docId]
                                severity: page.doc ? page.doc.noticeKind : "info"
                                message: page.doc ? page.doc.notice : ""
                                autoHide: page.noticeTime
                                onClosed: {
                                    var next = Object.assign({}, page.dismissedNotices)
                                    next[page.doc.docId] = true
                                    page.dismissedNotices = next
                                }
                            }
                        }
                        // Arbeit im Hintergrund (Speichern, Text ändern, ein weiteres PDF wird geöffnet …)
                        PProgressBar {
                            objectName: "readerBusy"
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            indeterminate: true
                            visible: (page.doc !== null && page.doc.busy) || Reader.opening > 0
                        }
                        // PDF über die Ansicht gezogen: Ablagefläche blendet weich ein (öffnet in einem neuen Tab) und
                        // beim Verlassen wieder aus – nur solange gezogen wird
                        Item {
                            objectName: "readerDropOverlay"
                            anchors.fill: parent
                            anchors.margins: Metrics.s16
                            opacity: Reader.dropHighlight ? 1 : 0
                            visible: opacity > 0
                            scale: Reader.dropHighlight ? 1 : Motion.menuScale
                            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
                            Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
                            Rectangle { anchors.fill: parent; radius: Metrics.radiusCard; color: Theme.viewer; opacity: 0.9 }
                            PDropZone {
                                anchors.fill: parent
                                highlighted: true
                                iconName: "document_pdf"
                                title: "PDF hier ablegen"
                                text: "Jede abgelegte PDF öffnet sich in einem eigenen Tab."
                            }
                        }
                    }

                    Rectangle {
                        objectName: "readerQuickToolsArea"
                        x: workspace.leftSpace
                        width: workspace.quickSpace
                        height: workspace.height
                        visible: workspace.quickShown
                        color: Theme.viewer
                        QuickTools {
                            id: quickTools
                            x: Metrics.s8
                            y: Metrics.readerViewMargin + (center.split ? Metrics.readerPanelHeaderHeight : 0)  // oben bündig mit der Seite
                            doc: page.doc
                            allToolsOpen: allTools.opened
                            onAllToolsRequested: page.toggleAllTools()
                            onSettingsRequested: page.toolSettingsOpen = !page.toolSettingsOpen
                        }
                    }
                    // »Alle Werkzeuge«: gleitet neben den Schnellwerkzeugen über die Seite
                    AllTools {
                        id: allTools
                        doc: page.doc
                        x: workspace.leftSpace + workspace.quickSpace - Metrics.s4
                        y: Metrics.readerViewMargin  // oben bündig mit Schnellwerkzeugen und Seite
                        height: workspace.height - 2 * Metrics.readerViewMargin
                    }

                    // Eingeklappte Seitenleisten (bei offener Leiste: deren Hintergrund)
                    PanelRail {
                        objectName: "readerLeftRail"
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: workspace.leftSpace
                        visible: !Reader.fullScreen
                        z: 1
                        side: "left"
                        collapsed: !workspace.leftOpen
                        items: [
                            { key: "thumbs", icon: "document_one_page_multiple", tip: "Seiten", name: "readerRailThumbs" },
                            { key: "outline", icon: "bookmark", tip: "Lesezeichen", name: "readerRailOutline" },
                            { key: "search", icon: "search", tip: "Suchen (Strg+F)", name: "readerRailSearch" },
                            { key: "attachments", icon: "attach", tip: "Anhänge", name: "readerRailAttachments" }
                        ]
                        onSelected: (key) => page.showLeft(key)
                    }
                    PanelRail {
                        objectName: "readerRightRail"
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: workspace.rightSpace
                        visible: !Reader.fullScreen
                        z: 1
                        side: "right"
                        collapsed: !workspace.rightOpen
                        items: [
                            { key: "comments", icon: "comment", tip: "Kommentare", name: "readerRailComments" },
                            { key: "properties", icon: "text_font", tip: "Eigenschaften", name: "readerRailProperties" }
                        ].concat(Assistant.enabled ? [{ key: "assistant", icon: "sparkle", tip: "KI-Assistent", name: "readerRailAssistant" }] : [])
                         .concat(Reader.compareActive ? [{ key: "compare", icon: "branch_compare", tip: "Vergleich", name: "readerRailCompare" }] : [])
                        onSelected: (key) => Reader.showRightPanel(key)
                    }
                    LeftPanel {
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        x: Motion.moves ? -(1 - workspace.leftShown) * width : 0
                        width: Metrics.readerLeftPanelWidth
                        opacity: Motion.moves ? 1 : workspace.leftShown
                        visible: workspace.leftShown > 0
                        doc: page.doc
                        z: 2
                        onChosen: (key) => page.showLeft(key)
                        PShadow { visible: page.narrow; radius: 0 }
                    }
                    RightPanel {
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        x: workspace.width - width + (Motion.moves ? (1 - workspace.rightShown) * width : 0)
                        width: Metrics.readerRightPanelWidth
                        opacity: Motion.moves ? 1 : workspace.rightShown
                        visible: workspace.rightShown > 0
                        doc: page.doc
                        z: 2
                        PShadow { visible: page.narrow; radius: 0 }
                    }
                }
            }

            // Tastenkürzel (zusätzlich zu Strg+O, Strg+F, F1 und Strg+Eingabe aus dem Fenster)
            Shortcut { sequences: [StandardKey.Save]; enabled: page.active && page.editing; onActivated: page.doc.saveDocument() }
            Shortcut { sequence: "Ctrl+Shift+S"; enabled: page.active && page.editing; onActivated: page.doc.saveDocumentAs() }
            Shortcut { sequences: [StandardKey.Print]; enabled: page.active && page.editing; onActivated: page.doc.printDocument() }
            Shortcut { sequences: [StandardKey.Undo]; enabled: page.active && page.editing && view.editing === null; onActivated: page.doc.undo() }
            Shortcut { sequences: ["Ctrl+Y", "Ctrl+Shift+Z"]; enabled: page.active && page.editing && view.editing === null; onActivated: page.doc.redo() }
            Shortcut { sequence: "Ctrl+W"; enabled: page.active && Reader.hasDocument; onActivated: Reader.closeCurrent() }
            Shortcut { sequences: ["F11"]; enabled: page.active && page.editing; onActivated: Reader.toggleFullScreen() }
            Shortcut { sequences: ["F5"]; enabled: page.active && page.editing && !Reader.presenting; onActivated: Reader.startPresentation() }
            Shortcut { sequence: "Ctrl+G"; enabled: page.active && page.editing && !Reader.organize; onActivated: controls.focusPage() }
            Shortcut {
                sequences: [StandardKey.SelectAll]
                enabled: page.active && page.editing && !Reader.organize && view.editing === null
                onActivated: {
                    if (page.doc.tool === "objects") page.doc.selectAllObjects(page.doc.currentPage)
                    else page.doc.selectAll(page.doc.currentPage)
                }
            }
            Shortcut { sequence: "Ctrl+Tab"; enabled: page.active && Reader.tabs.count > 1; onActivated: Reader.activateIndex(1) }
            Shortcut { sequence: "Ctrl+Shift+Tab"; enabled: page.active && Reader.tabs.count > 1; onActivated: Reader.activateIndex(-1) }
            Shortcut { sequences: [StandardKey.ZoomIn, "Ctrl+="]; enabled: page.active && page.editing; onActivated: view.smoothly(function() { page.doc.zoomIn() }) }
            Shortcut { sequences: [StandardKey.ZoomOut]; enabled: page.active && page.editing; onActivated: view.smoothly(function() { page.doc.zoomOut() }) }
            Shortcut { sequence: "Ctrl+0"; enabled: page.active && page.editing; onActivated: view.smoothly(function() { page.doc.fitPage() }) }
            Shortcut { sequence: "F3"; enabled: page.active && page.editing && page.doc.searchCount > 0; onActivated: page.doc.nextHit() }
            Shortcut { sequence: "Shift+F3"; enabled: page.active && page.editing && page.doc.searchCount > 0; onActivated: page.doc.previousHit() }
            Shortcut { sequences: [StandardKey.Copy]; enabled: page.active && page.editing && page.doc.selectionPage >= 0 && page.doc.objectSelection.length === 0; onActivated: page.doc.copySelection() }
            Shortcut {
                sequences: [StandardKey.Delete]
                enabled: page.active && page.editing && !Reader.organize && page.doc.tool !== "objects" && page.doc.selectedObject.kind !== undefined
                onActivated: {
                    var chosen = page.doc.selectedObject
                    if (chosen.kind === "image") page.doc.deleteImage(chosen.page, chosen.index)
                    else if (chosen.kind === "annotation") page.doc.deleteAnnotation(chosen.key)
                }
            }
        }
    }
}
