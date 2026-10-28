import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Diagramm einfügen oder ändern (Texte, seit 5.0 Beta 5): Art (Säulen, Balken, Linie, Kreis), Titel und eine kleine
// Tabelle mit den Werten – in der ersten Zeile die Namen der Reihen, darunter je Zeile eine Beschriftung und ihre
// Werte. Ein Kreis zeigt nur die erste Reihe.
ColumnLayout {
    id: root
    objectName: "chartContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    property string kind: "column"
    property var series: []
    property var rows: []   // [{label, values: []}]
    readonly property int maxRows: 12
    readonly property int maxSeries: 6
    readonly property bool acceptable: series.length > 0 && rows.length > 0
    readonly property bool handlesReturn: false
    function collect() { return { "kind": kind, "title": titleField.text, "series": series, "rows": rows } }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var data = request.data || {}
        kind = data.kind || "column"
        titleField.text = data.title || ""
        series = (data.series || []).slice()
        rows = (data.rows || []).map(function(row) { return { label: row.label, values: (row.values || []).slice() } })
    }

    function setSeries(index, value) { var copy = series.slice(); copy[index] = value; series = copy }
    function setLabel(row, value) { var copy = rows.slice(); copy[row] = { label: value, values: copy[row].values }; rows = copy }
    function setValue(row, column, value) {
        var copy = rows.slice()
        var values = copy[row].values.slice()
        values[column] = value
        copy[row] = { label: copy[row].label, values: values }
        rows = copy
    }
    function addRow() {
        if (rows.length >= maxRows) return
        var values = []
        for (var i = 0; i < series.length; ++i) values.push("0")
        rows = rows.concat([{ label: "Wert " + (rows.length + 1), values: values }])
    }
    function removeRow() { if (rows.length > 1) rows = rows.slice(0, rows.length - 1) }
    function addSeries() {
        if (series.length >= maxSeries) return
        series = series.concat(["Reihe " + (series.length + 1)])
        rows = rows.map(function(row) { return { label: row.label, values: row.values.concat(["0"]) } })
    }
    function removeSeries() {
        if (series.length <= 1) return
        series = series.slice(0, series.length - 1)
        rows = rows.map(function(row) { return { label: row.label, values: row.values.slice(0, series.length) } })
    }

    PFieldLabel { text: I18n.tr("Art", I18n.revision); first: true }
    RowLayout {
        spacing: 6
        Repeater {
            model: root.data_.kinds || []
            PButton {
                required property var modelData
                objectName: "chartKind_" + modelData.key
                iconName: modelData.key === "bar" ? "data_bar_horizontal" : (modelData.key === "line" ? "data_line" : (modelData.key === "pie" ? "data_pie" : "data_bar_vertical"))
                text: I18n.tr(modelData.label, I18n.revision)
                toggle: true
                checked: root.kind === modelData.key
                onClicked: root.kind = modelData.key
            }
        }
    }
    PFieldLabel { text: I18n.tr("Titel", I18n.revision) }
    PTextField {
        id: titleField
        objectName: "chartTitle"
        Layout.fillWidth: true
        label: I18n.tr("Titel", I18n.revision)
        placeholderText: I18n.tr("ohne Titel", I18n.revision)
        maximumLength: 120
    }
    PFieldLabel { text: I18n.tr("Werte", I18n.revision) }
    GridLayout {
        id: grid
        objectName: "chartGrid"
        Layout.fillWidth: true
        columns: root.series.length + 1
        rowSpacing: 4
        columnSpacing: 4
        Item { Layout.preferredWidth: 120; implicitHeight: 1 }
        Repeater {
            model: root.series.length
            PTextField {
                required property int index
                Layout.fillWidth: true
                preferredWidth: 80
                text: root.series[index] || ""
                label: I18n.tr("Name der Reihe", I18n.revision)
                font.weight: Font.DemiBold
                onTextEdited: root.setSeries(index, text)
            }
        }
        Repeater {
            model: root.rows.length * (root.series.length + 1)
            PTextField {
                required property int index
                readonly property int row: Math.floor(index / (root.series.length + 1))
                readonly property int column: index % (root.series.length + 1) - 1
                Layout.fillWidth: column >= 0
                Layout.preferredWidth: column < 0 ? 120 : -1
                preferredWidth: column < 0 ? 120 : 80
                text: column < 0 ? (root.rows[row] ? root.rows[row].label : "") : (root.rows[row] ? (root.rows[row].values[column] || "") : "")
                label: I18n.tr(column < 0 ? "Beschriftung" : "Wert", I18n.revision)
                horizontalAlignment: column < 0 ? Text.AlignLeft : Text.AlignRight
                invalid: column >= 0 && text.trim() !== "" && isNaN(Number(text.trim().replace(",", ".")))
                onTextEdited: column < 0 ? root.setLabel(row, text) : root.setValue(row, column, text)
            }
        }
    }
    RowLayout {
        Layout.topMargin: 8
        spacing: 6
        PButton { objectName: "chartAddRow"; iconName: "add"; text: I18n.tr("Zeile", I18n.revision); enabled: root.rows.length < root.maxRows; onClicked: root.addRow() }
        PButton { iconName: "subtract"; tip: I18n.tr("Letzte Zeile entfernen", I18n.revision); enabled: root.rows.length > 1; onClicked: root.removeRow() }
        Item { implicitWidth: 12 }
        PButton { objectName: "chartAddSeries"; iconName: "add"; text: I18n.tr("Reihe", I18n.revision); enabled: root.series.length < root.maxSeries; onClicked: root.addSeries() }
        PButton { iconName: "subtract"; tip: I18n.tr("Letzte Reihe entfernen", I18n.revision); enabled: root.series.length > 1; onClicked: root.removeSeries() }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 8
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        visible: root.kind === "pie"
        text: I18n.tr("Ein Kreisdiagramm zeigt nur die erste Reihe.", I18n.revision)
    }
}
