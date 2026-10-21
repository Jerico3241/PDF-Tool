import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Kennwortschutz«: ein Kennwort zum Öffnen und/oder Einschränkungen (Drucken, Kopieren, Ändern …) mit einem
// eigenen Berechtigungskennwort – oder den Schutz entfernen. Verschlüsselt wird mit AES-256 beim nächsten
// Speichern. Kennwörter stehen nur in diesem Dialog und im Arbeitsspeicher; die Felder zeigen Punkte und
// erlauben kein Kopieren.
ColumnLayout {
    id: root
    objectName: "protectContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    property string mode: "set"  // set oder remove
    property bool openLock: false
    property bool restrict: false
    property var rights: ({ "print": true, "copy": true, "edit": true, "annotate": true, "fill": true, "assemble": true })
    readonly property string problem: {
        if (mode === "remove") return ""
        if (!openLock && !restrict) return "Bitte ein Kennwort zum Öffnen oder Einschränkungen wählen."
        if (openLock && userField.text.length < 4) return "Das Kennwort zum Öffnen braucht mindestens 4 Zeichen."
        if (openLock && userField.text !== userRepeat.text) return "Die beiden Kennwörter zum Öffnen stimmen nicht überein."
        if (restrict && ownerField.text.length < 4) return "Das Berechtigungskennwort braucht mindestens 4 Zeichen."
        if (restrict && ownerField.text !== ownerRepeat.text) return "Die beiden Berechtigungskennwörter stimmen nicht überein."
        if (restrict && openLock && ownerField.text === userField.text) return "Das Berechtigungskennwort muss sich vom Kennwort zum Öffnen unterscheiden."
        return ""
    }
    readonly property bool acceptable: problem === ""
    function collect() {
        if (mode === "remove") return { "mode": "remove" }
        var result = { "mode": "set", "userPassword": openLock ? userField.text : "", "ownerPassword": restrict ? ownerField.text : "" }
        for (var key in rights) result[key] = restrict ? rights[key] : true
        return result
    }
    function setRight(key, value) {
        var next = Object.assign({}, rights)
        next[key] = value
        rights = next
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var data = request.data || {}
        var current = data.rights || {}
        mode = "set"
        openLock = !data["protected"]
        restrict = data.restricted === true
        rights = { "print": current["print"] !== false, "copy": current.copy !== false, "edit": current.edit !== false, "annotate": current.annotate !== false, "fill": current.fill_forms !== false, "assemble": current.assemble !== false }
        userField.text = ""
        userRepeat.text = ""
        ownerField.text = ""
        ownerRepeat.text = ""
    }

    component Secret: PTextField {
        Layout.fillWidth: true
        echoMode: TextInput.Password
        passwordCharacter: "●"
        inputMethodHints: Qt.ImhHiddenText | Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: I18n.tr(root.data_["protected"] ? "Dieses Dokument ist geschützt. Neue Kennwörter ersetzen die bisherigen; die Datei ändert sich erst beim Speichern." : "Der Schutz gilt ab dem nächsten Speichern. Ein vergessenes Kennwort lässt sich nicht wiederherstellen – auch nicht mit PDF Tool.", I18n.revision)
    }
    ColumnLayout {
        visible: root.data_["protected"] === true
        spacing: 0
        Layout.topMargin: 8
        PRadioButton { objectName: "protectModeSet"; text: I18n.tr("Schutz ändern", I18n.revision); checked: root.mode === "set"; onClicked: root.mode = "set" }
        PRadioButton { objectName: "protectModeRemove"; text: I18n.tr("Kennwortschutz entfernen", I18n.revision); checked: root.mode === "remove"; onClicked: root.mode = "remove" }
    }

    ColumnLayout {
        Layout.fillWidth: true
        enabled: root.mode === "set"
        opacity: enabled ? 1 : 0.5
        spacing: 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }

        PCheckBox {
            objectName: "protectOpen"
            Layout.topMargin: 12
            Layout.fillWidth: true
            text: I18n.tr("Zum Öffnen ein Kennwort verlangen", I18n.revision)
            checked: root.openLock
            onToggled: root.openLock = checked
        }
        GridLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 28
            visible: root.openLock
            columns: 2
            columnSpacing: 8
            Secret { id: userField; objectName: "protectUserPassword"; label: I18n.tr("Kennwort zum Öffnen", I18n.revision); placeholderText: I18n.tr("Kennwort", I18n.revision) }
            Secret { id: userRepeat; objectName: "protectUserRepeat"; label: I18n.tr("Kennwort wiederholen", I18n.revision); placeholderText: I18n.tr("Erneut eingeben", I18n.revision) }
        }

        PCheckBox {
            objectName: "protectRestrict"
            Layout.topMargin: 12
            Layout.fillWidth: true
            text: I18n.tr("Drucken, Kopieren und Ändern einschränken", I18n.revision)
            checked: root.restrict
            onToggled: root.restrict = checked
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 28
            visible: root.restrict
            spacing: 0
            PText { text: I18n.tr("Erlaubt bleiben:", I18n.revision); textStyle: "caption"; tone: "secondary"; Layout.topMargin: 4 }
            GridLayout {
                columns: 2
                columnSpacing: 16
                rowSpacing: 0
                Repeater {
                    model: [
                        { "key": "print", "label": "Drucken" },
                        { "key": "copy", "label": "Text und Bilder kopieren" },
                        { "key": "edit", "label": "Inhalt ändern" },
                        { "key": "annotate", "label": "Kommentieren" },
                        { "key": "fill", "label": "Formulare ausfüllen" },
                        { "key": "assemble", "label": "Seiten einfügen, löschen, drehen" }
                    ]
                    PCheckBox {
                        required property var modelData
                        objectName: "protectRight_" + modelData.key
                        text: I18n.tr(modelData.label, I18n.revision)
                        checked: root.rights[modelData.key] === true
                        onToggled: root.setRight(modelData.key, checked)
                    }
                }
            }
            GridLayout {
                Layout.fillWidth: true
                Layout.topMargin: 8
                columns: 2
                columnSpacing: 8
                Secret { id: ownerField; objectName: "protectOwnerPassword"; label: I18n.tr("Berechtigungskennwort", I18n.revision); placeholderText: I18n.tr("Berechtigungskennwort", I18n.revision) }
                Secret { id: ownerRepeat; objectName: "protectOwnerRepeat"; label: I18n.tr("Berechtigungskennwort wiederholen", I18n.revision); placeholderText: I18n.tr("Erneut eingeben", I18n.revision) }
            }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 4
                wrap: true
                textStyle: "caption"
                tone: "secondary"
                text: I18n.tr("Wer das Berechtigungskennwort kennt, kann die Einschränkungen aufheben. Viele Programme halten sich an sie – ein echter Schutz ist nur das Kennwort zum Öffnen.", I18n.revision)
            }
        }
    }
    PText {
        objectName: "protectProblem"
        Layout.fillWidth: true
        Layout.topMargin: 12
        visible: root.problem !== "" && (userField.text !== "" || ownerField.text !== "" || (!root.openLock && !root.restrict))
        wrap: true
        tone: "warning"
        text: I18n.tr(root.problem, I18n.revision)
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 12
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Verschlüsselung: AES-256. Kennwörter werden weder gespeichert noch protokolliert.", I18n.revision)
    }
}
