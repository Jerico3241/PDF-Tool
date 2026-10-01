import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

// Wiederherstellen: Zusammenfassung der geprüften Sicherung und Auswahl der Bereiche.
// Alle Bereiche sind vorgewählt; ohne gewählten Bereich lässt sich nicht bestätigen.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    property var chosen: ({})
    readonly property bool acceptable: {
        var areas = data_.areas || []
        for (var i = 0; i < areas.length; ++i)
            if (chosen[areas[i].key] !== false) return true
        return false
    }
    function collect() {
        var keys = []
        var areas = data_.areas || []
        for (var i = 0; i < areas.length; ++i)
            if (chosen[areas[i].key] !== false) keys.push(areas[i].key)
        return { "areas": keys }
    }
    function toggle(key, value) {
        var copy = Object.assign({}, chosen)
        copy[key] = value
        chosen = copy
    }
    onRequestChanged: chosen = ({})
    spacing: 0

    PFactList {
        Layout.fillWidth: true
        labelWidth: 110
        facts: [
            { "label": "Sicherung", "value": root.data_.name || "" },
            { "label": "Erstellt", "value": root.data_.created || "" },
            { "label": "Version", "value": "PDF Tool " + (root.data_.version || "") },
            { "label": "Art", "value": (root.data_.kind || "") + " · " + (root.data_.size || "") }
        ]
    }
    PText { text: "Wiederherstellen"; textStyle: "bodyStrong"; Layout.topMargin: 14; Layout.bottomMargin: 2 }
    Repeater {
        model: root.data_.areas || []
        RowLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: 8
            PCheckBox {
                objectName: "restoreArea_" + modelData.key
                text: modelData.label
                checked: root.chosen[modelData.key] !== false
                onToggled: root.toggle(modelData.key, checked)
            }
            PText { text: modelData.summary; textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true; horizontalAlignment: Text.AlignRight }
        }
    }
    Repeater {
        model: root.data_.notes || []
        PText { required property var modelData; text: modelData; textStyle: "caption"; tone: "warning"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 6 }
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: 12
        spacing: 8
        PIcon { name: "shield"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
        PText { text: "Nicht gewählte Bereiche bleiben unverändert. Excel- und PDF-Dateien werden nie verändert."; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
    }
}
