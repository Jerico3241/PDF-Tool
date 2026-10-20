import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Digital signieren« (seit 4.0 Beta 6): Zertifikat wählen (aus Windows oder eine .pfx-Datei mit Kennwort), Grund
// und Ort, auf Wunsch ein sichtbares Feld unten rechts auf einer Seite. Danach fragt PDF Tool nach dem Dateinamen der
// signierten Kopie.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    readonly property var certificates: data_.certificates || []
    property string thumbprint: ""   // gewähltes Zertifikat aus Windows ("" = Datei)
    property string file: ""
    readonly property bool useFile: thumbprint === ""
    readonly property bool acceptable: useFile ? file !== "" : thumbprint !== ""
    function collect() {
        return { "thumbprint": root.thumbprint, "file": root.useFile ? root.file : "", "password": root.useFile ? password.text : "",
                 "reason": reason.text, "location": location.text, "visible": visible_.checked, "page": Math.max(1, Math.min(root.data_.pageCount || 1, parseInt(pageBox.text) || 1)) - 1 }
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var data = request.data || {}
        var list = data.certificates || []
        var wanted = data.thumbprint || ""
        var found = list.some(function(item) { return item.thumbprint === wanted })
        root.thumbprint = found ? wanted : (list.length ? list[0].thumbprint : "")
        root.file = ""
        password.text = ""
        reason.text = data.reason || ""
        location.text = data.location || ""
        visible_.checked = data.visible !== false
        pageBox.text = String((data.current || 0) + 1)
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: "Die Signatur bestätigt, wer das Dokument unterschrieben hat, und dass es danach nicht verändert wurde. Signiert wird eine Kopie – das Original bleibt unverändert."
    }

    PFieldLabel { text: "Zertifikat" }
    PText {
        visible: root.certificates.length === 0
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: "In Windows ist kein Zertifikat zum Signieren eingerichtet. Wählen Sie eine Zertifikatsdatei (.pfx oder .p12)."
    }
    Repeater {
        model: root.certificates
        PRadioButton {
            required property var modelData
            required property int index
            objectName: "signCertificate_" + index
            Layout.fillWidth: true
            text: modelData.subject + "  ·  " + (modelData.selfSigned ? "selbst ausgestellt" : "von " + modelData.issuer) + "  ·  gültig bis " + modelData.until
            checked: root.thumbprint === modelData.thumbprint
            onClicked: root.thumbprint = modelData.thumbprint
        }
    }
    PRadioButton {
        objectName: "signUseFile"
        Layout.fillWidth: true
        text: "Zertifikatsdatei (.pfx, .p12)"
        checked: root.useFile
        onClicked: root.thumbprint = ""
    }
    RowLayout {
        visible: root.useFile
        Layout.fillWidth: true
        Layout.leftMargin: 28
        spacing: 8
        PText {
            objectName: "signFileName"
            Layout.fillWidth: true
            elide: Text.ElideMiddle
            tone: root.file !== "" ? "primary" : "tertiary"
            text: root.file !== "" ? root.file : "Keine Datei gewählt"
        }
        PButton {
            objectName: "signPickFile"
            text: "Datei wählen …"
            iconName: "folder_open"
            onClicked: {
                var path = Reader.current ? Reader.current.pickCertificateFile() : ""
                if (path !== "") root.file = path
            }
        }
    }
    PTextField {
        id: password
        objectName: "signPassword"
        visible: root.useFile
        Layout.fillWidth: true
        Layout.leftMargin: 28
        Layout.topMargin: 4
        label: "Kennwort der Zertifikatsdatei"
        placeholderText: "Kennwort der Zertifikatsdatei"
        echoMode: TextInput.Password
        passwordCharacter: "●"
        inputMethodHints: Qt.ImhHiddenText | Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
    }

    PFieldLabel { text: "Grund (optional)" }
    PTextField {
        id: reason
        objectName: "signReason"
        Layout.fillWidth: true
        label: "Grund"
        placeholderText: "z. B. Ich stimme dem Inhalt zu"
    }
    PFieldLabel { text: "Ort (optional)" }
    PTextField {
        id: location
        objectName: "signLocation"
        Layout.fillWidth: true
        label: "Ort"
        placeholderText: "z. B. Köln"
    }

    RowLayout {
        Layout.topMargin: 12
        spacing: 8
        PCheckBox {
            id: visible_
            objectName: "signVisible"
            text: "Sichtbares Signaturfeld unten rechts auf Seite"
        }
        PTextField {
            id: pageBox
            objectName: "signPage"
            preferredWidth: 64
            enabled: visible_.checked
            label: "Seite"
            validator: IntValidator { bottom: 1; top: Math.max(1, root.data_.pageCount || 1) }
        }
        PText { text: "von " + (root.data_.pageCount || 1); tone: "secondary" }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 4
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: "Das Feld zeigt Name, Datum und Grund. Ohne sichtbares Feld ist die Signatur nur in der Signaturprüfung zu sehen."
    }
}
