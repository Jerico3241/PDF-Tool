import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Einfaches Formular für die Tabellen-Befehle (seit 5.0 Beta 5): Pivot-Tabelle, Datenüberprüfung, bedingte
// Formatierung, Duplikate, Text in Spalten, Teilen/Zusammenführen und Kennwortschutz. Die Felder kommen aus Python
// (``data.fields``): je Feld ``key``, ``type`` (choice, text, password, check, checks, note, preview), ``label``,
// ``value`` und je nach Art ``options`` [{key, label}], ``placeholder``, ``required``; ``show`` {key, is} (oder eine Liste
// davon) zeigt ein Feld nur bei bestimmten Werten anderer. ``preview`` zeigt ``samples`` an ``source`` (Trennzeichen) geteilt.
ColumnLayout {
    id: root
    objectName: "sheetFormContent"
    property var request: ({})
    readonly property var fields: (request.data || {}).fields || []
    property var values: ({})
    readonly property bool handlesReturn: false
    readonly property bool acceptable: {
        for (var i = 0; i < fields.length; ++i) {
            var field = fields[i]
            if (!shown(field, values)) continue
            var value = values[field.key]
            if (field.required && (field.type === "text" || field.type === "password") && String(value || "").trim() === "") return false
            if (field.required && field.type === "checks" && (!value || value.length < (field.minimum || 1))) return false
            if (field.confirm && String(values[field.confirm] || "") !== String(value || "")) return false
        }
        return true
    }
    function collect() { return values }
    function shown(field, current) {
        if (!field.show) return true
        var rules = Array.isArray(field.show) ? field.show : [field.show]
        for (var i = 0; i < rules.length; ++i)
            if ((rules[i]["is"] || []).indexOf(current[rules[i].key]) < 0) return false
        return true
    }
    function setValue(key, value) {
        var copy = Object.assign({}, values)
        copy[key] = value
        values = copy
    }
    function toggleIn(key, option) {
        var list = (values[key] || []).slice()
        var at = list.indexOf(option)
        if (at >= 0) list.splice(at, 1)
        else list.push(option)
        setValue(key, list)
    }
    function splitSample(text, field) {
        var separator = values[field.source] || ";"
        if (separator === "other") separator = values[field.custom] || ""
        if (separator === "") return [text]
        if (separator === "tab") return text.split("\t")
        if (separator === " ") return text.trim().split(/\s+/)
        return text.split(separator)
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var start = {}
        var list = (request.data || {}).fields || []  // nicht ``fields``: dessen Bindung ist hier evtl. noch alt
        for (var i = 0; i < list.length; ++i) {
            var field = list[i]
            if (field.key) start[field.key] = field.value !== undefined ? field.value : (field.type === "checks" ? [] : (field.type === "check" ? false : ""))
        }
        values = start
    }

    Repeater {
        model: root.fields
        ColumnLayout {
            id: row
            required property var modelData
            required property int index
            readonly property var field: modelData
            Layout.fillWidth: true
            spacing: 0
            visible: root.shown(field, root.values)

            PFieldLabel {
                text: I18n.tr(row.field.label || "", I18n.revision)
                first: row.index === 0
                visible: (row.field.label || "") !== "" && row.field.type !== "check" && row.field.type !== "note"
            }
            PComboBox {
                objectName: "sheetForm_" + row.field.key
                visible: row.field.type === "choice"
                Layout.fillWidth: true
                label: I18n.tr(row.field.label || "", I18n.revision)
                textRole: "label"
                model: row.field.options || []
                currentIndex: {
                    var options = row.field.options || []
                    for (var i = 0; i < options.length; ++i) if (options[i].key === root.values[row.field.key]) return i
                    return 0
                }
                onActivated: (index) => root.setValue(row.field.key, row.field.options[index].key)
            }
            PTextField {
                objectName: "sheetForm_" + row.field.key
                visible: row.field.type === "text" || row.field.type === "password"
                Layout.fillWidth: true
                label: I18n.tr(row.field.label || "", I18n.revision)
                placeholderText: I18n.tr(row.field.placeholder || "", I18n.revision)
                echoMode: row.field.type === "password" ? TextInput.Password : TextInput.Normal
                passwordCharacter: "●"
                inputMethodHints: row.field.type === "password" ? Qt.ImhHiddenText | Qt.ImhSensitiveData | Qt.ImhNoPredictiveText : Qt.ImhNone
                text: row.field.type === "text" || row.field.type === "password" ? String(root.values[row.field.key] || "") : ""
                onTextEdited: root.setValue(row.field.key, text)
                Component.onCompleted: if (row.index === 0 && visible) forceActiveFocus(Qt.OtherFocusReason)
            }
            PCheckBox {
                objectName: "sheetForm_" + row.field.key
                visible: row.field.type === "check"
                Layout.topMargin: 8
                text: I18n.tr(row.field.label || "", I18n.revision)
                checked: root.values[row.field.key] === true
                onClicked: root.setValue(row.field.key, checked)
            }
            Flow {
                visible: row.field.type === "checks"
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: row.field.type === "checks" ? row.field.options || [] : []
                    PCheckBox {
                        required property var modelData
                        objectName: "sheetForm_" + row.field.key + "_" + modelData.key
                        width: Math.max(implicitWidth, 160)
                        text: I18n.tr(modelData.label, I18n.revision)
                        checked: (root.values[row.field.key] || []).indexOf(modelData.key) >= 0
                        onClicked: root.toggleIn(row.field.key, modelData.key)
                    }
                }
            }
            PText {
                visible: row.field.type === "note"
                Layout.fillWidth: true
                Layout.topMargin: row.index === 0 ? 0 : 10
                text: I18n.tr(row.field.label || "", I18n.revision)
                textStyle: "caption"
                tone: "secondary"
                wrap: true
            }
            // Vorschau: so werden die ersten Zeilen geteilt
            Rectangle {
                visible: row.field.type === "preview"
                Layout.fillWidth: true
                Layout.topMargin: 4
                implicitHeight: previewColumn.implicitHeight + 12
                radius: Metrics.radiusControl
                color: Theme.surfaceSecondary
                border.color: Theme.divider
                clip: true
                Column {
                    id: previewColumn
                    x: 6
                    y: 6
                    spacing: 2
                    Repeater {
                        model: row.field.type === "preview" ? row.field.samples || [] : []
                        Row {
                            required property var modelData
                            spacing: 1
                            Repeater {
                                model: root.splitSample(String(parent.modelData), row.field).slice(0, 8)
                                Rectangle {
                                    id: part
                                    required property var modelData
                                    readonly property string value: String(modelData).trim()  // Daten, kein Oberflächentext
                                    width: 86
                                    height: 22
                                    color: Theme.surface
                                    border.color: Theme.divider
                                    Text {
                                        anchors.fill: parent
                                        anchors.leftMargin: 4
                                        anchors.rightMargin: 4
                                        verticalAlignment: Text.AlignVCenter
                                        text: I18n.tr(part.value, I18n.revision)
                                        elide: Text.ElideRight
                                        font: Typography.caption
                                        color: Theme.textPrimary
                                        textFormat: Text.PlainText
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
