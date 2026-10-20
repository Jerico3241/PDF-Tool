import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls
import PdfTool.Backend

// Stapel: Vorlage für mehrere Einträge wählen (»Automatisch«, »Keine Vorlage« oder eine Vorlage).
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var options: (request.data || {}).options || []
    property string value: (request.data || {}).value || ""
    function collect() { return { "value": value } }
    spacing: 10
    PComboBox {
        Layout.fillWidth: true
        label: I18n.tr("Vorlage", I18n.revision)
        model: root.options
        currentIndex: root.options.indexOf(root.value)
        onActivated: (index) => root.value = root.options[index]
        focus: true
    }
    PText { text: I18n.tr("»Automatisch«: bevorzugte Vorlage der Kundenakte, sonst die Vorlage des Stapels, sonst die Standardvorlage. Eine hier gewählte Vorlage hat Vorrang vor allen.", I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
}
