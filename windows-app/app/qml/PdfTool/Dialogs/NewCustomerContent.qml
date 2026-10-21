import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls
import PdfTool.Backend

// »Als Kundenakte speichern«: Zusammenfassung, »Zuordnung merken« und Hinweise auf Doppelungen.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    function collect() { return { "remember": remember.checked } }
    spacing: 8

    PText { text: I18n.tr(root.data_.summary || "", I18n.revision); textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true }
    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: 4
        visible: (root.data_.email || "") !== ""
        spacing: 10
        PToggle { id: remember; showState: false; checked: root.data_.remember === true; label: I18n.tr("Zuordnung merken", I18n.revision) }
        PText { text: I18n.tr("Zuordnung merken: " + (root.data_.email || "") + " künftig diesem Kunden zuordnen", I18n.revision); wrap: true; Layout.fillWidth: true }
    }
    Repeater {
        model: root.data_.hints || []
        PText { required property var modelData; text: I18n.tr(modelData, I18n.revision); textStyle: "caption"; tone: "warning"; wrap: true; Layout.fillWidth: true }
    }
    PText { text: I18n.tr("Kundendaten werden ausschließlich lokal auf diesem PC gespeichert.", I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 4 }
}
