import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Wasserzeichen«: Text (Vorschläge oder eigener), Farbe, Deckkraft, Winkel, Größe, über oder hinter dem Inhalt
// und welche Seiten. Die kleine Seite zeigt das Ergebnis vorab.
ColumnLayout {
    id: root
    objectName: "watermarkContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    property string color: "#BE1E2D"
    property real opacity_: 0.25
    property real angle: 45
    property real size: 0
    property bool behind: false
    property string scope: "all"
    property bool replace: true
    readonly property bool acceptable: textField.text.trim() !== "" && (scope === "all" || rangeField.text.trim() !== "")
    function collect() {
        return { "text": textField.text.trim(), "font": boldBox.checked ? "Helvetica-Bold" : "Helvetica", "size": size, "color": color, "opacity": opacity_, "angle": angle, "behind": behind, "pages": scope === "all" ? "" : rangeField.text, "replace": replace }
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        textField.text = "VERTRAULICH"
        scope = "all"
        replace = true
        textField.selectAll()
        textField.forceActiveFocus(Qt.OtherFocusReason)
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 16
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            PFieldLabel { text: "Text"; first: true }
            PTextField { id: textField; objectName: "watermarkText"; Layout.fillWidth: true; label: "Text"; maximumLength: 60 }
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 6
                spacing: 6
                Repeater {
                    model: ["VERTRAULICH", "ENTWURF", "KOPIE", "MUSTER", "NUR ZUR ANSICHT"]
                    PButton { required property string modelData; kind: "subtle"; text: modelData; onClicked: textField.text = modelData }
                }
            }
            PCheckBox { id: boldBox; Layout.topMargin: 4; text: "Fett"; checked: true }
            PFieldLabel { text: "Farbe" }
            Row {
                spacing: 8
                Repeater {
                    model: [{ "value": "#BE1E2D", "name": "Rot" }, { "value": "#595959", "name": "Grau" }, { "value": "#1F4E9A", "name": "Blau" }, { "value": "#22803C", "name": "Grün" }, { "value": "#000000", "name": "Schwarz" }]
                    PSwatch { required property var modelData; size: 28; swatchColor: modelData.value; tip: modelData.name; selected: root.color === modelData.value; onClicked: root.color = modelData.value }
                }
            }
        }
        // Vorschau
        Rectangle {
            objectName: "watermarkPreview"
            Layout.alignment: Qt.AlignTop
            implicitWidth: 150
            implicitHeight: 212
            color: Theme.paper
            border.color: Theme.border
            radius: 2
            clip: true
            Column {
                anchors.centerIn: parent
                spacing: 6
                z: root.behind ? 1 : 0
                Repeater {
                    model: 12
                    Rectangle { width: 110 - (index % 3) * 16; height: 3; radius: 1.5; color: "#C8C8C8" }
                }
            }
            Text {
                anchors.centerIn: parent
                text: textField.text
                rotation: -root.angle
                font.pixelSize: root.size > 0 ? Math.max(6, root.size * 0.25) : Math.max(8, Math.min(40, 170 / Math.max(1, textField.text.length) * 1.3))
                font.bold: boldBox.checked
                font.family: "Arial"
                color: root.color
                opacity: root.opacity_
            }
        }
    }

    GridLayout {
        Layout.fillWidth: true
        Layout.topMargin: 8
        columns: 3
        columnSpacing: 8
        rowSpacing: 0
        PFieldLabel { text: "Deckkraft" }
        PFieldLabel { text: "Winkel" }
        PFieldLabel { text: "Größe" }
        PComboBox {
            objectName: "watermarkOpacity"
            Layout.fillWidth: true
            label: "Deckkraft"
            model: [{ "label": "10 %", "value": 0.1 }, { "label": "25 %", "value": 0.25 }, { "label": "40 %", "value": 0.4 }, { "label": "60 %", "value": 0.6 }, { "label": "100 %", "value": 1 }]
            textRole: "label"
            valueRole: "value"
            currentIndex: 1
            onActivated: (index) => root.opacity_ = model[index].value
        }
        PComboBox {
            Layout.fillWidth: true
            label: "Winkel"
            model: [{ "label": "Schräg (45°)", "value": 45 }, { "label": "Waagerecht", "value": 0 }, { "label": "Schräg fallend (−45°)", "value": -45 }, { "label": "Senkrecht (90°)", "value": 90 }]
            textRole: "label"
            valueRole: "value"
            onActivated: (index) => root.angle = model[index].value
        }
        PComboBox {
            Layout.fillWidth: true
            label: "Größe"
            model: [{ "label": "An die Seite anpassen", "value": 0 }, { "label": "36 pt", "value": 36 }, { "label": "48 pt", "value": 48 }, { "label": "72 pt", "value": 72 }, { "label": "96 pt", "value": 96 }]
            textRole: "label"
            valueRole: "value"
            onActivated: (index) => root.size = model[index].value
        }
    }
    PFieldLabel { text: "Lage" }
    RowLayout {
        spacing: 12
        PRadioButton { text: "Über dem Inhalt"; checked: !root.behind; onClicked: root.behind = false }
        PRadioButton { objectName: "watermarkBehind"; text: "Hinter dem Inhalt"; checked: root.behind; onClicked: root.behind = true }
    }
    PText {
        Layout.fillWidth: true
        visible: root.behind
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: "Hinter dem Inhalt ist das Wasserzeichen auf Scans und Seiten mit weißem Hintergrundbild nicht zu sehen."
    }
    PFieldLabel { text: "Seiten" }
    RowLayout {
        spacing: 12
        PRadioButton { text: "Alle (" + (root.data_.pageCount || 0) + ")"; checked: root.scope === "all"; onClicked: root.scope = "all" }
        PRadioButton { text: "Nur:"; checked: root.scope === "range"; onClicked: { root.scope = "range"; rangeField.forceActiveFocus() } }
        PTextField { id: rangeField; preferredWidth: 140; enabled: root.scope === "range"; label: "Seiten"; placeholderText: "z. B. 1-3, 5" }
    }
    PCheckBox {
        Layout.topMargin: 8
        Layout.fillWidth: true
        visible: (root.data_.existing || 0) > 0
        text: "Bisheriges Wasserzeichen von PDF Tool ersetzen (" + (root.data_.existing || 0) + " Seiten)"
        checked: root.replace
        onToggled: root.replace = checked
    }
}
