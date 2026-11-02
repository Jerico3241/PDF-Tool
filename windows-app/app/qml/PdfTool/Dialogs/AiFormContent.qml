import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Formular mit KI ausfüllen« (seit 5.0 Beta 8): Angaben als freien Text eingeben, einfügen oder aus einer Datei laden.
// Der Assistent ordnet sie den Feldern zu; danach zeigt Novadesk jeden Vorschlag zum Prüfen – nichts wird ungefragt
// eingetragen.
ColumnLayout {
    id: root
    objectName: "aiFormContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    readonly property bool acceptable: field.text.trim() !== ""
    function collect() { return { "data": field.text } }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        field.text = ""
        field.area.forceActiveFocus(Qt.OtherFocusReason)
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: I18n.tr("Das Formular hat " + (root.data_.count || 0) + " Felder. Geben Sie die Angaben ein – in beliebiger Form, etwa »Name: Anna Berger, geboren 3.5.1985, wohnt Hauptstraße 4 in Köln«.", I18n.revision)
    }
    PFieldLabel { text: I18n.tr("Felder", I18n.revision) }
    PText {
        objectName: "aiFormFields"
        Layout.fillWidth: true
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        maximumLineCount: 3
        elide: Text.ElideRight
        text: I18n.tr((root.data_.fields || []).join(" · ") + ((root.data_.more || 0) > 0 ? " und " + root.data_.more + " weitere" : ""), I18n.revision)
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: 12
        PFieldLabel { first: true; text: I18n.tr("Angaben", I18n.revision); Layout.fillWidth: true }
        PButton {
            objectName: "aiFormLoad"
            kind: "subtle"
            iconName: "folder_open"
            text: I18n.tr("Aus Datei laden …", I18n.revision)
            tip: I18n.tr("Angaben aus einer Text-, Word- oder PDF-Datei übernehmen", I18n.revision)
            onClicked: {
                var value = Assistant.pickDataFile()
                if (value !== "") field.text = value
            }
        }
    }
    PTextArea {
        id: field
        objectName: "aiFormData"
        Layout.fillWidth: true
        Layout.topMargin: 4
        minLines: 6
        maxLines: 12
        label: I18n.tr("Angaben", I18n.revision)
        placeholderText: I18n.tr("Name, Anschrift, Geburtsdatum, Kundennummer …", I18n.revision)
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 8
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Läuft nur auf diesem PC. Sie sehen jeden Vorschlag, bevor er eingetragen wird.", I18n.revision)
    }
}
