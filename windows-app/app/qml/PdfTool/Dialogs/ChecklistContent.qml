import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Auswahl, was ein Befehl tun soll (»Dokument bereinigen«, »Reduzieren«, Kopf-/Fußzeile und Wasserzeichen
// entfernen): je Eintrag ein Kontrollkästchen mit Erklärung und der gefundenen Anzahl. Einträge ohne Fund
// sind ausgegraut. ``data.items``: [{key, label, detail, count, checked, unit}].
ColumnLayout {
    id: root
    objectName: "checklistContent"
    property var request: ({})
    readonly property var items: (request.data || {}).items || []
    property var chosen: ({})
    readonly property bool acceptable: {
        for (var i = 0; i < items.length; ++i)
            if (chosen[items[i].key] && items[i].count > 0) return true
        return false
    }
    function collect() { return Object.assign({}, chosen) }
    spacing: 4

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var next = {}
        var list = (request.data || {}).items || []
        for (var i = 0; i < list.length; ++i)
            next[list[i].key] = list[i].checked === true && list[i].count > 0
        chosen = next
    }

    Repeater {
        model: root.items
        RowLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: 8
            PCheckBox {
                objectName: "checklist_" + parent.modelData.key
                Layout.fillWidth: true
                enabled: parent.modelData.count > 0
                checked: root.chosen[parent.modelData.key] === true
                text: parent.modelData.label + (parent.modelData.detail ? " – " + parent.modelData.detail : "")
                onToggled: {
                    var next = Object.assign({}, root.chosen)
                    next[parent.modelData.key] = checked
                    root.chosen = next
                }
            }
            PBadge {
                Layout.alignment: Qt.AlignVCenter
                text: parent.modelData.count > 0 ? (parent.modelData.count + (parent.modelData.unit ? " " + parent.modelData.unit : "")) : "nichts gefunden"
                tone: parent.modelData.count > 0 ? "info" : "neutral"
            }
        }
    }
}
