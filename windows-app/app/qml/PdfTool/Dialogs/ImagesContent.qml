import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »PDF aus Bildern«: Reihenfolge der Bilder (jedes Bild eine Seite), Seitengröße und Rand. Fotos (JPEG) werden
// unverändert übernommen, die Ausrichtung aus der Kamera wird beachtet.
ColumnLayout {
    id: root
    objectName: "imagesContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    property var items: []
    property string pageSize: "auto"
    property string margin: "none"
    readonly property bool acceptable: items.length > 0
    function collect() { return { "order": items.map(function(item) { return item.path }), "pageSize": pageSize, "margin": margin } }
    function move(index, delta) {
        var target = index + delta
        if (target < 0 || target >= items.length) return
        var copy = items.slice()
        var item = copy.splice(index, 1)[0]
        copy.splice(target, 0, item)
        items = copy
    }
    function remove(index) {
        var copy = items.slice()
        copy.splice(index, 1)
        items = copy
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var data = request.data || {}
        items = (data.files || []).slice()
        pageSize = data.pageSize || "auto"
        margin = data.margin || "none"
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: "Jedes Bild wird eine Seite – in dieser Reihenfolge. Fotos behalten ihre Qualität, gedrehte Aufnahmen stehen richtig herum."
    }
    PFieldLabel { text: root.items.length === 1 ? "1 Bild" : root.items.length + " Bilder" }
    ListView {
        id: list
        objectName: "imagesList"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(contentHeight, 6 * (Metrics.controlHeight + 4))
        clip: true
        model: root.items
        boundsBehavior: Flickable.StopAtBounds
        T.ScrollBar.vertical: PScrollBar {}
        delegate: RowLayout {
            required property var modelData
            required property int index
            objectName: "imagesRow_" + index
            width: ListView.view.width
            height: Metrics.controlHeight + 4
            spacing: 4
            PText { text: (index + 1) + "."; tone: "tertiary"; Layout.preferredWidth: 28 }
            PIcon { name: "image"; size: 16 }
            PText { Layout.fillWidth: true; text: modelData.name; elide: Text.ElideMiddle }
            PIconButton { objectName: "imagesUp_" + index; iconName: "chevron_up"; tip: "Nach oben"; enabled: index > 0; onClicked: root.move(index, -1) }
            PIconButton { objectName: "imagesDown_" + index; iconName: "chevron_down"; tip: "Nach unten"; enabled: index < root.items.length - 1; onClicked: root.move(index, 1) }
            PIconButton { objectName: "imagesRemove_" + index; iconName: "dismiss"; tip: "Aus der Liste nehmen"; onClicked: root.remove(index) }
        }
    }
    PFieldLabel { text: "Seitengröße" }
    Repeater {
        model: [
            { "key": "auto", "label": "Wie das Bild" },
            { "key": "a4", "label": "A4 – Bild eingepasst (hoch oder quer wie das Bild)" },
            { "key": "letter", "label": "US Letter – Bild eingepasst" }
        ]
        PRadioButton {
            required property var modelData
            objectName: "imagesSize_" + modelData.key
            text: modelData.label
            checked: root.pageSize === modelData.key
            onClicked: root.pageSize = modelData.key
        }
    }
    PFieldLabel { text: "Rand" }
    RowLayout {
        spacing: 16
        Repeater {
            model: [{ "key": "none", "label": "Kein" }, { "key": "small", "label": "Schmal (5 mm)" }, { "key": "normal", "label": "Normal (10 mm)" }]
            PRadioButton {
                required property var modelData
                objectName: "imagesMargin_" + modelData.key
                text: modelData.label
                checked: root.margin === modelData.key
                onClicked: root.margin = modelData.key
            }
        }
    }
}
