import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Ohne geöffnetes Dokument: PDF öffnen (Schaltfläche oder hineinziehen) und »Zuletzt geöffnet«.
// Die Liste enthält nur Pfade (keine Inhalte) und lässt sich leeren.
PPage {
    id: page
    objectName: "readerStart"
    title: "PDF Reader & Editor"
    subtitle: "PDFs öffnen, bearbeiten, organisieren und kommentieren."

    PDropZone {
        objectName: "readerDropZone"
        Layout.fillWidth: true
        Layout.preferredHeight: 220
        highlighted: Reader.dropHighlight
        iconName: "document_pdf"
        title: Reader.opening > 0 ? "Wird geöffnet …" : "PDF hierher ziehen"
        text: "oder eine Datei auswählen. Mehrere PDFs öffnen sich in eigenen Tabs."
        actions: [
            PButton {
                objectName: "readerOpenButton"
                kind: "accent"
                iconName: "folder_open"
                text: "PDF öffnen"
                tip: "Strg+O"
                busy: Reader.opening > 0
                onClicked: Reader.openDialog()
            }
        ]
    }

    PCard {
        objectName: "readerRecent"
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: "Zuletzt geöffnet"
        iconName: "history"
        headerRight: PButton {
            kind: "subtle"
            iconName: "delete"
            text: "Liste leeren"
            visible: Reader.recent.length > 0
            onClicked: Reader.clearRecent()
        }
        PText {
            Layout.fillWidth: true
            visible: Reader.recent.length === 0
            text: "Noch keine Dateien geöffnet."
            tone: "secondary"
        }
        Repeater {
            model: Reader.recent
            Item {
                id: entry
                required property var modelData
                required property int index
                Layout.fillWidth: true
                implicitHeight: 52
                Accessible.role: Accessible.ListItem
                Accessible.name: modelData.name
                PListItem { anchors.fill: parent; hovered: hover.hovered && !entry.modelData.missing }
                HoverHandler { id: hover }
                TapHandler { enabled: !entry.modelData.missing; onTapped: Reader.openRecent(entry.modelData.path) }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 4
                    spacing: 12
                    PIcon { name: entry.modelData.missing ? "document_dismiss" : "document_pdf"; color: entry.modelData.missing ? Theme.textTertiary : Theme.accent; size: Metrics.iconSizeMedium }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        PText { Layout.fillWidth: true; text: entry.modelData.name; tone: entry.modelData.missing ? "tertiary" : "" ; elide: Text.ElideMiddle }
                        PText { Layout.fillWidth: true; text: entry.modelData.missing ? "Nicht mehr vorhanden – " + entry.modelData.folder : entry.modelData.folder; textStyle: "caption"; tone: "secondary"; elide: Text.ElideMiddle }
                    }
                    PIconButton { iconName: "dismiss"; tip: "Aus der Liste entfernen"; onClicked: Reader.removeRecent(entry.modelData.path) }
                }
            }
        }
    }
    PInfoBar { Layout.fillWidth: true; notice: Notices.area("reader") }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 12
        text: "Alle Dateien bleiben auf diesem PC. PDF-JavaScript wird nie ausgeführt. Gespeichert wird erst nach einer Prüfung der neuen Datei – das Original bleibt bei einem Fehler unverändert."
        textStyle: "caption"
        tone: "secondary"
        wrap: true
    }
}
