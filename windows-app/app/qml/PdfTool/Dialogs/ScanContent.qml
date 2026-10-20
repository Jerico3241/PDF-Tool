import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

// »Scannen«: Scanner, Quelle (Vorlagenglas oder Einzug), Farbe und Auflösung, auf Wunsch gleich Text erkennen.
// Gescannt wird über die Scanner-Schnittstelle von Windows, ohne Fenster des Treibers.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    property string scanner: ""
    property string source: "flatbed"
    property string color: "color"
    property int dpi: 300
    readonly property bool acceptable: scanner !== ""
    function collect() { return { "scanner": root.scanner, "source": root.source, "color": root.color, "dpi": root.dpi, "ocr": ocr.checked } }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var data = request.data || {}
        root.scanner = data.scanner || ""
        root.source = data.source || "flatbed"
        root.color = data.color || "color"
        root.dpi = data.dpi || 300
        ocr.checked = data.ocr === true
    }

    PComboBox {
        objectName: "scanScanner"
        Layout.fillWidth: true
        label: "Scanner"
        model: root.data_.scanners || []
        textRole: "name"
        valueRole: "id"
        currentIndex: (root.data_.scanners || []).findIndex(function(item) { return item.id === root.scanner })
        onActivated: (index) => root.scanner = root.data_.scanners[index].id
        focus: true
    }

    PFieldLabel { text: "Quelle" }
    RowLayout {
        spacing: 16
        PRadioButton { objectName: "scanFlatbed"; text: "Vorlagenglas (Seite für Seite)"; checked: root.source === "flatbed"; onClicked: root.source = "flatbed" }
        PRadioButton { objectName: "scanFeeder"; text: "Einzug (alle Blätter)"; checked: root.source === "feeder"; onClicked: root.source = "feeder" }
    }

    PFieldLabel { text: "Farbe" }
    RowLayout {
        spacing: 16
        PRadioButton { objectName: "scanColor"; text: "Farbe"; checked: root.color === "color"; onClicked: root.color = "color" }
        PRadioButton { objectName: "scanGray"; text: "Graustufen"; checked: root.color === "gray"; onClicked: root.color = "gray" }
        PRadioButton { objectName: "scanBw"; text: "Schwarzweiß"; checked: root.color === "bw"; onClicked: root.color = "bw" }
    }

    PFieldLabel { text: "Auflösung" }
    PComboBox {
        objectName: "scanDpi"
        preferredWidth: 220
        model: (root.data_.resolutions || [150, 200, 300, 600]).map(function(value) { return { "label": value + " dpi" + (value === 300 ? " (empfohlen)" : value === 150 ? " (klein)" : value === 600 ? " (sehr fein)" : ""), "value": value } })
        textRole: "label"
        valueRole: "value"
        currentIndex: (root.data_.resolutions || [150, 200, 300, 600]).indexOf(root.dpi)
        onActivated: (index) => root.dpi = (root.data_.resolutions || [150, 200, 300, 600])[index]
    }

    PCheckBox {
        id: ocr
        objectName: "scanOcr"
        Layout.topMargin: 12
        Layout.fillWidth: true
        enabled: root.data_.ocrAvailable === true
        text: "Text erkennen – die PDF wird durchsuchbar"
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 4
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: "Danach wählen Sie, wo die PDF gespeichert wird. Die Texterkennung läuft vollständig auf diesem PC."
    }
}
