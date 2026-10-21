import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Digital signieren« (seit 4.0 Beta 6): Zertifikat wählen (aus Windows oder eine .pfx-Datei mit Kennwort), Grund
// und Ort, auf Wunsch ein sichtbares Feld unten rechts auf einer Seite. Danach fragt Novadesk nach dem Dateinamen der
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
        text: I18n.tr("Die Signatur bestätigt, wer das Dokument unterschrieben hat, und dass es danach nicht verändert wurde. Signiert wird eine Kopie – das Original bleibt unverändert.", I18n.revision)
    }

    PFieldLabel { text: I18n.tr("Zertifikat", I18n.revision) }
    PText {
        visible: root.certificates.length === 0
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: I18n.tr("In Windows ist kein Zertifikat zum Signieren eingerichtet. Wählen Sie eine Zertifikatsdatei (.pfx oder .p12).", I18n.revision)
    }
    Repeater {
        model: root.certificates
        PRadioButton {
            required property var modelData
            required property int index
            objectName: "signCertificate_" + index
            Layout.fillWidth: true
            text: I18n.tr(modelData.subject + "  ·  " + (modelData.selfSigned ? "selbst ausgestellt" : "von " + modelData.issuer) + "  ·  gültig bis " + modelData.until, I18n.revision)
            checked: root.thumbprint === modelData.thumbprint
            onClicked: root.thumbprint = modelData.thumbprint
        }
    }
    PRadioButton {
        objectName: "signUseFile"
        Layout.fillWidth: true
        text: I18n.tr("Zertifikatsdatei (.pfx, .p12)", I18n.revision)
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
            text: I18n.tr(root.file !== "" ? root.file : "Keine Datei gewählt", I18n.revision)
        }
        PButton {
            objectName: "signPickFile"
            text: I18n.tr("Datei wählen …", I18n.revision)
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
        label: I18n.tr("Kennwort der Zertifikatsdatei", I18n.revision)
        placeholderText: I18n.tr("Kennwort der Zertifikatsdatei", I18n.revision)
        echoMode: TextInput.Password
        passwordCharacter: "●"
        inputMethodHints: Qt.ImhHiddenText | Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
    }

    PFieldLabel { text: I18n.tr("Grund (optional)", I18n.revision) }
    PTextField {
        id: reason
        objectName: "signReason"
        Layout.fillWidth: true
        label: I18n.tr("Grund", I18n.revision)
        placeholderText: I18n.tr("z. B. Ich stimme dem Inhalt zu", I18n.revision)
    }
    PFieldLabel { text: I18n.tr("Ort (optional)", I18n.revision) }
    PTextField {
        id: location
        objectName: "signLocation"
        Layout.fillWidth: true
        label: I18n.tr("Ort", I18n.revision)
        placeholderText: I18n.tr("z. B. Köln", I18n.revision)
    }

    RowLayout {
        Layout.topMargin: 12
        spacing: 8
        PCheckBox {
            id: visible_
            objectName: "signVisible"
            text: I18n.tr("Sichtbares Signaturfeld unten rechts auf Seite", I18n.revision)
        }
        PTextField {
            id: pageBox
            objectName: "signPage"
            preferredWidth: 64
            enabled: visible_.checked
            label: I18n.tr("Seite", I18n.revision)
            validator: IntValidator { bottom: 1; top: Math.max(1, root.data_.pageCount || 1) }
        }
        PText { text: I18n.tr("von " + (root.data_.pageCount || 1), I18n.revision); tone: "secondary" }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 4
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Das Feld zeigt Name, Datum und Grund. Ohne sichtbares Feld ist die Signatur nur in der Signaturprüfung zu sehen.", I18n.revision)
    }
}
