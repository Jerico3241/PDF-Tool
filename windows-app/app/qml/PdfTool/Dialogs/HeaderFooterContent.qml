import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Kopf- und Fußzeile, Seitenzahlen«: je drei Felder oben und unten (links, Mitte, rechts) mit Platzhaltern für
// Seitenzahl, Seitenanzahl, Datum, Dateiname und Bates-Nummer; Schrift, Größe, Farbe, Abstand zum Rand, erste
// Seitenzahl und welche Seiten. Die kleine Seite rechts zeigt, wie es auf der ersten Seite aussieht.
ColumnLayout {
    id: root
    objectName: "headerFooterContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    readonly property var positions: ["tl", "tc", "tr", "bl", "bc", "br"]
    property var texts: ({ "tl": "", "tc": "", "tr": "", "bl": "", "bc": "", "br": "" })
    property string font: "Helvetica"
    property real size: 9
    property string color: "#000000"
    property real marginMm: 10
    property string scope: "all"
    property bool replace: true
    property var lastField: null
    readonly property bool usesBates: {
        for (var key in texts) if (texts[key].indexOf("{bates}") >= 0) return true
        return false
    }
    readonly property bool hasText: {
        for (var key in texts) if (texts[key].trim() !== "") return true
        return false
    }
    readonly property bool acceptable: hasText && (scope === "all" || rangeField.text.trim() !== "")
    function collect() {
        return {
            "items": Object.assign({}, texts), "font": font, "size": size, "color": color, "margin": marginMm * 72 / 25.4,
            "start": parseInt(startField.text) || 1, "pages": scope === "all" ? "" : rangeField.text,
            "batesPrefix": batesPrefix.text, "batesDigits": batesDigits.currentValue || 6, "batesStart": parseInt(batesStart.text) || 1, "batesSuffix": batesSuffix.text,
            "replace": replace
        }
    }
    function setText(key, value) {
        var next = Object.assign({}, texts)
        next[key] = value
        texts = next
    }
    function preview(value) {
        var bates = batesPrefix.text + String(parseInt(batesStart.text) || 1).padStart(batesDigits.currentValue || 6, "0") + batesSuffix.text
        var start = parseInt(startField.text) || 1
        return value.replace(/\{seite\}/gi, String(start)).replace(/\{seiten\}/gi, String(start + (data_.pageCount || 1) - 1))
                    .replace(/\{datum\}/gi, Qt.formatDate(new Date(), "dd.MM.yyyy")).replace(/\{datei\}/gi, data_.name || "Dokument").replace(/\{bates\}/gi, bates)
    }
    function applyPreset(index) {
        var presets = [
            {},
            { "bc": "Seite {seite} von {seiten}" },
            { "br": "{seite}" },
            { "tr": "{datum}", "bc": "Seite {seite} von {seiten}" },
            { "tl": "{datei}", "br": "Seite {seite}" },
            { "br": "{bates}" }
        ]
        if (index <= 0) return
        var next = { "tl": "", "tc": "", "tr": "", "bl": "", "bc": "", "br": "" }
        var chosen = presets[index]
        for (var key in chosen) next[key] = chosen[key]
        texts = next
    }
    function insert(token) {
        var field = lastField || fieldBc
        var position = field.cursorPosition
        field.insert(position, token)
        field.forceActiveFocus()
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        texts = { "tl": "", "tc": "", "tr": "", "bl": "", "bc": "Seite {seite} von {seiten}", "br": "" }
        scope = "all"
        replace = true
        startField.text = "1"
        rangeField.text = ""
    }

    component PositionField: PTextField {
        id: slotField
        property string key: ""
        Layout.fillWidth: true
        preferredWidth: 150
        text: root.texts[key] || ""
        onTextEdited: root.setText(key, text)
        onActiveFocusChanged: if (activeFocus) root.lastField = slotField
        objectName: "headerFooter_" + key
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 16
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            PFieldLabel { text: "Vorlage"; first: true }
            PComboBox {
                objectName: "headerFooterPreset"
                Layout.fillWidth: true
                label: "Vorlage"
                model: ["Eigene Angaben", "Seite 1 von 3 – unten Mitte", "Seitenzahl – unten rechts", "Datum oben rechts, Seitenzahl unten", "Dateiname oben links, Seitenzahl unten rechts", "Bates-Nummer – unten rechts"]
                onActivated: (index) => root.applyPreset(index)
            }
            PFieldLabel { text: "Kopfzeile (links · Mitte · rechts)" }
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                PositionField { key: "tl"; placeholderText: "links" }
                PositionField { key: "tc"; placeholderText: "Mitte" }
                PositionField { key: "tr"; placeholderText: "rechts" }
            }
            PFieldLabel { text: "Fußzeile (links · Mitte · rechts)" }
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                PositionField { key: "bl"; placeholderText: "links" }
                PositionField { id: fieldBc; key: "bc"; placeholderText: "Mitte" }
                PositionField { key: "br"; placeholderText: "rechts" }
            }
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 8
                spacing: 6
                Repeater {
                    model: [
                        { "token": "{seite}", "label": "Seitenzahl" },
                        { "token": "{seiten}", "label": "Seitenanzahl" },
                        { "token": "{datum}", "label": "Datum" },
                        { "token": "{datei}", "label": "Dateiname" },
                        { "token": "{bates}", "label": "Bates-Nummer" }
                    ]
                    PButton {
                        required property var modelData
                        kind: "subtle"
                        iconName: "add"
                        text: modelData.label
                        tip: "Platzhalter " + modelData.token + " an der Schreibmarke einfügen"
                        onClicked: root.insert(modelData.token)
                    }
                }
            }
        }
        // Vorschau der ersten Seite
        Rectangle {
            objectName: "headerFooterPreview"
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 4
            implicitWidth: 150
            implicitHeight: 212
            color: Theme.paper
            border.color: Theme.border
            radius: 2
            Repeater {
                model: root.positions
                Text {
                    required property string modelData
                    readonly property bool atTop: modelData[0] === "t"
                    readonly property string side: modelData[1]
                    width: parent.width - 12
                    x: 6
                    y: atTop ? 6 : parent.height - height - 6
                    horizontalAlignment: side === "l" ? Text.AlignLeft : (side === "c" ? Text.AlignHCenter : Text.AlignRight)
                    text: root.preview(root.texts[modelData] || "")
                    font.pixelSize: Math.max(5, root.size * 0.62)
                    font.bold: root.font.indexOf("Bold") >= 0
                    font.family: root.font.indexOf("Times") === 0 ? "Times New Roman" : (root.font === "Courier" ? "Courier New" : "Arial")
                    color: root.color
                    elide: Text.ElideRight
                }
            }
            Column {
                anchors.centerIn: parent
                spacing: 6
                Repeater {
                    model: 9
                    Rectangle { width: 96 - (index % 3) * 14; height: 3; radius: 1.5; color: "#E3E3E3" }
                }
            }
        }
    }

    GridLayout {
        Layout.fillWidth: true
        Layout.topMargin: 8
        columns: 4
        columnSpacing: 8
        rowSpacing: 0
        PFieldLabel { text: "Schrift" }
        PFieldLabel { text: "Größe" }
        PFieldLabel { text: "Randabstand" }
        PFieldLabel { text: "Beginnt bei" }
        PComboBox {
            objectName: "headerFooterFont"
            Layout.fillWidth: true
            label: "Schrift"
            model: [{ "label": "Helvetica", "value": "Helvetica" }, { "label": "Helvetica fett", "value": "Helvetica-Bold" }, { "label": "Times", "value": "Times-Roman" }, { "label": "Times fett", "value": "Times-Bold" }, { "label": "Courier", "value": "Courier" }]
            textRole: "label"
            valueRole: "value"
            onActivated: (index) => root.font = model[index].value
        }
        PComboBox {
            Layout.fillWidth: true
            label: "Größe"
            model: [{ "label": "7 pt", "value": 7 }, { "label": "8 pt", "value": 8 }, { "label": "9 pt", "value": 9 }, { "label": "10 pt", "value": 10 }, { "label": "11 pt", "value": 11 }, { "label": "12 pt", "value": 12 }, { "label": "14 pt", "value": 14 }]
            textRole: "label"
            valueRole: "value"
            currentIndex: 2
            onActivated: (index) => root.size = model[index].value
        }
        PComboBox {
            Layout.fillWidth: true
            label: "Abstand zum Rand"
            model: [{ "label": "5 mm", "value": 5 }, { "label": "10 mm", "value": 10 }, { "label": "15 mm", "value": 15 }, { "label": "20 mm", "value": 20 }]
            textRole: "label"
            valueRole: "value"
            currentIndex: 1
            onActivated: (index) => root.marginMm = model[index].value
        }
        PTextField {
            id: startField
            objectName: "headerFooterStart"
            Layout.fillWidth: true
            preferredWidth: 80
            label: "Erste Seitenzahl"
            validator: IntValidator { bottom: 0; top: 99999 }
            text: "1"
        }
    }
    PFieldLabel { text: "Farbe" }
    Row {
        spacing: 8
        Repeater {
            model: [{ "value": "#000000", "name": "Schwarz" }, { "value": "#595959", "name": "Grau" }, { "value": "#1F4E9A", "name": "Blau" }, { "value": "#BE1E2D", "name": "Rot" }]
            PSwatch {
                required property var modelData
                size: 28
                swatchColor: modelData.value
                tip: modelData.name
                selected: root.color === modelData.value
                onClicked: root.color = modelData.value
            }
        }
    }

    // Bates-Nummer (fortlaufende Kennzeichnung, z. B. für Akten): nur wenn sie verwendet wird
    GridLayout {
        Layout.fillWidth: true
        Layout.topMargin: 4
        visible: root.usesBates
        columns: 4
        columnSpacing: 8
        rowSpacing: 0
        PFieldLabel { text: "Bates: Präfix" }
        PFieldLabel { text: "Stellen" }
        PFieldLabel { text: "Startnummer" }
        PFieldLabel { text: "Suffix" }
        PTextField { id: batesPrefix; objectName: "batesPrefix"; Layout.fillWidth: true; preferredWidth: 100; label: "Präfix"; placeholderText: "z. B. AKTE-" }
        PComboBox {
            id: batesDigits
            Layout.fillWidth: true
            label: "Stellen"
            model: [{ "label": "4", "value": 4 }, { "label": "5", "value": 5 }, { "label": "6", "value": 6 }, { "label": "7", "value": 7 }, { "label": "8", "value": 8 }]
            textRole: "label"
            valueRole: "value"
            currentIndex: 2
        }
        PTextField { id: batesStart; Layout.fillWidth: true; preferredWidth: 80; label: "Startnummer"; text: "1"; validator: IntValidator { bottom: 0; top: 999999999 } }
        PTextField { id: batesSuffix; Layout.fillWidth: true; preferredWidth: 80; label: "Suffix" }
    }

    PFieldLabel { text: "Seiten" }
    RowLayout {
        spacing: 12
        PRadioButton { text: "Alle (" + (root.data_.pageCount || 0) + ")"; checked: root.scope === "all"; onClicked: root.scope = "all" }
        PRadioButton { objectName: "headerFooterRange"; text: "Nur:"; checked: root.scope === "range"; onClicked: { root.scope = "range"; rangeField.forceActiveFocus() } }
        PTextField { id: rangeField; preferredWidth: 140; enabled: root.scope === "range"; label: "Seiten"; placeholderText: "z. B. 2-10" }
    }
    PCheckBox {
        Layout.topMargin: 8
        Layout.fillWidth: true
        visible: (root.data_.existing || 0) > 0
        text: "Bisherige Kopf- und Fußzeile von PDF Tool ersetzen (" + (root.data_.existing || 0) + " Seiten)"
        checked: root.replace
        onToggled: root.replace = checked
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 8
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: "Die Texte stehen aufrecht, wie man die Seite sieht – auch auf gedrehten Seiten. Entfernen lassen sie sich später über »Kopf-/Fußzeile und Wasserzeichen entfernen«."
    }
}
