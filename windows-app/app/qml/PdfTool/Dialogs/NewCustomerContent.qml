import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

// »Als Kundenakte speichern«: Zusammenfassung, »Zuordnung merken« und Hinweise auf Doppelungen.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    function collect() { return { "remember": remember.checked } }
    spacing: 8

    PText { text: root.data_.summary || ""; textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true }
    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: 4
        visible: (root.data_.email || "") !== ""
        spacing: 10
        PToggle { id: remember; showState: false; checked: root.data_.remember === true; label: "Zuordnung merken" }
        PText { text: "Zuordnung merken: " + (root.data_.email || "") + " künftig diesem Kunden zuordnen"; wrap: true; Layout.fillWidth: true }
    }
    Repeater {
        model: root.data_.hints || []
        PText { required property var modelData; text: modelData; textStyle: "caption"; tone: "warning"; wrap: true; Layout.fillWidth: true }
    }
    PText { text: "Kundendaten werden ausschließlich lokal auf diesem PC gespeichert."; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 4 }
}
