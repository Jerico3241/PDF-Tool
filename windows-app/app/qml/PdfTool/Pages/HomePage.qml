import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Startseite: Auswahl der Werkzeuge.
PPage {
    id: page
    objectName: "homePage"
    title: App.appName
    subtitle: "Werkzeuge für PDF-Dateien – wählen Sie, was Sie erledigen möchten."

    GridLayout {
        Layout.fillWidth: true
        columns: page.columns
        columnSpacing: 12
        rowSpacing: 12
        Repeater {
            model: App.tools
            PToolCard {
                required property var modelData
                objectName: "toolCard_" + modelData.key
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                iconName: modelData.icon
                title: modelData.title
                description: modelData.description
                shortcut: modelData.shortcut
                onClicked: App.openTool(modelData.key)
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: 20
        spacing: 8
        PIcon {
            name: "shield"
            color: Theme.textSecondary
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 1
        }
        PText {
            text: "Alle Dateien werden lokal auf diesem PC verarbeitet. Es wird nichts hochgeladen."
            textStyle: "caption"
            tone: "secondary"
            wrap: true
            Layout.fillWidth: true
        }
    }
}
