import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Dokument übersetzen« (KI-Assistent, seit 4.0 Beta 6): Zielsprache und Seiten wählen. Das Ergebnis ist ein neues PDF
// mit dem übersetzten Text; das Original bleibt unverändert.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    readonly property var languages: data_.languages || []
    readonly property int pageCount: data_.pageCount || 1
    property string language: ""
    readonly property bool acceptable: language !== ""
    function collect() {
        var first = Math.max(1, Math.min(root.pageCount, parseInt(fromBox.text) || 1))
        var last = Math.max(first, Math.min(root.pageCount, parseInt(toBox.text) || root.pageCount))
        return { "language": root.language, "first": first - 1, "last": last - 1 }
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var data = request.data || {}
        root.language = data.language || ((data.languages || []).length ? data.languages[0].key : "")
        fromBox.text = "1"
        toBox.text = String(data.pageCount || 1)
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: "Der Assistent übersetzt den Text Seite für Seite auf diesem PC und speichert ihn als neues PDF. Das Layout des Originals wird nicht nachgebaut. Je Seite dauert das etwa eine halbe bis zwei Minuten."
    }
    PFieldLabel { text: "Übersetzen ins" }
    Flow {
        Layout.fillWidth: true
        spacing: 4
        Repeater {
            model: root.languages
            PRadioButton {
                required property var modelData
                objectName: "translateLanguage_" + modelData.key
                width: 150
                text: modelData.label
                checked: root.language === modelData.key
                onClicked: root.language = modelData.key
            }
        }
    }
    PFieldLabel { text: "Seiten" }
    RowLayout {
        spacing: 8
        PText { text: "von" }
        PTextField {
            id: fromBox
            objectName: "translateFrom"
            preferredWidth: 64
            label: "Erste Seite"
            validator: IntValidator { bottom: 1; top: root.pageCount }
        }
        PText { text: "bis" }
        PTextField {
            id: toBox
            objectName: "translateTo"
            preferredWidth: 64
            label: "Letzte Seite"
            validator: IntValidator { bottom: 1; top: root.pageCount }
        }
        PText { text: "von " + root.pageCount; tone: "secondary" }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 8
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: "Scans ohne Text erkennt PDF Tool vorher mit der Texterkennung, wenn sie eingerichtet ist. Übersetzungen können Fehler enthalten – wichtige Stellen bitte im Original prüfen."
    }
}
