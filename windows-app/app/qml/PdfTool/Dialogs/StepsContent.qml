import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls
import PdfTool.Backend

// Kurzanleitung: nummerierte Schritte und Hinweise.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    function collect() { return ({}) }
    spacing: 6

    Repeater {
        model: root.data_.steps || []
        RowLayout {
            required property var modelData
            required property int index
            Layout.fillWidth: true
            spacing: 8
            PText {
                text: I18n.tr((index + 1) + ".", I18n.revision)
                textStyle: "bodyStrong"
                tone: "accent"
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 20
            }
            PText {
                text: I18n.tr(modelData, I18n.revision)
                wrap: true
                Layout.fillWidth: true
            }
        }
    }
    PText {
        text: I18n.tr("Hinweise", I18n.revision)
        textStyle: "bodyStrong"
        visible: (root.data_.notes || []).length > 0
        Layout.topMargin: 10
        Layout.bottomMargin: 2
    }
    Repeater {
        model: root.data_.notes || []
        PText {
            required property var modelData
            text: I18n.tr(modelData, I18n.revision)
            textStyle: "caption"
            tone: "secondary"
            wrap: true
            Layout.fillWidth: true
        }
    }
}
