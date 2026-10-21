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
            text: I18n.tr("Alle Werkzeuge", I18n.revision)
            tip: I18n.tr("Alle Werkzeuge mit Namen zeigen", I18n.revision)
            toggle: true
            checked: root.allToolsOpen
            enabled: root.doc !== null
            onClicked: root.allToolsRequested()
        }
        Separator {}
        PIconButton { objectName: "readerOpen"; iconName: "folder_open"; tip: I18n.tr("Öffnen" + Shortcuts.hints["app.open"], I18n.revision); onClicked: Reader.openDialog() }
        PIconButton {
            objectName: "readerSave"
            iconName: "save"
            tip: I18n.tr("Speichern" + Shortcuts.hints["reader.save"], I18n.revision)
            enabled: root.doc !== null && !root.doc.busy && (root.doc.dirty || root.doc.path === "")
            busy: root.doc !== null && root.doc.saving
            onClicked: root.doc.saveDocument()
        }
        PIconButton { objectName: "readerPrint"; iconName: "print"; tip: I18n.tr("Drucken" + Shortcuts.hints["reader.print"], I18n.revision); enabled: root.doc !== null; onClicked: root.doc.printDocument() }
        PIconButton { objectName: "readerMail"; iconName: "mail"; tip: I18n.tr("Per E-Mail senden", I18n.revision); enabled: root.doc !== null; onClicked: Reader.sendByMail() }
        Separator {}
        PIconButton {
            objectName: "readerUndo"
            iconName: "arrow_undo"
            tip: I18n.tr((root.doc && root.doc.undoText ? "Rückgängig: " + root.doc.undoText : "Rückgängig") + Shortcuts.hints["reader.undo"], I18n.revision)
            enabled: root.doc !== null && root.doc.undoText !== "" && !root.doc.busy
            onClicked: root.doc.undo()
        }
        PIconButton {
            objectName: "readerRedo"
            iconName: "arrow_redo"
            tip: I18n.tr((root.doc && root.doc.redoText ? "Wiederholen: " + root.doc.redoText : "Wiederholen") + Shortcuts.hints["reader.redo"], I18n.revision)
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
            text: I18n.tr(root.doc === null ? "" : (root.doc.saveState === "saving" ? "Speichern …" : (root.doc.saveState === "saved" ? "Gespeichert" : "")), I18n.revision)
            TextMetrics { id: saveStateWidth; font: Typography.caption; text: I18n.tr("Speichern …", I18n.revision) }
        }

        Item { Layout.fillWidth: true }

        PIconButton { objectName: "readerSearchButton"; iconName: "search"; tip: I18n.tr("Suchen" + Shortcuts.hints["app.find"], I18n.revision); enabled: root.doc !== null; onClicked: root.searchRequested() }
        PIconButton {
            id: viewButton
            objectName: "readerViewMode"
            visible: root.roomy
            iconName: root.doc && root.doc.viewMode === "single" ? "document_one_page" : (root.doc && root.doc.viewMode === "two" ? "book_open" : (root.doc && root.doc.viewMode === "continuousTwo" ? "layout_column_two" : "document_one_page_multiple"))
            tip: I18n.tr("Seitenansicht", I18n.revision)
            onClicked: viewMenu.popup(viewButton, 0, viewButton.height)
        }
        PIconButton {
            objectName: "readerOrganize"
            visible: root.roomy
            iconName: "grid"
            tip: I18n.tr("Seiten organisieren", I18n.revision)
            toggle: true
            checked: Reader.organize
            onClicked: Reader.setOrganize(!Reader.organize)
        }
        PIconButton { id: moreButton; objectName: "readerMore"; iconName: "more_horizontal"; tip: I18n.tr("Weitere Befehle", I18n.revision); onClicked: moreMenu.popup(moreButton, 0, moreButton.height) }
    }

    PMenu {
        id: viewMenu
        PMenuItem { text: I18n.tr("Einzelseite", I18n.revision); iconName: "document_one_page"; onTriggered: root.doc.setViewMode("single") }
        PMenuItem { text: I18n.tr("Fortlaufend", I18n.revision); iconName: "document_one_page_multiple"; onTriggered: root.doc.setViewMode("continuous") }
        PMenuItem { text: I18n.tr("Zwei Seiten", I18n.revision); iconName: "book_open"; onTriggered: root.doc.setViewMode("two") }
        PMenuItem { text: I18n.tr("Fortlaufend, zwei Seiten", I18n.revision); iconName: "layout_column_two"; onTriggered: root.doc.setViewMode("continuousTwo") }
        PMenuItem { objectName: "readerMenuSplit"; text: I18n.tr(Reader.splitKey !== "" ? "Geteilte Ansicht schließen" : "Geteilte Ansicht", I18n.revision); iconName: "layout_column_two"; onTriggered: viewMenu.afterClose = function() { Reader.toggleSplit() } }
        PMenuItem { objectName: "readerMenuPresent"; text: I18n.tr("Präsentation" + Shortcuts.hints["reader.present"], I18n.revision); iconName: "play"; onTriggered: viewMenu.afterClose = function() { Reader.startPresentation() } }
        PMenuItem {
            objectName: "readerNightMode"
            text: I18n.tr(Reader.nightMode ? "Nachtmodus ausschalten" : "Nachtmodus (Seiten dunkel)", I18n.revision)
            iconName: "weather_moon"
            onTriggered: Reader.setNightMode(!Reader.nightMode)
        }
    }
    PMenu {
        id: moreMenu
        PMenuItem { text: I18n.tr("Speichern unter …", I18n.revision); iconName: "save"; enabled: root.doc !== null; onTriggered: root.doc.saveDocumentAs() }
        PMenuItem { text: I18n.tr("Druckvorschau", I18n.revision); iconName: "eye"; enabled: root.doc !== null; onTriggered: root.doc.previewPrint() }
        PMenuItem { text: I18n.tr("Seiten organisieren", I18n.revision); iconName: "grid"; visible: !root.roomy; height: visible ? implicitHeight : 0; onTriggered: Reader.setOrganize(!Reader.organize) }
        PMenuItem { text: I18n.tr("Seitenansicht …", I18n.revision); iconName: "document_one_page_multiple"; visible: !root.roomy; height: visible ? implicitHeight : 0; onTriggered: viewMenu.popup(moreButton, 0, moreButton.height) }
        PMenuItem { objectName: "readerMenuSpeech"; text: I18n.tr((Speech.active ? "Vorlesen beenden" : "Vorlesen") + Shortcuts.hints["reader.speech"], I18n.revision); iconName: "speaker_2"; enabled: root.doc !== null; onTriggered: moreMenu.afterClose = function() { Speech.toggle() } }
        PMenuItem { text: I18n.tr("Eigenschaften", I18n.revision); iconName: "info"; enabled: root.doc !== null; onTriggered: root.doc.showProperties() }
        PMenuItem { text: I18n.tr("Pfad kopieren", I18n.revision); iconName: "copy"; enabled: root.doc !== null && root.doc.path !== ""; onTriggered: App.copyPath(root.doc.path) }
        PMenuItem { text: I18n.tr("Ordner öffnen", I18n.revision); iconName: "folder"; enabled: root.doc !== null && root.doc.path !== ""; onTriggered: Reader.showInFolder(root.doc.path) }
        PMenuItem { text: I18n.tr("Schließen" + Shortcuts.hints["app.closeTab"], I18n.revision); iconName: "dismiss"; enabled: root.doc !== null; onTriggered: Reader.closeCurrent() }
    }
}
