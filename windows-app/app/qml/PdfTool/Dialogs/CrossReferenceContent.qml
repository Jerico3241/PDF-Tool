import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Querverweis einfügen (Texte, seit 5.0 Beta 5): Art des Ziels (Überschriften, Textmarken, Fuß- und Endnoten), das
// Ziel aus der Liste und was an der Schreibmarke erscheinen soll (Seitenzahl, Text, Nummer, »oben«/»unten«). Ändert
// sich das Ziel später, aktualisiert »Verzeichnisse aktualisieren« den Verweis.
ColumnLayout {
    id: root
    objectName: "crossReferenceContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    property string kind: ""
    property int chosen: -1
    readonly property var targets: data_.targets || []
    readonly property var shown: {
        var result = []
        for (var i = 0; i < targets.length; ++i)
            if (targets[i].kind === kind) result.push({ index: i, target: targets[i] })
        return result
    }
    readonly property var partList: (data_.parts || {})[kind] || []
    readonly property bool acceptable: chosen >= 0 && chosen < targets.length && targets[chosen].kind === kind
    readonly property bool handlesReturn: true
    function collect() { return { "target": chosen, "part": partList.length > 0 && partBox.currentIndex >= 0 ? partList[partBox.currentIndex].key : "" } }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var kinds = (request.data || {}).kinds || []
        kind = kinds.length > 0 ? kinds[0].key : ""
        chosen = -1
        partBox.currentIndex = 0
    }
    onKindChanged: { chosen = shown.length > 0 ? shown[0].index : -1; partBox.currentIndex = 0 }

    PFieldLabel { text: I18n.tr("Verweisen auf", I18n.revision); first: true }
    Flow {
        Layout.fillWidth: true
        spacing: 6
        Repeater {
            model: root.data_.kinds || []
            PButton {
                required property var modelData
                objectName: "crossReferenceKind_" + modelData.key
                text: I18n.tr(modelData.label, I18n.revision)
                toggle: true
                checked: root.kind === modelData.key
                onClicked: root.kind = modelData.key
            }
        }
    }
    PFieldLabel { text: I18n.tr("Ziel", I18n.revision) }
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 220
        radius: Metrics.radiusControl
        color: Theme.control
        border.color: Theme.controlStroke
        ListView {
            id: list
            objectName: "crossReferenceTargets"
            anchors.fill: parent
            anchors.margins: 4
            clip: true
            model: root.shown
            spacing: 1
            boundsBehavior: Flickable.StopAtBounds
            T.ScrollBar.vertical: PScrollBar {}
            PWheelScroll { flickable: list }
            delegate: T.ItemDelegate {
                id: item
                required property var modelData
                width: list.width
                implicitHeight: 32
                hoverEnabled: true
                Accessible.name: I18n.tr(modelData.target.label, I18n.revision)
                onClicked: root.chosen = modelData.index
                onDoubleClicked: { root.chosen = modelData.index; Dialogs.answer(root.request.id, "primary", root.collect()) }
                background: Rectangle {
                    radius: Metrics.radiusControl
                    color: root.chosen === item.modelData.index ? Theme.selectedSubtle : (item.hovered ? Theme.subtleHover : "transparent")
                }
                contentItem: RowLayout {
                    spacing: 6
                    Item { implicitWidth: 8 + Math.max(0, item.modelData.target.level - 1) * 16 }
                    PText {
                        visible: text !== ""
                        text: I18n.tr(item.modelData.target.number, I18n.revision)
                        tone: "secondary"
                    }
                    PText {
                        Layout.fillWidth: true
                        text: I18n.tr(item.modelData.target.label, I18n.revision)
                        elide: Text.ElideRight
                        font.weight: item.modelData.target.level === 1 ? Font.DemiBold : Font.Normal
                    }
                }
            }
        }
    }
    PFieldLabel { text: I18n.tr("Einfügen als", I18n.revision) }
    PComboBox {
        id: partBox
        objectName: "crossReferencePart"
        Layout.fillWidth: true
        label: I18n.tr("Einfügen als", I18n.revision)
        model: root.partList
        textRole: "label"
        displayText: I18n.tr(currentIndex >= 0 && currentIndex < root.partList.length ? root.partList[currentIndex].label : "", I18n.revision)
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 8
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Ändert sich die Seite oder der Text des Ziels, bringt »Referenzen › Aktualisieren« den Verweis auf den neuesten Stand.", I18n.revision)
    }
}
