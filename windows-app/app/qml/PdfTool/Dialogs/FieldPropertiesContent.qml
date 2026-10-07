import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Feldeigenschaften« (Formular gestalten): Name, Kurzinfo, Pflichtfeld, schreibgeschützt; je nach Art
// mehrzeilig und Zeichenzahl (Textfeld), Schriftgröße und Ausrichtung, Optionen (Dropdown, Liste) oder
// Exportwert (Kontrollkästchen, Option einer Gruppe); Rahmen und Hintergrund. Übernommen werden nur
// geänderte Werte – als ein Schritt für Rückgängig.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var field: (request.data || {}).field || ({})
    readonly property string kind: field.kind || ""
    readonly property bool textKind: kind === "text"
    readonly property bool choiceKind: kind === "combo" || kind === "list"
    readonly property bool buttonKind: kind === "checkbox" || kind === "radio"
    readonly property bool sizeKind: textKind || choiceKind
    readonly property string problem: {
        var name = nameField.text.trim()
        if (name === "") return "Bitte einen Namen angeben."
        if (name.indexOf(".") >= 0) return "Der Name darf keinen Punkt enthalten (der Punkt trennt Gruppen von Feldern)."
        if (root.buttonKind && exportField.text.trim() === "") return "Bitte einen Exportwert angeben (z. B. »Ja«)."
        if (root.buttonKind && exportField.text.trim() === "Off") return "»Off« steht für »nicht gewählt« – bitte einen anderen Exportwert."
        if (root.choiceKind && optionLines().length === 0) return "Bitte mindestens eine Option angeben."
        if (root.textKind && maxField.text.trim() !== "" && !/^\d+$/.test(maxField.text.trim())) return "Die Zeichenzahl muss eine ganze Zahl sein (leer: beliebig)."
        return ""
    }
    readonly property bool acceptable: problem === ""
    function optionLines() {
        return optionsArea.text.split("\n").map(function(line) { return line.trim() }).filter(function(line) { return line !== "" })
    }
    function collect() {
        return {
            "name": nameField.text.trim(), "tooltip": tooltipField.text.trim(), "required": required.checked, "readOnly": readOnly.checked,
            "multiline": multiline.checked, "maxLength": maxField.text.trim() === "" ? 0 : Number(maxField.text.trim()),
            "fontSize": fontSize.currentValue === undefined ? root.field.fontSize : fontSize.currentValue,
            "align": align.currentValue === undefined ? root.field.align : align.currentValue,
            "options": optionLines(), "export": exportField.text.trim(), "border": border.checked, "background": background.checked
        }
    }
    function kindLabel(name) {
        switch (name) {
        case "text": return "Textfeld"
        case "checkbox": return "Kontrollkästchen"
        case "radio": return "Option einer Optionsgruppe"
        case "combo": return "Dropdown (Auswahlliste)"
        case "list": return "Liste"
        case "signature": return "Signaturfeld"
        case "button": return "Schaltfläche"
        default: return "Feld"
        }
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var f = (request.data || {}).field || {}
        var name = String(f.name || "")
        nameField.text = name.split(".").pop()
        tooltipField.text = f.tooltip || ""
        required.checked = f.required === true
        readOnly.checked = f.readOnly === true
        multiline.checked = f.multiline === true
        maxField.text = f.maxLength > 0 ? String(f.maxLength) : ""
        fontSize.currentIndex = Math.max(0, fontSize.indexOfValue(Math.round(f.fontSize || 0)))
        align.currentIndex = Math.max(0, align.indexOfValue(f.align || "left"))
        optionsArea.text = (f.options || []).join("\n")
        exportField.text = f.export || ""
        border.checked = f.border === true
        background.checked = f.background === true
        nameField.selectAll()
        nameField.forceActiveFocus(Qt.OtherFocusReason)
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: root.kindLabel(root.kind) + (root.kind === "radio" ? " »" + String(root.field.name || "") + "« – Name, Kurzinfo, Pflicht und Schreibschutz gelten für die ganze Gruppe, der Exportwert nur für diese Option." : ".") + " Mit »Rückgängig« (Strg+Z) lässt sich alles zurücknehmen."
    }

    GridLayout {
        Layout.fillWidth: true
        Layout.topMargin: 12
        columns: 2
        columnSpacing: 12
        rowSpacing: 8
        PText { text: "Name"; tone: "secondary" }
        PTextField { id: nameField; objectName: "fieldName"; Layout.fillWidth: true; label: "Name"; maximumLength: 120; invalid: root.problem !== "" && (text.trim() === "" || text.indexOf(".") >= 0) }
        PText { text: "Kurzinfo"; tone: "secondary" }
        PTextField { id: tooltipField; objectName: "fieldTooltip"; Layout.fillWidth: true; label: "Kurzinfo"; placeholderText: "erscheint beim Zeigen auf das Feld"; maximumLength: 500 }
        PText { text: "Exportwert"; tone: "secondary"; visible: root.buttonKind }
        PTextField { id: exportField; objectName: "fieldExport"; visible: root.buttonKind; Layout.fillWidth: true; label: "Exportwert"; maximumLength: 60; placeholderText: "Wert, wenn gewählt (z. B. Ja)" }
        PText { text: "Höchstens"; tone: "secondary"; visible: root.textKind }
        RowLayout {
            visible: root.textKind
            spacing: 8
            PTextField { id: maxField; objectName: "fieldMaxLength"; preferredWidth: 90; label: "Höchstzahl Zeichen"; placeholderText: "beliebig"; inputMethodHints: Qt.ImhDigitsOnly; maximumLength: 6 }
            PText { text: "Zeichen"; tone: "secondary" }
        }
        PText { text: "Schriftgröße"; tone: "secondary"; visible: root.sizeKind }
        PComboBox {
            id: fontSize
            objectName: "fieldFontSize"
            visible: root.sizeKind
            preferredWidth: 140
            label: "Schriftgröße"
            model: [{ "label": "Automatisch", "value": 0 }, { "label": "8 pt", "value": 8 }, { "label": "9 pt", "value": 9 }, { "label": "10 pt", "value": 10 }, { "label": "11 pt", "value": 11 }, { "label": "12 pt", "value": 12 }, { "label": "14 pt", "value": 14 }, { "label": "16 pt", "value": 16 }, { "label": "18 pt", "value": 18 }, { "label": "24 pt", "value": 24 }]
            textRole: "label"
            valueRole: "value"
        }
        PText { text: "Ausrichtung"; tone: "secondary"; visible: root.textKind || root.kind === "combo" }
        PComboBox {
            id: align
            objectName: "fieldAlign"
            visible: root.textKind || root.kind === "combo"
            preferredWidth: 140
            label: "Ausrichtung"
            model: [{ "label": "Links", "value": "left" }, { "label": "Zentriert", "value": "center" }, { "label": "Rechts", "value": "right" }]
            textRole: "label"
            valueRole: "value"
        }
    }

    PFieldLabel { visible: root.choiceKind; text: "Optionen (eine je Zeile)" }
    PTextArea {
        id: optionsArea
        objectName: "fieldOptions"
        visible: root.choiceKind
        Layout.fillWidth: true
        minLines: 3
        maxLines: 8
        label: "Optionen"
    }

    ColumnLayout {
        Layout.topMargin: 12
        spacing: 0
        PCheckBox { id: multiline; objectName: "fieldMultiline"; visible: root.textKind; text: "Mehrzeilig (Zeilenumbrüche erlaubt)" }
        PCheckBox { id: required; objectName: "fieldRequired"; text: "Pflichtfeld" }
        PCheckBox { id: readOnly; objectName: "fieldReadOnly"; text: "Schreibgeschützt (lässt sich nicht ausfüllen)" }
        PCheckBox { id: border; objectName: "fieldBorder"; visible: root.kind !== "signature" && root.kind !== "button"; text: "Rahmen" }
        PCheckBox { id: background; objectName: "fieldBackground"; visible: root.kind !== "signature" && root.kind !== "button"; text: "Weißer Hintergrund" }
    }

    PText {
        objectName: "fieldProblem"
        Layout.fillWidth: true
        Layout.topMargin: 8
        visible: root.problem !== ""
        wrap: true
        tone: "warning"
        textStyle: "caption"
        text: root.problem
    }
}
