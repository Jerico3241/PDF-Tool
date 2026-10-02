import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »PDF Reader & Editor«: Tabs, Befehlsleiste, Leiste des Werkzeugs; links die Seitenleiste mit Seiten,
// Lesezeichen oder Suche, rechts Kommentare oder Eigenschaften – jeweils mit ihren Umschaltern im
// eigenen Kopf, eingeklappt als schmaler Streifen mit Symbolen –, in der Mitte die Seiten (oder »Seiten
// organisieren«). Ohne Dokument: Öffnen und »Zuletzt geöffnet«. In schmalen Fenstern liegen die
// Seitenleisten über der Ansicht.
// Tastenkürzel gelten nur, solange diese Seite zu sehen ist und kein Dialog offen ist.
FocusScope {
    id: page
    objectName: "readerPage"
    readonly property var doc: Reader.current
    readonly property bool narrow: width < Metrics.readerNarrowFrom
    readonly property bool active: App.currentPage === "reader" && !Dialogs.open
    readonly property bool editing: doc !== null && doc !== undefined
    property var dismissedNotices: ({})
    // Objektmodus: die Eigenschaften öffnen sich mit dem Modus (nicht erst mit der ersten Auswahl – sonst
    // verschöbe sich die Seite unter dem Mauszeiger) und gehen beim Verlassen wieder zu, wenn sie dafür
    // geöffnet wurden. In schmalen Fenstern nie von selbst (dort überdecken sie die Seite).
    property bool propertiesOpenedForObjects: false
    // Linke Seitenleiste mit diesem Inhalt zeigen (Streifen oder Kopf); die Suche bekommt den Fokus
    function showLeft(key) {
        Reader.showLeftPanel(key)
        if (key === "search" && doc) doc.requestSearch()
    }
    readonly property string currentTool: doc ? doc.tool : ""
    onCurrentToolChanged: {
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

    ColumnLayout {
        anchors.fill: parent
        visible: Reader.hasDocument
        spacing: 0

        ReaderTabs { Layout.fillWidth: true }
        ReaderToolbar { Layout.fillWidth: true; doc: page.doc }
        ToolOptions { Layout.fillWidth: true; doc: page.doc }

        Item {
            id: workspace
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            // Drei Ebenen: links und rechts je eine Seitenleiste mit fester Breite (springt nicht je nach
            // Inhalt) – geschlossen ein schmaler Streifen mit ihren Symbolen –, dazwischen die
            // Dokumentfläche. Öffnen/Schließen: die Leiste gleitet über ihren Streifen herein bzw. hinaus
            // (»Reduziert«: blendet, »Aus«: sofort). Die Dokumentfläche nimmt ihre neue Breite einmal an.
            readonly property bool leftOpen: Reader.leftPanel !== ""
            readonly property bool rightOpen: Reader.rightPanel !== ""
            readonly property int leftSpace: page.narrow || !leftOpen ? Metrics.readerRailWidth : Metrics.readerLeftPanelWidth
            readonly property int rightSpace: page.narrow || !rightOpen ? Metrics.readerRailWidth : Metrics.readerRightPanelWidth
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

                DocumentView {
                    id: view
                    anchors.fill: parent
                    doc: page.doc
                    visible: !Reader.organize
                    focus: true
                }
                Loader {
                    anchors.fill: parent
                    active: Reader.organize
                    sourceComponent: OrganizeView { doc: page.doc }
                    onLoaded: item.forceActiveFocus()
                }
                ViewControls {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 16
                    doc: page.doc
                    visible: !Reader.organize && page.doc !== null
                }
                // Hinweise: Meldungen des Readers und Hinweis zum Dokument (signiert, repariert, XFA …)
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: 16
                    anchors.rightMargin: 24
                    spacing: 0
                    PInfoBar { Layout.fillWidth: true; notice: Notices.area("reader") }
                    PInfoBar {
                        objectName: "readerObjectNotice"
                        Layout.fillWidth: true
                        shown: page.doc !== null && page.doc.tool === "objects" && page.doc.objectMessage !== ""
                        severity: "info"
                        message: page.doc ? page.doc.objectMessage : ""
                        closable: false
                    }
                    PInfoBar {
                        objectName: "readerDocumentNotice"
                        Layout.fillWidth: true
                        shown: page.doc !== null && page.doc.notice !== "" && !page.dismissedNotices[page.doc.docId]
                        severity: page.doc ? page.doc.noticeKind : "info"
                        message: page.doc ? page.doc.notice : ""
                        onClosed: {
                            var next = Object.assign({}, page.dismissedNotices)
                            next[page.doc.docId] = true
                            page.dismissedNotices = next
                        }
                    }
                }
                // Arbeit im Hintergrund (Speichern, Text ändern …)
                PProgressBar {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    indeterminate: true
                    visible: page.doc !== null && page.doc.busy
                }
            }

            // Eingeklappte Seitenleisten (bei offener Leiste: deren Hintergrund)
            PanelRail {
                objectName: "readerLeftRail"
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: workspace.leftSpace
                z: 1
                side: "left"
                collapsed: !workspace.leftOpen
                items: [
                    { key: "thumbs", icon: "document_one_page_multiple", tip: "Seiten", name: "readerRailThumbs" },
                    { key: "outline", icon: "bookmark", tip: "Lesezeichen", name: "readerRailOutline" },
                    { key: "search", icon: "search", tip: "Suchen (Strg+F)", name: "readerRailSearch" }
                ]
                onSelected: (key) => page.showLeft(key)
            }
            PanelRail {
                objectName: "readerRightRail"
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: workspace.rightSpace
                z: 1
                side: "right"
                collapsed: !workspace.rightOpen
                items: [
                    { key: "comments", icon: "comment", tip: "Kommentare", name: "readerRailComments" },
                    { key: "properties", icon: "text_font", tip: "Eigenschaften", name: "readerRailProperties" }
                ]
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
    Shortcut { sequence: "Ctrl+Tab"; enabled: page.active && Reader.tabs.count > 1; onActivated: Reader.activateIndex(1) }
    Shortcut { sequence: "Ctrl+Shift+Tab"; enabled: page.active && Reader.tabs.count > 1; onActivated: Reader.activateIndex(-1) }
    Shortcut { sequences: [StandardKey.ZoomIn, "Ctrl+="]; enabled: page.active && page.editing; onActivated: page.doc.zoomIn() }
    Shortcut { sequences: [StandardKey.ZoomOut]; enabled: page.active && page.editing; onActivated: page.doc.zoomOut() }
    Shortcut { sequence: "Ctrl+0"; enabled: page.active && page.editing; onActivated: page.doc.fitPage() }
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
