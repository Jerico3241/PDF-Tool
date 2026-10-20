import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Einen Namen eingeben (Vorlage oder Regelwerk anlegen, umbenennen). Eingabe bestätigt, sobald
// das Feld nicht leer ist; der vorhandene Name ist markiert und wird beim Tippen ersetzt.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    readonly property bool acceptable: field.text.trim() !== ""
    readonly property bool handlesReturn: true
    function collect() { return { "value": field.text } }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return  // gleiche Anfrage: Eingabe bleibt
        shownId = request.id
        // Direkt aus der Anfrage lesen: »data_« folgt ihr erst nach diesem Signal
        var data = request.data || {}
        field.text = data.value || ""
        field.selectAll()
        field.forceActiveFocus(Qt.OtherFocusReason)
    }

    PFieldLabel { text: I18n.tr(root.data_.label || "Name", I18n.revision); first: true }
    PTextField {
        id: field
        objectName: "dialogTextInput"
        Layout.fillWidth: true
        label: I18n.tr(root.data_.label || "Name", I18n.revision)
        placeholderText: I18n.tr(root.data_.placeholder || "", I18n.revision)
        focus: true
        maximumLength: 120
        Keys.onReturnPressed: (event) => {
            if (root.acceptable) Dialogs.answer(root.request.id, "primary", root.collect())
            event.accepted = true
        }
        Keys.onEnterPressed: (event) => {
            if (root.acceptable) Dialogs.answer(root.request.id, "primary", root.collect())
            event.accepted = true
        }
    }
    PText {
        text: I18n.tr(root.data_.hint || "", I18n.revision)
        visible: text !== ""
        textStyle: "caption"
        tone: "secondary"
        wrap: true
        Layout.fillWidth: true
        Layout.topMargin: 8
    }
}
