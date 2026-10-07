import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Link setzen oder ändern: Ziel ist eine Seite dieses Dokuments oder eine Webadresse (https://, mailto:).
// Andere Ziele (Programme, Dateien, Skripte) bietet PDF Tool bewusst nicht an.
ColumnLayout {
    id: root
    objectName: "linkContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    property string kind: "page"
    readonly property int pageNumber: parseInt(pageField.text)
    readonly property bool acceptable: kind === "page" ? (pageNumber >= 1 && pageNumber <= (data_.pageCount || 1)) : uriField.text.trim() !== ""
    readonly property bool handlesReturn: true
    function collect() { return { "kind": kind, "page": pageField.text, "uri": uriField.text.trim() } }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var data = request.data || {}
        kind = data.kind === "web" ? "web" : "page"
        pageField.text = String(data.page || 1)
        uriField.text = data.uri || ""
        if (kind === "web") uriField.forceActiveFocus(Qt.OtherFocusReason)
        else pageField.forceActiveFocus(Qt.OtherFocusReason)
    }

    PRadioButton { objectName: "linkKindPage"; text: "Zu einer Seite dieses Dokuments"; checked: root.kind === "page"; onClicked: { root.kind = "page"; pageField.forceActiveFocus() } }
    RowLayout {
        Layout.leftMargin: 28
        spacing: 8
        PText { text: "Seite" }
        PTextField {
            id: pageField
            objectName: "linkPage"
            preferredWidth: 90
            enabled: root.kind === "page"
            label: "Seite"
            validator: IntValidator { bottom: 1; top: 999999 }
            invalid: root.kind === "page" && text !== "" && !root.acceptable
            Keys.onReturnPressed: (event) => { if (root.acceptable) Dialogs.answer(root.request.id, "primary", root.collect()); event.accepted = true }
        }
        PText { text: "von " + (root.data_.pageCount || 1); tone: "secondary" }
    }
    PRadioButton { objectName: "linkKindWeb"; Layout.topMargin: 8; text: "Zu einer Webadresse oder E-Mail-Adresse"; checked: root.kind === "web"; onClicked: { root.kind = "web"; uriField.forceActiveFocus() } }
    PTextField {
        id: uriField
        objectName: "linkUri"
        Layout.fillWidth: true
        Layout.leftMargin: 28
        enabled: root.kind === "web"
        label: "Adresse"
        placeholderText: "https://www.beispiel.de oder name@beispiel.de"
        maximumLength: 2000
        Keys.onReturnPressed: (event) => { if (root.acceptable) Dialogs.answer(root.request.id, "primary", root.collect()); event.accepted = true }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 8
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: "Erlaubt sind Webadressen (http, https) und E-Mail-Adressen. Beim Anklicken fragt PDF Tool nach, bevor eine Webadresse geöffnet wird."
    }
}
