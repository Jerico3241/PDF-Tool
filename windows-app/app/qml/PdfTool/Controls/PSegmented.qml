import QtQuick
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style

// Segmente (seit 5.0 Beta 10, Entwurf 5): eine Auswahl aus wenigen Möglichkeiten nebeneinander in einer Schale – die
// gewählte mit Rand und Schrift im Akzent (Neon: leuchtend). Die Markierung gleitet zur gewählten Möglichkeit.
// ``model``: Liste aus {value, label}; ``current``: gewählter Wert.
Rectangle {
    id: root
    property var model: []
    property string current: ""
    property string label: ""
    signal activated(string value)

    implicitHeight: 36
    implicitWidth: row.implicitWidth + 8
    radius: Metrics.radiusControl + 4
    color: Theme.control
    border.color: Theme.controlStroke
    Accessible.role: Accessible.RadioButton
    Accessible.name: I18n.tr(label, I18n.revision)

    function indexOf(value) {
        for (var i = 0; i < model.length; ++i)
            if (model[i].value === value) return i
        return -1
    }
    readonly property Item currentItem: { row.children.length; var i = indexOf(current); return i >= 0 ? repeater.itemAt(i) : null }

    // gleitende Markierung
    Rectangle {
        id: marker
        visible: root.currentItem !== null
        x: root.currentItem ? row.x + root.currentItem.x : 0
        y: 4
        width: root.currentItem ? root.currentItem.width : 0
        height: root.height - 8
        radius: Metrics.radiusControl + 2
        color: Theme.pressedFill
        border.width: 1
        border.color: Theme.accent
        Behavior on x { enabled: Motion.moves; NumberAnimation { duration: Motion.indicator; easing.type: Motion.decelerate } }
        Behavior on width { enabled: Motion.moves; NumberAnimation { duration: Motion.indicator; easing.type: Motion.decelerate } }
        Repeater {
            model: Theme.glow > 0 ? 4 : 0
            Rectangle {
                required property int index
                x: -(index + 1); y: -(index + 1)
                width: marker.width + 2 * (index + 1); height: marker.height + 2 * (index + 1)
                radius: marker.radius + index + 1
                color: "transparent"
                border.width: 1
                border.color: Theme.accent
                opacity: 0.22 * Theme.glow * (1 - index / 4)
            }
        }
    }
    Row {
        id: row
        x: 4
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        Repeater {
            id: repeater
            model: root.model
            T.AbstractButton {
                id: option
                required property var modelData
                required property int index
                readonly property bool selected: root.current === modelData.value
                objectName: root.objectName + "_" + modelData.value
                implicitHeight: root.height - 8
                implicitWidth: label.implicitWidth + 28
                hoverEnabled: true
                focusPolicy: Qt.TabFocus
                Accessible.role: Accessible.RadioButton
                Accessible.name: I18n.tr(modelData.label, I18n.revision)
                Accessible.checked: selected
                onClicked: if (!selected) root.activated(modelData.value)
                Keys.onLeftPressed: if (index > 0) root.activated(root.model[index - 1].value)
                Keys.onRightPressed: if (index < root.model.length - 1) root.activated(root.model[index + 1].value)
                background: Rectangle {
                    radius: Metrics.radiusControl + 2
                    color: !option.selected && option.hovered ? Theme.subtleHover : "transparent"
                    PFocusRing { visible: option.visualFocus }
                }
                contentItem: Item {}
                Text {
                    id: label
                    anchors.centerIn: parent
                    text: I18n.tr(option.modelData.label, I18n.revision)
                    font: Typography.body
                    color: option.selected ? Theme.accent : Theme.textPrimary
                    textFormat: Text.PlainText
                    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
                }
            }
        }
    }
}
