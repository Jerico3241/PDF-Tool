import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

// »Kundenakte aktualisieren«: jede Abweichung einzeln wählbar (bisher → neu).
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var changes: (request.data || {}).changes || []
    property var chosen: ({})
    readonly property bool acceptable: {
        for (var i = 0; i < changes.length; ++i)
            if (chosen[changes[i].key] !== false) return true
        return false
    }
    function collect() {
        var keys = []
        for (var i = 0; i < changes.length; ++i)
            if (chosen[changes[i].key] !== false) keys.push(changes[i].key)
        return { "chosen": keys }
    }
    spacing: 8

    Repeater {
        model: root.changes
        RowLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: 10
            PToggle {
                showState: false
                label: modelData.name
                checked: root.chosen[modelData.key] !== false
                Layout.alignment: Qt.AlignTop
                onToggled: {
                    var next = Object.assign({}, root.chosen)
                    next[modelData.key] = checked
                    root.chosen = next
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                PText { text: modelData.name; textStyle: "bodyStrong" }
                PText { text: modelData.old + "  →  " + modelData["new"]; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
            }
        }
    }
    PText { text: "Nur gewählte Angaben werden in der Kundenakte gespeichert. PDF- und Excel-Dateien bleiben unberührt."; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 6 }
}
