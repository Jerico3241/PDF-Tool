import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »PDF verkleinern«: Stufe wählen. Bilder werden auf die Auflösung der Stufe neu berechnet, ungenutzte Teile
// entfernt; Text und Grafiken bleiben scharf. Gespeichert wird immer als Kopie – das Original bleibt.
ColumnLayout {
    id: root
    objectName: "optimizeContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    property string level: "mittel"
    function collect() { return { "level": root.level } }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        level = "mittel"
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: I18n.tr("Aktuelle Größe: " + (root.data_.size || "–") + ". Fotos und Scans werden neu berechnet, Text und Grafiken bleiben scharf. Gespeichert wird als Kopie; das Original bleibt unverändert.", I18n.revision)
    }
    PFieldLabel { text: I18n.tr("Qualität", I18n.revision) }
    Repeater {
        model: [
            { "key": "klein", "label": "Klein – für E-Mail und Bildschirm (110 dpi)" },
            { "key": "mittel", "label": "Ausgewogen – empfohlen (150 dpi)" },
            { "key": "hoch", "label": "Hoch – für den Druck (220 dpi)" }
        ]
        PRadioButton {
            required property var modelData
            objectName: "optimize_" + modelData.key
            text: I18n.tr(modelData.label, I18n.revision)
            checked: root.level === modelData.key
            onClicked: root.level = modelData.key
        }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 12
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Die Kopie enthält den aktuellen Stand – auch noch nicht gespeicherte Änderungen. Kennwortschutz bleibt erhalten.", I18n.revision)
    }
}
