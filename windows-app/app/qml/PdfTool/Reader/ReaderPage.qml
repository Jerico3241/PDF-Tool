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
    // Tabellen (seit 5.0) und Texte (seit 5.0 Beta 3) haben ihre eigene Ansicht (SheetView, TextView); »doc« ist immer ein PDF
    readonly property bool sheetShown: Reader.current !== null && Reader.current !== undefined && Reader.current.kind === "tabelle"
    readonly property bool textShown: Reader.current !== null && Reader.current !== undefined && Reader.current.kind === "text"
    readonly property bool slidesShown: Reader.current !== null && Reader.current !== undefined && Reader.current.kind === "praesentation"
    readonly property bool officeShown: sheetShown || textShown || slidesShown
    // Direkt aus Reader.current (nicht über officeShown): beim Wechsel Text → Tabelle war officeShown kurz falsch
    // (textShown schon aus, sheetShown noch nicht an) und die PDF-Ansicht bekam die Tabelle
    readonly property var doc: Reader.current && ["tabelle", "text", "praesentation"].indexOf(Reader.current.kind) < 0 ? Reader.current : null
    readonly property bool narrow: width < Metrics.readerNarrowFrom
    readonly property bool active: App.currentPage === "reader" && !Dialogs.open && !officeShown
    readonly property bool editing: doc !== null && doc !== undefined
    property var dismissedNotices: ({})
    property var dismissedOffice: ({})  // Hinweis »Ansicht« je Dokument geschlossen
    property var dismissedScans: ({})  // Hinweis »Gescannte Seiten« je Tab geschlossen
    // Hinweise zum Dokument (repariert, signiert, gescannt, Text nicht lesbar …) gehen nach 5 s von selbst zu
    // (seit 4.0); ein Objekt-Hinweis erst wieder, wenn er sich ändert
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
    // Seitenleiste über den Streifen rechts: ein Klick zeigt den Inhalt, ein Klick auf den gezeigten schließt sie
    readonly property var leftKeys: ["thumbs", "outline", "search", "attachments"]
    function toggleSide(key) {
        if (Reader.leftPanel === key) { Reader.setLeftPanel(key); return }
        if (Reader.rightPanel === key) { Reader.setRightPanel(key); return }
        if (leftKeys.indexOf(key) >= 0) showLeft(key)
        else Reader.showRightPanel(key)
    }
    // Beide Seitenleisten stehen rechts an derselben Stelle: die zuletzt geöffnete schließt die andere
    Connections {
        target: Reader
        function onLeftPanelChanged() { if (Reader.leftPanel !== "" && Reader.rightPanel !== "") Reader.setRightPanel(Reader.rightPanel) }
        function onRightPanelChanged() { if (Reader.rightPanel !== "" && Reader.leftPanel !== "") Reader.setLeftPanel(Reader.leftPanel) }
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
        visible: Reader.hasDocument && !page.officeShown
        focus: !page.officeShown
        active: requested || Reader.hasDocument
        asynchronous: !Reader.hasDocument
        sourceComponent: documentComponent
    }
    Component.onCompleted: Qt.callLater(function() { documentArea.requested = true })

    // Tabelle bearbeiten (seit 5.0): Menüband, Formelleiste, Raster und Blätter
    Loader {
        id: sheetArea
        objectName: "readerSheetArea"
        anchors.fill: parent
        active: page.sheetShown
        visible: active
        focus: page.sheetShown
        sourceComponent: SheetView {
            sheet: page.sheetShown ? Reader.current : null
        }
    }

    // Text bearbeiten (seit 5.0 Beta 3): Menüband, Seiten und Formatvorlagen
    Loader {
        id: textArea
        objectName: "readerTextArea"
        anchors.fill: parent
        active: page.textShown
        visible: active
        focus: page.textShown
        sourceComponent: TextView {
            doc: page.textShown ? Reader.current : null
        }
    }
    // Präsentation bearbeiten (seit 5.0 Beta 4): Menüband, Folie mit Notizen und die Folienleiste
    Loader {
        id: slidesArea
        objectName: "readerSlidesArea"
        anchors.fill: parent
        active: page.slidesShown
        visible: active
        focus: page.slidesShown
        sourceComponent: SlidesView {
            doc: page.slidesShown ? Reader.current : null
        }
    }
    Component {
        id: documentComponent
        Item {
            readonly property var allToolsPanel: allTools
            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                // Die Dokument-Tabs stehen in der Leiste oben (AppTabs). Im Vollbild (F11) nur das Dokument mit den
                // schwebenden Leisten
                // Menüband wie bei Texten und Tabellen (seit 5.0 Beta 3)
                PdfRibbon {
                    id: ribbon
                    Layout.fillWidth: true
                    doc: page.doc
                    view: view
                    tools: allTools
                    visible: !Reader.fullScreen
                    allToolsOpen: allTools.opened
                    onAllToolsRequested: page.toggleAllTools()
                    onSearchRequested: page.showLeft("search")
                    onSettingsRequested: page.toolSettingsOpen = !page.toolSettingsOpen
                }

                Item {
                    id: workspace
                    objectName: "readerWorkspace"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    // Drei Ebenen: links und rechts je eine Seitenleiste mit fester Breite (springt nicht je nach
                    // Inhalt) – geschlossen ganz weg wie die Formatvorlagen bei Texten (ein- und ausgeblendet über das
                    // Menüband) –, dazwischen die Dokumentfläche. Öffnen/Schließen: die Leiste gleitet über ihren Streifen herein bzw. hinaus
                    // (»Reduziert«: blendet, »Aus«: sofort). Die Dokumentfläche nimmt ihre neue Breite einmal an.
                    readonly property bool leftOpen: Reader.leftPanel !== "" && !Reader.fullScreen
                    readonly property bool rightOpen: Reader.rightPanel !== "" && !Reader.fullScreen
                    // Beide Seitenleisten stehen rechts neben dem Streifen mit ihren Symbolen am Fensterrand (wie bei
                    // Texten), immer nur eine zur Zeit; links bleibt die Dokumentfläche frei
                    readonly property int railSpace: Reader.fullScreen ? 0 : Metrics.readerRailWidth
                    readonly property int leftSpace: 0
                    readonly property int rightSpace: railSpace + (Reader.fullScreen || page.narrow || !(leftOpen || rightOpen) ? 0 : Metrics.readerLeftPanelWidth)
                    property real leftShown: leftOpen ? 1 : 0   // 0…1: wie weit die Leiste zu sehen ist
                    property real rightShown: rightOpen ? 1 : 0
                    Behavior on leftShown { enabled: Motion.enabled; NumberAnimation { duration: Motion.moves ? Motion.pane : Motion.fade; easing.type: Motion.decelerate } }
                    Behavior on rightShown { enabled: Motion.enabled; NumberAnimation { duration: Motion.moves ? Motion.pane : Motion.fade; easing.type: Motion.decelerate } }

                    Item {
                        id: center
                        anchors.fill: parent
                        // neue Breite sofort (einmal neu angeordnet, nicht in jedem Bild der Leisten-Animation)
                        anchors.leftMargin: workspace.leftSpace
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
                                PText { anchors.verticalCenter: parent.verticalCenter; text: I18n.tr(page.doc ? page.doc.name : "", I18n.revision) }
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
                            // Seite und Zoom stehen im Menüband – schwebend nur noch im Vollbild
                            visible: Reader.fullScreen && !Reader.organize && !Reader.presenting && page.doc !== null
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
                            SpeechBar { Layout.fillWidth: true }
                            PInfoBar { Layout.fillWidth: true; notice: Notices.area("reader") }
                            PInfoBar {
                                objectName: "readerObjectNotice"
                                Layout.fillWidth: true
                                shown: page.doc !== null && page.doc.tool === "objects" && page.doc.objectMessage !== "" && page.doc.objectMessage !== page.seenObjectMessage
                                severity: "info"
                                message: I18n.tr(page.doc ? page.doc.objectMessage : "", I18n.revision)
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
                                title: I18n.tr("Gescannte Seiten", I18n.revision)
                                message: I18n.tr("Dieses PDF enthält Seiten ohne erkannten Text – Suchen und Kopieren finden darauf nichts.", I18n.revision)
                                actions: ["Text erkennen …"]
                                autoHide: page.noticeTime
                                onActionTriggered: page.doc.recognizeText([])
                                onClosed: {
                                    var next = Object.assign({}, page.dismissedScans)
                                    next[page.doc.docId] = true
                                    page.dismissedScans = next
                                }
                            }
                            // Ansicht einer Office-Datei (seit 5.0): was sie ist, und – bei Tabellen – »Vertragsübersicht erstellen«
                            PInfoBar {
                                objectName: "readerOfficeNotice"
                                readonly property bool sheet: page.doc !== null && /\.(xlsx|xlsm|xls)$/i.test(page.doc.sourcePath)  // nur Excel – wie die Vertragsübersichten
                                Layout.fillWidth: true
                                shown: page.doc !== null && page.doc.sourcePath !== "" && page.doc.officeNote !== "" && !page.dismissedOffice[page.doc.docId]
                                severity: "info"
                                title: I18n.tr("Ansicht", I18n.revision)
                                message: I18n.tr(page.doc ? page.doc.officeNote : "", I18n.revision)
                                actions: sheet ? ["Vertragsübersicht erstellen", "Im Standardprogramm öffnen"] : ["Im Standardprogramm öffnen"]
                                onActionTriggered: (index) => Reader.officeAction(sheet && index === 0 ? "overview" : "external")
                                onClosed: {
                                    var next = Object.assign({}, page.dismissedOffice)
                                    next[page.doc.docId] = true
                                    page.dismissedOffice = next
                                }
                            }
                            PInfoBar {
                                objectName: "readerDocumentNotice"
                                Layout.fillWidth: true
                                shown: page.doc !== null && page.doc.notice !== "" && !page.dismissedNotices[page.doc.docId]
                                severity: page.doc ? page.doc.noticeKind : "info"
                                message: I18n.tr(page.doc ? page.doc.notice : "", I18n.revision)
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
                                title: I18n.tr("PDF hier ablegen", I18n.revision)
                                text: I18n.tr("Jede abgelegte PDF öffnet sich in einem eigenen Tab.", I18n.revision)
                            }
                        }
                    }

                    // »Alle Werkzeuge«: gleitet am linken Rand der Seitenfläche über die Seite
                    AllTools {
                        id: allTools
                        doc: page.doc
                        x: workspace.leftSpace + Metrics.s8
                        y: Metrics.readerViewMargin  // oben bündig mit der Seite
                        height: workspace.height - 2 * Metrics.readerViewMargin
                    }

                    // Streifen mit den Inhalten beider Seitenleisten (über den Leisten, die darunter hereingleiten)
                    SideRail {
                        objectName: "readerSideRail"
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: workspace.railSpace
                        visible: !Reader.fullScreen
                        z: 3
                        current: Reader.leftPanel !== "" ? Reader.leftPanel : Reader.rightPanel
                        accentColor: FileKinds.color("pdf")
                        items: [
                            { key: "thumbs", icon: "document_one_page_multiple", tip: "Seiten", name: "readerRailThumbs" },
                            { key: "outline", icon: "bookmark", tip: "Lesezeichen", name: "readerRailOutline" },
                            { key: "search", icon: "search", tip: "Suchen" + Shortcuts.hints["app.find"], name: "readerRailSearch" },
                            { key: "attachments", icon: "attach", tip: "Anhänge", name: "readerRailAttachments" },
                            { key: "comments", icon: "comment", tip: "Kommentare", name: "readerRailComments", separator: true },
                            { key: "properties", icon: "text_font", tip: "Eigenschaften", name: "readerRailProperties" }
                        ].concat(Assistant.enabled ? [{ key: "assistant", icon: "sparkle", tip: "KI-Assistent", name: "readerRailAssistant" }] : [])
                         .concat(Reader.compareActive ? [{ key: "compare", icon: "branch_compare", tip: "Vergleich", name: "readerRailCompare" }] : [])
                        onSelected: (key) => page.toggleSide(key)
                    }
                    LeftPanel {
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        x: workspace.width - workspace.railSpace - width + (Motion.moves ? (1 - workspace.leftShown) * width : 0)
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
                        x: workspace.width - workspace.railSpace - width + (Motion.moves ? (1 - workspace.rightShown) * width : 0)
                        width: Metrics.readerLeftPanelWidth
                        opacity: Motion.moves ? 1 : workspace.rightShown
                        visible: workspace.rightShown > 0
                        doc: page.doc
                        z: 2
                        PShadow { visible: page.narrow; radius: 0 }
                    }
                }
            }

            // Tastenkürzel (zusätzlich zu Strg+O, Strg+F, F1 und Strg+Eingabe aus dem Fenster)
            Shortcut { sequences: Shortcuts.keys["reader.save"] || []; enabled: page.active && page.editing; onActivated: page.doc.saveDocument() }
            Shortcut { sequences: Shortcuts.keys["reader.saveAs"] || []; enabled: page.active && page.editing; onActivated: page.doc.saveDocumentAs() }
            Shortcut { sequences: Shortcuts.keys["reader.print"] || []; enabled: page.active && page.editing; onActivated: page.doc.printDocument() }
            Shortcut { sequences: Shortcuts.keys["reader.undo"] || []; enabled: page.active && page.editing && view.editing === null; onActivated: page.doc.undo() }
            Shortcut { sequences: Shortcuts.keys["reader.redo"] || []; enabled: page.active && page.editing && view.editing === null; onActivated: page.doc.redo() }
            Shortcut { sequences: Shortcuts.keys["app.closeTab"] || []; enabled: page.active && Reader.hasDocument; onActivated: Reader.closeCurrent() }
            Shortcut { sequences: Shortcuts.keys["reader.fullScreen"] || []; enabled: page.active && page.editing; onActivated: Reader.toggleFullScreen() }
            Shortcut { sequences: Shortcuts.keys["reader.present"] || []; enabled: page.active && page.editing && !Reader.presenting; onActivated: Reader.startPresentation() }
            Shortcut { sequences: Shortcuts.keys["reader.speech"] || []; enabled: page.active && Reader.hasDocument && !Reader.organize; onActivated: Speech.toggle() }
            Shortcut { sequences: Shortcuts.keys["reader.goToPage"] || []; enabled: page.active && page.editing && !Reader.organize; onActivated: Reader.fullScreen ? controls.focusPage() : ribbon.focusPage() }
            Shortcut {
                sequences: Shortcuts.keys["reader.selectAll"] || []
                enabled: page.active && page.editing && !Reader.organize && view.editing === null
                onActivated: {
                    if (page.doc.tool === "objects") page.doc.selectAllObjects(page.doc.currentPage)
                    else page.doc.selectAll(page.doc.currentPage)
                }
            }
            Shortcut { sequences: Shortcuts.keys["reader.nextTab"] || []; enabled: page.active && Reader.tabs.count > 1; onActivated: Reader.activateIndex(1) }
            Shortcut { sequences: Shortcuts.keys["reader.previousTab"] || []; enabled: page.active && Reader.tabs.count > 1; onActivated: Reader.activateIndex(-1) }
            Shortcut { sequences: Shortcuts.keys["reader.zoomIn"] || []; enabled: page.active && page.editing; onActivated: view.smoothly(function() { page.doc.zoomIn() }) }
            Shortcut { sequences: Shortcuts.keys["reader.zoomOut"] || []; enabled: page.active && page.editing; onActivated: view.smoothly(function() { page.doc.zoomOut() }) }
            Shortcut { sequences: Shortcuts.keys["reader.fitPage"] || []; enabled: page.active && page.editing; onActivated: view.smoothly(function() { page.doc.fitPage() }) }
            Shortcut { sequences: Shortcuts.keys["reader.nextHit"] || []; enabled: page.active && page.editing && page.doc.searchCount > 0; onActivated: page.doc.nextHit() }
            Shortcut { sequences: Shortcuts.keys["reader.previousHit"] || []; enabled: page.active && page.editing && page.doc.searchCount > 0; onActivated: page.doc.previousHit() }
            Shortcut { sequences: Shortcuts.keys["reader.copy"] || []; enabled: page.active && page.editing && page.doc.selectionPage >= 0 && page.doc.objectSelection.length === 0; onActivated: page.doc.copySelection() }
            Shortcut {
                sequences: Shortcuts.keys["reader.delete"] || []
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
