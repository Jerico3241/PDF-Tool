import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Befehlsleiste des Readers (seit 4.0 nach Acrobat-Vorbild): links »Alle Werkzeuge«, dann Datei (Öffnen,
// Speichern, Drucken, Per E-Mail senden) und Rückgängig/Wiederholen; rechts Suchen, Ansicht, Seiten
// organisieren und »Mehr«. Die Werkzeuge selbst stehen in den Schnellwerkzeugen am linken Rand der
// Dokumentfläche (QuickTools) und vollständig mit Namen in »Alle Werkzeuge« (AllTools). Bei schmalem Fenster
// wandern Ansicht und Organisieren in »Mehr«. Die Umschalter der Seitenleisten (Seiten, Lesezeichen, Suchen;
// Kommentare, Eigenschaften) sitzen in den Randleisten bei ihrer Seitenleiste.
Rectangle {
    id: root
    objectName: "readerToolbar"
    property var doc: null
    property bool allToolsOpen: false
    signal allToolsRequested()
    signal searchRequested()
    readonly property bool roomy: width >= 760

    implicitHeight: Metrics.readerToolbarHeight
    color: Theme.layer
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.divider }

    component Separator: Rectangle {
        Layout.preferredWidth: 1
        Layout.preferredHeight: 20
        Layout.leftMargin: 4
        Layout.rightMargin: 4
        color: Theme.divider
    }

    RowLayout {
        id: bar
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        spacing: 2

        // »Alle Werkzeuge« mit Namen – wie das Menü »Alle Werkzeuge« bei Acrobat
        PButton {
            objectName: "readerAllTools"
            kind: "subtle"
            iconName: "apps"
            text: "Alle Werkzeuge"
            tip: "Alle Werkzeuge mit Namen zeigen"
            toggle: true
            checked: root.allToolsOpen
            enabled: root.doc !== null
            onClicked: root.allToolsRequested()
        }
        Separator {}
        PIconButton { objectName: "readerOpen"; iconName: "folder_open"; tip: "Öffnen (Strg+O)"; onClicked: Reader.openDialog() }
        PIconButton {
            objectName: "readerSave"
            iconName: "save"
            tip: "Speichern (Strg+S)"
            enabled: root.doc !== null && !root.doc.busy && (root.doc.dirty || root.doc.path === "")
            busy: root.doc !== null && root.doc.saving
            onClicked: root.doc.saveDocument()
        }
        PIconButton { objectName: "readerPrint"; iconName: "print"; tip: "Drucken (Strg+P)"; enabled: root.doc !== null; onClicked: root.doc.printDocument() }
        PIconButton { objectName: "readerMail"; iconName: "mail"; tip: "Per E-Mail senden"; enabled: root.doc !== null; onClicked: Reader.sendByMail() }
        Separator {}
        PIconButton {
            objectName: "readerUndo"
            iconName: "arrow_undo"
            tip: root.doc && root.doc.undoText ? "Rückgängig: " + root.doc.undoText + " (Strg+Z)" : "Rückgängig (Strg+Z)"
            enabled: root.doc !== null && root.doc.undoText !== "" && !root.doc.busy
            onClicked: root.doc.undo()
        }
        PIconButton {
            objectName: "readerRedo"
            iconName: "arrow_redo"
            tip: root.doc && root.doc.redoText ? "Wiederholen: " + root.doc.redoText + " (Strg+Y)" : "Wiederholen (Strg+Y)"
            enabled: root.doc !== null && root.doc.redoText !== "" && !root.doc.busy
            onClicked: root.doc.redo()
        }
        // »Speichern …« → »Gespeichert« (kurz), ohne Dialog; feste Breite: die Leiste springt nicht
        PCrossfadeText {
            objectName: "readerSaveState"
            Layout.leftMargin: 6
            Layout.preferredWidth: saveStateWidth.advanceWidth + 4
            Layout.fillHeight: true
            font: Typography.caption
            color: Theme.textSecondary
            text: root.doc === null ? "" : (root.doc.saveState === "saving" ? "Speichern …" : (root.doc.saveState === "saved" ? "Gespeichert" : ""))
            TextMetrics { id: saveStateWidth; font: Typography.caption; text: "Speichern …" }
        }

        Item { Layout.fillWidth: true }

        PIconButton { objectName: "readerSearchButton"; iconName: "search"; tip: "Suchen (Strg+F)"; enabled: root.doc !== null; onClicked: root.searchRequested() }
        PIconButton {
            id: viewButton
            objectName: "readerViewMode"
            visible: root.roomy
            iconName: root.doc && root.doc.viewMode === "single" ? "document_one_page" : (root.doc && root.doc.viewMode === "two" ? "book_open" : (root.doc && root.doc.viewMode === "continuousTwo" ? "layout_column_two" : "document_one_page_multiple"))
            tip: "Seitenansicht"
            onClicked: viewMenu.popup(viewButton, 0, viewButton.height)
        }
        PIconButton {
            objectName: "readerOrganize"
            visible: root.roomy
            iconName: "grid"
            tip: "Seiten organisieren"
            toggle: true
            checked: Reader.organize
            onClicked: Reader.setOrganize(!Reader.organize)
        }
        PIconButton { id: moreButton; objectName: "readerMore"; iconName: "more_horizontal"; tip: "Weitere Befehle"; onClicked: moreMenu.popup(moreButton, 0, moreButton.height) }
    }

    PMenu {
        id: viewMenu
        PMenuItem { text: "Einzelseite"; iconName: "document_one_page"; onTriggered: root.doc.setViewMode("single") }
        PMenuItem { text: "Fortlaufend"; iconName: "document_one_page_multiple"; onTriggered: root.doc.setViewMode("continuous") }
        PMenuItem { text: "Zwei Seiten"; iconName: "book_open"; onTriggered: root.doc.setViewMode("two") }
        PMenuItem { text: "Fortlaufend, zwei Seiten"; iconName: "layout_column_two"; onTriggered: root.doc.setViewMode("continuousTwo") }
        PMenuItem { objectName: "readerMenuSplit"; text: Reader.splitKey !== "" ? "Geteilte Ansicht schließen" : "Geteilte Ansicht"; iconName: "layout_column_two"; onTriggered: viewMenu.afterClose = function() { Reader.toggleSplit() } }
        PMenuItem { objectName: "readerMenuPresent"; text: "Präsentation (F5)"; iconName: "play"; onTriggered: viewMenu.afterClose = function() { Reader.startPresentation() } }
        PMenuItem {
            objectName: "readerNightMode"
            text: Reader.nightMode ? "Nachtmodus ausschalten" : "Nachtmodus (Seiten dunkel)"
            iconName: "weather_moon"
            onTriggered: Reader.setNightMode(!Reader.nightMode)
        }
    }
    PMenu {
        id: moreMenu
        PMenuItem { text: "Speichern unter …"; iconName: "save"; enabled: root.doc !== null; onTriggered: root.doc.saveDocumentAs() }
        PMenuItem { text: "Druckvorschau"; iconName: "eye"; enabled: root.doc !== null; onTriggered: root.doc.previewPrint() }
        PMenuItem { text: "Seiten organisieren"; iconName: "grid"; visible: !root.roomy; height: visible ? implicitHeight : 0; onTriggered: Reader.setOrganize(!Reader.organize) }
        PMenuItem { text: "Seitenansicht …"; iconName: "document_one_page_multiple"; visible: !root.roomy; height: visible ? implicitHeight : 0; onTriggered: viewMenu.popup(moreButton, 0, moreButton.height) }
        PMenuItem { text: "Eigenschaften"; iconName: "info"; enabled: root.doc !== null; onTriggered: root.doc.showProperties() }
        PMenuItem { text: "Pfad kopieren"; iconName: "copy"; enabled: root.doc !== null && root.doc.path !== ""; onTriggered: App.copyPath(root.doc.path) }
        PMenuItem { text: "Ordner öffnen"; iconName: "folder"; enabled: root.doc !== null && root.doc.path !== ""; onTriggered: Reader.showInFolder(root.doc.path) }
        PMenuItem { text: "Schließen (Strg+W)"; iconName: "dismiss"; enabled: root.doc !== null; onTriggered: Reader.closeCurrent() }
    }
}
