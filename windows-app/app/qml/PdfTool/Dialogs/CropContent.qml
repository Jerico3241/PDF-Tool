import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Seiten zuschneiden«: Ränder in Millimetern (wie man die Seite sieht) – oder »An den Inhalt anpassen« mit den
// erkannten Rändern der aktuellen Seite. Zugeschnitten wird nur die Anzeige (CropBox); der Inhalt außerhalb
// bleibt in der Datei, »Zuschnitt zurücksetzen« holt ihn zurück.
ColumnLayout {
    id: root
    objectName: "cropContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    property string scope: "all"
    property bool reset: false
    readonly property var fields: [leftField, topField, rightField, bottomField]
    readonly property bool acceptable: reset || ((scope !== "range" || rangeField.text.trim() !== "") && fields.some(function(field) { return parseFloat(field.text.replace(",", ".")) > 0 }))
    function value(field) {
        var number = parseFloat(field.text.replace(",", "."))
        return isNaN(number) ? 0 : Math.max(0, number)
    }
    function collect() {
        return { "margins": [value(leftField), value(topField), value(rightField), value(bottomField)], "scope": scope, "range": rangeField.text, "reset": reset }
    }
    function useAuto() {
        var auto = data_.auto || [0, 0, 0, 0]
        leftField.text = String(auto[0]).replace(".", ",")
        topField.text = String(auto[1]).replace(".", ",")
        rightField.text = String(auto[2]).replace(".", ",")
        bottomField.text = String(auto[3]).replace(".", ",")
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var data = request.data || {}
        scope = (data.selected || 0) > 0 ? "selected" : "all"
        reset = false
        for (var i = 0; i < 4; ++i) fields[i].text = "0"
        rangeField.text = ""
    }

    component Margin: PTextField {
        preferredWidth: 90
        validator: DoubleValidator { bottom: 0; top: 2000; decimals: 1; notation: DoubleValidator.StandardNotation; locale: "de_DE" }
        enabled: !root.reset
    }

    GridLayout {
        Layout.alignment: Qt.AlignHCenter
        columns: 3
        columnSpacing: 8
        rowSpacing: 6
        Item { implicitWidth: 1 }
        ColumnLayout { spacing: 2; PText { text: I18n.tr("Oben (mm)", I18n.revision); textStyle: "caption" } Margin { id: topField; objectName: "cropTop"; label: I18n.tr("Oben", I18n.revision) } }
        Item { implicitWidth: 1 }
        ColumnLayout { spacing: 2; PText { text: I18n.tr("Links (mm)", I18n.revision); textStyle: "caption" } Margin { id: leftField; objectName: "cropLeft"; label: I18n.tr("Links", I18n.revision) } }
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            implicitWidth: 70
            implicitHeight: 96
            color: Theme.paper
            border.color: Theme.border
            Rectangle {
                readonly property real k: 0.33
                x: Math.min(parent.width / 2 - 4, root.value(leftField) * k)
                y: Math.min(parent.height / 2 - 4, root.value(topField) * k)
                width: Math.max(8, parent.width - x - Math.min(parent.width / 2 - 4, root.value(rightField) * k))
                height: Math.max(8, parent.height - y - Math.min(parent.height / 2 - 4, root.value(bottomField) * k))
                color: "transparent"
                border.width: 2
                border.color: Theme.accent
                visible: !root.reset
            }
        }
        ColumnLayout { spacing: 2; PText { text: I18n.tr("Rechts (mm)", I18n.revision); textStyle: "caption" } Margin { id: rightField; objectName: "cropRight"; label: I18n.tr("Rechts", I18n.revision) } }
        Item { implicitWidth: 1 }
        ColumnLayout { spacing: 2; PText { text: I18n.tr("Unten (mm)", I18n.revision); textStyle: "caption" } Margin { id: bottomField; objectName: "cropBottom"; label: I18n.tr("Unten", I18n.revision) } }
        Item { implicitWidth: 1 }
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: 8
        spacing: 12
        PButton {
            objectName: "cropAuto"
            iconName: "page_fit"
            text: I18n.tr("An den Inhalt anpassen", I18n.revision)
            enabled: !root.reset
            tip: I18n.tr("Weiße Ränder der aktuellen Seite erkennen", I18n.revision)
            onClicked: root.useAuto()
        }
        PText {
            Layout.fillWidth: true
            wrap: true
            textStyle: "caption"
            tone: "secondary"
            text: I18n.tr("Erkannt auf Seite " + ((root.data_.current || 0) + 1) + ": " + (root.data_.auto || [0, 0, 0, 0]).map(function(v) { return String(v).replace(".", ",") }).join(" · ") + " mm (links · oben · rechts · unten)", I18n.revision)
        }
    }

    PFieldLabel { text: I18n.tr("Seiten", I18n.revision) }
    ColumnLayout {
        spacing: 0
        PRadioButton { text: I18n.tr("Alle Seiten (" + (root.data_.pageCount || 0) + ")", I18n.revision); checked: root.scope === "all"; onClicked: root.scope = "all" }
        PRadioButton { text: I18n.tr("Aktuelle Seite (" + ((root.data_.current || 0) + 1) + ")", I18n.revision); checked: root.scope === "current"; onClicked: root.scope = "current" }
        PRadioButton { visible: (root.data_.selected || 0) > 0; text: I18n.tr("Ausgewählte Seiten (" + (root.data_.selected || 0) + ")", I18n.revision); checked: root.scope === "selected"; onClicked: root.scope = "selected" }
        RowLayout {
            spacing: 8
            PRadioButton { text: I18n.tr("Nur:", I18n.revision); checked: root.scope === "range"; onClicked: { root.scope = "range"; rangeField.forceActiveFocus() } }
            PTextField { id: rangeField; preferredWidth: 140; enabled: root.scope === "range"; label: I18n.tr("Seiten", I18n.revision); placeholderText: I18n.tr("z. B. 1-3, 5", I18n.revision) }
        }
    }
    PCheckBox {
        objectName: "cropReset"
        Layout.topMargin: 8
        Layout.fillWidth: true
        text: I18n.tr("Stattdessen den Zuschnitt zurücksetzen (ganze Seite zeigen)", I18n.revision)
        checked: root.reset
        onToggled: root.reset = checked
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 8
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Zugeschnitten wird die sichtbare Seite. Der Inhalt außerhalb bleibt in der Datei erhalten – zum Entfernen vertraulicher Inhalte »Schwärzen« verwenden.", I18n.revision)
    }
}
