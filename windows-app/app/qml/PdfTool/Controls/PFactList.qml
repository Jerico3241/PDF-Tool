import QtQuick
import QtQuick.Layouts
import PdfTool.Style

// Angaben als Zeilen »Beschriftung · Wert« – ``facts``: Liste aus {label, value, tone}.
ColumnLayout {
    id: root
    property var facts: []
    property int labelWidth: 150
    spacing: 4
    Repeater {
        model: root.facts
        RowLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: 12
            PText {
                text: modelData.label || ""
                textStyle: "caption"
                tone: "secondary"
                Layout.preferredWidth: root.labelWidth
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: 2
            }
            PText {
                text: modelData.value || ""
                tone: modelData.tone === "caution" ? "warning" : (modelData.tone === "muted" ? "secondary" : (modelData.tone || ""))
                wrap: true
                Layout.fillWidth: true
            }
        }
    }
}
