import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Suchen und schwärzen«: Muster (IBAN mit Prüfziffer, E-Mail-Adressen, Telefonnummern, Datumsangaben) und
// eigene Begriffe – Fundstellen werden zum Schwärzen vorgemerkt und lassen sich vor dem Anwenden prüfen.
ColumnLayout {
    id: root
    objectName: "redactSearchContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    property var kinds: []
    property string scope: "all"
    readonly property bool acceptable: kinds.length > 0 || terms.text.trim() !== ""
    function collect() { return { "kinds": kinds.slice(), "terms": terms.text, "matchCase": matchCase.checked, "scope": scope } }
    function toggle(key, on) {
        var next = kinds.filter(function(item) { return item !== key })
        if (on) next.push(key)
        kinds = next
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        kinds = []
        scope = "all"
        terms.text = ""
        matchCase.checked = false
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: I18n.tr("Gefundene Stellen werden rot umrandet vorgemerkt – noch nichts wird entfernt. Prüfen Sie die Markierungen und wählen Sie dann »Schwärzen anwenden«.", I18n.revision)
    }
    PFieldLabel { text: I18n.tr("Muster", I18n.revision) }
    GridLayout {
        columns: 2
        columnSpacing: 24
        rowSpacing: 0
        Repeater {
            model: [
                { "key": "iban", "label": "IBAN (mit Prüfziffer)" },
                { "key": "email", "label": "E-Mail-Adressen" },
                { "key": "phone", "label": "Telefonnummern" },
                { "key": "date", "label": "Datumsangaben" }
            ]
            PCheckBox {
                required property var modelData
                objectName: "redactKind_" + modelData.key
                text: I18n.tr(modelData.label, I18n.revision)
                checked: root.kinds.indexOf(modelData.key) >= 0
                onToggled: root.toggle(modelData.key, checked)
            }
        }
    }
    PFieldLabel { text: I18n.tr("Eigene Begriffe (einer je Zeile)", I18n.revision) }
    PTextArea {
        id: terms
        objectName: "redactTerms"
        Layout.fillWidth: true
        minLines: 3
        maxLines: 6
        placeholderText: I18n.tr("z. B. Namen, Kundennummern, Adressen", I18n.revision)
        label: I18n.tr("Eigene Begriffe", I18n.revision)
    }
    PCheckBox { id: matchCase; Layout.topMargin: 4; text: I18n.tr("Groß- und Kleinschreibung beachten", I18n.revision) }
    PFieldLabel { text: I18n.tr("Seiten", I18n.revision) }
    RowLayout {
        spacing: 12
        PRadioButton { text: I18n.tr("Alle Seiten (" + (root.data_.pageCount || 0) + ")", I18n.revision); checked: root.scope === "all"; onClicked: root.scope = "all" }
        PRadioButton { text: I18n.tr("Aktuelle Seite (" + ((root.data_.current || 0) + 1) + ")", I18n.revision); checked: root.scope === "current"; onClicked: root.scope = "current" }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 8
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Gesucht wird im Text der Seiten. Gescannte Seiten ohne Text vorher mit »Text erkennen« durchsuchbar machen.", I18n.revision)
    }
}
