import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Passwort eines PDFs eingeben. Das Passwort bleibt nur im Arbeitsspeicher – es wird weder
// gespeichert noch protokolliert; das Feld zeigt nur Punkte und erlaubt kein Kopieren.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    readonly property bool acceptable: field.text !== ""
    readonly property bool handlesReturn: true
    function collect() { return { "value": field.text } }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        field.text = ""
        field.forceActiveFocus(Qt.OtherFocusReason)
    }

    PFieldLabel { text: root.data_.label || "Passwort"; first: true }
    PTextField {
        id: field
        objectName: "dialogPassword"
        Layout.fillWidth: true
        label: root.data_.label || "Passwort"
        echoMode: TextInput.Password
        passwordCharacter: "●"
        inputMethodHints: Qt.ImhHiddenText | Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
        focus: true
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
        text: "Das Passwort wird nur für dieses Dokument im Arbeitsspeicher gehalten und nirgends gespeichert."
        textStyle: "caption"
        tone: "secondary"
        wrap: true
        Layout.fillWidth: true
        Layout.topMargin: 8
    }
}
