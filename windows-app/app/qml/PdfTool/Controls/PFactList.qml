import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Backend

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
                text: I18n.tr(modelData.label || "", I18n.revision)
                textStyle: "caption"
                tone: "secondary"
                Layout.preferredWidth: root.labelWidth
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: 2
            }
            PText {
                text: I18n.tr(modelData.value || "", I18n.revision)
                tone: modelData.tone === "caution" ? "warning" : (modelData.tone === "muted" ? "secondary" : (modelData.tone || ""))
                wrap: true
                Layout.fillWidth: true
            }
        }
    }
}
