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
            PFieldLabel { text: I18n.tr("Text", I18n.revision); first: true }
            PTextField { id: textField; objectName: "watermarkText"; Layout.fillWidth: true; label: I18n.tr("Text", I18n.revision); maximumLength: 60 }
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 6
                spacing: 6
                Repeater {
                    model: ["VERTRAULICH", "ENTWURF", "KOPIE", "MUSTER", "NUR ZUR ANSICHT"]
                    PButton { required property string modelData; kind: "subtle"; text: I18n.tr(modelData, I18n.revision); onClicked: textField.text = modelData }
                }
            }
            PCheckBox { id: boldBox; Layout.topMargin: 4; text: I18n.tr("Fett", I18n.revision); checked: true }
            PFieldLabel { text: I18n.tr("Farbe", I18n.revision) }
            Row {
                spacing: 8
                Repeater {
                    model: [{ "value": "#BE1E2D", "name": "Rot" }, { "value": "#595959", "name": "Grau" }, { "value": "#1F4E9A", "name": "Blau" }, { "value": "#22803C", "name": "Grün" }, { "value": "#000000", "name": "Schwarz" }]
                    PSwatch { required property var modelData; size: 28; swatchColor: modelData.value; tip: I18n.tr(modelData.name, I18n.revision); selected: root.color === modelData.value; onClicked: root.color = modelData.value }
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
                text: I18n.tr(textField.text, I18n.revision)
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
        PFieldLabel { text: I18n.tr("Deckkraft", I18n.revision) }
        PFieldLabel { text: I18n.tr("Winkel", I18n.revision) }
        PFieldLabel { text: I18n.tr("Größe", I18n.revision) }
        PComboBox {
            objectName: "watermarkOpacity"
            Layout.fillWidth: true
            label: I18n.tr("Deckkraft", I18n.revision)
            model: [{ "label": "10 %", "value": 0.1 }, { "label": "25 %", "value": 0.25 }, { "label": "40 %", "value": 0.4 }, { "label": "60 %", "value": 0.6 }, { "label": "100 %", "value": 1 }]
            textRole: "label"
            valueRole: "value"
            currentIndex: 1
            onActivated: (index) => root.opacity_ = model[index].value
        }
        PComboBox {
            Layout.fillWidth: true
            label: I18n.tr("Winkel", I18n.revision)
            model: [{ "label": "Schräg (45°)", "value": 45 }, { "label": "Waagerecht", "value": 0 }, { "label": "Schräg fallend (−45°)", "value": -45 }, { "label": "Senkrecht (90°)", "value": 90 }]
            textRole: "label"
            valueRole: "value"
            onActivated: (index) => root.angle = model[index].value
        }
        PComboBox {
            Layout.fillWidth: true
            label: I18n.tr("Größe", I18n.revision)
            model: [{ "label": "An die Seite anpassen", "value": 0 }, { "label": "36 pt", "value": 36 }, { "label": "48 pt", "value": 48 }, { "label": "72 pt", "value": 72 }, { "label": "96 pt", "value": 96 }]
            textRole: "label"
            valueRole: "value"
            onActivated: (index) => root.size = model[index].value
        }
    }
    PFieldLabel { text: I18n.tr("Lage", I18n.revision) }
    RowLayout {
        spacing: 12
        PRadioButton { text: I18n.tr("Über dem Inhalt", I18n.revision); checked: !root.behind; onClicked: root.behind = false }
        PRadioButton { objectName: "watermarkBehind"; text: I18n.tr("Hinter dem Inhalt", I18n.revision); checked: root.behind; onClicked: root.behind = true }
    }
    PText {
        Layout.fillWidth: true
        visible: root.behind
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Hinter dem Inhalt ist das Wasserzeichen auf Scans und Seiten mit weißem Hintergrundbild nicht zu sehen.", I18n.revision)
    }
    PFieldLabel { text: I18n.tr("Seiten", I18n.revision) }
    RowLayout {
        spacing: 12
        PRadioButton { text: I18n.tr("Alle (" + (root.data_.pageCount || 0) + ")", I18n.revision); checked: root.scope === "all"; onClicked: root.scope = "all" }
        PRadioButton { text: I18n.tr("Nur:", I18n.revision); checked: root.scope === "range"; onClicked: { root.scope = "range"; rangeField.forceActiveFocus() } }
        PTextField { id: rangeField; preferredWidth: 140; enabled: root.scope === "range"; label: I18n.tr("Seiten", I18n.revision); placeholderText: I18n.tr("z. B. 1-3, 5", I18n.revision) }
    }
    PCheckBox {
        Layout.topMargin: 8
        Layout.fillWidth: true
        visible: (root.data_.existing || 0) > 0
        text: I18n.tr("Bisheriges Wasserzeichen von PDF Tool ersetzen (" + (root.data_.existing || 0) + " Seiten)", I18n.revision)
        checked: root.replace
        onToggled: root.replace = checked
    }
}
