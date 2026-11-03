import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Text schreiben lassen« (KI, seit 5.0 Beta 8): Auftrag eingeben – Beispiele füllen das Feld. Der Text erscheint im
// Gespräch des Assistenten und lässt sich dort an der Schreibmarke einfügen.
ColumnLayout {
    id: root
    objectName: "aiWriteContent"
    property var request: ({})
    readonly property bool acceptable: field.text.trim() !== ""
    function collect() { return { "instruction": field.text } }
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
        text: I18n.tr("Beschreiben Sie, was der Assistent schreiben soll. Er schreibt passend zum Text vor der Schreibmarke. Namen, Zahlen und Daten, die er nicht kennt, setzt er als [Platzhalter].", I18n.revision)
    }
    PFieldLabel { text: I18n.tr("Auftrag", I18n.revision) }
    PTextArea {
        id: field
        objectName: "aiWriteInstruction"
        Layout.fillWidth: true
        minLines: 3
        maxLines: 6
        label: I18n.tr("Auftrag", I18n.revision)
        placeholderText: I18n.tr("Zum Beispiel: Eine kurze Einladung zum Sommerfest am Freitag", I18n.revision)
    }
    PFieldLabel { text: I18n.tr("Beispiele", I18n.revision) }
    Flow {
        Layout.fillWidth: true
        spacing: 6
        Repeater {
            model: [
                "Eine freundliche Absage auf eine Bewerbung", "Eine Einleitung für diesen Bericht", "Eine Zusammenfassung in drei Sätzen",
                "Eine höfliche Zahlungserinnerung", "Einen Abschlussabsatz mit Dank"
            ]
            PButton {
                required property var modelData
                implicitHeight: 28
                leftPadding: 10
                rightPadding: 10
                text: I18n.tr(modelData, I18n.revision)
                onClicked: { field.text = I18n.tr(modelData, I18n.revision); field.area.forceActiveFocus() }
            }
        }
    }
}
