import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls
import PdfTool.Backend

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
            PText { text: I18n.tr("•", I18n.revision); tone: "accent"; Layout.alignment: Qt.AlignTop }
            PText { text: I18n.tr(modelData, I18n.revision); wrap: true; Layout.fillWidth: true }
        }
    }
}
