import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »PDF Reader & Editor«: Tabs, Befehlsleiste, Leiste des Werkzeugs, links Miniaturen, Lesezeichen
// oder Suche, in der Mitte die Seiten (oder »Seiten organisieren«), rechts die Kommentare. Ohne
// Dokument: Öffnen und »Zuletzt geöffnet«. In schmalen Fenstern liegen die Seitenleisten über der
// Ansicht. Tastenkürzel gelten nur, solange diese Seite zu sehen ist und kein Dialog offen ist.
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
            readonly property int leftWidth: Reader.leftPanel === "" ? 0 : (Reader.leftPanel === "thumbs" ? Metrics.readerThumbPanelWidth : Metrics.readerPanelWidth)
            readonly property int rightWidth: Reader.rightPanel === "" ? 0 : Metrics.readerPanelWidth

            Item {
                id: center
                anchors.fill: parent
                anchors.leftMargin: page.narrow ? 0 : workspace.leftWidth
                anchors.rightMargin: page.narrow ? 0 : workspace.rightWidth

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

            LeftPanel {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: workspace.leftWidth
                visible: Reader.leftPanel !== ""
                doc: page.doc
                z: 2
                PShadow { visible: page.narrow; radius: 0 }
            }
            Rectangle {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: workspace.rightWidth
                visible: Reader.rightPanel !== ""
                color: Theme.layer
                z: 2
                Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 1; color: Theme.divider }
                PShadow { visible: page.narrow; radius: 0 }
                Loader {
                    anchors.fill: parent
                    anchors.leftMargin: 1
                    active: Reader.rightPanel === "comments"
                    sourceComponent: CommentsPanel { doc: page.doc }
                }
                Loader {
                    anchors.fill: parent
                    anchors.leftMargin: 1
                    active: Reader.rightPanel === "properties"
                    sourceComponent: ObjectPanel { doc: page.doc }
                }
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
