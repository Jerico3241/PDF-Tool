import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Bekannten Kunden auswählen«: Suche (entprellt) und virtualisierte Liste der Kundenakten.
// Eingabe übernimmt den markierten Treffer, ↓ wechselt in die Liste.
ColumnLayout {
    id: root
    property var request: ({})
    property string chosen: ""
    readonly property bool acceptable: chosen !== ""
    readonly property bool handlesReturn: true
    function collect() { return { "id": chosen } }
    spacing: 8

    PTextField {
        id: search
        Layout.fillWidth: true
        visible: root.request.data ? root.request.data.search !== false : true
        label: "Kundenakten durchsuchen"
        placeholderText: "Firma, Kundennummer oder E-Mail suchen"
        text: Customers.pickerSearch
        focus: visible
        onTextEdited: Customers.pickerSearch = text
        Keys.onDownPressed: { list.forceActiveFocus(); list.currentIndex = 0 }
        Keys.onReturnPressed: (event) => {
            if (list.count > 0) {
                root.chosen = Customers.pickerModel.get(0).id
                Dialogs.answer(root.request.id, "primary", root.collect())
            }
            event.accepted = true
        }
        Component.onCompleted: if (visible) forceActiveFocus()
    }
    PText { text: Customers.pickerCount; textStyle: "caption"; tone: "secondary" }
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: Math.min(5, Math.max(1, list.count)) * 56 + 8
        radius: Metrics.radiusControl
        color: Theme.surface
        border.color: Theme.border
        ListView {
            id: list
            anchors.fill: parent
            anchors.margins: 4
            clip: true
            model: Customers.pickerModel
            reuseItems: true
            boundsBehavior: Flickable.StopAtBounds
            keyNavigationEnabled: true
            currentIndex: -1
            focus: !search.visible
            Accessible.role: Accessible.List
            Accessible.name: "Kundenakten"
            onCurrentIndexChanged: if (currentIndex >= 0) root.chosen = Customers.pickerModel.get(currentIndex).id
            Keys.onReturnPressed: (event) => { if (root.chosen !== "") Dialogs.answer(root.request.id, "primary", root.collect()); event.accepted = true }
            Keys.onEnterPressed: (event) => { if (root.chosen !== "") Dialogs.answer(root.request.id, "primary", root.collect()); event.accepted = true }
            T.ScrollBar.vertical: PScrollBar {}
            delegate: Item {
                id: row
                required property int index
                required property string id
                required property string company
                required property string subtitle
                required property string when
                width: list.width
                height: 56
                Accessible.role: Accessible.ListItem
                Accessible.name: company + ", " + subtitle
                PListItem {
                    anchors.fill: parent
                    anchors.margins: 2
                    hovered: mouse.containsMouse
                    pressed: mouse.pressed
                    selected: root.chosen === row.id
                    focused: list.activeFocus && list.currentIndex === row.index
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 12
                    spacing: 10
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        PText { text: row.company; textStyle: "bodyStrong"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                        PText { text: row.subtitle; textStyle: "caption"; tone: "secondary"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    }
                    PText { text: row.when; textStyle: "caption"; tone: "secondary" }
                }
                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: { list.currentIndex = row.index; root.chosen = row.id }
                    onDoubleClicked: { root.chosen = row.id; Dialogs.answer(root.request.id, "primary", root.collect()) }
                }
            }
        }
    }
}
