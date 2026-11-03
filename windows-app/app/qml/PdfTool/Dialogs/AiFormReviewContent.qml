import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Vorschläge des Assistenten für ein PDF-Formular prüfen (seit 5.0 Beta 8): je Feld der bisherige und der neue Wert
// mit Kontrollkästchen. Nur angekreuzte Vorschläge werden eingetragen. ``data.items``: [{key, title, value, current,
// checked}].
ColumnLayout {
    id: root
    objectName: "aiFormReviewContent"
    property var request: ({})
    readonly property var items: (request.data || {}).items || []
    property var chosen: ({})
    readonly property int chosenCount: {
        var n = 0
        for (var i = 0; i < items.length; ++i) if (chosen[items[i].key]) n++
        return n
    }
    readonly property bool acceptable: chosenCount > 0
    function collect() {
        var keys = []
        for (var i = 0; i < items.length; ++i) if (chosen[items[i].key]) keys.push(items[i].key)
        return { "chosen": keys }
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var next = {}
        var list = (request.data || {}).items || []
        for (var i = 0; i < list.length; ++i) next[list[i].key] = list[i].checked !== false
        chosen = next
    }

    RowLayout {
        Layout.fillWidth: true
        PText {
            Layout.fillWidth: true
            wrap: true
            tone: "secondary"
            text: I18n.tr(root.chosenCount + " von " + root.items.length + " Vorschlägen gewählt. Bitte prüfen – die KI kann sich irren.", I18n.revision)
        }
        PButton {
            objectName: "aiFormReviewToggle"
            kind: "subtle"
            text: I18n.tr(root.chosenCount === root.items.length ? "Keine" : "Alle", I18n.revision)
            onClicked: {
                var all = root.chosenCount !== root.items.length
                var next = {}
                for (var i = 0; i < root.items.length; ++i) next[root.items[i].key] = all
                root.chosen = next
            }
        }
    }
    Flickable {
        id: list
        Layout.fillWidth: true
        Layout.topMargin: 8
        Layout.preferredHeight: Math.min(rows.implicitHeight, 360)
        contentHeight: rows.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        T.ScrollBar.vertical: PScrollBar {}
        ColumnLayout {
            id: rows
            width: list.width - 12
            spacing: 0
            Repeater {
                model: root.items
                Rectangle {
                    id: row
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    implicitHeight: line.implicitHeight + 12
                    color: index % 2 === 0 ? "transparent" : Theme.subtleHover
                    radius: Metrics.radiusControl
                    RowLayout {
                        id: line
                        x: 6
                        y: 6
                        width: parent.width - 12
                        spacing: 10
                        PCheckBox {
                            objectName: "aiFormReview_" + row.index
                            Layout.alignment: Qt.AlignTop
                            checked: root.chosen[row.modelData.key] === true
                            Accessible.name: I18n.tr(row.modelData.title, I18n.revision)
                            onToggled: {
                                var next = Object.assign({}, root.chosen)
                                next[row.modelData.key] = checked
                                root.chosen = next
                            }
                        }
                        PText {
                            Layout.preferredWidth: 180
                            Layout.alignment: Qt.AlignTop
                            text: I18n.tr(row.modelData.title, I18n.revision)
                            textStyle: "bodyStrong"
                            wrap: true
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            spacing: 2
                            PText { Layout.fillWidth: true; text: I18n.tr(row.modelData.value, I18n.revision); wrap: true }
                            PText {
                                Layout.fillWidth: true
                                visible: row.modelData.current !== ""
                                text: I18n.tr("bisher: ", I18n.revision) + row.modelData.current
                                textStyle: "caption"
                                tone: "secondary"
                                wrap: true
                            }
                        }
                    }
                }
            }
        }
    }
}
