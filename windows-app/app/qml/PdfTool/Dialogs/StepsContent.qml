import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

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
                text: (index + 1) + "."
                textStyle: "bodyStrong"
                tone: "accent"
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 20
            }
            PText {
                text: modelData
                wrap: true
                Layout.fillWidth: true
            }
        }
    }
    PText {
        text: "Hinweise"
        textStyle: "bodyStrong"
        visible: (root.data_.notes || []).length > 0
        Layout.topMargin: 10
        Layout.bottomMargin: 2
    }
    Repeater {
        model: root.data_.notes || []
        PText {
            required property var modelData
            text: modelData
            textStyle: "caption"
            tone: "secondary"
            wrap: true
            Layout.fillWidth: true
        }
    }
}
