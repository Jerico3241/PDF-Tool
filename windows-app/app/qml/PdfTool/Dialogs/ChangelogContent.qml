import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

// »Neu in Version …«: Punkte der Neuerungen.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    function collect() { return ({}) }
    spacing: 6
    Repeater {
        model: root.data_.items || []
        RowLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: 8
            PText { text: "•"; tone: "accent"; Layout.alignment: Qt.AlignTop }
            PText { text: modelData; wrap: true; Layout.fillWidth: true }
        }
    }
}
